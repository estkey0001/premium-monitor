"""初心者向け案件スキャナー。

Phase 9A: 商品ごとに買取価格を横断比較し、実利益を計算し、
beginner_easy / beginner_watch を判定してbeginner_dealsに保存する。
"""

import logging
from datetime import datetime
from typing import Optional

import ulid

from src.db.repository import Repository
from src.models.beginner_deal import BeginnerDealModel, DEFAULT_COSTS
from src.models.buyback_price import BuybackPriceModel, BUYBACK_SHOPS, CONDITION_LABELS
from src.models.product import ProductModel

logger = logging.getLogger(__name__)


class BeginnerDealScanner:
    """初心者向け案件のスキャン・利益計算を行う。"""

    def __init__(self, repository: Repository):
        self.repo = repository

    def scan_all(self, category: Optional[str] = None) -> list[BeginnerDealModel]:
        """全商品（またはカテゴリ）の初心者向け案件をスキャンする。"""
        products = self.repo.list_products()
        if category:
            products = [p for p in products if p.genre == category]

        deals = []
        for product in products:
            deal = self.scan_product(product)
            if deal:
                self.repo.upsert_beginner_deal(deal)
                deals.append(deal)

        deals.sort(key=lambda d: d.net_profit_jpy, reverse=True)
        return deals

    def scan_product(self, product: ProductModel) -> Optional[BeginnerDealModel]:
        """1商品の初心者向け案件をスキャンする。"""
        official = product.official_price or product.retail_price or 0
        if official <= 0:
            return None

        # 買取価格を収集（buyback_pricesテーブル + price_historyテーブル）
        buyback_list = self.repo.list_buyback_prices(product_id=product.id)

        # price_historyからもbuyback型を補完
        ph_buybacks = self.repo.list_price_history(
            product_id=product.id, price_type="buyback", limit=20
        )
        for ph in ph_buybacks:
            # 既にbuyback_pricesにある店舗は除外
            if not any(b.shop_id == ph.source_id for b in buyback_list):
                buyback_list.append(BuybackPriceModel(
                    id=ph.id,
                    product_id=product.id,
                    shop_id=ph.source_id,
                    shop_name=BUYBACK_SHOPS.get(ph.source_id, {}).get("name", ph.source_id),
                    buyback_price=ph.price,
                    condition="new_unopened",
                    buyback_url="",
                    observed_at=ph.recorded_at,
                ))

        if not buyback_list:
            return None

        # 最高買取を選択
        best = max(buyback_list, key=lambda b: b.buyback_price)
        if best.buyback_price <= official:
            # 買取 <= 定価 ならbeginner案件にならない
            return None

        # 実利益計算
        gross_profit = best.buyback_price - official
        costs = self._estimate_costs(product, official)
        net_profit = gross_profit - costs
        net_rate = round(net_profit / official, 4) if official > 0 else 0

        # beginner判定
        stock_status = product.official_stock_status or ""
        sale_method = "lottery" if product.is_lottery else (
            "discontinued" if product.is_discontinued else (
                "soldout" if "SOLD" in stock_status.upper() else "normal"
            )
        )
        difficulty = self._calc_difficulty(product, sale_method, stock_status)
        beginner_score = self._calc_beginner_score(
            official, best.buyback_price, sale_method, stock_status, product, net_profit
        )

        # user_level判定
        user_level, action = self._classify(
            sale_method, stock_status, difficulty, net_profit, gross_profit
        )

        # 公式URL
        official_url = self._get_official_url(product)

        return BeginnerDealModel(
            id=str(ulid.new()),
            product_id=product.id,
            product_name=product.name,
            category=product.genre,
            brand=product.brand,
            official_price_jpy=official,
            official_url=official_url,
            stock_status=stock_status,
            sale_method=sale_method,
            best_buyback_price=best.buyback_price,
            best_buyback_shop=best.shop_name or best.shop_id,
            best_buyback_url=best.buyback_url,
            buyback_condition=CONDITION_LABELS.get(best.condition, best.condition),
            gross_profit_jpy=gross_profit,
            estimated_costs_jpy=costs,
            net_profit_jpy=net_profit,
            net_profit_rate=net_rate,
            beginner_score=beginner_score,
            difficulty_score=difficulty,
            user_level=user_level,
            recommended_action=action,
            scanned_at=datetime.now(),
        )

    def compare_buyback(self, product: ProductModel) -> list[dict]:
        """1商品の買取価格を全店舗で比較する。"""
        official = product.official_price or product.retail_price or 0
        buyback_list = self.repo.list_buyback_prices(product_id=product.id)

        # price_historyからも補完
        ph_buybacks = self.repo.list_price_history(
            product_id=product.id, price_type="buyback", limit=20
        )
        seen_shops = {b.shop_id for b in buyback_list}
        for ph in ph_buybacks:
            if ph.source_id not in seen_shops:
                buyback_list.append(BuybackPriceModel(
                    id=ph.id, product_id=product.id,
                    shop_id=ph.source_id,
                    shop_name=BUYBACK_SHOPS.get(ph.source_id, {}).get("name", ph.source_id),
                    buyback_price=ph.price, condition="new_unopened",
                    buyback_url="", observed_at=ph.recorded_at,
                ))
                seen_shops.add(ph.source_id)

        results = []
        costs = self._estimate_costs(product, official) if official else 0
        for b in sorted(buyback_list, key=lambda x: x.buyback_price, reverse=True):
            gross = b.buyback_price - official if official else 0
            net = gross - costs if gross > 0 else 0
            results.append({
                "shop_id": b.shop_id,
                "shop_name": b.shop_name or b.shop_id,
                "buyback_price": b.buyback_price,
                "condition": CONDITION_LABELS.get(b.condition, b.condition),
                "url": b.buyback_url,
                "gross_profit": gross,
                "net_profit": net,
                "net_rate": round(net / official, 4) if official and net > 0 else 0,
                "observed_at": b.observed_at,
            })
        return results

    # ===== 利益計算 =====

    def _estimate_costs(self, product: ProductModel, official_price: int) -> int:
        """推定コストを計算する。"""
        c = DEFAULT_COSTS.copy()

        # Apple公式はクレカ手数料0%
        if product.brand == "Apple":
            c["cc_fee_rate"] = 0.0
        # 一般量販店はポイント考慮でクレカ0%想定
        c["cc_fee_rate"] = 0.0

        total = (
            c["shipping_jpy"]
            + c["transfer_fee_jpy"]
            + c["transport_jpy"]
            + c["insurance_jpy"]
            + int(official_price * c["cc_fee_rate"])
        )
        return total

    # ===== スコア計算 =====

    def _calc_difficulty(self, product, sale_method, stock_status) -> float:
        score = 0.0
        if sale_method == "lottery":
            score = 0.70
        elif sale_method == "soldout":
            score = 0.60
        elif sale_method == "discontinued":
            score = 0.80
        elif "お取り寄せ" in stock_status or "販売休止" in stock_status:
            score = 0.40

        if sale_method == "normal":
            score = max(score - 0.15, 0.0)

        name_lower = product.name.lower()
        if any(kw in name_lower for kw in ["monochrome", "limited", "限定"]):
            score += 0.15

        return round(min(1.0, score), 2)

    def _calc_beginner_score(self, official, buyback, sale_method, stock_status, product, net_profit) -> float:
        score = 0.0
        if official > 0:
            score += 0.15
        if sale_method == "normal":
            score += 0.25
            if not stock_status or "SOLD" not in stock_status.upper():
                score += 0.10
        if buyback and buyback > official:
            score += 0.15
        if net_profit >= 5000:
            score += 0.15
        if net_profit >= 20000:
            score += 0.10
        if product.brand in {"Apple", "Nintendo", "Sony"}:
            score += 0.10
        return round(min(1.0, score), 2)

    def _classify(self, sale_method, stock_status, difficulty, net_profit, gross_profit) -> tuple[str, str]:
        is_normal = sale_method == "normal"
        is_in_stock = "SOLD" not in (stock_status or "").upper()

        if is_normal and is_in_stock and net_profit >= 5000 and difficulty <= 0.35:
            return "beginner_easy", "check_official"
        if is_normal and net_profit >= 3000 and difficulty <= 0.50:
            return "beginner_watch", "check_buyback"
        if gross_profit >= 30000 and sale_method in ("lottery", "soldout", "discontinued"):
            return "advanced_high_profit", "lottery_only" if sale_method == "lottery" else "watch_price"
        if gross_profit >= 30000:
            return "advanced_high_profit", "watch_price"
        if net_profit > 0:
            return "beginner_watch", "watch_price"
        return "", "watch_price"

    def _get_official_url(self, product: ProductModel) -> str:
        """product_source_configsから公式URLを取得する。"""
        try:
            rows = self.repo.db.connection.execute(
                """SELECT target_url FROM product_source_configs
                   WHERE product_id = ? AND source_id LIKE 'src_apple%'
                   LIMIT 1""",
                (product.id,),
            ).fetchall()
            if rows:
                return rows[0]["target_url"]
        except Exception:
            pass

        # Apple製品のデフォルト
        if product.brand == "Apple":
            return "https://www.apple.com/jp/shop/"
        return ""

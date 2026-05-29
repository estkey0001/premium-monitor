"""初心者向け案件スキャナー。

Phase 9A: 商品ごとに買取価格を横断比較し、実利益を計算し、
beginner_easy / beginner_watch を判定してbeginner_dealsに保存する。
"""

import json
import logging
import statistics
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
                # monitoring / fetch_failed / 利益あり → upsert して表示
                self.repo.upsert_beginner_deal(deal)
                deals.append(deal)
            else:
                # scan_product が None を返した場合: 全店舗 fetch_failed のみか確認
                # fetch_failed / product_not_listed のみの場合は既存 deal を保持する
                all_prices = self.repo.list_buyback_prices_by_product(product.id, limit=30)
                valid_prices = [
                    p for p in all_prices
                    if p.get("data_source") not in ("fetch_failed", "product_not_listed")
                    and (p.get("buyback_price") or 0) > 0
                ]
                if all_prices and not valid_prices:
                    # 全店舗 fetch_failed → 既存 deal を維持（deactivate しない）
                    logger.info(
                        "[%s] 全店舗 fetch_failed のみ — 既存 deal を保持してスキップ",
                        product.id,
                    )
                    continue
                # データなし（buyback_list が空 or official_price なし）→ 非アクティブ化
                self.repo.deactivate_beginner_deal(product.id)

        deals.sort(key=lambda d: d.net_profit_jpy, reverse=True)
        return deals

    def scan_product(self, product: ProductModel) -> Optional[BeginnerDealModel]:
        """1商品の初心者向け案件をスキャンする。"""
        official = product.official_price or product.retail_price or 0
        if official <= 0:
            return None

        # 各ショップの最新1行のみ取得（fetch_failed も含む）
        # list_buyback_prices（全行）ではなく list_buyback_prices_by_product（MAX observed_at）を使い
        # 古い manual_today が fetch_failed を上書きしないようにする
        _bp_dicts = self.repo.list_buyback_prices_by_product(product_id=product.id, limit=20)
        buyback_list = []
        for _d in _bp_dicts:
            _obs_str = _d.get('observed_at', '')
            try:
                _obs_dt = datetime.fromisoformat(str(_obs_str)) if _obs_str else datetime.now()
            except Exception:
                _obs_dt = datetime.now()
            buyback_list.append(BuybackPriceModel(
                id=f"scan_{_d['shop_id']}",
                product_id=product.id,
                shop_id=_d.get('shop_id', ''),
                shop_name=_d.get('shop_name', ''),
                buyback_price=_d.get('buyback_price', 0),
                condition=_d.get('condition', 'new_unopened'),
                buyback_url=_d.get('buyback_url', ''),
                observed_at=_obs_dt,
                data_source=_d.get('data_source', 'manual_today'),
                link_verified=bool(_d.get('link_verified', False)),
            ))

        if not buyback_list:
            return None

        # ── 二次流通（resale_market）価格を早期チェック ──
        # all_failed 判定より先に sale_prices を確認し、有効な二次流通価格があれば
        # fetch_failed 早期リターンをバイパスする（カメラ系：買取店全滅でも二次流通あり）
        _RESALE_NEW_CONDITIONS = {'new_unopened', 'new_unopened_simfree', 'new', 'unused'}
        _resale_precheck: list = []
        try:
            _sp_rows_pre = self.repo.list_sale_prices(product_id=product.id, active_only=True, limit=30)
            for _sp_pre in _sp_rows_pre:
                _sp_cond_pre = (getattr(_sp_pre, 'condition', '') or '').strip()
                if _sp_cond_pre not in _RESALE_NEW_CONDITIONS:
                    continue
                if not _sp_pre.sale_price or _sp_pre.sale_price <= 0:
                    continue
                _sp_shop_pre = _sp_pre.shop_name or _sp_pre.shop_id or 'secondary_market'
                _sp_sid_pre = f"resale_{(_sp_shop_pre or '').replace(' ', '_')[:24]}"
                _obs_pre = _sp_pre.observed_at if _sp_pre.observed_at else datetime.now()
                _resale_precheck.append(BuybackPriceModel(
                    id=f"resale_{_sp_pre.id[:20]}",
                    product_id=product.id,
                    shop_id=_sp_sid_pre,
                    shop_name=_sp_shop_pre,
                    buyback_price=_sp_pre.sale_price,
                    condition='new_unopened',
                    buyback_url=_sp_pre.url or '',
                    observed_at=_obs_pre,
                    data_source='resale_market',
                    link_verified=bool(getattr(_sp_pre, 'link_verified', False)),
                ))
        except Exception as _e_pre:
            logger.debug("[%s] sale_prices 早期チェック エラー（スキップ）: %s", product.id, _e_pre)

        # 全店舗が fetch_failed → user_level="fetch_failed" で返す（Noneにしない）
        # ただし、有効な二次流通価格（resale_market）が存在する場合はバイパスして処理継続
        all_failed = all(
            getattr(b, 'data_source', '') == 'fetch_failed' or b.buyback_price == 0
            for b in buyback_list
        )
        if all_failed and not _resale_precheck:
            # 買取店全滅 かつ 二次流通価格もなし → fetch_failed
            official_url = self._get_official_url(product)
            return BeginnerDealModel(
                id=str(ulid.new()),
                product_id=product.id,
                product_name=product.name,
                category=product.genre or "",
                brand=getattr(product, 'brand', '') or "",
                official_price_jpy=official,
                official_url=official_url,
                stock_status="",
                sale_method="normal",
                best_buyback_price=0,
                best_buyback_shop="",
                best_buyback_url="",
                buyback_condition="",
                gross_profit_jpy=0,
                estimated_costs_jpy=0,
                net_profit_jpy=0,
                net_profit_rate=0.0,
                beginner_score=0.0,
                difficulty_score=100.0,
                user_level="fetch_failed",
                recommended_action="取得失敗 / 要確認",
                is_active=True,
                scanned_at=datetime.now(),
                notes="全店舗価格取得失敗",
            )
        # 買取店全滅でも二次流通価格あり → valid_buybacks を二次流通で代替して処理続行
        if all_failed and _resale_precheck:
            logger.info(
                "[%s] 買取店全滅だが二次流通価格あり（%d件）→ scan 続行",
                product.id, len(_resale_precheck),
            )

        # fetch_failed (price=0) は価格計算から完全除外
        # auto_scraped が有効（price>0）な店舗を優先取得
        auto_valid = [
            b for b in buyback_list
            if b.buyback_price > 0 and getattr(b, "data_source", "") == "auto_scraped"
        ]
        # manual_today / manual_confirmed フォールバック候補
        manual_valid = [
            b for b in buyback_list
            if b.buyback_price > 0
            and getattr(b, "data_source", "") in ("manual_today", "manual_confirmed")
        ]
        # auto_scraped が全店舗取得失敗または存在しない場合は手動データを使用
        if auto_valid:
            # auto_scraped 優先。auto がない店舗のみ manual を補完
            auto_shop_ids = {b.shop_id for b in auto_valid}
            valid_buybacks = auto_valid + [
                m for m in manual_valid if m.shop_id not in auto_shop_ids
            ]
        else:
            # auto_scraped が使えない → manual_today / manual_confirmed で代替
            valid_buybacks = manual_valid
            if not valid_buybacks:
                # それも無ければ fetch_failed / product_not_listed 以外の全有効データ
                valid_buybacks = [
                    b for b in buyback_list
                    if b.buyback_price > 0
                    and getattr(b, "data_source", "") not in ("fetch_failed", "product_not_listed")
                ]
        # ── 二次流通（resale_market）価格を追加候補として追加 ──
        # 早期チェック（_resale_precheck）で取得済みの二次流通価格を valid_buybacks に追加する。
        # 二重取得を避けるため、すでにチェック済みの _resale_precheck をそのまま利用する。
        try:
            if _resale_precheck:
                valid_buybacks.extend(_resale_precheck)
        except Exception as _e:
            logger.debug("[%s] resale_precheck 注入エラー（スキップ）: %s", product.id, _e)
        except Exception as _e:
            logger.debug("[%s] sale_prices 取得エラー（スキップ）: %s", product.id, _e)

        if not valid_buybacks:
            return None

        # 店舗ごとに重複排除: 優先順位 = auto_scraped > 最新 observed_at
        shop_best: dict[str, BuybackPriceModel] = {}
        for b in valid_buybacks:
            sid = b.shop_id or b.shop_name or "unknown"
            if sid not in shop_best:
                shop_best[sid] = b
            else:
                existing = shop_best[sid]
                b_is_auto = getattr(b, "data_source", "") == "auto_scraped"
                e_is_auto = getattr(existing, "data_source", "") == "auto_scraped"
                b_time = b.observed_at if b.observed_at else datetime.min
                e_time = existing.observed_at if existing.observed_at else datetime.min
                # auto_scraped が優先。同じ data_source ならより新しい observed_at を採用
                if b_is_auto and not e_is_auto:
                    shop_best[sid] = b
                elif not b_is_auto and e_is_auto:
                    pass  # 既存の auto_scraped を維持
                elif b_time > e_time:
                    shop_best[sid] = b
        deduped = sorted(shop_best.values(), key=lambda b: b.buyback_price, reverse=True)

        # 最高買取を選択
        best = deduped[0]
        # ※ 買取 <= 定価（赤字）でも monitoring として表示するため None にしない

        # 複数店舗統計計算
        prices_sorted = [b.buyback_price for b in deduped]
        shop_count = len(prices_sorted)
        median_price = int(statistics.median(prices_sorted)) if prices_sorted else None

        # 上位5店舗をJSONで保存
        top5 = deduped[:5]
        prices_json = json.dumps([
            {
                "shop_id": b.shop_id,
                "shop_name": b.shop_name or b.shop_id,
                "price": b.buyback_price,
                "url": b.buyback_url or "",
                "link_verified": bool(getattr(b, "link_verified", False)),
                "data_source": getattr(b, "data_source", "manual_today"),
            }
            for b in top5
        ], ensure_ascii=False)

        # 最高値店舗のlink_verified
        best_link_verified = bool(getattr(best, "link_verified", False))
        # link_verified=falseのURLはリンク表示しない
        best_url = best.buyback_url if best_link_verified else ""

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

        # 赤字（net_profit <= 0）は monitoring として表示
        if net_profit <= 0 and user_level == "":
            user_level = "monitoring"
            action = "取得失敗 / 要確認" if action == "" else action

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
            best_buyback_url=best_url,
            best_link_verified=best_link_verified,
            buyback_condition=CONDITION_LABELS.get(best.condition, best.condition),
            median_buyback_price=median_price,
            buyback_shop_count=shop_count,
            buyback_prices_json=prices_json,
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

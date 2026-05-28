"""一次流通仕入れ → 二次流通販売 利益計算スキャナー (PHASE 2)。

公式・正規一次販売店で定価購入した新品・未使用品を
海外eBay・国内メルカリ等の二次流通市場で売却した場合の差益を計算する。

利益計算:
  gross_profit = overseas_sell_price - official_price
  total_costs = platform_fee(13%) + intl_shipping(3000) + packaging(500)
  net_profit = gross_profit - total_costs
  profit_rate = net_profit / official_price
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import ulid

from src.db.repository import Repository
from src.models.beginner_deal import BeginnerDealModel
from src.models.product import ProductModel

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# 海外プラットフォーム手数料・コスト
EBAY_SELLER_FEE_RATE = 0.13      # eBay seller fee ~13%
INTL_SHIPPING_JPY = 3000          # 国際送料
PACKAGING_JPY = 500               # 梱包費・資材
TOTAL_FIXED_COSTS = INTL_SHIPPING_JPY + PACKAGING_JPY  # 3500

# 利益閾値
PROFIT_EASY_MIN_JPY = 15000       # beginner_easy: 差益¥15,000以上
PROFIT_WATCH_MIN_JPY = 5000       # beginner_watch: 差益¥5,000以上

# Confidence フィルタ
VALID_CONFIDENCE = {"high", "medium"}


class PrimaryToSecondaryScanner:
    """公式購入 → 海外/二次流通販売 の利益計算スキャナー。

    一次流通(公式) → 二次流通(eBay等) の利益計算。
    condition_filter.py で新品・未使用のみを対象とする。
    """

    def __init__(self, repository: Repository):
        self.repo = repository
        self._overseas_cache: Optional[dict] = None

    def scan_all(self) -> list[BeginnerDealModel]:
        """全商品をスキャンして利益案件リストを返す。"""
        overseas = self._load_overseas_prices()
        products = self.repo.list_products()

        deals = []
        for product in products:
            deal = self.scan_product(product, overseas)
            if deal:
                # DBに保存 (user_level が beginner_easy/watch/monitoring)
                self.repo.upsert_beginner_deal(deal)
                deals.append(deal)

        deals.sort(key=lambda d: d.net_profit_jpy, reverse=True)
        logger.info(
            "PrimaryToSecondaryScanner: %d products → %d deals "
            "(easy=%d, watch=%d, monitoring=%d)",
            len(products), len(deals),
            sum(1 for d in deals if d.user_level == "beginner_easy"),
            sum(1 for d in deals if d.user_level == "beginner_watch"),
            sum(1 for d in deals if d.user_level == "monitoring"),
        )
        return deals

    def scan_product(
        self, product: ProductModel, overseas: dict
    ) -> Optional[BeginnerDealModel]:
        """1商品の一次→二次利益をスキャンする。"""
        official = product.official_price or product.retail_price or 0
        if official <= 0:
            return None

        alias = product.id.replace("prod_", "")

        # 海外価格取得 (by product_id or alias)
        ovs = overseas.get(product.id) or overseas.get(alias)

        if not ovs:
            # 海外価格データなし → monitoring で保存
            return self._make_monitoring(
                product, official, 0, "overseas_price_not_fetched"
            )

        ovs_price_jpy = ovs.get("price_jpy", 0)
        confidence = ovs.get("confidence", "low")
        listing_count = ovs.get("listing_count", 0)
        stale = ovs.get("stale", False)

        # confidence low または stale → monitoring
        if confidence not in VALID_CONFIDENCE:
            return self._make_monitoring(
                product, official, ovs_price_jpy,
                f"confidence_low_skip (count={listing_count})"
            )
        if stale:
            return self._make_monitoring(
                product, official, ovs_price_jpy, "stale_data"
            )
        if ovs_price_jpy <= 0:
            return self._make_monitoring(
                product, official, 0, "overseas_price_zero"
            )

        # 利益計算
        platform_fee = int(ovs_price_jpy * EBAY_SELLER_FEE_RATE)
        total_costs = platform_fee + TOTAL_FIXED_COSTS
        gross_profit = ovs_price_jpy - official
        net_profit = gross_profit - total_costs
        profit_rate = net_profit / official if official > 0 else 0.0

        # user_level 判定
        if net_profit >= PROFIT_EASY_MIN_JPY:
            user_level = "beginner_easy"
            recommended_action = "購入検討 → eBay出品"
        elif net_profit >= PROFIT_WATCH_MIN_JPY:
            user_level = "beginner_watch"
            recommended_action = "様子見 → 価格変動を監視"
        elif net_profit > 0:
            user_level = "beginner_watch"
            recommended_action = "利益小 → 送料・手数料に注意"
        else:
            return self._make_monitoring(
                product, official, ovs_price_jpy,
                f"negative_profit (net={net_profit:,})"
            )

        notes = (
            f"海外価格:¥{ovs_price_jpy:,} ({ovs.get('market','eBay')}) "
            f"conf={confidence} "
            f"件数={listing_count} "
            f"platform_fee=¥{platform_fee:,} "
            f"route=primary_to_secondary"
        )
        if stale:
            notes += " [STALE]"

        logger.info(
            "[%s] %s official=¥%s overseas=¥%s net=¥%s rate=%.1f%% level=%s",
            alias, product.name,
            f"{official:,}", f"{ovs_price_jpy:,}",
            f"{net_profit:,}", profit_rate * 100, user_level
        )

        return BeginnerDealModel(
            id=str(ulid.new()),
            product_id=product.id,
            product_name=product.name,
            category=product.genre or "",
            brand=getattr(product, "brand", "") or "",
            official_price_jpy=official,
            official_url=self._get_official_url(product),
            stock_status="",
            sale_method="normal",
            best_buyback_price=ovs_price_jpy,     # 海外売却価格をbest_buybackとして保存
            best_buyback_shop=ovs.get("market", "eBay"),
            best_buyback_url=ovs.get("url", ""),
            best_link_verified=True,
            buyback_condition="new",
            median_buyback_price=ovs.get("median_price_jpy", ovs_price_jpy),
            buyback_shop_count=ovs.get("listing_count", 1),
            buyback_prices_json=json.dumps({
                "overseas": ovs_price_jpy,
                "market": ovs.get("market", "eBay"),
                "confidence": confidence,
                "listing_count": listing_count,
                "min_jpy": ovs.get("min_price_jpy", 0),
                "max_jpy": ovs.get("max_price_jpy", 0),
                "median_jpy": ovs.get("median_price_jpy", ovs_price_jpy),
                "route_type": "primary_to_secondary",
            }),
            gross_profit_jpy=gross_profit,
            estimated_costs_jpy=total_costs,
            net_profit_jpy=net_profit,
            net_profit_rate=profit_rate,
            beginner_score=min(100.0, max(0.0, profit_rate * 100 * 2)),
            difficulty_score=max(0.0, min(100.0, 50 - profit_rate * 200)),
            user_level=user_level,
            recommended_action=recommended_action,
            is_active=True,
            scanned_at=datetime.now(),
            notes=notes,
        )

    def _make_monitoring(
        self, product: ProductModel, official: int,
        overseas_jpy: int, reason: str
    ) -> BeginnerDealModel:
        """監視中(赤字・低信頼度)の deal を生成する。"""
        estimated_costs = int(overseas_jpy * EBAY_SELLER_FEE_RATE) + TOTAL_FIXED_COSTS if overseas_jpy > 0 else TOTAL_FIXED_COSTS
        net = overseas_jpy - official - estimated_costs if overseas_jpy > 0 else -official
        return BeginnerDealModel(
            id=str(ulid.new()),
            product_id=product.id,
            product_name=product.name,
            category=product.genre or "",
            brand=getattr(product, "brand", "") or "",
            official_price_jpy=official,
            official_url=self._get_official_url(product),
            stock_status="",
            sale_method="normal",
            best_buyback_price=overseas_jpy,
            best_buyback_shop="eBay",
            best_buyback_url="",
            buyback_condition="new",
            median_buyback_price=overseas_jpy,
            buyback_shop_count=0,
            buyback_prices_json=json.dumps({"route_type": "primary_to_secondary", "reason": reason}),
            gross_profit_jpy=overseas_jpy - official if overseas_jpy > 0 else 0,
            estimated_costs_jpy=estimated_costs,
            net_profit_jpy=net,
            net_profit_rate=net / official if official > 0 else 0.0,
            beginner_score=0.0,
            difficulty_score=100.0,
            user_level="monitoring",
            recommended_action=f"監視中 / {reason}",
            is_active=True,
            scanned_at=datetime.now(),
            notes=f"route=primary_to_secondary reason={reason}",
        )

    def _get_official_url(self, product: ProductModel) -> str:
        """公式購入URLを取得する。"""
        genre = getattr(product, "genre", "") or ""
        if genre == "iphone" or "apple" in product.name.lower():
            return f"https://www.apple.com/jp/shop/buy-iphone"
        if genre == "pc" and "mac" in product.name.lower():
            return f"https://www.apple.com/jp/shop/buy-mac"
        if genre == "game_console":
            if "switch" in product.name.lower():
                return "https://store.nintendo.co.jp/"
            if "ps5" in product.name.lower():
                return "https://direct.playstation.com/ja-jp/"
        if genre == "camera":
            if "ricoh" in product.name.lower():
                return "https://www.ricoh-imaging.co.jp/"
            if "fujifilm" in product.name.lower():
                return "https://fujifilm-x.com/ja-jp/"
        return ""

    def _load_overseas_prices(self) -> dict:
        """exports/overseas_prices/latest.json から海外価格データを読み込む。

        Returns:
            {product_id_or_alias: price_dict} の辞書
        """
        if self._overseas_cache is not None:
            return self._overseas_cache

        json_path = PROJECT_ROOT / "exports" / "overseas_prices" / "latest.json"
        if not json_path.exists():
            logger.warning("overseas_prices/latest.json not found")
            self._overseas_cache = {}
            return {}

        try:
            with open(json_path, encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("Failed to load overseas_prices/latest.json: %s", e)
            self._overseas_cache = {}
            return {}

        # by_product から読み込む
        by_product = data.get("by_product", {})
        result = {}
        for alias, entry in by_product.items():
            # alias → product_id マッピング
            product_id = f"prod_{alias}"
            result[alias] = entry
            result[product_id] = entry

        self._overseas_cache = result
        return result

"""せどりルート計算エンジン (Phase 14/15)。

sale_prices（仕入れ候補）と buyback_prices（売却先）を組み合わせて
全ルートを計算し、sedori_routesテーブルに保存する。

計算式:
  gross_profit = sell_price - buy_price
  estimated_costs = shipping_fee + transfer_fee + travel_fee + other_costs
  net_profit = gross_profit - estimated_costs
  profit_rate = net_profit / buy_price
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

import ulid

from src.db.repository import Repository
from src.models.sale_price import SedoriRouteModel
from src.market.normalized_prices import (
    build_observations, pro_buy_options, pro_sell_options,
)

logger = logging.getLogger(__name__)

# デフォルトコスト（変更可能）
DEFAULT_SHIPPING_FEE = 1000   # 送料
DEFAULT_TRANSFER_FEE = 300    # 振込手数料
DEFAULT_TRAVEL_FEE   = 500    # 交通費
DEFAULT_OTHER_COSTS  = 0      # その他


class SedoriRouteCalculator:
    """仕入れ→売却の全ルートを計算して保存する。"""

    def __init__(
        self,
        repository: Repository,
        shipping_fee: int = DEFAULT_SHIPPING_FEE,
        transfer_fee: int = DEFAULT_TRANSFER_FEE,
        travel_fee: int = DEFAULT_TRAVEL_FEE,
        other_costs: int = DEFAULT_OTHER_COSTS,
    ):
        self.repo = repository
        self.shipping_fee = shipping_fee
        self.transfer_fee = transfer_fee
        self.travel_fee = travel_fee
        self.other_costs = other_costs

    @property
    def estimated_costs(self) -> int:
        return self.shipping_fee + self.transfer_fee + self.travel_fee + self.other_costs

    def _load_observations(self) -> list[dict]:
        """正規化価格観測を構築する（唯一の入力源）。

        now は build_observations 側で JST aware（datetime.now(tz=JST)）が
        デフォルト適用される。naive を渡すと _age_days のタイムゾーン比較で
        例外→全 stale 扱いになるため、ここでは明示的に渡さない。
        """
        try:
            return build_observations(self.repo.db.connection)
        except Exception as e:
            logger.warning("normalized observations build failed: %s", e)
            return []

    def calculate_all(self) -> dict:
        """全商品のせどりルートを計算して保存する。"""
        products = self.repo.list_products()
        total_saved = 0
        total_routes = 0
        results_by_product = {}
        obs = self._load_observations()

        for product in products:
            alias = product.id.replace("prod_", "")
            routes = self._calculate_for_product(product.id, product.name, alias, obs)
            total_routes += len(routes)
            saved = self._save_routes(alias, routes)
            total_saved += saved
            if routes:
                results_by_product[alias] = {
                    "product_name": product.name,
                    "route_count": len(routes),
                    "best_net_profit": routes[0].net_profit if routes else 0,
                }

        logger.info(
            "SedoriRouteCalculator: %d products, %d routes calculated, %d saved",
            len(products), total_routes, total_saved,
        )
        return {
            "products_scanned": len(products),
            "total_routes": total_routes,
            "routes_saved": total_saved,
            "by_product": results_by_product,
        }

    def calculate_for_alias(self, product_alias: str) -> list[SedoriRouteModel]:
        """指定商品のせどりルートを計算して保存する。"""
        # product_id を解決
        product_id = f"prod_{product_alias}"
        product = self.repo.get_product(product_id)
        product_name = product.name if product else product_alias

        obs = self._load_observations()
        routes = self._calculate_for_product(product_id, product_name, product_alias, obs)
        self._save_routes(product_alias, routes)
        return routes

    def _calculate_for_product(
        self,
        product_id: str,
        product_name: str,
        product_alias: str,
        obs: list[dict],
    ) -> list[SedoriRouteModel]:
        """商品の全ルートを計算する（保存はしない）。

        仕入れ・売却の双方を normalized_price_observations（唯一の入力源）から取得する。
        - buy:  price_role=buy（shop_sale / flea_listing / flea_sold / overseas_listing）
        - sell: price_role=sell（buyback / overseas_sold）
        これにより buyback を仕入れに使う・sale/listing を売却に使う等の混同は構造的に排除される。
        trade_in / price=0 / stale / unknown condition も is_usable_for_pro=False で除外済み。
        """
        def _parse_dt(s):
            try:
                d = datetime.fromisoformat(str(s))
                return d.replace(tzinfo=None) if d.tzinfo else d
            except Exception:
                return datetime.now()

        # ソースごとに最良の1件に集約（仕入れ=最安, 売却=最高）
        _buy_by_src: dict = {}
        for o in pro_buy_options(obs, product_id):  # 安い順
            key = o["source_id"] or o["source_name"]
            if key not in _buy_by_src:
                _buy_by_src[key] = o  # 安い順なので先勝ち=最安
        _sell_by_src: dict = {}
        for o in pro_sell_options(obs, product_id):  # 高い順
            key = o["source_id"] or o["source_name"]
            if key not in _sell_by_src:
                _sell_by_src[key] = o  # 高い順なので先勝ち=最高
        buy_opts = list(_buy_by_src.values())
        sell_opts = list(_sell_by_src.values())

        if not buy_opts or not sell_opts:
            return []

        routes: list[SedoriRouteModel] = []

        for b in buy_opts:
            for s in sell_opts:
                # 同一ソースはスキップ
                if b["source_id"] and b["source_id"] == s["source_id"]:
                    continue

                buy_price = int(b["price"])
                sell_price = int(s["price"])
                gross_profit = sell_price - buy_price
                if gross_profit <= 0:
                    continue
                net_profit = gross_profit - self.estimated_costs
                if net_profit <= 0:
                    continue
                profit_rate = net_profit / buy_price if buy_price > 0 else 0.0

                route = SedoriRouteModel(
                    id=str(ulid.new()),
                    product_id=product_id,
                    product_name=product_name,
                    product_alias=product_alias,
                    buy_shop_name=b["source_name"],
                    buy_shop_id=b["source_id"],
                    buy_price=buy_price,
                    buy_url=b["item_url"] or b["source_url"],
                    buy_condition=b["condition"],
                    buy_price_type=b["price_type"],
                    buy_source=b["source_id"],
                    sell_shop_name=s["source_name"],
                    sell_shop_id=s["source_id"],
                    sell_price=sell_price,
                    sell_url=s["item_url"] or s["source_url"],
                    sell_price_type=s["price_type"],
                    sell_source=s["source_id"],
                    gross_profit=gross_profit,
                    shipping_fee=self.shipping_fee,
                    transfer_fee=self.transfer_fee,
                    travel_fee=self.travel_fee,
                    other_costs=self.other_costs,
                    estimated_costs=self.estimated_costs,
                    net_profit=net_profit,
                    profit_rate=profit_rate,
                    rank=0,  # 後でランク付け
                    calculated_at=datetime.now(),
                )
                # 品質チェック用メタデータ（DBには保存しない一時属性）
                route._buy_observed_at = _parse_dt(b["observed_at"])
                route._buy_link_verified = (b["link_type"] == "item")
                route._sell_observed_at = _parse_dt(s["observed_at"])
                route._sell_link_verified = (s["link_type"] == "item")
                route._sell_condition = s["condition"]
                routes.append(route)

        # 品質スコア計算
        for route in routes:
            quality_score, warning_flags, needs_review = self._calculate_quality(route)
            route.route_quality_score = quality_score
            route.route_warning_flags = warning_flags
            route.needs_review = needs_review
            route.sort_score = route.net_profit * quality_score

        # sort_score降順でソートしてランク付け（品質調整済み）
        routes.sort(key=lambda r: r.sort_score, reverse=True)
        for i, r in enumerate(routes, start=1):
            r.rank = i

        return routes

    def _calculate_quality(
        self,
        route: "SedoriRouteModel",
    ) -> tuple[float, list[str], bool]:
        """ルートの品質スコア・警告フラグ・要確認フラグを計算する。

        Returns:
            (quality_score, warning_flags, needs_review)
            quality_score: 0.0〜1.0 (高いほど信頼性が高い)
        """
        flags: list[str] = []
        score = 1.0

        # --- 条件ズレチェック (weight: 0.25) ---
        # 仕入れ条件と売却先の条件が明らかに不整合（中古を新品として売れない）
        buy_cond = (route.buy_condition or "").lower()
        sell_cond = getattr(route, "_sell_condition", "").lower()
        condition_mismatch = False
        # 仕入れが中古なのに売却先が新品価格（buy=used_*, sell=new_unopened）の場合
        if buy_cond.startswith("used") and sell_cond in ("new_unopened", "new_unopened_simfree", "new_opened"):
            condition_mismatch = True
            flags.append("condition_mismatch")
            score -= 0.25
        elif buy_cond.startswith("used") and sell_cond == "":
            # 売却先の条件が未定義の場合は警告（明確なズレとはしない）
            flags.append("sell_condition_unknown")
            score -= 0.05

        # --- 仕入れ価格の鮮度チェック (weight: 0.20) ---
        def _age_days(dt) -> int:
            """datetime の経過日数を返す（タイムゾーン対応）。"""
            if dt is None:
                return 0
            now = datetime.now()
            # tzinfo がある場合はstrip（naive同士で比較）
            if hasattr(dt, "tzinfo") and dt.tzinfo is not None:
                dt = dt.replace(tzinfo=None)
            try:
                return (now - dt).days
            except Exception:
                return 0

        stale_sale_price = False
        if hasattr(route, "_buy_observed_at") and route._buy_observed_at:
            if _age_days(route._buy_observed_at) > 7:
                stale_sale_price = True
                flags.append("stale_sale_price")
                score -= 0.20

        # --- 買取価格の鮮度チェック (weight: 0.20) ---
        stale_buyback_price = False
        if hasattr(route, "_sell_observed_at") and route._sell_observed_at:
            if _age_days(route._sell_observed_at) > 7:
                stale_buyback_price = True
                flags.append("stale_buyback_price")
                score -= 0.20

        # --- 仕入れURLの検証チェック (weight: 0.10) ---
        unverified_buy_url = False
        if hasattr(route, "_buy_link_verified") and not route._buy_link_verified:
            unverified_buy_url = True
            flags.append("unverified_buy_url")
            score -= 0.10

        # --- 売却URLの検証チェック (weight: 0.10) ---
        unverified_sell_url = False
        if hasattr(route, "_sell_link_verified") and not route._sell_link_verified:
            unverified_sell_url = True
            flags.append("unverified_sell_url")
            score -= 0.10

        # --- 利益率の異常チェック (weight: 0.15) ---
        abnormal_profit_rate = False
        if route.profit_rate >= 0.50:
            # 50%以上は異常値の可能性が高い
            abnormal_profit_rate = True
            flags.append("abnormal_profit_rate")
            score -= 0.15
        elif route.profit_rate >= 0.20:
            # 20-50%は要注意（ペナルティ小）
            score -= 0.06

        # --- 買取上限チェック (weight: 0.10) ---
        # 仕入れ価格の2倍以上の買取価格は上限設定ミスの可能性
        upper_limit_buyback = False
        if route.buy_price > 0 and route.sell_price >= route.buy_price * 2.0:
            upper_limit_buyback = True
            flags.append("upper_limit_buyback")
            score -= 0.10

        # --- モデルミスマッチ疑惑チェック ---
        # 同一カテゴリでも大幅に異なる価格帯（net_profit > 200,000円）
        if route.net_profit >= 200_000:
            flags.append("possible_model_mismatch")
            score -= 0.10

        # スコアを0.0〜1.0にクランプ
        score = max(0.0, min(1.0, score))

        # --- 要確認フラグの判定 ---
        needs_review = (
            route.profit_rate >= 0.50
            or route.net_profit >= 100_000
            or condition_mismatch
            or (stale_sale_price and stale_buyback_price)
            or (unverified_buy_url and unverified_sell_url)
            or upper_limit_buyback
        )

        return score, flags, needs_review

    def _save_routes(self, product_alias: str, routes: list[SedoriRouteModel]) -> int:
        """計算済みルートを保存する（既存分を削除してから保存）。"""
        self.repo.delete_sedori_routes_by_product(product_alias)
        saved = 0
        for route in routes:
            try:
                self.repo.upsert_sedori_route(route)
                saved += 1
            except Exception as e:
                logger.warning("Failed to save sedori route: %s", e)
        return saved

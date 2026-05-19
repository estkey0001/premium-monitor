"""せどりルート計算エンジン (Phase 14)。

sale_prices（仕入れ候補）と buyback_prices（売却先）を組み合わせて
全ルートを計算し、sedori_routesテーブルに保存する。

計算式:
  gross_profit = sell_price - buy_price
  estimated_costs = shipping_fee + transfer_fee + travel_fee + other_costs
  net_profit = gross_profit - estimated_costs
  profit_rate = net_profit / buy_price
"""

import logging
from datetime import datetime
from typing import Optional

import ulid

from src.db.repository import Repository
from src.models.sale_price import SedoriRouteModel

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

    def calculate_all(self) -> dict:
        """全商品のせどりルートを計算して保存する。"""
        products = self.repo.list_products()
        total_saved = 0
        total_routes = 0
        results_by_product = {}

        for product in products:
            alias = product.id.replace("prod_", "")
            routes = self._calculate_for_product(product.id, product.name, alias)
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

        routes = self._calculate_for_product(product_id, product_name, product_alias)
        self._save_routes(product_alias, routes)
        return routes

    def _calculate_for_product(
        self,
        product_id: str,
        product_name: str,
        product_alias: str,
    ) -> list[SedoriRouteModel]:
        """商品の全ルートを計算する（保存はしない）。"""
        # 仕入れ候補（販売価格）を取得 — 店舗ごとに最安値1件に絞る
        _sp_all = self.repo.list_sale_prices(
            product_id=product_id, active_only=True, limit=50
        )
        # product_aliasでも検索（product_idが解決できない場合のフォールバック）
        if not _sp_all:
            _sp_all = self.repo.list_sale_prices(
                product_alias=product_alias, active_only=True, limit=50
            )
        # 店舗ごとに最安値1件のみ残す（重複排除）
        _sp_map: dict = {}
        for sp in _sp_all:
            key = sp.shop_id or sp.shop_name
            if key not in _sp_map or sp.sale_price < _sp_map[key].sale_price:
                _sp_map[key] = sp
        sale_prices = list(_sp_map.values())

        # 売却先（買取価格）を取得 — list_buyback_prices_by_product で店舗別最高価格のみ
        _bp_rows = self.repo.list_buyback_prices_by_product(product_id=product_id, limit=20)
        # dict形式から必要フィールドを抽出してシンプルなオブジェクト化
        from types import SimpleNamespace
        buyback_prices = [
            SimpleNamespace(
                shop_id=r.get("shop_id", ""),
                shop_name=r.get("shop_name", ""),
                buyback_price=r.get("buyback_price", 0),
                buyback_url=r.get("buyback_url", ""),
                condition=r.get("condition", ""),
            )
            for r in _bp_rows
            if r.get("buyback_price", 0) > 0
        ]

        if not sale_prices or not buyback_prices:
            return []

        routes: list[SedoriRouteModel] = []

        for sp in sale_prices:
            for bp in buyback_prices:
                # 同一店舗はスキップ
                if sp.shop_id == bp.shop_id or sp.shop_name == bp.shop_name:
                    continue

                gross_profit = bp.buyback_price - sp.sale_price

                # 粗利がゼロ以下はスキップ
                if gross_profit <= 0:
                    continue

                net_profit = gross_profit - self.estimated_costs

                # 実質利益がゼロ以下はスキップ
                if net_profit <= 0:
                    continue

                profit_rate = net_profit / sp.sale_price if sp.sale_price > 0 else 0.0

                route = SedoriRouteModel(
                    id=str(ulid.new()),
                    product_id=product_id,
                    product_name=product_name,
                    product_alias=product_alias,
                    buy_shop_name=sp.shop_name,
                    buy_shop_id=sp.shop_id,
                    buy_price=sp.sale_price,
                    buy_url=sp.url,
                    buy_condition=sp.condition,
                    sell_shop_name=bp.shop_name,
                    sell_shop_id=bp.shop_id,
                    sell_price=bp.buyback_price,
                    sell_url=bp.buyback_url,
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
                routes.append(route)

        # net_profit降順でソートしてランク付け
        routes.sort(key=lambda r: r.net_profit, reverse=True)
        for i, r in enumerate(routes, start=1):
            r.rank = i

        return routes

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

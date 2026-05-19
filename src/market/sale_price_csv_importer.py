"""販売価格CSVインポーター (Phase 14)。

data/manual_sale_prices.csv からsale_pricesテーブルへ投入する。

CSV形式:
product_alias,shop_name,sale_price,condition,url,observed_at,link_verified
iphone17pro256,じゃんぱら,179800,used_a,https://www.janpara.co.jp/sale/...,2026-05-19T12:00:00+09:00,true
"""

import csv
import io
import logging
from datetime import datetime
from pathlib import Path

import ulid

from src.db.repository import Repository
from src.models.sale_price import SalePriceModel

logger = logging.getLogger(__name__)

# 商品エイリアス → product_id マッピング（BuybackCSVImporterと共通）
ALIAS_MAP = {
    "gr4": "prod_gr4", "gr4_hdf": "prod_gr4_hdf", "gr4_mono": "prod_gr4_mono",
    "gr3x": "prod_gr3x", "gr3": "prod_gr3", "gr3_hdf": "prod_gr3_hdf",
    "x100vi": "prod_x100vi",
    # iPhone 17
    "iphone17pro256": "prod_iphone17pro_256", "iphone17pro": "prod_iphone17pro_256",
    "iphone17pro512": "prod_iphone17pro_512",
    "iphone17pm256": "prod_iphone17pm_256", "iphone17pm": "prod_iphone17pm_256",
    "iphone17pm512": "prod_iphone17pm_512",
    "iphone17_256": "prod_iphone17_256", "iphone17": "prod_iphone17_256",
    # iPhone 16
    "iphone16pro256": "prod_iphone16pro_256",
    "iphone16pm": "prod_iphone16pm_256", "iphone16pm_256": "prod_iphone16pm_256",
    "iphone16pm_512": "prod_iphone16pm_512",
    # Mac
    "macbook_air_m4_13": "prod_macbook_air_m4_13",
    "macbook_air_m4_15": "prod_macbook_air_m4_15",
    "macbook_pro_m4_14": "prod_macbook_pro_m4_14",
    "mac_mini_m4": "prod_mac_mini_m4",
    # iPad
    "ipad_pro_m4_11": "prod_ipad_pro_m4_11", "ipad_pro_m4_13": "prod_ipad_pro_m4_13",
    "ipad_air_m3": "prod_ipad_air_m3",
    # Apple Watch / AirPods
    "apple_watch_s11": "prod_apple_watch_s11", "apple_watch_ultra3": "prod_apple_watch_ultra3",
    "airpods_pro3": "prod_airpods_pro3", "airpods_max": "prod_airpods_max",
    # ゲーム機
    "ps5_pro": "prod_ps5_pro", "ps5_de": "prod_ps5_de",
    "switch2": "prod_switch2", "switch2_mk": "prod_switch2_mk",
    "xbox_sx": "prod_xbox_sx",
}


class SalePriceCSVImporter:
    """販売価格CSVインポーター。"""

    def __init__(self, repository: Repository):
        self.repo = repository

    def import_csv(self, csv_content: str) -> dict:
        reader = csv.DictReader(io.StringIO(csv_content))
        results = {"imported": 0, "skipped": 0, "errors": []}

        for i, row in enumerate(reader, start=2):
            try:
                self._import_row(row)
                results["imported"] += 1
            except Exception as e:
                results["errors"].append(f"Row {i}: {e}")
                results["skipped"] += 1

        return results

    def import_file(self, filepath: str) -> dict:
        with open(filepath, "r", encoding="utf-8") as f:
            return self.import_csv(f.read())

    def _import_row(self, row: dict) -> None:
        alias = row.get("product_alias", "").strip()
        shop_name = row.get("shop_name", "").strip()
        price_str = row.get("sale_price", "0").strip()
        condition = row.get("condition", "new_unopened").strip()
        url = row.get("url", "").strip()
        observed_str = row.get("observed_at", "").strip()
        link_verified = row.get("link_verified", "false").strip().lower() == "true"
        data_source = row.get("data_source", "manual").strip() or "manual"

        if not alias:
            raise ValueError("product_alias が空")
        if not shop_name:
            raise ValueError("shop_name が空")

        price = int(price_str.replace(",", "")) if price_str else 0
        if price <= 0:
            raise ValueError(f"Invalid sale_price: {price}")

        product_id = ALIAS_MAP.get(alias, f"prod_{alias}")
        shop_id = f"shop_{shop_name.lower().replace(' ', '_').replace('　', '_')}"

        observed_at = datetime.fromisoformat(observed_str) if observed_str else datetime.now()

        sp = SalePriceModel(
            id=str(ulid.new()),
            product_id=product_id,
            product_alias=alias,
            shop_name=shop_name,
            shop_id=shop_id,
            sale_price=price,
            condition=condition,
            url=url,
            link_verified=link_verified,
            observed_at=observed_at,
            data_source=data_source,
        )
        self.repo.insert_sale_price(sp)
        logger.debug("sale_price imported: %s / %s ¥%s", alias, shop_name, price)

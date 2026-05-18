"""買取価格専用CSVインポーター (Phase 9A)。

data/manual_buyback_prices.csv からbuyback_pricesテーブルへ投入する。

CSV形式:
product_alias,buyback_shop,buyback_price,condition,url,observed_at
iphone17pro256,mobile_ichiban,208000,new_unopened_simfree,https://example.com,2026-05-18T12:00:00+09:00
"""

import csv
import io
import logging
from datetime import datetime
from pathlib import Path

import ulid

from src.db.repository import Repository
from src.models.buyback_price import BuybackPriceModel, BUYBACK_SHOPS

logger = logging.getLogger(__name__)

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

SHOP_MAP = {
    "mobile_ichiban": "src_mobile_ichiban",
    "kaitori_shouten": "src_kaitori_shouten",
    "kaitori_itchome": "src_kaitori_itchome",
    "janpara": "src_janpara",
    "iosys": "src_iosys",
    "sofmap": "src_sofmap",
    "geo": "src_geo",
    "kitamura": "src_kitamura",
    "mapcamera": "src_mapcamera",
    "fujiya": "src_fujiya",
}


class BuybackCSVImporter:
    """買取価格CSVインポーター。"""

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
        shop = row.get("buyback_shop", "").strip()
        price = int(row.get("buyback_price", "0").strip())
        condition = row.get("condition", "new_unopened").strip()
        url = row.get("url", "").strip()
        observed_str = row.get("observed_at", "").strip()
        data_source = row.get("data_source", "manual_today").strip() or "manual_today"
        link_verified = row.get("link_verified", "false").strip().lower() == "true"

        product_id = ALIAS_MAP.get(alias, f"prod_{alias}")
        shop_id = SHOP_MAP.get(shop, f"src_{shop}")
        shop_name = BUYBACK_SHOPS.get(shop_id, {}).get("name", shop)

        if price <= 0:
            raise ValueError(f"Invalid price: {price}")

        observed_at = datetime.fromisoformat(observed_str) if observed_str else datetime.now()

        bp = BuybackPriceModel(
            id=str(ulid.new()),
            product_id=product_id,
            shop_id=shop_id,
            shop_name=shop_name,
            buyback_price=price,
            condition=condition,
            buyback_url=url,
            observed_at=observed_at,
            data_source=data_source,
            link_verified=link_verified,
        )
        self.repo.insert_buyback_price(bp)

        # price_historyにも記録
        from src.models.observation import PriceHistoryModel
        self.repo.insert_price_history(PriceHistoryModel(
            id=str(ulid.new()),
            product_id=product_id,
            source_id=shop_id,
            price_type="buyback",
            price=price,
            recorded_at=observed_at,
        ))

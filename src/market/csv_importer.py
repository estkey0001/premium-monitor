"""市場価格CSVインポート。

スクレイピング不安定なサイトの価格を手入力でインポートする。

CSV形式:
product_alias,source,price_type,price,currency,condition,is_sold,url,observed_at,data_source,link_verified,price_basis
gr4,mercari,used,250000,JPY,unused,false,https://example.com,2026-05-18T12:00:00,manual_today,true,出品価格
x100vi,ebay,overseas,2800,USD,used,true,https://example.com,2026-05-18T12:00:00,manual_today,true,海外sold

price_basis が空の場合は SOURCE_DEFAULT_BASIS から自動補完する。
"""

import csv
import io
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import ulid
import yaml

from src.db.repository import Repository
from src.models.observation import ObservationModel, PriceHistoryModel

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# product_alias → product_id
ALIAS_MAP = {
    "gr4": "prod_gr4", "gr4_hdf": "prod_gr4_hdf", "gr4_mono": "prod_gr4_mono",
    "gr3x": "prod_gr3x", "gr3": "prod_gr3", "gr3_hdf": "prod_gr3_hdf",
    "x100vi": "prod_x100vi",
    "iphone17pro256": "prod_iphone17pro_256", "iphone17pro": "prod_iphone17pro_256",
    "iphone16pm": "prod_iphone16pm_256", "iphone16pm_256": "prod_iphone16pm_256",
    "iphone16pm_512": "prod_iphone16pm_512",
    "ps5_pro": "prod_ps5_pro", "switch2": "prod_switch2",
}

# source短縮名 → source_id
SOURCE_MAP = {
    "mercari": "src_mercari", "ebay": "src_ebay", "yahoo_auction": "src_yahoo_auction",
    "kitamura": "src_kitamura", "fujiya": "src_fujiya", "janpara": "src_janpara",
    "iosys": "src_iosys", "sofmap": "src_sofmap", "map_camera": "src_map_camera",
    "kakaku": "src_kakaku", "yodobashi": "src_yodobashi", "biccamera": "src_biccamera",
    "stockx": "src_stockx", "manual": "manual",
    # 買取専門店
    "mobile_ichiban": "src_mobile_ichiban", "kaitori_shouten": "src_kaitori_shouten",
    "kaitori_ichome": "src_kaitori_ichome",
}

# source短縮名 → price_basis デフォルト値
# CSV に price_basis 列がない / 空欄の場合に使用する
SOURCE_DEFAULT_BASIS: dict = {
    "mercari":         "出品価格",
    "yahoo_auction":   "成約価格",
    "rakuten_flea":    "出品価格",
    "map_camera":      "中古販売価格",
    "kitamura":        "中古販売価格",
    "fujiya":          "中古販売価格",
    "sofmap":          "中古販売価格",
    "janpara":         "中古販売価格",
    "iosys":           "中古販売価格",
    "kakaku":          "新品販売価格",
    "yodobashi":       "新品販売価格",
    "biccamera":       "新品販売価格",
    "bhphoto":         "海外販売価格",
    "adorama":         "海外販売価格",
    "mpb":             "海外中古販売価格",
    "keh":             "海外中古販売価格",
    "amazon_us":       "海外販売価格",
    "stockx":          "海外販売価格",
    "ebay":            "海外sold",
    "mobile_ichiban":  "買取価格",
    "kaitori_shouten": "買取価格",
    "kaitori_ichome":  "買取価格",
    "manual":          "",
}


class CSVImporter:
    """市場価格CSVインポーター。"""

    def __init__(self, repository: Repository):
        self.repo = repository
        self.fx = self._load_fx()

    def _load_fx(self) -> dict:
        try:
            with open(PROJECT_ROOT / "config" / "fx_rates.yaml") as f:
                return yaml.safe_load(f)
        except Exception:
            return {"fx_rates": {"USD_JPY": 155}, "overseas_fees": {}}

    def import_csv(self, csv_content: str) -> dict:
        """CSV文字列をパースしてDBにインポートする。"""
        reader = csv.DictReader(io.StringIO(csv_content))
        results = {"imported": 0, "skipped": 0, "errors": []}

        for i, row in enumerate(reader, start=2):
            try:
                self._import_row(row)
                results["imported"] += 1
            except Exception as e:
                results["errors"].append(f"Row {i}: {e}")
                results["skipped"] += 1

        logger.info(
            "CSV import: %d imported, %d skipped, %d errors",
            results["imported"], results["skipped"], len(results["errors"]),
        )
        return results

    def import_file(self, filepath: str) -> dict:
        """CSVファイルをインポートする。"""
        with open(filepath, "r", encoding="utf-8") as f:
            return self.import_csv(f.read())

    def _import_row(self, row: dict) -> None:
        alias = row.get("product_alias", "").strip()
        source = row.get("source", "manual").strip()
        price_type = row.get("price_type", "used").strip()
        price_val = float(row.get("price", "0").strip())
        currency = row.get("currency", "JPY").strip().upper()
        is_sold = row.get("is_sold", "false").strip().lower() == "true"
        url = row.get("url", "").strip()
        observed_str = row.get("observed_at", "").strip()
        # price_basis: CSV 明示値 → ソースデフォルト → is_sold フラグから推定
        price_basis_raw = row.get("price_basis", "").strip()
        if price_basis_raw:
            price_basis = price_basis_raw
        else:
            price_basis = SOURCE_DEFAULT_BASIS.get(source, "")
            # ebay の is_sold=false は「海外販売価格」に補正
            if source == "ebay" and not is_sold:
                price_basis = "海外販売価格"

        product_id = ALIAS_MAP.get(alias, f"prod_{alias}")
        source_id = SOURCE_MAP.get(source, f"src_{source}")

        # 通貨変換
        if currency != "JPY":
            rate_key = f"{currency}_JPY"
            rate = self.fx.get("fx_rates", {}).get(rate_key)
            if not rate:
                raise ValueError(f"Unknown currency: {currency} (no {rate_key} rate)")
            jpy_price = int(price_val * rate)
            if price_type == "overseas":
                fees = self.fx.get("overseas_fees", {})
                jpy_price += fees.get("default_shipping_jpy", 3000)
                jpy_price += int(jpy_price * fees.get("default_import_tax_rate", 0.10))
        else:
            jpy_price = int(price_val)

        observed_at = datetime.fromisoformat(observed_str) if observed_str else datetime.now()

        # observation_type決定
        obs_type_map = {
            "overseas": "overseas_price",
            "used": "price",
            "buyback": "buyback",
            "retail": "stock",
            "market": "flea_market",
        }
        obs_type = obs_type_map.get(price_type, "price")

        now = datetime.now()
        obs = ObservationModel(
            id=str(ulid.new()),
            product_id=product_id,
            source_id=source_id,
            observation_type=obs_type,
            observed_at=observed_at,
            price=jpy_price,
            is_in_stock=not is_sold if price_type != "overseas" else None,
            raw_text=f"csv_import: {currency} {price_val} → ¥{jpy_price:,}",
            confidence=0.60,
        )
        self.repo.insert_observation(obs)
        self.repo.insert_price_history(PriceHistoryModel(
            id=str(ulid.new()),
            product_id=product_id,
            source_id=source_id,
            price_type=price_type,
            price=jpy_price,
            recorded_at=observed_at,
            price_basis=price_basis,
        ))

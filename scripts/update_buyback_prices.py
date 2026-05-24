#!/usr/bin/env python3
"""買取価格自動取得スクリプト。

各買取サイトから最新価格を取得し、data/manual_buyback_prices.csv を更新する。
- 取得成功: observed_at = 取得時刻, data_source = "auto_scraped"
- 取得失敗: buyback_price = 0, data_source = "fetch_failed" として記録
- 取得していない商品は前回価格を引き継がない（完全上書き）

実行:
  python scripts/update_buyback_prices.py
  python scripts/update_buyback_prices.py --dry-run  # 取得のみ、CSV未更新
  python scripts/update_buyback_prices.py --no-scrape  # スクレイピングスキップ（構造確認用）
"""
import argparse
import csv
import logging
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("update_buyback_prices")

JST = timezone(timedelta(hours=9))
PROJECT_ROOT = Path(__file__).parent.parent
CSV_PATH = PROJECT_ROOT / "data" / "manual_buyback_prices.csv"

# ── 対象商品定義 ──
TARGET_PRODUCTS = [
    {
        "product_alias":  "iphone17pro256",
        "product_name":   "iPhone 17 Pro 256GB SIMフリー",
        "condition":      "new_unopened_simfree",
        "shops":          ["mobile_ichiban", "kaitori_shouten", "kaitori_itchome", "janpara", "iosys",
                           "geo_mobile", "2ndstreet", "netoff"],
    },
    {
        "product_alias":  "iphone17pro512",
        "product_name":   "iPhone 17 Pro 512GB SIMフリー",
        "condition":      "new_unopened_simfree",
        "shops":          ["mobile_ichiban", "kaitori_shouten", "kaitori_itchome", "janpara", "iosys",
                           "geo_mobile", "2ndstreet", "netoff"],
    },
    {
        "product_alias":  "iphone17pm256",
        "product_name":   "iPhone 17 Pro Max 256GB SIMフリー",
        "condition":      "new_unopened_simfree",
        "shops":          ["mobile_ichiban", "kaitori_shouten", "kaitori_itchome", "janpara", "iosys",
                           "geo_mobile", "2ndstreet", "netoff"],
    },
    {
        "product_alias":  "iphone17pm512",
        "product_name":   "iPhone 17 Pro Max 512GB SIMフリー",
        "condition":      "new_unopened_simfree",
        "shops":          ["mobile_ichiban", "kaitori_shouten", "kaitori_itchome", "janpara", "iosys",
                           "geo_mobile", "2ndstreet", "netoff"],
    },
    {
        "product_alias":  "switch2",
        "product_name":   "Nintendo Switch 2",
        "condition":      "new_unopened",
        # ゲーム機向け店舗優先。bookoff/surugaya/sofmap/tsutaya はコレクター未実装 → fetch_failed + 確認リンク
        "shops":          ["geo", "iosys", "kaitori_shouten", "janpara",
                           "hardoff", "dosupara", "pasoko",
                           "sofmap", "bookoff", "surugaya", "tsutaya"],
    },
    {
        "product_alias":  "ps5_pro",
        "product_name":   "PlayStation 5 Pro",
        "condition":      "new_unopened",
        # ゲーム機向け店舗優先。bookoff/surugaya/sofmap/tsutaya はコレクター未実装 → fetch_failed + 確認リンク
        "shops":          ["geo", "iosys", "kaitori_shouten", "mobile_ichiban", "janpara",
                           "hardoff", "dosupara", "pasoko",
                           "sofmap", "bookoff", "surugaya", "tsutaya"],
    },
]

# ── 既存CSV内の他商品（自動取得対象外）は引き継ぐ ──
AUTO_ALIASES = {p["product_alias"] for p in TARGET_PRODUCTS}


def _load_collectors() -> dict:
    """コレクターをロードして shop_id → collector インスタンスのdictを返す。"""
    collectors = {}
    try:
        from src.collectors.buyback_mobile_ichiban import MobileIchibanCsvCollector
        collectors["mobile_ichiban"] = MobileIchibanCsvCollector()
    except ImportError as e:
        logger.warning("MobileIchibanCsvCollector not available: %s", e)

    try:
        from src.collectors.buyback_kaitori_shouten import KaitoriShoutenCsvCollector
        collectors["kaitori_shouten"] = KaitoriShoutenCsvCollector()
    except ImportError as e:
        logger.warning("KaitoriShoutenCsvCollector not available: %s", e)

    try:
        from src.collectors.buyback_kaitori_itchome import KaitoriItchomeCsvCollector
        collectors["kaitori_itchome"] = KaitoriItchomeCsvCollector()
    except ImportError as e:
        logger.warning("KaitoriItchomeCsvCollector not available: %s", e)

    try:
        from src.collectors.buyback_janpara import JanparaCsvCollector
        collectors["janpara"] = JanparaCsvCollector()
    except ImportError as e:
        logger.warning("JanparaCsvCollector not available: %s", e)

    try:
        from src.collectors.buyback_iosys import IosysCsvCollector
        collectors["iosys"] = IosysCsvCollector()
    except ImportError as e:
        logger.warning("IosysCsvCollector not available: %s", e)

    try:
        from src.collectors.buyback_geo import GeoCsvCollector
        collectors["geo"] = GeoCsvCollector()
    except ImportError as e:
        logger.warning("GeoCsvCollector not available: %s", e)

    try:
        from src.collectors.buyback_surugaya import SurugayaCsvCollector
        collectors["surugaya"] = SurugayaCsvCollector()
    except ImportError as e:
        logger.warning("SurugayaCsvCollector not available: %s", e)

    try:
        from src.collectors.buyback_sofmap import SofmapCsvCollector
        collectors["sofmap"] = SofmapCsvCollector()
    except ImportError as e:
        logger.warning("SofmapCsvCollector not available: %s", e)

    try:
        from src.collectors.buyback_hardoff import HardoffCsvCollector
        collectors["hardoff"] = HardoffCsvCollector()
    except ImportError as e:
        logger.warning("HardoffCsvCollector not available: %s", e)

    try:
        from src.collectors.buyback_geo_mobile import GeoMobileCsvCollector
        collectors["geo_mobile"] = GeoMobileCsvCollector()
    except ImportError as e:
        logger.warning("GeoMobileCsvCollector not available: %s", e)

    try:
        from src.collectors.buyback_dosupara import DosuparaCsvCollector
        collectors["dosupara"] = DosuparaCsvCollector()
    except ImportError as e:
        logger.warning("DosuparaCsvCollector not available: %s", e)

    try:
        from src.collectors.buyback_pasoko import PasakoCsvCollector
        collectors["pasoko"] = PasakoCsvCollector()
    except ImportError as e:
        logger.warning("PasakoCsvCollector not available: %s", e)

    try:
        from src.collectors.buyback_2ndstreet import SecondStreetCsvCollector
        collectors["2ndstreet"] = SecondStreetCsvCollector()
    except ImportError as e:
        logger.warning("SecondStreetCsvCollector not available: %s", e)

    try:
        from src.collectors.buyback_netoff import NetoffCsvCollector
        collectors["netoff"] = NetoffCsvCollector()
    except ImportError as e:
        logger.warning("NetoffCsvCollector not available: %s", e)

    return collectors


def _load_existing_csv() -> list[dict]:
    """既存CSVを読み込む。ファイルなければ空リスト。"""
    if not CSV_PATH.exists():
        return []
    rows = []
    with open(CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(dict(row))
    return rows


def _write_csv(rows: list[dict]) -> None:
    """CSV書き込み。"""
    fieldnames = ["product_alias", "buyback_shop", "buyback_price", "condition",
                  "url", "observed_at", "data_source", "link_verified"]
    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in fieldnames})


def run(dry_run: bool = False, no_scrape: bool = False) -> int:
    """メイン実行。戻り値: 0=成功, 1=一部失敗あり。"""
    collectors = {} if no_scrape else _load_collectors()
    existing_rows = _load_existing_csv()

    # 自動取得対象外の既存行を保持
    preserved_rows = [
        r for r in existing_rows
        if r.get("product_alias", "") not in AUTO_ALIASES
    ]

    now_jst = datetime.now(tz=JST)
    new_rows = []
    results_summary = []  # (product_alias, shop, status, price)

    for product in TARGET_PRODUCTS:
        alias    = product["product_alias"]
        pname    = product["product_name"]
        cond     = product["condition"]
        shops    = product["shops"]

        for shop_id in shops:
            collector = collectors.get(shop_id)

            if no_scrape or collector is None:
                # スクレイピングスキップ or コレクター未対応 → fetch_failed として記録
                row = {
                    "product_alias": alias,
                    "buyback_shop": shop_id,
                    "buyback_price": "0",
                    "condition": cond,
                    "url": _fallback_url(shop_id, alias),
                    "observed_at": now_jst.isoformat(timespec="seconds"),
                    "data_source": "fetch_failed",
                    "link_verified": "false",
                }
                new_rows.append(row)
                results_summary.append((alias, shop_id, "SKIP", 0))
                continue

            logger.info("Fetching %s x %s ...", alias, shop_id)
            try:
                result = collector.fetch(alias, pname, cond)
                if result and result.get("buyback_price", 0) > 0:
                    row = {
                        "product_alias": alias,
                        "buyback_shop": shop_id,
                        "buyback_price": str(result["buyback_price"]),
                        "condition": result.get("condition", cond),
                        "url": result.get("url", _fallback_url(shop_id, alias)),
                        "observed_at": result.get("observed_at", now_jst.isoformat(timespec="seconds")),
                        "data_source": result.get("data_source", "auto_scraped"),
                        "link_verified": result.get("link_verified", "true"),
                    }
                    new_rows.append(row)
                    results_summary.append((alias, shop_id, "OK", result["buyback_price"]))
                else:
                    # 取得失敗 → fetch_failed として記録
                    row = {
                        "product_alias": alias,
                        "buyback_shop": shop_id,
                        "buyback_price": "0",
                        "condition": cond,
                        "url": _fallback_url(shop_id, alias),
                        "observed_at": now_jst.isoformat(timespec="seconds"),
                        "data_source": "fetch_failed",
                        "link_verified": "false",
                    }
                    new_rows.append(row)
                    results_summary.append((alias, shop_id, "FAILED", 0))
            except Exception as e:
                logger.error("Error fetching %s x %s: %s", alias, shop_id, e)
                row = {
                    "product_alias": alias,
                    "buyback_shop": shop_id,
                    "buyback_price": "0",
                    "condition": cond,
                    "url": _fallback_url(shop_id, alias),
                    "observed_at": now_jst.isoformat(timespec="seconds"),
                    "data_source": "fetch_failed",
                    "link_verified": "false",
                }
                new_rows.append(row)
                results_summary.append((alias, shop_id, "ERROR", 0))

    # 結果サマリー表示
    print("\n" + "="*60)
    print(" Buyback Price Update Results")
    print("="*60)
    ok_count = sum(1 for _, _, s, _ in results_summary if s == "OK")
    fail_count = sum(1 for _, _, s, _ in results_summary if s in ("FAILED", "ERROR"))
    skip_count = sum(1 for _, _, s, _ in results_summary if s == "SKIP")
    for alias, shop, status, price in results_summary:
        icon = "OK" if status == "OK" else ("SKIP" if status == "SKIP" else "NG")
        price_str = f"Y{price:,}" if price > 0 else "-"
        print(f"  [{icon}] {alias} x {shop}: {status} {price_str}")
    print(f"\n  OK: {ok_count} | Failed: {fail_count} | Skip: {skip_count}")

    if dry_run:
        print("\n  [DRY RUN] CSV書き込みをスキップしました。")
        return 0

    # CSV書き込み
    final_rows = preserved_rows + new_rows
    _write_csv(final_rows)
    print(f"\n  CSV更新完了: {len(final_rows)}行 -> {CSV_PATH}")
    print("="*60 + "\n")

    return 1 if fail_count > 0 else 0


def _fallback_url(shop_id: str, product_alias: str) -> str:
    """取得失敗時の確認リンクURL（公式買取ページ）。"""
    FALLBACKS = {
        "mobile_ichiban":  "https://www.mobile-ichiban.com/",
        "kaitori_shouten": "https://www.kaitorishouten-co.jp/keitai",
        "kaitori_itchome": "https://www.1-chome.com/keitai/",
        "janpara":         "https://buy.janpara.co.jp/buy/",
        "iosys":           "https://k-tai-iosys.com/pricelist/",
        "geo":             "https://www.geo-online.co.jp/store_info/buy/",
        # ゲーム機向け店舗（コレクター未実装 → fetch_failed 表示用リンク）
        "sofmap":          "https://www.sofmap.com/buy_list.aspx",
        "bookoff":         "https://www.bookoffgroup.co.jp/sell/",
        "surugaya":        "https://www.suruga-ya.jp/kaitori/",
        "tsutaya":         "https://tsutaya.tsite.jp/feature/kaitori/",
        # 新規追加店舗
        "hardoff":         "https://www.hardoff.co.jp/search/",
        "geo_mobile":      "https://geomobile.jp/purchase/",
        "dosupara":        "https://www.dospara.co.jp/kaitori/",
        "pasoko":          "https://www.pc-koubou.jp/pc/used/buy/",
        "2ndstreet":       "https://www.2ndstreet.jp/sell/",
        "netoff":          "https://www.netoff.co.jp/sell/",
    }
    return FALLBACKS.get(shop_id, "")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="買取価格自動取得・CSV更新")
    parser.add_argument("--dry-run",   action="store_true", help="取得のみ、CSV未更新")
    parser.add_argument("--no-scrape", action="store_true", help="スクレイピングをスキップ（全fetch_failedとして記録）")
    args = parser.parse_args()

    # プロジェクトルートをPATHに追加
    sys.path.insert(0, str(PROJECT_ROOT))

    exit_code = run(dry_run=args.dry_run, no_scrape=args.no_scrape)
    sys.exit(exit_code)

#!/usr/bin/env python3
"""買取価格自動取得スクリプト。

各買取サイトから最新価格を取得し、data/manual_buyback_prices.csv を更新する。
- 取得成功: observed_at = 取得時刻, data_source = "auto_scraped"
- 取得失敗: buyback_price = 0, data_source = "fetch_failed" として記録
- 取得していない商品は前回価格を引き継がない（完全上書き）
- 実行後に exports/collector_report/latest.json / latest.md を出力

実行:
  python scripts/update_buyback_prices.py
  python scripts/update_buyback_prices.py --dry-run    # 取得のみ、CSV/レポート未更新
  python scripts/update_buyback_prices.py --no-scrape  # スクレイピングスキップ（構造確認用）
  python scripts/update_buyback_prices.py --verbose    # 詳細ログ出力
"""
import argparse
import csv
import json
import logging
import statistics
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
CSV_PATH     = PROJECT_ROOT / "data" / "manual_buyback_prices.csv"
REPORT_DIR   = PROJECT_ROOT / "exports" / "collector_report"

# ── 公式価格・ジャンル定義（suspicious_price 判定用） ──
OFFICIAL_PRICES: dict[str, int] = {
    "iphone17pro256": 179_800,
    "iphone17pro512": 214_800,
    "iphone17pm256":  219_800,
    "iphone17pm512":  254_800,
    "switch2":         49_980,
    "ps5_pro":        119_980,
}

PRODUCT_GENRES: dict[str, str] = {
    "iphone17pro256": "iphone",
    "iphone17pro512": "iphone",
    "iphone17pm256":  "iphone",
    "iphone17pm512":  "iphone",
    "switch2":         "game_console",
    "ps5_pro":         "game_console",
}

# ゲーム機でスマホ価格帯（10万円超）を拾った場合はsuspicious
GAME_CONSOLE_SMARTPHONE_THRESHOLD = 100_000

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
    existing_rows = _load_existing_csv()  # 前回データ（price_changes比較用）

    # 自動取得対象外の既存行を保持
    preserved_rows = [
        r for r in existing_rows
        if r.get("product_alias", "") not in AUTO_ALIASES
    ]

    now_jst = datetime.now(tz=JST)
    new_rows        = []
    results_summary = []   # (product_alias, shop, status, price)
    failure_reasons : dict[tuple, str] = {}  # (alias, shop_id) -> reason

    for product in TARGET_PRODUCTS:
        alias    = product["product_alias"]
        pname    = product["product_name"]
        cond     = product["condition"]
        shops    = product["shops"]

        for shop_id in shops:
            collector = collectors.get(shop_id)

            if no_scrape or collector is None:
                reason = "collector_not_loaded" if (not no_scrape and collector is None) else "scrape_skipped"
                row = {
                    "product_alias": alias,
                    "buyback_shop":  shop_id,
                    "buyback_price": "0",
                    "condition":     cond,
                    "url":           _fallback_url(shop_id, alias),
                    "observed_at":   now_jst.isoformat(timespec="seconds"),
                    "data_source":   "fetch_failed",
                    "link_verified": "false",
                }
                new_rows.append(row)
                results_summary.append((alias, shop_id, "SKIP", 0))
                failure_reasons[(alias, shop_id)] = reason
                continue

            logger.info("Fetching %s x %s ...", alias, shop_id)
            try:
                result = collector.fetch(alias, pname, cond)
                if result and result.get("buyback_price", 0) > 0:
                    row = {
                        "product_alias": alias,
                        "buyback_shop":  shop_id,
                        "buyback_price": str(result["buyback_price"]),
                        "condition":     result.get("condition", cond),
                        "url":           result.get("url", _fallback_url(shop_id, alias)),
                        "observed_at":   result.get("observed_at", now_jst.isoformat(timespec="seconds")),
                        "data_source":   result.get("data_source", "auto_scraped"),
                        "link_verified": result.get("link_verified", "true"),
                    }
                    new_rows.append(row)
                    results_summary.append((alias, shop_id, "OK", result["buyback_price"]))
                else:
                    # 取得失敗 → fetch_failed として記録
                    reason = getattr(collector, "last_failure_reason", None) or "price_not_found"
                    row = {
                        "product_alias": alias,
                        "buyback_shop":  shop_id,
                        "buyback_price": "0",
                        "condition":     cond,
                        "url":           _fallback_url(shop_id, alias),
                        "observed_at":   now_jst.isoformat(timespec="seconds"),
                        "data_source":   "fetch_failed",
                        "link_verified": "false",
                    }
                    new_rows.append(row)
                    results_summary.append((alias, shop_id, "FAILED", 0))
                    failure_reasons[(alias, shop_id)] = reason
            except Exception as e:
                logger.error("Error fetching %s x %s: %s", alias, shop_id, e)
                reason = getattr(collector, "last_failure_reason", None) or f"exception_{type(e).__name__}"
                row = {
                    "product_alias": alias,
                    "buyback_shop":  shop_id,
                    "buyback_price": "0",
                    "condition":     cond,
                    "url":           _fallback_url(shop_id, alias),
                    "observed_at":   now_jst.isoformat(timespec="seconds"),
                    "data_source":   "fetch_failed",
                    "link_verified": "false",
                }
                new_rows.append(row)
                results_summary.append((alias, shop_id, "ERROR", 0))
                failure_reasons[(alias, shop_id)] = reason

    # 結果サマリー表示
    print("\n" + "="*60)
    print(" Buyback Price Update Results")
    print("="*60)
    ok_count   = sum(1 for _, _, s, _ in results_summary if s == "OK")
    fail_count = sum(1 for _, _, s, _ in results_summary if s in ("FAILED", "ERROR"))
    skip_count = sum(1 for _, _, s, _ in results_summary if s == "SKIP")
    for alias, shop, status, price in results_summary:
        icon      = "OK" if status == "OK" else ("SKIP" if status == "SKIP" else "NG")
        price_str = f"Y{price:,}" if price > 0 else "-"
        reason_str = ""
        if status != "OK":
            r = failure_reasons.get((alias, shop), "")
            reason_str = f" [{r}]" if r else ""
        print(f"  [{icon}] {alias} x {shop}: {status} {price_str}{reason_str}")
    print(f"\n  OK: {ok_count} | Failed: {fail_count} | Skip: {skip_count}")

    if dry_run:
        print("\n  [DRY RUN] CSV/レポート書き込みをスキップしました。")
        return 0

    # CSV書き込み
    final_rows = preserved_rows + new_rows
    _write_csv(final_rows)
    print(f"\n  CSV更新完了: {len(final_rows)}行 -> {CSV_PATH}")
    print("="*60 + "\n")

    # コレクターレポート生成
    _generate_collector_report(
        new_rows=new_rows,
        results_summary=results_summary,
        now_jst=now_jst,
        existing_rows=existing_rows,
        failure_reasons=failure_reasons,
    )

    return 1 if fail_count > 0 else 0


def _generate_collector_report(
    new_rows: list[dict],
    results_summary: list,
    now_jst,
    existing_rows: list[dict],
    failure_reasons: dict,
) -> None:
    """コレクターレポートを exports/collector_report/latest.{json,md} に出力する。"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # ── 集計 ──────────────────────────────────────────────────────────────
    by_shop:    dict[str, dict] = {}
    by_product: dict[str, dict] = {}

    for alias, shop_id, status, _price in results_summary:
        # shop集計
        if shop_id not in by_shop:
            by_shop[shop_id] = {"ok": 0, "failed": 0, "skip": 0}
        key = "ok" if status == "OK" else ("skip" if status == "SKIP" else "failed")
        by_shop[shop_id][key] += 1

        # product集計
        if alias not in by_product:
            by_product[alias] = {"ok": 0, "failed": 0, "skip": 0}
        by_product[alias][key] += 1

    ok_count   = sum(1 for _, _, s, _ in results_summary if s == "OK")
    fail_count = sum(1 for _, _, s, _ in results_summary if s in ("FAILED", "ERROR"))
    skip_count = sum(1 for _, _, s, _ in results_summary if s == "SKIP")

    # ── 取得失敗一覧 ───────────────────────────────────────────────────────
    fetch_failed_list = []
    for alias, shop_id, status, _price in results_summary:
        if status != "OK":
            reason = failure_reasons.get((alias, shop_id), "unknown")
            row_match = next(
                (r for r in new_rows
                 if r.get("product_alias") == alias and r.get("buyback_shop") == shop_id),
                {}
            )
            fetch_failed_list.append({
                "product_alias": alias,
                "shop": shop_id,
                "status": status,
                "reason": reason,
                "url": row_match.get("url", ""),
                "observed_at": row_match.get("observed_at", ""),
            })

    # ── 前回価格との差分 ───────────────────────────────────────────────────
    prev_price_map: dict[tuple, int] = {}
    for r in existing_rows:
        try:
            p = int(r.get("buyback_price", 0) or 0)
        except (ValueError, TypeError):
            p = 0
        if p > 0:
            prev_price_map[(r.get("product_alias", ""), r.get("buyback_shop", ""))] = p

    price_changes = []
    for row in new_rows:
        alias   = row.get("product_alias", "")
        shop_id = row.get("buyback_shop", "")
        try:
            new_price = int(row.get("buyback_price", 0) or 0)
        except (ValueError, TypeError):
            new_price = 0
        if new_price <= 0:
            continue
        prev_price = prev_price_map.get((alias, shop_id))
        if prev_price and prev_price != new_price:
            change_pct = round((new_price - prev_price) / prev_price * 100, 1)
            price_changes.append({
                "product_alias": alias,
                "shop": shop_id,
                "prev_price": prev_price,
                "new_price": new_price,
                "change_pct": change_pct,
                "direction": "up" if change_pct > 0 else "down",
            })

    # ── suspicious_price 検出 ─────────────────────────────────────────────
    # 同一商品の取得成功価格を集める（平均比較用）
    product_prices: dict[str, list[int]] = {}
    for row in new_rows:
        alias = row.get("product_alias", "")
        try:
            p = int(row.get("buyback_price", 0) or 0)
        except (ValueError, TypeError):
            p = 0
        if p > 0:
            product_prices.setdefault(alias, []).append(p)

    suspicious_prices = []

    for row in new_rows:
        alias   = row.get("product_alias", "")
        shop_id = row.get("buyback_shop", "")
        try:
            price = int(row.get("buyback_price", 0) or 0)
        except (ValueError, TypeError):
            price = 0
        if price <= 0:
            continue  # fetch_failedはスキップ

        official = OFFICIAL_PRICES.get(alias)
        genre    = PRODUCT_GENRES.get(alias, "")
        flags: list[dict] = []

        # ① 前回比 ±30%以上
        prev = prev_price_map.get((alias, shop_id))
        if prev and prev > 0:
            change_pct = abs(price - prev) / prev * 100
            if change_pct >= 30:
                flags.append({
                    "reason": "price_change_over_30pct",
                    "details": f"前回¥{prev:,} → 今回¥{price:,}（{change_pct:+.1f}%）",
                })

        if official and official > 0:
            ratio = price / official
            # ② 公式価格の3倍以上
            if ratio >= 3.0:
                flags.append({
                    "reason": "over_3x_official",
                    "details": f"公式¥{official:,}の{ratio:.1f}倍（¥{price:,}）",
                })
            # ③ 公式価格の30%未満
            if ratio < 0.30:
                flags.append({
                    "reason": "below_30pct_official",
                    "details": f"公式¥{official:,}の{ratio*100:.0f}%未満（¥{price:,}）",
                })

        # ④ 同一商品内で他店舗平均との差が極端（±50%以上）
        peers = [p for p in product_prices.get(alias, []) if p != price]
        if len(peers) >= 2:
            mean_peers = statistics.mean(peers)
            if mean_peers > 0:
                dev_pct = abs(price - mean_peers) / mean_peers * 100
                if dev_pct >= 50:
                    flags.append({
                        "reason": "outlier_vs_peer_shops",
                        "details": f"他店平均¥{mean_peers:,.0f}から{dev_pct:.0f}%乖離（¥{price:,}）",
                    })

        # ⑤ ゲーム機なのにスマホ価格帯（公式価格の2.5倍 or 10万円のうち大きい方を超える）
        # 例: Switch2(¥49,980) → 閾値¥124,950、PS5 Pro(¥119,980) → 閾値¥299,950
        if genre == "game_console":
            gc_threshold = max(
                GAME_CONSOLE_SMARTPHONE_THRESHOLD,
                int(official * 2.5) if official else GAME_CONSOLE_SMARTPHONE_THRESHOLD,
            )
            if price > gc_threshold:
                flags.append({
                    "reason": "game_console_smartphone_price",
                    "details": f"ゲーム機({alias})なのに¥{price:,}（閾値¥{gc_threshold:,}超 / スマホ価格帯の可能性）",
                })

        for flag in flags:
            suspicious_prices.append({
                "product_alias":  alias,
                "shop":           shop_id,
                "price":          price,
                "official_price": official,
                "reason":         flag["reason"],
                "details":        flag["details"],
            })

    # ── JSON出力 ───────────────────────────────────────────────────────────
    report = {
        "generated_at":    now_jst.isoformat(timespec="seconds"),
        "summary": {
            "total":   len(results_summary),
            "ok":      ok_count,
            "failed":  fail_count,
            "skip":    skip_count,
        },
        "by_shop":          by_shop,
        "by_product":       by_product,
        "fetch_failed":     fetch_failed_list,
        "price_changes":    price_changes,
        "suspicious_prices": suspicious_prices,
    }

    json_path = REPORT_DIR / "latest.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # ── Markdown出力 ───────────────────────────────────────────────────────
    md_lines: list[str] = [
        f"# Collector Quality Report",
        f"",
        f"生成日時: {now_jst.strftime('%Y-%m-%d %H:%M:%S %Z')}",
        f"",
        f"## サマリ",
        f"",
        f"| 合計 | OK | 失敗 | スキップ |",
        f"|------|-----|------|----------|",
        f"| {len(results_summary)} | {ok_count} | {fail_count} | {skip_count} |",
        f"",
        f"## 店舗別 OK/失敗/スキップ",
        f"",
        f"| 店舗 | OK | 失敗 | スキップ |",
        f"|------|-----|------|----------|",
    ]
    for shop_id, cnt in sorted(by_shop.items()):
        md_lines.append(f"| {shop_id} | {cnt['ok']} | {cnt['failed']} | {cnt['skip']} |")

    md_lines += [
        f"",
        f"## 商品別 OK/失敗/スキップ",
        f"",
        f"| 商品 | OK | 失敗 | スキップ |",
        f"|------|-----|------|----------|",
    ]
    for alias, cnt in sorted(by_product.items()):
        md_lines.append(f"| {alias} | {cnt['ok']} | {cnt['failed']} | {cnt['skip']} |")

    md_lines += [f"", f"## 取得失敗一覧 ({len(fetch_failed_list)}件)", f""]
    if fetch_failed_list:
        md_lines.append(f"| 商品 | 店舗 | ステータス | 理由 |")
        md_lines.append(f"|------|------|-----------|------|")
        for item in fetch_failed_list:
            md_lines.append(
                f"| {item['product_alias']} | {item['shop']} | {item['status']} | {item['reason']} |"
            )
    else:
        md_lines.append("（なし）")

    md_lines += [f"", f"## 価格変動一覧 ({len(price_changes)}件)", f""]
    if price_changes:
        md_lines.append(f"| 商品 | 店舗 | 前回 | 今回 | 変化率 |")
        md_lines.append(f"|------|------|------|------|--------|")
        for c in sorted(price_changes, key=lambda x: abs(x["change_pct"]), reverse=True):
            arrow = "↑" if c["change_pct"] > 0 else "↓"
            md_lines.append(
                f"| {c['product_alias']} | {c['shop']} | ¥{c['prev_price']:,} | ¥{c['new_price']:,} | {arrow}{abs(c['change_pct']):.1f}% |"
            )
    else:
        md_lines.append("（前回との変動なし）")

    md_lines += [f"", f"## ⚠️ suspicious_price 一覧 ({len(suspicious_prices)}件)", f""]
    if suspicious_prices:
        md_lines.append(f"| 商品 | 店舗 | 価格 | 理由 | 詳細 |")
        md_lines.append(f"|------|------|------|------|------|")
        for s in suspicious_prices:
            md_lines.append(
                f"| {s['product_alias']} | {s['shop']} | ¥{s['price']:,} | {s['reason']} | {s['details']} |"
            )
    else:
        md_lines.append("（suspicious_price なし）")

    md_path = REPORT_DIR / "latest.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines) + "\n")

    # サマリ表示
    suspicious_count = len(suspicious_prices)
    warn_icon = "⚠️ " if suspicious_count > 0 else "✅"
    print(f"\n  {warn_icon} Collector Report: {json_path}")
    if suspicious_count > 0:
        print(f"  ⚠️  suspicious_price {suspicious_count}件 — latest.md を確認してください")
    if price_changes:
        print(f"  📊 価格変動 {len(price_changes)}件")
    logger.info("Collector report saved: %s", json_path)


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
    parser.add_argument("--dry-run",   action="store_true", help="取得のみ、CSV/レポート未更新")
    parser.add_argument("--no-scrape", action="store_true", help="スクレイピングをスキップ（全fetch_failedとして記録）")
    parser.add_argument("--verbose",   action="store_true", help="DEBUGレベルの詳細ログ出力")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)
        logging.getLogger("src.collectors").setLevel(logging.DEBUG)

    # プロジェクトルートをPATHに追加
    sys.path.insert(0, str(PROJECT_ROOT))

    exit_code = run(dry_run=args.dry_run, no_scrape=args.no_scrape)
    sys.exit(exit_code)

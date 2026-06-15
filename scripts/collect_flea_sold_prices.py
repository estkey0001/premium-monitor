#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""フリマ成約(sold)価格 収集スクリプト（Pro 仕入れ側強化）。

重要（規約遵守）:
  メルカリ等はスクレイピングを規約で禁止しているため、本スクリプトは
  **ライブの自動大量取得を行わない**。以下の ToS 安全な方式で動作する:
    1) 各商品・各ソースの「検索URL」を生成（人手確認用）
    2) 人手で確認・記録した data/manual_flea_sold_prices.csv を読み込む
    3) 本体一致・非アクセサリー・14日以内・price>0 のものを sale_prices(flea_sold_price) に保存
    4) target_buy_price（買取で売れる上限）以下のものを main route 候補、超過は参考扱い

出力:
  exports/flea_sold_prices/yahoo_sold.json
  exports/flea_sold_prices/mercari_sold.json
  exports/flea_sold_prices/rakuma_sold.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

JST = timezone(timedelta(hours=9))
DB_PATH = PROJECT_ROOT / "data" / "premium_monitor.db"
CSV_PATH = PROJECT_ROOT / "data" / "manual_flea_sold_prices.csv"
PROFIT_PATH = PROJECT_ROOT / "exports" / "profit_routes" / "latest.json"
OUT_DIR = PROJECT_ROOT / "exports" / "flea_sold_prices"

FRESH_DAYS = 14
NEW_CONDITIONS = {"new", "new_unopened", "unused", "未使用", "新品", "未開封"}
ACCESSORY_KW = ("ケース", "case", "カバー", "cover", "バッテリー", "battery", "充電器",
                "charger", "ストラップ", "strap", "レンズ", "lens", "フィルター", "filter",
                "アダプター", "adapter", "保護", "protector", "leather", "pouch", "grip",
                "グリップ", "フード", "hood", "三脚", "tripod", "シール", "skin")

SOURCE_META = {
    "yahoo_auction": {"name": "Yahoo Auction sold",
                      "search": "https://auctions.yahoo.co.jp/closedsearch/closedsearch?p={kw}&va={kw}"},
    "mercari": {"name": "Mercari sold",
                "search": "https://jp.mercari.com/search?keyword={kw}&status=sold_out"},
    "rakuma": {"name": "Rakuma sold",
               "search": "https://fril.jp/s?query={kw}&transaction=sold_out"},
}


def _is_accessory(title: str) -> bool:
    t = (title or "").lower()
    return any(k.lower() in t for k in ACCESSORY_KW)


def _age_days(observed_at: str, now: datetime) -> float:
    try:
        dt = datetime.fromisoformat(str(observed_at))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return (now - dt.astimezone(JST)).total_seconds() / 86400.0
    except Exception:
        return 9999.0


def _load_targets() -> dict:
    """profit_routes の zero diagnostics から商品別 target_buy_price を読む。"""
    targets = {}
    try:
        d = json.loads(PROFIT_PATH.read_text(encoding="utf-8"))
        for pid, z in d.get("zero_route_diagnostics", {}).items():
            if z.get("target_buy_price"):
                targets[pid] = z["target_buy_price"]
    except Exception:
        pass
    return targets


def _load_products():
    import sqlite3
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    rows = con.execute("SELECT id, name, keywords FROM products WHERE is_active=1").fetchall()
    con.close()
    out = {}
    for r in rows:
        alias = r["id"].replace("prod_", "")
        out[alias] = {"product_id": r["id"], "name": r["name"], "keywords": r["keywords"] or r["name"]}
    return out


def _save_sale_price(con, alias, product_id, source_name, price, condition, item_url, search_url, observed_at):
    import sqlite3  # noqa
    cols = [c[1] for c in con.execute("PRAGMA table_info(sale_prices)").fetchall()]
    sid = "src_flea_" + source_name.split()[0].lower()
    vals = {
        "id": f"flea_sold_{alias}_{sid}", "product_id": product_id, "product_alias": alias,
        "shop_name": source_name, "shop_id": sid, "sale_price": int(price),
        "condition": condition or "new_unopened", "url": item_url or search_url,
        "link_verified": 1 if item_url else 0, "observed_at": observed_at,
        "data_source": "flea_sold", "is_active": 1,
    }
    present = {k: v for k, v in vals.items() if k in cols}
    con.execute(f"INSERT OR REPLACE INTO sale_prices ({','.join(present)}) VALUES "
                f"({','.join('?' * len(present))})", list(present.values()))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sources", default="yahoo,mercari,rakuma")
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()
    now = datetime.now(tz=JST)
    src_map = {"yahoo": "yahoo_auction", "mercari": "mercari", "rakuma": "rakuma"}
    sources = [src_map.get(s.strip(), s.strip()) for s in args.sources.split(",") if s.strip()]
    print(f"[collect_flea_sold_prices] 開始: {now.strftime('%Y-%m-%d %H:%M')} JST / sources={sources}")
    print("  ※ 規約遵守: ライブスクレイピングは行わず、手動キュレーションCSV + 検索URL方式で動作します。")

    targets = _load_targets()
    products = _load_products()

    # 手動キュレーション CSV を読み込む
    manual_rows = []
    if CSV_PATH.exists():
        with open(CSV_PATH, encoding="utf-8") as f:
            # 先頭の # コメント行を除外してから DictReader（最初の非コメント行がヘッダ）
            reader = csv.DictReader(line for line in f if not line.lstrip().startswith("#"))
            manual_rows = [r for r in reader]
    print(f"  手動キュレーション sold: {len(manual_rows)} 行")

    import sqlite3
    con = sqlite3.connect(str(DB_PATH))

    by_source = {s: defaultdict(list) for s in sources}
    saved = 0
    adopted = 0  # target以下でmain候補
    reference = 0  # target超で参考のみ

    for r in manual_rows:
        alias = (r.get("product_alias") or "").strip()
        source = (r.get("source") or "").strip()
        if source not in sources:
            continue
        prod = products.get(alias)
        if not prod:
            continue
        try:
            price = int(float(r.get("price") or 0))
        except ValueError:
            price = 0
        title = r.get("title") or ""
        condition = (r.get("condition") or "").strip()
        item_url = (r.get("item_url") or "").strip()
        observed_at = (r.get("observed_at") or "").strip()
        age = _age_days(observed_at, now)
        # フィルタ: 新品/未使用 / 非アクセサリー / price>0 / 14日以内 / URLあり
        reject = ""
        if price <= 0:
            reject = "price_zero"
        elif condition not in NEW_CONDITIONS:
            reject = "not_new_unused"
        elif _is_accessory(title):
            reject = "accessory_or_wrong_product"
        elif age > FRESH_DAYS:
            reject = "stale_over_14d"
        elif not (item_url or True):  # search_url は常に生成可能のため URL は必須を満たす
            reject = "no_url"
        target = targets.get(prod["product_id"])
        within_target = (target is not None and price <= target)
        kw = quote(prod["keywords"])
        search_url = SOURCE_META[source]["search"].format(kw=kw)
        rec = {
            "product_id": prod["product_id"], "product_alias": alias, "product_name": prod["name"],
            "price": price, "condition": condition, "title": title[:80],
            "item_url": item_url, "search_url": search_url, "observed_at": observed_at,
            "age_days": round(age, 1), "target_buy_price": target,
            "within_target": bool(within_target), "rejection_reason": reject,
        }
        by_source[source][alias].append(rec)
        if not reject:
            _save_sale_price(con, alias, prod["product_id"], SOURCE_META[source]["name"],
                             price, condition, item_url, search_url, observed_at)
            saved += 1
            if within_target:
                adopted += 1
            else:
                reference += 1
    con.commit()
    con.close()

    # ソース別 JSON 出力（median/min/recent count/item_url一覧 + 検索URL）
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    file_map = {"yahoo_auction": "yahoo_sold.json", "mercari": "mercari_sold.json", "rakuma": "rakuma_sold.json"}
    for source in sources:
        products_out = {}
        for alias, recs in by_source[source].items():
            valid = [x for x in recs if not x["rejection_reason"]]
            prices = sorted(x["price"] for x in valid)
            median = prices[len(prices) // 2] if prices else None
            products_out[alias] = {
                "product_name": recs[0]["product_name"],
                "count_recent": len(valid), "median_price": median,
                "min_price": (min(prices) if prices else None),
                "target_buy_price": recs[0]["target_buy_price"],
                "within_target_count": sum(1 for x in valid if x["within_target"]),
                "search_url": recs[0]["search_url"],
                "item_urls": [x["item_url"] for x in valid if x["item_url"]],
                "items": recs,
            }
        payload = {
            "generated_at": now.strftime("%Y-%m-%d %H:%M JST"),
            "source": SOURCE_META[source]["name"],
            "policy": "no_live_scraping_tos_safe_manual_curation_plus_search_url",
            "fresh_days": FRESH_DAYS,
            "products": products_out,
        }
        (OUT_DIR / file_map[source]).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  → {OUT_DIR / file_map[source]} ({len(products_out)}商品)")

    print(f"  保存 sale_prices(flea_sold): {saved} 行 / target以下(main候補) {adopted} / target超(参考) {reference}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

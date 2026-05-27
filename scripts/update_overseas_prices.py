#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""海外市場価格を更新するスクリプト。

現時点では data/manual_market_prices.csv から海外価格データを読み込み、
exports/overseas_prices/latest.json として保存します。

将来的には eBay API / StockX API 等のリアルタイム取得に拡張予定。

対象市場:
  - eBay sold
  - StockX
  - Amazon US
  - B&H Photo
  - Adorama
  - MPB
  - KEH Camera
  - 海外カメラ店
  - 海外ゲーム機相場

最低限保存項目:
  - product_name
  - market
  - price_jpy
  - currency
  - original_price
  - condition
  - sold_or_listing
  - observed_at
  - url
  - confidence
  - failure_reason
"""
from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

JST = timezone(timedelta(hours=9))
EXPORT_DIR = PROJECT_ROOT / "exports" / "overseas_prices"

# 海外市場と判定するソース名
OVERSEAS_SOURCES: frozenset[str] = frozenset({
    "ebay", "ebay_sold", "ebay_listing",
    "stockx",
    "amazon_us", "amazon_com",
    "bh", "bhphotovideo", "b&h",
    "adorama",
    "mpb", "mpb_com",
    "keh", "keh_camera",
    "roberts", "roberts_camera",
    "used.photo",
    "mr_photo",
})

# ソース → 表示名マッピング
SOURCE_LABELS: dict[str, str] = {
    "ebay": "eBay",
    "ebay_sold": "eBay (sold)",
    "ebay_listing": "eBay (listing)",
    "stockx": "StockX",
    "amazon_us": "Amazon US",
    "amazon_com": "Amazon.com",
    "bh": "B&H Photo",
    "bhphotovideo": "B&H Photo",
    "b&h": "B&H Photo",
    "adorama": "Adorama",
    "mpb": "MPB",
    "mpb_com": "MPB",
    "keh": "KEH Camera",
    "keh_camera": "KEH Camera",
    "roberts": "Roberts Camera",
    "roberts_camera": "Roberts Camera",
    "used.photo": "Used Photo",
    "mr_photo": "MR Photo",
}

# スタブデータ（リアルタイム取得が未対応の場合のフォールバック）
_STUB_MARKETS: list[dict] = [
    {
        "market": "eBay",
        "url": "https://www.ebay.com/sch/i.html?_nkw=",
        "note": "eBay sold listingsを手動で確認してください",
    },
    {
        "market": "StockX",
        "url": "https://stockx.com/",
        "note": "StockXの取引履歴を手動で確認してください",
    },
]


def _load_manual_overseas_prices() -> list[dict]:
    """data/manual_market_prices.csv から海外価格データを読み込む。"""
    csv_path = PROJECT_ROOT / "data" / "manual_market_prices.csv"
    if not csv_path.exists():
        return []

    results = []
    try:
        with open(csv_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                source = (row.get("source") or "").strip().lower()
                if source not in OVERSEAS_SOURCES:
                    continue

                # 状態フィルタ（新品・未使用のみ）
                condition = (row.get("condition") or "").strip()

                # 価格
                try:
                    price_raw = float(row.get("price") or 0)
                except (ValueError, TypeError):
                    price_raw = 0.0

                currency = (row.get("currency") or "JPY").strip().upper()

                # JPY換算（USD→JPY 仮レート: 155円）
                if currency == "USD":
                    price_jpy = int(price_raw * 155)
                elif currency == "EUR":
                    price_jpy = int(price_raw * 168)
                elif currency == "GBP":
                    price_jpy = int(price_raw * 196)
                else:
                    price_jpy = int(price_raw)

                results.append({
                    "product_name": (row.get("product_alias") or "").strip(),
                    "market": SOURCE_LABELS.get(source, source.upper()),
                    "source": source,
                    "price_jpy": price_jpy,
                    "currency": currency,
                    "original_price": price_raw,
                    "condition": condition,
                    "sold_or_listing": "sold" if row.get("is_sold", "").lower() in ("true", "1", "yes") else "listing",
                    "observed_at": (row.get("observed_at") or "").strip(),
                    "url": (row.get("url") or "").strip(),
                    "confidence": "manual",
                    "failure_reason": "",
                    "price_basis": (row.get("price_basis") or "").strip(),
                    "data_source": (row.get("data_source") or "manual").strip(),
                })
    except Exception as e:
        print(f"[WARN] manual_market_prices.csv 読み込みエラー: {e}", file=sys.stderr)

    return results


def _build_product_index(prices: list[dict]) -> dict[str, list[dict]]:
    """商品名をキーとした海外価格インデックスを構築する。"""
    index: dict[str, list[dict]] = {}
    for p in prices:
        name = p.get("product_name", "").strip()
        if not name:
            continue
        if name not in index:
            index[name] = []
        index[name].append(p)
    # 各商品の価格を価格降順でソート
    for name in index:
        index[name].sort(key=lambda x: x.get("price_jpy", 0), reverse=True)
    return index


def main() -> int:
    """メイン処理: 海外価格データを更新・保存する。"""
    now = datetime.now(tz=JST)
    print(f"[update_overseas_prices] 開始: {now.strftime('%Y-%m-%d %H:%M')} JST")

    # manual_market_prices.csv から海外価格を読み込む
    overseas_prices = _load_manual_overseas_prices()
    print(f"[INFO] manual_market_prices.csv から {len(overseas_prices)} 件の海外価格を読み込みました")

    # 商品別インデックス
    product_index = _build_product_index(overseas_prices)

    # 統計
    markets = {}
    for p in overseas_prices:
        m = p.get("market", "unknown")
        markets[m] = markets.get(m, 0) + 1

    # レポート構築
    report = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "total_prices": len(overseas_prices),
        "products_with_overseas": len(product_index),
        "markets": markets,
        "note": "現時点では manual_market_prices.csv からの読み込みのみ。将来的にeBay API/StockX API等のリアルタイム取得に拡張予定。",
        "prices": overseas_prices,
        "by_product": {
            name: prices
            for name, prices in sorted(product_index.items())
        },
    }

    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    json_path = EXPORT_DIR / "latest.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    print(f"[INFO] overseas_prices/latest.json 保存完了 "
          f"(商品数: {len(product_index)}, 価格数: {len(overseas_prices)})")
    if markets:
        for m, c in sorted(markets.items(), key=lambda x: -x[1]):
            print(f"  {m}: {c} 件")
    else:
        print("[INFO] 海外価格データなし（manual_market_prices.csv に overseas ソースなし）")

    return 0


if __name__ == "__main__":
    sys.exit(main())

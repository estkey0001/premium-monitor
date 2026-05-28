"""手動CSVフォールバックコレクター。

manual_market_prices.csv から海外価格を読み込む。
自動収集が失敗した場合のフォールバックとして使用。
"""
from __future__ import annotations

import csv
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from src.collectors.overseas.base_overseas import (
    OverseasPriceResult, is_stale, load_fx_rates
)
from src.collectors.overseas.fx_fetcher import get_usd_jpy, get_eur_jpy

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
JST = timezone(timedelta(hours=9))

# 対応海外ソース
OVERSEAS_SOURCES = frozenset({
    "ebay", "ebay_sold", "ebay_listing",
    "stockx", "amazon_us", "amazon_com",
    "bh", "bhphotovideo", "b&h",
    "adorama", "mpb", "mpb_com",
    "keh", "keh_camera",
    "roberts", "roberts_camera",
})

SOURCE_LABELS = {
    "ebay": "eBay", "ebay_sold": "eBay (Sold)", "ebay_listing": "eBay (Listing)",
    "stockx": "StockX", "amazon_us": "Amazon US", "amazon_com": "Amazon.com",
    "bh": "B&H Photo", "bhphotovideo": "B&H Photo", "b&h": "B&H Photo",
    "adorama": "Adorama", "mpb": "MPB", "mpb_com": "MPB",
    "keh": "KEH Camera", "keh_camera": "KEH Camera",
}


class ManualFallbackCollector:
    """手動CSV海外価格コレクター。"""

    def collect_all(self, product_alias: str, product_id: str) -> list[OverseasPriceResult]:
        """指定商品の全手動CSVエントリを収集する。"""
        usd_jpy, _ = get_usd_jpy()
        eur_jpy, _ = get_eur_jpy()
        now_str = datetime.now(tz=JST).isoformat()

        csv_path = PROJECT_ROOT / "data" / "manual_market_prices.csv"
        if not csv_path.exists():
            return []

        results = []
        try:
            with open(csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    src = (row.get("source") or "").strip().lower()
                    alias = (row.get("product_alias") or "").strip().lower()
                    if alias != product_alias.lower() or src not in OVERSEAS_SOURCES:
                        continue

                    try:
                        price_raw = float(row.get("price") or 0)
                    except (ValueError, TypeError):
                        continue
                    if price_raw <= 0:
                        continue

                    currency = (row.get("currency") or "JPY").strip().upper()
                    if currency == "USD":
                        price_jpy = int(price_raw * usd_jpy)
                        fx = usd_jpy
                    elif currency == "EUR":
                        price_jpy = int(price_raw * eur_jpy)
                        fx = eur_jpy
                    else:
                        price_jpy = int(price_raw)
                        fx = 1.0

                    observed_at = (row.get("observed_at") or now_str).strip()
                    stale = is_stale(observed_at)

                    results.append(OverseasPriceResult(
                        source=src,
                        market=SOURCE_LABELS.get(src, src.upper()),
                        product_id=product_id,
                        product_alias=product_alias,
                        country="US" if currency == "USD" else "EU",
                        currency=currency,
                        price_local=price_raw,
                        fx_rate=fx,
                        price_jpy=price_jpy,
                        confidence="medium",  # 手動入力はmedium
                        listing_count=1,
                        median_price_jpy=price_jpy,
                        min_price_jpy=price_jpy,
                        max_price_jpy=price_jpy,
                        fetched_at=observed_at,
                        stale=stale,
                        failure_reason="" if not stale else "stale_manual",
                        url=(row.get("url") or "").strip(),
                        raw_prices_json=f"[{price_raw}]",
                    ))
        except Exception as e:
            logger.warning("ManualFallback CSV error: %s", e)

        return results

    def get_best(self, product_alias: str, product_id: str) -> Optional[OverseasPriceResult]:
        """最高価格の非staleエントリを返す。"""
        all_results = self.collect_all(product_alias, product_id)
        valid = [r for r in all_results if not r.stale and r.price_jpy > 0]
        if not valid:
            valid = all_results  # staleでもデータがあれば使う
        if not valid:
            return None
        return max(valid, key=lambda r: r.price_jpy)

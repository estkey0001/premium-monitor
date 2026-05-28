"""StockX価格コレクター。

注意: StockXは利用規約でスクレイピングを禁止しています。
このモジュールは manual_market_prices.csv からのデータ読み込みのみを実装します。
将来的にStockX公式APIが提供された場合に対応予定。
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
from src.collectors.overseas.fx_fetcher import get_usd_jpy

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
JST = timezone(timedelta(hours=9))


class StockXCollector:
    """StockX価格コレクター（manual CSVのみ）。

    ToS制約により、自動スクレイピングは実装しない。
    manual_market_prices.csv に source="stockx" として手動入力したデータを読み込む。
    """

    MARKET_NAME = "StockX"
    SOURCE_ID = "stockx"

    def __init__(self):
        self.fx_rates = load_fx_rates()

    def collect(
        self,
        product_id: str,
        product_alias: str,
        keywords: list[str],
    ) -> Optional[OverseasPriceResult]:
        """manual_market_prices.csv から StockX データを読み込む。"""
        usd_jpy, _ = get_usd_jpy()
        now_str = datetime.now(tz=JST).isoformat()

        csv_path = PROJECT_ROOT / "data" / "manual_market_prices.csv"
        if not csv_path.exists():
            return self._failure(product_id, product_alias, usd_jpy, now_str, "csv_not_found")

        rows = []
        try:
            with open(csv_path, encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    src = (row.get("source") or "").strip().lower()
                    alias = (row.get("product_alias") or "").strip().lower()
                    if src == self.SOURCE_ID and alias == product_alias.lower():
                        rows.append(row)
        except Exception as e:
            return self._failure(product_id, product_alias, usd_jpy, now_str, f"csv_error:{e}")

        if not rows:
            return None  # データなし → skip (failureではない)

        # 最新データを使用
        rows.sort(key=lambda r: r.get("observed_at", ""), reverse=True)
        latest = rows[0]

        try:
            price_raw = float(latest.get("price") or 0)
        except (ValueError, TypeError):
            return self._failure(product_id, product_alias, usd_jpy, now_str, "invalid_price")

        currency = (latest.get("currency") or "USD").strip().upper()
        if currency == "USD":
            price_jpy = int(price_raw * usd_jpy)
        elif currency == "JPY":
            price_jpy = int(price_raw)
        else:
            price_jpy = int(price_raw * usd_jpy)  # フォールバック

        stale = is_stale(latest.get("observed_at", ""))

        return OverseasPriceResult(
            source=self.SOURCE_ID,
            market=self.MARKET_NAME,
            product_id=product_id,
            product_alias=product_alias,
            country="US",
            currency=currency,
            price_local=price_raw,
            fx_rate=usd_jpy,
            price_jpy=price_jpy,
            confidence="low",  # 手動入力のためlow固定（実APIなし）
            listing_count=1,
            median_price_jpy=price_jpy,
            min_price_jpy=price_jpy,
            max_price_jpy=price_jpy,
            fetched_at=latest.get("observed_at", now_str),
            stale=stale,
            failure_reason="manual_only_tos_restriction",  # ToS制約を明示
            url=latest.get("url", ""),
            raw_prices_json=f"[{price_raw}]",
        )

    def _failure(self, product_id, product_alias, usd_jpy, now_str, reason):
        return OverseasPriceResult(
            source=self.SOURCE_ID, market=self.MARKET_NAME,
            product_id=product_id, product_alias=product_alias,
            country="US", currency="USD",
            price_local=0.0, fx_rate=usd_jpy, price_jpy=0,
            confidence="low", listing_count=0,
            median_price_jpy=0, min_price_jpy=0, max_price_jpy=0,
            fetched_at=now_str, stale=False,
            failure_reason=reason, url="", raw_prices_json="[]",
        )

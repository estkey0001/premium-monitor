"""Chrono24価格コレクター（時計専門）。

Chrono24の公開検索ページから時計の成約価格を収集する。
時計ジャンル以外はスキップする。
"""
from __future__ import annotations

import json
import logging
import re
import statistics
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent

from src.collectors.overseas.base_overseas import (
    OverseasPriceResult, calc_confidence, load_fx_rates
)
from src.collectors.overseas.fx_fetcher import get_usd_jpy, get_eur_jpy

logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))

# Chrono24 検索URL
CHRONO24_SEARCH_URL = "https://www.chrono24.com/search/index.htm?query={keyword}&dosearch=1&resultview=block&maxAgeInDays=0"

# 対象ジャンル
WATCH_GENRES = {"watch", "watches", "luxury_watch", "時計"}


class Chrono24Collector:
    """Chrono24時計価格コレクター。"""

    def collect(
        self,
        product_id: str,
        product_alias: str,
        keywords: list[str],
        genre: str = "",
    ) -> Optional[OverseasPriceResult]:
        """Chrono24から時計価格を収集する。時計以外はNone。"""
        # 時計ジャンル以外はスキップ
        if genre.lower() not in WATCH_GENRES and not any(
            w in (product_alias + " ".join(keywords)).lower()
            for w in ["watch", "rolex", "omega", "seiko", "casio"]
        ):
            return None

        usd_jpy, _ = get_usd_jpy()
        eur_jpy, _ = get_eur_jpy()
        now_str = datetime.now(tz=JST).isoformat()

        if not keywords:
            return self._failure(product_id, product_alias, eur_jpy, now_str, "no_keywords")

        keyword = keywords[0]
        url = CHRONO24_SEARCH_URL.format(keyword=keyword.replace(" ", "+"))

        prices_eur = self._fetch_chrono24_prices(url)
        if not prices_eur:
            return self._failure(product_id, product_alias, eur_jpy, now_str, "no_listings")

        sorted_p = sorted(prices_eur)
        median_eur = statistics.median(sorted_p)
        min_eur = min(sorted_p)
        max_eur = max(sorted_p)

        median_jpy = int(median_eur * eur_jpy)
        min_jpy = int(min_eur * eur_jpy)
        max_jpy = int(max_eur * eur_jpy)

        confidence = calc_confidence(len(prices_eur), min_jpy, max_jpy, median_jpy)

        return OverseasPriceResult(
            source="chrono24",
            market="Chrono24",
            product_id=product_id,
            product_alias=product_alias,
            country="EU",
            currency="EUR",
            price_local=round(median_eur, 2),
            fx_rate=eur_jpy,
            price_jpy=median_jpy,
            confidence=confidence,
            listing_count=len(prices_eur),
            median_price_jpy=median_jpy,
            min_price_jpy=min_jpy,
            max_price_jpy=max_jpy,
            fetched_at=now_str,
            stale=False,
            failure_reason="",
            url=url,
            raw_prices_json=json.dumps(sorted_p[:20]),
        )

    def _fetch_chrono24_prices(self, url: str) -> list[float]:
        """Chrono24検索ページから価格リストを取得する。"""
        try:
            import requests
            headers = {
                "User-Agent": "Mozilla/5.0 (compatible; PremiumMonitor/1.0)",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            }
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                return []

            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "lxml")
            prices: list[float] = []

            # Chrono24 価格クラス
            for el in soup.select(".price, .article-price, [class*='price']"):
                text = el.get_text(strip=True)
                # EUR価格: "€1,234" or "EUR 1,234"
                m = re.search(r'€\s*([\d,.]+)|EUR\s*([\d,.]+)', text, re.I)
                if m:
                    raw = (m.group(1) or m.group(2)).replace(",", "").replace(".", "")
                    try:
                        p = float(raw)
                        if 100 <= p <= 1000000:
                            prices.append(p)
                    except ValueError:
                        pass

            return prices[:50]  # 最大50件
        except Exception as e:
            logger.debug("Chrono24 fetch failed: %s", e)
            return []

    def _failure(self, product_id, product_alias, eur_jpy, now_str, reason):
        return OverseasPriceResult(
            source="chrono24", market="Chrono24",
            product_id=product_id, product_alias=product_alias,
            country="EU", currency="EUR",
            price_local=0.0, fx_rate=eur_jpy, price_jpy=0,
            confidence="low", listing_count=0,
            median_price_jpy=0, min_price_jpy=0, max_price_jpy=0,
            fetched_at=now_str, stale=False,
            failure_reason=reason, url="", raw_prices_json="[]",
        )

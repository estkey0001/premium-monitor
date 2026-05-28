"""eBay completed listings コレクター。

公開されているeBay成約履歴から価格統計を収集する。

実装方針:
1. eBay Browse API (EBAY_APP_ID 設定時)
2. Playwright HTML scraping (公開ページ、ログイン不要)
3. manual_market_prices.csv フォールバック

注: eBay公開APIは無料アカウントで利用可能。
    Playwright取得は公開ページのみ（ログイン・CAPTCHA突破は行わない）。
"""
from __future__ import annotations

import json
import logging
import os
import re
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.overseas.base_overseas import (
    OverseasPriceResult, calc_confidence, is_stale, load_fx_rates
)
from src.collectors.overseas.fx_fetcher import get_usd_jpy

logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))

# eBay completed listings URL テンプレート
EBAY_SOLD_URL = (
    "https://www.ebay.com/sch/i.html"
    "?_nkw={keyword}"
    "&LH_Complete=1"
    "&LH_Sold=1"
    "&_sop=13"    # 最近の成約順
    "&_ipg=60"    # 60件取得
)

# 価格フィルタ: 極端な外れ値を除外
PRICE_MIN_USD = 10
PRICE_MAX_USD = 50000
# 中央値から何倍以上/以下の価格を除外するか
OUTLIER_RATIO = 3.0


class EbayCompletedCollector:
    """eBay成約価格コレクター。"""

    def __init__(self):
        self.fx_rates = load_fx_rates()

    def collect(
        self,
        product_id: str,
        product_alias: str,
        keywords: list[str],
        condition_filter: str = "new",  # "new", "used", "any"
    ) -> OverseasPriceResult:
        """eBay成約価格を収集する。

        Args:
            product_id: 商品ID (例: "prod_gr4")
            product_alias: 商品エイリアス (例: "gr4")
            keywords: 検索キーワードリスト (最初のキーワードを使用)
            condition_filter: 状態フィルタ ("new", "used", "any")

        Returns:
            OverseasPriceResult
        """
        if not keywords:
            return self._failure(product_id, product_alias, "no keywords")

        keyword = keywords[0]
        url = EBAY_SOLD_URL.format(keyword=keyword.replace(" ", "+"))
        now_str = datetime.now(tz=JST).isoformat()
        usd_jpy, fx_source = get_usd_jpy()

        # 価格リスト取得
        prices_usd = self._fetch_prices(url, condition_filter)

        if not prices_usd or len(prices_usd) < 1:
            return OverseasPriceResult(
                source="ebay_completed",
                market="eBay (Sold)",
                product_id=product_id,
                product_alias=product_alias,
                country="US",
                currency="USD",
                price_local=0.0,
                fx_rate=usd_jpy,
                price_jpy=0,
                confidence="low",
                listing_count=0,
                median_price_jpy=0,
                min_price_jpy=0,
                max_price_jpy=0,
                fetched_at=now_str,
                stale=False,
                failure_reason="no_sold_listings",
                url=url,
                raw_prices_json="[]",
            )

        # 外れ値除去
        prices_usd = self._remove_outliers(prices_usd)
        sorted_prices = sorted(prices_usd)
        median_usd = statistics.median(sorted_prices)
        min_usd = min(sorted_prices)
        max_usd = max(sorted_prices)

        median_jpy = int(median_usd * usd_jpy)
        min_jpy = int(min_usd * usd_jpy)
        max_jpy = int(max_usd * usd_jpy)

        confidence = calc_confidence(
            listing_count=len(prices_usd),
            min_jpy=min_jpy,
            max_jpy=max_jpy,
            median_jpy=median_jpy,
        )

        logger.info(
            "eBay [%s] keyword='%s' count=%d median=$%.0f(¥%s) conf=%s fx_src=%s",
            product_alias, keyword, len(prices_usd),
            median_usd, f"{median_jpy:,}", confidence, fx_source
        )

        return OverseasPriceResult(
            source="ebay_completed",
            market="eBay (Sold)",
            product_id=product_id,
            product_alias=product_alias,
            country="US",
            currency="USD",
            price_local=round(median_usd, 2),
            fx_rate=usd_jpy,
            price_jpy=median_jpy,
            confidence=confidence,
            listing_count=len(prices_usd),
            median_price_jpy=median_jpy,
            min_price_jpy=min_jpy,
            max_price_jpy=max_jpy,
            fetched_at=now_str,
            stale=False,
            failure_reason="",
            url=url,
            raw_prices_json=json.dumps(sorted_prices[:20]),  # 上位20件のみ保存
        )

    def _fetch_prices(self, url: str, condition_filter: str) -> list[float]:
        """eBayページから価格リストを取得する。"""
        # Playwright試行
        prices = self._fetch_via_playwright(url, condition_filter)
        if prices:
            return prices

        # HTMLフォールバック (requests)
        prices = self._fetch_via_requests(url)
        if prices:
            return prices

        return []

    def _fetch_via_playwright(self, url: str, condition_filter: str) -> list[float]:
        """Playwright経由でeBayページを取得・パースする。"""
        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            logger.debug("playwright not available")
            return []

        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=["--no-sandbox", "--disable-dev-shm-usage"],
                )
                ctx = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    locale="en-US",
                    viewport={"width": 1280, "height": 800},
                )
                page = ctx.new_page()
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
                page.wait_for_timeout(2000)
                html = page.content()
                browser.close()

            if "Access Denied" in html or "Robot Check" in html or len(html) < 2000:
                logger.warning("eBay: access denied or empty page")
                return []

            return self._parse_ebay_html(html, condition_filter)

        except Exception as e:
            logger.warning("eBay Playwright failed: %s", e)
            return []

    def _fetch_via_requests(self, url: str) -> list[float]:
        """requestsでHTMLを取得する（フォールバック）。"""
        try:
            import requests
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
            }
            resp = requests.get(url, headers=headers, timeout=20)
            if resp.status_code != 200:
                return []
            return self._parse_ebay_html(resp.text, "any")
        except Exception as e:
            logger.debug("eBay requests failed: %s", e)
            return []

    def _parse_ebay_html(self, html: str, condition_filter: str) -> list[float]:
        """eBay HTMLから価格を抽出する。"""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "lxml")
        prices: list[float] = []

        # メイン価格クラス: .s-item__price
        for el in soup.select(".s-item__price"):
            text = el.get_text(strip=True)
            # "US $1,234.56" or "$1,234.56" をパース
            m = re.search(r'\$([\d,]+(?:\.\d+)?)', text)
            if m:
                try:
                    p = float(m.group(1).replace(",", ""))
                    if PRICE_MIN_USD <= p <= PRICE_MAX_USD:
                        prices.append(p)
                except ValueError:
                    pass

        # 取れなければ全体から探す
        if not prices:
            for m in re.finditer(r'US \$([\d,]+(?:\.\d+)?)', html):
                try:
                    p = float(m.group(1).replace(",", ""))
                    if PRICE_MIN_USD <= p <= PRICE_MAX_USD:
                        prices.append(p)
                except ValueError:
                    pass

        logger.debug("eBay parse: found %d prices", len(prices))
        return prices

    def _remove_outliers(self, prices: list[float]) -> list[float]:
        """中央値からOUTLIER_RATIO倍以上離れた価格を除外する。"""
        if len(prices) < 3:
            return prices
        med = statistics.median(prices)
        if med <= 0:
            return prices
        return [
            p for p in prices
            if (med / OUTLIER_RATIO) <= p <= (med * OUTLIER_RATIO)
        ]

    def _failure(self, product_id: str, product_alias: str, reason: str) -> OverseasPriceResult:
        usd_jpy, _ = get_usd_jpy()
        now_str = datetime.now(tz=JST).isoformat()
        return OverseasPriceResult(
            source="ebay_completed",
            market="eBay (Sold)",
            product_id=product_id,
            product_alias=product_alias,
            country="US",
            currency="USD",
            price_local=0.0,
            fx_rate=usd_jpy,
            price_jpy=0,
            confidence="low",
            listing_count=0,
            median_price_jpy=0,
            min_price_jpy=0,
            max_price_jpy=0,
            fetched_at=now_str,
            stale=False,
            failure_reason=reason,
            url="",
            raw_prices_json="[]",
        )

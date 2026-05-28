"""eBay completed listings コレクター。

取得優先順位:
1. eBay Finding API (EBAY_APP_ID または EBAY_CLIENT_ID 環境変数が設定されている場合)
2. HTML scraping フォールバック (ローカル実行時のみ有効)
   - GitHub Actions の Cloud IP は eBay にブロックされるため site_blocked として正常分類
3. 結果なし → listing_count=0 / failure_reason=site_blocked

collector_method:
  "api"          eBay Finding API 成功
  "html"         HTML scraping 成功
  "html_blocked" HTML scraping でアクセス拒否/ブロック検出
  "unknown"      未実行・エラー

絶対禁止: 自動購入・CAPTCHA突破・ログイン突破・高頻度アクセス
"""
from __future__ import annotations

import json
import logging
import os
import re
import statistics
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.collectors.overseas.base_overseas import (
    OverseasPriceResult, is_stale, load_fx_rates
)
from src.collectors.overseas.fx_fetcher import get_usd_jpy

logger = logging.getLogger(__name__)
JST = timezone(timedelta(hours=9))

# eBay Finding API エンドポイント
FINDING_API_URL = "https://svcs.ebay.com/services/search/FindingService/v1"
FINDING_API_GLOBAL_ID = "EBAY-US"
FINDING_API_VERSION = "1.0.0"

# eBay sold URL テンプレート（HTML fallback 用）
EBAY_SOLD_URL = (
    "https://www.ebay.com/sch/i.html"
    "?_nkw={keyword}"
    "&LH_Complete=1"
    "&LH_Sold=1"
    "&_sop=13"    # 最近の成約順
    "&_ipg=60"    # 60件取得
)

# 価格フィルタ
PRICE_MIN_USD = 10
PRICE_MAX_USD = 50000
OUTLIER_RATIO = 3.0

# eBay condition ID
# 1000=New, 1500=New other (see developer.ebay.com/devzone/finding/callref/extra/ItemFilterType.Condition.html)
CONDITION_IDS_NEW = ["1000", "1500"]

# HTML アクセス拒否シグナル
_BLOCKED_SIGNALS = (
    "Access Denied",
    "Robot Check",
    "Sign in to confirm",
    "Just a moment",
    "cf-error",
    "Captcha",
    "captcha",
    "verify you are human",
    "eBay requires JavaScript",
)


def _ebay_app_id() -> Optional[str]:
    """EBAY_APP_ID または EBAY_CLIENT_ID 環境変数から App ID を返す。"""
    return os.environ.get("EBAY_APP_ID") or os.environ.get("EBAY_CLIENT_ID") or None


def _calc_confidence_ebay(listing_count: int, spread: float) -> str:
    """eBay API 向けの confidence 計算。
    high: 5件以上 + 乖離 < 30%
    medium: 2-4件 + 乖離 < 60%
    low: 1件以下
    """
    if listing_count <= 0:
        return "low"
    if listing_count >= 5 and spread < 0.30:
        return "high"
    elif listing_count >= 2 and spread < 0.60:
        return "medium"
    else:
        return "low"


class EbayCompletedCollector:
    """eBay成約価格コレクター（Finding API → HTML fallback → blocked分類）。"""

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
            OverseasPriceResult (collector_method: "api" / "html" / "html_blocked" / "unknown")
        """
        if not keywords:
            return self._failure(product_id, product_alias, "no_keywords", "unknown")

        keyword = keywords[0]
        url = EBAY_SOLD_URL.format(keyword=keyword.replace(" ", "+"))
        usd_jpy, fx_source = get_usd_jpy()
        now_str = datetime.now(tz=JST).isoformat()

        app_id = _ebay_app_id()

        # --- 1. eBay Finding API ---
        if app_id:
            prices_usd, api_url, api_error = self._fetch_via_api(
                keyword=keyword,
                app_id=app_id,
                condition_filter=condition_filter,
            )
            if prices_usd:
                logger.info(
                    "eBay API [%s] keyword='%s' count=%d fx_src=%s",
                    product_alias, keyword, len(prices_usd), fx_source,
                )
                return self._build_result(
                    product_id=product_id,
                    product_alias=product_alias,
                    prices_usd=prices_usd,
                    usd_jpy=usd_jpy,
                    url=api_url or url,
                    now_str=now_str,
                    collector_method="api",
                )
            elif api_error:
                logger.warning("eBay API [%s] error: %s", product_alias, api_error)
                # API エラー時は HTML fallback へ
        else:
            logger.debug("eBay: EBAY_APP_ID 未設定 → HTML fallback へ")

        # --- 2. HTML scraping fallback ---
        prices_usd, is_blocked = self._fetch_via_html(url, condition_filter)

        if is_blocked:
            # GitHub Actions の Cloud IP がブロックされた場合 → 正常分類
            logger.info(
                "eBay [%s] HTML blocked (site_blocked) — GitHub Actions cloud IP is blocked by eBay. "
                "Set EBAY_APP_ID to use the Finding API instead.",
                product_alias,
            )
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
                failure_reason="site_blocked",
                url=url,
                raw_prices_json="[]",
                collector_method="html_blocked",
            )

        if prices_usd:
            logger.info(
                "eBay HTML [%s] keyword='%s' count=%d fx_src=%s",
                product_alias, keyword, len(prices_usd), fx_source,
            )
            return self._build_result(
                product_id=product_id,
                product_alias=product_alias,
                prices_usd=prices_usd,
                usd_jpy=usd_jpy,
                url=url,
                now_str=now_str,
                collector_method="html",
            )

        # --- 3. 価格取得なし ---
        logger.info("eBay [%s] no prices found", product_alias)
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
            collector_method="unknown",
        )

    def _build_result(
        self,
        product_id: str,
        product_alias: str,
        prices_usd: list[float],
        usd_jpy: float,
        url: str,
        now_str: str,
        collector_method: str,
    ) -> OverseasPriceResult:
        """価格リストから OverseasPriceResult を構築する。"""
        prices_usd = self._remove_outliers(prices_usd)
        sorted_prices = sorted(prices_usd)
        median_usd = statistics.median(sorted_prices)
        min_usd = min(sorted_prices)
        max_usd = max(sorted_prices)

        median_jpy = int(median_usd * usd_jpy)
        min_jpy = int(min_usd * usd_jpy)
        max_jpy = int(max_usd * usd_jpy)

        spread = (max_jpy - min_jpy) / median_jpy if median_jpy > 0 else 1.0
        confidence = _calc_confidence_ebay(len(sorted_prices), spread)

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
            listing_count=len(sorted_prices),
            median_price_jpy=median_jpy,
            min_price_jpy=min_jpy,
            max_price_jpy=max_jpy,
            fetched_at=now_str,
            stale=False,
            failure_reason="",
            url=url,
            raw_prices_json=json.dumps(sorted_prices[:20]),
            collector_method=collector_method,
        )

    # ─────────────────────────────────────────────────────────────
    # eBay Finding API
    # ─────────────────────────────────────────────────────────────

    def _fetch_via_api(
        self,
        keyword: str,
        app_id: str,
        condition_filter: str,
    ) -> tuple[list[float], str, str]:
        """eBay Finding API を呼び出して成約価格リストを返す。

        Returns:
            (prices_usd, api_url, error_message)
            成功時: (prices, url, "")
            失敗時: ([], "", error_message)
        """
        try:
            params = {
                "OPERATION-NAME": "findCompletedItems",
                "SERVICE-VERSION": FINDING_API_VERSION,
                "SECURITY-APPNAME": app_id,
                "RESPONSE-DATA-FORMAT": "JSON",
                "REST-PAYLOAD": "",
                "keywords": keyword,
                "GLOBAL-ID": FINDING_API_GLOBAL_ID,
                "paginationInput.entriesPerPage": "100",
                "sortOrder": "EndTimeSoonest",
                # SoldItemsOnly フィルタ
                "itemFilter(0).name": "SoldItemsOnly",
                "itemFilter(0).value": "true",
            }

            # 新品・未使用フィルタ
            if condition_filter == "new":
                params["itemFilter(1).name"] = "Condition"
                for i, cid in enumerate(CONDITION_IDS_NEW):
                    params[f"itemFilter(1).value({i})"] = cid

            query_string = urllib.parse.urlencode(params)
            api_url = f"{FINDING_API_URL}?{query_string}"

            req = urllib.request.Request(
                api_url,
                headers={"Accept": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=20) as resp:
                raw = resp.read().decode("utf-8")

            data = json.loads(raw)
            prices = self._parse_api_response(data)
            return prices, api_url, ""

        except urllib.error.HTTPError as e:
            return [], "", f"http_{e.code}: {e.reason}"
        except Exception as e:
            return [], "", str(e)[:200]

    def _parse_api_response(self, data: dict) -> list[float]:
        """Finding API の JSON レスポンスから価格リストを取得する。"""
        try:
            # ネストされたレスポンス構造を展開
            resp = data.get("findCompletedItemsResponse", [{}])
            if isinstance(resp, list):
                resp = resp[0]

            ack = resp.get("ack", [""])[0]
            if ack.lower() != "success":
                logger.warning("eBay API ack=%s", ack)
                return []

            search_result = resp.get("searchResult", [{}])
            if isinstance(search_result, list):
                search_result = search_result[0]

            items = search_result.get("item", [])
            prices: list[float] = []

            for item in items:
                # sellingStatus.currentPrice[0].__value__
                selling = item.get("sellingStatus", [{}])
                if isinstance(selling, list):
                    selling = selling[0]
                current_price = selling.get("currentPrice", [{}])
                if isinstance(current_price, list):
                    current_price = current_price[0]
                price_val = current_price.get("__value__") or current_price.get("value")
                if price_val is not None:
                    try:
                        p = float(price_val)
                        if PRICE_MIN_USD <= p <= PRICE_MAX_USD:
                            prices.append(p)
                    except (ValueError, TypeError):
                        pass

            logger.debug("eBay API parse: %d prices", len(prices))
            return prices

        except Exception as e:
            logger.warning("eBay API parse error: %s", e)
            return []

    # ─────────────────────────────────────────────────────────────
    # HTML scraping fallback
    # ─────────────────────────────────────────────────────────────

    def _fetch_via_html(
        self, url: str, condition_filter: str
    ) -> tuple[list[float], bool]:
        """HTML scraping で価格を取得する。

        Returns:
            (prices_usd, is_blocked)
            is_blocked=True の場合は site_blocked として扱う。
        """
        # Playwright 試行
        prices, is_blocked = self._fetch_via_playwright(url, condition_filter)
        if is_blocked:
            return [], True
        if prices:
            return prices, False

        # requests フォールバック
        prices, is_blocked = self._fetch_via_requests(url)
        if is_blocked:
            return [], True
        return prices, False

    def _is_blocked(self, html: str) -> bool:
        """HTML レスポンスがアクセス拒否/ブロックページかどうかを判定する。"""
        if len(html) < 500:
            return True  # コンテンツが非常に短い = ブロックの可能性
        return any(signal in html for signal in _BLOCKED_SIGNALS)

    def _fetch_via_playwright(
        self, url: str, condition_filter: str
    ) -> tuple[list[float], bool]:
        """Playwright経由でeBayページを取得・パースする。

        Returns:
            (prices, is_blocked)
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.debug("playwright not available")
            return [], False

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

            if self._is_blocked(html):
                logger.info("eBay Playwright: blocked page detected")
                return [], True

            prices = self._parse_ebay_html(html, condition_filter)
            return prices, False

        except Exception as e:
            logger.warning("eBay Playwright failed: %s", e)
            return [], False

    def _fetch_via_requests(self, url: str) -> tuple[list[float], bool]:
        """requests でHTMLを取得する（フォールバック）。

        Returns:
            (prices, is_blocked)
        """
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
            # 403/429/503 は Cloud IP ブロックとして html_blocked 分類
            if resp.status_code in (403, 429, 503):
                logger.info("eBay requests: status %d → html_blocked", resp.status_code)
                return [], True
            if resp.status_code != 200:
                logger.warning("eBay requests: status %d", resp.status_code)
                return [], False
            if self._is_blocked(resp.text):
                return [], True
            return self._parse_ebay_html(resp.text, "any"), False
        except Exception as e:
            logger.debug("eBay requests failed: %s", e)
            return [], False

    def _parse_ebay_html(self, html: str, condition_filter: str) -> list[float]:
        """eBay HTMLから価格を抽出する。"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, "lxml")
        except ImportError:
            soup = None

        prices: list[float] = []

        if soup:
            for el in soup.select(".s-item__price"):
                text = el.get_text(strip=True)
                m = re.search(r'\$([\d,]+(?:\.\d+)?)', text)
                if m:
                    try:
                        p = float(m.group(1).replace(",", ""))
                        if PRICE_MIN_USD <= p <= PRICE_MAX_USD:
                            prices.append(p)
                    except ValueError:
                        pass
        else:
            # BeautifulSoup 未使用時は正規表現で抽出
            for m in re.finditer(r'US \$([\d,]+(?:\.\d+)?)', html):
                try:
                    p = float(m.group(1).replace(",", ""))
                    if PRICE_MIN_USD <= p <= PRICE_MAX_USD:
                        prices.append(p)
                except ValueError:
                    pass

        # 取れなければ全体から探す
        if not prices:
            for m in re.finditer(r'\$([\d,]+(?:\.\d{2}))', html):
                try:
                    p = float(m.group(1).replace(",", ""))
                    if PRICE_MIN_USD <= p <= PRICE_MAX_USD:
                        prices.append(p)
                except ValueError:
                    pass

        logger.debug("eBay HTML parse: found %d prices", len(prices))
        return prices

    # ─────────────────────────────────────────────────────────────
    # ユーティリティ
    # ─────────────────────────────────────────────────────────────

    def _remove_outliers(self, prices: list[float]) -> list[float]:
        """中央値から OUTLIER_RATIO 倍以上離れた価格を除外する。"""
        if len(prices) < 3:
            return prices
        med = statistics.median(prices)
        if med <= 0:
            return prices
        return [
            p for p in prices
            if (med / OUTLIER_RATIO) <= p <= (med * OUTLIER_RATIO)
        ]

    def _failure(
        self,
        product_id: str,
        product_alias: str,
        reason: str,
        collector_method: str = "unknown",
    ) -> OverseasPriceResult:
        """エラー時の OverseasPriceResult を返す。"""
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
            collector_method=collector_method,
        )

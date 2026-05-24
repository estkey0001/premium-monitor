"""買取価格CSVアップデート用 軽量基底コレクター。
DB・Pydantic不要。requestsとBeautifulSoupのみ使用。
"""
import logging
import re
import time
from abc import abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

JST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)


class BaseCsvBuybackCollector:
    """CSVアップデート専用の軽量買取価格コレクター。"""

    SHOP_ID: str = ""       # CSV の buyback_shop 値
    SHOP_NAME: str = ""     # 表示用名称
    BASE_URL: str = ""
    REQUIRES_JS: bool = False

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.last_failure_reason: Optional[str] = None  # 最後の失敗理由（report用）
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (compatible; PremiumMonitor/1.0; +https://github.com/estkey0001/premium-monitor)",
            "Accept-Language": "ja,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def fetch(self, product_alias: str, product_name: str, condition: str = "new_unopened_simfree") -> Optional[dict]:
        """価格取得。成功→dict, 失敗→None。失敗理由は last_failure_reason に保存。"""
        self.last_failure_reason = None
        url = self._build_url(product_alias, product_name)
        if not url:
            logger.info("[%s] No URL defined for %s", self.SHOP_NAME, product_alias)
            self.last_failure_reason = "no_url"
            return None

        try:
            html = self._fetch_html(url)
            if not html:
                logger.warning("[%s] Empty HTML for %s", self.SHOP_NAME, product_alias)
                if self.last_failure_reason is None:
                    self.last_failure_reason = "empty_html"
                return None

            price = self._parse_price(html, product_alias, product_name)
            if not price or price <= 0:
                logger.info("[%s] Price not found for %s", self.SHOP_NAME, product_alias)
                self.last_failure_reason = "price_not_found"
                return None

            actual_url = self._parse_detail_url(html, url)
            return {
                "product_alias": product_alias,
                "shop_id": self.SHOP_ID,
                "shop_name": self.SHOP_NAME,
                "buyback_price": price,
                "condition": condition,
                "url": actual_url,
                "link_verified": "true",
                "observed_at": datetime.now(tz=JST).isoformat(timespec="seconds"),
                "data_source": "auto_scraped",
            }
        except Exception as e:
            logger.warning("[%s] Error fetching %s: %s", self.SHOP_NAME, product_alias, e)
            if self.last_failure_reason is None:
                self.last_failure_reason = f"exception_{type(e).__name__}"
            return None

    def _fetch_html(self, url: str) -> Optional[str]:
        try:
            time.sleep(1.5)  # レートリミット遵守
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            if self.REQUIRES_JS and len(resp.text) < 3000:
                return self._fetch_with_playwright(url)
            return resp.text
        except requests.HTTPError as e:
            status = e.response.status_code if (hasattr(e, 'response') and e.response is not None) else 0
            self.last_failure_reason = f"http_{status}" if status else "http_error"
            logger.warning("[%s] HTTP error %s: %s", self.SHOP_NAME, url, e)
            if self.REQUIRES_JS:
                return self._fetch_with_playwright(url)
            return None
        except requests.exceptions.SSLError as e:
            self.last_failure_reason = "ssl_error"
            logger.warning("[%s] SSL error %s: %s", self.SHOP_NAME, url, e)
            if self.REQUIRES_JS:
                return self._fetch_with_playwright(url)
            return None
        except requests.RequestException as e:
            self.last_failure_reason = "connection_error"
            logger.warning("[%s] HTTP error %s: %s", self.SHOP_NAME, url, e)
            if self.REQUIRES_JS:
                return self._fetch_with_playwright(url)
            return None

    def _fetch_with_playwright(self, url: str) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    user_agent="Mozilla/5.0 (compatible; PremiumMonitor/1.0)"
                )
                page.goto(url, timeout=25000)
                page.wait_for_load_state("networkidle", timeout=12000)
                html = page.content()
                browser.close()
                return html
        except ImportError:
            logger.debug("[%s] Playwright not installed", self.SHOP_NAME)
            return None
        except Exception as e:
            logger.warning("[%s] Playwright error: %s", self.SHOP_NAME, e)
            return None

    @abstractmethod
    def _build_url(self, product_alias: str, product_name: str) -> str:
        """商品エイリアスに対応するURLを返す。"""
        ...

    @abstractmethod
    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        """HTMLから買取価格（円）を返す。見つからない場合はNone。"""
        ...

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return fallback_url

    @staticmethod
    def extract_price(text: str, min_price: int = 10000, max_price: int = 5_000_000) -> Optional[int]:
        """テキストから買取価格を抽出する汎用ヘルパー。"""
        patterns = [
            r'[¥￥]\s*([\d,]+)',
            r'([\d,]+)\s*円',
        ]
        prices = []
        for pat in patterns:
            for m in re.finditer(pat, text):
                try:
                    p = int(m.group(1).replace(",", ""))
                    if min_price <= p <= max_price:
                        prices.append(p)
                except ValueError:
                    pass
        return max(prices) if prices else None  # 最高買取価格を返す

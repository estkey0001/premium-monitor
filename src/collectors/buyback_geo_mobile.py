"""ゲオモバイル 買取価格コレクター。
URL: https://geomobile.jp/ (スマホ特化の買取)
取得方式: Playwright（Cloudflare対策 — ブラウザ風UA + inner_text()）
検索URL方式（URLスラッグ推測禁止）

注意: geomobile.jp は Cloudflare 保護下にあり、requests では SSL/タイムアウトが発生する。
     Playwright でブラウザ風UAを使用してアクセスする。
"""
import logging
import re
import time
from typing import Optional

from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

logger = logging.getLogger(__name__)


def _search_url(keyword: str) -> str:
    import urllib.parse
    encoded = urllib.parse.quote(keyword)
    return f"https://geomobile.jp/purchase/search/?q={encoded}"


SEARCH_KEYWORDS = {
    "iphone17pro256": "iPhone 17 Pro 256GB",
    "iphone17pro512": "iPhone 17 Pro 512GB",
    "iphone17pm256":  "iPhone 17 Pro Max 256GB",
    "iphone17pm512":  "iPhone 17 Pro Max 512GB",
}

# inner_text() から取得したプレーンテキスト向けのパターン
DIRECT_PATTERNS = {
    "iphone17pro256": [
        r'iPhone 17 Pro\s+256.{0,200}?([\d]{2,3},\d{3})円',
        r'iPhone 17 Pro\s+256.{0,200}?¥\s*([\d,]+)',
        r'256.{0,100}?([\d]{2,3},\d{3})円',
    ],
    "iphone17pro512": [
        r'iPhone 17 Pro\s+512.{0,200}?([\d]{2,3},\d{3})円',
        r'iPhone 17 Pro\s+512.{0,200}?¥\s*([\d,]+)',
        r'512.{0,100}?([\d]{2,3},\d{3})円',
    ],
    "iphone17pm256": [
        r'iPhone 17 Pro Max\s+256.{0,200}?([\d]{2,3},\d{3})円',
        r'iPhone 17 Pro Max\s+256.{0,200}?¥\s*([\d,]+)',
        r'Pro Max.{0,50}256.{0,100}?([\d]{2,3},\d{3})円',
    ],
    "iphone17pm512": [
        r'iPhone 17 Pro Max\s+512.{0,200}?([\d]{2,3},\d{3})円',
        r'iPhone 17 Pro Max\s+512.{0,200}?¥\s*([\d,]+)',
        r'Pro Max.{0,50}512.{0,100}?([\d]{2,3},\d{3})円',
    ],
}


class GeoMobileCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "geo_mobile"
    SHOP_NAME = "ゲオモバイル"
    BASE_URL  = "https://geomobile.jp/"
    REQUIRES_JS = True  # Cloudflare保護のため Playwright 必須

    def _build_url(self, product_alias: str, product_name: str) -> str:
        kw = SEARCH_KEYWORDS.get(product_alias)
        return _search_url(kw) if kw else ""

    def _fetch_html(self, url: str) -> Optional[str]:
        """Playwright でブラウザ風UAを使用してアクセス (Cloudflare対策)。
        inner_text() を返す（BS4 解析ではなく plain text で処理）。
        """
        time.sleep(2)  # レートリミット遵守
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/120.0.0.0 Safari/537.36"
                    ),
                    extra_http_headers={
                        "Accept-Language": "ja,en;q=0.9",
                        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                    },
                )
                page = context.new_page()
                page.goto(url, timeout=30000, wait_until="domcontentloaded")
                page.wait_for_timeout(3000)  # JS描画待機
                text = page.inner_text("body")
                browser.close()
                self.last_failure_reason = None  # 成功時はリセット
                return text
        except ImportError:
            logger.warning("[ゲオモバイル] Playwright not installed")
            self.last_failure_reason = "playwright_not_installed"
            return None
        except Exception as e:
            err_str = str(e).lower()
            if "timeout" in err_str:
                self.last_failure_reason = "cloudflare_timeout"
            elif "ssl" in err_str:
                self.last_failure_reason = "ssl_error"
            else:
                self.last_failure_reason = f"playwright_error"
            logger.warning("[ゲオモバイル] Playwright error: %s", e)
            return None

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        """html は Playwright inner_text() の plain text。"""
        text = html  # inner_text() をそのまま使用

        for pat in DIRECT_PATTERNS.get(product_alias, []):
            m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass

        return None

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return fallback_url

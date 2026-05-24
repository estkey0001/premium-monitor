"""モバイル一番 買取価格コレクター（CSV更新用）。
URL: https://www.mobile-ichiban.com/ (トップページに買取価格一覧)
実装: Playwright (JS動的ロード) + inner_text() + 直接regex
価格形式: 新品\n178,000円 (カンマ区切り + 円)

対応商品:
- iPhone 17 Pro 256/512GB → 確認済み
- iPhone 17 Pro Max 256/512GB → 確認済み
- PS5 Pro (CFI-7000B01) → 確認済み
- Nintendo Switch 2 → 未掲載 (スキップ)
"""
import logging
import re
import time
from typing import Optional

from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

logger = logging.getLogger(__name__)

# トップページに全商品の価格が掲載
PRODUCT_URLS = {
    "iphone17pro256":  "https://www.mobile-ichiban.com/",
    "iphone17pro512":  "https://www.mobile-ichiban.com/",
    "iphone17pm256":   "https://www.mobile-ichiban.com/",
    "iphone17pm512":   "https://www.mobile-ichiban.com/",
    "switch2":         "",   # 未掲載 → スキップ
    "ps5_pro":         "https://www.mobile-ichiban.com/",
}

# 商品特定用の直接正規表現パターン (Playwright inner_text に適用)
# テキスト例: "iPhone 17 Pro 256GB\nsimfree未開封 \xa0\n\xa0\n新品\n178,000円"
# 注意: "iPhone 17 Pro 256GB" は "iPhone 17 Pro Max 256GB" にはマッチしない (Max が間にある)
PRICE_PATTERNS = {
    "iphone17pro256": r'iPhone 17 Pro 256GB.*?新品\n([\d,]+)円',
    "iphone17pro512": r'iPhone 17 Pro 512GB.*?新品\n([\d,]+)円',
    "iphone17pm256":  r'iPhone 17 Pro Max 256GB.*?新品\n([\d,]+)円',
    "iphone17pm512":  r'iPhone 17 Pro Max 512GB.*?新品\n([\d,]+)円',
    "ps5_pro":        r'PlayStation 5 Pro.*?新品\n([\d,]+)円',
}


class MobileIchibanCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "mobile_ichiban"
    SHOP_NAME = "モバイル一番"
    BASE_URL  = "https://www.mobile-ichiban.com/"
    REQUIRES_JS = True

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def _fetch_html(self, url: str) -> Optional[str]:
        """JS動的ロードのため、常にPlaywrightを使用。inner_text()を返す。"""
        time.sleep(1.5)  # レートリミット遵守
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(
                    user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                )
                page.goto(url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=15000)
                page.wait_for_timeout(5000)  # JS描画完了まで待機
                text = page.inner_text("body")
                browser.close()
                return text
        except ImportError:
            logger.warning("[モバイル一番] Playwright not installed")
            return None
        except Exception as e:
            logger.warning("[モバイル一番] Playwright error: %s", e)
            return None

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        """html は Playwright inner_text() の plain text (BS4 不使用)。"""
        text = html  # inner_text() はそのまま使用

        pat = PRICE_PATTERNS.get(product_alias)
        if pat:
            m = re.search(pat, text, re.DOTALL)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass

        # フォールバック: simfree未開封 + 新品 の価格
        for fallback_pat in [
            r'simfree未開封.*?新品\n([\d,]+)円',
            r'新品\n([\d,]+)円',
        ]:
            m = re.search(fallback_pat, text, re.DOTALL)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass

        return self.extract_price(text)

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return "https://www.mobile-ichiban.com/"

"""買取一丁目 買取価格コレクター（CSV更新用）。
URL: https://www.1-chome.com/ (トップページの強化買取商品一覧)
実装: Playwright (SPA) + inner_text() + 直接regex
価格形式: 未開封\n¥178,000 (円記号 + カンマ区切り数字)

対応商品:
- iPhone 17 Pro 256/512GB → 確認済み
- iPhone 17 Pro Max 256/512GB → 確認済み
- Nintendo Switch 2 / PS5 Pro → 未掲載 (スキップ)
"""
import logging
import re
import time
from typing import Optional

from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

logger = logging.getLogger(__name__)

# トップページに強化買取商品の価格が掲載
PRODUCT_URLS = {
    "iphone17pro256":  "https://www.1-chome.com/",
    "iphone17pro512":  "https://www.1-chome.com/",
    "iphone17pm256":   "https://www.1-chome.com/",
    "iphone17pm512":   "https://www.1-chome.com/",
    "switch2":         "",  # 未掲載 → スキップ
    "ps5_pro":         "",  # 未掲載 → スキップ
}

# 商品特定用の直接正規表現パターン (Playwright inner_text に適用)
# テキスト例: "iPhone 17 Pro 256GB\n\n新品\n\n未開封\n¥178,000\n開封済未使用品\n¥168,000"
# [\s\n]+ で空白/改行の表記揺れ（\xa0 含む）に対応
PRICE_PATTERNS = {
    "iphone17pro256": r'iPhone 17 Pro 256GB.*?未開封[\s\n]+¥([\d,]+)',
    "iphone17pro512": r'iPhone 17 Pro 512GB.*?未開封[\s\n]+¥([\d,]+)',
    "iphone17pm256":  r'iPhone 17 Pro Max 256GB.*?未開封[\s\n]+¥([\d,]+)',
    "iphone17pm512":  r'iPhone 17 Pro Max 512GB.*?未開封[\s\n]+¥([\d,]+)',
}

# 緩いフォールバックパターン: 商品名から500文字以内の ¥N,NNN
FALLBACK_PATTERNS = {
    "iphone17pro256": r'iPhone 17 Pro 256GB.{0,500}?¥([\d,]+)',
    "iphone17pro512": r'iPhone 17 Pro 512GB.{0,500}?¥([\d,]+)',
    "iphone17pm256":  r'iPhone 17 Pro Max 256GB.{0,500}?¥([\d,]+)',
    "iphone17pm512":  r'iPhone 17 Pro Max 512GB.{0,500}?¥([\d,]+)',
}


class KaitoriItchomeCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "kaitori_itchome"
    SHOP_NAME = "買取一丁目"
    BASE_URL  = "https://www.1-chome.com/"
    REQUIRES_JS = True  # SPA のため Playwright 必須

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def _fetch_html(self, url: str) -> Optional[str]:
        """SPA のため、常にPlaywrightを使用。inner_text()を返す。"""
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
                page.wait_for_timeout(5000)  # SPA描画完了まで待機（3000→5000ms）
                text = page.inner_text("body")
                browser.close()
                return text
        except ImportError:
            logger.warning("[買取一丁目] Playwright not installed")
            return None
        except Exception as e:
            logger.warning("[買取一丁目] Playwright error: %s", e)
            return None

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        """html は Playwright inner_text() の plain text (BS4 不使用)。"""
        text = html  # inner_text() をそのまま使用

        # ── Step1: メインパターン（[\s\n]+ で空白表記揺れ吸収）──
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

        # ── Step2: 緩いフォールバックパターン ──
        fb_pat = FALLBACK_PATTERNS.get(product_alias)
        if fb_pat:
            m = re.search(fb_pat, text, re.DOTALL)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass

        # ── Step3: ¥N,NNN 形式の最大価格 ──
        prices = []
        for m in re.finditer(r'¥([\d,]+)', text):
            try:
                p = int(m.group(1).replace(",", ""))
                if 10000 <= p <= 5_000_000:
                    prices.append(p)
            except ValueError:
                pass
        return max(prices) if prices else None

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return "https://www.1-chome.com/"

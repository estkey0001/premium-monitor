"""買取一丁目 買取価格コレクター（CSV更新用）。
URL: https://www.1-chome.com/keitai/search/[商品名]
注: SPA (JavaScript レンダリング必須)。Playwright を使用。
"""
import re
from urllib.parse import quote
from typing import Optional
from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

# 検索URL形式: /keitai/search/[URLエンコードされた商品名]
PRODUCT_SEARCH_QUERIES = {
    "iphone17pro256":  "iPhone 17 Pro 256GB",
    "iphone17pro512":  "iPhone 17 Pro 512GB",
    "iphone17pm256":   "iPhone 17 Pro Max 256GB",
    "iphone17pm512":   "iPhone 17 Pro Max 512GB",
    "switch2":         "Nintendo Switch 2",
    "ps5_pro":         "PS5 Pro",
}

# 容量キーワード（検索結果の絞り込みに使用）
CAPACITY_KEYWORDS = {
    "iphone17pro256": ["256"],
    "iphone17pro512": ["512"],
    "iphone17pm256":  ["256"],
    "iphone17pm512":  ["512"],
}


class KaitoriItchomeCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "kaitori_itchome"
    SHOP_NAME = "買取一丁目"
    BASE_URL  = "https://www.1-chome.com/"
    REQUIRES_JS = True  # SPA のため Playwright 必須

    def _build_url(self, product_alias: str, product_name: str) -> str:
        query = PRODUCT_SEARCH_QUERIES.get(product_alias, "")
        if not query:
            return ""
        return f"https://www.1-chome.com/keitai/search/{quote(query)}"

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        caps = CAPACITY_KEYWORDS.get(product_alias, [])

        # 容量キーワードが含まれる周辺テキストから価格を抽出
        if caps:
            for cap in caps:
                for pat in [
                    cap + r'.{0,200}?買取価格[^¥￥\d]{0,20}[¥￥]\s*([\d,]{5,})',
                    cap + r'.{0,200}?買取[^¥￥\d]{0,20}[¥￥]\s*([\d,]{5,})',
                    cap + r'.{0,300}?([\d]{2,3},[\d]{3})円',
                ]:
                    m = re.search(pat, text, re.DOTALL)
                    if m:
                        try:
                            price = int(m.group(1).replace(",", ""))
                            if 10000 <= price <= 5_000_000:
                                return price
                        except ValueError:
                            pass

        # 汎用パターン
        for pat in [
            r'買取価格[^¥￥\d]{0,20}[¥￥]\s*([\d,]{5,})',
            r'買取価格[^¥￥\d]{0,20}([\d,]{5,})円',
            r'買取上限[^¥￥\d]{0,20}[¥￥]\s*([\d,]{5,})',
        ]:
            m = re.search(pat, text)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass

        return self.extract_price(text)

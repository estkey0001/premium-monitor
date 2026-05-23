"""モバイル一番 買取価格コレクター（CSV更新用）。
URL: https://mobileno1.com/
"""
import re
from typing import Optional
from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

PRODUCT_URLS = {
    "iphone17pro256":  "https://mobileno1.com/kaitori/iphone17pro/",
    "iphone17pro512":  "https://mobileno1.com/kaitori/iphone17pro/",
    "iphone17pm256":   "https://mobileno1.com/kaitori/iphone17promax/",
    "iphone17pm512":   "https://mobileno1.com/kaitori/iphone17promax/",
    "switch2":         "https://mobileno1.com/kaitori/switch/",
    "ps5_pro":         "https://mobileno1.com/kaitori/playstation/",
}

# 確認リンク（取得失敗時はこちらを返す）
FALLBACK_URLS = {
    "iphone17pro256":  "https://mobileno1.com/kaitori/iphone17pro/",
    "iphone17pro512":  "https://mobileno1.com/kaitori/iphone17pro/",
    "iphone17pm256":   "https://mobileno1.com/kaitori/iphone17promax/",
    "iphone17pm512":   "https://mobileno1.com/kaitori/iphone17promax/",
    "switch2":         "https://mobileno1.com/kaitori/",
    "ps5_pro":         "https://mobileno1.com/kaitori/",
}

CAPACITY_KEYWORDS = {
    "iphone17pro256": ["256"],
    "iphone17pro512": ["512"],
    "iphone17pm256":  ["256"],
    "iphone17pm512":  ["512"],
    "switch2":        [],
    "ps5_pro":        [],
}


class MobileIchibanCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "mobile_ichiban"
    SHOP_NAME = "モバイル一番"
    BASE_URL  = "https://mobileno1.com/"
    REQUIRES_JS = True

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        caps = CAPACITY_KEYWORDS.get(product_alias, [])

        # まず容量キーワード周辺を探す
        if caps:
            for cap in caps:
                pattern = cap + r'.{0,300}?[¥￥]([\d,]{5,})'
                m = re.search(pattern, text)
                if m:
                    try:
                        price = int(m.group(1).replace(",", ""))
                        if 10000 <= price <= 5_000_000:
                            return price
                    except ValueError:
                        pass

        # フォールバック: 最高買取価格
        return self.extract_price(text)

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return fallback_url

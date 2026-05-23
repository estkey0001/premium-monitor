"""イオシス 買取価格コレクター（CSV更新用）。
URL: https://iosys.co.jp/buy/
"""
import re
from typing import Optional
from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

PRODUCT_URLS = {
    "iphone17pro256":  "https://iosys.co.jp/buy/search/?q=iPhone+17+Pro+256GB",
    "iphone17pro512":  "https://iosys.co.jp/buy/search/?q=iPhone+17+Pro+512GB",
    "iphone17pm256":   "https://iosys.co.jp/buy/search/?q=iPhone+17+Pro+Max+256GB",
    "iphone17pm512":   "https://iosys.co.jp/buy/search/?q=iPhone+17+Pro+Max+512GB",
    "switch2":         "https://iosys.co.jp/buy/search/?q=Switch+2",
    "ps5_pro":         "https://iosys.co.jp/buy/search/?q=PS5+Pro",
}


class IosysCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "iosys"
    SHOP_NAME = "イオシス"
    BASE_URL  = "https://iosys.co.jp/"
    REQUIRES_JS = False

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        for pat in [
            r'買取価格[^¥￥\d]{0,20}[¥￥]\s*([\d,]{5,})',
            r'買取上限[^¥￥\d]{0,20}[¥￥]\s*([\d,]{5,})',
            r'買取[^¥￥\d]{0,30}([\d,]{5,})\s*円',
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

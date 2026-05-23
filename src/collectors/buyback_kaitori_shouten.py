"""買取商店 買取価格コレクター（CSV更新用）。
URL: https://www.kaitorishouten-co.jp/ または https://kaitori-shouten.com/
"""
import re
from typing import Optional
from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

PRODUCT_URLS = {
    "iphone17pro256":  "https://kaitori-shouten.com/iphone/iphone17pro/",
    "iphone17pro512":  "https://kaitori-shouten.com/iphone/iphone17pro/",
    "iphone17pm256":   "https://kaitori-shouten.com/iphone/iphone17promax/",
    "iphone17pm512":   "https://kaitori-shouten.com/iphone/iphone17promax/",
    "switch2":         "https://kaitori-shouten.com/game/switch2/",
    "ps5_pro":         "https://kaitori-shouten.com/game/ps5pro/",
}

CAPACITY_KEYWORDS = {
    "iphone17pro256": ["256"],
    "iphone17pro512": ["512"],
    "iphone17pm256":  ["256"],
    "iphone17pm512":  ["512"],
}


class KaitoriShoutenCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "kaitori_shouten"
    SHOP_NAME = "買取商店"
    BASE_URL  = "https://kaitori-shouten.com/"
    REQUIRES_JS = False

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        caps = CAPACITY_KEYWORDS.get(product_alias, [])
        if caps:
            for cap in caps:
                pattern = cap + r'.{0,400}?[¥￥]([\d,]{5,})'
                m = re.search(pattern, text)
                if m:
                    try:
                        price = int(m.group(1).replace(",", ""))
                        if 10000 <= price <= 5_000_000:
                            return price
                    except ValueError:
                        pass

        # 汎用パターン
        for pat in [
            r'買取価格[^¥￥\d]{0,20}[¥￥]([\d,]{5,})',
            r'買取上限[^¥￥\d]{0,20}[¥￥]([\d,]{5,})',
            r'査定価格[^¥￥\d]{0,20}[¥￥]([\d,]{5,})',
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

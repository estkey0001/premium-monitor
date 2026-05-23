"""ゲオ 買取価格コレクター（CSV更新用）。
URL: https://kaitori.geo-online.co.jp/ または https://www.geonet.co.jp/service/kaitori/
スクレイピング困難なため、公式確認リンクをfallbackとして使用。
"""
import re
from typing import Optional
from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

# ゲオ買取の検索URL
PRODUCT_URLS = {
    "iphone17pro256":  "https://kaitori.geo-online.co.jp/search?q=iPhone+17+Pro+256GB",
    "iphone17pro512":  "https://kaitori.geo-online.co.jp/search?q=iPhone+17+Pro+512GB",
    "iphone17pm256":   "https://kaitori.geo-online.co.jp/search?q=iPhone+17+Pro+Max+256GB",
    "iphone17pm512":   "https://kaitori.geo-online.co.jp/search?q=iPhone+17+Pro+Max+512GB",
    "switch2":         "https://kaitori.geo-online.co.jp/search?q=Switch+2",
    "ps5_pro":         "https://kaitori.geo-online.co.jp/search?q=PS5+Pro",
}

CONFIRM_URLS = {
    "iphone17pro256":  "https://kaitori.geo-online.co.jp/search?q=iPhone+17+Pro+256GB",
    "iphone17pro512":  "https://kaitori.geo-online.co.jp/search?q=iPhone+17+Pro+512GB",
    "iphone17pm256":   "https://kaitori.geo-online.co.jp/search?q=iPhone+17+Pro+Max+256GB",
    "iphone17pm512":   "https://kaitori.geo-online.co.jp/search?q=iPhone+17+Pro+Max+512GB",
    "switch2":         "https://kaitori.geo-online.co.jp/search?q=Nintendo+Switch+2",
    "ps5_pro":         "https://kaitori.geo-online.co.jp/search?q=PS5+Pro",
}


class GeoCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "geo"
    SHOP_NAME = "ゲオ"
    BASE_URL  = "https://kaitori.geo-online.co.jp/"
    REQUIRES_JS = True

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        for pat in [
            r'買取価格[^¥￥\d]{0,20}[¥￥]\s*([\d,]{4,})',
            r'査定価格[^¥￥\d]{0,20}[¥￥]\s*([\d,]{4,})',
            r'買取[^¥￥\d]{0,30}([\d,]{4,})\s*円',
        ]:
            m = re.search(pat, text)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass

        return self.extract_price(text, min_price=10000)

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return fallback_url

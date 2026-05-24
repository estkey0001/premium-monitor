"""ハードオフ 買取価格コレクター（CSV更新用）。
URL: https://www.hardoff.co.jp/
取得方式: requests（静的HTML）
検索URL方式（URLスラッグ推測禁止）
ゲーム機・PC中心の買取店
"""
import re
import urllib.parse
from typing import Optional

from src.collectors.buyback_base_csv import BaseCsvBuybackCollector


def _search_url(keyword: str) -> str:
    encoded = urllib.parse.quote(keyword)
    return f"https://www.hardoff.co.jp/search/?keyword={encoded}&condition=S"


SEARCH_KEYWORDS = {
    "switch2":  "Nintendo Switch 2",
    "ps5_pro":  "PlayStation 5 Pro",
    "iphone17pro256": "iPhone 17 Pro 256GB",
    "iphone17pro512": "iPhone 17 Pro 512GB",
    "iphone17pm256": "iPhone 17 Pro Max 256GB",
    "iphone17pm512": "iPhone 17 Pro Max 512GB",
}

DIRECT_PATTERNS = {
    "switch2": [r'Nintendo Switch 2.{0,100}?([\d]{2},\d{3})円', r'Switch 2.{0,100}?¥([\d,]+)'],
    "ps5_pro": [r'PlayStation\s*5\s*Pro.{0,100}?([\d]{2,3},\d{3})円', r'PS5\s*Pro.{0,100}?¥([\d,]+)'],
    "iphone17pro256": [r'iPhone 17 Pro 256.{0,100}?([\d]{2,3},\d{3})円'],
    "iphone17pro512": [r'iPhone 17 Pro 512.{0,100}?([\d]{2,3},\d{3})円'],
    "iphone17pm256":  [r'iPhone 17 Pro Max 256.{0,100}?([\d]{2,3},\d{3})円'],
    "iphone17pm512":  [r'iPhone 17 Pro Max 512.{0,100}?([\d]{2,3},\d{3})円'],
}


class HardoffCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "hardoff"
    SHOP_NAME = "ハードオフ"
    BASE_URL  = "https://www.hardoff.co.jp/"
    REQUIRES_JS = False

    def _build_url(self, product_alias: str, product_name: str) -> str:
        kw = SEARCH_KEYWORDS.get(product_alias)
        return _search_url(kw) if kw else ""

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        from bs4 import BeautifulSoup
        text = BeautifulSoup(html, "html.parser").get_text(" ", strip=True)
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

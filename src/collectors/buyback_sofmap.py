"""ソフマップ 買取価格コレクター（CSV更新用）。
URL: https://www.sofmap.com/
取得方式: requests → Playwright フォールバック（JS動的ページの可能性あり）
検索URL方式（URLスラッグ推測禁止）:
  - 買取一覧検索: /buy_list.aspx?keyword=Nintendo+Switch+2

価格形式: "買取価格 ¥45,000" や "45,000円(税込)"
"""
import re
import urllib.parse
from typing import Optional

from src.collectors.buyback_base_csv import BaseCsvBuybackCollector


def _search_url(keyword: str) -> str:
    encoded = urllib.parse.quote(keyword)
    return f"https://www.sofmap.com/buy_list.aspx?keyword={encoded}"


SEARCH_KEYWORDS = {
    "switch2":  "Nintendo Switch 2",
    "ps5_pro":  "PlayStation 5 Pro",
}

DIRECT_PATTERNS = {
    "switch2": [
        r'Nintendo Switch 2.{0,300}?買取価格[^\d¥￥]*?[¥￥]?([\d,]+)円',
        r'Switch 2.{0,200}?[¥￥]([\d,]+)',
        r'Switch 2.*?([\d]{2},\d{3})円',
    ],
    "ps5_pro": [
        r'PlayStation\s*5\s*Pro.{0,300}?買取価格[^\d¥￥]*?[¥￥]?([\d,]+)円',
        r'PS5\s*Pro.{0,200}?[¥￥]([\d,]+)',
        r'PS5.*?Pro.*?([\d]{2,3},\d{3})円',
    ],
}


class SofmapCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "sofmap"
    SHOP_NAME = "ソフマップ"
    BASE_URL  = "https://www.sofmap.com/"
    REQUIRES_JS = True  # JS動的ページの可能性あり → Playwright フォールバック有効

    def _build_url(self, product_alias: str, product_name: str) -> str:
        kw = SEARCH_KEYWORDS.get(product_alias)
        if not kw:
            return ""
        return _search_url(kw)

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        patterns = DIRECT_PATTERNS.get(product_alias, [])
        for pat in patterns:
            m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass

        for fallback_pat in [
            r'買取価格[^\d]*?([\d,]+)円',
            r'買取上限[^\d]*?([\d,]+)円',
        ]:
            m = re.search(fallback_pat, text)
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

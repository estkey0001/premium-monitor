"""駿河屋 買取価格コレクター（CSV更新用）。
URL: https://www.suruga-ya.jp/kaitori/
取得方式: requests（静的HTML）
検索URL方式（URLスラッグ推測禁止）:
  - 商品キーワード検索: /kaitori/kaitori_list.php?keyword=Nintendo+Switch+2
  - カテゴリ絞り込み不要（キーワードで商品特定）

買取価格形式例:
  - "買取価格: 45,000円" または "¥45,000" の形式
"""
import re
import urllib.parse
from typing import Optional

from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

# キーワード検索URLを使用（URLスラッグ推測禁止）
def _search_url(keyword: str) -> str:
    encoded = urllib.parse.quote(keyword)
    return f"https://www.suruga-ya.jp/kaitori/kaitori_list.php?keyword={encoded}&category=&stock=2"


SEARCH_KEYWORDS = {
    "switch2":  "Nintendo Switch 2",
    "ps5_pro":  "PlayStation 5 Pro",
}

# ゲーム機を直接特定するパターン（テキスト全体に適用）
# 駿河屋の価格表示: "買取価格 ¥45,000" や "45,000円"
DIRECT_PATTERNS = {
    "switch2": [
        r'Nintendo Switch 2.{0,200}?買取価格[^\d]*?([\d,]+)円',
        r'Switch 2.{0,200}?[¥￥]([\d,]+)',
        r'Switch 2.{0,100}?([\d]{2},\d{3})円',
    ],
    "ps5_pro": [
        r'PlayStation\s*5\s*Pro.{0,200}?買取価格[^\d]*?([\d,]+)円',
        r'PS5\s*Pro.{0,200}?[¥￥]([\d,]+)',
        r'PS5.*?Pro.{0,100}?([\d]{2,3},\d{3})円',
    ],
}


class SurugayaCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "surugaya"
    SHOP_NAME = "駿河屋"
    BASE_URL  = "https://www.suruga-ya.jp/"
    REQUIRES_JS = False

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

        # フォールバック: 「買取価格」付き価格
        for fallback_pat in [
            r'買取価格[^\d]*?([\d,]+)円',
            r'買取[^\d]*?[¥￥]([\d,]+)',
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

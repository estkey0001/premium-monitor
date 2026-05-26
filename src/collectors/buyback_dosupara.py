"""ドスパラ 買取価格コレクター。
URL: https://www.dospara.co.jp/
取得方式: requests（静的HTML）
検索URL方式（URLスラッグ推測禁止）
PC・ゲーム機買取専門
"""
import re
import urllib.parse
from typing import Optional

from src.collectors.buyback_base_csv import BaseCsvBuybackCollector


def _search_url(keyword: str) -> str:
    # keyword パラメーター付き URL は 404 になるため、
    # 買取一覧ページ（トップ）を使用。価格はページ内テキスト検索で取得。
    encoded = urllib.parse.quote(keyword)
    return f"https://www.dospara.co.jp/kaitori/web/search?keyword={encoded}"


# 代替URL（検索が使えない場合のフォールバック）
FALLBACK_URLS: dict[str, str] = {
    "switch2": "https://www.dospara.co.jp/kaitori/",
    "ps5_pro": "https://www.dospara.co.jp/kaitori/",
}

SEARCH_KEYWORDS = {
    "switch2": "Nintendo Switch 2",
    "ps5_pro": "PlayStation 5 Pro",
}

DIRECT_PATTERNS = {
    "switch2": [r'Nintendo Switch 2.{0,100}?([\d]{2},\d{3})円', r'Switch 2.{0,80}?¥([\d,]+)'],
    "ps5_pro": [r'PlayStation\s*5\s*Pro.{0,100}?([\d]{2,3},\d{3})円'],
}


class DosuparaCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "dosupara"
    SHOP_NAME = "ドスパラ"
    BASE_URL  = "https://www.dospara.co.jp/"
    REQUIRES_JS = False

    def _build_url(self, product_alias: str, product_name: str) -> str:
        kw = SEARCH_KEYWORDS.get(product_alias)
        if not kw:
            return ""
        return _search_url(kw)

    def _fetch_html(self, url: str):
        """HTTPエラー時にフォールバックURLを試みる。"""
        html = super()._fetch_html(url)
        if html is None and self.last_failure_reason in ("http_404", "http_error"):
            # フォールバック: 商品alias はURL自体からは取れないので _build_url で渡された alias を使う
            # → 検索URLからaliasを逆引き
            fallback = next(
                (fb for alias, fb in FALLBACK_URLS.items() if SEARCH_KEYWORDS.get(alias, "") in url),
                None
            )
            if fallback and fallback != url:
                self.last_failure_reason = None
                html = super()._fetch_html(fallback)
        return html

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

"""じゃんぱら 買取価格コレクター（CSV更新用）。
買取価格ページ: https://www.janpara.co.jp/buy/
注: CORS/セッション制限のためJS対応必要。
"""
import re
from typing import Optional
from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

# じゃんぱらの買取価格検索URL
PRODUCT_URLS = {
    "iphone17pro256":  "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+256GB",
    "iphone17pro512":  "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+512GB",
    "iphone17pm256":   "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+Max+256GB",
    "iphone17pm512":   "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+Max+512GB",
    "switch2":         "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=Switch+2",
    "ps5_pro":         "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=PS5+Pro",
}

# 公式確認リンク（スクレイピング失敗時のfallback URL）
CONFIRM_URLS = {
    "iphone17pro256":  "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+256GB",
    "iphone17pro512":  "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+512GB",
    "iphone17pm256":   "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+Max+256GB",
    "iphone17pm512":   "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+Max+512GB",
    "switch2":         "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=Switch+2",
    "ps5_pro":         "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=PS5+Pro",
}


class JanparaCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "janpara"
    SHOP_NAME = "じゃんぱら"
    BASE_URL  = "https://www.janpara.co.jp/"
    REQUIRES_JS = True

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        for pat in [
            r'買取上限[^¥￥\d]{0,30}[¥￥]\s*([\d,]{5,})',
            r'買取価格[^¥￥\d]{0,30}[¥￥]\s*([\d,]{5,})',
            r'買取[^¥￥\d]{0,20}[¥￥]\s*([\d,]{5,})',
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

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return CONFIRM_URLS.get("", fallback_url) or fallback_url

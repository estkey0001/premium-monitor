"""モバイル一番 買取価格コレクター（CSV更新用）。
URL: https://www.mobile-ichiban.com/ (トップページに買取価格一覧が静的HTMLで掲載)
価格形式: 178,000円 (カンマ区切り + 円)
"""
import re
from typing import Optional
from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

# トップページに全商品の価格が載っているため、全商品同一URL
PRODUCT_URLS = {
    "iphone17pro256":  "https://www.mobile-ichiban.com/",
    "iphone17pro512":  "https://www.mobile-ichiban.com/",
    "iphone17pm256":   "https://www.mobile-ichiban.com/",
    "iphone17pm512":   "https://www.mobile-ichiban.com/",
    "switch2":         "https://www.mobile-ichiban.com/",
    "ps5_pro":         "https://www.mobile-ichiban.com/",
}

# 商品を特定するための検索キーワード（順に一致確認）
SEARCH_KEYWORDS = {
    "iphone17pro256": ["iPhone 17 Pro", "256"],
    "iphone17pro512": ["iPhone 17 Pro", "512"],
    "iphone17pm256":  ["iPhone 17 Pro Max", "256"],
    "iphone17pm512":  ["iPhone 17 Pro Max", "512"],
    "switch2":        ["Switch 2", "Nintendo Switch 2"],
    "ps5_pro":        ["PS5 Pro", "PlayStation 5 Pro"],
}


class MobileIchibanCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "mobile_ichiban"
    SHOP_NAME = "モバイル一番"
    BASE_URL  = "https://www.mobile-ichiban.com/"
    REQUIRES_JS = True   # 価格は JavaScript 動的ロードのため Playwright 必須

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        keywords = SEARCH_KEYWORDS.get(product_alias, [])

        # キーワードが含まれる周辺テキストから価格を抽出
        # テキストを行単位で分割して該当行近辺を探す
        lines = text.split("\n")
        for i, line in enumerate(lines):
            if not keywords:
                break
            # 全キーワードが行またはその周辺に含まれているか確認
            context = " ".join(lines[max(0, i-2):min(len(lines), i+5)])
            if all(kw.lower() in context.lower() for kw in keywords):
                # 周辺テキストから価格を抽出
                for pat in [
                    r'([\d]{2,3},[\d]{3})円',  # N,NNN円 or NN,NNN円
                    r'[¥￥]\s*([\d,]+)',
                ]:
                    for m in re.finditer(pat, context):
                        try:
                            price = int(m.group(1).replace(",", ""))
                            if 10000 <= price <= 5_000_000:
                                return price
                        except ValueError:
                            pass

        # フォールバック: 全文から最高買取価格
        return self.extract_price(text)

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return "https://www.mobile-ichiban.com/"

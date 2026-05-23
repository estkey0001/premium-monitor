"""買取商店 買取価格コレクター（CSV更新用）。
URL: https://www.kaitorishouten-co.jp/
注: サイト側で 403 Forbidden が返ることが多い。
    取得できた場合のパーサーも実装しているが、失敗時は fetch_failed として記録される。
"""
import re
from typing import Optional
from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

PRODUCT_URLS = {
    "iphone17pro256":  "https://www.kaitorishouten-co.jp/keitai",
    "iphone17pro512":  "https://www.kaitorishouten-co.jp/keitai",
    "iphone17pm256":   "https://www.kaitorishouten-co.jp/keitai",
    "iphone17pm512":   "https://www.kaitorishouten-co.jp/keitai",
    "switch2":         "https://www.kaitorishouten-co.jp/kaden",
    "ps5_pro":         "https://www.kaitorishouten-co.jp/kaden",
}

# 商品を特定するための検索キーワード
# iPhone: "Pro Max" が含まれると Pro Max と区別できないため "Pro 256" のような形式を使用
SEARCH_KEYWORDS = {
    "iphone17pro256": ["iPhone 17 Pro 256", "iPhone17 Pro 256"],
    "iphone17pro512": ["iPhone 17 Pro 512", "iPhone17 Pro 512"],
    "iphone17pm256":  ["iPhone 17 Pro Max 256", "iPhone17 Pro Max 256"],
    "iphone17pm512":  ["iPhone 17 Pro Max 512", "iPhone17 Pro Max 512"],
    "switch2":        ["Switch 2", "スイッチ ２", "スイッチ2"],
    "ps5_pro":        ["PS5 Pro", "プレイステーション5 Pro", "CFI-7"],
}

# 商品を直接特定する正規表現パターン（テキスト全体に適用）
# 買取商店のページは改行なしの一続きテキストのため、直接regexで抽出
DIRECT_PATTERNS = {
    "iphone17pro256": r'iPhone 17 Pro 256.{0,120}?(\d{2,3},\d{3})円',
    "iphone17pro512": r'iPhone 17 Pro 512.{0,120}?(\d{2,3},\d{3})円',
    "iphone17pm256":  r'iPhone 17 Pro Max 256.{0,120}?(\d{2,3},\d{3})円',
    "iphone17pm512":  r'iPhone 17 Pro Max 512.{0,120}?(\d{2,3},\d{3})円',
    "switch2":        r'(?:Nintendo Switch 2|Switch 2|スイッチ\s*２).{0,150}?(\d{2},\d{3})円',
    "ps5_pro":        r'(?:PS5 Pro|プレイステーション5 Pro|CFI-7[01]).{0,150}?(\d{2,3},\d{3})円',
}


class KaitoriShoutenCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "kaitori_shouten"
    SHOP_NAME = "買取商店"
    BASE_URL  = "https://www.kaitorishouten-co.jp/"
    REQUIRES_JS = False

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        # 直接正規表現マッチング（ページ内の一続きテキストに対応）
        pat = DIRECT_PATTERNS.get(product_alias)
        if pat:
            m = re.search(pat, text)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass

        # フォールバック: 汎用パターン
        for fallback_pat in [
            r'買取価格[^¥￥\d]{0,20}[¥￥]([\d,]{5,})',
            r'買取上限[^¥￥\d]{0,20}[¥￥]([\d,]{5,})',
        ]:
            m = re.search(fallback_pat, text)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass

        return self.extract_price(text)

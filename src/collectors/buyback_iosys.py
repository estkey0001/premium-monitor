"""イオシス買取 買取価格コレクター（CSV更新用）。
URL: https://k-tai-iosys.com/pricelist/
HTML構造: <span class="s-price">157,000円</span> (未使用品価格)
"""
import re
from typing import Optional
from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

PRODUCT_URLS = {
    "iphone17pro256":  "https://k-tai-iosys.com/pricelist/smartphone/iphone/iphone17pro/",
    "iphone17pro512":  "https://k-tai-iosys.com/pricelist/smartphone/iphone/iphone17pro/",
    "iphone17pm256":   "https://k-tai-iosys.com/pricelist/smartphone/iphone/iphone17pro_max/",
    "iphone17pm512":   "https://k-tai-iosys.com/pricelist/smartphone/iphone/iphone17pro_max/",
    "switch2":         "https://k-tai-iosys.com/pricelist/game/hard/",
    "ps5_pro":         "https://k-tai-iosys.com/pricelist/game/hard/",
}

# 容量キーワード（対象行を絞り込む）
CAPACITY_KEYWORDS = {
    "iphone17pro256": "256",
    "iphone17pro512": "512",
    "iphone17pm256":  "256",
    "iphone17pm512":  "512",
    "switch2":        "",
    "ps5_pro":        "",
}

# ゲーム機一覧ページで商品を直接特定する正規表現パターン（テキスト全体に適用）
# 問題: コンテキストウィンドウに他商品の価格が混入するため、keyword+価格を直結させる
GAME_DIRECT_PATTERNS = {
    "switch2": r'(?:Nintendo Switch 2|Switch 2|スイッチ\s*2).{0,200}?未使用品買取価格\s*([\d,]+)円',
    "ps5_pro": r'(?:PlayStation5 Pro|PS5 Pro|CFI-7[0-9]).{0,200}?未使用品買取価格\s*([\d,]+)円',
}


class IosysCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "iosys"
    SHOP_NAME = "イオシス"
    BASE_URL  = "https://k-tai-iosys.com/"
    REQUIRES_JS = False

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        cap = CAPACITY_KEYWORDS.get(product_alias, "")

        # --- スマートフォン系: <tr> の s-price クラスから取得 ---
        for tr in soup.find_all("tr"):
            name_span = tr.find("span", class_="name")
            simfree_span = tr.find("span", class_="simfree")
            if not name_span or not simfree_span:
                continue
            if cap and cap not in name_span.get_text():
                continue
            # 未使用品価格クラス s-price を優先取得
            s_price = tr.find("span", class_="s-price")
            if s_price:
                m = re.search(r'([\d,]+)円', s_price.get_text(strip=True))
                if m:
                    try:
                        price = int(m.group(1).replace(",", ""))
                        if 10000 <= price <= 5_000_000:
                            return price
                    except ValueError:
                        pass

        # --- ゲーム機系: テキスト全体に直接正規表現を適用（コンテキスト混入を防ぐ）---
        game_pat = GAME_DIRECT_PATTERNS.get(product_alias)
        if game_pat:
            text_full = soup.get_text(" ", strip=True)
            m = re.search(game_pat, text_full, re.DOTALL | re.IGNORECASE)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass

        # フォールバック: ページ全体から未使用品価格を探す
        text = soup.get_text(" ", strip=True)
        for pat in [
            r'未使用品買取価格\s*([\d,]+)円',
            r'買取価格[^¥￥\d]{0,20}([\d,]+)円',
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

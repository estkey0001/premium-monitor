"""イオシス買取 買取価格コレクター（CSV更新用）。
URL: https://k-tai-iosys.com/pricelist/
HTML構造: <span class="s-price">157,000円</span> (未使用品価格)

取得方式: requests（静的HTML、JS不要）
URL選択方針:
  - URLスラッグ推測を禁止。確実に存在するカテゴリページのみ使用。
  - スマートフォン: /pricelist/ (全一覧ページ) で1回リクエスト + 商品名で絞り込み
  - ゲーム機: /pricelist/game/ (ゲームカテゴリ)
"""
import re
from typing import Optional
from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

# 確実に存在するカテゴリページ（URLスラッグ推測禁止）
PRODUCT_URLS = {
    "iphone17pro256":  "https://k-tai-iosys.com/pricelist/",
    "iphone17pro512":  "https://k-tai-iosys.com/pricelist/",
    "iphone17pm256":   "https://k-tai-iosys.com/pricelist/",
    "iphone17pm512":   "https://k-tai-iosys.com/pricelist/",
    "switch2":         "https://k-tai-iosys.com/pricelist/game/",
    "ps5_pro":         "https://k-tai-iosys.com/pricelist/game/",
}

# 商品特定用キーワード（商品名の表記揺れに対応）
SEARCH_KEYWORDS = {
    "iphone17pro256":  ["iPhone 17 Pro 256", "iPhone17 Pro 256", "iPhone17Pro 256"],
    "iphone17pro512":  ["iPhone 17 Pro 512", "iPhone17 Pro 512"],
    "iphone17pm256":   ["iPhone 17 Pro Max 256", "iPhone17 Pro Max 256", "iPhone17ProMax 256"],
    "iphone17pm512":   ["iPhone 17 Pro Max 512", "iPhone17 Pro Max 512"],
    "switch2":         ["Nintendo Switch 2", "Switch 2", "スイッチ 2", "スイッチ2"],
    "ps5_pro":         ["PlayStation 5 Pro", "PS5 Pro", "CFI-7000", "プレイステーション5 Pro"],
}

# 容量キーワード（スマートフォン対象行を絞り込む）
CAPACITY_KEYWORDS = {
    "iphone17pro256": "256",
    "iphone17pro512": "512",
    "iphone17pm256":  "256",
    "iphone17pm512":  "512",
    "switch2":        "",
    "ps5_pro":        "",
}

# ゲーム機: キーワード + 価格を直結させるパターン（複数商品が1ページに混在するため）
GAME_DIRECT_PATTERNS = {
    "switch2": [
        r'(?:Nintendo Switch 2|Switch 2|スイッチ\s*2).{0,300}?未使用品買取価格\s*([\d,]+)円',
        r'(?:Nintendo Switch 2|Switch 2|スイッチ\s*2).{0,200}?([\d]{2,3},\d{3})円',
    ],
    "ps5_pro": [
        r'(?:PlayStation\s*5\s*Pro|PS5\s*Pro|CFI-7[0-9]).{0,300}?未使用品買取価格\s*([\d,]+)円',
        r'(?:PlayStation\s*5\s*Pro|PS5\s*Pro|CFI-7[0-9]).{0,200}?([\d]{2,3},\d{3})円',
    ],
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
        # キーワードリストで商品行を特定
        keywords = SEARCH_KEYWORDS.get(product_alias, [])
        for tr in soup.find_all("tr"):
            row_text = tr.get_text(" ", strip=True)
            # いずれかのキーワードが行に含まれるか確認
            if not any(kw.lower() in row_text.lower() for kw in keywords):
                continue
            if cap and cap not in row_text:
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
            # s-price が見つからない場合はその行の最大価格
            for price_m in re.finditer(r'([\d,]+)円', row_text):
                try:
                    p = int(price_m.group(1).replace(",", ""))
                    if 10000 <= p <= 5_000_000:
                        return p
                except ValueError:
                    pass

        # --- ゲーム機系: テキスト全体に直接正規表現を適用 ---
        game_patterns = GAME_DIRECT_PATTERNS.get(product_alias, [])
        if game_patterns:
            text_full = soup.get_text(" ", strip=True)
            for game_pat in game_patterns:
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

        return None  # URLスラッグ推測禁止のため汎用extract_priceも使わない

"""ゲオ 買取価格コレクター（CSV更新用）。
URL: https://www.geo-online.co.jp/store_info/buy/
価格形式: 参考買取価格 40,000円
注: iPhoneページは /store_info/buy/iphone/ で静的HTML公開。
    ゲーム機本体は /store_info/buy/ (トップ) に掲載。
    buy.geo-online.co.jp は 403 Forbidden のためアクセス不可。

2026-05-27 調査結果:
  - iPhone 17 シリーズ: geo の /store_info/buy/iphone/ は iPhone 16 以前のみ掲載。
    iPhone 17 Pro/Max は geo_mobile コレクターが Playwright で担当する。
  - PS5 Pro (CFI-7000): /store_info/buy/ に掲載なし（2026-05現在）。
    PS5 CFI-2000 はジャンク品欄にあるが PS5 Pro は未掲載。
    → ps5_pro は product_not_listed として記録。
  - Switch 2 (ＳＷ２): 本体・周辺機器欄に 50,000円 で掲載 → 取得成功。
"""
import re
from typing import Optional
from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

PRODUCT_URLS = {
    "iphone17pro256":  "https://www.geo-online.co.jp/store_info/buy/iphone/",
    "iphone17pro512":  "https://www.geo-online.co.jp/store_info/buy/iphone/",
    "iphone17pm256":   "https://www.geo-online.co.jp/store_info/buy/iphone/",
    "iphone17pm512":   "https://www.geo-online.co.jp/store_info/buy/iphone/",
    "switch2":         "https://www.geo-online.co.jp/store_info/buy/",
    "ps5_pro":         "",  # geo では PS5 Pro 未掲載（2026-05現在）→ product_not_listed
}

# geo では掲載のない商品（product_not_listed として記録）
_NOT_LISTED: frozenset[str] = frozenset({
    "ps5_pro",         # PS5 Pro: 2026-05現在 /store_info/buy/ に未掲載
    "iphone17pro256",  # iPhone 17 Pro/Max: geo_mobile が担当。geo/iphone/ は iPhone 16 以前のみ
    "iphone17pro512",
    "iphone17pm256",
    "iphone17pm512",
})

# 直接正規表現パターン（ゲオのページは全角文字・全角スペース混在）
# 実際のページテキスト例: "ＳＷ２　ニンテンドー　スイッチ　２　（日本語・国内専用） 参考買取価格 40,000円"
DIRECT_PATTERNS = {
    "iphone17pro256": r'iPhone 17 Pro 256.{0,120}?参考買取価格\s*([\d,]+)円',
    "iphone17pro512": r'iPhone 17 Pro 512.{0,120}?参考買取価格\s*([\d,]+)円',
    "iphone17pm256":  r'iPhone 17 Pro Max 256.{0,120}?参考買取価格\s*([\d,]+)円',
    "iphone17pm512":  r'iPhone 17 Pro Max 512.{0,120}?参考買取価格\s*([\d,]+)円',
    # Switch2の表記揺れに対応: "ＳＷ２", "スイッチ２", "Nintendo Switch 2", "Switch 2"
    "switch2":        r'(?:ＳＷ２|スイッチ\s*[２2]|Nintendo Switch\s*2|Switch\s*2|ニンテンドースイッチ[２2]).{0,80}?参考買取価格\s*([\d,]+)円',
    "ps5_pro":        r'(?:ＰＳ５.*?Pro|PS5\s*Pro|プレイステーション5\s*Pro|PlayStation\s*5\s*Pro).{0,80}?参考買取価格\s*([\d,]+)円',
}


class GeoCsvCollector(BaseCsvBuybackCollector):
    SHOP_ID   = "geo"
    SHOP_NAME = "ゲオ"
    BASE_URL  = "https://www.geo-online.co.jp/"
    REQUIRES_JS = False  # store_info/buy/ は静的HTML

    def _build_url(self, product_alias: str, product_name: str) -> str:
        return PRODUCT_URLS.get(product_alias, "")

    def fetch(self, product_alias: str, product_name: str, condition: str = "new_unopened_simfree"):
        """商品未掲載の場合は product_not_listed として早期リターン。"""
        if product_alias in _NOT_LISTED:
            self.last_failure_reason = "product_not_listed"
            self.last_confidence = "high"
            return None
        return super().fetch(product_alias, product_name, condition)

    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        text = soup.get_text(" ", strip=True)

        # 直接正規表現マッチング（全角文字・全角スペース混在に対応）
        pat = DIRECT_PATTERNS.get(product_alias)
        if pat:
            m = re.search(pat, text, re.DOTALL)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass

        return None  # パターン不一致の場合は誤検出防止のため None を返す

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return fallback_url

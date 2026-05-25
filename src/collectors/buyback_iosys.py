"""イオシス買取 買取価格コレクター（CSV更新用）。

URL変遷:
  旧: https://k-tai-iosys.com/pricelist/  ← 3件のプレースホルダのみ。使用不可
  新: https://k-tai-iosys.com/pricelist/smartphone/iphone/  ← iPhone全機種一覧 ✅
      https://k-tai-iosys.com/pricelist/game/hard/          ← ゲーム機本体一覧 ✅

HTML構造: <span class="s-price">157,000円</span> (未使用品価格)

取得方式: requests（静的HTML、JS不要）
注意: 商品名の表記は "iPhone17 Pro" (スペースなし) であることを確認済み。
"""
import re
from typing import Optional
from src.collectors.buyback_base_csv import BaseCsvBuybackCollector

# 確実に存在するカテゴリページ（URLスラッグ推測禁止）
# 2026-05-25 調査確認済み
PRODUCT_URLS = {
    "iphone17pro256":  "https://k-tai-iosys.com/pricelist/smartphone/iphone/",
    "iphone17pro512":  "https://k-tai-iosys.com/pricelist/smartphone/iphone/",
    "iphone17pm256":   "https://k-tai-iosys.com/pricelist/smartphone/iphone/",
    "iphone17pm512":   "https://k-tai-iosys.com/pricelist/smartphone/iphone/",
    "switch2":         "https://k-tai-iosys.com/pricelist/game/hard/",
    "ps5_pro":         "https://k-tai-iosys.com/pricelist/game/hard/",
}

# 商品特定用キーワード（実際のページ表示テキストに合わせた表記）
# 実際のtr行例: "au版SIMフリー iPhone17 Pro\n256GB 未使用品買取価格 157,000円 ..."
# ← "iPhone17 Pro" (iPhone と17の間にスペースなし) であることを確認
SEARCH_KEYWORDS = {
    "iphone17pro256":  ["iPhone17 Pro 256", "iPhone17 Pro\n256", "iPhone17Pro 256"],
    "iphone17pro512":  ["iPhone17 Pro 512", "iPhone17 Pro\n512"],
    # iosys のページ表記は "Pro MAX"（全大文字）であることを確認済み
    "iphone17pm256":   ["iPhone17 Pro MAX 256", "iPhone17 Pro Max 256", "iPhone17 Pro MAX\n256"],
    "iphone17pm512":   ["iPhone17 Pro MAX 512", "iPhone17 Pro Max 512", "iPhone17 Pro MAX\n512"],
    "switch2":         ["Switch 2 日本語・国内専用", "Nintendo Switch 2\n", "Switch 2\n"],
    "ps5_pro":         ["CFI-7000B01", "PlayStation5 Pro", "PlayStation 5 Pro", "PS5 Pro"],
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

# iPhone の Pro と Pro Max を区別するための除外キーワード
# "iPhone17 Pro 256" は "iPhone17 Pro Max 256" にもマッチしてしまうため
# Pro Max 行では "Max" が含まれるので、Pro 専用行を取りたい場合は "Max" を除外する
EXCLUDE_KEYWORDS = {
    # Pro行からPro MAX行を除外（iosys表記は "Pro MAX" 全大文字）
    "iphone17pro256": ["Pro MAX", "Pro Max"],
    "iphone17pro512": ["Pro MAX", "Pro Max"],
    "iphone17pm256":  [],   # Pro MAX なので除外不要
    "iphone17pm512":  [],
    "switch2":        [],
    "ps5_pro":        [],
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
        keywords = SEARCH_KEYWORDS.get(product_alias, [])
        excludes = EXCLUDE_KEYWORDS.get(product_alias, [])

        # ── Step1: <tr> ベース検索 — s-price クラスから取得 ──
        for tr in soup.find_all("tr"):
            row_text = tr.get_text(" ", strip=True)

            # キーワードのいずれかを含む行か確認
            if not any(kw in row_text for kw in keywords):
                continue
            # 除外キーワードが含まれていたらスキップ（Pro vs Pro Max 区別）
            if any(ex in row_text for ex in excludes):
                continue
            # 容量フィルター（256/512）
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

            # s-price が見つからない場合: spanタグ内の価格を全探索
            for span in tr.find_all("span"):
                span_text = span.get_text(strip=True)
                m = re.search(r'([\d,]+)円', span_text)
                if m:
                    try:
                        price = int(m.group(1).replace(",", ""))
                        if 10000 <= price <= 5_000_000:
                            return price
                    except ValueError:
                        pass

            # さらにフォールバック: 未使用品買取価格のパターンをテキストから抽出
            m_up = re.search(r'未使用品買取価格\s*([\d,]+)円', row_text)
            if m_up:
                try:
                    price = int(m_up.group(1).replace(",", ""))
                    if 10000 <= price <= 5_000_000:
                        return price
                except ValueError:
                    pass

        # ── Step2: テキスト全体にキーワード近傍パターン（ゲーム機系など） ──
        text_full = soup.get_text(" ", strip=True)
        for kw in keywords:
            idx = text_full.find(kw)
            if idx < 0:
                continue
            if any(ex in text_full[idx:idx + 200] for ex in excludes):
                continue
            block = text_full[idx:idx + 300]
            if cap and cap not in block:
                continue
            # 未使用品買取価格 を優先
            for near_pat in [
                r'未使用品買取価格\s*([\d,]+)円',
                r'([\d,]+)円',
            ]:
                m = re.search(near_pat, block)
                if m:
                    try:
                        price = int(m.group(1).replace(",", ""))
                        if 10000 <= price <= 5_000_000:
                            return price
                    except ValueError:
                        pass

        return None  # URLスラッグ推測禁止のため汎用extract_priceも使わない

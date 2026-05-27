"""
CameraRetailersLotteryCollector — カメラ販売店（マップカメラ / キタムラ）抽選販売コレクター

調査日: 2026-05-27
URL:
  マップカメラ: https://www.mapcamera.com/ec/shop/lottery
  キタムラ: https://ec.kitamura.jp/shopbrand/lottery
取得方式: requests（JS 不要）
価格形式: ¥XXX,XXX（税込）
対象ブランド: RICOH / FUJIFILM / Sony / Leica / Nikon / Canon
"""

from __future__ import annotations

import re
import logging

from .base import BaseLotteryCollector

logger = logging.getLogger(__name__)

# 販売店リスト
RETAILERS = [
    {
        "shop_name": "マップカメラ",
        "shop_id": "mapcamera",
        "lottery_url": "https://www.mapcamera.com/ec/shop/lottery",
        "requires_js": False,
    },
    {
        "shop_name": "キタムラ",
        "shop_id": "kitamura",
        "lottery_url": "https://ec.kitamura.jp/shopbrand/lottery",
        "requires_js": False,
    },
]

# 対象ブランド
TARGET_BRANDS = ["RICOH", "FUJIFILM", "Sony", "Leica", "Nikon", "Canon"]

# ブランド名マッピング（表記ゆれ対応）
BRAND_ALIASES: dict[str, str] = {
    "リコー": "RICOH",
    "RICOH": "RICOH",
    "富士フイルム": "FUJIFILM",
    "FUJIFILM": "FUJIFILM",
    "FUJI": "FUJIFILM",
    "ソニー": "Sony",
    "Sony": "Sony",
    "SONY": "Sony",
    "ライカ": "Leica",
    "Leica": "Leica",
    "LEICA": "Leica",
    "ニコン": "Nikon",
    "Nikon": "Nikon",
    "NIKON": "Nikon",
    "キヤノン": "Canon",
    "Canon": "Canon",
    "CANON": "Canon",
}


def _infer_brand(product_name: str) -> str:
    """商品名からブランドを推定する。"""
    for alias, brand in BRAND_ALIASES.items():
        if alias.lower() in product_name.lower():
            return brand
    return ""


class CameraRetailersLotteryCollector(BaseLotteryCollector):
    """カメラ販売店（マップカメラ / キタムラ）の抽選販売情報を収集するコレクター。"""

    SHOP_ID = "camera_retailers"
    SHOP_NAME = "カメラ販売店"
    REQUIRES_JS = False

    def collect(self) -> list[dict]:
        """全販売店の抽選ページを取得して商品ごとのイベントを返す。"""
        events: list[dict] = []
        for retailer in RETAILERS:
            retailer_events = self._collect_retailer(retailer)
            events.extend(retailer_events)
            self._sleep()
        return events

    def _collect_retailer(self, retailer: dict) -> list[dict]:
        """1 販売店の抽選ページをスクレイピングして複数商品を返す。"""
        url = retailer["lottery_url"]
        shop_name = retailer["shop_name"]
        shop_id = retailer["shop_id"]

        # requires_js が True の場合は Playwright を使用
        if retailer.get("requires_js"):
            text = self._fetch_with_playwright(url)
        else:
            text = self._fetch_page_text(url)

        if not text:
            logger.warning("[%s] ページ取得失敗: %s (%s)", self.SHOP_ID, shop_name, url)
            return []

        # 抽選商品ブロックを抽出
        products = self._extract_lottery_products(text, url, shop_name, shop_id)
        logger.info("[%s] %s: %d件取得", self.SHOP_ID, shop_name, len(products))
        return products

    def _extract_lottery_products(
        self, text: str, source_url: str, shop_name: str, shop_id: str
    ) -> list[dict]:
        """テキストから抽選商品情報を抽出して dict リストを返す。"""
        events: list[dict] = []

        # 対象ブランドの商品が含まれているか確認
        found_brands = [b for b in TARGET_BRANDS if b.lower() in text.lower()]
        if not found_brands:
            # エイリアスでも確認
            for alias, brand in BRAND_ALIASES.items():
                if alias in text and brand in TARGET_BRANDS:
                    if brand not in found_brands:
                        found_brands.append(brand)

        if not found_brands:
            logger.info("[%s] %s: 対象ブランドの商品なし", self.SHOP_ID, shop_name)
            return []

        # 商品名らしき行を抽出（ブランド名を含む行）
        lines = text.split("\n") if "\n" in text else text.split("  ")
        product_lines = self._find_product_lines(lines)

        for product_name, product_text in product_lines:
            brand = _infer_brand(product_name)
            if not brand:
                continue

            # 日付パース
            entry_start_at, entry_end_at = self._parse_dates_from_text(product_text)
            status = self._determine_status(entry_start_at, entry_end_at)

            # 価格抽出
            official_price = self._extract_price(product_text)

            # フォーム URL
            entry_form_url = self._extract_form_url(product_text)

            events.append(self._make_event(
                product_name=product_name,
                brand=brand,
                product_code="",
                official_price=official_price,
                url=source_url,
                entry_form_url=entry_form_url,
                source_url=source_url,
                entry_start_at=entry_start_at,
                entry_end_at=entry_end_at,
                status=status,
                note=f"{shop_name} 抽選ページより取得",
            ))

        return events

    def _find_product_lines(self, lines: list[str]) -> list[tuple[str, str]]:
        """行リストから商品名とその周辺テキストのペアを抽出する。"""
        results: list[tuple[str, str]] = []
        for i, line in enumerate(lines):
            line = line.strip()
            # ブランド名を含む行を商品名の候補とする
            for alias in BRAND_ALIASES:
                if alias.lower() in line.lower() and len(line) > 5:
                    # 商品名の周辺テキストをコンテキストとして取得
                    start = max(0, i - 2)
                    end = min(len(lines), i + 15)
                    context = " ".join(lines[start:end])
                    results.append((line, context))
                    break
        return results

    def _extract_price(self, text: str) -> str:
        """テキストから価格を抽出する。"""
        # ¥XX,XXX（税込）形式
        m = re.search(r"[¥￥][\d,]+(?:\s*（税込）)?", text)
        if m:
            return m.group(0)
        # 数字+円形式
        m = re.search(r"[\d,]+\s*円(?:\s*（税込）)?", text)
        if m:
            return m.group(0)
        return ""

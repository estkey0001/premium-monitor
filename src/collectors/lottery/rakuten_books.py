"""
RakutenBooksLotteryCollector — 楽天ブックス 抽選販売コレクター

調査日: 2026-05-27
URL: https://books.rakuten.co.jp/
取得方式: requests（JS 不要）
価格形式: ¥XX,XXX（税込）
対象商品: Nintendo Switch 2 / PlayStation 5 Pro
抽出キーワード: 「抽選」「申込受付」「先行予約」
"""

from __future__ import annotations

import logging

from .base import BaseLotteryCollector

logger = logging.getLogger(__name__)

# 既知商品リスト（JAN コードベース）
KNOWN_PRODUCTS = [
    {
        "product_name": "Nintendo Switch 2",
        "product_code": "4902370551242",  # JAN コード
        "brand": "Nintendo",
        "official_price": "¥49,980（税込）",
        "url": "https://books.rakuten.co.jp/search?sgenre=101&keyword=Switch+2",
    },
    {
        "product_name": "PlayStation 5 Pro",
        "product_code": "4948872415934",  # JAN コード
        "brand": "Sony",
        "official_price": "¥119,980（税込）",
        "url": "https://books.rakuten.co.jp/search?sgenre=101&keyword=PS5+Pro",
    },
]

# 抽選・先行予約を示すキーワード
LOTTERY_KEYWORDS = ["抽選", "申込受付", "先行予約", "先行販売", "抽選販売", "エントリー"]


class RakutenBooksLotteryCollector(BaseLotteryCollector):
    """楽天ブックスの抽選販売情報を収集するコレクター。"""

    SHOP_ID = "rakuten_books"
    SHOP_NAME = "楽天ブックス"
    REQUIRES_JS = False

    def collect(self) -> list[dict]:
        """全既知商品の抽選情報を取得して返す。"""
        events: list[dict] = []
        for product in KNOWN_PRODUCTS:
            event = self._collect_product(product)
            if event is not None:
                events.append(event)
            self._sleep()
        return events

    def _collect_product(self, product: dict) -> dict | None:
        """1 商品の抽選情報を取得する。失敗時は None。"""
        url = product["url"]
        text = self._fetch_page_text(url)
        if not text:
            logger.warning(
                "[%s] ページ取得失敗: %s (%s)", self.SHOP_ID, product["product_name"], url
            )
            return None

        # 抽選・先行予約キーワードを検索
        is_lottery = any(kw in text for kw in LOTTERY_KEYWORDS)
        if not is_lottery:
            logger.info(
                "[%s] 抽選情報なし: %s", self.SHOP_ID, product["product_name"]
            )
            return self._make_event(
                product_name=product["product_name"],
                brand=product["brand"],
                product_code=product["product_code"],
                official_price=product["official_price"],
                url=url,
                source_url=url,
                status="closed",
                note="抽選キーワード未検出",
            )

        # 抽選キーワード近傍から日付を抽出
        lottery_text = self._extract_lottery_block(text)
        entry_start_at, entry_end_at = self._parse_dates_from_text(lottery_text or text)
        status = self._determine_status(entry_start_at, entry_end_at)

        # フォーム URL
        entry_form_url = self._extract_form_url(text)

        logger.info(
            "[%s] 取得成功: %s status=%s start=%s end=%s",
            self.SHOP_ID, product["product_name"], status, entry_start_at, entry_end_at,
        )

        return self._make_event(
            product_name=product["product_name"],
            brand=product["brand"],
            product_code=product["product_code"],
            official_price=product["official_price"],
            url=url,
            entry_form_url=entry_form_url,
            source_url=url,
            entry_start_at=entry_start_at,
            entry_end_at=entry_end_at,
            status=status,
        )

    def _extract_lottery_block(self, text: str) -> str | None:
        """「抽選」「申込受付」「先行予約」キーワード近傍のテキストブロックを抽出する。"""
        for kw in LOTTERY_KEYWORDS:
            idx = text.find(kw)
            if idx != -1:
                return text[max(0, idx - 100): idx + 600]
        return None

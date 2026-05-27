"""
SonyLotteryCollector — Sony Store Japan 抽選販売コレクター

調査日: 2026-05-27
URL: https://store.sony.jp/
取得方式: requests（JS 不要）
価格形式: ¥XXX,XXX（税込）
対象商品: PlayStation 5 Pro / SONY α ZV-E10 II
抽出キーワード: 「抽選」「先行販売」「応募」を含むブロックを抽出
"""

from __future__ import annotations

import logging

from .base import BaseLotteryCollector

logger = logging.getLogger(__name__)

# 既知商品リスト
KNOWN_PRODUCTS = [
    {
        "product_name": "PlayStation 5 Pro",
        "product_code": "CFI-7000B01",
        "brand": "Sony",
        "official_price": "¥119,980（税込）",
        "url": "https://store.sony.jp/category/gaming/playstation/ps5/",
        "search_url": "https://store.sony.jp/",
    },
    {
        "product_name": "SONY α ZV-E10 II",
        "product_code": "ZV-E10M2",
        "brand": "Sony",
        "official_price": "¥120,000（税込）",
        "url": "https://store.sony.jp/category/camera/interchangeable_lens/zv-series/",
        "search_url": "https://store.sony.jp/",
    },
]

# 抽選・先行販売を示すキーワード
LOTTERY_KEYWORDS = ["抽選", "先行販売", "応募", "先行予約", "抽せん", "エントリー"]


class SonyLotteryCollector(BaseLotteryCollector):
    """Sony Store Japan の抽選販売情報を収集するコレクター。"""

    SHOP_ID = "sony_store"
    SHOP_NAME = "Sony Store Japan"
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

        # 抽選キーワードを含むかチェック
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

        # 抽選・先行販売ブロックを抽出して日付を探す
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
        """「抽選」「先行販売」「応募」キーワードを含むブロックを抽出する。"""
        for kw in LOTTERY_KEYWORDS:
            idx = text.find(kw)
            if idx != -1:
                # キーワード前後 600 文字を返す
                return text[max(0, idx - 100): idx + 600]
        return None

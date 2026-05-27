"""
FujifilmLotteryCollector — 富士フイルム X ストア 抽選販売コレクター

調査日: 2026-05-27
URL: https://shop.fujifilm-x.com/
取得方式: requests（JS 不要）
価格形式: ¥XXX,XXX（税込）
対象商品: FUJIFILM GFX 100RF Limited Edition / FUJIFILM X100VI
"""

from __future__ import annotations

import logging

from .base import BaseLotteryCollector

logger = logging.getLogger(__name__)

# 既知商品リスト
KNOWN_PRODUCTS = [
    {
        "product_name": "FUJIFILM GFX 100RF Limited Edition",
        "product_code": "GFX100RF-LE",
        "brand": "FUJIFILM",
        "official_price": "要確認",
        "url": "https://shop.fujifilm-x.com/shopping/goods/limited/",
    },
    {
        "product_name": "FUJIFILM X100VI",
        "product_code": "X100VI",
        "brand": "FUJIFILM",
        "official_price": "¥253,000（税込）",
        "url": "https://shop.fujifilm-x.com/shopping/goods/16779901/",
    },
]


class FujifilmLotteryCollector(BaseLotteryCollector):
    """富士フイルム X ストアの抽選販売情報を収集するコレクター。"""

    SHOP_ID = "fujifilm_x_store"
    SHOP_NAME = "富士フイルム X ストア"
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

        # 抽選販売・申込期間キーワード確認
        lottery_keywords = ["抽選", "申込受付", "受付期間", "申込期間", "先行販売", "応募"]
        is_lottery = any(kw in text for kw in lottery_keywords)
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
                note="抽選情報未検出",
            )

        # 日付パース（「受付期間」「申込期間」近傍を優先）
        entry_start_at, entry_end_at = self._parse_dates_from_text(text)
        status = self._determine_status(entry_start_at, entry_end_at)

        # フォーム URL（Google フォームまたはサイト内フォーム）
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

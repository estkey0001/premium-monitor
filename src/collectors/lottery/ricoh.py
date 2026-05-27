"""
RicohLotteryCollector — RICOH Imaging Store 抽選販売コレクター

調査日: 2026-05-27
URL: https://ricohimagingstore.com/Form/Product/ProductDetail.aspx?shop=0&pid={product_code}&cat={category}
取得方式: requests（JS 不要）
価格形式: ¥XXX,XXX（税込）
対象商品: RICOH GR IV Monochrome / GR IV HDF / GR IV
"""

from __future__ import annotations

import logging

from .base import BaseLotteryCollector

logger = logging.getLogger(__name__)

# 既知商品リスト
PRODUCTS = [
    {
        "product_code": "S0001580",
        "product_name": "RICOH GR IV Monochrome",
        "official_price": "¥283,800（税込）",
        "category": "002010",
    },
    {
        "product_code": "S0001566",
        "product_name": "RICOH GR IV HDF",
        "official_price": "¥187,020（税込）",
        "category": "002010",
    },
    {
        "product_code": "S0001551",
        "product_name": "RICOH GR IV",
        "official_price": "¥194,800（税込）",
        "category": "002010",
    },
]

BASE_URL = "https://ricohimagingstore.com/Form/Product/ProductDetail.aspx"


class RicohLotteryCollector(BaseLotteryCollector):
    """RICOH Imaging Store の抽選販売情報を収集するコレクター。"""

    SHOP_ID = "ricoh_imaging_store"
    SHOP_NAME = "RICOH Imaging Store"
    REQUIRES_JS = False

    def collect(self) -> list[dict]:
        """全既知商品の抽選情報を取得して返す。"""
        events: list[dict] = []
        for product in PRODUCTS:
            event = self._collect_product(product)
            if event is not None:
                events.append(event)
            self._sleep()
        return events

    def _collect_product(self, product: dict) -> dict | None:
        """1 商品の抽選情報を取得する。失敗時は None。"""
        url = (
            f"{BASE_URL}"
            f"?shop=0&pid={product['product_code']}&cat={product['category']}"
        )
        text = self._fetch_page_text(url)
        if not text:
            logger.warning(
                "[%s] ページ取得失敗: %s (%s)", self.SHOP_ID, product["product_name"], url
            )
            return None

        # 抽選販売ページかどうか確認
        lottery_keywords = ["抽選", "先行販売", "先行予約", "申込", "応募", "エントリー"]
        is_lottery = any(kw in text for kw in lottery_keywords)
        if not is_lottery:
            logger.info(
                "[%s] 抽選情報なし: %s", self.SHOP_ID, product["product_name"]
            )
            # 抽選情報がなくても closed として記録する
            return self._make_event(
                product_name=product["product_name"],
                brand="RICOH",
                product_code=product["product_code"],
                official_price=product["official_price"],
                url=url,
                source_url=url,
                status="closed",
                note="抽選情報未検出",
            )

        # 日付パース
        entry_start_at, entry_end_at = self._parse_dates_from_text(text)
        status = self._determine_status(entry_start_at, entry_end_at)

        # フォーム URL
        entry_form_url = self._extract_form_url(text)

        logger.info(
            "[%s] 取得成功: %s status=%s start=%s end=%s",
            self.SHOP_ID, product["product_name"], status, entry_start_at, entry_end_at,
        )

        return self._make_event(
            product_name=product["product_name"],
            brand="RICOH",
            product_code=product["product_code"],
            official_price=product["official_price"],
            url=url,
            entry_form_url=entry_form_url,
            source_url=url,
            entry_start_at=entry_start_at,
            entry_end_at=entry_end_at,
            status=status,
        )

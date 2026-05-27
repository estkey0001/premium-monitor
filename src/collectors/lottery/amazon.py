"""
AmazonLotteryCollector — Amazon 招待制購入コレクター

調査日: 2026-05-27
URL: https://www.amazon.co.jp/dp/{ASIN}
取得方式: requests（IP ブロックが多いため失敗時は fetch_failed として記録）
価格形式: ¥XX,XXX（税込）
対象商品: Nintendo Switch 2 / PlayStation 5 Pro
注意: Amazon は IP ブロックが多いため失敗時は raise せず fetch_failed として記録する
"""

from __future__ import annotations

import logging

from .base import BaseLotteryCollector

logger = logging.getLogger(__name__)

# 既知商品リスト（ASIN ベース）
KNOWN_PRODUCTS = [
    {
        "product_name": "Nintendo Switch 2",
        "product_code": "B0CX2YNK6V",  # ASIN
        "brand": "Nintendo",
        "official_price": "¥49,980（税込）",
        "url": "https://www.amazon.co.jp/dp/B0CX2YNK6V",
    },
    {
        "product_name": "PlayStation 5 Pro",
        "product_code": "B0CPQWJHFF",  # ASIN
        "brand": "Sony",
        "official_price": "¥119,980（税込）",
        "url": "https://www.amazon.co.jp/dp/B0CPQWJHFF",
    },
]

# 招待制購入を示すキーワード
INVITE_KEYWORDS = ["招待制購入", "Invitation", "招待を受けた", "招待のみ", "By Invitation"]


class AmazonLotteryCollector(BaseLotteryCollector):
    """Amazon 招待制購入の情報を収集するコレクター。"""

    SHOP_ID = "amazon_jp"
    SHOP_NAME = "Amazon.co.jp"
    REQUIRES_JS = False

    def collect(self) -> list[dict]:
        """全既知商品の招待制購入情報を取得して返す。"""
        events: list[dict] = []
        for product in KNOWN_PRODUCTS:
            event = self._collect_product(product)
            if event is not None:
                events.append(event)
            self._sleep()
        return events

    def _collect_product(self, product: dict) -> dict | None:
        """
        1 商品の招待制購入情報を取得する。
        Amazon は IP ブロックが多いため失敗時は fetch_failed として記録する（raise しない）。
        """
        url = product["url"]
        text = self._fetch_page_text(url)

        if not text:
            # 取得失敗は fetch_failed として記録（スキップせず記録する）
            logger.warning(
                "[%s] ページ取得失敗 (IP ブロック等): %s (%s)",
                self.SHOP_ID, product["product_name"], url,
            )
            return self._make_event(
                product_name=product["product_name"],
                brand=product["brand"],
                product_code=product["product_code"],
                official_price=product["official_price"],
                url=url,
                source_url=url,
                status="active",  # 不明は保守的に active
                note="fetch_failed: IP ブロックまたはタイムアウト",
            )

        # 招待制購入キーワードの確認
        is_invite = any(kw in text for kw in INVITE_KEYWORDS)

        if is_invite:
            # 招待制購入として記録
            sale_method = "招待制購入"
            status = "active"
            logger.info(
                "[%s] 招待制購入確認: %s", self.SHOP_ID, product["product_name"]
            )
        else:
            # 通常販売または取扱なし
            sale_method = "抽選販売"
            status = "closed"
            logger.info(
                "[%s] 招待制購入キーワードなし: %s", self.SHOP_ID, product["product_name"]
            )

        # 日付パース（Amazon は通常期間表示がないため空になることが多い）
        entry_start_at, entry_end_at = self._parse_dates_from_text(text)

        # フォーム URL（Amazon は通常なし）
        entry_form_url = self._extract_form_url(text)

        return self._make_event(
            product_name=product["product_name"],
            brand=product["brand"],
            product_code=product["product_code"],
            official_price=product["official_price"],
            sale_method=sale_method,
            url=url,
            entry_form_url=entry_form_url,
            source_url=url,
            entry_start_at=entry_start_at,
            entry_end_at=entry_end_at,
            status=status,
        )

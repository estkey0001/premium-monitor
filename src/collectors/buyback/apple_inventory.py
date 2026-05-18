"""Apple Store 在庫・価格Collector。

Apple公式サイト (apple.com/jp) から以下を取得:
- 公式価格
- 在庫状態
- SIMフリー / 容量 / 色
- 購入URL

注意: Apple公式APIは存在するが非公開。
HTMLパーシングで取得し、変更検知はrate limitを守って行う。
"""

import json
import logging
import re
from typing import Optional

from src.collectors.buyback.base_buyback import BaseBuybackCollector
from src.models.product import ProductModel
from src.models.buyback_price import BuybackPriceModel

logger = logging.getLogger(__name__)

# Apple製品の公式ストアURL
APPLE_PRODUCT_URLS = {
    "prod_iphone17pro_256": "https://www.apple.com/jp/shop/buy-iphone/iphone-17-pro",
    "prod_iphone16pm_256": "https://www.apple.com/jp/shop/buy-iphone/iphone-16-pro-max",
    "prod_iphone16pm_512": "https://www.apple.com/jp/shop/buy-iphone/iphone-16-pro-max",
    "prod_ipad_pro_m4": "https://www.apple.com/jp/shop/buy-ipad/ipad-pro",
    "prod_macbook_air_m3": "https://www.apple.com/jp/shop/buy-mac/macbook-air",
    "prod_macbook_pro_m4": "https://www.apple.com/jp/shop/buy-mac/macbook-pro",
    "prod_apple_watch_ultra2": "https://www.apple.com/jp/shop/buy-watch/apple-watch-ultra",
}


class AppleInventoryInfo:
    """Apple公式から取得した在庫情報。"""

    def __init__(self):
        self.price: Optional[int] = None
        self.in_stock: Optional[bool] = None
        self.url: str = ""
        self.sim_free: bool = True  # Apple公式はすべてSIMフリー
        self.variants: list[dict] = []  # 容量・色別のバリエーション


class AppleInventoryCollector(BaseBuybackCollector):
    """Apple公式サイトの在庫・価格情報を取得する。

    注意: これは買取Collectorではなく「公式側」のCollector。
    BaseBuybackCollectorを継承しているがcollect()は使わず、
    check_inventory()で在庫情報を返す。
    """

    SHOP_ID = "src_apple_jp"
    SHOP_NAME = "Apple公式"
    BASE_URL = "https://www.apple.com/jp/"
    REQUIRES_JS = True

    def _build_url(self, product: ProductModel) -> str:
        return APPLE_PRODUCT_URLS.get(product.id, "")

    def _parse_buyback_price(self, html: str, product: ProductModel) -> Optional[int]:
        # Appleは買取ではないので公式価格を返す
        return self._parse_official_price(html, product)

    def check_inventory(self, product: ProductModel) -> AppleInventoryInfo:
        """Apple公式の在庫・価格を取得する。"""
        info = AppleInventoryInfo()
        url = self._build_url(product)
        if not url:
            return info

        info.url = url
        html = self._fetch_html(url)
        if not html:
            return info

        info.price = self._parse_official_price(html, product)
        info.in_stock = self._check_in_stock(html)
        info.sim_free = True  # Apple公式は全てSIMフリー

        return info

    def _parse_official_price(self, html: str, product: ProductModel) -> Optional[int]:
        """公式価格を抽出する。"""
        # Apple公式の価格パターン
        patterns = [
            r'¥([\d,]+)\s*\(税込\)',
            r'¥([\d,]+)</span>',
            r'"price":\s*"?(\d+)"?',
            r'data-price="(\d+)"',
        ]
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 10000 <= price <= 1_000_000:
                        return price
                except ValueError:
                    continue

        # retail_priceからフォールバック
        return product.retail_price if product.retail_price else None

    def _check_in_stock(self, html: str) -> Optional[bool]:
        """在庫状態を判定する。"""
        out_of_stock_patterns = [
            "在庫切れ", "現在ご購入いただけません", "入荷待ち",
            "sold out", "unavailable", "out of stock",
        ]
        html_lower = html.lower()
        for pat in out_of_stock_patterns:
            if pat.lower() in html_lower:
                return False

        add_to_cart = ["カートに入れる", "バッグに追加", "add to bag", "購入する"]
        for pat in add_to_cart:
            if pat.lower() in html_lower:
                return True

        return None

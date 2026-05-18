"""モバイル一番 買取価格Collector。

iPhone / iPad / Apple Watch の買取に強い。
サイト: https://mobileno1.com/
JS描画の可能性あり → Playwright fallback対応。
"""

import logging
import re
from typing import Optional

from src.collectors.buyback.base_buyback import BaseBuybackCollector
from src.models.product import ProductModel

logger = logging.getLogger(__name__)

# 商品別の検索URL (手動マッピング)
PRODUCT_URLS = {
    "prod_iphone17pro_256": "https://mobileno1.com/kaitori/iphone17pro/",
    "prod_iphone16pm_256": "https://mobileno1.com/kaitori/iphone16promax/",
    "prod_iphone16pm_512": "https://mobileno1.com/kaitori/iphone16promax/",
}


class MobileIchibanCollector(BaseBuybackCollector):
    """モバイル一番の買取価格を取得する。"""

    SHOP_ID = "src_mobile_ichiban"
    SHOP_NAME = "モバイル一番"
    BASE_URL = "https://mobileno1.com/"
    REQUIRES_JS = True

    def _build_url(self, product: ProductModel) -> str:
        return PRODUCT_URLS.get(product.id, "")

    def _parse_buyback_price(self, html: str, product: ProductModel) -> Optional[int]:
        """買取価格を抽出する。

        モバイル一番のページ構造に合わせたパーサー。
        容量とSIMフリー条件でマッチングを試みる。
        """
        # キーワードでマッチング
        keywords = product.keywords + [product.name]
        for kw in keywords:
            # キーワード周辺から価格を探す
            pattern = re.escape(kw) + r'.{0,200}?買取.{0,50}?[¥￥]\s*([\d,]+)'
            m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if m:
                price_str = m.group(1).replace(",", "")
                try:
                    return int(price_str)
                except ValueError:
                    continue

        # フォールバック: ページ内の最高買取価格
        return self.extract_price_from_text(html)

    def _parse_condition(self, html: str, product: ProductModel) -> str:
        if "SIMフリー" in html or "simfree" in html.lower():
            return "new_unopened_simfree"
        return "new_unopened"

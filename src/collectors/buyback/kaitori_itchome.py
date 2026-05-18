"""買取一丁目 買取価格Collector。

iPhone / iPad / MacBook の買取に特化。
サイト: https://kaitori-1chome.com/
"""

import logging
import re
from typing import Optional

from src.collectors.buyback.base_buyback import BaseBuybackCollector
from src.models.product import ProductModel

logger = logging.getLogger(__name__)

PRODUCT_URLS = {
    "prod_iphone17pro_256": "https://kaitori-1chome.com/item/iphone17pro/",
    "prod_iphone16pm_256": "https://kaitori-1chome.com/item/iphone16promax/",
}


class KaitoriItchomeCollector(BaseBuybackCollector):
    """買取一丁目の買取価格を取得する。"""

    SHOP_ID = "src_kaitori_itchome"
    SHOP_NAME = "買取一丁目"
    BASE_URL = "https://kaitori-1chome.com/"
    REQUIRES_JS = True

    def _build_url(self, product: ProductModel) -> str:
        return PRODUCT_URLS.get(product.id, "")

    def _parse_buyback_price(self, html: str, product: ProductModel) -> Optional[int]:
        for kw in product.keywords + [product.name]:
            pattern = re.escape(kw) + r'.{0,300}?([\d,]{5,})\s*円'
            m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if m:
                try:
                    return int(m.group(1).replace(",", ""))
                except ValueError:
                    continue
        return self.extract_price_from_text(html)

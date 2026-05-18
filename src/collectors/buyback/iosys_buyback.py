"""イオシス 買取価格Collector（BuybackPriceModel版）。"""

import logging
import re
from typing import Optional

from src.collectors.buyback.base_buyback import BaseBuybackCollector
from src.models.product import ProductModel

logger = logging.getLogger(__name__)

PRODUCT_URLS = {
    "prod_iphone17pro_256": "https://iosys.co.jp/items/smartphone/iphone/iphone17pro",
    "prod_iphone16pm_256": "https://iosys.co.jp/items/smartphone/iphone/iphone16promax",
    "prod_switch2": "https://iosys.co.jp/items/game/nintendoswitch2",
    "prod_ps5_pro": "https://iosys.co.jp/items/game/ps5pro",
    "prod_gr4": "https://iosys.co.jp/items/camera/ricoh/griv",
    "prod_x100vi": "https://iosys.co.jp/items/camera/fujifilm/x100vi",
}


class IosysBuybackCollector(BaseBuybackCollector):
    """イオシス買取価格Collector。"""

    SHOP_ID = "src_iosys"
    SHOP_NAME = "イオシス"
    BASE_URL = "https://iosys.co.jp/"
    REQUIRES_JS = False

    def _build_url(self, product: ProductModel) -> str:
        return PRODUCT_URLS.get(product.id, "")

    def _parse_buyback_price(self, html: str, product: ProductModel) -> Optional[int]:
        patterns = [
            r'買取価格[^¥￥\d]*[¥￥]\s*([\d,]+)',
            r'買取上限[^¥￥\d]*[¥￥]\s*([\d,]+)',
            r'買取[^¥￥\d]{0,30}([\d,]{5,})\s*円',
        ]
        for pat in patterns:
            m = re.search(pat, html)
            if m:
                try:
                    price = int(m.group(1).replace(",", ""))
                    if 1000 <= price <= 10_000_000:
                        return price
                except ValueError:
                    continue
        return self.extract_price_from_text(html)

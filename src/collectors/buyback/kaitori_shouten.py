"""買取商店 買取価格Collector。

iPhone / ゲーム機 / カメラの買取に対応。
サイト: https://kaitori-shouten.com/
"""

import logging
import re
from typing import Optional

from src.collectors.buyback.base_buyback import BaseBuybackCollector
from src.models.product import ProductModel

logger = logging.getLogger(__name__)

PRODUCT_URLS = {
    "prod_iphone17pro_256": "https://kaitori-shouten.com/iphone/iphone17pro/",
    "prod_iphone16pm_256": "https://kaitori-shouten.com/iphone/iphone16promax/",
    "prod_switch2": "https://kaitori-shouten.com/game/switch2/",
    "prod_ps5_pro": "https://kaitori-shouten.com/game/ps5pro/",
}


class KaitoriShoutenCollector(BaseBuybackCollector):
    """買取商店の買取価格を取得する。"""

    SHOP_ID = "src_kaitori_shouten"
    SHOP_NAME = "買取商店"
    BASE_URL = "https://kaitori-shouten.com/"
    REQUIRES_JS = False

    def _build_url(self, product: ProductModel) -> str:
        return PRODUCT_URLS.get(product.id, "")

    def _parse_buyback_price(self, html: str, product: ProductModel) -> Optional[int]:
        # 買取価格パターン
        for kw in product.keywords + [product.name]:
            pattern = re.escape(kw) + r'.{0,300}?買取.{0,80}?[¥￥]([\d,]+)'
            m = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if m:
                try:
                    return int(m.group(1).replace(",", ""))
                except ValueError:
                    continue
        return self.extract_price_from_text(html)

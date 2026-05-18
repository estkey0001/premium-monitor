"""じゃんぱら 買取価格Collector（BuybackPriceModel版）。

既存の JanparaCollector を補完する買取専用Collector。
直接スクレイピングが困難な場合はCSV fallback推奨。
"""

import logging
import re
from typing import Optional

from src.collectors.buyback.base_buyback import BaseBuybackCollector
from src.models.product import ProductModel

logger = logging.getLogger(__name__)

PRODUCT_URLS = {
    "prod_iphone17pro_256": "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+17+Pro+256",
    "prod_iphone16pm_256": "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=iPhone+16+Pro+Max+256",
    "prod_switch2": "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=Switch+2",
    "prod_ps5_pro": "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=PS5+Pro",
    "prod_gr4": "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=GR+IV",
    "prod_x100vi": "https://www.janpara.co.jp/buy/search/result/?KEYWORDS=X100VI",
}


class JanparaBuybackCollector(BaseBuybackCollector):
    """じゃんぱら買取価格Collector。"""

    SHOP_ID = "src_janpara"
    SHOP_NAME = "じゃんぱら"
    BASE_URL = "https://www.janpara.co.jp/"
    REQUIRES_JS = True  # Cookie/CSRF必須

    def _build_url(self, product: ProductModel) -> str:
        return PRODUCT_URLS.get(product.id, "")

    def _parse_buyback_price(self, html: str, product: ProductModel) -> Optional[int]:
        # 「買取上限」「買取価格」パターン
        patterns = [
            r'買取上限[^¥￥\d]*[¥￥]\s*([\d,]+)',
            r'買取価格[^¥￥\d]*[¥￥]\s*([\d,]+)',
            r'買取[^¥￥\d]{0,20}[¥￥]\s*([\d,]+)',
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

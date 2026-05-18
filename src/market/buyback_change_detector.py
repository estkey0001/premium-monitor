"""買取価格急変検知エンジン。

buyback_historyから前回→今回の差分を計算し、
+5,000円以上 → buyback_surge
-5,000円以上 → buyback_drop
を検知してbuyback_alertsに記録する。
"""

import logging
from datetime import datetime
from typing import Optional

from src.db.repository import Repository
from src.models.buyback_price import BUYBACK_SHOPS

logger = logging.getLogger(__name__)

SURGE_THRESHOLD = 5000   # 急騰閾値
DROP_THRESHOLD = -5000   # 急落閾値


class BuybackChangeDetector:
    """買取価格の急変を検知する。"""

    def __init__(self, repository: Repository):
        self.repo = repository

    def detect_all(self) -> list[dict]:
        """全商品×全店舗の急変を検知する。"""
        products = self.repo.list_products()
        shop_ids = list(BUYBACK_SHOPS.keys())

        alerts = []
        for product in products:
            for shop_id in shop_ids:
                result = self.detect_change(product.id, product.name, shop_id)
                if result:
                    alerts.append(result)

        return alerts

    def detect_change(self, product_id: str, product_name: str,
                       shop_id: str) -> Optional[dict]:
        """1商品×1店舗の急変を検知する。"""
        current = self.repo.get_latest_buyback_price(product_id, shop_id)
        previous = self.repo.get_previous_buyback_price(product_id, shop_id, offset=1)

        if current is None or previous is None:
            return None

        change = current - previous
        shop_name = BUYBACK_SHOPS.get(shop_id, {}).get("name", shop_id)

        if change >= SURGE_THRESHOLD:
            alert_type = "buyback_surge"
        elif change <= DROP_THRESHOLD:
            alert_type = "buyback_drop"
        else:
            return None

        # DB記録
        self.repo.insert_buyback_alert(
            product_id=product_id,
            product_name=product_name,
            shop_id=shop_id,
            shop_name=shop_name,
            alert_type=alert_type,
            previous_price=previous,
            current_price=current,
            price_change=change,
        )

        logger.info(
            "Buyback %s: %s @ %s: ¥%s → ¥%s (%+d)",
            alert_type, product_name, shop_name,
            f"{previous:,}", f"{current:,}", change,
        )

        return {
            "product_id": product_id,
            "product_name": product_name,
            "shop_id": shop_id,
            "shop_name": shop_name,
            "alert_type": alert_type,
            "previous_price": previous,
            "current_price": current,
            "price_change": change,
        }

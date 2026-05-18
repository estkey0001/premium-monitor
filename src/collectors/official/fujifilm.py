"""FUJIFILM公式サイト Collector。

fujifilm-x.com の製品ページから以下を取得する:
- 希望小売価格（オープン価格の場合はNone）
- 抽選販売情報
- 発売日
- JANコード

Chrome調査結果 (2026-05-17):
  URL: fujifilm-x.com/ja-jp/products/cameras/x100vi/
  価格: "希望小売価格 オープン価格" → 定価取得不可
  抽選: "抽選受付開始日" テキストあり
  発売日: "2024年3月28日" テキストあり
  JANコード: "45-47410-528282" テキストあり
  SSR: requestsで取得可能（get_page_textで全文取得成功）
"""

import json
import logging
import re
from datetime import datetime
from typing import Optional

import ulid

from src.collectors.base import BaseCollector
from src.models.observation import ObservationModel, PriceHistoryModel
from src.models.product import ProductModel
from src.models.source import ProductSourceConfigModel
from src.pipeline.normalizer import Normalizer

logger = logging.getLogger(__name__)


class FujifilmOfficialCollector(BaseCollector):
    """FUJIFILM公式サイト Collector。"""

    def collect(
        self, product: ProductModel, config: ProductSourceConfigModel
    ) -> Optional[ObservationModel]:
        url = config.target_url
        if not url:
            self.logger.error("No target_url for %s", product.id)
            return None

        started_at = datetime.now()
        html = self.fetch_page(url)
        if html is None:
            self.log_collection(product.id, started_at, "error", error_message="fetch failed")
            return None

        try:
            result = self._parse(html, url)
        except Exception as e:
            self.logger.error("Parse error: %s", e)
            self.log_collection(product.id, started_at, "error", error_message=str(e))
            return None

        now = datetime.now()
        obs = ObservationModel(
            id=str(ulid.new()),
            product_id=product.id,
            source_id=self.source.id,
            observation_type="official_price",
            observed_at=now,
            is_in_stock=result.get("is_in_stock"),
            price=result["price"],
            lottery_status=result.get("lottery_status"),
            raw_text=json.dumps(result["raw"], ensure_ascii=False),
            raw_html_hash=self.hash_html(html),
            confidence=0.99,
        )
        self.repository.insert_observation(obs)

        if result["price"]:
            self.repository.insert_price_history(PriceHistoryModel(
                id=str(ulid.new()),
                product_id=product.id,
                source_id=self.source.id,
                price_type="retail",
                price=result["price"],
                recorded_at=now,
            ))

        self.log_collection(product.id, started_at, "success")
        self.logger.info(
            "fujifilm_official | %s | price=%s | lottery=%s",
            product.name,
            f"¥{result['price']:,}" if result['price'] else "オープン価格",
            result.get("lottery_status", "N/A"),
        )
        return obs

    def _parse(self, html: str, url: str) -> dict:
        result = {
            "price": None,
            "is_in_stock": None,
            "lottery_status": None,
            "raw": {"url": url},
        }

        soup = self.parse_html(html)
        page_text = soup.get_text()

        # 希望小売価格
        price_match = re.search(r"希望小売価格\s*[：:]?\s*([¥￥]?[\d,]+円?|オープン価格)", page_text)
        if price_match:
            price_text = price_match.group(1)
            result["raw"]["official_price_text"] = price_text
            if "オープン" in price_text:
                result["price"] = None
                result["raw"]["is_open_price"] = True
            else:
                result["price"] = Normalizer.parse_price(price_text)

        # 抽選情報
        if "抽選受付開始" in page_text or "抽選販売" in page_text:
            result["raw"]["has_lottery"] = True
            if "受付中" in page_text:
                result["lottery_status"] = "open"
            elif "受付終了" in page_text or "当選発表" in page_text:
                result["lottery_status"] = "closed"
            else:
                result["lottery_status"] = "upcoming"

        # 抽選受付開始日
        lottery_date = re.search(r"抽選受付開始日\s*[：:]?\s*(.+?)(?:\n|$)", page_text)
        if lottery_date:
            result["raw"]["lottery_date"] = lottery_date.group(1).strip()

        # 発売日
        release_match = re.search(r"発売日\s*[：:]?\s*(.+?)(?:\n|$)", page_text)
        if release_match:
            result["raw"]["release_date"] = release_match.group(1).strip()

        # JANコード
        jan_match = re.search(r"JANコード\s*[：:]?\s*([\d\-]+)", page_text)
        if jan_match:
            result["raw"]["jan_code"] = jan_match.group(1)

        # 製品型番
        model_match = re.search(r"製品型番\s*[：:]?\s*(.+?)(?:\s*/|$)", page_text)
        if model_match:
            result["raw"]["model_number"] = model_match.group(1).strip()

        # 販売終了
        if "販売終了" in page_text or "生産完了" in page_text:
            result["raw"]["is_discontinued"] = True
            result["is_in_stock"] = False

        return result

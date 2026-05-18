"""イオシス Collector。

買取価格・中古販売価格を取得する。

Chrome調査結果 (2026-05-17):
  URL: https://iosys.co.jp/items?keyword=XXX
  SSR: はい（requestsで取得可能）
  商品カード: div.item
  価格: span.price / div.price_area
  在庫数: "在庫数：N" テキスト
  ランク: "中古Bランク" / "中古Cランク" / "未使用品" テキスト
  買取URL: https://iosys.co.jp/buy/search?keyword=XXX
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


class IosysCollector(BaseCollector):
    """イオシス Collector。"""

    BUYBACK_URL = "https://iosys.co.jp/buy/search?keyword={keyword}"

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
            result = self._parse_sales(html, product, url)
        except Exception as e:
            self.logger.error("Parse error: %s", e)
            self.log_collection(product.id, started_at, "error", error_message=str(e))
            return None

        # 買取価格も取得試行
        if product.keywords:
            buyback_url = self.BUYBACK_URL.format(keyword=product.keywords[0].replace(" ", "+"))
            bp = self._fetch_buyback(buyback_url, product)
            if bp:
                result["buyback_price"] = bp

        now = datetime.now()
        obs_type = "buyback" if result.get("buyback_price") else "price"
        obs = ObservationModel(
            id=str(ulid.new()),
            product_id=product.id,
            source_id=self.source.id,
            observation_type=obs_type,
            observed_at=now,
            is_in_stock=result.get("is_in_stock"),
            price=result.get("used_price"),
            buyback_price=result.get("buyback_price"),
            raw_text=json.dumps(result.get("raw", {}), ensure_ascii=False),
            raw_html_hash=self.hash_html(html),
            confidence=0.85,
        )
        self.repository.insert_observation(obs)

        if result.get("buyback_price"):
            self.repository.insert_price_history(PriceHistoryModel(
                id=str(ulid.new()), product_id=product.id, source_id=self.source.id,
                price_type="buyback", price=result["buyback_price"], recorded_at=now,
            ))
        if result.get("used_price"):
            self.repository.insert_price_history(PriceHistoryModel(
                id=str(ulid.new()), product_id=product.id, source_id=self.source.id,
                price_type="used", price=result["used_price"], recorded_at=now,
            ))

        self.log_collection(product.id, started_at, "success")
        self.logger.info(
            "iosys | %s | buyback=¥%s | used=¥%s | stock=%s",
            product.name,
            f"{result.get('buyback_price', 0):,}" if result.get("buyback_price") else "N/A",
            f"{result.get('used_price', 0):,}" if result.get("used_price") else "N/A",
            result.get("is_in_stock"),
        )
        return obs

    def _parse_sales(self, html: str, product: ProductModel, url: str) -> dict:
        result = {"used_price": None, "is_in_stock": None, "buyback_price": None, "raw": {"url": url}}
        soup = self.parse_html(html)

        # 商品カード（div.item内）からキーワードマッチ
        items = soup.select("div.item, [class*='item-card'], [class*='product']")
        matched_prices = []

        for item in items:
            text = item.get_text()
            if not any(kw.lower() in text.lower() for kw in product.keywords):
                continue
            # アクセサリー除外
            if re.search(r"ケース|フィルム|ストラップ|バッテリー|充電", text):
                continue

            # 価格抽出
            price_el = item.select_one("span.price, div.price, [class*='price']")
            if price_el:
                price = Normalizer.parse_price(price_el.get_text())
                if price and price > 5000:
                    matched_prices.append(price)

            # 在庫数
            stock_match = re.search(r"在庫数[：:]\s*(\d+)", text)
            if stock_match:
                count = int(stock_match.group(1))
                result["is_in_stock"] = count > 0
                result["raw"]["stock_count"] = count

        if matched_prices:
            result["used_price"] = min(matched_prices)
            result["is_in_stock"] = True
            result["raw"]["matched_prices"] = sorted(matched_prices)

        # フォールバック: ページ全体から価格スキャン
        if not matched_prices:
            all_prices = Normalizer.parse_price_multiple(soup.get_text())
            reasonable = [p for p in all_prices if 10000 < p < 500000]
            if reasonable:
                result["used_price"] = min(reasonable)
                result["raw"]["fallback_prices"] = reasonable[:5]

        return result

    def _fetch_buyback(self, url: str, product: ProductModel) -> Optional[int]:
        try:
            html = self.fetch_page(url)
            if not html:
                return None
            soup = self.parse_html(html)
            # 買取価格テキストを探す
            for el in soup.select("[class*='price'], [class*='kaitori']"):
                text = el.get_text()
                if any(kw.lower() in text.lower() for kw in product.keywords):
                    price = Normalizer.parse_price(text)
                    if price and 1000 < price < 500000:
                        return price
            # regexフォールバック
            m = re.search(r"買取[^¥￥\d]*[¥￥]?\s*([\d,]+)", soup.get_text())
            if m:
                price = Normalizer.parse_price(m.group(1))
                if price and 1000 < price < 500000:
                    return price
        except Exception as e:
            self.logger.debug("Buyback fetch failed: %s", e)
        return None

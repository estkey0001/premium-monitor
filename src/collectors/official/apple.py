"""Apple Japan Collector。

apple.com/jp の製品ページから以下を取得する:
- 公式価格（JSON-LD / meta / HTMLから）
- 購入可否
- カラー/容量別価格

Apple公式サイトの特徴:
- JSON-LDにProduct型あり（価格含む）
- metaタグに og:title, product:price:amount あり
- SSR: requestsで取得可能
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


class AppleOfficialCollector(BaseCollector):
    """Apple Japan公式 Collector。"""

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
            result = self._parse(html, product, url)
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
            is_in_stock=result["is_in_stock"],
            price=result["price"],
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

        if result["price"]:
            stock_status = "在庫あり" if result["is_in_stock"] else "在庫なし"
            self.repository.mark_official_price_candidate(
                product.id, result["price"], self.source.id,
                stock_status=stock_status,
            )

        self.log_collection(product.id, started_at, "success")
        self.logger.info(
            "apple_official | %s | price=%s | stock=%s",
            product.name,
            f"¥{result['price']:,}" if result['price'] else "N/A",
            result["is_in_stock"],
        )
        return obs

    def _parse(self, html: str, product: ProductModel, url: str) -> dict:
        result = {
            "price": None,
            "is_in_stock": None,
            "raw": {"url": url},
        }

        soup = self.parse_html(html)

        # --- 戦略1: JSON-LD ---
        json_ld_list = Normalizer.extract_json_ld(html)
        for item in json_ld_list:
            if item.get("@type") == "Product":
                result["raw"]["json_ld_product"] = True
                offers = item.get("offers", {})
                if isinstance(offers, dict):
                    price_str = offers.get("price") or offers.get("lowPrice")
                    if price_str:
                        result["price"] = Normalizer.parse_price(str(price_str))
                        result["raw"]["price_method"] = "json_ld"
                    avail = offers.get("availability", "")
                    if "InStock" in avail:
                        result["is_in_stock"] = True
                    elif "OutOfStock" in avail:
                        result["is_in_stock"] = False
                elif isinstance(offers, list):
                    # 複数バリエーション（容量別など）
                    prices = []
                    for o in offers:
                        p = Normalizer.parse_price(str(o.get("price", "")))
                        if p:
                            prices.append(p)
                    if prices:
                        result["price"] = min(prices)
                        result["raw"]["price_method"] = "json_ld_multi"
                        result["raw"]["all_prices"] = sorted(prices)
                break

        # --- 戦略2: metaタグ ---
        if result["price"] is None:
            meta_price = Normalizer.extract_meta_content(html, "product:price:amount")
            if meta_price:
                result["price"] = Normalizer.parse_price(meta_price)
                result["raw"]["price_method"] = "meta"

        # --- 戦略3: ページ内の「¥XXX,XXX から」パターン ---
        if result["price"] is None:
            m = re.search(r"[¥￥]([\d,]+)\s*から", html)
            if m:
                result["price"] = Normalizer.parse_price(m.group(1))
                result["raw"]["price_method"] = "from_pattern"

        # --- 戦略4: ページ内の全価格から対象商品の容量を特定 ---
        if result["price"] is None:
            all_prices = Normalizer.parse_price_multiple(soup.get_text())
            # iPhone系は10万以上の価格帯
            apple_range = [p for p in all_prices if 50000 < p < 1000000]
            if apple_range:
                result["price"] = min(apple_range)
                result["raw"]["price_method"] = "page_scan"
                result["raw"]["all_prices_found"] = sorted(set(apple_range))[:10]

        # --- 在庫判定 ---
        if result["is_in_stock"] is None:
            page_text = soup.get_text()
            if "購入" in page_text or "カートに追加" in page_text or "注文" in page_text:
                result["is_in_stock"] = True
            elif "在庫なし" in page_text or "現在ご利用いただけません" in page_text:
                result["is_in_stock"] = False

        return result

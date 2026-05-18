"""価格.com Collector。

商品個別ページから以下を取得する:
- 最安価格
- 商品名
- 販売ショップ数

実ページ調査結果（2026-05-17）:
- JSON-LDにProduct型なし（WebSiteとBreadcrumbListのみ）
- metaタグにprice情報なし
- 最安価格: a.p-prdInfoLowprice_entity (テキスト "208,940円")
- 店舗数: "全Nショップ" テキストから抽出
- 商品名: h1タグ内テキスト
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


class KakakuComCollector(BaseCollector):
    """価格.com Collector。"""

    def collect(
        self, product: ProductModel, config: ProductSourceConfigModel
    ) -> Optional[ObservationModel]:
        url = config.target_url
        if not url:
            self.logger.error("No target_url configured for %s", product.id)
            return None

        started_at = datetime.now()

        html = self.fetch_page(url)
        if html is None:
            self.log_collection(product.id, started_at, "error", error_message="fetch failed")
            return None

        try:
            result = self._parse_page(html, url)
        except Exception as e:
            self.logger.error("Parse error for %s: %s", url, e)
            self.log_collection(product.id, started_at, "error", error_message=str(e))
            return None

        if result["price"] is None:
            self.logger.warning("No price found for %s at %s", product.name, url)
            self.log_collection(product.id, started_at, "error", error_message="no price found")
            return None

        now = datetime.now()
        obs = ObservationModel(
            id=str(ulid.new()),
            product_id=product.id,
            source_id=self.source.id,
            observation_type="price",
            observed_at=now,
            is_in_stock=result["is_in_stock"],
            price=result["price"],
            raw_text=json.dumps(result["raw"], ensure_ascii=False),
            raw_html_hash=self.hash_html(html),
            confidence=self._calc_confidence(result),
        )
        self.repository.insert_observation(obs)

        ph = PriceHistoryModel(
            id=str(ulid.new()),
            product_id=product.id,
            source_id=self.source.id,
            price_type="retail",
            price=result["price"],
            recorded_at=now,
        )
        self.repository.insert_price_history(ph)

        self.log_collection(product.id, started_at, "success")
        self.logger.info(
            "kakaku.com | %s | price=¥%s | shops=%s | stock=%s",
            product.name,
            f"{result['price']:,}",
            result.get("shop_count", "?"),
            result["is_in_stock"],
        )
        return obs

    def _parse_page(self, html: str, url: str) -> dict:
        result = {
            "price": None,
            "product_name": None,
            "is_in_stock": None,
            "shop_count": None,
            "url": url,
            "raw": {},
        }

        soup = self.parse_html(html)

        # --- 商品名: <h1> からタイトルページの名前を取得 ---
        h1 = soup.select_one("h1")
        if h1:
            result["product_name"] = Normalizer.clean_text(h1.get_text())
            result["raw"]["h1_text"] = result["product_name"]

        # og:titleフォールバック
        if not result["product_name"]:
            og = Normalizer.extract_meta_content(html, "og:title")
            if og:
                result["product_name"] = Normalizer.clean_text(og)

        # --- 最安価格 ---
        # 戦略1: a.p-prdInfoLowprice_entity (実ページで確認済みセレクタ)
        price_selectors = [
            "a.p-prdInfoLowprice_entity",
            ".p-prdInfoLowprice_entity",
            ".p-priceList_price",
            "#priceBox .priceTxt",
            "span[itemprop='lowPrice']",
        ]
        for sel in price_selectors:
            el = soup.select_one(sel)
            if el:
                parsed = Normalizer.parse_price(el.get_text())
                if parsed:
                    result["price"] = parsed
                    result["raw"]["price_selector"] = sel
                    result["raw"]["price_text"] = el.get_text().strip()
                    break

        # 戦略2: テキスト "最安価格" の直後の金額をregexで探す
        if result["price"] is None:
            m = re.search(r"最安価格\s*[¥￥]?([\d,]+)", html)
            if m:
                result["price"] = Normalizer.parse_price(m.group(1))
                result["raw"]["price_method"] = "regex_lowest"

        # 戦略3: JSON-LDのProduct型（存在すれば）
        if result["price"] is None:
            json_ld_list = Normalizer.extract_json_ld(html)
            for item in json_ld_list:
                if item.get("@type") == "Product":
                    offers = item.get("offers", {})
                    if isinstance(offers, dict):
                        price_str = offers.get("lowPrice") or offers.get("price")
                        if price_str:
                            result["price"] = Normalizer.parse_price(str(price_str))
                            result["raw"]["price_method"] = "json_ld"
                    break

        # --- 店舗数 ---
        shop_match = re.search(r"全(\d+)ショップ", html)
        if shop_match:
            result["shop_count"] = int(shop_match.group(1))
            result["raw"]["shop_count"] = result["shop_count"]
            result["is_in_stock"] = result["shop_count"] > 0

        # 在庫フォールバック
        if result["is_in_stock"] is None and result["price"] is not None:
            result["is_in_stock"] = True

        return result

    def _calc_confidence(self, result: dict) -> float:
        base = 0.90
        if result.get("shop_count") and result["shop_count"] >= 3:
            base = 0.95
        if result.get("raw", {}).get("price_method") == "regex_lowest":
            base -= 0.05
        return round(base, 2)

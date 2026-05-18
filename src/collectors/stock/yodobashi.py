"""ヨドバシカメラ Collector。

商品個別ページから以下を取得する:
- 販売価格（税込）
- 在庫状態
- ポイント還元情報

実ページ調査結果（2026-05-17）:
- JSON-LDなし
- 価格: span#js_scl_unitPrice.productPrice (テキスト "￥139,800")
- 在庫: div.salesInfo (テキスト "販売休止中です" / "在庫あり" 等)
- ポイント: span.point.js_ppPoint (テキスト "13,980 ゴールドポイント（10％還元）")
- 商品名: h1#products_maintitle.pName
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


class YodobashiCollector(BaseCollector):
    """ヨドバシカメラ Collector。"""

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
            self.log_collection(
                product.id, started_at, "error",
                error_message="no price found"
            )
            return None

        now = datetime.now()
        raw_data = result["raw"]
        if result.get("points_info"):
            raw_data["points_info"] = result["points_info"]
        if result.get("stock_detail"):
            raw_data["stock_detail"] = result["stock_detail"]

        obs = ObservationModel(
            id=str(ulid.new()),
            product_id=product.id,
            source_id=self.source.id,
            observation_type="stock",
            observed_at=now,
            is_in_stock=result["is_in_stock"],
            price=result["price"],
            raw_text=json.dumps(raw_data, ensure_ascii=False),
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
            "yodobashi | %s | price=¥%s | stock=%s | points=%s",
            product.name,
            f"{result['price']:,}",
            result.get("stock_detail", result["is_in_stock"]),
            result.get("points_info", "N/A"),
        )
        return obs

    def _parse_page(self, html: str, url: str) -> dict:
        result = {
            "price": None,
            "product_name": None,
            "is_in_stock": None,
            "stock_detail": None,
            "points_info": None,
            "url": url,
            "raw": {},
        }

        soup = self.parse_html(html)

        # --- 商品名 ---
        # 実ページ: h1#products_maintitle.pName
        title_selectors = [
            "h1#products_maintitle",
            "h1.pName",
            "#products_maintitle",
        ]
        for sel in title_selectors:
            el = soup.select_one(sel)
            if el:
                result["product_name"] = Normalizer.clean_text(el.get_text())
                result["raw"]["title_selector"] = sel
                break

        # og:titleフォールバック
        if not result["product_name"]:
            og = Normalizer.extract_meta_content(html, "og:title")
            if og:
                result["product_name"] = Normalizer.clean_text(og)

        # --- 価格 ---
        # 実ページ: span#js_scl_unitPrice.productPrice (テキスト "￥139,800")
        price_selectors = [
            "#js_scl_unitPrice",
            "span.productPrice",
            ".productPrice",
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

        # regexフォールバック: "価格：￥XXX,XXX" パターン
        if result["price"] is None:
            m = re.search(r"価格[：:]\s*[¥￥]([\d,]+)", html)
            if m:
                result["price"] = Normalizer.parse_price(m.group(1))
                result["raw"]["price_method"] = "regex"

        # 「販売終了時の価格」フォールバック
        if result["price"] is None:
            m = re.search(r"販売終了時の価格[：:]\s*[¥￥]([\d,]+)", html)
            if m:
                result["price"] = Normalizer.parse_price(m.group(1))
                result["raw"]["price_method"] = "ended_price"

        # --- 在庫状態 ---
        # 実ページ: div.salesInfo (テキスト "販売休止中です")
        stock_selectors = [
            "div.salesInfo",
            ".salesInfo",
            "#js_scl_salesStatus",
            ".pSalesInfo",
        ]
        for sel in stock_selectors:
            els = soup.select(sel)
            for el in els:
                stock_text = Normalizer.clean_text(el.get_text())
                if stock_text and len(stock_text) < 50:
                    result["stock_detail"] = stock_text
                    result["is_in_stock"] = Normalizer.normalize_stock(stock_text)
                    result["raw"]["stock_selector"] = sel
                    result["raw"]["stock_text"] = stock_text
                    break
            if result["stock_detail"]:
                break

        # 「販売休止中」はnormalize_stockで拾えない場合の追加対応
        if result["is_in_stock"] is None and result.get("stock_detail"):
            st = result["stock_detail"]
            if "販売休止" in st or "販売終了" in st:
                result["is_in_stock"] = False
            elif "在庫" in st and "なし" not in st:
                result["is_in_stock"] = True

        # --- ポイント還元 ---
        # 実ページ: span.point.js_ppPoint (テキスト "13,980 ゴールドポイント（10％還元）")
        point_selectors = [
            "span.js_ppPoint",
            "span.point",
            ".unitPoint",
        ]
        for sel in point_selectors:
            els = soup.select(sel)
            for el in els:
                text = Normalizer.clean_text(el.get_text())
                if "ポイント" in text and len(text) < 80:
                    result["points_info"] = text
                    parsed_points = Normalizer.parse_points(text)
                    if parsed_points:
                        result["raw"]["points_parsed"] = parsed_points
                    break
            if result["points_info"]:
                break

        # regexフォールバック
        if result["points_info"] is None:
            m = re.search(r"([\d,]+)\s*ゴールドポイント[^)]*?(\d+％?%?還元)?", html)
            if m:
                result["points_info"] = Normalizer.clean_text(m.group(0))

        return result

    def _calc_confidence(self, result: dict) -> float:
        base = 0.95
        if result.get("raw", {}).get("price_method") == "regex":
            base -= 0.05
        if result.get("raw", {}).get("price_method") == "ended_price":
            base -= 0.10
        if result.get("is_in_stock") is None:
            base -= 0.05
        return round(max(base, 0.5), 2)

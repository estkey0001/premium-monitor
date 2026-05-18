"""ビックカメラ Collector。

販売価格・在庫状態・ポイント還元を取得する。

Chrome調査結果 (2026-05-17):
  WAF: 自動化アクセスを検知して遮断する場合がある
  SSR: はい（WAFを通過すれば requestsで取得可能）
  商品ページURL: https://www.biccamera.com/bc/item/XXXXXXXXXX/
  検索URL: https://www.biccamera.com/bc/category/?q=KEYWORD
  価格: .bcs_price / span.val (税込表記)
  在庫: .bcs_stock / "在庫あり" / "お取り寄せ" / "在庫なし"
  ポイント: .bcs_point
  robots.txt: 要確認
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


class BiccameraCollector(BaseCollector):
    """ビックカメラ Collector。"""

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
            self.log_collection(product.id, started_at, "error", error_message="fetch failed (WAF?)")
            return None

        # WAF遮断チェック
        if "アクセスを遮断" in html or "Bad Request" in html:
            self.logger.warning("biccamera WAF blocked: %s", url)
            self.log_collection(product.id, started_at, "error", error_message="WAF blocked")
            return None

        try:
            result = self._parse(html, product, url)
        except Exception as e:
            self.logger.error("Parse error: %s", e)
            self.log_collection(product.id, started_at, "error", error_message=str(e))
            return None

        if result["price"] is None:
            self.log_collection(product.id, started_at, "error", error_message="no price found")
            return None

        now = datetime.now()
        raw = result.get("raw", {})
        if result.get("points_info"):
            raw["points_info"] = result["points_info"]

        obs = ObservationModel(
            id=str(ulid.new()),
            product_id=product.id,
            source_id=self.source.id,
            observation_type="stock",
            observed_at=now,
            is_in_stock=result["is_in_stock"],
            price=result["price"],
            raw_text=json.dumps(raw, ensure_ascii=False),
            raw_html_hash=self.hash_html(html),
            confidence=0.95,
        )
        self.repository.insert_observation(obs)

        self.repository.insert_price_history(PriceHistoryModel(
            id=str(ulid.new()), product_id=product.id, source_id=self.source.id,
            price_type="retail", price=result["price"], recorded_at=now,
        ))

        self.log_collection(product.id, started_at, "success")
        self.logger.info(
            "biccamera | %s | price=¥%s | stock=%s | points=%s",
            product.name, f"{result['price']:,}", result["is_in_stock"],
            result.get("points_info", "N/A"),
        )
        return obs

    def _parse(self, html: str, product: ProductModel, url: str) -> dict:
        result = {"price": None, "is_in_stock": None, "points_info": None, "raw": {"url": url}}
        soup = self.parse_html(html)

        # 商品名確認（検索結果の場合）
        # 個別商品ページの場合は直接価格取得

        # 価格セレクタ（複数パターン）
        price_selectors = [
            ".bcs_price .val", ".bcs_price", ".itemPrice .val",
            "span.bcs_price", "[class*='price'] .val",
            "span[itemprop='price']",
        ]
        for sel in price_selectors:
            el = soup.select_one(sel)
            if el:
                price = Normalizer.parse_price(el.get_text())
                if price:
                    result["price"] = price
                    result["raw"]["price_selector"] = sel
                    break

        # regex フォールバック
        if result["price"] is None:
            m = re.search(r"[¥￥]([\d,]+)\s*\(税込\)", html)
            if m:
                result["price"] = Normalizer.parse_price(m.group(1))
                result["raw"]["price_method"] = "regex"

        # 検索結果ページの場合：キーワードマッチする商品カード内の価格
        if result["price"] is None:
            for a in soup.find_all("a"):
                text = a.get_text()
                if any(kw.lower() in text.lower() for kw in product.keywords):
                    if re.search(r"ケース|フィルム|ストラップ|バッテリー", text):
                        continue
                    parent = a.parent
                    for _ in range(4):
                        if parent and parent.parent:
                            parent = parent.parent
                    if parent:
                        prices = Normalizer.parse_price_multiple(parent.get_text())
                        prices = [p for p in prices if p > 10000]
                        if prices:
                            result["price"] = prices[0]
                            result["raw"]["price_method"] = "card_scan"
                            break

        # 在庫状態
        stock_selectors = [".bcs_stock", ".itemStock", "[class*='stock']"]
        for sel in stock_selectors:
            el = soup.select_one(sel)
            if el:
                text = Normalizer.clean_text(el.get_text())
                result["is_in_stock"] = Normalizer.normalize_stock(text)
                result["raw"]["stock_text"] = text
                break

        if result["is_in_stock"] is None:
            page_text = soup.get_text()
            if "お取り寄せ" in page_text:
                result["is_in_stock"] = False
                result["raw"]["stock_text"] = "お取り寄せ"
            elif "在庫あり" in page_text or "カートに入れる" in page_text:
                result["is_in_stock"] = True

        # ポイント
        point_selectors = [".bcs_point", ".itemPoint", "[class*='point']"]
        for sel in point_selectors:
            el = soup.select_one(sel)
            if el:
                text = Normalizer.clean_text(el.get_text())
                if "ポイント" in text:
                    result["points_info"] = text
                    break

        return result

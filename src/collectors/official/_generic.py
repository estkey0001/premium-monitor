"""汎用 公式ストア Collector（SSR: requests で取得可能なサイト向け）。

サイト固有のセレクタに依存せず、以下の順で公式価格を抽出する堅牢な戦略:
  1. JSON-LD（schema.org Product/offers）
  2. meta タグ（product:price:amount / og:price:amount）
  3. ページ内の「¥XXX,XXX」価格パターン（対象商品の価格帯でフィルタ）

canon / nikon / sony など「公式定価が比較的安定・SSR取得可能」なストアを
最小コストで自動化するための共通実装。取得不可時は graceful に None を返す
（CI のクラウドIPブロック時も例外で止めない）。ToS 遵守: robots.txt 準拠・低頻度。
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


class GenericOfficialCollector(BaseCollector):
    """SSR 公式ストア向けの汎用 Collector。

    サブクラスは PRICE_MIN / PRICE_MAX（ページ内スキャン時の価格帯フィルタ）と
    LABEL（ログ表示名）を上書きできる。
    """

    PRICE_MIN = 10000
    PRICE_MAX = 2000000
    LABEL = "official"

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
            # クラウドIPブロック/到達不可は error ログのみ（例外で止めない）
            self.log_collection(product.id, started_at, "error", error_message="fetch failed")
            return None

        try:
            result = self._parse(html, product, url)
        except Exception as e:
            self.logger.error("Parse error (%s): %s", self.LABEL, e)
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
            confidence=0.99,  # 公式サイトは最高信頼度
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
            stock_status = "在庫あり" if result["is_in_stock"] else "在庫なし"
            self.repository.mark_official_price_candidate(
                product.id, result["price"], self.source.id, stock_status=stock_status,
            )

        self.log_collection(product.id, started_at, "success")
        self.logger.info(
            "%s | %s | price=%s | stock=%s",
            self.LABEL, product.name,
            f"¥{result['price']:,}" if result["price"] else "N/A",
            result["is_in_stock"],
        )
        return obs

    def _parse(self, html: str, product: ProductModel, url: str) -> dict:
        result = {"price": None, "is_in_stock": None, "raw": {"url": url, "label": self.LABEL}}
        soup = self.parse_html(html)

        # --- 戦略1: JSON-LD ---
        try:
            for item in Normalizer.extract_json_ld(html):
                if item.get("@type") != "Product":
                    continue
                offers = item.get("offers", {})
                if isinstance(offers, dict):
                    ps = offers.get("price") or offers.get("lowPrice")
                    if ps:
                        result["price"] = Normalizer.parse_price(str(ps))
                        result["raw"]["price_method"] = "json_ld"
                    avail = offers.get("availability", "")
                    if "InStock" in avail:
                        result["is_in_stock"] = True
                    elif "OutOfStock" in avail or "SoldOut" in avail:
                        result["is_in_stock"] = False
                elif isinstance(offers, list):
                    prices = [Normalizer.parse_price(str(o.get("price", ""))) for o in offers]
                    prices = [p for p in prices if p]
                    if prices:
                        result["price"] = min(prices)
                        result["raw"]["price_method"] = "json_ld_multi"
                if result["price"]:
                    break
        except Exception as e:
            result["raw"]["json_ld_error"] = str(e)

        # --- 戦略2: meta タグ ---
        if result["price"] is None:
            for key in ("product:price:amount", "og:price:amount"):
                meta_price = Normalizer.extract_meta_content(html, key)
                if meta_price:
                    result["price"] = Normalizer.parse_price(meta_price)
                    result["raw"]["price_method"] = f"meta:{key}"
                    break

        # --- 戦略3: ページ内価格スキャン（対象価格帯でフィルタ）---
        if result["price"] is None:
            all_prices = Normalizer.parse_price_multiple(soup.get_text())
            ranged = [p for p in all_prices if self.PRICE_MIN <= p <= self.PRICE_MAX]
            if ranged:
                result["price"] = min(ranged)
                result["raw"]["price_method"] = "page_scan"
                result["raw"]["all_prices_found"] = sorted(set(ranged))[:10]

        # --- 在庫判定 ---
        if result["is_in_stock"] is None:
            text = soup.get_text()
            if any(k in text for k in ("カートに入れる", "カートに追加", "購入手続き", "ご注文", "在庫あり")):
                result["is_in_stock"] = True
            elif any(k in text for k in ("SOLD OUT", "在庫なし", "販売を終了", "入荷待ち", "予約受付終了")):
                result["is_in_stock"] = False

        return result

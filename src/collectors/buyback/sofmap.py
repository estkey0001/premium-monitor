"""ソフマップ Collector。

買取価格・中古販売価格・在庫を取得する。

Chrome調査結果 (2026-05-17):
  検索URL: https://www.sofmap.com/search_result.aspx?keyword=XXX
  SSR: はい（requestsで取得可能）
  カテゴリ絞り込み: &gid=001080 (カメラ)
  タブ: 全ての商品 / 新品商品 / 中古商品
  価格: ¥X,XXX(税込) テキスト
  ポイント: "XXXポイントサービス" テキスト
  在庫: "お取り寄せ" テキスト
  発売日: "発売日：YYYY/MM/DD" テキスト
  買取URL: https://www.sofmap.com/kaitori/search_result.aspx?keyword=XXX
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


class SofmapCollector(BaseCollector):
    """ソフマップ Collector。"""

    BUYBACK_URL = "https://www.sofmap.com/kaitori/search_result.aspx?keyword={keyword}"

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

        # 買取価格取得
        if product.keywords:
            bp = self._fetch_buyback(product)
            if bp:
                result["buyback_price"] = bp

        now = datetime.now()
        primary_price = result.get("used_price") or result.get("new_price")
        obs_type = "buyback" if result.get("buyback_price") else "price"

        obs = ObservationModel(
            id=str(ulid.new()),
            product_id=product.id,
            source_id=self.source.id,
            observation_type=obs_type,
            observed_at=now,
            is_in_stock=result.get("is_in_stock"),
            price=primary_price,
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
        if result.get("new_price"):
            self.repository.insert_price_history(PriceHistoryModel(
                id=str(ulid.new()), product_id=product.id, source_id=self.source.id,
                price_type="retail", price=result["new_price"], recorded_at=now,
            ))
        if result.get("used_price"):
            self.repository.insert_price_history(PriceHistoryModel(
                id=str(ulid.new()), product_id=product.id, source_id=self.source.id,
                price_type="used", price=result["used_price"], recorded_at=now,
            ))

        self.log_collection(product.id, started_at, "success")
        self.logger.info(
            "sofmap | %s | new=¥%s | used=¥%s | buyback=¥%s | stock=%s",
            product.name,
            f"{result.get('new_price', 0):,}" if result.get("new_price") else "N/A",
            f"{result.get('used_price', 0):,}" if result.get("used_price") else "N/A",
            f"{result.get('buyback_price', 0):,}" if result.get("buyback_price") else "N/A",
            result.get("is_in_stock"),
        )
        return obs

    def _parse(self, html: str, product: ProductModel, url: str) -> dict:
        result = {"new_price": None, "used_price": None, "buyback_price": None,
                  "is_in_stock": None, "raw": {"url": url}}
        soup = self.parse_html(html)

        # 商品カードからキーワードマッチ
        # ソフマップの検索結果はリンク+価格+ポイント+在庫の構造
        new_prices = []
        used_prices = []

        for a in soup.find_all("a"):
            text = a.get_text()
            if not any(kw.lower() in text.lower() for kw in product.keywords):
                continue
            if re.search(r"ケース|フィルム|ストラップ|バッテリー|フード|アダプター", text):
                continue

            # 親要素から価格と在庫を探す
            parent = a
            for _ in range(5):
                if parent.parent:
                    parent = parent.parent
            card_text = parent.get_text() if parent else ""
            prices = Normalizer.parse_price_multiple(card_text)
            prices = [p for p in prices if 10000 < p < 1000000]

            if "中古" in card_text:
                used_prices.extend(prices)
            else:
                new_prices.extend(prices)

            # 在庫
            if "お取り寄せ" in card_text:
                result["is_in_stock"] = False
            elif "在庫あり" in card_text or "カートに入れる" in card_text:
                result["is_in_stock"] = True
            elif prices:
                result["is_in_stock"] = True

        if new_prices:
            result["new_price"] = min(new_prices)
            result["raw"]["new_prices"] = sorted(set(new_prices))
        if used_prices:
            result["used_price"] = min(used_prices)
            result["raw"]["used_prices"] = sorted(set(used_prices))

        # フォールバック
        if not new_prices and not used_prices:
            all_prices = Normalizer.parse_price_multiple(soup.get_text())
            reasonable = [p for p in all_prices if 50000 < p < 500000]
            if reasonable:
                result["new_price"] = min(reasonable)
                result["raw"]["fallback_prices"] = reasonable[:5]

        return result

    def _fetch_buyback(self, product: ProductModel) -> Optional[int]:
        keyword = product.keywords[0] if product.keywords else product.name
        url = self.BUYBACK_URL.format(keyword=keyword.replace(" ", "+"))
        try:
            html = self.fetch_page(url)
            if not html:
                return None
            soup = self.parse_html(html)

            # 買取価格を探す
            for a in soup.find_all("a"):
                text = a.get_text()
                if any(kw.lower() in text.lower() for kw in product.keywords):
                    parent = a.parent
                    for _ in range(3):
                        if parent and parent.parent:
                            parent = parent.parent
                    if parent:
                        card_text = parent.get_text()
                        m = re.search(r"[¥￥]([\d,]+)", card_text)
                        if m:
                            price = Normalizer.parse_price(m.group(1))
                            if price and 1000 < price < 500000:
                                return price

            # regexフォールバック
            page_text = soup.get_text()
            m = re.search(r"買取[上最高]*価格[^¥￥\d]*[¥￥]?\s*([\d,]+)", page_text)
            if m:
                price = Normalizer.parse_price(m.group(1))
                if price and 1000 < price < 500000:
                    return price
        except Exception as e:
            self.logger.debug("Sofmap buyback fetch failed: %s", e)
        return None

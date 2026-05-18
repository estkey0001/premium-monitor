"""カメラのキタムラ Collector。

カメラ中古市場の信頼性高い国内相場を取得する。
SSR + JS描画併用。requestsで基本取得、不足時Playwright。

検索URL: https://shop.kitamura.jp/ec/list?keyword=XXX
中古URL: https://shop.kitamura.jp/ec/used/list?keyword=XXX
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


class KitamuraCollector(BaseCollector):
    """カメラのキタムラ Collector。"""

    USED_URL = "https://shop.kitamura.jp/ec/used/list?keyword={keyword}"

    def collect(
        self, product: ProductModel, config: ProductSourceConfigModel
    ) -> Optional[ObservationModel]:
        url = config.target_url
        if not url:
            keyword = product.keywords[0] if product.keywords else product.name
            url = f"https://shop.kitamura.jp/ec/list?keyword={keyword.replace(' ', '+')}"

        started_at = datetime.now()

        # requests試行、失敗時Playwright
        html = self.fetch_page(url)
        if html and len(html) < 2000:
            html = self._try_playwright(url)

        if html is None:
            self.log_collection(product.id, started_at, "error", error_message="fetch failed")
            return None

        try:
            result = self._parse(html, product, url)
        except Exception as e:
            self.logger.error("Parse error: %s", e)
            self.log_collection(product.id, started_at, "error", error_message=str(e))
            return None

        # 中古ページも取得試行
        used_price = self._fetch_used(product)
        if used_price:
            result["used_price"] = used_price

        if not result.get("new_price") and not result.get("used_price"):
            self.log_collection(product.id, started_at, "error", error_message="no price data")
            return None

        now = datetime.now()
        primary = result.get("used_price") or result.get("new_price")
        obs_type = "price" if result.get("new_price") else "price"

        obs = ObservationModel(
            id=str(ulid.new()),
            product_id=product.id,
            source_id=self.source.id,
            observation_type=obs_type,
            observed_at=now,
            is_in_stock=result.get("is_in_stock"),
            price=primary,
            raw_text=json.dumps(result.get("raw", {}), ensure_ascii=False),
            confidence=0.85,
        )
        self.repository.insert_observation(obs)

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
            "kitamura | %s | new=¥%s | used=¥%s | stock=%s",
            product.name,
            f"{result.get('new_price', 0):,}" if result.get("new_price") else "N/A",
            f"{result.get('used_price', 0):,}" if result.get("used_price") else "N/A",
            result.get("is_in_stock"),
        )
        return obs

    def _parse(self, html: str, product: ProductModel, url: str) -> dict:
        result = {"new_price": None, "used_price": None, "is_in_stock": None, "raw": {"url": url}}
        soup = self.parse_html(html)

        # キーワードマッチする商品の価格を探す
        for a in soup.find_all("a"):
            text = a.get_text()
            if not any(kw.lower() in text.lower() for kw in product.keywords):
                continue
            if re.search(r"ケース|フィルム|ストラップ|バッテリー|フード|アダプター", text):
                continue

            parent = a
            for _ in range(5):
                if parent.parent:
                    parent = parent.parent
            card = parent.get_text() if parent else ""
            prices = Normalizer.parse_price_multiple(card)
            prices = [p for p in prices if 10000 < p < 1000000]

            if "中古" in card:
                if prices:
                    result["used_price"] = min(prices)
            else:
                if prices:
                    result["new_price"] = min(prices)

            if "在庫あり" in card or "カートに入れる" in card:
                result["is_in_stock"] = True
            elif "在庫なし" in card or "品切れ" in card or "お取り寄せ" in card:
                result["is_in_stock"] = False

            if result["new_price"] or result["used_price"]:
                break

        return result

    def _fetch_used(self, product: ProductModel) -> Optional[int]:
        keyword = product.keywords[0] if product.keywords else product.name
        url = self.USED_URL.format(keyword=keyword.replace(" ", "+"))
        try:
            html = self.fetch_page(url)
            if not html or len(html) < 1000:
                return None
            soup = self.parse_html(html)
            prices = Normalizer.parse_price_multiple(soup.get_text())
            camera_prices = [p for p in prices if 10000 < p < 500000]
            return min(camera_prices) if camera_prices else None
        except Exception:
            return None

    def _try_playwright(self, url: str) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page()
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(3000)
                html = page.content()
                browser.close()
                return html
        except Exception:
            return None

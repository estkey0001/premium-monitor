"""じゃんぱら Collector。

買取価格・中古販売価格を取得する。

Chrome調査結果 (2026-05-17):
  検索URLが直接アクセスでBad Request（CSRF/Cookie依存）
  → Playwrightでトップページ経由の検索が必要
  SSR: 部分的（検索はCookie必須）
  買取検索URL: https://www.janpara.co.jp/buy/search/result/
  販売検索URL: https://www.janpara.co.jp/sale/search/result/
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


class JanparaCollector(BaseCollector):
    """じゃんぱら Collector（Playwright使用）。"""

    def collect(
        self, product: ProductModel, config: ProductSourceConfigModel
    ) -> Optional[ObservationModel]:
        url = config.target_url
        if not url:
            self.logger.error("No target_url for %s", product.id)
            return None

        started_at = datetime.now()
        html = self._fetch_with_playwright(url, product.keywords[0] if product.keywords else product.name)
        if html is None:
            self.log_collection(product.id, started_at, "error", error_message="playwright fetch failed")
            return None

        try:
            result = self._parse(html, product, url)
        except Exception as e:
            self.logger.error("Parse error: %s", e)
            self.log_collection(product.id, started_at, "error", error_message=str(e))
            return None

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
            "janpara | %s | buyback=¥%s | used=¥%s | stock=%s",
            product.name,
            f"{result.get('buyback_price', 0):,}" if result.get("buyback_price") else "N/A",
            f"{result.get('used_price', 0):,}" if result.get("used_price") else "N/A",
            result.get("is_in_stock"),
        )
        return obs

    def _fetch_with_playwright(self, base_url: str, keyword: str) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.error("Playwright not installed")
            return None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=self.session.headers.get("User-Agent", ""))
                page.goto("https://www.janpara.co.jp/", wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(2000)
                search = page.locator('input[name="KEYWORDS"], input[placeholder*="検索"]').first
                if search.count() > 0:
                    search.fill(keyword)
                    search.press("Enter")
                    page.wait_for_timeout(5000)
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            self.logger.error("Playwright error: %s", e)
            return None

    def _parse(self, html: str, product: ProductModel, url: str) -> dict:
        result = {"buyback_price": None, "used_price": None, "is_in_stock": None, "raw": {}}
        soup = self.parse_html(html)

        # 価格を含む要素を探す
        all_prices = Normalizer.parse_price_multiple(soup.get_text())
        camera_prices = [p for p in all_prices if 10000 < p < 500000]

        # キーワードマッチする商品カード内の価格を探す
        for a in soup.find_all("a"):
            text = a.get_text()
            if any(kw.lower() in text.lower() for kw in product.keywords):
                parent = a.parent
                if parent:
                    for _ in range(3):
                        parent = parent.parent if parent.parent else parent
                    card_text = parent.get_text() if parent else ""
                    prices = Normalizer.parse_price_multiple(card_text)
                    prices = [p for p in prices if 10000 < p < 500000]
                    if prices:
                        result["used_price"] = min(prices)
                        result["is_in_stock"] = True
                        result["raw"]["matched_prices"] = prices
                        break

        # 買取価格（「買取」テキスト近くの金額）
        page_text = soup.get_text()
        m = re.search(r"買取[^¥￥\d]*[¥￥]?\s*([\d,]+)", page_text)
        if m:
            bp = Normalizer.parse_price(m.group(1))
            if bp and 1000 < bp < 500000:
                result["buyback_price"] = bp

        if not result["used_price"] and camera_prices:
            result["used_price"] = min(camera_prices)
            result["raw"]["fallback_prices"] = camera_prices[:5]

        return result

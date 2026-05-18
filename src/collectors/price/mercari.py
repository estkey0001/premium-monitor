"""メルカリ Collector。

国内フリマ相場・出品数・売れ行きを把握する。
SPA（完全JS描画）のためPlaywright必須。
取得不安定のため、CSVインポート併用を推奨。

禁止: ログイン突破、CAPTCHA突破、高頻度アクセス
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


class MercariCollector(BaseCollector):
    """メルカリ Collector（Playwright使用）。"""

    SEARCH_URL = "https://jp.mercari.com/search?keyword={keyword}&status=on_sale"
    SOLD_URL = "https://jp.mercari.com/search?keyword={keyword}&status=sold_out"

    def collect(
        self, product: ProductModel, config: ProductSourceConfigModel
    ) -> Optional[ObservationModel]:
        keyword = product.keywords[0] if product.keywords else product.name
        url = config.target_url or self.SEARCH_URL.format(keyword=keyword.replace(" ", "+"))
        started_at = datetime.now()

        html = self._fetch_with_playwright(url)
        if html is None:
            self.log_collection(product.id, started_at, "error",
                                error_message="playwright fetch failed or CAPTCHA")
            return None

        try:
            result = self._parse(html, product)
        except Exception as e:
            self.logger.error("Parse error: %s", e)
            self.log_collection(product.id, started_at, "error", error_message=str(e))
            return None

        if not result.get("prices"):
            self.log_collection(product.id, started_at, "error", error_message="no prices found")
            return None

        now = datetime.now()
        median_price = result["median_price"]
        obs = ObservationModel(
            id=str(ulid.new()),
            product_id=product.id,
            source_id=self.source.id,
            observation_type="flea_market",
            observed_at=now,
            is_in_stock=True if result["listing_count"] > 0 else None,
            price=median_price,
            raw_text=json.dumps({
                "listing_count": result["listing_count"],
                "median_price": median_price,
                "min_price": result["min_price"],
                "max_price": result["max_price"],
                "prices_sample": result["prices"][:10],
            }, ensure_ascii=False),
            confidence=0.70,
        )
        self.repository.insert_observation(obs)
        self.repository.insert_price_history(PriceHistoryModel(
            id=str(ulid.new()), product_id=product.id, source_id=self.source.id,
            price_type="used", price=median_price, recorded_at=now,
        ))

        self.log_collection(product.id, started_at, "success")
        self.logger.info(
            "mercari | %s | median=¥%s | listings=%d | range=¥%s〜¥%s",
            product.name, f"{median_price:,}", result["listing_count"],
            f"{result['min_price']:,}", f"{result['max_price']:,}",
        )
        return obs

    def _fetch_with_playwright(self, url: str) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            self.logger.error("Playwright not installed")
            return None
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=self.session.headers.get("User-Agent", ""))
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(5000)
                # CAPTCHA検知
                if "認証" in page.title() or "ロボット" in page.content()[:500]:
                    self.logger.warning("Mercari CAPTCHA detected")
                    browser.close()
                    return None
                html = page.content()
                browser.close()
                return html
        except Exception as e:
            self.logger.error("Playwright error: %s", e)
            return None

    def _parse(self, html: str, product: ProductModel) -> dict:
        soup = self.parse_html(html)
        prices = []

        # メルカリの商品カード: [data-testid="item-cell"] or li内の価格
        for el in soup.select('[data-testid="item-cell"], [class*="ItemCell"], li[class*="item"]'):
            text = el.get_text()
            if not any(kw.lower() in text.lower() for kw in product.keywords[:3]):
                continue
            p_list = Normalizer.parse_price_multiple(text)
            for p in p_list:
                if 5000 < p < 1000000:
                    prices.append(p)

        # フォールバック: ページ全体から¥価格を抽出
        if not prices:
            all_prices = Normalizer.parse_price_multiple(soup.get_text())
            prices = [p for p in all_prices if 10000 < p < 1000000]

        if not prices:
            return {"prices": [], "listing_count": 0}

        prices.sort()
        return {
            "prices": prices,
            "listing_count": len(prices),
            "median_price": prices[len(prices) // 2],
            "min_price": prices[0],
            "max_price": prices[-1],
        }

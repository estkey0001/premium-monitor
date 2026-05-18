"""eBay sold listings Collector。

海外成約価格を取得し、JPY換算する。

技術方針:
  1. eBay Browse API（APP_ID設定時）
  2. HTML parser（フォールバック）
  3. CSVインポート（最終手段）

Chrome調査 (2026-05-18): Access Denied (bot検知)
→ API優先、HTMLはPlaywright経由で試行
"""

import json
import logging
import os
import re
from datetime import datetime
from pathlib import Path
from typing import Optional

import ulid
import yaml

from src.collectors.base import BaseCollector
from src.models.observation import ObservationModel, PriceHistoryModel
from src.models.product import ProductModel
from src.models.source import ProductSourceConfigModel
from src.pipeline.normalizer import Normalizer

logger = logging.getLogger(__name__)
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


class EbayCollector(BaseCollector):
    """eBay sold listings Collector。"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fx = self._load_fx()

    def _load_fx(self) -> dict:
        try:
            with open(PROJECT_ROOT / "config" / "fx_rates.yaml") as f:
                data = yaml.safe_load(f)
            return data
        except Exception:
            return {"fx_rates": {"USD_JPY": 155}, "overseas_fees": {}}

    def collect(
        self, product: ProductModel, config: ProductSourceConfigModel
    ) -> Optional[ObservationModel]:
        url = config.target_url or self._build_search_url(product)
        started_at = datetime.now()

        # API優先
        result = self._try_api(product)

        # HTMLフォールバック
        if result is None:
            html = self._try_html(url)
            if html:
                result = self._parse_sold_listings(html, product)

        if result is None or result.get("sold_price_usd") is None:
            self.log_collection(product.id, started_at, "error",
                                error_message="no sold data (API unavailable, HTML blocked)")
            return None

        # JPY換算
        usd_jpy = self.fx.get("fx_rates", {}).get("USD_JPY", 155)
        fees = self.fx.get("overseas_fees", {})
        raw_jpy = int(result["sold_price_usd"] * usd_jpy)
        shipping = fees.get("default_shipping_jpy", 3000)
        tax = int(raw_jpy * fees.get("default_import_tax_rate", 0.10))
        net_jpy = raw_jpy + shipping + tax

        now = datetime.now()
        obs = ObservationModel(
            id=str(ulid.new()),
            product_id=product.id,
            source_id=self.source.id,
            observation_type="overseas_price",
            observed_at=now,
            price=net_jpy,
            raw_text=json.dumps({
                "sold_price_usd": result["sold_price_usd"],
                "usd_jpy": usd_jpy,
                "raw_jpy": raw_jpy,
                "shipping_jpy": shipping,
                "tax_jpy": tax,
                "net_jpy": net_jpy,
                "currency": result.get("currency", "USD"),
                "sold_count": result.get("sold_count", 0),
                "source": "ebay_sold",
            }, ensure_ascii=False),
            raw_html_hash="",
            confidence=0.70,
        )
        self.repository.insert_observation(obs)
        self.repository.insert_price_history(PriceHistoryModel(
            id=str(ulid.new()), product_id=product.id, source_id=self.source.id,
            price_type="overseas", price=net_jpy, recorded_at=now,
        ))

        self.log_collection(product.id, started_at, "success")
        self.logger.info(
            "ebay | %s | sold=$%s → ¥%s (net ¥%s)",
            product.name, result["sold_price_usd"], f"{raw_jpy:,}", f"{net_jpy:,}",
        )
        return obs

    def _build_search_url(self, product: ProductModel) -> str:
        kw = product.keywords[0] if product.keywords else product.name
        return f"https://www.ebay.com/sch/i.html?_nkw={kw.replace(' ', '+')}&LH_Complete=1&LH_Sold=1&_sop=13"

    def _try_api(self, product: ProductModel) -> Optional[dict]:
        """eBay Browse APIを試行する。APP_ID未設定時はNone。"""
        app_id = os.environ.get("EBAY_APP_ID", "")
        if not app_id:
            return None
        # API実装は将来対応
        self.logger.debug("eBay API: APP_ID set but API not yet implemented")
        return None

    def _try_html(self, url: str) -> Optional[str]:
        """Playwright経由でHTMLを取得する。"""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=self.session.headers.get("User-Agent", ""))
                page.goto(url, wait_until="networkidle", timeout=30000)
                page.wait_for_timeout(3000)
                html = page.content()
                browser.close()
                if "Access Denied" in html or len(html) < 1000:
                    return None
                return html
        except Exception as e:
            self.logger.debug("eBay HTML fetch failed: %s", e)
            return None

    def _parse_sold_listings(self, html: str, product: ProductModel) -> Optional[dict]:
        """sold listings HTMLから成約価格を抽出する。"""
        soup = self.parse_html(html)
        prices = []

        # eBayのsold price: s-item__price クラス
        for el in soup.select(".s-item__price, [class*='item__price']"):
            text = el.get_text()
            m = re.search(r'\$([\d,.]+)', text)
            if m:
                try:
                    price = float(m.group(1).replace(",", ""))
                    if 50 < price < 10000:
                        prices.append(price)
                except ValueError:
                    pass

        if not prices:
            # フォールバック: ページ全体から$価格を探す
            for m in re.finditer(r'\$([\d,]+\.?\d*)', html):
                try:
                    p = float(m.group(1).replace(",", ""))
                    if 100 < p < 5000:
                        prices.append(p)
                except ValueError:
                    pass

        if not prices:
            return None

        median = sorted(prices)[len(prices) // 2]
        return {
            "sold_price_usd": round(median, 2),
            "currency": "USD",
            "sold_count": len(prices),
            "min_usd": round(min(prices), 2),
            "max_usd": round(max(prices), 2),
        }

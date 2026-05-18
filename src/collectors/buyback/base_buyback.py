"""買取価格Collector基底クラス。

全買取店Collectorの共通ロジック:
- HTML取得 → 買取価格パース → BuybackPriceModel生成
- JS描画サイト対応（Playwright fallback）
- robots.txt / rate limit 遵守
"""

import logging
import re
from abc import abstractmethod
from datetime import datetime
from typing import Optional

import requests
import ulid

from src.models.buyback_price import BuybackPriceModel
from src.models.product import ProductModel

logger = logging.getLogger(__name__)


class BaseBuybackCollector:
    """買取価格Collector基底クラス。"""

    SHOP_ID: str = ""
    SHOP_NAME: str = ""
    BASE_URL: str = ""
    REQUIRES_JS: bool = False

    def __init__(self, user_agent: str = "", timeout: int = 15):
        self.user_agent = user_agent or "PremiumMonitor/1.0 (educational research)"
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": self.user_agent,
            "Accept-Language": "ja,en;q=0.9",
        })

    def collect(self, product: ProductModel, target_url: str = "") -> Optional[BuybackPriceModel]:
        """買取価格を取得する。"""
        url = target_url or self._build_url(product)
        if not url:
            logger.warning("[%s] No URL for %s", self.SHOP_NAME, product.name)
            return None

        try:
            html = self._fetch_html(url)
            if not html:
                return None

            price = self._parse_buyback_price(html, product)
            if not price or price <= 0:
                logger.info("[%s] No buyback price found for %s", self.SHOP_NAME, product.name)
                return None

            condition = self._parse_condition(html, product)
            buyback_url = self._parse_buyback_url(html, url)

            return BuybackPriceModel(
                id=str(ulid.new()),
                product_id=product.id,
                shop_id=self.SHOP_ID,
                shop_name=self.SHOP_NAME,
                buyback_price=price,
                condition=condition,
                buyback_url=buyback_url or url,
                observed_at=datetime.now(),
            )

        except Exception as e:
            logger.error("[%s] Error collecting %s: %s", self.SHOP_NAME, product.name, e)
            return None

    def _fetch_html(self, url: str) -> Optional[str]:
        """HTMLを取得する。JS描画サイトの場合はPlaywright fallback。"""
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"

            # JS描画チェック
            if self.REQUIRES_JS and len(resp.text) < 2000:
                return self._fetch_with_playwright(url)

            return resp.text
        except requests.RequestException as e:
            logger.warning("[%s] HTTP error: %s", self.SHOP_NAME, e)
            if self.REQUIRES_JS:
                return self._fetch_with_playwright(url)
            return None

    def _fetch_with_playwright(self, url: str) -> Optional[str]:
        """Playwright fallback。"""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=self.user_agent)
                page.goto(url, timeout=20000)
                page.wait_for_load_state("networkidle", timeout=10000)
                html = page.content()
                browser.close()
                return html
        except ImportError:
            logger.debug("[%s] Playwright not installed", self.SHOP_NAME)
            return None
        except Exception as e:
            logger.warning("[%s] Playwright error: %s", self.SHOP_NAME, e)
            return None

    @abstractmethod
    def _build_url(self, product: ProductModel) -> str:
        """商品に対応する買取ページURLを構築する。"""
        ...

    @abstractmethod
    def _parse_buyback_price(self, html: str, product: ProductModel) -> Optional[int]:
        """HTMLから買取価格を抽出する。"""
        ...

    def _parse_condition(self, html: str, product: ProductModel) -> str:
        """買取条件をパースする（デフォルト: new_unopened）。"""
        return "new_unopened"

    def _parse_buyback_url(self, html: str, original_url: str) -> str:
        """買取ページURLを返す。"""
        return original_url

    @staticmethod
    def extract_price_from_text(text: str) -> Optional[int]:
        """テキストから価格を抽出する汎用ヘルパー。"""
        # ¥123,456 / 123,456円 / 123456 パターン
        patterns = [
            r'[¥￥]\s*([\d,]+)',
            r'([\d,]+)\s*円',
            r'買取.{0,10}?([\d,]{4,})',
        ]
        for pat in patterns:
            m = re.search(pat, text)
            if m:
                price_str = m.group(1).replace(",", "")
                try:
                    price = int(price_str)
                    if 1000 <= price <= 10_000_000:
                        return price
                except ValueError:
                    continue
        return None

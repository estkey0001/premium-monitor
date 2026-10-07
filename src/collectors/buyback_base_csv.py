"""買取価格CSVアップデート用 軽量基底コレクター。
DB・Pydantic不要。requestsとBeautifulSoupのみ使用。
"""
import logging
import re
from abc import abstractmethod
from datetime import datetime, timezone, timedelta
from typing import Optional

import requests
from bs4 import BeautifulSoup

# robots.txt・同じドメインの間隔・正直な User-Agent は共通の作法（src/collectors/polite.py）を使う（Phase 12）。
# HONEST_UA はサブクラスが import する
from src.collectors import polite
from src.collectors.polite import HONEST_UA  # noqa: F401

JST = timezone(timedelta(hours=9))
logger = logging.getLogger(__name__)

class BaseCsvBuybackCollector:
    """CSVアップデート専用の軽量買取価格コレクター。"""

    SHOP_ID: str = ""       # CSV の buyback_shop 値
    SHOP_NAME: str = ""     # 表示用名称
    BASE_URL: str = ""
    REQUIRES_JS: bool = False

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.last_failure_reason: Optional[str] = None   # 最後の失敗理由（report用）
        self.last_confidence: str = "high"               # 価格信頼度: high/mid/low
        self.last_http_status: int = 0                   # 最後のHTTPステータスコード（debug用）
        self.last_html_length: int = 0                   # 取得HTMLの文字数（debug用）
        self.last_fetch_url: str = ""                    # 実際にfetchしたURL（debug用）
        self.last_elapsed_seconds: float = 0.0           # fetch所要時間（debug用）
        self.last_text_length: int = 0                   # inner_text の文字数（Playwright系）
        self.last_error_type: str = ""                   # 例外クラス名（debug用）
        self.last_from_cache: bool = False               # 前回の取得がこの実行のキャッシュからか
        self.last_wait_seconds: float = 0.0              # 同じドメインの間隔のために待った秒数
        self.request_count: int = 0                      # この実行で実際に送ったリクエスト数（キャッシュを除く）
        # 1回の実行の中だけ使う、取得できたページ（同じ URL を商品ごとに取り直さない）と、その時の HTTP 状態
        self._page_cache: dict[str, str] = {}
        self._page_status: dict[str, int] = {}
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": HONEST_UA,
            "Accept-Language": "ja,en;q=0.9",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        })

    def fetch(self, product_alias: str, product_name: str, condition: str = "new_unopened_simfree") -> Optional[dict]:
        """価格取得。成功→dict, 失敗→None。失敗理由は last_failure_reason に保存。"""
        self.last_failure_reason = None
        self.last_confidence = "high"  # デフォルトは high; コレクター内で mid/low に変更可能
        url = self._build_url(product_alias, product_name)
        if not url:
            logger.info("[%s] No URL defined for %s", self.SHOP_NAME, product_alias)
            self.last_failure_reason = "no_url"
            return None

        try:
            html = self._polite_fetch(url)
            if not html:
                logger.warning("[%s] Empty HTML for %s", self.SHOP_NAME, product_alias)
                if self.last_failure_reason is None:
                    self.last_failure_reason = "empty_html"
                return None

            price = self._parse_price(html, product_alias, product_name)
            if not price or price <= 0:
                logger.info("[%s] Price not found for %s", self.SHOP_NAME, product_alias)
                # サブクラスが _parse_price 内で reason をセット済みの場合は上書きしない
                # 例: product_not_listed（掲載なし）は price_not_found とは別扱い
                if self.last_failure_reason is None:
                    self.last_failure_reason = "price_not_found"
                return None

            actual_url = self._parse_detail_url(html, url)
            return {
                "product_alias": product_alias,
                "shop_id": self.SHOP_ID,
                "shop_name": self.SHOP_NAME,
                "buyback_price": price,
                "condition": condition,
                "url": actual_url,
                "link_verified": "true",
                "observed_at": datetime.now(tz=JST).isoformat(timespec="seconds"),
                "data_source": "auto_scraped",
                "confidence": self.last_confidence,  # high / mid / low
            }
        except Exception as e:
            logger.warning("[%s] Error fetching %s: %s", self.SHOP_NAME, product_alias, e)
            if self.last_failure_reason is None:
                self.last_failure_reason = f"exception_{type(e).__name__}"
            return None

    def _polite_fetch(self, url: str) -> Optional[str]:
        """robots.txt・同じドメインの間隔を守って取得する（Phase 12）。

        - この実行で取得できたページはキャッシュから返す（リクエストを送らない・待たない。HTTP 状態はその時の値）
        - robots.txt で禁止されている URL は取得しない（last_failure_reason=robots_disallowed）
        - 同じドメインへは rate_limit_sec（sources.yaml）・Crawl-delay・MIN_INTERVAL_SEC の最大の間隔をあける
        """
        if url in self._page_cache:
            self.last_from_cache = True
            self.last_fetch_url = url
            self.last_http_status = self._page_status.get(url, 0)
            self.last_html_length = len(self._page_cache[url])
            self.last_wait_seconds = 0.0
            return self._page_cache[url]
        self.last_from_cache = False
        if not polite.robots_allowed(url):
            self.last_fetch_url = url
            self.last_http_status = 0
            self.last_failure_reason = polite.robots_block_reason(url)
            logger.warning("[%s] robots.txt で禁止されているため取得しない: %s", self.SHOP_NAME, url)
            return None
        self.last_wait_seconds = polite.polite_wait(url, self.SHOP_ID)
        self.request_count += 1
        html = self._fetch_html(url)
        if html:
            self._page_cache[url] = html
            self._page_status[url] = self.last_http_status
        return html

    def _fetch_html(self, url: str) -> Optional[str]:
        self.last_fetch_url = url
        self.last_http_status = 0
        self.last_html_length = 0
        try:
            resp = self.session.get(url, timeout=self.timeout)
            self.last_http_status = resp.status_code
            resp.raise_for_status()
            resp.encoding = resp.apparent_encoding or "utf-8"
            if self.REQUIRES_JS and len(resp.text) < 3000:
                polite.polite_wait(url, self.SHOP_ID)      # 同じ URL への2回目の取得（Phase 12 監査 M5）
                html = self._fetch_with_playwright(url)
                self.last_html_length = len(html) if html else 0
                return html
            self.last_html_length = len(resp.text)
            return resp.text
        except requests.HTTPError as e:
            status = e.response.status_code if getattr(e, 'response', None) is not None else 0
            self.last_http_status = status
            self.last_failure_reason = f"http_{status}" if status else "http_error"
            if status == 429:
                self.last_failure_reason = "rate_limited_429"
            logger.warning("[%s] HTTP error %s: %s", self.SHOP_NAME, url, e)
            # ブロック（401/403）・429 は Playwright に切り替えて取り直さない（拒否を回り道で越えない。Phase 12）
            if self.REQUIRES_JS and status not in (401, 403, 429):
                polite.polite_wait(url, self.SHOP_ID)
                html = self._fetch_with_playwright(url)
                self.last_html_length = len(html) if html else 0
                return html
            return None
        except requests.exceptions.SSLError as e:
            # 接続の失敗（切断はブロックのこともある）を Playwright で取り直さない（Phase 12 監査 M5）
            self.last_failure_reason = "ssl_error"
            logger.warning("[%s] SSL error %s: %s", self.SHOP_NAME, url, e)
            return None
        except requests.RequestException as e:
            self.last_failure_reason = "connection_error"
            logger.warning("[%s] HTTP error %s: %s", self.SHOP_NAME, url, e)
            return None

    def _fetch_with_playwright(self, url: str) -> Optional[str]:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(user_agent=HONEST_UA)
                resp = page.goto(url, timeout=25000)
                if resp is not None and resp.status in (401, 403, 429):
                    self.last_failure_reason = polite.status_reason(resp.status)
                    browser.close()
                    return None
                page.wait_for_load_state("networkidle", timeout=12000)
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
    def _build_url(self, product_alias: str, product_name: str) -> str:
        """商品エイリアスに対応するURLを返す。"""
        ...

    @abstractmethod
    def _parse_price(self, html: str, product_alias: str, product_name: str) -> Optional[int]:
        """HTMLから買取価格（円）を返す。見つからない場合はNone。"""
        ...

    def _parse_detail_url(self, html: str, fallback_url: str) -> str:
        return fallback_url

    def extract_price(self, text: str, min_price: int = 10000, max_price: int = 5_000_000) -> Optional[int]:
        """テキストから買取価格を抽出する汎用ヘルパー。

        ⚠️ 商品名マッチなしで全テキストの最高値を返すため confidence=low に設定。
        キーワードで絞り込んだブロックにのみ使用してください。
        """
        self.last_confidence = "low"  # 汎用フォールバックは信頼度低
        patterns = [
            r'[¥￥]\s*([\d,]+)',
            r'([\d,]+)\s*円',
        ]
        prices = []
        for pat in patterns:
            for m in re.finditer(pat, text):
                try:
                    p = int(m.group(1).replace(",", ""))
                    if min_price <= p <= max_price:
                        prices.append(p)
                except ValueError:
                    pass
        return max(prices) if prices else None  # 最高買取価格を返す

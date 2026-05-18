"""BaseCollector - 全Collectorの共通基盤。

各サイトのCollectorはこのクラスを継承し、collect() を実装する。
"""

import hashlib
import logging
import re
import time
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.collectors.rate_limiter import RateLimiter
from src.collectors.robots_checker import RobotsChecker
from src.db.database import Database
from src.db.repository import Repository
from src.models.observation import ObservationModel, CollectorLogModel
from src.models.source import SourceModel, ProductSourceConfigModel
from src.models.product import ProductModel

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """全Collectorの基底クラス。

    サイト別Collectorはこのクラスを継承し、collect() メソッドを実装する。
    HTTP取得・レートリミット・robots.txtチェック・エラーハンドリングは
    この基底クラスが提供する。
    """

    # サブクラスで上書き可能な定数
    MAX_RETRIES = 3
    RETRY_DELAYS = [30, 60, 120]  # リトライ間隔（秒）

    def __init__(
        self,
        source: SourceModel,
        repository: Repository,
        rate_limiter: Optional[RateLimiter] = None,
        robots_checker: Optional[RobotsChecker] = None,
        user_agent: str = "PremiumMonitor/1.0",
        timeout: int = 30,
    ):
        self.source = source
        self.repository = repository
        self.rate_limiter = rate_limiter or RateLimiter()
        self.robots_checker = robots_checker or RobotsChecker(user_agent=user_agent)
        self.timeout = timeout

        # HTTPセッション（User-Agent設定済み）
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "ja,en-US;q=0.9,en;q=0.8",
            }
        )

        self.logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    # =========================================
    # サブクラスで実装するメソッド
    # =========================================

    @abstractmethod
    def collect(
        self, product: ProductModel, config: ProductSourceConfigModel
    ) -> Optional[ObservationModel]:
        """商品データを取得する。サブクラスで実装必須。

        Args:
            product: 対象商品
            config: 商品×情報源の設定

        Returns:
            取得データ。取得失敗時はNone。
        """
        ...

    def health_check(self) -> bool:
        """情報源への疎通確認。デフォルトはbase_urlへのGET。"""
        try:
            resp = self.session.get(
                self.source.base_url, timeout=self.timeout, allow_redirects=True
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    # =========================================
    # 共通ユーティリティ
    # =========================================

    def fetch_page(self, url: str) -> Optional[str]:
        """HTMLページを取得する（レートリミット・robots.txtチェック込み）。

        Args:
            url: 取得対象URL

        Returns:
            HTMLテキスト。取得失敗時はNone。
        """
        # robots.txtチェック
        if not self.robots_checker.is_allowed(url):
            self.logger.warning("Blocked by robots.txt: %s", url)
            return None

        # レートリミット（Crawl-delay考慮）
        crawl_delay = self.robots_checker.get_crawl_delay(url)
        interval = max(
            self.source.rate_limit_sec,
            crawl_delay or 0,
            60,  # グローバル最低60秒
        )
        self.rate_limiter.wait_if_needed(url, interval)

        # リトライ付きHTTP GET
        last_error: Optional[Exception] = None
        for attempt in range(self.MAX_RETRIES):
            try:
                response = self.session.get(url, timeout=self.timeout)
                response.raise_for_status()
                response.encoding = response.apparent_encoding or "utf-8"
                self.logger.debug(
                    "Fetched %s (status=%d, %d bytes)",
                    url,
                    response.status_code,
                    len(response.text),
                )
                return response.text

            except requests.Timeout as e:
                last_error = e
                self.logger.warning(
                    "Timeout on attempt %d/%d for %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    url,
                )
            except requests.HTTPError as e:
                last_error = e
                self.logger.warning(
                    "HTTP %s on attempt %d/%d for %s",
                    e.response.status_code if e.response else "???",
                    attempt + 1,
                    self.MAX_RETRIES,
                    url,
                )
            except requests.RequestException as e:
                last_error = e
                self.logger.warning(
                    "Request error on attempt %d/%d for %s: %s",
                    attempt + 1,
                    self.MAX_RETRIES,
                    url,
                    e,
                )

            # リトライ待機
            if attempt < self.MAX_RETRIES - 1:
                delay = self.RETRY_DELAYS[min(attempt, len(self.RETRY_DELAYS) - 1)]
                self.logger.info("Retrying in %ds...", delay)
                time.sleep(delay)

        self.logger.error("All %d attempts failed for %s: %s", self.MAX_RETRIES, url, last_error)
        return None

    def parse_html(self, html: str) -> BeautifulSoup:
        """HTMLをBeautifulSoupでパースする。"""
        return BeautifulSoup(html, "lxml")

    @staticmethod
    def parse_price(text: str) -> Optional[int]:
        """価格文字列を整数（円）にパースする。

        対応フォーマット: ¥189,800 / 189,800円 / 189800 / ￥189,800（税込）
        """
        if not text:
            return None
        # 数字とカンマ以外を除去
        cleaned = re.sub(r"[^\d]", "", text)
        if not cleaned:
            return None
        try:
            return int(cleaned)
        except ValueError:
            return None

    @staticmethod
    def normalize_stock_text(text: str) -> Optional[bool]:
        """在庫文字列をboolに変換する。

        True: 在庫あり / False: 在庫なし / None: 判定不能
        """
        if not text:
            return None
        text = text.strip()

        in_stock_keywords = [
            "在庫あり", "○", "◎", "残りわずか", "カートに入れる",
            "購入する", "予約する", "在庫有り", "入荷済み",
            "In Stock", "Add to Cart", "Buy Now",
        ]
        out_of_stock_keywords = [
            "在庫なし", "×", "品切れ", "売り切れ", "入荷待ち",
            "在庫切れ", "完売", "販売終了", "予定数終了",
            "Out of Stock", "Sold Out", "Currently Unavailable",
        ]

        text_lower = text.lower()
        for kw in in_stock_keywords:
            if kw.lower() in text_lower:
                return True
        for kw in out_of_stock_keywords:
            if kw.lower() in text_lower:
                return False

        return None

    @staticmethod
    def hash_html(html: str) -> str:
        """HTMLのSHA256ハッシュを生成（変化検知用）。"""
        return hashlib.sha256(html.encode("utf-8")).hexdigest()

    def log_collection(
        self,
        product_id: Optional[str],
        started_at: datetime,
        status: str,
        http_status: Optional[int] = None,
        error_message: Optional[str] = None,
    ) -> None:
        """Collector実行ログを記録する。"""
        import ulid

        finished_at = datetime.now()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)

        log = CollectorLogModel(
            id=str(ulid.new()),
            source_id=self.source.id,
            product_id=product_id,
            started_at=started_at,
            finished_at=finished_at,
            status=status,
            http_status=http_status,
            error_message=error_message,
            duration_ms=duration_ms,
        )
        try:
            self.repository.insert_collector_log(log)
        except Exception as e:
            self.logger.error("Failed to save collector log: %s", e)

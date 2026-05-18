"""robots.txt準拠チェッカー。

対象URLがrobots.txtで許可されているかを確認する。
"""

import logging
from functools import lru_cache
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests

logger = logging.getLogger(__name__)

# デフォルトのUser-Agent
DEFAULT_USER_AGENT = "PremiumMonitor/1.0"


class RobotsChecker:
    """robots.txtのルールを確認し、アクセス可否を判定する。"""

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, timeout: int = 10):
        self.user_agent = user_agent
        self.timeout = timeout
        self._parsers: dict[str, RobotFileParser | None] = {}

    def _get_robots_url(self, url: str) -> str:
        """URLからrobots.txtのURLを生成。"""
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"

    def _fetch_parser(self, robots_url: str) -> RobotFileParser | None:
        """robots.txtを取得してパーサーを返す。取得失敗時はNone。"""
        if robots_url in self._parsers:
            return self._parsers[robots_url]

        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = requests.get(
                robots_url,
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent},
            )
            if response.status_code == 200:
                parser.parse(response.text.splitlines())
                self._parsers[robots_url] = parser
                logger.debug("robots.txt loaded: %s", robots_url)
                return parser
            else:
                # robots.txt が存在しない場合は全許可扱い
                logger.debug(
                    "robots.txt not found (status=%d): %s",
                    response.status_code,
                    robots_url,
                )
                self._parsers[robots_url] = None
                return None
        except requests.RequestException as e:
            logger.warning("Failed to fetch robots.txt from %s: %s", robots_url, e)
            self._parsers[robots_url] = None
            return None

    def is_allowed(self, url: str) -> bool:
        """指定URLへのアクセスがrobots.txtで許可されているか。

        robots.txt取得失敗時はTrue（許可）として扱う。
        """
        robots_url = self._get_robots_url(url)
        parser = self._fetch_parser(robots_url)

        if parser is None:
            # robots.txtが取得できない場合は許可
            return True

        allowed = parser.can_fetch(self.user_agent, url)
        if not allowed:
            logger.warning("robots.txt DISALLOWED: %s", url)
        return allowed

    def get_crawl_delay(self, url: str) -> int | None:
        """robots.txtのCrawl-delayを取得。未設定ならNone。"""
        robots_url = self._get_robots_url(url)
        parser = self._fetch_parser(robots_url)

        if parser is None:
            return None

        try:
            delay = parser.crawl_delay(self.user_agent)
            return int(delay) if delay is not None else None
        except Exception:
            return None

    def clear_cache(self) -> None:
        """キャッシュをクリア（テスト用）。"""
        self._parsers.clear()

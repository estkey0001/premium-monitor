"""robots.txt準拠チェッカー。

対象URLがrobots.txtで許可されているかを確認する。
"""

import logging
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

logger = logging.getLogger(__name__)

# デフォルトのUser-Agent
DEFAULT_USER_AGENT = "PremiumMonitor/1.0"

# robots.txt の取得結果（is_allowed の判定とは別に、ログで区別するための状態）
#   loaded    : robots.txt を取得・解析できた
#   not_found : HTTP 4xx（robots.txt が存在しない。RFC 9309 では制限なし扱い）
#   unknown   : HTTP 5xx / ネットワークエラー等で取得できなかった
ROBOTS_LOADED = "loaded"
ROBOTS_NOT_FOUND = "not_found"
ROBOTS_UNKNOWN = "unknown"


class RobotsChecker:
    """robots.txtのルールを確認し、アクセス可否を判定する。"""

    def __init__(self, user_agent: str = DEFAULT_USER_AGENT, timeout: int = 10):
        self.user_agent = user_agent
        self.timeout = timeout
        self._parsers: dict[str, RobotFileParser | None] = {}
        # robots_url -> ROBOTS_LOADED / ROBOTS_NOT_FOUND / ROBOTS_UNKNOWN
        self._fetch_status: dict[str, str] = {}

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
                self._fetch_status[robots_url] = ROBOTS_LOADED
                logger.debug("robots.txt loaded: %s", robots_url)
                return parser
            else:
                self._fetch_status[robots_url] = (
                    ROBOTS_NOT_FOUND if 400 <= response.status_code < 500
                    else ROBOTS_UNKNOWN)
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
            self._fetch_status[robots_url] = ROBOTS_UNKNOWN
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

    def robots_status(self, url: str) -> str:
        """robots.txt の判定根拠を返す（ログ・監視表示用）。

        is_allowed() は取得失敗時も True を返す（既存仕様・fail-open）が、
        ログ上で「取得失敗 = 許可」と誤解させないために根拠を区別する。

        Returns:
            "allowed" / "disallowed" : robots.txt を解析した結果
            "not_found"              : robots.txt が存在しない（HTTP 4xx）
            "unknown"                : robots.txt を取得できなかった
        """
        robots_url = self._get_robots_url(url)
        parser = self._fetch_parser(robots_url)
        status = self._fetch_status.get(robots_url, ROBOTS_UNKNOWN)
        if status != ROBOTS_LOADED or parser is None:
            return status
        return "allowed" if parser.can_fetch(self.user_agent, url) else "disallowed"

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
        self._fetch_status.clear()

"""ドメイン単位のレートリミッター。

全Collectorで共有し、同一ドメインへの過剰アクセスを防ぐ。
"""

import logging
import threading
import time
from datetime import datetime
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class RateLimiter:
    """ドメイン単位でアクセス間隔を管理するシングルトン風リミッター。"""

    _instance: "RateLimiter | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "RateLimiter":
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
                cls._instance._last_access: dict[str, float] = {}
                cls._instance._domain_lock = threading.Lock()
        return cls._instance

    @staticmethod
    def _extract_domain(url: str) -> str:
        """URLからドメインを抽出する。"""
        parsed = urlparse(url)
        return parsed.netloc or parsed.path.split("/")[0]

    def wait_if_needed(self, url: str, min_interval_sec: int = 60) -> None:
        """前回アクセスからmin_interval_sec秒未満ならsleepして待つ。

        Args:
            url: アクセス先URL
            min_interval_sec: 最小アクセス間隔（秒）。最低60秒を強制。
        """
        # 安全のため最低60秒を強制
        min_interval_sec = max(min_interval_sec, 60)

        domain = self._extract_domain(url)

        with self._domain_lock:
            now = time.monotonic()
            last = self._last_access.get(domain)

            if last is not None:
                elapsed = now - last
                if elapsed < min_interval_sec:
                    wait_time = min_interval_sec - elapsed
                    logger.info(
                        "Rate limit: waiting %.1fs before accessing %s",
                        wait_time,
                        domain,
                    )
                    # ロック外でsleepするためにwait_timeを記録
                    self._last_access[domain] = now + wait_time
                    # ロックを一旦解放してsleep
                    self._domain_lock.release()
                    try:
                        time.sleep(wait_time)
                    finally:
                        self._domain_lock.acquire()
                    self._last_access[domain] = time.monotonic()
                    return

            self._last_access[domain] = now

    def get_last_access(self, url: str) -> datetime | None:
        """指定ドメインの最終アクセス日時を取得（デバッグ用）。"""
        domain = self._extract_domain(url)
        ts = self._last_access.get(domain)
        if ts is None:
            return None
        # monotonic → 実時刻へ変換（近似）
        offset = time.time() - time.monotonic()
        return datetime.fromtimestamp(ts + offset)

    def reset(self) -> None:
        """全ドメインのアクセス記録をクリア（テスト用）。"""
        with self._domain_lock:
            self._last_access.clear()

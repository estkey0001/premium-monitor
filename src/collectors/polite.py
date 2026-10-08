"""取得の共通の作法（Phase 12）: robots.txt・同じドメインの間隔・店（取得元）単位の打ち切り・正直な User-Agent。

既存の部品を使う:
- robots.txt の判定: src/collectors/robots_checker.RobotsChecker（ホストごとに1回だけ取得してキャッシュ）
- 同じドメインの間隔: src/collectors/rate_limiter.RateLimiter（最低60秒を強制）
新しい判定の仕組みは作らない。ここは複数の取得スクリプトから同じ形で呼ぶための薄い入口だけ。

禁止（このモジュールを使う側も守る）: robots.txt の無視・ステルス・プロキシの切り替え・CAPTCHA の回避・
ブラウザの指紋の偽装。ブロックされた取得元は、その実行の中では取りに行かない（次の実行で再び試す）。
"""

from __future__ import annotations

import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# 正直な User-Agent（ブラウザを名乗らない。ブラウザ互換の「Mozilla」の形にもしない。監査 L1）
HONEST_UA = "PremiumMonitor/1.0 (+https://github.com/estkey0001/premium-monitor)"
# robots.txt の User-agent の照合に使う名前（判定のライブラリは最初の / より前を名前として使うので、
# UA の全文ではなくこの名前を渡す。全文だと「Mozilla」として判定され、PremiumMonitor 向けの禁止を見落とす）
ROBOTS_AGENT = "PremiumMonitor/1.0"

# 同じドメインへの最低の間隔（秒）。sources.yaml の rate_limit_sec・robots.txt の Crawl-delay の大きい方を使い、
# どちらも無いときもこれより短くしない（RateLimiter も最低60秒を強制する）
MIN_INTERVAL_SEC = 60

_SOURCE_RATE_LIMITS: Optional[dict] = None
_SOURCE_HOSTS: Optional[dict] = None
_ROBOTS = None


def source_rate_limit_sec(source_id: str) -> Optional[int]:
    """config/sources.yaml の rate_limit_sec（source_id は src_xxx。無ければ None）。"""
    global _SOURCE_RATE_LIMITS
    if _SOURCE_RATE_LIMITS is None:
        _SOURCE_RATE_LIMITS = {}
        try:
            from pathlib import Path

            import yaml
            path = Path(__file__).resolve().parent.parent.parent / "config" / "sources.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            for src in (data.get("sources", []) if isinstance(data, dict) else data):
                if isinstance(src, dict) and src.get("id") and src.get("rate_limit_sec"):
                    _SOURCE_RATE_LIMITS[str(src["id"])] = int(src["rate_limit_sec"])
        except Exception as e:  # noqa: BLE001 - 設定が読めなくても最低の間隔は守る
            logger.warning("sources.yaml の rate_limit_sec を読めません: %s", e)
    return _SOURCE_RATE_LIMITS.get(source_id if source_id.startswith("src_") else f"src_{source_id}")


def source_id_for_url(url: str) -> str:
    """URL のホストに対応する sources.yaml の id（base_url のホストが同じもの。www. の有無は同じとみなす）。
    見つからなければ空文字（そのときも最低の間隔は守る）。"""
    global _SOURCE_HOSTS
    from urllib.parse import urlparse

    def _host(u):
        h = urlparse(u).netloc.lower()
        return h[4:] if h.startswith("www.") else h
    if _SOURCE_HOSTS is None:
        _SOURCE_HOSTS = {}
        try:
            from pathlib import Path

            import yaml
            path = Path(__file__).resolve().parent.parent.parent / "config" / "sources.yaml"
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or []
            for src in (data.get("sources", []) if isinstance(data, dict) else data):
                if isinstance(src, dict) and src.get("id") and src.get("base_url"):
                    _SOURCE_HOSTS.setdefault(_host(str(src["base_url"])), str(src["id"]))
        except Exception as e:  # noqa: BLE001
            logger.warning("sources.yaml の base_url を読めません: %s", e)
    return _SOURCE_HOSTS.get(_host(url), "")


def robots_checker():
    """プロセスで共有する RobotsChecker。"""
    global _ROBOTS
    if _ROBOTS is None:
        from src.collectors.robots_checker import RobotsChecker
        _ROBOTS = RobotsChecker(user_agent=ROBOTS_AGENT)
    return _ROBOTS


def robots_block_reason(url: str) -> str:
    """取得しない理由（空なら取得してよい）。robots.txt で禁止 → robots_disallowed、robots.txt に到達できない
    （5xx・通信の失敗）→ robots_unreachable（規約上の禁止と一時的な障害を取り違えないため。Phase 12 再レビュー N-M2）。"""
    rc = robots_checker()
    status_fn = getattr(rc, "robots_status", None)
    if callable(status_fn):
        st = status_fn(url)
        if st == "unknown":
            return "robots_unreachable"
        if st == "disallowed":
            return "robots_disallowed"
        if st in ("allowed", "not_found"):
            return ""
    return "" if rc.is_allowed(url) else "robots_disallowed"


def robots_allowed(url: str) -> bool:
    """robots.txt で取得してよい URL か（PremiumMonitor/1.0 として判定）。

    robots.txt を取得できなかった（5xx・ネットワークの失敗 = unknown）ときは取得しない（RFC 9309 の
    「到達できないときは全面禁止とみなす」に合わせる。監査 M7）。robots.txt が無い（4xx）ときは制限なし。
    """
    return not robots_block_reason(url)


def polite_wait(url: str, source_id: str = "") -> float:
    """同じドメインへの間隔（rate_limit_sec・Crawl-delay・MIN_INTERVAL_SEC の最大）をあける。待った秒数を返す。"""
    from src.collectors.rate_limiter import RateLimiter
    sid = source_id or source_id_for_url(url)
    interval = max((source_rate_limit_sec(sid) or 0) if sid else 0,
                   robots_checker().get_crawl_delay(url) or 0, MIN_INTERVAL_SEC)
    t0 = time.monotonic()
    RateLimiter().wait_if_needed(url, interval)
    return round(time.monotonic() - t0, 1)


# ── 店（取得元）単位の打ち切り ─────────────────────────────────────────────
# ブロック・規約上の拒否（再試行しても変わらない）→ その取得元の残りはこの実行では取りに行かない
CUTOFF_IMMEDIATE = frozenset({"http_403", "http_401", "site_blocked", "rate_limited_429", "robots_disallowed",
                              "robots_unreachable",
                              "blocked_cloud_ip", "cloudflare_blocked", "access_denied",
                              "html_scraping_disabled"})
# 一時的な失敗・ページの形の不一致（パーサーの不一致）→ 同じ取得元で2回続いたら打ち切る
CUTOFF_AFTER = 2
CUTOFF_COUNTED = frozenset({"price_not_found", "http_404", "service_unavailable", "timeout", "connection_error",
                            "ssl_error", "playwright_error", "empty_html", "http_500", "http_502", "http_503",
                            "http_504", "html_failed", "no_data"})
# 打ち切りに数えない（商品ごとの事情: 未掲載・URL 未定義・取得しない設定）
CUTOFF_IGNORED = frozenset({"product_not_listed", "no_url", "not_supported", "model_mismatch",
                            "not_buyback_context", "trade_in_or_conditional_only",
                            # 商品ごとの事情（その商品の価格が範囲外・検索結果が販売の一覧だった。Phase 12 再レビュー N-M1）
                            "price_out_of_range", "sales_catalog_no_buyback",
                            # 同じ JAN に違う価格が並んだ（その商品の事情。Phase 17 監査 L3）
                            "ambiguous_rows"})


class ShopCutoff:
    """取得元ごとの連続失敗を数え、この実行の中で取りに行くのをやめる取得元を決める（次の実行では再び試す）。"""

    def __init__(self):
        self.consecutive: dict[str, int] = {}
        self.cut: dict[str, dict] = {}

    def is_cut(self, source: str) -> bool:
        return source in self.cut

    def record(self, source: str, ok: bool, reason: Optional[str] = None) -> None:
        if ok:
            self.consecutive[source] = 0
            return
        r = str(reason or "")
        if r in CUTOFF_IGNORED or source in self.cut:
            return
        if r in CUTOFF_IMMEDIATE:
            self.cut[source] = {"reason": r, "after_attempts": self.consecutive.get(source, 0) + 1, "skipped": []}
            logger.warning("[%s] %s のため、この実行では以後の取得をやめる", source, r)
            return
        # 一時的な失敗・形の不一致（CUTOFF_COUNTED）に加え、名前の分からない失敗の理由も安全側に数える
        # （理由の名前の取り違えで打ち切りが効かなくならないように。Phase 12 監査 H1）
        n = self.consecutive.get(source, 0) + 1
        self.consecutive[source] = n
        if n >= CUTOFF_AFTER:
            self.cut[source] = {"reason": r or "unknown_failure", "after_attempts": n, "skipped": []}
            logger.warning("[%s] %s が%d回続いたため、この実行では以後の取得をやめる", source, r, n)

    def skip(self, source: str, item: str) -> str:
        """打ち切った取得元の項目を飛ばしたことを記録し、打ち切りの理由を返す。"""
        self.cut[source]["skipped"].append(item)
        return self.cut[source]["reason"]


def status_reason(status: Optional[int]) -> str:
    """HTTP 状態から失敗の理由の名前（打ち切りの判定に使う）。"""
    if status in (401, 403):
        return f"http_{status}"
    if status == 429:
        return "rate_limited_429"
    if status == 503:
        return "service_unavailable"
    if status:
        return f"http_{status}"
    return "connection_error"

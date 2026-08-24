#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API 収集ランタイム — kill-switch / dry-run / rate-limit / retry / circuit-breaker /
error 分類 / health / data_origin。

API 自動化の安全機構を一元化する。利益/AI ロジックは変更しない（収集側の制御のみ）。
Secret 実値は一切扱わない（存在有無のみ）。
"""
from __future__ import annotations

import os
import random
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

# ── data_origin（API/fallback/manual を必ず区別）──
ORIGIN_API = "api"
ORIGIN_FALLBACK = "fallback"
ORIGIN_MANUAL = "manual"

# API 定義: 名前 → (キーとなる env 群, kill-switch env)
API_DEFS = {
    "ebay": {"keys": ("EBAY_APP_ID", "EBAY_CLIENT_ID"), "enable": "ENABLE_EBAY_API",
             "ttl_sec": 3600},
    "rakuten": {"keys": ("RAKUTEN_APP_ID",), "enable": "ENABLE_RAKUTEN_API", "ttl_sec": 3600},
    "yahoo": {"keys": ("YAHOO_SHOPPING_APP_ID",), "enable": "ENABLE_YAHOO_API", "ttl_sec": 3600},
}

# 一時エラー（retry 対象）/ 恒久エラー（retry 禁止）
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
PERMANENT_STATUS = {400, 401, 403}


def is_configured(api: str) -> bool:
    d = API_DEFS.get(api, {})
    return any(bool(os.environ.get(k)) for k in d.get("keys", ()))


def configured_status(api: str) -> str:
    return "configured" if is_configured(api) else "not_configured"


def kill_switch_on(api: str) -> bool:
    """ENABLE_<API>_API が明示的に false のとき True（＝停止）。既定は有効。"""
    d = API_DEFS.get(api, {})
    val = (os.environ.get(d.get("enable", ""), "") or "").strip().lower()
    return val in ("false", "0", "no", "off")


def api_enabled(api: str) -> bool:
    """このAPIを実際に叩いてよいか（configured かつ kill-switch off）。"""
    return is_configured(api) and not kill_switch_on(api)


def is_dry_run() -> bool:
    return (os.environ.get("API_DRY_RUN", "") or "").strip().lower() in ("1", "true", "yes", "on")


# ── Progressive Rollout: stage 制御（Task43/44）──
STAGE_ENV = {"ebay": "EBAY_API_STAGE", "rakuten": "RAKUTEN_API_STAGE", "yahoo": "YAHOO_API_STAGE"}
VALID_STAGES = ("0", "5", "10", "25", "all")


def api_stage(api: str) -> str:
    """rollout stage を返す（0/5/10/25/all）。既定は 0（Canary のみ）。安全側。"""
    raw = (os.environ.get(STAGE_ENV.get(api, ""), "") or "").strip().lower()
    return raw if raw in VALID_STAGES else "0"


def stage_product_limit(stage: str):
    """stage → 取得を許可する商品数上限。'all'→None（無制限）、'0'→0（Canaryのみ）。"""
    if stage == "all":
        return None
    try:
        return int(stage)
    except (TypeError, ValueError):
        return 0


def rollout_state(api: str) -> str:
    """API の現在の rollout 状態を返す（Task43）。

    NOT_CONFIGURED / DISABLED / DRY_RUN / CANARY / STAGE_5 / STAGE_10 / STAGE_25 / FULL
    （ROLLOUT_BLOCKED は Canary 失敗時に上位ロジックが付与する）
    """
    if not is_configured(api):
        return "NOT_CONFIGURED"
    if kill_switch_on(api):
        return "DISABLED"
    if is_dry_run():
        return "DRY_RUN"
    stage = api_stage(api)
    return {"0": "CANARY", "5": "STAGE_5", "10": "STAGE_10",
            "25": "STAGE_25", "all": "FULL"}.get(stage, "CANARY")


def ttl_seconds(api: str) -> int:
    return API_DEFS.get(api, {}).get("ttl_sec", 3600)


def classify_error(status: Optional[int], exc: Optional[Exception] = None) -> str:
    """transient / permanent / unknown を返す。"""
    if status in PERMANENT_STATUS:
        return "permanent"
    if status in TRANSIENT_STATUS:
        return "transient"
    if exc is not None and status is None:
        # timeout / connection error は transient 扱い
        return "transient"
    if status and 200 <= status < 300:
        return "ok"
    return "unknown"


@dataclass
class RateLimitState:
    request_count: int = 0
    remaining: Optional[int] = None
    reset_at: Optional[str] = None
    count_429: int = 0
    retry_after: Optional[int] = None
    last_rate_limit_event: Optional[str] = None

    def note_request(self):
        self.request_count += 1

    def note_429(self, retry_after: Optional[int], now_iso: str):
        self.count_429 += 1
        self.retry_after = retry_after
        self.last_rate_limit_event = now_iso

    def as_dict(self):
        return {"request_count": self.request_count, "remaining": self.remaining,
                "reset_at": self.reset_at, "count_429": self.count_429,
                "retry_after": self.retry_after, "last_rate_limit_event": self.last_rate_limit_event}


@dataclass
class CircuitBreaker:
    """連続失敗で一時停止（無限連打防止）。"""
    threshold: int = 5
    cooldown_sec: int = 300
    consecutive_failures: int = 0
    opened_at: Optional[float] = None

    def record_success(self):
        self.consecutive_failures = 0
        self.opened_at = None

    def record_failure(self, now: float):
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold and self.opened_at is None:
            self.opened_at = now

    def is_open(self, now: float) -> bool:
        if self.opened_at is None:
            return False
        if now - self.opened_at >= self.cooldown_sec:
            # half-open: 再試行を許可（成功で閉じる）
            return False
        return True

    def as_dict(self):
        return {"threshold": self.threshold, "consecutive_failures": self.consecutive_failures,
                "open": self.opened_at is not None}


@dataclass
class HealthTracker:
    api: str
    requests: int = 0
    success: int = 0
    failed: int = 0
    rate_limited: int = 0
    timeout: int = 0
    retries: int = 0
    items_received: int = 0
    exact_matches: int = 0
    rejected: int = 0
    main_eligible: int = 0
    latency_ms_total: int = 0
    last_success: Optional[str] = None
    errors: list = field(default_factory=list)

    def avg_latency_ms(self) -> int:
        return int(self.latency_ms_total / self.success) if self.success else 0

    def success_rate(self) -> float:
        return round(self.success / self.requests, 4) if self.requests else 0.0

    def as_dict(self):
        return {"api": self.api, "requests": self.requests, "success": self.success,
                "failed": self.failed, "rate_limited": self.rate_limited, "timeout": self.timeout,
                "retries": self.retries, "items_received": self.items_received,
                "exact_matches": self.exact_matches, "rejected": self.rejected,
                "main_eligible": self.main_eligible, "average_latency_ms": self.avg_latency_ms(),
                "success_rate": self.success_rate(), "last_success": self.last_success,
                "error_kinds": _count_errors(self.errors)}


def _count_errors(errs):
    from collections import Counter
    return dict(Counter(e.get("kind", "unknown") for e in errs))


def retry_with_backoff(fn: Callable, *, max_retries: int = 4, base_delay: float = 1.0,
                       sleep_fn: Callable[[float], None] = time.sleep,
                       health: Optional[HealthTracker] = None,
                       breaker: Optional[CircuitBreaker] = None,
                       now_fn: Callable[[], float] = time.monotonic) -> dict:
    """fn() -> {"status": int|None, "data": ..., "retry_after": int|None, "exc": Exception|None}
    を、exponential backoff + jitter で再試行。恒久エラーは即中断。Retry-After 優先。

    返り値: {"ok": bool, "data":..., "status":..., "attempts": n, "error_kind": str|None}
    """
    if breaker and breaker.is_open(now_fn()):
        return {"ok": False, "data": None, "status": None, "attempts": 0, "error_kind": "circuit_open"}

    attempt = 0
    last_status = None
    while attempt <= max_retries:
        attempt += 1
        if health:
            health.requests += 1
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001
            r = {"status": None, "data": None, "retry_after": None, "exc": e}
        status = r.get("status")
        last_status = status
        kind = classify_error(status, r.get("exc"))
        if kind == "ok":
            if health:
                health.success += 1
            if breaker:
                breaker.record_success()
            return {"ok": True, "data": r.get("data"), "status": status, "attempts": attempt,
                    "error_kind": None}
        if kind == "permanent":
            if health:
                health.failed += 1
                health.errors.append({"kind": f"permanent_{status}"})
            if breaker:
                breaker.record_failure(now_fn())
            return {"ok": False, "data": None, "status": status, "attempts": attempt,
                    "error_kind": f"permanent_{status}"}
        # transient / unknown → retry（上限まで）
        if health:
            health.failed += 1
            if status == 429:
                health.rate_limited += 1
            if status is None:
                health.timeout += 1
            health.errors.append({"kind": f"transient_{status}"})
        if breaker:
            breaker.record_failure(now_fn())
        if attempt > max_retries:
            break
        # Retry-After 優先、無ければ指数バックオフ + jitter
        ra = r.get("retry_after")
        delay = float(ra) if ra else base_delay * (2 ** (attempt - 1))
        delay += random.uniform(0, min(1.0, delay * 0.25))
        if health:
            health.retries += 1
        sleep_fn(delay)
    return {"ok": False, "data": None, "status": last_status, "attempts": attempt,
            "error_kind": "exhausted_retries"}

# -*- coding: utf-8 -*-
"""TCG 収集の実行の指標と、取得元の健全性の分類（Coverage Wave 6 Stage J / Z）。

run が成功したことと、取得元が健全なことは別。取得 0 件・パーサーの不一致（取得はできたが期待するものが無い）・
ブロック・到達不能（タイムアウトを含む）・失敗・取得数の上限による打ち切りを区別して数える。公開してよい件数と秒数だけ。
"""
from __future__ import annotations

HEALTHY = "HEALTHY"
ZERO_EVENTS = "ZERO_EVENTS"            # 取得でき、現在の販売情報が無い（市場なしと断定しない。取得できた事実だけ）
PARSER_DEGRADED = "PARSER_DEGRADED"    # 取得できたが、期待する記事・商品を発見できない（ページの形が変わった疑い）
BLOCKED = "BLOCKED"                    # robots 拒否・403 など（回避しない）
UNREACHABLE = "UNREACHABLE"            # 通信失敗・robots に到達できない・タイムアウト
FAILED = "FAILED"                      # 1 ページも取得できない・例外
CLASSES = (HEALTHY, ZERO_EVENTS, PARSER_DEGRADED, BLOCKED, UNREACHABLE, FAILED)
_TIMEOUT_WORDS = ("timeout", "timed out", "readtimeout", "connecttimeout")


def _timed_out(h: dict) -> bool:
    msgs = " ".join(str(m) for m in (h.get("error_messages") or [])).lower()
    return any(w in msgs for w in _TIMEOUT_WORDS)


def classify(h: dict | None) -> str:
    """1 つの取得元の health（funnel 付き）から分類を決める。優先順: BLOCKED > UNREACHABLE > FAILED > PARSER_DEGRADED > ZERO_EVENTS > HEALTHY。"""
    h = h or {}
    st = str(h.get("status") or "")
    if st == "BLOCKED" or (h.get("blocked") and not (h.get("funnel") or {}).get("pages_loaded")):
        return BLOCKED
    if h.get("unreachable") or _timed_out(h) and not (h.get("funnel") or {}).get("pages_loaded"):
        return UNREACHABLE
    if st == "FAILED":
        return FAILED
    f = h.get("funnel") or {}
    if st == "DEGRADED" or int(f.get("structure_changed_pages") or 0) > 0:
        return PARSER_DEGRADED
    if st == "OK_NO_EVENTS":
        return ZERO_EVENTS
    if st == "HEALTHY":
        return HEALTHY
    return FAILED if not f.get("pages_loaded") else PARSER_DEGRADED     # 状態が不明なものを healthy にしない


def is_truncated(h: dict | None) -> bool:
    """詳細の取得が上限で打ち切られ、見つけた告知を全部は読めていない取得元。"""
    h = h or {}
    return int(h.get("skipped_due_to_limit") or 0) > 0 or bool(h.get("truncated"))


def summarize(collector_health: list[dict], lottery_sources: list[dict], *, total_seconds: float,
              cache_stats: dict | None, collector_seconds: dict | None = None, lottery_seconds: dict | None = None,
              global_cap: int = 0) -> dict:
    """公開してよい指標（件数・秒数だけ。取得元の名前・URL は入れない）。"""
    counts = {k: 0 for k in CLASSES}
    truncated = partial_blocked = 0
    detail_fetched = detail_candidates = 0
    list_requests = 0
    rows = [h for h in (collector_health or [])] + [
        {"status": s.get("health"), "blocked": s.get("blocked"), "unreachable": s.get("unreachable"),
         "error_messages": [s.get("error")] if s.get("error") else [],
         "funnel": {"pages_loaded": 1 if s.get("reachable") else 0, "structure_changed_pages": s.get("structure_changed_pages", 0)},
         "skipped_due_to_limit": s.get("skipped_due_to_limit", 0), "truncated": s.get("truncated")}
        for s in (lottery_sources or []) if s.get("collection_method") != "MANUAL_VERIFIED" and s.get("health") is not None]
    for h in rows:
        cls = classify(h)
        counts[cls] += 1
        truncated += int(is_truncated(h))
        # 一部のページだけ読めた取得元（詳細だけ 403 など）は HEALTHY に隠れるので、別に数える
        partial_blocked += int(bool(h.get("blocked")) and cls not in (BLOCKED, UNREACHABLE, FAILED))
    for s in lottery_sources or []:
        detail_fetched += int(s.get("detail_fetched") or 0)
        detail_candidates += int(s.get("detail_candidates") or 0)
    for h in collector_health or []:
        list_requests += int((h.get("funnel") or {}).get("pages_requested") or 0)
    slow = max([*(collector_seconds or {}).values(), *(lottery_seconds or {}).values()] or [0])
    c = cache_stats or {}
    return {
        "mode": "PARALLEL_CROSS_DOMAIN", "global_cap": int(global_cap), "per_domain_concurrency": 1,
        "total_seconds": round(float(total_seconds), 1), "slowest_source_seconds": round(float(slow), 1),
        "sources_by_health": counts, "sources_total": sum(counts.values()), "truncated_sources": truncated, "partial_blocked_sources": partial_blocked,
        "list_requests": list_requests, "detail_candidates": detail_candidates, "detail_fetched": detail_fetched,
        "http_fetches": int(c.get("fetches") or 0), "http_cache_hits": int(c.get("cache_hits") or 0),
        "domains": int(c.get("domains") or 0), "max_fetches_per_domain": int(c.get("max_per_domain") or 0),
        "cache_scope": "THIS_RUN_ONLY",
    }

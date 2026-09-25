# -*- coding: utf-8 -*-
"""Task11: TCG Opportunity Score / Task12: BUY NOW Signal。

重要: 既存の Profit / AI / Opportunity ロジックには一切触れない。
これは TCG BOX 専用の独立した追加レイヤー。
"""
from __future__ import annotations

from typing import Optional

from .models import (
    INSTANT_SALE_EVENTS, EVENT_LOTTERY, EVENT_PREORDER,
    EVENT_GUERRILLA_SALE, EVENT_FIRST_COME, EVENT_CONVENIENCE_STORE,
    EVENT_ONLINE_RESTOCK, EVENT_RESTOCK, EVENT_OFFICIAL_STORE,
    SHRINK_SEALED, SHRINK_UNKNOWN, SHRINK_TAPE_CUT, SHRINK_REMOVED,
    SHRINK_OPENED_BOX, SHRINK_PACK_ONLY,
    OFFICIAL_SOURCE_TYPES, CONF_HIGH, CONF_MEDIUM,
    ST_AVAILABLE_NOW, ST_OPEN, ST_ENDING_SOON, ST_PURCHASE_PERIOD,
    PRIO_CRITICAL, PRIO_HIGH, PRIO_MEDIUM, PRIO_LOW,
)

# 各要素の配点（合計 100）
WEIGHTS: dict[str, int] = {
    "premium": 30,            # Premium %
    "liquidity": 15,          # 流動性（サンプル数）
    "availability": 15,       # 今買えるか
    "purchase_difficulty": 10,  # 入手難易度（低いほど加点）
    "restock_probability": 8,   # 再入荷の見込み
    "source_confidence": 12,    # 情報の信頼度
    "shrink_condition": 6,      # シュリンク状態
    "purchase_limit": 4,        # 購入制限の緩さ
}

# BUY NOW の閾値
BUY_NOW_MIN_PREMIUM_PERCENT = 30.0


def _premium_points(premium_percent: Optional[float]) -> float:
    if premium_percent is None:
        return 0.0
    if premium_percent <= 0:
        return 0.0
    # 100% で満点
    return WEIGHTS["premium"] * min(premium_percent / 100.0, 1.0)


def _liquidity_points(sample_count: int) -> float:
    if sample_count <= 0:
        return 0.0
    return WEIGHTS["liquidity"] * min(sample_count / 10.0, 1.0)


def _availability_points(status: str) -> float:
    return {
        ST_AVAILABLE_NOW: WEIGHTS["availability"],
        ST_PURCHASE_PERIOD: WEIGHTS["availability"] * 0.9,
        ST_ENDING_SOON: WEIGHTS["availability"] * 0.6,
        ST_OPEN: WEIGHTS["availability"] * 0.5,
    }.get(status, 0.0)


def _difficulty_points(event_type: str) -> float:
    """入手難易度が低いほど加点。"""
    ratio = {
        EVENT_OFFICIAL_STORE: 0.9,
        EVENT_PREORDER: 0.8,
        EVENT_CONVENIENCE_STORE: 0.6,
        EVENT_ONLINE_RESTOCK: 0.5,
        EVENT_RESTOCK: 0.5,
        EVENT_FIRST_COME: 0.4,
        EVENT_LOTTERY: 0.2,       # 抽選は当たらないと買えない
        EVENT_GUERRILLA_SALE: 0.2,
    }.get(event_type, 0.3)
    return WEIGHTS["purchase_difficulty"] * ratio


def _restock_points(event_type: str, signals: int = 0) -> float:
    base = 0.6 if event_type in (EVENT_RESTOCK, EVENT_ONLINE_RESTOCK) else 0.3
    base += min(signals * 0.2, 0.4)
    return WEIGHTS["restock_probability"] * min(base, 1.0)


def _confidence_points(source_type: str, confidence: str) -> float:
    ratio = 0.2
    if source_type in OFFICIAL_SOURCE_TYPES:
        ratio = 1.0 if confidence == CONF_HIGH else 0.7
    elif confidence == CONF_MEDIUM:
        ratio = 0.5
    return WEIGHTS["source_confidence"] * ratio


def _shrink_points(shrink_status: str) -> float:
    ratio = {
        SHRINK_SEALED: 1.0,
        SHRINK_UNKNOWN: 0.4,      # 不明は満点にしない（BOX=シュリンクと仮定しない）
        SHRINK_TAPE_CUT: 0.3,
        SHRINK_REMOVED: 0.2,
        SHRINK_OPENED_BOX: 0.1,
        SHRINK_PACK_ONLY: 0.3,
    }.get(shrink_status, 0.3)
    return WEIGHTS["shrink_condition"] * ratio


def _limit_points(purchase_limit: Optional[str]) -> float:
    if not purchase_limit:
        return WEIGHTS["purchase_limit"] * 0.5   # 不明
    import re
    nums = [int(n) for n in re.findall(r"\d+", str(purchase_limit))]
    if not nums:
        return WEIGHTS["purchase_limit"] * 0.5
    n = max(nums)
    return WEIGHTS["purchase_limit"] * min(n / 5.0, 1.0)


def opportunity_score(event: dict, premium: Optional[dict] = None,
                      signals: int = 0) -> dict:
    """TCG BOX 専用の機会スコア（0-100）と内訳を返す。"""
    premium = premium or event.get("premium") or {}
    parts = {
        "premium": _premium_points(premium.get("premium_percent")),
        "liquidity": _liquidity_points(premium.get("sealed_sample_count", 0)),
        "availability": _availability_points(event.get("status", "")),
        "purchase_difficulty": _difficulty_points(event.get("event_type", "")),
        "restock_probability": _restock_points(event.get("event_type", ""), signals),
        "source_confidence": _confidence_points(event.get("source_type", ""),
                                                event.get("confidence", "low")),
        "shrink_condition": _shrink_points(event.get("shrink_status", SHRINK_UNKNOWN)),
        "purchase_limit": _limit_points(event.get("purchase_limit")),
    }
    total = int(round(sum(parts.values())))
    return {
        "score": max(0, min(100, total)),
        "breakdown": {k: round(v, 1) for k, v in parts.items()},
    }


def buy_now_signal(event: dict, premium: Optional[dict] = None) -> dict:
    """Task12: BUY NOW 判定。

    公式 / 小売公式から現在購入可能で、かつ十分なプレミアがある場合のみ。
    規約・購入制限・転売禁止条件がある場合は必ず notes に明示する。
    """
    premium = premium or event.get("premium") or {}
    pct = premium.get("premium_percent")
    status = event.get("status", "")
    src = event.get("source_type", "")

    reasons: list[str] = []
    notes: list[str] = []

    official = src in OFFICIAL_SOURCE_TYPES
    purchasable = status in (ST_AVAILABLE_NOW, ST_PURCHASE_PERIOD)
    enough_premium = pct is not None and pct >= BUY_NOW_MIN_PREMIUM_PERCENT
    fresh = not event.get("stale", False)

    if not official:
        reasons.append("公式 / 小売公式の情報ではない")
    if not purchasable:
        reasons.append(f"現在購入可能な状態ではない（{status or 'UNKNOWN'}）")
    if not enough_premium:
        reasons.append("プレミア率が閾値未満、または市場価格のサンプル不足")
    if not fresh:
        reasons.append("情報の鮮度切れ（TTL超過）")

    if event.get("purchase_limit"):
        notes.append(f"購入制限: {event['purchase_limit']}")
    if event.get("resale_restricted"):
        notes.append("販売規約で転売が禁止されています")
    if event.get("shrink_status") == SHRINK_UNKNOWN:
        notes.append("シュリンク状態は未確認です（BOX販売＝シュリンク付きとは限りません）")
    if event.get("store_specific_variation"):
        notes.append(f"店舗別条件: {event['store_specific_variation']}")

    ok = not reasons
    return {
        "buy_now": ok,
        "priority": PRIO_HIGH if ok else PRIO_LOW,
        "premium_percent": pct,
        "premium_yen": premium.get("premium_yen"),
        "blocked_reasons": reasons,
        "notes": notes,
    }


def notification_priority(event: dict, signals: int = 0) -> str:
    """Task14: 通知優先度。即売系は抽選より優先度を高くする。"""
    et = event.get("event_type", "")
    src = event.get("source_type", "")
    status = event.get("status", "")
    official = src in OFFICIAL_SOURCE_TYPES
    stale = event.get("stale", False)

    if stale:
        return PRIO_LOW
    if et in INSTANT_SALE_EVENTS:
        if official and status in (ST_AVAILABLE_NOW, ST_ENDING_SOON):
            return PRIO_CRITICAL
        if signals >= 1:
            return PRIO_HIGH          # 同一チェーン複数店舗で再販報告
        if event.get("confidence") == CONF_MEDIUM:
            return PRIO_MEDIUM        # 単一店舗SNS報告
        return PRIO_LOW               # 未確認情報
    if et == EVENT_LOTTERY and status in (ST_ENDING_SOON, ST_PURCHASE_PERIOD):
        return PRIO_HIGH
    if official:
        return PRIO_MEDIUM
    return PRIO_LOW

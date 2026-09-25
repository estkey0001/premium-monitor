# -*- coding: utf-8 -*-
"""Task13: 抽選締切アラート / Task14: 即売アラート / Task24-25: 通知文面。

安全方針:
  - 入荷時間を推測して断定しない（公式記載のある時刻だけ書く）。
  - 店舗への電話確認・長時間の待機・購入制限の回避方法は案内しない。
  - 未確認情報には必ず「在庫保証ではありません」を添える。
"""
from __future__ import annotations

from datetime import timedelta
from typing import Optional

from .models import (
    EVENT_LOTTERY, INSTANT_SALE_EVENTS, OFFICIAL_SOURCE_TYPES,
    PRIO_CRITICAL, PRIO_HIGH, PRIO_MEDIUM, PRIO_LOW,
    VERIFY_CONFIRMED, now_jst, parse_dt,
)
from .classify import scope_label
from .scoring import notification_priority

# Task13: 抽選のマイルストーン
LOTTERY_MILESTONES: tuple[tuple[str, str], ...] = (
    ("application_start", "応募開始"),
    ("application_end_24h", "応募終了24時間前"),
    ("application_end_3h", "応募終了3時間前"),
    ("result_date", "当選発表"),
    ("purchase_end_24h", "購入期限24時間前"),
)

# 通知に必ず添える注意書き
DISCLAIMER_UNVERIFIED = "※在庫を保証するものではありません"
DISCLAIMER_OFFICIAL = "※販売条件は必ず公式サイトでご確認ください"


def lottery_deadline_alerts(event: dict, now=None,
                            window: timedelta = timedelta(hours=1)) -> list[dict]:
    """抽選イベントから、今この時点で発火すべき締切アラートを返す。"""
    if event.get("event_type") != EVENT_LOTTERY:
        return []
    now = now or now_jst()
    a_start = parse_dt(event.get("application_start"))
    a_end = parse_dt(event.get("application_end"))
    result = parse_dt(event.get("result_date"))
    p_end = parse_dt(event.get("purchase_end"))

    candidates: list[tuple[str, str, Optional[object]]] = [
        ("application_start", "応募開始", a_start),
        ("application_end_24h", "応募終了24時間前",
         (a_end - timedelta(hours=24)) if a_end else None),
        ("application_end_3h", "応募終了3時間前",
         (a_end - timedelta(hours=3)) if a_end else None),
        ("result_date", "当選発表", result),
        ("purchase_end_24h", "購入期限24時間前",
         (p_end - timedelta(hours=24)) if p_end else None),
    ]

    out: list[dict] = []
    for key, label, at in candidates:
        if at is None:
            continue
        delta = at - now
        if timedelta(0) <= delta <= window:
            out.append({
                "milestone": key,
                "label": label,
                "fires_at": at.isoformat(),
                "product_name": event.get("product_name"),
                "tcg": event.get("tcg"),
                "store": event.get("store"),
                "source_url": event.get("source_url"),
                "priority": PRIO_HIGH,
                "message": f"{event.get('product_name', '')} {label}",
            })
    return out


def instant_sale_alerts(events: list[dict], signals: Optional[list[dict]] = None,
                        now=None) -> list[dict]:
    """Task14: 即売系（先着 / コンビニ / 再入荷 / EC復活 / ゲリラ）の通知候補。"""
    now = now or now_jst()
    signals = signals or []
    chains_with_signal = {s.get("chain") for s in signals}

    out: list[dict] = []
    for ev in events:
        if ev.get("event_type") not in INSTANT_SALE_EVENTS:
            continue
        if ev.get("stale"):
            continue   # 古い入荷報告を「今買える」として通知しない
        chain = (ev.get("store_chain") or ev.get("store") or "").upper()
        sig = 1 if chain in chains_with_signal else 0
        prio = notification_priority(ev, signals=sig)
        if prio == PRIO_LOW:
            continue
        out.append({
            "priority": prio,
            "tcg": ev.get("tcg"),
            "product_name": ev.get("product_name"),
            "store": ev.get("store"),
            "event_type": ev.get("event_type"),
            "status": ev.get("status"),
            "verification": ev.get("verification"),
            "source_url": ev.get("source_url"),
            "message": build_sale_message(ev, signal_count=sig),
        })
    order = {PRIO_CRITICAL: 0, PRIO_HIGH: 1, PRIO_MEDIUM: 2, PRIO_LOW: 3}
    return sorted(out, key=lambda a: order.get(a["priority"], 9))


def build_sale_message(event: dict, signal_count: int = 0) -> str:
    """Task24: 販売情報の通知文面を組み立てる。

    公式記載のある時刻のみ表示し、記載が無い場合は「時間未公表」と書く。
    """
    official = event.get("source_type") in OFFICIAL_SOURCE_TYPES
    head = "🔥 TCG販売情報" if official else "🚨 入荷報告"
    lines = [head, "", event.get("product_name", "") or "（商品名不明）"]

    store = event.get("store_chain") or event.get("store")
    if store:
        lines.append(str(store))

    et_label = {
        "FIRST_COME": "店頭先着", "CONVENIENCE_STORE": "コンビニ販売",
        "RESTOCK": "再入荷", "ONLINE_RESTOCK": "EC在庫復活",
        "GUERRILLA_SALE": "突発店頭販売", "LOTTERY": "抽選",
        "PREORDER": "予約", "GENERAL_SALE": "通常販売",
        "OFFICIAL_STORE": "公式ストア販売",
        "RESERVATION_REOPEN": "予約キャンセル分",
    }.get(event.get("event_type", ""), event.get("event_type", ""))
    lines.append(et_label)

    start = parse_dt(event.get("sale_start"))
    if start:
        lines.append(start.strftime("%-m/%-d %H:%M〜"))
    elif event.get("sale_start_time"):
        lines.append(str(event["sale_start_time"]))
    else:
        lines.append("販売時間: 未公表")   # 推測しない

    if event.get("purchase_limit"):
        lines.append(f"購入制限: {event['purchase_limit']}")

    shrink = event.get("shrink_status")
    if shrink and shrink != "UNKNOWN":
        lines.append(f"シュリンク: {shrink}")
    else:
        lines.append("シュリンク状態: 未確認")

    if event.get("verification") == VERIFY_CONFIRMED:
        lines.append("公式確認済み")
    else:
        lines.append(scope_label(event.get("source_type", ""),
                                 event.get("corroborations", 1),
                                 signal_count + 1))
    lines.append("")
    lines.append(DISCLAIMER_OFFICIAL if official else DISCLAIMER_UNVERIFIED)
    return "\n".join(lines)


def build_premium_message(event: dict) -> Optional[str]:
    """Task25: プレミアアラートの文面。サンプル不足なら None。"""
    prem = event.get("premium") or {}
    if prem.get("premium_percent") is None or prem.get("insufficient_samples"):
        return None
    retail = prem.get("retail_price")
    median = prem.get("market_median")
    lines = [
        "📈 TCG Premium Alert", "",
        f"商品: {event.get('product_name', '')}",
        f"定価: ¥{retail:,}" if retail else "定価: 不明",
        f"シュリンク市場中央値: ¥{median:,}" if median else "市場中央値: 不明",
        f"Premium: {prem['premium_percent']:+.1f}%"
        + (f" ({prem['premium_yen']:+,}円)" if prem.get("premium_yen") is not None else ""),
        f"Liquidity: {_liquidity_label(prem.get('sealed_sample_count', 0))}",
        f"現在購入可能: {'YES' if event.get('status') == 'AVAILABLE_NOW' else 'NO'}",
        "",
        DISCLAIMER_OFFICIAL,
    ]
    return "\n".join(lines)


def build_restock_signal_message(signal: dict) -> str:
    """地域入荷シグナルの通知文面（確定情報として書かない）。"""
    prefs = "・".join(signal.get("prefectures", [])[:5])
    return "\n".join([
        "🚨 BOX再販報告", "",
        signal.get("label", ""),
        f"対象地域: {prefs}" if prefs else "",
        f"{signal.get('window_minutes', 0)}分以内: {signal.get('report_count', 0)}件",
        "Confidence: MEDIUM",
        "",
        DISCLAIMER_UNVERIFIED,
    ])


def _liquidity_label(sample_count: int) -> str:
    if sample_count >= 10:
        return "HIGH"
    if sample_count >= 5:
        return "MEDIUM"
    if sample_count >= 1:
        return "LOW"
    return "UNKNOWN"

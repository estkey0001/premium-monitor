# -*- coding: utf-8 -*-
"""Task21: 重複イベントの排除 / Task20: 下位 source が上位 source を上書きしない。"""
from __future__ import annotations

from typing import Iterable

from .models import SOURCE_PRIORITY, parse_dt
from .sources import is_higher_priority

_CONF_RANK = {"high": 0, "medium": 1, "low": 2}


def event_key(ev: dict) -> tuple:
    """同一販売情報の判定キー（tcg / product / store / event_type / sale_date）。"""
    day = ""
    dt = parse_dt(ev.get("sale_start") or ev.get("application_start")
                  or ev.get("release_date"))
    if dt:
        day = dt.date().isoformat()
    return (ev.get("tcg", ""), ev.get("product_id", ""),
            (ev.get("store") or "").upper(), ev.get("event_type", ""), day)


def _better(a: dict, b: dict) -> dict:
    """同一キーの2件からどちらを残すか決める。

    1. source 優先度（上位が勝つ = 下位は上位を上書きしない）
    2. confidence
    3. 観測時刻が新しい方
    """
    pa = SOURCE_PRIORITY.get(a.get("source_type", ""), 99)
    pb = SOURCE_PRIORITY.get(b.get("source_type", ""), 99)
    if pa != pb:
        return a if pa < pb else b
    ca = _CONF_RANK.get(a.get("confidence", "low"), 9)
    cb = _CONF_RANK.get(b.get("confidence", "low"), 9)
    if ca != cb:
        return a if ca < cb else b
    da = parse_dt(a.get("observed_at")) or parse_dt("1970-01-01T00:00:00")
    db = parse_dt(b.get("observed_at")) or parse_dt("1970-01-01T00:00:00")
    return a if da >= db else b


def dedupe_events(events: Iterable[dict]) -> list[dict]:
    """重複イベントを1件に統合する。統合件数を merged_count に記録。"""
    kept: dict[tuple, dict] = {}
    for ev in events:
        k = event_key(ev)
        if k not in kept:
            ev = dict(ev)
            ev.setdefault("merged_count", 1)
            ev.setdefault("corroborations", ev.get("corroborations", 1))
            kept[k] = ev
            continue
        cur = kept[k]
        win = _better(cur, ev)
        win = dict(win)
        win["merged_count"] = cur.get("merged_count", 1) + 1
        # 別ソースからの裏付けとして corroborations を加算する。
        # 投入順で結果が変わらないよう、両者の大きい方を基準にする。
        base = max(cur.get("corroborations", 1), ev.get("corroborations", 1))
        differs = (cur.get("source_url") or "") != (ev.get("source_url") or "")
        win["corroborations"] = base + (1 if differs else 0)
        kept[k] = win
    return list(kept.values())


def can_override(existing_source_type: str, new_source_type: str) -> bool:
    """Task20: new が existing を上書きしてよいか（同位以上のみ可）。"""
    if existing_source_type == new_source_type:
        return True
    return is_higher_priority(new_source_type, existing_source_type)

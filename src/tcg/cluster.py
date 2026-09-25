# -*- coding: utf-8 -*-
"""Task7: 地域クラスタリング（チェーン横断の入荷シグナル検出）。

同一チェーンについて短時間に複数地域から入荷報告が出た場合に
possible_chainwide_restock / <REGION>_RESTOCK_SIGNAL を検出する。
ただしこれは事実確定ではなく signal として扱う。
"""
from __future__ import annotations

from collections import defaultdict
from datetime import timedelta

from .models import now_jst, parse_dt, INSTANT_SALE_EVENTS
from .region import region_of, REGION_LABELS

# 短時間ウィンドウ
CLUSTER_WINDOW = timedelta(minutes=60)
# 同一地域内シグナルに必要な最小報告数（異なる都道府県）
MIN_PREFECTURES_FOR_REGION_SIGNAL = 2
MIN_REPORTS_FOR_REGION_SIGNAL = 3
# チェーン全体シグナルに必要な地方ブロック数
MIN_REGIONS_FOR_CHAINWIDE = 3


def detect_restock_signals(events: list[dict], now=None,
                           window: timedelta = CLUSTER_WINDOW) -> list[dict]:
    """入荷報告から地域シグナルを検出する。

    戻り値は signal の一覧（確定情報ではない）。
    """
    now = now or now_jst()
    recent: list[dict] = []
    for ev in events:
        if ev.get("event_type") not in INSTANT_SALE_EVENTS:
            continue
        ts = parse_dt(ev.get("reported_at") or ev.get("observed_at"))
        if ts is None or (now - ts) > window:
            continue
        recent.append(ev)

    by_chain: dict[str, list[dict]] = defaultdict(list)
    for ev in recent:
        chain = (ev.get("store_chain") or ev.get("store") or "").upper()
        if chain:
            by_chain[chain].append(ev)

    signals: list[dict] = []
    for chain, evs in by_chain.items():
        by_region: dict[str, list[dict]] = defaultdict(list)
        for ev in evs:
            reg = region_of(ev.get("prefecture"))
            if reg:
                by_region[reg].append(ev)

        for reg, revs in by_region.items():
            prefs = {e.get("prefecture") for e in revs if e.get("prefecture")}
            if (len(prefs) >= MIN_PREFECTURES_FOR_REGION_SIGNAL
                    and len(revs) >= MIN_REPORTS_FOR_REGION_SIGNAL):
                signals.append({
                    "signal": f"{reg}_RESTOCK_SIGNAL",
                    "signal_type": "region_restock",
                    "label": f"{REGION_LABELS.get(reg, reg)}で{chain}の入荷報告が集中",
                    "chain": chain,
                    "region": reg,
                    "prefectures": sorted(p for p in prefs if p),
                    "report_count": len(revs),
                    "window_minutes": int(window.total_seconds() // 60),
                    "confirmed": False,
                    "note": "複数報告から推定したシグナルです。在庫を保証するものではありません。",
                    "detected_at": now.isoformat(),
                })

        if len(by_region) >= MIN_REGIONS_FOR_CHAINWIDE:
            signals.append({
                "signal": "possible_chainwide_restock",
                "signal_type": "chainwide_restock",
                "label": f"{chain} で全国的な入荷の可能性",
                "chain": chain,
                "region": None,
                "regions": sorted(by_region.keys()),
                "report_count": len(evs),
                "window_minutes": int(window.total_seconds() // 60),
                "confirmed": False,
                "note": "複数地域の報告から推定したシグナルです。全国販売の確定情報ではありません。",
                "detected_at": now.isoformat(),
            })
    return signals

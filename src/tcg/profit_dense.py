"""TCG の利益が出やすいイベントの優先度・定価との結び付き・検知の間隔のシミュレーション（Coverage Wave 5 Stage L / N / O / Q）。

- 優先度（L）: 受付中の抽選・予約・再販・期限が近い・限定（公式の商品名にその語がある）・発売直後（公式の発売日）を優先する。
  点は並べ替えにだけ使う（`src/research/signals.py` の決まった点）。**価格の予測・利益の計算はしない**
- 質（N）: イベントごとに 商品・小売・応募開始・応募終了・当選発表・購入期間・公式 URL の 7 項目がどれだけ揃うか。
  7 項目すべて揃わないイベントは actionable にしない（`actionable_event` = False）
- 定価との結び付き（O）: イベントの product_id が、定価の台帳（公式 API で商品 1 個の希望小売価格が明示されたもの）にあるときだけ結ぶ。
  名前の近さでは結ばない。利益の計算はしない
- 検知の間隔のシミュレーション（Q）: 実際の応募の期間（開始・終了が読めるイベント）に対して、24 / 12 / 6 / 3 時間ごとに見に行く場合の、
  応募の期間中に一度も見つけられない割合と、応募の半分以上を失ってから見つける割合を数える。**実装はしない（数えるだけ）**

個別のイベントは非公開（.private）。公開してよいのは件数だけ。
"""
from __future__ import annotations

from datetime import datetime

from src.research import signals as sg
from src.tcg import event_quality as eq

ACTIVE = eq.ACTIVE_STATUSES
COMPLETENESS_FIELDS = ("product", "retailer", "application_start", "application_end", "winner_announcement", "purchase_window", "official_url")
HIGH_DENSITY_POINTS = 12
SIM_INTERVALS = (24, 12, 6, 3)
SIM_PHASES = 12                       # 見に行く時刻の位相（間隔を 12 等分した開始位置）。偏らないように全位相で数える
# 定時の実行が、応募の開始から実際にイベントを観測するまでに必ずかかる遅れ（時間）。Wave 4 の実測: 定時の開始の遅れ 最大 6.4 時間
# + 実行の所要（TCG の取得まで）約 2 時間。間隔を短くしても、この遅れは縮まらない（実装で縮められるのは間隔だけ）
PIPELINE_LATENCY_HOURS = 8.4


def _msrp_index(msrp: dict | None) -> dict:
    rows = (msrp or {}).get("verified") or []
    return {str(r.get("product_id")): r for r in rows if isinstance(r, dict) and r.get("product_id")}


def completeness(i: dict, now: datetime) -> dict:
    st, _ = eq._pick(i, "application_start", "application_start_date", now)
    en, _ = eq._pick(i, "application_end", "application_end_date", now, end_of_day=True)
    flags = {
        "product": bool(i.get("product_id")) and str(i.get("product_match") or "") == "exact" and not i.get("provisional_product"),
        "retailer": bool(i.get("retailer")),
        "application_start": st is not None, "application_end": en is not None,
        "winner_announcement": bool(i.get("winner_announcement_at") or i.get("winner_announcement_date")),
        "purchase_window": bool((i.get("purchase_start") or i.get("purchase_start_date")) and (i.get("purchase_end") or i.get("purchase_end_date"))),
        "official_url": bool(i.get("entry_url") or i.get("purchase_url")),
    }
    n = sum(flags.values())
    return {"completeness": n, "missing": [k for k in COMPLETENESS_FIELDS if not flags[k]], "actionable_event": n == len(COMPLETENESS_FIELDS)}


def evaluate(items: list[dict], msrp: dict | None, now: datetime) -> dict:
    """{"counts": 公開してよい件数, "events": 非公開の個別の行}。入力が壊れていても例外にしない。"""
    items = [i for i in (items or []) if isinstance(i, dict)]
    idx = _msrp_index(msrp)
    rows, counts = [], {"active_tcg_priority": 0, "tcg_new_release": 0, "tcg_limited": 0, "tcg_supply_pressure": 0,
                        "tcg_msrp_linked_active": 0, "tcg_actionable_events": 0, "tcg_incomplete_active": 0,
                        "tcg_stock_unknown_not_counted": 0}
    for i in items:
        status = str(i.get("status") or "")
        if status not in ACTIVE:
            continue
        _end, _ = eq._pick(i, "application_end", "application_end_date", now, end_of_day=True)
        if _end is not None and _end < now:
            continue                                        # 状態の文字列が受付中でも、応募の終了が過ぎたイベントは対象にしない
        pid = str(i.get("product_id") or "")
        m = idx.get(pid) if pid and str(i.get("product_match") or "") == "exact" else None
        rel = sg.release_signal((m or {}).get("release_date"), now)
        lim = sg.limited_signal(official_name=(m or {}).get("name", ""), official_url=(m or {}).get("official_url", ""),
                                official=bool(m and m.get("source") == "official_product_api"))
        st, _ = eq._pick(i, "application_start", "application_start_date", now)
        en, _ = eq._pick(i, "application_end", "application_end_date", now, end_of_day=True)
        hours = eq._hours(st, en)
        etype = str(i.get("event_type") or "")
        sup = sg.supply_signals(event_type=etype, application_hours=hours, lottery_active=(etype == "LOTTERY" and status in ("OPEN", "ENDING_SOON")))
        prio = eq.priority_of(i, now)
        d = sg.profit_density(release=rel, limited=lim, supply=sup)
        pts = d["signal_points"] + (sg.POINTS["tcg_active"] if prio in (eq.P_ACTIVE_LOTTERY, eq.P_PREORDER_OPEN, eq.P_RESTOCK) else 0) \
            + (sg.POINTS["tcg_deadline"] if prio == eq.P_DEADLINE_SOON else 0)
        c = completeness(i, now)
        rows.append({"retailer": str(i.get("retailer") or ""), "status": status, "priority": prio, "signal_points": pts,
                     "release": rel, "limited": lim, "supply_signals": sup, "msrp_linked": m is not None,
                     "msrp_price": (m or {}).get("retail_price"), **c})
        # 高密度 = 受付中であることに加え、需要か逼迫の根拠がある（発売直後・限定・短い応募期間・再販・期限が近い・定価に結べた）。
        # 「抽選が開いている」だけ（二重の加点）では数えない
        dense = (rel["release_state"] in (sg.REL_NEW, sg.REL_RECENT) or lim["limited"] or m is not None
                 or sg.SUP_SHORT_WINDOW in sup or sg.SUP_RESTOCK in sup or prio == eq.P_DEADLINE_SOON)
        counts["active_tcg_priority"] += int(dense and pts >= HIGH_DENSITY_POINTS)
        counts["tcg_new_release"] += int(rel["release_state"] == sg.REL_NEW)
        counts["tcg_limited"] += int(lim["limited"])
        counts["tcg_supply_pressure"] += int(bool(sup))
        counts["tcg_msrp_linked_active"] += int(m is not None)
        counts["tcg_actionable_events"] += int(c["actionable_event"])
        counts["tcg_incomplete_active"] += int(not c["actionable_event"])
    rows.sort(key=lambda r: (-r["signal_points"], r["priority"], r["retailer"]))
    return {"counts": counts, "events": rows}


def simulate_detection(items: list[dict], now: datetime, latency_hours: float = PIPELINE_LATENCY_HOURS) -> dict:
    """N 時間ごとに見に行く場合の取りこぼしの数（応募の開始・終了が読めるイベントだけ。実装ではなく計算）。

    イベントごとに、見に行く時刻の位相を SIM_PHASES 通り試し、
    missed = 応募の期間中に一度も見に行かない割合、lost_half = 初めて見つけたのが応募の半分を過ぎてからの割合（見つけられなかった分も含む）の合計。
    最初の観測までの待ち時間は 定時の実行の遅れ（latency_hours。最悪の実測）+ 見に行く間隔の位相（0 以上 h 未満）。
    日付だけのイベントは開始 = 0:00・終了 = 23:59:59 とする（時刻の精度があるように見せない）。
    """
    windows = []
    for i in items or []:
        if not isinstance(i, dict):
            continue
        st, _ = eq._pick(i, "application_start", "application_start_date", now)
        en, _ = eq._pick(i, "application_end", "application_end_date", now, end_of_day=True)
        if st is not None and en is not None and en > st:
            windows.append((en - st).total_seconds() / 3600)
    out: dict = {"events_measured": len(windows), "latency_hours": round(float(latency_hours), 1)}
    for h in SIM_INTERVALS:
        missed = lost = 0.0
        for dur in windows:
            for k in range(SIM_PHASES):
                # 応募の開始から見て、最初の観測までの待ち時間（0 以上 h 未満）。位相 k を等間隔に取る
                wait = latency_hours + h * k / SIM_PHASES
                if wait >= dur:
                    missed += 1 / SIM_PHASES
                    lost += 1 / SIM_PHASES
                elif wait > dur * 0.5:
                    lost += 1 / SIM_PHASES
        out[f"h{h}_missed"] = round(missed, 1)
        out[f"h{h}_lost_half"] = round(lost, 1)
    return out

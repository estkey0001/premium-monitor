"""TCG の抽選・予約イベントの質・優先順位・検知の遅れの許容（Coverage Wave 3 Stage Q / R / S）。

- 質（Q）: 受付中のイベントについて、応募開始・応募終了・当選発表・購入期間・行動の URL がどれだけ埋まっているか（件数。取得元別も）
- 優先順位（R）: 受付中の抽選 / 期限が近い / 予約受付中 / 先着 / 再販 / これから始まる、の順（決まった規則。予測は使わない）
- 検知の遅れの許容（S）: イベントごとの「応募の長さ・観測時点の経過時間・観測時点の残り時間」。**高速化はまだ実装しない**。
  今のイベントから、どれくらいの間隔で見に行けば応募の半分の期間が残っているうちに見つけられるかの目安を出す。
  **初めて見た時刻（first_seen）は実行をまたいで保持していない**（台帳の鍵なし）ので、本当の検知の遅れは測れない。ここで出すのは
  「告知の公開日から、この実行が観測した時刻までの経過」（age_at_observation）で、毎日観測し直すため検知の遅れの上限ではなく目安にすぎない

日付だけの値（応募期間が日付で書かれている告知）は、開始 = その日の 0:00、終了 = その日の 23:59:59 として扱い、precision="date" と明示する
（時刻の精度があるように見せない）。個別のイベント（商品名・日程）は非公開に置き、公開してよいのは件数・時間の中央値だけ。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

ACTIVE_STATUSES = frozenset({"OPEN", "ENDING_SOON", "UPCOMING"})
P_DEADLINE_SOON, P_ACTIVE_LOTTERY, P_PREORDER_OPEN, P_FIRST_COME, P_RESTOCK, P_UPCOMING = (
    "DEADLINE_SOON", "ACTIVE_LOTTERY", "PREORDER_OPEN", "FIRST_COME", "RESTOCK", "UPCOMING")
PRIORITIES = (P_DEADLINE_SOON, P_ACTIVE_LOTTERY, P_PREORDER_OPEN, P_FIRST_COME, P_RESTOCK, P_UPCOMING)
_PRIORITY_ORDER = {p: i for i, p in enumerate(PRIORITIES)}
DEADLINE_SOON_HOURS = 24
HALF_WINDOW = 0.5            # 応募の長さのこの割合が残っているうちに検知したい（目安）


def _parse(v, now: datetime, *, end_of_day: bool = False):
    s = str(v or "").strip()
    if not s:
        return None, ""
    precision = "datetime" if ("T" in s or ":" in s) else "date"
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None, ""
    if precision == "date" and end_of_day:
        d = d.replace(hour=23, minute=59, second=59)
    if d.tzinfo is None and now.tzinfo is not None:
        d = d.replace(tzinfo=now.tzinfo)
    elif d.tzinfo is not None and now.tzinfo is None:
        d = d.replace(tzinfo=None)
    return d, precision


def _pick(i: dict, dt_key: str, date_key: str, now: datetime, *, end_of_day: bool = False):
    d, p = _parse(i.get(dt_key), now, end_of_day=end_of_day)
    if d is not None:
        return d, p
    return _parse(i.get(date_key), now, end_of_day=end_of_day)


def _hours(a, b):
    return None if a is None or b is None else round((b - a).total_seconds() / 3600, 1)


def priority_of(i: dict, now: datetime) -> str:
    """受付中のイベントの優先順位（決まった規則）。"""
    status, etype = str(i.get("status") or ""), str(i.get("event_type") or "")
    end, _p = _pick(i, "application_end", "application_end_date", now, end_of_day=True)
    if status == "UPCOMING":
        return P_UPCOMING
    if status == "ENDING_SOON" or (end is not None and timedelta(0) <= end - now <= timedelta(hours=DEADLINE_SOON_HOURS)):
        return P_DEADLINE_SOON
    if etype == "PREORDER":
        return P_PREORDER_OPEN
    if etype == "FIRST_COME":
        return P_FIRST_COME
    if etype == "RESTOCK":
        return P_RESTOCK
    return P_ACTIVE_LOTTERY


def evaluate(items: list[dict], now: datetime) -> dict:
    """{"quality": 件数, "priority": 件数, "fast_lane": 件数・中央値, "events": 非公開の個別の行}。入力が壊れていても例外にしない。"""
    items = [i for i in (items or []) if isinstance(i, dict)]
    active = [i for i in items if str(i.get("status") or "") in ACTIVE_STATUSES]
    q = {"active_events": len(active), "with_application_start": 0, "with_application_end": 0, "with_winner_announcement": 0,
         "with_purchase_window": 0, "with_action_url": 0, "fully_dated": 0}
    by_source: dict[str, dict] = {}
    prio = {p: 0 for p in PRIORITIES}
    for i in active:
        st, _ = _pick(i, "application_start", "application_start_date", now)
        en, _ = _pick(i, "application_end", "application_end_date", now, end_of_day=True)
        win = i.get("winner_announcement_at") or i.get("winner_announcement_date")
        pw = bool((i.get("purchase_start") or i.get("purchase_start_date")) and (i.get("purchase_end") or i.get("purchase_end_date")))
        url = bool(i.get("entry_url") or i.get("purchase_url"))
        flags = {"with_application_start": st is not None, "with_application_end": en is not None,
                 "with_winner_announcement": bool(win), "with_purchase_window": pw, "with_action_url": url}
        for k, v in flags.items():
            q[k] += int(v)
        full = all(flags[k] for k in ("with_application_start", "with_application_end", "with_winner_announcement", "with_purchase_window"))
        q["fully_dated"] += int(full)
        sid = str(i.get("retailer") or "UNKNOWN")
        b = by_source.setdefault(sid, {"active_events": 0, **{k: 0 for k in flags}})
        b["active_events"] += 1
        for k, v in flags.items():
            b[k] += int(v)
        prio[priority_of(i, now)] += 1
    # 検知の遅れの許容（開始と終了が読めるイベントすべて。受付中だけだと少なすぎる）
    rows, durations, delays, under24, late_half = [], [], [], 0, 0
    for i in items:
        st, ps = _pick(i, "application_start", "application_start_date", now)
        en, pe = _pick(i, "application_end", "application_end_date", now, end_of_day=True)
        if st is None or en is None or en <= st:
            continue
        obs, _ = _parse(i.get("observed_at"), now)
        anchor, _ = _parse(i.get("published_at"), now)
        anchor = anchor or st                                   # 告知の公開日が無ければ応募開始を基準にする
        dur = _hours(st, en)
        delay = _hours(anchor, obs)
        remaining_at_observation = _hours(obs, en) if obs is not None else None
        precision = "datetime" if (ps == "datetime" and pe == "datetime") else "date"
        durations.append(dur)
        if delay is not None:
            delays.append(max(delay, 0.0))
        if remaining_at_observation is not None:
            under24 += int(remaining_at_observation < 24)
            late_half += int(remaining_at_observation < dur * HALF_WINDOW)
        rows.append({"source": str(i.get("retailer") or ""), "status": str(i.get("status") or ""), "precision": precision,
                     "application_duration_hours": dur, "age_at_observation_hours": delay,
                     "remaining_at_observation_hours": remaining_at_observation,
                     "remaining_now_hours": _hours(now, en),
                     "tolerated_age_at_observation_hours": round(dur * HALF_WINDOW, 1),
                     "priority": priority_of(i, now) if str(i.get("status") or "") in ACTIVE_STATUSES else ""})
    tol = sorted(r["tolerated_age_at_observation_hours"] for r in rows)
    p25 = tol[len(tol) // 4] if tol else None
    fast = {"events_measured": len(rows),
            "median_application_duration_hours": round(median(durations), 1) if durations else None,
            "median_age_at_observation_hours": round(median(delays), 1) if delays else None,
            "windows_under_24h_at_observation": under24, "observed_after_half_window": late_half,
            "tolerated_age_at_observation_hours_p25": p25,
            # 応募の長さの 4 分位の下側の半分より短い間隔で見に行けば、多くのイベントを半分以上残っているうちに見つけられる目安
            "suggested_max_detection_interval_hours": (max(1, int(p25)) if p25 is not None else None),
            "date_precision_events": sum(1 for r in rows if r["precision"] == "date")}
    rows.sort(key=lambda r: (_PRIORITY_ORDER.get(r["priority"], 99), r.get("remaining_now_hours") if r.get("remaining_now_hours") is not None else 10**9))
    return {"first_seen_available": False, "quality": q, "quality_by_source": by_source, "priority": prio, "fast_lane": fast, "events": rows}

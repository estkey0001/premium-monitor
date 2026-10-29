# -*- coding: utf-8 -*-
"""TCG イベントの「初めて見た時刻（first_seen）」と、実際の検知の遅れの測定（Coverage Wave 6 Stage F）。

first_seen は、**実行をまたいで台帳を引き継げたとき**（RESTORED_FROM_PREVIOUS_RUN）にだけ意味を持つ。台帳が無い日・初回は、
この run で初めて見えたものが全部「今日」になってしまうので、測定の対象にしない（UNKNOWN）。台帳を使い始めた最初の run に
既にあったイベントは、いつから公開されていたか分からないので baseline とし、測定の対象にしない。

測定できるのは、台帳を使い始めた**後に**初めて現れたイベントだけ。そのうえで、
- 遅れ（detection_delay_hours）= first_seen − 情報元の公開日時（source_published_at）。公開日時が無ければ UNKNOWN（推測しない）
- 応募の開始前に見つけたか（detected_before_start）、応募の期間のうち見つけた時点で残っていた割合（remaining_fraction）
first_seen の時刻の精度は「その run の時刻」（定時の実行の間隔）。実際の公開より前には戻れない（遅れは 0 以上に丸めず、負なら UNKNOWN）。

個別のイベントは非公開（.private）。公開してよいのは件数と遅れの中央値・最大だけ。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

from src.tcg import event_quality as eq

RETENTION_DAYS = 60
SOURCE_GAP_HOURS = 36            # その取得元（小売）が、前回の台帳でこの時間以内に見えていなければ、復旧日の「新規」は測らない（取得できていなかっただけ）
MIN_SAMPLES_FOR_VALUES = 3       # 遅れの中央値・最大を公開するのは、測れたイベントがこの件数以上のとき（1 件だけだと個別の値になる）


def event_key(i: dict) -> str:
    """イベントの安定した識別子（lottery_id。無ければ 小売 + 種別 + 情報元 URL）。"""
    lid = str(i.get("lottery_id") or "")
    if lid:
        return lid
    # lottery_id が無いとき: 商品名は微修正されうるので、情報元の URL があればそれで決める（名前の修正で別イベントにしない）
    if i.get("source_url"):
        return "|".join(str(i.get(k) or "") for k in ("retailer", "event_type", "source_url"))[:300]
    return "|".join(str(i.get(k) or "") for k in ("retailer", "event_type", "product_name"))[:300]


def _date_only(value) -> bool:
    """時刻の無い日付（YYYY-MM-DD）。時刻の精度が無いので、公開日時としては使わない（遅れが最大約 24 時間ぶれる）。"""
    s = str(value or "").strip()
    return bool(s) and "T" not in s and ":" not in s


def _ts(value, now: datetime):
    s = str(value or "").strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace(" JST", ""))
    except ValueError:
        return None
    if d.tzinfo is None and now.tzinfo is not None:
        return d.replace(tzinfo=now.tzinfo)
    if d.tzinfo is not None and now.tzinfo is None:
        return d.replace(tzinfo=None)
    return d


def sanitize(prev) -> dict:
    """前回の first_seen の台帳を検証する（壊れていたら空 = 比べられない）。"""
    if not isinstance(prev, dict) or not isinstance(prev.get("events"), dict) or not isinstance(prev.get("started_at"), str):
        return {}
    ev = {str(k): v for k, v in prev["events"].items()
          if isinstance(v, dict) and isinstance(v.get("first_seen"), str) and isinstance(v.get("last_seen"), str)}

    def _m(x):
        return {str(k): v for k, v in x.items() if isinstance(v, str)} if isinstance(x, dict) else {}
    return {"started_at": prev["started_at"], "events": ev, "sources": _m(prev.get("sources")), "sources_base": _m(prev.get("sources_base")),
            "run_id": str(prev.get("run_id") or ""), "trusted": prev.get("trusted") is True}


def update(items: list[dict], prev, *, comparable: bool, now: datetime, run_id: str = "",
           healthy_sources: set | None = None) -> tuple[dict, dict, list[dict]]:
    """(新しい台帳, 公開してよい件数, 非公開の個別の行)。comparable=False（前回の台帳を使えない）なら引き継がず、測定もしない。

    comparable は「前回の台帳を使ってよい」: 前回の run から引き継げたとき、または同じ run の中の再生成が最初の生成の台帳を読んだとき
    （後者は、前回の run までの first_seen を既に含んでいる。ここで捨てると across-runs の記録が消える）。
    測定してよいのは trusted（前回の run から引き継いだ台帳の上に作った）ときだけ。同じ run の再生成は、最初の生成の trusted を引き継ぐ
    （最初の生成が引き継げていなければ、再生成も測らない）。run_id: この run の識別子。
    - 同じイベントは、台帳を使い始めた後に初めて見えた run（measured_run）だけで測る。翌日の run で、また数えない（同じ run の再生成は数える）
    - その取得元が前回の台帳で見えていたか（sources）は、同じ run の再生成では、最初の生成が引き継いだ時点の値（sources_base）で判定する
    - sources の更新: 今回正常に取得できた取得元（healthy_sources）と、受付中のイベントがある取得元
    """
    stamp = now.isoformat(timespec="seconds")
    p = sanitize(prev) if comparable else {}
    same_run = bool(p) and bool(run_id) and p.get("run_id") == run_id
    trusted = bool(p) and (p.get("trusted") is True if same_run else True)
    started = p.get("started_at") or stamp
    old = p.get("events") or {}
    cutoff = now - timedelta(days=RETENTION_DAYS)
    prev_sources = (p.get("sources_base") if same_run else p.get("sources")) or {}
    sources: dict = {k: v for k, v in (p.get("sources") or {}).items() if (_ts(v, now) or cutoff) >= cutoff}
    events: dict = {}
    for k, v in old.items():                                       # 今回見えなかったイベントも、期間内は引き継ぐ（再び現れても first_seen を変えない）
        last = _ts(v.get("last_seen"), now)
        if last is not None and last >= cutoff:
            events[k] = dict(v)
    rows: list[dict] = []
    counts = {"events_active": 0, "baseline_events": 0, "new_after_baseline": 0, "measured": 0, "unknown_published_at": 0,
              "detected_before_start": 0, "source_gap_excluded": 0}
    delays: list[float] = []
    for i in items or []:
        if not isinstance(i, dict) or str(i.get("status") or "") not in eq.ACTIVE_STATUSES:
            continue
        k = event_key(i)
        counts["events_active"] += 1
        seen = events.get(k)
        obs = _ts(i.get("observed_at"), now)                         # 収集した時刻（LP の生成時刻より正確）。読めない・未来なら今
        obs_stamp = obs.isoformat(timespec="seconds") if obs is not None and obs <= now else stamp
        retailer = str(i.get("retailer") or "")
        if seen is None:
            seen = events[k] = {"first_seen": obs_stamp, "last_seen": stamp, "retailer": retailer}
        else:
            seen["last_seen"] = stamp
        first = seen["first_seen"]
        fs = _ts(first, now)
        # 台帳を使い始めた後に初めて現れた（使い始めと同時に見えていたものは baseline）
        is_new = trusted and fs is not None and fs > (_ts(started, now) or now)
        row = {"first_seen": first, "measurable": False, "detection_delay_hours": None,
               "detected_before_start": None, "remaining_fraction": None}
        if not is_new:
            counts["baseline_events"] += 1 if trusted else 0
            rows.append(row)
            continue
        counts["new_after_baseline"] += 1
        mr = seen.get("measured_run")
        if mr is not None and mr != run_id:
            rows.append(row)                                           # 前の run で既に測った（または除外した）イベントは、また数えない
            continue
        seen["measured_run"] = run_id
        last_src = _ts(prev_sources.get(retailer), now) if retailer else None
        if last_src is None or now - last_src > timedelta(hours=SOURCE_GAP_HOURS):
            counts["source_gap_excluded"] += 1                         # 前回その取得元が見えていない（停止・ブロック・ID の変更）。復旧日の「新規」は遅れとして測らない
            rows.append(row)
            continue
        pub = _ts(i.get("published_at"), now)
        st, _ = eq._pick(i, "application_start", "application_start_date", now)
        en, _ = eq._pick(i, "application_end", "application_end_date", now, end_of_day=True)
        if pub is None or _date_only(i.get("published_at")) or fs < pub:
            counts["unknown_published_at"] += 1                      # 公開日時が無い・矛盾する → 推測しない
            rows.append(row)
            continue
        d = round((fs - pub).total_seconds() / 3600, 1)
        row.update({"measurable": True, "detection_delay_hours": d})
        if st is not None:
            row["detected_before_start"] = fs <= st
            counts["detected_before_start"] += int(fs <= st)
        if st is not None and en is not None and en > st:
            row["remaining_fraction"] = round(max(0.0, min(1.0, (en - max(fs, st)).total_seconds() / (en - st).total_seconds())), 2)
        counts["measured"] += 1
        delays.append(d)
        rows.append(row)
    # 件数が少ないと中央値・最大が個別のイベントの値そのものになるので、公開しない（0 = 公開しない。測れた件数は measured に出る）
    enough = len(delays) >= MIN_SAMPLES_FOR_VALUES
    counts["median_delay_hours"] = round(median(delays), 1) if enough else 0
    counts["max_delay_hours"] = round(max(delays), 1) if enough else 0
    counts["delay_values_withheld"] = int(bool(delays) and not enough)
    counts["comparable"] = int(trusted)
    # 今回見えた取得元を記録する（次回の「取得元が見えていたか」の根拠）: 正常に取得できた取得元と、受付中のイベントがある取得元
    for r in (healthy_sources or ()):
        sources[str(r)] = stamp
    for i in items or []:
        if isinstance(i, dict) and i.get("retailer") and str(i.get("status") or "") in eq.ACTIVE_STATUSES:
            sources[str(i["retailer"])] = stamp
    return ({"started_at": started, "events": events, "sources": sources, "sources_base": dict(prev_sources), "run_id": run_id,
             "trusted": trusted}, counts, rows)

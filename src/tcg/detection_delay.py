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

指標の定義（読み手へ）: 測れるのは「その取得元を前回観測した**後**に公開され、今回初めて見えたイベント」だけ。前回の観測より前に公開されていた
イベント（数日遅れて見つけたもの・鍵の変化・日程の補完で受付中になったもの）は、同じイベントを新規と誤って測る恐れがあるので測らない
（previously_observable_excluded に件数だけ出す）。つまり遅れの中央値・最大は、**実行間隔以内に見つけた新規だけ**の値で、
実際の検知力より良く（小さく）出る。取りこぼしの規模は previously_observable_excluded と identity_ambiguous の件数で見る。
公開日時が日付だけ（00:00:00 を含む）のものは UNKNOWN。URL が無い・一般的なイベント、手動の確認済みイベントは測らない。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from statistics import median

from src.tcg import event_quality as eq

RETENTION_DAYS = 60
SOURCE_GAP_HOURS = 36            # その取得元（小売）が、前回の台帳でこの時間以内に見えていなければ、復旧日の「新規」は測らない（取得できていなかっただけ）
EVENT_KEY_VERSION = 4                  # event_key の規則の版。台帳の版が違えば（旧鍵の台帳）引き継がない: 新しい鍵で同じイベントが「新規」に見え、遅れを偽って測るため
INPUT_MAX_AGE_HOURS = 6          # 入力（exports/tcg の生成物）がこの時間より古いと、今回の観測として扱わない（収集が失敗して前回の生成物が残った日）
MIN_SAMPLES_FOR_VALUES = 3       # 遅れの中央値・最大を公開するのは、測れたイベントがこの件数以上のとき（1 件だけだと個別の値になる）


_GENERIC_SEGMENTS = {"news", "info", "blog", "shop", "lottery", "event", "events", "topics", "category", "search", "list", "index",
                     "index.html", "tag", "archive", "campaign", "information", "notice", "release"}
_ID_PARAMS = {"id", "p", "no", "post", "pid", "cid", "event", "entry", "article", "item", "lottery_id", "news_id"}
_NOISE_PARAMS = ("utm_", "fbclid", "gclid", "ref", "from")


def specific_url(url) -> str:
    """出来事ごとに固有の情報元 URL（正規化したもの）。店の入口・お知らせ一覧・検索・カテゴリなどの一般的な URL は空文字（識別に使わない）。
    固有とみなすのは、(a) id らしいクエリ（数字を含む）がある、(b) 最後のパスに数字がある（記事番号など）、のどちらか。"""
    from urllib.parse import parse_qsl, urlsplit
    try:
        sp = urlsplit(str(url or "").strip())
    except ValueError:
        return ""
    if sp.scheme not in ("http", "https") or not sp.netloc:
        return ""
    segs = [x for x in sp.path.split("/") if x]
    q = [(k.lower(), v) for k, v in parse_qsl(sp.query, keep_blank_values=False) if not k.lower().startswith(_NOISE_PARAMS)]
    has_id = any(k in _ID_PARAMS and any(c.isdigit() for c in v) for k, v in q)
    last = segs[-1] if segs else ""
    if not has_id and (not segs or last.lower() in _GENERIC_SEGMENTS or not any(c.isdigit() for c in last)):
        return ""                                                   # 一般的な URL（入口・一覧・検索・カテゴリ）
    kept = sorted((k, v) for k, v in q if k in _ID_PARAMS) if has_id else []
    return f"https://{sp.netloc.lower()}/{'/'.join(segs)}" + ("?" + "&".join(f"{k}={v}" for k, v in kept) if kept else "")


def _name_key(i: dict) -> str:
    from src.tcg.lottery.schema import product_key
    return product_key(str(i.get("product_name") or ""))


def event_key(i: dict, *, multi_urls=frozenset()) -> str:
    """イベントの安定した識別子（EVENT_KEY_VERSION の規則）。優先順位:
    1. 出来事固有の情報元 URL（specific_url）+ 店舗（店舗別のみ）+ 種別。商品名・product_id・応募期間は鍵に入れない
       （名前の微修正・正本との照合・期間の補完・延長で、同じイベントが「新規」にならない）。
       ただし 1 つの URL に複数の商品がある（multi_urls）ときは、商品名の正規化キーを足す（別の商品を 1 つに潰さない）
    2. URL が無い・一般的なとき: lottery_id があれば正規化した商品名 + 小売 + 店舗 + 種別。product_id は使わない（後から付く）
    3. それも無ければ 小売 + 種別 + 名前
    同じ鍵のイベントは update で 1 つに数える。"""
    store = str(i.get("store_name") or "") if i.get("store_specific") else ""
    etype = str(i.get("event_type") or "")
    u = specific_url(i.get("source_url"))
    if u:
        k = "|".join(("u", u, store, etype))
        return ((k + "|" + _name_key(i)) if u in multi_urls else k)[:400]
    return name_event_key(i)


def name_event_key(i: dict) -> str:
    """URL を使わない（URL が無い・一般的な）ときの鍵。固有 URL が後から付いたとき、台帳のこの鍵のエントリを新しい鍵へ引き継ぐ。"""
    if i.get("lottery_id"):
        store = str(i.get("store_name") or "") if i.get("store_specific") else ""
        return "|".join(("n", str(i.get("tcg") or ""), _name_key(i), str(i.get("retailer") or "").upper(), store, str(i.get("event_type") or "")))[:300]
    return "|".join(("r", str(i.get("retailer") or "").upper(), str(i.get("event_type") or ""), str(i.get("product_name") or "")))[:300]


def input_is_fresh(*generated_at, now: datetime) -> bool:
    """入力の生成物の生成時刻がすべて、この run の入力として十分新しい（INPUT_MAX_AGE_HOURS 以内）。読めない・無い・未来（5 分超）は古い扱い。
    収集が失敗した日に前回の生成物が残っていても、今日の観測として扱わないための確認。"""
    if not generated_at:
        return False
    for g in generated_at:
        t = _ts(g, now)
        if t is None:
            return False
        age = (now - t).total_seconds() / 3600
        if age < -5 / 60 or age > INPUT_MAX_AGE_HOURS:
            return False
    return True


def _date_only(value) -> bool:
    """時刻の無い日付（YYYY-MM-DD）。時刻の精度が無いので、公開日時としては使わない（遅れが最大約 24 時間ぶれる）。"""
    s = str(value or "").strip()
    if not s:
        return False
    if "T" not in s and ":" not in s:
        return True
    # 収集器は日付だけの公開日を 00:00:00 の時刻つきに変換して出す（例 2026-10-02T00:00:00+09:00）。時刻の精度が無いので、日付だけと同じ扱い
    return bool(re.search(r"[T ]00:00(:00)?(\.0+)?\s*(JST|Z|[+-]\d{2}:?\d{2})?$", s))


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
    if prev.get("event_key_version") != EVENT_KEY_VERSION:                      # 旧鍵の台帳（版なし・別の版）は使わない（測らない。台帳は新しい鍵で作り直す）
        return {}
    ev = {str(k): v for k, v in prev["events"].items()
          if isinstance(v, dict) and isinstance(v.get("first_seen"), str) and isinstance(v.get("last_seen"), str)}

    def _m(x):
        return {str(k): v for k, v in x.items() if isinstance(v, str)} if isinstance(x, dict) else {}
    return {"started_at": prev["started_at"], "events": ev, "sources": _m(prev.get("sources")), "sources_base": _m(prev.get("sources_base")),
            "run_id": str(prev.get("run_id") or ""), "trusted": prev.get("trusted") is True, "event_key_version": EVENT_KEY_VERSION}


def update(items: list[dict], prev, *, comparable: bool, now: datetime, run_id: str = "",
           healthy_sources: set | None = None, input_fresh: bool = True) -> tuple[dict, dict, list[dict]]:
    """(新しい台帳, 公開してよい件数, 非公開の個別の行)。comparable=False（前回の台帳を使えない）なら引き継がず、測定もしない。

    comparable は「前回の台帳を使ってよい」: 前回の run から引き継げたとき、または同じ run の中の再生成が最初の生成の台帳を読んだとき
    （後者は、前回の run までの first_seen を既に含んでいる。ここで捨てると across-runs の記録が消える）。
    測定してよいのは trusted（前回の run から引き継いだ台帳の上に作った）ときだけ。同じ run の再生成は、最初の生成の trusted を引き継ぐ
    （最初の生成が引き継げていなければ、再生成も測らない）。run_id: この run の識別子。
    - 同じイベントは、台帳を使い始めた後に初めて見えた run（measured_run）だけで測る。翌日の run で、また数えない（同じ run の再生成は数える）
    - その取得元が前回の台帳で見えていたか（sources）は、同じ run の再生成では、最初の生成が引き継いだ時点の値（sources_base）で判定する
    - sources の更新: 今回正常に取得できた取得元（healthy_sources）だけ。healthy_sources が渡されない（None）ときだけ、収集器が取得した受付中のイベントがある取得元
    """
    stamp = now.isoformat(timespec="seconds")
    p = sanitize(prev) if comparable else {}
    if not input_fresh:
        # 入力が古い（収集が失敗して前回の生成物が残った日）: 今日の観測として扱わない。台帳は一切進めない
        # （sources・last_seen・first_seen を今に更新しない = 取得元の停止を「見えていた」ことにしない。復旧日の除外が効き続ける）
        zero = {k: 0 for k in ("events_active", "baseline_events", "new_after_baseline", "measured", "unknown_published_at",
                               "detected_before_start", "source_gap_excluded", "identity_ambiguous", "median_delay_hours",
                               "max_delay_hours", "delay_values_withheld", "comparable", "previously_observable_excluded")}
        zero["stale_input"] = 1
        zero["source_not_observed_this_run"] = len(p.get("sources") or {})
        return (dict(p) if p else {}), zero, []
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
    # 1 つの URL に複数の商品がある（この run、または台帳にそのような URL が既にある）: 商品名も鍵に足す。台帳に無い名前は「同一性が曖昧」で測らない
    names_by_url: dict[str, set] = {}
    for it in items or []:
        if isinstance(it, dict) and str(it.get("status") or "") in eq.ACTIVE_STATUSES and specific_url(it.get("source_url")):
            names_by_url.setdefault(specific_url(it.get("source_url")), set()).add(_name_key(it))
    ledger_url_n: dict[str, int] = {}
    for v in events.values():
        if v.get("url"):
            ledger_url_n[v["url"]] = ledger_url_n.get(v["url"], 0) + 1
    multi_urls = {u for u, n in names_by_url.items() if len(n) > 1} | {u for u, n in ledger_url_n.items() if n > 1}
    rows: list[dict] = []
    done_keys: set = set()                                         # 同じ鍵に潰れた複数のイベント（期間違いのラウンドなど）は、1 つのイベントとして 1 回だけ数える・測る
    counts = {"events_active": 0, "baseline_events": 0, "new_after_baseline": 0, "measured": 0, "unknown_published_at": 0,
              "detected_before_start": 0, "source_gap_excluded": 0, "identity_ambiguous": 0, "stale_input": 0,
              "source_not_observed_this_run": 0, "previously_observable_excluded": 0}
    delays: list[float] = []
    for i in items or []:
        if not isinstance(i, dict) or str(i.get("status") or "") not in eq.ACTIVE_STATUSES:
            continue
        k = event_key(i, multi_urls=multi_urls)
        if k in done_keys:
            continue
        done_keys.add(k)
        counts["events_active"] += 1
        seen = events.get(k)
        if seen is None and specific_url(i.get("source_url")):
            # URL が無かった（名前の鍵で台帳に載った）イベントに、後から固有の URL が付いた: 同じイベント。新しい鍵へ引き継ぐ（新規として測らない）
            alt = name_event_key(i)
            if alt in events and not events[alt].get("url"):
                seen = events[k] = events.pop(alt)
        obs = _ts(i.get("observed_at"), now)                         # 収集した時刻（LP の生成時刻より正確）。読めない・未来なら今
        obs_stamp = obs.isoformat(timespec="seconds") if obs is not None and obs <= now else stamp
        retailer = str(i.get("retailer") or "")
        u = specific_url(i.get("source_url"))
        if seen is None:
            seen = events[k] = {"first_seen": obs_stamp, "last_seen": stamp, "retailer": retailer}
            if u:
                seen["url"] = u
            if u in multi_urls or not u:
                # 共有 URL で台帳に無い名前、または固有の URL が無い（名前でしか識別できない）: 新しいイベントか、同じイベントの名前の変更か
                # 区別できない。測らない（過大測定を避ける。固有 URL を持つ取得元だけが検知の遅れの測定対象）
                seen["ambiguous"] = True
        else:
            seen["last_seen"] = stamp
            if u and not seen.get("url"):
                seen["url"] = u
        first = seen["first_seen"]
        fs = _ts(first, now)
        # 台帳を使い始めた後に初めて現れた（使い始めと同時に見えていたものは baseline）
        is_new = trusted and fs is not None and fs > (_ts(started, now) or now)
        ambiguous_new = False
        if is_new and seen.get("ambiguous"):
            counts["identity_ambiguous"] += 1
            is_new = False
            ambiguous_new = True
        row = {"first_seen": first, "measurable": False, "detection_delay_hours": None,
               "detected_before_start": None, "remaining_fraction": None}
        if not is_new:
            counts["baseline_events"] += 1 if (trusted and not ambiguous_new) else 0        # 同一性が曖昧で測らなかったものは baseline ではない（identity_ambiguous に数える）
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
        if str(i.get("collection_method") or "").upper().startswith("MANUAL"):
            counts["unknown_published_at"] += 1                        # 手動の確認済みイベント: 公開日時・観測の時刻が収集器のものではない。測らない
            rows.append(row)
            continue
        pub = _ts(i.get("published_at"), now)
        st, _ = eq._pick(i, "application_start", "application_start_date", now)
        en, _ = eq._pick(i, "application_end", "application_end_date", now, end_of_day=True)
        if pub is None or _date_only(i.get("published_at")) or fs < pub:
            counts["unknown_published_at"] += 1                      # 公開日時が無い・矛盾する → 推測しない
            rows.append(row)
            continue
        if last_src is not None and pub < last_src:
            # 公開が、その取得元を前回観測した時刻より前: 前回見えていたはずのイベント。今回初めて「新規」に見えるのは、同じイベントの
            # 鍵の変化（URL の付け替え・名前や種別の再分類）や、日程の補完で受付中になっただけの可能性がある。測らない（過大測定を避ける）
            counts["previously_observable_excluded"] += 1
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
    if healthy_sources is None:                                    # 正常に取得できた取得元が分からない呼び出しだけ、受付中のイベントがある取得元を見えていたとみなす
        for i in items or []:
            # 手動の確認済みイベント（収集器が取得していない）は、取得元が見えていた根拠にしない（ブロック中の取得元を「見えていた」ことにしない）
            if (isinstance(i, dict) and i.get("retailer") and str(i.get("status") or "") in eq.ACTIVE_STATUSES
                    and not str(i.get("collection_method") or "").upper().startswith("MANUAL")):
                sources[str(i["retailer"])] = stamp
    return ({"started_at": started, "events": events, "sources": sources, "sources_base": dict(prev_sources), "run_id": run_id,
             "trusted": trusted, "event_key_version": EVENT_KEY_VERSION}, counts, rows)

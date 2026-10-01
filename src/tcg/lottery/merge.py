# -*- coding: utf-8 -*-
"""Task22 / Task23 / Task24: 抽選の重複排除・情報源の優先・公式同士の矛盾検出。

- 同一抽選（tcg / 商品 / 小売 / 店舗 / 応募期間）は1件にまとめ、根拠 URL は全て残す。
- 下位の情報源は上位の情報源の期間・条件を上書きしない（空欄を埋めるだけ）。
- 公式同士で開始・締切・価格が食い違う場合は、勝手に一方を採用せず
  SOURCE_CONFLICT として該当項目を空にし、候補値を残して要確認にする。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Iterable

from .schema import (
    LOTTERY_SOURCE_PRIORITY, OFFICIAL_LOTTERY_SOURCES, lottery_id_of, product_key,
)

CONFLICT_FIELDS = ("application_start", "application_end", "retail_price")
# 片方の日時しか無い情報を、既存の回と同じ抽選とみなす許容日数。
# 日付のみの値が関わる場合（時刻で比べられない場合）にだけ使う
PARTIAL_TOLERANCE_DAYS = 3

# 時刻付きの項目と「日付のみ」の項目の対応
_TWIN = {
    "application_start": "application_start_date", "application_start_date": "application_start",
    "application_end": "application_end_date", "application_end_date": "application_end",
    "winner_announcement_at": "winner_announcement_date",
    "winner_announcement_date": "winner_announcement_at",
    "purchase_start": "purchase_start_date", "purchase_start_date": "purchase_start",
    "purchase_end": "purchase_end_date", "purchase_end_date": "purchase_end",
}
# 空欄を埋めてよい日程（公式の情報源からのみ）
SCHEDULE_FIELDS = ("application_start", "application_end", "application_start_date",
                   "application_end_date", "winner_announcement_at", "winner_announcement_date",
                   "purchase_start", "purchase_end", "purchase_start_date", "purchase_end_date")
FILL_FIELDS = (
    "shipping_period",
    "release_date", "retail_price", "price_text", "eligibility_text",
    "membership_required", "app_required", "purchase_history_required",
    "identity_verification_required", "store_pickup_required",
    "payment_method_requirement", "entry_url", "result_url", "purchase_url",
    "shrink_status", "product_id",
)


def _prio(ev: dict) -> int:
    return LOTTERY_SOURCE_PRIORITY.get(ev.get("source_type", ""), 99)


def _group_key(ev: dict) -> tuple:
    """矛盾検出のための「同じ抽選らしい」キー（期間を含めない）。"""
    return (
        ev.get("tcg") or "",
        ev.get("product_id") or product_key(ev.get("product_name") or ""),
        (ev.get("retailer") or "").upper(),
        (ev.get("store_name") or "") if ev.get("store_specific") else "",
    )


def _period(ev: dict):
    """応募期間（開始, 終了）を datetime で返す。日付のみの場合はその日の範囲。"""
    from datetime import timedelta
    from src.tcg.models import parse_dt
    start = parse_dt(ev.get("application_start") or ev.get("application_start_date"))
    end = parse_dt(ev.get("application_end") or ev.get("application_end_date"))
    if end is not None and not ev.get("application_end") and ev.get("application_end_date"):
        end = end + timedelta(days=1)
    return start, end


def _day(ev: dict, key: str):
    """時刻付き / 日付のみのどちらでも、その日付（date）を返す。"""
    from src.tcg.models import parse_dt
    v = parse_dt(ev.get(key) or ev.get(_TWIN.get(key, "")))
    return v.date() if v else None


def _overlaps(a: dict, b: dict) -> bool:
    """応募期間が重なるか。どちらかの期間が不明なら「同じ抽選かもしれない」として True。"""
    a0, a1 = _period(a)
    b0, b1 = _period(b)
    if None in (a0, a1, b0, b1):
        return True
    return a0 <= b1 and b0 <= a1


def _clusters(evs: list[dict]) -> list[list[dict]]:
    """同じ商品・小売の中で、応募期間が重なるものだけを同じ抽選としてまとめる。

    - 開始・締切の両方が分かる event どうしは、期間が重なる場合だけ同じ抽選にする。
      追加抽選・第2弾のように期間が重ならない別回は別の抽選として残す。
    - 開始か締切のどちらかしか分からない event は、その日時を含む回、開始が一致する回、
      無ければ開始が最も近い回に入れる（古い回に入れて日程を消さない）。
      どちらも分からない event は、回が1つだけならそこへ、複数あれば単独で残す。
    """
    complete = [e for e in evs if None not in _period(e)]
    partial = [e for e in evs if None in _period(e)]
    clusters: list[list[dict]] = []
    for ev in sorted(complete, key=lambda e: str(_period(e)[0])):
        for cl in clusters:
            if all(_overlaps(ev, other) for other in cl):
                cl.append(ev)
                break
        else:
            clusters.append([ev])

    for ev in partial:
        s0, s1 = _period(ev)
        point = s0 or s1
        if point is None:
            # 開始も締切も分からない: 回が1つならそこへ、複数なら単独で残す
            if len(clusters) == 1:
                clusters[0].append(ev)
            else:
                clusters.append([ev])
            continue
        # その日付が回の期間（開始日〜締切日）に収まる回だけを候補にする。
        # 時刻ではなく日付で比べる（締切 16:59 と「10/5（時刻未公表）」等を同じ回として扱い、
        # 食い違いは矛盾として検出する）。期間外なら別の回として残す。
        from datetime import timedelta as _td
        from src.tcg.models import parse_dt
        start_only = s0 is not None
        key = "application_start" if start_only else "application_end"
        p_exact = parse_dt(ev.get(key))
        p_day = _day(ev, key)
        fits = []
        for cl in clusters:
            head = cl[0]
            c0d, c1d = _day(head, "application_start"), _day(head, "application_end")
            c0x, c1x = parse_dt(head.get("application_start")), parse_dt(head.get("application_end"))
            if c0d is None or c1d is None or p_day is None:
                continue
            if start_only:
                # 時刻が分かれば時刻で比べる。回の締切より後に始まるなら別の回
                if p_exact and c1x and p_exact > c1x:
                    continue
                if p_exact and c0x:
                    ok = p_exact <= c1x if c1x else p_day <= c1d
                    ok = ok and (p_day == c0d or c0x <= p_exact)
                else:
                    # 日付のみが関わる場合だけ、告知の食い違いとして数日の幅を認める
                    ok = c0d - _td(days=PARTIAL_TOLERANCE_DAYS) <= p_day <= c1d
                ref = c0d
            else:
                # 回の開始より前に締切が来るなら別の回
                if p_exact and c0x and p_exact < c0x:
                    continue
                if p_exact and c1x:
                    # 時刻付き同士: 回の期間内、または締切と同じ日だけを同じ抽選とみなす
                    ok = p_exact <= c1x or p_day == c1d
                else:
                    ok = c0d <= p_day <= c1d + _td(days=PARTIAL_TOLERANCE_DAYS)
                ref = c1d
            if ok:
                fits.append((abs((p_day - ref).days), cl))
        if fits:
            min(fits, key=lambda x: x[0])[1].append(ev)
        else:
            clusters.append([ev])
    return clusters


def merge_lotteries(events: Iterable[dict]) -> list[dict]:
    """重複をまとめ、矛盾を検出した抽選一覧を返す。"""
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for ev in events:
        groups[_group_key(ev)].append(dict(ev))

    out: list[dict] = []
    for evs in (cl for g in groups.values() for cl in _clusters(g)):
        evs.sort(key=_prio)
        base = dict(evs[0])
        base["source_urls"] = list(dict.fromkeys(
            u for e in evs for u in (e.get("source_urls") or [e.get("source_url")]) if u))
        base["merged_count"] = len(evs)

        # 公式同士の矛盾（開始・締切・価格）
        officials = [e for e in evs if e.get("source_type") in OFFICIAL_LOTTERY_SOURCES]
        conflicts: dict[str, list] = {}
        for f in CONFLICT_FIELDS:
            if f == "retail_price":
                vals = {e.get(f) for e in officials if e.get(f) not in (None, "")}
                if len(vals) > 1:
                    conflicts[f] = sorted(str(v) for v in vals)
                continue
            exact = {str(e.get(f))[:16] for e in officials if e.get(f)}
            days = {str(_day(e, f)) for e in officials if _day(e, f)}
            # 時刻付き同士の食い違い、または日付そのものの食い違い
            if len(exact) > 1 or len(days) > 1:
                conflicts[f] = sorted(exact | {d for d in days if d not in {x[:10] for x in exact}})
        if conflicts:
            base["conflict"] = True
            base["conflict_fields"] = conflicts
            for f in conflicts:
                base[f] = None      # どちらかを勝手に採用しない
                if _TWIN.get(f):
                    base[_TWIN[f]] = None
            base.setdefault("notes", []).append(
                "公式情報どうしで日程・価格が食い違っています（要確認）: "
                + ", ".join(conflicts))
        else:
            # 下位 source は上位 source の空欄だけを埋める（上書きしない）。
            # 応募期間などの日程は、公式の情報源からだけ埋める
            # （コミュニティ情報の日程を公式の抽選として表示しない）。
            for e in evs[1:]:
                # 日程・応募条件・URL などは公式の情報源からだけ埋める。
                # コミュニティ / 非公式の手動情報は、公式の抽選の空欄も埋めない。
                if e.get("source_type") not in OFFICIAL_LOTTERY_SOURCES:
                    continue
                for f in FILL_FIELDS + SCHEDULE_FIELDS:
                    if base.get(f) not in (None, "", []) or e.get(f) in (None, "", []):
                        continue
                    # 基準側が「日付のみ」を持っていれば時刻付きの値で埋めない（逆も同じ）。
                    # 時刻の無い締切に別 source の時刻（00:00 等）を足さないため
                    twin = _TWIN.get(f)
                    if twin and base.get(twin):
                        continue
                    base[f] = e[f]
        base["lottery_id"] = lottery_id_of(base)
        out.append(base)
    return out

# -*- coding: utf-8 -*-
"""Task15: Freshness (TTL) / Task16: Current Status。

TCG の入荷情報は通常の価格情報より寿命が短い。
古い入荷報告を「現在買える」と表示しないための層。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional

from .models import (
    EVENT_GUERRILLA_SALE, EVENT_RESTOCK, EVENT_ONLINE_RESTOCK,
    EVENT_CONVENIENCE_STORE, EVENT_LOTTERY, EVENT_FIRST_COME,
    EVENT_PREORDER, EVENT_GENERAL_SALE, EVENT_OFFICIAL_STORE,
    EVENT_RESERVATION_REOPEN, EVENT_SECONDARY_MARKET,
    ST_OPEN, ST_STARTING_SOON, ST_AVAILABLE_NOW, ST_ENDING_SOON, ST_ENDED,
    ST_SOLD_OUT, ST_RESULT_PENDING, ST_PURCHASE_PERIOD, ST_UNVERIFIED,
    now_jst, parse_dt,
)

# イベント種別ごとの TTL（秒）
TTL_SECONDS: dict[str, int] = {
    EVENT_GUERRILLA_SALE: 30 * 60,          # 30分
    EVENT_RESTOCK: 2 * 60 * 60,             # 店頭再入荷: 2時間
    EVENT_ONLINE_RESTOCK: 15 * 60,          # EC在庫復活: 15分
    EVENT_CONVENIENCE_STORE: 2 * 60 * 60,   # コンビニ入荷報告: 2時間
    EVENT_RESERVATION_REOPEN: 2 * 60 * 60,
}
# 「今買える」と表示してよい情報源
_OFFICIAL_SOURCES = ("OFFICIAL", "RETAILER_OFFICIAL", "STORE_OFFICIAL")

# LOTTERY は締切まで有効 / OFFICIAL 系は release date まで有効（TTL なし）
NO_TTL_EVENTS: frozenset[str] = frozenset({
    EVENT_LOTTERY, EVENT_PREORDER, EVENT_FIRST_COME,
    EVENT_GENERAL_SALE, EVENT_OFFICIAL_STORE, EVENT_SECONDARY_MARKET,
})

# 「もうすぐ」の閾値
STARTING_SOON_WINDOW = timedelta(hours=24)
ENDING_SOON_WINDOW = timedelta(hours=24)

# 販売終了日が不明な販売イベントを「今買える」と言い続けてよい上限。
# これを過ぎたら在庫を確認できないので AVAILABLE_NOW にしない。
AVAILABLE_NOW_WINDOW = timedelta(hours=48)


def ttl_for(event_type: str) -> Optional[int]:
    """イベント種別の TTL（秒）。締切基準のものは None。"""
    if event_type in NO_TTL_EVENTS:
        return None
    return TTL_SECONDS.get(event_type)


def is_stale(event: dict, now: Optional[datetime] = None) -> bool:
    """TTL を超過していれば True（= 「今買える」として表示してはいけない）。

    注意: 記事から読み取れた日付に時刻が含まれない場合、起点は 00:00 になる。
    TTL が短い入荷系イベントはその日のうちに stale と判定されるため、
    scraping 由来の入荷情報は「今買える」には昇格しない（安全側の仕様）。
    時刻付きの報告が必要な場合は data/tcg_restock_reports.csv を使う。
    """
    now = now or now_jst()
    ttl = ttl_for(event.get("event_type", ""))
    if ttl is None:
        # 締切基準: 締切/販売終了を過ぎていれば stale
        end = parse_dt(event.get("application_end") or event.get("sale_end")
                       or event.get("purchase_end"))
        return bool(end and now > end)
    observed = parse_dt(event.get("reported_at") or event.get("observed_at"))
    if observed is None:
        return True   # 観測時刻不明の入荷報告は鮮度を保証できない
    return (now - observed).total_seconds() > ttl


def compute_status(event: dict, now: Optional[datetime] = None) -> str:
    """Task16: 画面表示用ステータスを算出する。

    stale な入荷報告は AVAILABLE_NOW にしない（ENDED 扱い）。
    """
    now = now or now_jst()
    et = event.get("event_type", "")
    stale = is_stale(event, now)

    if event.get("sold_out") is True:
        return ST_SOLD_OUT

    # 抽選フロー: 応募期間 → 当選発表待ち → 購入期間
    if et == EVENT_LOTTERY:
        a_start = parse_dt(event.get("application_start"))
        a_end = parse_dt(event.get("application_end"))
        result = parse_dt(event.get("result_date"))
        p_start = parse_dt(event.get("purchase_start"))
        p_end = parse_dt(event.get("purchase_end"))
        if p_start and p_end and p_start <= now <= p_end:
            return ST_PURCHASE_PERIOD
        if a_end and now > a_end:
            if p_end and now > p_end:
                return ST_ENDED
            if result and now < result:
                return ST_RESULT_PENDING
            if result and now >= result and p_start and now < p_start:
                return ST_RESULT_PENDING
            return ST_RESULT_PENDING if (result or p_start) else ST_ENDED
        if a_start and now < a_start:
            return ST_STARTING_SOON if (a_start - now) <= STARTING_SOON_WINDOW else ST_OPEN
        if a_start and a_end and a_start <= now <= a_end:
            return ST_ENDING_SOON if (a_end - now) <= ENDING_SOON_WINDOW else ST_OPEN
        if a_end and now <= a_end:
            return ST_ENDING_SOON if (a_end - now) <= ENDING_SOON_WINDOW else ST_OPEN
        return ST_UNVERIFIED

    # 販売系
    s_start = parse_dt(event.get("sale_start"))
    s_end = parse_dt(event.get("sale_end"))
    if s_start and now < s_start:
        return ST_STARTING_SOON if (s_start - now) <= STARTING_SOON_WINDOW else ST_OPEN
    if s_end and now > s_end:
        return ST_ENDED

    # 入荷報告系: 鮮度が切れていれば「今買える」とは言わない
    if et in TTL_SECONDS:
        if stale:
            return ST_ENDED
        if event.get("source_type") in _OFFICIAL_SOURCES:
            return ST_AVAILABLE_NOW
        return ST_UNVERIFIED   # 未確認報告は AVAILABLE_NOW にしない

    if s_start and now >= s_start:
        # 公式 / 小売公式でなければ「今買える」「締切間近」とは言わない
        if event.get("source_type") not in _OFFICIAL_SOURCES:
            return ST_UNVERIFIED
        if s_end and (s_end - now) <= ENDING_SOON_WINDOW:
            return ST_ENDING_SOON
        # 終了日が不明なまま時間が経ったものは在庫を確認できない
        if s_end is None and (now - s_start) > AVAILABLE_NOW_WINDOW:
            return ST_UNVERIFIED
        return ST_AVAILABLE_NOW
    return ST_UNVERIFIED


def available_now(event: dict, now: Optional[datetime] = None) -> bool:
    """「今買える」とUI表示してよいか。stale / 未確認は False。"""
    return compute_status(event, now) == ST_AVAILABLE_NOW and not is_stale(event, now)

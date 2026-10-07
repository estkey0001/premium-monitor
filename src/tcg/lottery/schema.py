# -*- coding: utf-8 -*-
"""Task3 / Task4 / Task5 / Task7: 抽選イベントのスキーマ・状態・締切カウントダウン。

TCG では「今買える」より「抽選受付中」を上位に扱う。
判定できない日時は None のまま残し、締切を推測しない。
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from src.tcg.models import CONF_HIGH, CONF_LOW, CONF_MEDIUM, now_jst, parse_dt

# ── 状態（Task4） ─────────────────────────────────────────────────────────
L_UPCOMING = "UPCOMING"                      # 応募開始前（公式に開始日時が確認できたもの）
L_OPEN = "OPEN"                              # 応募受付中
L_ENDING_SOON = "ENDING_SOON"                # 締切まで24時間以内
L_CLOSED = "CLOSED"                          # 応募締切後（結果発表日が不明）
L_RESULT_PENDING = "RESULT_PENDING"          # 応募締切後・結果発表前
L_WINNER_ANNOUNCED = "WINNER_ANNOUNCED"      # 結果発表後・購入期間前
L_WINNER_PURCHASE_PERIOD = "WINNER_PURCHASE_PERIOD"  # 当選者のみ購入できる期間
L_ENDED = "ENDED"                            # 購入期間終了 / 終了から一定期間経過
L_UNKNOWN = "UNKNOWN"                        # 日程が確認できない
LOTTERY_STATUSES: tuple[str, ...] = (
    L_UPCOMING, L_OPEN, L_ENDING_SOON, L_CLOSED, L_RESULT_PENDING,
    L_WINNER_ANNOUNCED, L_WINNER_PURCHASE_PERIOD, L_ENDED, L_UNKNOWN,
)
# 「現在進行中」として表示する状態（ENDED / UNKNOWN 以外）
ACTIVE_STATUSES: frozenset[str] = frozenset({
    L_UPCOMING, L_OPEN, L_ENDING_SOON, L_CLOSED, L_RESULT_PENDING,
    L_WINNER_ANNOUNCED, L_WINNER_PURCHASE_PERIOD,
})

# 抽選イベントの種類
LT_LOTTERY = "LOTTERY"                  # 抽選販売
LT_PURCHASE_RIGHT = "PURCHASE_RIGHT"    # 購入権の抽選
LT_PREORDER = "PREORDER"                # 予約（抽選でない受付）
LOTTERY_EVENT_TYPES: tuple[str, ...] = (LT_LOTTERY, LT_PURCHASE_RIGHT, LT_PREORDER)

# 「締切間近」の閾値
ENDING_SOON_WINDOW = timedelta(hours=24)
# 結果発表日も購入期間も分からない抽選を、締切後に表示し続ける上限
CLOSED_RETENTION = timedelta(days=14)
# 開始日時だけ分かっていて締切が分からない抽選の、開始後の扱いの上限
START_ONLY_RETENTION = timedelta(days=7)

# 情報源の確度（Task23 の優先順位。数値が小さいほど上位）
SRC_MANUFACTURER = "MANUFACTURER_OFFICIAL"
SRC_RETAILER = "RETAILER_OFFICIAL"
SRC_STORE = "STORE_OFFICIAL"
SRC_MANUAL_OFFICIAL = "MANUAL_VERIFIED_OFFICIAL"   # 公式ページを手動で確認したもの
SRC_MANUAL = "MANUAL_VERIFIED"                     # 根拠が公式ページでない手動入力
SRC_COMMUNITY = "COMMUNITY"
LOTTERY_SOURCE_PRIORITY: dict[str, int] = {
    SRC_MANUFACTURER: 1, SRC_RETAILER: 2, SRC_STORE: 3,
    SRC_MANUAL_OFFICIAL: 4, SRC_MANUAL: 8, SRC_COMMUNITY: 9,
}
OFFICIAL_LOTTERY_SOURCES: frozenset[str] = frozenset({
    SRC_MANUFACTURER, SRC_RETAILER, SRC_STORE, SRC_MANUAL_OFFICIAL,
})


@dataclass
class LotteryEvent:
    """抽選・予約・購入権イベント（Task3）。不明な項目は None のまま。"""

    tcg: str
    product_name: str
    retailer: str                       # 小売の正規化キー（GEO / POKEMON_CENTER_ONLINE 等）
    event_type: str = LT_LOTTERY

    product_id: Optional[str] = None
    provisional_product: bool = False   # 商品 registry に無い（新商品等）
    product_match: Optional[str] = None  # "exact" / "ambiguous" / "none"
    retailer_name: Optional[str] = None
    store_name: Optional[str] = None
    store_id: Optional[str] = None
    prefecture: Optional[str] = None
    city: Optional[str] = None
    region: str = "JP"
    channel: Optional[str] = None       # ONLINE / STORE / BOTH
    store_specific: bool = False        # 店舗ごとの抽選か（全国共通なら False）
    online_only: Optional[bool] = None

    application_start: Optional[str] = None
    application_end: Optional[str] = None
    winner_announcement_at: Optional[str] = None
    purchase_start: Optional[str] = None
    purchase_end: Optional[str] = None
    # 時刻が公表されていない場合は日付だけ（YYYY-MM-DD）。00:00 等を補わない
    application_start_date: Optional[str] = None
    application_end_date: Optional[str] = None
    winner_announcement_date: Optional[str] = None
    purchase_start_date: Optional[str] = None
    purchase_end_date: Optional[str] = None
    shipping_period: Optional[str] = None   # 原文（「12月10日～12月25日発送予定」等）
    release_date: Optional[str] = None
    retail_price: Optional[int] = None
    price_text: Optional[str] = None

    # Task9: 応募条件（明記がある場合だけ True。原文も必ず保持する）
    eligibility_text: Optional[str] = None
    membership_required: Optional[bool] = None
    app_required: Optional[bool] = None
    purchase_history_required: Optional[bool] = None
    identity_verification_required: Optional[bool] = None
    store_pickup_required: Optional[bool] = None
    payment_method_requirement: Optional[str] = None

    entry_url: Optional[str] = None     # 公式の応募ページのみ（Task27）
    result_url: Optional[str] = None
    purchase_url: Optional[str] = None

    shrink_status: Optional[str] = None
    source_url: str = ""
    source_urls: list[str] = field(default_factory=list)
    source_type: str = SRC_COMMUNITY
    confidence: str = CONF_LOW
    verified: bool = False
    verified_by: Optional[str] = None
    published_at: Optional[str] = None
    observed_at: Optional[str] = None
    last_verified_at: Optional[str] = None
    collection_method: Optional[str] = None

    status: str = L_UNKNOWN
    conflict: bool = False
    conflict_fields: dict = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.event_type not in LOTTERY_EVENT_TYPES:
            raise ValueError(f"unknown lottery event_type: {self.event_type}")
        if self.source_type not in LOTTERY_SOURCE_PRIORITY:
            raise ValueError(f"unknown lottery source_type: {self.source_type}")
        if self.observed_at is None:
            self.observed_at = now_jst().isoformat()
        if self.source_url and self.source_url not in self.source_urls:
            self.source_urls.append(self.source_url)

    @property
    def lottery_id(self) -> str:
        return lottery_id_of(self.to_dict())

    def to_dict(self) -> dict:
        d = asdict(self)
        d["lottery_id"] = lottery_id_of(d)
        return d


def product_key(name: str) -> str:
    """商品名の正規化キー（重複排除用）。"""
    import re
    import unicodedata
    s = unicodedata.normalize("NFKC", name or "").lower()
    return re.sub(r"[^a-z0-9ぁ-んァ-ヶ一-龠ー]", "", s)


def lottery_key(d: dict) -> tuple:
    """Task22: 同一抽選の判定キー。店舗別抽選と全国抽選は別物として扱う。

    Phase 11: 予約（PREORDER）・購入権は抽選と別物として扱う（同じ商品・店・期間でも混ぜない）。
    既存の抽選の lottery_id を変えないため、LOTTERY 以外のときだけ種類をキーに加える。
    """
    etype = d.get("event_type") or LT_LOTTERY
    return (
        d.get("tcg") or "",
        d.get("product_id") or product_key(d.get("product_name") or ""),
        (d.get("retailer") or "").upper(),
        (d.get("store_name") or "") if d.get("store_specific") else "",
        (d.get("application_start") or d.get("application_start_date") or "")[:16],
        (d.get("application_end") or d.get("application_end_date") or "")[:16],
    ) + (() if etype == LT_LOTTERY else (etype,))


def lottery_id_of(d: dict) -> str:
    raw = "|".join(str(x) for x in lottery_key(d))
    return "lot-" + hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


def confidence_for_source(source_type: str) -> str:
    if source_type in (SRC_MANUFACTURER, SRC_RETAILER):
        return CONF_HIGH
    if source_type in (SRC_STORE, SRC_MANUAL_OFFICIAL):
        return CONF_MEDIUM if source_type == SRC_STORE else CONF_HIGH
    return CONF_LOW


# ── Task5: 状態判定 ───────────────────────────────────────────────────────
def _bound(ev: dict, key: str, date_key: str) -> tuple[Optional[datetime], Optional[datetime]]:
    """(確実に過ぎたと言える時刻, まだ来ていないと言える時刻)。

    時刻付きなら両方とも同じ時刻。日付だけの場合は、
      - その日の 00:00 より前ならまだ来ていない
      - 翌日 00:00 以降なら確実に過ぎた
    とだけ扱い、その日の中の時刻は推測しない。
    """
    exact = parse_dt(ev.get(key))
    if exact:
        return exact, exact
    d = parse_dt(ev.get(date_key))
    if d:
        day = d.replace(hour=0, minute=0, second=0, microsecond=0)
        return day + timedelta(days=1), day
    return None, None


def compute_lottery_status(ev: dict, now: Optional[datetime] = None) -> str:
    """JST 基準で抽選の状態を決める。日時は公式記載のものだけを使う。

    日付だけ（時刻未公表）の項目は安全側に扱う:
      - 開始日当日はまだ開始前（受付中と言わない）
      - 締切日当日は締切間近（締切後かどうかは断定しない）、翌日以降は締切後
    """
    now = now or now_jst()
    start_passed, start_not_yet = _bound(ev, "application_start", "application_start_date")
    end_passed, end_not_yet = _bound(ev, "application_end", "application_end_date")
    result_passed, result_not_yet = _bound(ev, "winner_announcement_at", "winner_announcement_date")
    ps_passed, _ps_not_yet = _bound(ev, "purchase_start", "purchase_start_date")
    pe_passed, pe_not_yet = _bound(ev, "purchase_end", "purchase_end_date")

    if start_passed is None and end_passed is None:
        return L_UNKNOWN
    ended = end_passed is not None and now >= end_passed
    # 締切を過ぎたものは、開始が日付のみ（開始判定が翌日 0 時）でも「開始前」にしない
    if not ended and start_passed and now < start_passed:
        return L_UPCOMING
    if end_passed is None:
        # 開始は確認できたが締切が分からない。締切を推測して OPEN と言い続けない
        if start_passed and now - start_passed <= START_ONLY_RETENTION:
            return L_UNKNOWN
        return L_ENDED
    if now < end_not_yet:
        return L_ENDING_SOON if (end_not_yet - now) <= ENDING_SOON_WINDOW else L_OPEN
    if now < end_passed:
        return L_ENDING_SOON   # 締切日当日（時刻未公表）

    # 以降は応募締切後
    if pe_passed and now >= pe_passed:
        return L_ENDED
    if ps_passed and pe_not_yet and ps_passed <= now:
        return L_WINNER_PURCHASE_PERIOD
    if result_not_yet and now < result_not_yet:
        return L_RESULT_PENDING
    if result_passed and now < result_passed:
        return L_RESULT_PENDING   # 当選発表日当日（時刻未公表）
    if result_passed and now >= result_passed:
        if pe_passed is None and now - result_passed > CLOSED_RETENTION:
            return L_ENDED
        return L_WINNER_ANNOUNCED
    # 結果発表日も購入期間も不明
    return L_CLOSED if now - end_passed <= CLOSED_RETENTION else L_ENDED


def countdown(target_iso: Optional[str], now: Optional[datetime] = None) -> Optional[dict]:
    """Task7: 締切（または開始）までの残り時間。過ぎていれば None。"""
    now = now or now_jst()
    t = parse_dt(target_iso)
    if t is None or t <= now:
        return None
    sec = int((t - now).total_seconds())
    days, rem = divmod(sec, 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    if days >= 1:
        label = f"{days}日{hours}時間" if hours else f"{days}日"
    elif hours >= 1:
        label = f"{hours}時間{minutes}分" if minutes else f"{hours}時間"
    else:
        label = f"{max(minutes, 1)}分"
    return {"remaining_days": days, "remaining_hours": hours,
            "remaining_minutes": minutes, "remaining_seconds": sec, "label": label}


# ── Task28: 並び順 ────────────────────────────────────────────────────────
_STATUS_ORDER = {
    L_ENDING_SOON: 0, L_OPEN: 1, L_UPCOMING: 2, L_WINNER_PURCHASE_PERIOD: 3,
    L_WINNER_ANNOUNCED: 4, L_RESULT_PENDING: 5, L_CLOSED: 6, L_UNKNOWN: 7, L_ENDED: 8,
}
_FAR = "9999-12-31"


def sort_key(ev: dict) -> tuple:
    """OPEN は締切が近い順、UPCOMING は開始が近い順、購入期間は購入期限が近い順。"""
    st = ev.get("status")
    if st in (L_OPEN, L_ENDING_SOON):
        t = ev.get("application_end") or ev.get("application_end_date") or _FAR
    elif st == L_UPCOMING:
        t = ev.get("application_start") or ev.get("application_start_date") or _FAR
    elif st == L_WINNER_PURCHASE_PERIOD:
        t = ev.get("purchase_end") or ev.get("purchase_end_date") or _FAR
    else:
        t = (ev.get("application_end") or ev.get("application_end_date")
             or ev.get("application_start") or _FAR)
    return (_STATUS_ORDER.get(st, 9), t)

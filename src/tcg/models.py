# -*- coding: utf-8 -*-
"""TCG（ポケモンカード / ONE PIECEカードゲーム）販売イベントの統一モデル。

既存の lottery_events とは独立した追加レイヤー。
既存の Profit / AI / Opportunity / Notification ロジックには一切触れない。
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta, timezone
from typing import Optional

JST = timezone(timedelta(hours=9))

# ── TCG種別 (Task2) ────────────────────────────────────────────────────────
TCG_POKEMON = "POKEMON"
TCG_ONE_PIECE = "ONE_PIECE"
TCG_TYPES: tuple[str, ...] = (TCG_POKEMON, TCG_ONE_PIECE)

# ── 販売方式 (Task3) ──────────────────────────────────────────────────────
# 「抽選」と「先着」と「コンビニ販売」を絶対に混同しない。
EVENT_LOTTERY = "LOTTERY"                      # 抽選
EVENT_PREORDER = "PREORDER"                    # 予約
EVENT_FIRST_COME = "FIRST_COME"                # 発売日時固定の店頭先着
EVENT_CONVENIENCE_STORE = "CONVENIENCE_STORE"  # コンビニ発売
EVENT_RESTOCK = "RESTOCK"                      # 再入荷
EVENT_GUERRILLA_SALE = "GUERRILLA_SALE"        # 時間非公開の突発店頭販売
EVENT_ONLINE_RESTOCK = "ONLINE_RESTOCK"        # EC在庫復活
EVENT_RESERVATION_REOPEN = "RESERVATION_REOPEN"  # 予約キャンセル分
EVENT_GENERAL_SALE = "GENERAL_SALE"            # 通常販売
EVENT_OFFICIAL_STORE = "OFFICIAL_STORE"        # 公式ストア販売
EVENT_SECONDARY_MARKET = "SECONDARY_MARKET"    # 二次流通

EVENT_TYPES: tuple[str, ...] = (
    EVENT_LOTTERY, EVENT_PREORDER, EVENT_FIRST_COME, EVENT_CONVENIENCE_STORE,
    EVENT_RESTOCK, EVENT_GUERRILLA_SALE, EVENT_ONLINE_RESTOCK,
    EVENT_RESERVATION_REOPEN, EVENT_GENERAL_SALE, EVENT_OFFICIAL_STORE,
    EVENT_SECONDARY_MARKET,
)

# 「今すぐ買える可能性がある」即売系（Task14 で通知優先度を上げる対象）
INSTANT_SALE_EVENTS: frozenset[str] = frozenset({
    EVENT_FIRST_COME, EVENT_CONVENIENCE_STORE, EVENT_RESTOCK,
    EVENT_ONLINE_RESTOCK, EVENT_GUERRILLA_SALE,
})

# ── 情報源の種別 (Task5) ──────────────────────────────────────────────────
SRC_OFFICIAL = "OFFICIAL"                    # メーカー公式
SRC_RETAILER_OFFICIAL = "RETAILER_OFFICIAL"  # 小売公式
SRC_STORE_OFFICIAL = "STORE_OFFICIAL"        # 店舗公式
SRC_COMMUNITY_REPORT = "COMMUNITY_REPORT"    # コミュニティ報告
SRC_SOCIAL_REPORT = "SOCIAL_REPORT"          # SNS報告
SRC_UNVERIFIED = "UNVERIFIED"                # 未確認

SOURCE_TYPES: tuple[str, ...] = (
    SRC_OFFICIAL, SRC_RETAILER_OFFICIAL, SRC_STORE_OFFICIAL,
    SRC_COMMUNITY_REPORT, SRC_SOCIAL_REPORT, SRC_UNVERIFIED,
)

# Task20: 情報取得優先順位（数値が小さいほど上位）。
# 下位 source は上位 source を上書きしない。
SOURCE_PRIORITY: dict[str, int] = {
    SRC_OFFICIAL: 1,
    SRC_RETAILER_OFFICIAL: 2,
    SRC_STORE_OFFICIAL: 3,
    SRC_COMMUNITY_REPORT: 5,   # 複数SNS一致が取れた場合に昇格
    SRC_SOCIAL_REPORT: 6,      # 単一SNS報告
    SRC_UNVERIFIED: 9,
}

# 公式系（これらだけが Confirmed になれる）
OFFICIAL_SOURCE_TYPES: frozenset[str] = frozenset({
    SRC_OFFICIAL, SRC_RETAILER_OFFICIAL, SRC_STORE_OFFICIAL,
})

# ── 信頼度 (Task5) ────────────────────────────────────────────────────────
CONF_HIGH = "high"
CONF_MEDIUM = "medium"
CONF_LOW = "low"
CONFIDENCE_LEVELS: tuple[str, ...] = (CONF_HIGH, CONF_MEDIUM, CONF_LOW)

# ── 情報の確度表記 (Task22) ───────────────────────────────────────────────
VERIFY_CONFIRMED = "Confirmed"
VERIFY_LIKELY = "Likely"
VERIFY_REPORTED = "Reported"
VERIFY_UNVERIFIED = "Unverified"
VERIFICATION_LEVELS: tuple[str, ...] = (
    VERIFY_CONFIRMED, VERIFY_LIKELY, VERIFY_REPORTED, VERIFY_UNVERIFIED,
)

# ── シュリンク状態 (Task8) ────────────────────────────────────────────────
# 「BOX販売」=「シュリンク付き」と仮定しない。不明は必ず UNKNOWN。
SHRINK_SEALED = "SEALED_SHRINK"
SHRINK_REMOVED = "SHRINK_REMOVED"
SHRINK_TAPE_CUT = "TAPE_CUT"
SHRINK_OPENED_BOX = "OPENED_BOX"
SHRINK_PACK_ONLY = "PACK_ONLY"
SHRINK_UNKNOWN = "UNKNOWN"
SHRINK_STATUSES: tuple[str, ...] = (
    SHRINK_SEALED, SHRINK_REMOVED, SHRINK_TAPE_CUT,
    SHRINK_OPENED_BOX, SHRINK_PACK_ONLY, SHRINK_UNKNOWN,
)

# ── 表示ステータス (Task16) ───────────────────────────────────────────────
ST_OPEN = "OPEN"
ST_STARTING_SOON = "STARTING_SOON"
ST_AVAILABLE_NOW = "AVAILABLE_NOW"
ST_ENDING_SOON = "ENDING_SOON"
ST_ENDED = "ENDED"
ST_SOLD_OUT = "SOLD_OUT"
ST_RESULT_PENDING = "RESULT_PENDING"
ST_PURCHASE_PERIOD = "PURCHASE_PERIOD"
ST_UNVERIFIED = "UNVERIFIED"
STATUSES: tuple[str, ...] = (
    ST_OPEN, ST_STARTING_SOON, ST_AVAILABLE_NOW, ST_ENDING_SOON, ST_ENDED,
    ST_SOLD_OUT, ST_RESULT_PENDING, ST_PURCHASE_PERIOD, ST_UNVERIFIED,
)

# ── 通知優先度 (Task14) ───────────────────────────────────────────────────
PRIO_CRITICAL = "CRITICAL"
PRIO_HIGH = "HIGH"
PRIO_MEDIUM = "MEDIUM"
PRIO_LOW = "LOW"
PRIORITIES: tuple[str, ...] = (PRIO_CRITICAL, PRIO_HIGH, PRIO_MEDIUM, PRIO_LOW)

# ── 販売チャネル ──────────────────────────────────────────────────────────
CHANNEL_STORE = "STORE"
CHANNEL_ONLINE = "ONLINE"
CHANNEL_BOTH = "BOTH"
CHANNEL_UNKNOWN = "UNKNOWN"


def now_jst() -> datetime:
    """現在時刻（JST）。"""
    return datetime.now(JST)


def parse_dt(value) -> Optional[datetime]:
    """ISO8601 文字列（または datetime）を JST aware datetime に変換。失敗時 None。"""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=JST)
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
    return dt.astimezone(JST) if dt.tzinfo else dt.replace(tzinfo=JST)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if isinstance(dt, datetime) else (dt or None)


@dataclass
class TcgEvent:
    """TCG販売イベント（Task2 の統一モデル）。

    未確定の項目は必ず None / UNKNOWN のままにする。推測で埋めない。
    """

    tcg: str
    product_id: str
    product_name: str
    event_type: str
    store: str
    channel: str = CHANNEL_UNKNOWN

    # 日時（すべて ISO8601 JST 文字列、未確定は None）
    application_start: Optional[str] = None
    application_end: Optional[str] = None
    sale_start: Optional[str] = None
    sale_end: Optional[str] = None
    result_date: Optional[str] = None
    purchase_start: Optional[str] = None
    purchase_end: Optional[str] = None

    price: Optional[int] = None
    purchase_limit: Optional[str] = None
    box_available: Optional[bool] = None       # 不明なら None（False と区別）
    sold_out: Optional[bool] = None            # 不明なら None（売り切れ断定しない）
    shrink_status: str = SHRINK_UNKNOWN
    region: str = "JP"

    source_url: str = ""
    source_type: str = SRC_UNVERIFIED
    confidence: str = CONF_LOW
    observed_at: Optional[str] = None

    # ── 補助情報 ──
    store_chain: Optional[str] = None
    prefecture: Optional[str] = None
    city: Optional[str] = None
    reported_at: Optional[str] = None
    quantity_if_known: Optional[int] = None
    shrink_report: Optional[str] = None
    official_confirmation: bool = False
    reservation_allowed: Optional[bool] = None
    hold_allowed: Optional[bool] = None
    store_specific_variation: Optional[str] = None
    packs_per_customer: Optional[str] = None
    box_sale: Optional[bool] = None
    release_date: Optional[str] = None
    sale_start_time: Optional[str] = None
    note: Optional[str] = None
    notes: list[str] = field(default_factory=list)

    # ── 派生（計算後に埋まる） ──
    verification: str = VERIFY_UNVERIFIED
    status: str = ST_UNVERIFIED
    priority: str = PRIO_LOW
    stale: bool = False
    ttl_sec: Optional[int] = None
    premium: dict = field(default_factory=dict)
    opportunity_score: Optional[int] = None
    buy_now: bool = False

    def __post_init__(self) -> None:
        if self.tcg not in TCG_TYPES:
            raise ValueError(f"unknown tcg: {self.tcg}")
        if self.event_type not in EVENT_TYPES:
            raise ValueError(f"unknown event_type: {self.event_type}")
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"unknown source_type: {self.source_type}")
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"unknown confidence: {self.confidence}")
        if self.shrink_status not in SHRINK_STATUSES:
            raise ValueError(f"unknown shrink_status: {self.shrink_status}")
        if self.observed_at is None:
            self.observed_at = now_jst().isoformat()

    @property
    def dedupe_key(self) -> tuple:
        """Task21: 同一販売情報の重複判定キー（dedupe と同一ロジック）。"""
        from .dedupe import event_key
        return event_key(self.to_dict())

    def to_dict(self) -> dict:
        return asdict(self)


def event_from_dict(d: dict) -> TcgEvent:
    """dict から TcgEvent を復元（未知キーは無視）。"""
    allowed = set(TcgEvent.__dataclass_fields__)
    return TcgEvent(**{k: v for k, v in d.items() if k in allowed})

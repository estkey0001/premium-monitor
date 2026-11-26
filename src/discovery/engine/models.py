"""発見のエンジンのデータ形式（dataclass。不明は None。時刻は +09:00 つき ISO 8601）。

- Lead: URL の手がかり（どこで見つけたか・選別の結果・取得の状態）。検索のタイトル・スニペットは持たない
- FetchedDoc: 自分で取得した一次情報（本文は正規化テキスト。根拠の位置はこのテキスト上の文字オフセット）
- Evidence / FieldValue: 抽出値と根拠（doc_id・URL・取得時刻・start/end・quote）。quote が本文と一致しない値は null
- Extraction: 1 文書の抽出（抽出器ごと）
- GateResult: 品質ゲートの結果（通過した関門・落ちた理由・publish_ready・台帳の状態）
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# ── Lead の発見元 ──────────────────────────────────────────────────────
FOUND_SITEMAP = "frontier:sitemap"
FOUND_RSS = "frontier:rss"
FOUND_LIST = "frontier:list"
FOUND_SEARCH_PREFIX = "search:"          # 将来の検索 API（今回は Null だけ）

# ── URL の選別 ─────────────────────────────────────────────────────────
ACCEPT_PRIMARY = "ACCEPT_PRIMARY"        # 公式・運営者の証拠のある店舗のドメイン → 取得して根拠にしてよい
ACCEPT_HINT_ONLY = "ACCEPT_HINT_ONLY"    # それ以外 → 根拠にしない（今回は取得もしない）
REJECT_POLICY = "REJECT_POLICY"          # policy_excluded・SNS・比較サイト・検索結果ページ・http(s) でない
REJECT_ROBOTS = "REJECT_ROBOTS"          # robots.txt の禁止・到達不能
REJECT_MARKETPLACE = "REJECT_MARKETPLACE"  # メルカリ・ラクマ・Amazon・ヤフオク・eBay・楽天
REJECT_DUP = "REJECT_DUP"                # 同じ実行の中で同じ URL
URL_DECISIONS = (ACCEPT_PRIMARY, ACCEPT_HINT_ONLY, REJECT_POLICY, REJECT_ROBOTS, REJECT_MARKETPLACE, REJECT_DUP)

# ── 取得の状態 ─────────────────────────────────────────────────────────
NOT_FETCHED = "NOT_FETCHED"
FETCHED = "FETCHED"
BLOCKED = "BLOCKED"                      # robots・403・429 等（回避しない）
FAILED = "FAILED"
SKIPPED_BUDGET = "SKIPPED_BUDGET"
FETCH_STATES = (NOT_FETCHED, FETCHED, BLOCKED, FAILED, SKIPPED_BUDGET)

# ── 抽出する項目 ───────────────────────────────────────────────────────
SCHEDULE_FIELDS = (
    "application_start", "application_end", "application_start_date", "application_end_date",
    "winner_announcement_at", "winner_announcement_date",
    "purchase_start", "purchase_end", "purchase_start_date", "purchase_end_date",
)
PRICE_FIELDS = ("retail_price",)
FIELDS = (
    "title", "published_at", "tcg", "product_name_raw", "product_code", "event_type",
    *SCHEDULE_FIELDS, "retail_price", "jan",
    "membership_required", "app_required", "identity_verification_required", "purchase_history_required",
    "store_pickup_required", "eligibility_text",
)


@dataclass
class Lead:
    lead_id: str
    url: str
    host: str
    found_by: str
    first_seen_at: str
    last_seen_on: str
    source_url: str = ""                 # どの sitemap / RSS / 一覧で見つけたか
    lastmod: Optional[str] = None        # sitemap の lastmod・RSS の pubDate（原文のまま）
    query_id: Optional[str] = None
    seed_id: Optional[str] = None
    url_decision: Optional[str] = None
    decision_reason: str = ""
    fetch_state: str = NOT_FETCHED
    fetch_reason: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FetchedDoc:
    doc_id: str                          # sha256(正規化テキスト)
    url: str
    host: str
    fetched_at: str                      # この本文を最初に取得した時刻（同じ本文の再取得では進めない）
    last_fetched_at: str                 # 最後に取得した時刻（観測の記録。抽出値の時刻には使わない）
    text: str
    http_status: Optional[int] = 200
    robots: str = "allowed"
    content_type: str = "text/html"
    text_path: Optional[str] = None
    published_hint: Optional[str] = None  # frontier の lastmod / pubDate（ページの公開日が本文に無いときの手がかり）
    source_class: Optional[str] = None

    @property
    def text_len(self) -> int:
        return len(self.text or "")

    def index_entry(self) -> dict:
        d = asdict(self)
        d.pop("text", None)
        d["text_len"] = self.text_len
        return d


@dataclass
class Evidence:
    doc_id: str
    url: str
    fetched_at: str
    start: int
    end: int
    quote: str

    def to_dict(self) -> dict:
        return asdict(self)

    def position(self) -> dict:
        """公開してよい位置だけ（quote 本文は公開の台帳に書かない）。"""
        return {"start": self.start, "end": self.end}


@dataclass
class FieldValue:
    value: Any = None
    evidence: Optional[Evidence] = None
    extra: dict = field(default_factory=dict)   # 価格の単位・税込など（quote から導いたもの）

    def to_dict(self) -> dict:
        return {"value": self.value, "evidence": self.evidence.to_dict() if self.evidence else None, **self.extra}


@dataclass
class Extraction:
    doc_id: str
    url: str
    fetched_at: str
    extractor: str
    fields: dict = field(default_factory=dict)       # 名前 → FieldValue
    base_published_at: Optional[str] = None          # 年の補完に使った公開日（本文の根拠つき）
    unknown: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def value(self, name: str):
        fv = self.fields.get(name)
        return fv.value if fv is not None else None

    def to_dict(self) -> dict:
        return {"doc_id": self.doc_id, "url": self.url, "fetched_at": self.fetched_at, "extractor": self.extractor,
                "base_published_at": self.base_published_at,
                "fields": {k: v.to_dict() for k, v in sorted(self.fields.items())},
                "unknown": sorted(set(self.unknown)), "warnings": list(self.warnings)}


@dataclass
class GateResult:
    passed: list = field(default_factory=list)       # 通過した関門（"G1" 等）
    failed: list = field(default_factory=list)       # 落ちた理由（"G5:product_unmapped" 等）
    values: dict = field(default_factory=dict)       # 関門を通った値（名前 → FieldValue）
    lottery_status: Optional[str] = None             # compute_lottery_status の結果（抽出値ではない）
    publish_ready: bool = False
    drop: bool = False                               # 候補にしない（G1・G6 ENDED・G8 重複・G10）
    drop_reason: str = ""
    g4_mode: str = ""                                # rules_only / agree / disagree
    private_notes: dict = field(default_factory=dict)  # 不一致の候補値など（.private だけに残す）

    def reasons(self) -> list:
        return sorted({f.split(":", 1)[1] if ":" in f else f for f in self.failed})

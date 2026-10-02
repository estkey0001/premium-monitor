"""価格の根拠（いつ・どう確認した値か）の分類と、利益を「今狙える利益」として出してよいかの判定。

価格の根拠は5段階に分ける。

| 区分 | 意味 |
|---|---|
| VERIFIED_CURRENT | 実際に取得・確認した値で、確認から CURRENT_DAYS 日以内 |
| VERIFIED_DATED | 確認日がある値で、OFFICIAL_STALE_DAYS 日以内（固定の定価を確認した日など） |
| CONFIGURED_REFERENCE | 設定値（config/products.yaml の定価など）。確認日が分からない |
| STALE | 確認日はあるが古すぎる |
| UNKNOWN | 価格が無い・日時が読めない |

利益・ROI を「現在狙える利益」として強く出せる（最高利益・BUY・TOP10・高利益に入れる）のは、
仕入れも売却も VERIFIED_CURRENT / VERIFIED_DATED のときだけ。
CONFIGURED_REFERENCE・STALE・UNKNOWN を使った差額は「参考差額」として、確定利益と区別して出す。

既存の normalized_prices の freshness_basis（verified / observed / config_unknown_date など）は
from_freshness_basis で同じ区分に読み替える。新しい DB の列は作らない。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from src.market.normalized_prices import OFFICIAL_STALE_DAYS

JST = timezone(timedelta(hours=9))

VERIFIED_CURRENT = "VERIFIED_CURRENT"
VERIFIED_DATED = "VERIFIED_DATED"
CONFIGURED_REFERENCE = "CONFIGURED_REFERENCE"
STALE = "STALE"
UNKNOWN = "UNKNOWN"

ALL_EVIDENCE = (VERIFIED_CURRENT, VERIFIED_DATED, CONFIGURED_REFERENCE, STALE, UNKNOWN)
# 「今狙える利益」の計算に使ってよい区分
PROFIT_ELIGIBLE = frozenset({VERIFIED_CURRENT, VERIFIED_DATED})

# 確認からこの日数以内なら「最新の確認」とみなす
CURRENT_DAYS = 7
# 確認日が OFFICIAL_STALE_DAYS（normalized_prices と共通）より古い定価は STALE

# freshness_basis（normalized_prices が付ける値）→ 区分
_BASIS_MAP = {
    "observed": VERIFIED_CURRENT,
    "verified": VERIFIED_DATED,
    "verified_stale": STALE,
    "observed_stale": STALE,
    "config_unknown_date": CONFIGURED_REFERENCE,
}

# ユーザー向けの短い説明（内部の区分名は出さない）
_LABELS = {
    VERIFIED_CURRENT: "確認済み",
    VERIFIED_DATED: "確認日あり",
    CONFIGURED_REFERENCE: "確認日不明",
    STALE: "確認が古い",
    UNKNOWN: "未確認",
}


def _parse(value) -> datetime | None:
    """日時を JST の aware datetime にする。タイムゾーン無しは JST とみなす（このプロジェクトの保存形式）。"""
    if isinstance(value, datetime):
        d = value
    else:
        s = str(value or "").strip().replace(" JST", "")
        if not s:
            return None
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return (d if d.tzinfo else d.replace(tzinfo=JST)).astimezone(JST)


def classify_dated_price(price, checked_at, now: datetime | None = None, *,
                         current_days: int = CURRENT_DAYS,
                         stale_days: int = OFFICIAL_STALE_DAYS) -> str:
    """価格と「その価格を確認した日時」から区分を決める。確認日が無ければ CONFIGURED_REFERENCE。"""
    try:
        p = float(price or 0)
    except (TypeError, ValueError):
        return UNKNOWN
    if not p > 0:
        return UNKNOWN
    if checked_at in (None, ""):
        return CONFIGURED_REFERENCE
    d = _parse(checked_at)
    if d is None:
        return UNKNOWN
    n = _parse(now) if now is not None else datetime.now(tz=JST)
    age_days = (n - d).total_seconds() / 86400.0
    if age_days < -1:  # 未来の確認日は信用しない
        return UNKNOWN
    if age_days <= current_days:
        return VERIFIED_CURRENT
    if age_days <= stale_days:
        return VERIFIED_DATED
    return STALE


def classify_product_msrp(product, now: datetime | None = None) -> str:
    """商品の定価（BeginnerDealScanner が仕入れ値に使う official_price or retail_price）の区分。

    公式から取得・確認した定価（official_price と official_price_updated_at がある）だけが確認済み。
    official_price が無く retail_price（設定値）を使う場合や、確認日が無い場合は CONFIGURED_REFERENCE。
    """
    official = getattr(product, "official_price", None) or 0
    retail = getattr(product, "retail_price", None) or 0
    if official > 0:
        return classify_dated_price(official, getattr(product, "official_price_updated_at", None), now)
    if retail > 0:
        return CONFIGURED_REFERENCE
    return UNKNOWN


def from_freshness_basis(basis) -> str:
    """normalized_prices の freshness_basis を区分に読み替える。無い・知らない値は UNKNOWN。"""
    return _BASIS_MAP.get(str(basis or "").strip(), UNKNOWN)


def is_profit_eligible(evidence: str) -> bool:
    return evidence in PROFIT_ELIGIBLE


def evidence_label(evidence: str) -> str:
    """ユーザー向けの短い説明（「確認日不明」など）。"""
    return _LABELS.get(evidence, _LABELS[UNKNOWN])


@dataclass(frozen=True)
class ProfitEligibility:
    eligible: bool
    reasons: tuple[str, ...]


def profit_display_eligibility(*, buy_price, buy_evidence: str, sell_price, sell_evidence: str,
                               identity_confirmed: bool = True, price_kind_allowed: bool = True,
                               costs_known: bool = True) -> ProfitEligibility:
    """利益・ROI を「現在狙える利益」として出してよいか。出せない理由を全部返す。

    条件: 仕入れ・売却の価格が有効 / 商品の同一性を確認済み / 価格の種別が許可されたもの /
    仕入れ・売却とも確認済みで新しい（PROFIT_ELIGIBLE）/ 必要な費用が分かっている。
    """
    reasons = []

    def _valid(v) -> bool:
        try:
            return float(v) > 0
        except (TypeError, ValueError):
            return False

    if not _valid(buy_price):
        reasons.append("invalid_buy_price")
    if not _valid(sell_price):
        reasons.append("invalid_sell_price")
    if not identity_confirmed:
        reasons.append("identity_unconfirmed")
    if not price_kind_allowed:
        reasons.append("price_kind_not_allowed")
    if buy_evidence not in PROFIT_ELIGIBLE:
        reasons.append(f"buy_{str(buy_evidence or UNKNOWN).lower()}")
    if sell_evidence not in PROFIT_ELIGIBLE:
        reasons.append(f"sell_{str(sell_evidence or UNKNOWN).lower()}")
    if not costs_known:
        reasons.append("costs_unknown")
    return ProfitEligibility(not reasons, tuple(reasons))

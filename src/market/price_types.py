"""価格の種別（何の価格か）の正本と、成約（SOLD）の根拠・成約中央値の判定。

価格の種別をこのファイルだけで定義する。ほかのファイルで「sold」「落札」などの文字列から
独自に種別を決めない（既存の正規化データの price_type は NPO_TO_CANONICAL で読み替える）。

| 種別 | 意味 |
|---|---|
| RETAIL | 定価・小売店の販売価格 |
| BUYBACK_CASH | 買取店の現金買取価格 |
| TRADE_IN | 下取り価格（現金買取ではない） |
| LISTING | 出品中の希望価格（売れた価格ではない） |
| SOLD | 実際に成約・落札した1件の価格 |
| SOLD_MEDIAN | 同じ商品の成約価格を期間で集計した中央値（件数・期間つき） |
| CONFIGURED_REFERENCE | 設定値の参考価格（確認日不明） |
| UNKNOWN | 種別が分からない（過去のデータで種別が記録されていないものを含む） |

混同しないこと:
- 出品価格を sold / 落札 / 成約 と呼ばない。出品の中央値を成約の中央値として扱わない
- 種別が記録されていない過去のデータは UNKNOWN。名前に「落札」「sold」とあっても SOLD にしない
- SOLD は1件ごとの根拠（商品ページの URL と成約日時）が必要。ダミーの URL・検索結果の URL は根拠にならない
- 利益を「確定利益」として計算してよい売値は BUYBACK_CASH と、条件を満たした SOLD_MEDIAN だけ
"""

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

JST = timezone(timedelta(hours=9))

RETAIL = "RETAIL"
BUYBACK_CASH = "BUYBACK_CASH"
TRADE_IN = "TRADE_IN"
LISTING = "LISTING"
SOLD = "SOLD"
SOLD_MEDIAN = "SOLD_MEDIAN"
CONFIGURED_REFERENCE = "CONFIGURED_REFERENCE"
UNKNOWN = "UNKNOWN"

ALL_PRICE_TYPES = (RETAIL, BUYBACK_CASH, TRADE_IN, LISTING, SOLD, SOLD_MEDIAN,
                   CONFIGURED_REFERENCE, UNKNOWN)

# 確定利益の計算に使ってよい売値の種別
CONFIRMED_SELL_TYPES = frozenset({BUYBACK_CASH, SOLD_MEDIAN})

# 成約中央値を利益判断に使える最低件数（これ未満は insufficient_samples）
MIN_SOLD_SAMPLES = 3

# 正規化データ（normalized_price_observations）の price_type → 正本の種別
NPO_TO_CANONICAL = {
    "official_price": RETAIL,
    "shop_sale_price": RETAIL,
    "flea_listing_price": LISTING,
    "overseas_listing_price": LISTING,
    "flea_sold_price": SOLD,
    # 海外の成約は集計値。SOLD_MEDIAN の条件（件数・期間）を満たすかは別に判定する
    "overseas_sold_price": SOLD,
    "buyback_price": BUYBACK_CASH,
    "trade_in_price": TRADE_IN,
}

# ユーザー向けの呼び方（「市場価格」だけで済ませない）
_LABELS = {
    RETAIL: "定価・販売価格",
    BUYBACK_CASH: "買取価格",
    TRADE_IN: "下取り価格",
    LISTING: "出品価格",
    SOLD: "成約価格",
    SOLD_MEDIAN: "成約価格（中央値）",
    CONFIGURED_REFERENCE: "参考価格（確認日不明）",
    UNKNOWN: "種別不明",
}


def canonical(value) -> str:
    """保存されている種別を正本の種別にする。正本の値・NPO の price_type 以外は UNKNOWN。"""
    v = str(value or "").strip()
    if v in ALL_PRICE_TYPES:
        return v
    return NPO_TO_CANONICAL.get(v, UNKNOWN)


def label(price_type: str) -> str:
    return _LABELS.get(canonical(price_type), _LABELS[UNKNOWN])


def is_confirmed_sell_type(price_type: str) -> bool:
    return canonical(price_type) in CONFIRMED_SELL_TYPES


# ── 成約の根拠 ─────────────────────────────────────────────────────────

# 商品ページ（1件の出品・取引）の URL。検索結果・一覧の URL は含めない
_ITEM_URL_PATTERNS = (
    re.compile(r"^https://(page\.)?auctions\.yahoo\.co\.jp/jp/auction/[A-Za-z0-9]+/?$"),
    re.compile(r"^https://jp\.mercari\.com/(item|shops/product)/[A-Za-z0-9]+/?$"),
    re.compile(r"^https://item\.fril\.jp/[A-Za-z0-9]+/?$"),
    re.compile(r"^https://www\.ebay\.(com|co\.uk|de)/itm/\d+/?$"),
)
# ダミーの番号（x000000001・m00000000001 など、0 が5個以上続く）
_DUMMY_ID = re.compile(r"/[A-Za-z]?0{5,}\d{0,3}/?$")


def is_dummy_url(url) -> bool:
    u = str(url or "").strip()
    return bool(_DUMMY_ID.search(u)) or "example." in u


def is_item_url(url) -> bool:
    """1件の商品ページの URL か（検索結果・ダミーは False）。"""
    u = str(url or "").strip().split("?", 1)[0].split("#", 1)[0]
    if not u or is_dummy_url(u):
        return False
    return any(p.match(u) for p in _ITEM_URL_PATTERNS)


def _parse_dt(value):
    if isinstance(value, datetime):
        d = value
    else:
        s = str(value or "").strip()
        if not s:
            return None
        try:
            d = datetime.fromisoformat(s.replace("Z", "+00:00"))
        except ValueError:
            return None
    return (d if d.tzinfo else d.replace(tzinfo=JST)).astimezone(JST)


def sold_evidence_reasons(item_url, sold_at) -> tuple[str, ...]:
    """1件の成約として扱えない理由（空なら根拠あり）。"""
    reasons = []
    if is_dummy_url(item_url):
        reasons.append("dummy_url")
    elif not is_item_url(item_url):
        reasons.append("no_item_url")
    t = _parse_dt(sold_at)
    if t is None:
        reasons.append("no_sold_at")
    elif t > datetime.now(tz=JST) + timedelta(days=1):
        reasons.append("sold_at_in_future")          # 未来の成約日時は信用しない
    return tuple(reasons)


def has_sold_evidence(item_url, sold_at) -> bool:
    return not sold_evidence_reasons(item_url, sold_at)


# ── 成約中央値・出品の集計 ───────────────────────────────────────────────

@dataclass(frozen=True)
class MarketSample:
    price: int
    price_type: str            # SOLD / LISTING など（正本の種別）
    identity: str              # 同じ商品とみなすキー（商品 + 容量・型など）
    condition: str = ""
    item_url: str = ""
    sold_at: str = ""          # SOLD のときの成約日時


def sold_median(samples, *, identity: str, period_start, period_end,
                conditions=None, min_samples: int = MIN_SOLD_SAMPLES) -> dict:
    """成約中央値（SOLD_MEDIAN）。

    使うのは次をすべて満たす標本だけ: 種別が SOLD / 同じ identity / condition が互換 /
    成約の根拠あり（商品ページの URL と成約日時）/ 成約日時が集計期間内。
    件数が min_samples 未満なら status=insufficient_samples（利益判断に使わない）。
    出品（LISTING）は件数にも値にも入れない。
    """
    ps, pe_ = _parse_dt(period_start), _parse_dt(period_end)
    out = {"price_type": SOLD_MEDIAN, "identity": identity, "sample_count": 0,
           "median": None, "min": None, "max": None,
           "period_start": ps.isoformat() if ps else "", "period_end": pe_.isoformat() if pe_ else "",
           "min_samples": min_samples}
    if ps is None or pe_ is None or ps > pe_:
        return {**out, "status": "no_period"}
    used = []
    for s in samples:
        if canonical(s.price_type) != SOLD or s.identity != identity:
            continue
        if conditions is not None and s.condition not in conditions:
            continue
        if not has_sold_evidence(s.item_url, s.sold_at):
            continue
        t = _parse_dt(s.sold_at)
        if not (ps <= t <= pe_):
            continue
        if not (isinstance(s.price, (int, float)) and s.price > 0):
            continue
        used.append(int(s.price))
    out["sample_count"] = len(used)
    if len(used) < min_samples:
        return {**out, "status": "insufficient_samples"}
    return {**out, "status": "ok", "median": int(statistics.median(used)),
            "min": min(used), "max": max(used)}


def is_sold_median_eligible(stat: dict | None) -> bool:
    """成約中央値を確定利益の売値に使ってよいか。"""
    s = stat or {}
    return (s.get("price_type") == SOLD_MEDIAN and s.get("status") == "ok"
            and int(s.get("sample_count") or 0) >= MIN_SOLD_SAMPLES
            and bool(s.get("period_start")) and bool(s.get("period_end")))


def listing_stats(samples, *, identity: str, conditions=None) -> dict:
    """出品価格（LISTING）の集計。成約中央値とは別物（売れた価格ではない）。"""
    used = [int(s.price) for s in samples
            if canonical(s.price_type) == LISTING and s.identity == identity
            and (conditions is None or s.condition in conditions)
            and isinstance(s.price, (int, float)) and s.price > 0]
    if not used:
        return {"price_type": LISTING, "identity": identity, "listing_count": 0,
                "minimum_listing": None, "maximum_listing": None, "median_listing": None}
    return {"price_type": LISTING, "identity": identity, "listing_count": len(used),
            "minimum_listing": min(used), "maximum_listing": max(used),
            "median_listing": int(statistics.median(used))}


# ── 表示 ───────────────────────────────────────────────────────────────

_SOLD_WORDS = ("成約", "落札", "sold", "完売")


def is_sold_label(text) -> bool:
    """「成約」「落札」「sold」など、成約を名乗る表記か。"""
    t = str(text or "").lower()
    return any(w in t for w in _SOLD_WORDS)


def basis_display(basis, *, has_evidence: bool = False) -> str:
    """価格の種別の表記（price_basis）を一般向けに出すときの文言。

    成約を名乗るのに1件ごとの根拠（商品ページの URL と成約日時）が無い値は「（根拠未確認）」を付ける。
    price_history の手動の値（海外sold・成約価格など）は URL も成約日時も持たないので、常に根拠未確認。
    """
    b = str(basis or "").strip()
    if b and is_sold_label(b) and not has_evidence:
        return f"{b}（根拠未確認）"
    return b

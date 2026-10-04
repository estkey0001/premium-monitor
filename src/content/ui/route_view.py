"""新UIの「せどりルート」の表示モデル（RouteView。UI Phase 5）。

確定ルートは、利益商品と同じ判定（opportunity.eligibility）を通った、定価で公式から買う以外のルートだけ。
判定は次をすべて満たすもの:
- 売値: 買取価格か、条件（件数3以上・集計期間あり）を満たす成約中央値
- 商品の同一性: 両側とも確認済み。二次流通で買う場合は商品ページ単位の URL がある
- 状態: 新品・中古の系統が同じ
- 費用: 購入送料・手数料などがすべて分かっている（0円とみなさない）
- 鮮度: 両側とも14日以内
利益・ROI は既存の値をそのまま使い、ここでも画面でも計算し直さない。

出品価格（LISTING）は確定ルートに使わず、「出品価格の参考」（ListingRef）として別に出す。
利益・ROI は出さない。最高出品価格を売値として扱わない。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from src.content.ui import categories as cats
from src.content.ui import opportunity as opp
from src.content.ui import runtime as rt
from src.market import price_types as pt

RETAIL_TO_SOLD_MEDIAN = "RETAIL_TO_SOLD_MEDIAN"
SECONDARY_TO_SOLD_MEDIAN = "SECONDARY_TO_SOLD_MEDIAN"
RETAIL_TO_BUYBACK = "RETAIL_TO_BUYBACK"
SECONDARY_TO_BUYBACK = "SECONDARY_TO_BUYBACK"
ROUTE_LABELS = {RETAIL_TO_SOLD_MEDIAN: "正規店 → 二次流通", SECONDARY_TO_SOLD_MEDIAN: "二次流通 → 二次流通",
                RETAIL_TO_BUYBACK: "正規店 → 買取店", SECONDARY_TO_BUYBACK: "二次流通 → 買取店"}
# 画面のタブ（買取店へのルートは補助として「その他」）
ROUTE_TAB = {RETAIL_TO_SOLD_MEDIAN: "retail", SECONDARY_TO_SOLD_MEDIAN: "secondary",
             RETAIL_TO_BUYBACK: "other", SECONDARY_TO_BUYBACK: "other"}


@dataclass
class RouteView:
    route_id: str
    route_type: str
    product_id: str
    category: str
    product_name: str
    model: str
    variant: str
    capacity: str
    condition: str
    buy_source: str
    buy_source_type: str
    buy_price: float | None
    buy_price_label: str
    buy_shipping: float | None
    buy_required_cost: float | None
    buy_url: str
    buy_last_verified_at: str
    sell_source: str
    sell_price_type: str
    sell_price: float | None
    sell_fee: float | None
    sell_shipping: float | None
    sell_required_cost: float | None
    sell_url: str
    sell_last_verified_at: str
    sell_period_start: str
    sell_period_end: str
    sell_sample_count: int | None
    sell_min: float | None
    sell_max: float | None
    net_profit: float | None
    roi: float | None
    acquisition_cost: float | None
    cost_lines: list = field(default_factory=list)
    stock_state: str = "UNKNOWN"
    route_status: str = "CONFIRMED"
    freshness: str = ""
    identity_quality: str = "VERIFIED"

    @property
    def route_label(self) -> str:
        return ROUTE_LABELS.get(self.route_type, "その他")

    @property
    def tab(self) -> str:
        return ROUTE_TAB.get(self.route_type, "other")

    @property
    def category_label(self) -> str:
        return cats.LABELS.get(self.category, "その他")

    @property
    def sell_type_label(self) -> str:
        return opp.SELL_TYPE_LABELS.get(self.sell_price_type, "未確認")


def _route_type(v) -> str:
    """仕入れが新品の販売価格（正規店）か、それ以外（二次流通）か × 売り先が成約中央値か買取か。"""
    r = v.flags.get("route") or {}
    retail = v.buy_price_type == pt.RETAIL and opp._cond_family(r.get("buy_condition")) == "new"
    if v.sell_price_type == pt.SOLD_MEDIAN:
        return RETAIL_TO_SOLD_MEDIAN if retail else SECONDARY_TO_SOLD_MEDIAN
    return RETAIL_TO_BUYBACK if retail else SECONDARY_TO_BUYBACK


def from_view(v) -> RouteView:
    r = v.flags.get("route") or {}
    return RouteView(
        route_id=v.id, route_type=_route_type(v), product_id=v.product_id, category=v.category,
        product_name=v.product_name, model=v.model, variant=v.variant, capacity=v.capacity, condition=v.condition,
        buy_source=v.buy_source, buy_source_type="retail" if _route_type(v).startswith("RETAIL") else "secondary",
        buy_price=v.buy_price, buy_price_label=v.buy_price_label, buy_shipping=v.buy_shipping,
        buy_required_cost=v.buy_required_cost, buy_url=rt.safe_url(v.buy_url),
        buy_last_verified_at=v.buy_checked_at,
        sell_source=v.sell_source, sell_price_type=v.sell_price_type, sell_price=v.sell_price,
        sell_fee=v.sell_fee, sell_shipping=v.sell_shipping, sell_required_cost=v.sell_required_cost,
        sell_url=rt.safe_url(v.sell_url), sell_last_verified_at=v.sell_checked_at,
        sell_period_start=str(r.get("sell_period_start") or ""), sell_period_end=str(r.get("sell_period_end") or ""),
        sell_sample_count=v.sell_samples if isinstance(v.sell_samples, int) else None,
        sell_min=opp._num(r.get("sell_min")), sell_max=opp._num(r.get("sell_max")),
        net_profit=v.net_profit, roi=v.roi, acquisition_cost=v.acquisition_cost, cost_lines=list(v.cost_lines),
        stock_state=v.buy_stock, freshness="FRESH")


def build(opportunity_set) -> list[RouteView]:
    """確定ルート（定価で公式から買う以外で、掲載の判定を通ったもの）。純利益の大きい順。"""
    if opportunity_set is None:
        return []
    views = [from_view(v) for v in opportunity_set.eligible if v.kind != "official_to_buyback"]
    # 同じ商品・同じ仕入先・同じ売却先・同じ価格の重複はまとめる
    seen, out = set(), []
    for rv in sorted(views, key=lambda x: -(x.net_profit or 0)):
        key = (rv.product_id, rv.buy_source, rv.buy_price, rv.sell_source, rv.sell_price)
        if key not in seen:
            seen.add(key)
            out.append(rv)
    return out


# ── 出品価格の参考（確定ルートには使わない） ──────────────────────────────

@dataclass
class ListingRef:
    product_id: str
    product_name: str
    category: str
    marketplace: str
    price: int
    count: int | None
    observed_at: str
    stale: bool
    url: str
    condition: str = ""


# 参考に出す出品価格の古さの上限（これより古いものは出さない）
REF_MAX_AGE_DAYS = 30
_SOLD_URL_MARKS = ("lh_sold", "lh_complete", "sold=1", "status=sold", "/sold")


def _marketplace(o: dict) -> str:
    """二次流通の市場名（収集元の名前に「sold」などが入っていても、出品として表示する）。"""
    s = f'{o.get("source_name") or ""} {o.get("source_id") or ""}'.lower()
    for key, label in (("ebay", "eBay"), ("メルカリ", "メルカリ"), ("mercari", "メルカリ"), ("ラクマ", "ラクマ"),
                       ("rakuma", "ラクマ"), ("ヤフオク", "Yahoo!オークション"), ("yahoo", "Yahoo!オークション"),
                       ("amazon", "Amazon マーケットプレイス")):
        if key in s:
            return label
    return "その他の市場"


def listing_refs(observations: list | None, product_genres: dict | None, now=None) -> list[ListingRef]:
    """二次流通の出品価格（価格の種別が出品のもの）。商品×市場ごとに最新の1件。

    出すのは、商品の同一性が確認済み（is_exact_product_match）で、付属品・別の型番・品質の理由で外れたものでなく、
    確認から REF_MAX_AGE_DAYS 日以内のものだけ。成約（sold）の検索ページへのリンクは付けない。
    """
    from datetime import datetime as _dtm

    from src.models.sale_price import CONDITION_LABELS
    from src.tcg.models import JST, parse_dt
    now = now or _dtm.now(tz=JST)
    genres = product_genres or {}
    best: dict = {}
    for o in observations or []:
        if not isinstance(o, dict):
            continue
        ptype = str(o.get("price_type") or "")
        if pt.canonical(o.get("canonical_price_type")) != pt.LISTING and not ptype.endswith("_listing_price"):
            continue
        price = opp._num(o.get("price"))
        if price is None or price <= 0 or not o.get("product_id"):
            continue
        # 商品違い・付属品・照合未了・品質の理由で外れた価格は出さない
        if (o.get("is_exact_product_match") is not True or o.get("accessory_flag") or o.get("wrong_model_flag")
                or str(o.get("product_match_confidence") or "").lower() == "low"
                or str(o.get("rejection_reason") or "") not in ("", "stale_over_14d")):
            continue
        at = parse_dt(str(o.get("observed_at") or "").replace(" ", "T", 1))
        age = (now - at).total_seconds() / 86400 if at is not None else None
        if age is None or age < -1 or age > REF_MAX_AGE_DAYS:     # 未来の時刻・30日より古いものは出さない
            continue
        url = rt.safe_url(o.get("item_url") or o.get("source_url"))
        if any(m in url.lower() for m in _SOLD_URL_MARKS):
            url = ""        # 出品の参考に、成約の検索ページを付けない
        ref = ListingRef(
            product_id=str(o["product_id"]), product_name=str(o.get("product_name") or ""),
            category=cats.from_genre(genres.get(str(o["product_id"]), "")), marketplace=_marketplace(o),
            price=int(price), count=o.get("sample_count") if isinstance(o.get("sample_count"), int) else None,
            observed_at=str(o.get("observed_at") or ""), stale=o.get("freshness_basis") != "observed",
            url=url, condition=CONDITION_LABELS.get(str(o.get("condition") or ""), ""))
        key = (ref.product_id, ref.marketplace)
        if key not in best or ref.observed_at > best[key].observed_at:
            best[key] = ref
    return sorted(best.values(), key=lambda r: (r.stale, r.category, r.product_name, r.marketplace))

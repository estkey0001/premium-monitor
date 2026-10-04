"""新UIの「目的 × ジャンル」の掲載データと件数。

HOME のジャンル・目的の件数と、各目的ページの一覧は、すべてここで作る（同じ定義で数える）。
値の補正・推測はしない。既存の出力（exports）と表示ガード（home.py）をそのまま使う。

件数の定義（Fake count 禁止。どれも「今その目的のページに掲載している件数」）:

| 目的 | 数えるもの |
|---|---|
| 利益商品 opportunities | OpportunityView のうち opportunity.eligibility を通るもの（定価で買って買取店に売る案件と、
|                        | 定価以外で仕入れるルートの両方）。判定の内容は opportunity.py の docstring が正本 |
| 抽選・予約 lottery | 抽選・予約・発売待ちの runtime の状態で、受付中・締切間近・まもなく開始・日程要確認・
|                    | 当選者購入期間・結果待ち・当選発表・発売待ちのもの（bucket < 99。runtime.COUNTED_STATUSES）。
|                    | 受付終了（結果発表日不明）・終了・日程不明は数えない。閲覧時にブラウザで数え直す |
| 在庫再開 restock | 在庫の状態の履歴（exports/stock_history）で、今「購入可能」なもの（在庫あり・確認から
|                  | stock_state.freshness_seconds 以内・公式の https の販売ページあり）。過去の再入荷は数えない。
|                  | 閲覧時にブラウザで期限を判定し直す |
| せどりルート routes | 確定ルート（route_view.RouteView）。利益商品のうち定価で公式から買う以外のもので、
|                     | 売値は買取か条件を満たした成約中央値・両側の商品の同一性と状態・費用がそろったもの。
|                     | 出品価格の参考（ListingRef）は数えない |

ジャンルの件数は、そのジャンルで掲載中の件数（利益商品・抽選・予約・在庫再開の合計。
せどりルートは利益商品の一部なので重ねて数えない）。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from urllib.parse import urlencode

from src.content.ui import categories as cats
from src.content.ui import components as c
from src.content.ui import home
from src.content.ui import opportunity as opp
from src.content.ui import runtime as rt
from src.tcg.models import JST

PURPOSES = ("opportunities", "lottery", "restock", "routes")
# ほかの目的の一部（ジャンルの件数で重ねて数えない）。せどりルートは利益商品の中の「定価以外で仕入れる」もの
OVERLAPPING = ("routes",)


@dataclass
class Item:
    """一覧の1件（Card に渡す値と、ジャンル）。利益商品・せどりルートは view（OpportunityView）を持つ。"""
    purpose: str
    category: str
    card: c.Card | None
    sort_key: tuple = ()
    view: opp.OpportunityView | None = None


@dataclass
class Catalog:
    items: dict[str, list[Item]] = field(default_factory=lambda: {p: [] for p in PURPOSES})
    lottery_cats: dict[str, str] = field(default_factory=dict)      # 抽選の VM の id → ジャンル
    lottery_active: dict[str, bool] = field(default_factory=dict)   # 生成時点で掲載中か
    opportunity_set: opp.OpportunitySet | None = None
    lottery_views: list = field(default_factory=list)                # 抽選・予約の表示モデル（lottery_view）
    restock_views: list = field(default_factory=list)                # 在庫再開の表示モデル（restock_view）
    route_views: list = field(default_factory=list)                  # せどりルートの確定ルート（route_view）
    listing_refs: list = field(default_factory=list)                 # 出品価格の参考（確定ルートには使わない）

    def count(self, purpose: str, category: str = cats.ALL) -> int:
        """生成時点の件数（抽選は閲覧時にブラウザで数え直す）。"""
        if purpose == "lottery":
            return sum(1 for vid, cat in self.lottery_cats.items()
                       if self.lottery_active.get(vid) and category in (cats.ALL, cat))
        return sum(1 for it in self.items[purpose] if category in (cats.ALL, it.category))

    def category_total(self, category: str) -> int:
        """そのジャンルで掲載中の件数（せどりルートは利益商品の一部なので重ねて数えない）。"""
        return sum(self.count(p, category) for p in PURPOSES if p not in OVERLAPPING)

    def static_counts(self) -> dict[str, dict[str, int]]:
        """ブラウザで件数を数え直すときの土台（抽選以外。抽選は runtime の状態から数える）。"""
        out: dict[str, dict[str, int]] = {}
        for p in PURPOSES:
            if p == "lottery":
                continue
            out[p] = {k: self.count(p, k) for k in cats.KEYS}
        return out

    def data_json(self) -> str:
        return json.dumps({"static": self.static_counts(), "lot": self.lottery_cats, "overlap": list(OVERLAPPING)},
                          ensure_ascii=False, separators=(",", ":"))


def _md(value) -> str:
    """日時を「10/03」の形にする（読めなければ空）。"""
    from src.tcg.models import JST, parse_dt
    d = parse_dt(str(value or "").replace(" ", "T", 1)) if value else None
    return d.astimezone(JST).strftime("%m/%d") if d else ""


def _store_label(key) -> str:
    """TCG の店舗キー（POKEMON_CARD_OFFICIAL など）を表示名にする（旧UIと同じ表）。"""
    k = str(key or "")
    try:
        from src.tcg.sources import SOURCE_BY_KEY
    except Exception:  # noqa: BLE001
        return k
    entry = SOURCE_BY_KEY.get(k.upper())
    return (entry["name"] if entry else k) or ""


def _route_card(v: opp.OpportunityView) -> c.Card:
    """せどりルートのページのカード（値は OpportunityView のまま。計算し直さない）。"""
    roi = f"（ROI {v.roi * 100:.1f}%）" if v.roi is not None else ""
    return c.Card(
        title=v.product_name, subtitle=f"{v.buy_source} → {v.sell_source}",
        primary_metric=f"想定純利益 +{_yen(v.net_profit)}{roi}",
        secondary_metric=f"仕入れ {_yen(v.buy_price)} ／ 売却 {_yen(v.sell_price)}（{v.sell_type_label}）",
        cta_label="利益商品で詳しく見る",
        cta_href="?" + urlencode({"ui": "new", "page": "opportunities", "q": v.product_name[:40]}),
        cta_external=False, cta_kind="secondary")


def _yen(v) -> str:
    try:
        return f"¥{int(float(v)):,}"
    except (TypeError, ValueError):
        return ""


def build(*, model: home.HomeModel, tcg_report: dict | None, profit_routes: dict | None,
          legacy_lotteries: list | None, profit_deals: list[dict] | None,
          product_genres: dict[str, str] | None, stock_history: dict | None = None,
          price_observations: list | None = None) -> Catalog:
    genres = product_genres or {}
    cg = Catalog()

    # ── 利益商品・せどりルート: OpportunityView（掲載の判定は opportunity.eligibility だけ） ──
    # 生成の段階で外したルート（excluded_routes の確定候補）も渡し、ここでも同じ判定で外す（除外理由の診断に残すため）
    pr = profit_routes if isinstance(profit_routes, dict) else {}
    routes = list(pr.get("main_routes") or []) + [
        r for r in (pr.get("excluded_routes") or []) if isinstance(r, dict) and r.get("excluded_kind") == "main"]
    cg.opportunity_set = opp.build(deals=profit_deals, routes=routes,
                                   product_genres=genres, now=model.now or datetime.now(tz=JST))
    for v in cg.opportunity_set.eligible:
        cg.items["opportunities"].append(Item("opportunities", v.category, None, (), v))
    # せどりルート（定価で公式から買う以外の確定ルート）は利益商品の一部（ジャンルの件数では重ねて数えない）。
    # 件数は一覧と同じ RouteView（重複をまとめたもの）から数える
    from src.content.ui import route_view as rtv
    cg.route_views = rtv.build(cg.opportunity_set)
    for rv in cg.route_views:
        cg.items["routes"].append(Item("routes", rv.category, None, (-(rv.net_profit or 0),)))
    cg.listing_refs = rtv.listing_refs(price_observations, genres, now=model.now)

    # ── 在庫再開: 在庫の状態の履歴（exports/stock_history）から。件数は「今購入可能」なものだけ
    #    （過去の再入荷は数えない。閲覧時にブラウザで期限を判定し直す） ──
    from src.content.ui import restock_view as rv
    now = model.now or datetime.now(tz=JST)
    cg.restock_views = rv.build(stock_history, opportunity_set=cg.opportunity_set, now=now)
    for v in cg.restock_views:
        if v.available(now):
            cg.items["restock"].append(Item("restock", v.category, None))

    # ── 抽選・予約: runtime の状態（閲覧時に数え直す） ──
    legacy_cat = {}
    for i, raw in enumerate(legacy_lotteries or []):
        try:
            it = raw if isinstance(raw, dict) else dict(raw)
        except (TypeError, ValueError):
            continue
        g = genres.get(str(it.get("product_id") or ""), "")
        legacy_cat[rt.legacy_id(it, i)] = (cats.from_genre(g) if g
                                           else cats.from_text(it.get("brand"), it.get("product_name")))
    for vm in model.vms:
        if vm.get("ann"):
            continue
        # TCG の抽選と、TCG の公式の発売予定は TCG。旧来の抽選は商品のジャンル
        cat = "tcg" if vm.get("src") in ("tcg", "release") else legacy_cat.get(vm["id"], "other")
        cg.lottery_cats[vm["id"]] = cat
        cg.lottery_active[vm["id"]] = model.states[vm["id"]]["bucket"] < rt.BUCKET_HIDDEN
    from src.content.ui import lottery_view as lv
    cg.lottery_views = lv.build(vms=model.vms, tcg_report=tcg_report, legacy_items=legacy_lotteries,
                                lottery_cats=cg.lottery_cats, opportunity_set=cg.opportunity_set)
    return cg

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
| 在庫再開 restock | TCG の販売・入荷の情報で、今買える（AVAILABLE_NOW）かつ古くないもの |
| せどりルート routes | 利益商品のうち、定価以外（店・フリマ）で仕入れるもの（利益ルート由来）。
|                     | 売値は買取か条件を満たした成約中央値だけなので、成約データが無い今は0件になりうる |

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
          product_genres: dict[str, str] | None) -> Catalog:
    genres = product_genres or {}
    cg = Catalog()

    # ── 利益商品・せどりルート: OpportunityView（掲載の判定は opportunity.eligibility だけ） ──
    cg.opportunity_set = opp.build(deals=profit_deals, routes=(profit_routes or {}).get("main_routes"),
                                   product_genres=genres, now=model.now or datetime.now(tz=JST))
    for v in cg.opportunity_set.eligible:
        cg.items["opportunities"].append(Item("opportunities", v.category, None, (), v))
        if v.kind != "official_to_buyback":
            # せどりルート（定価以外で仕入れるルート）は利益商品の一部。同じ案件を2回数えないよう印を付ける
            cg.items["routes"].append(Item("routes", v.category, _route_card(v), (-(v.net_profit or 0),), v))

    # ── 在庫再開: 今買える TCG の販売・入荷（古いものは除く） ──
    # 項目は exports/tcg/latest.json の events の形（store / price / canonical_url / source_url / observed_at）
    for e in ((tcg_report or {}).get("events") or []):
        if not isinstance(e, dict) or e.get("status") != "AVAILABLE_NOW" or e.get("stale"):
            continue
        # 販売ページは公式ストアだけでなく小売店のページもあるので、公式ドメインに限らず https の URL を使う
        # （safe_url: https で書き方が正しいものだけ。収集元は src/tcg/sources の登録済みの店舗）
        url = rt.safe_url(e.get("canonical_url")) or rt.safe_url(e.get("source_url"))
        price = rt.price_text(e.get("price"))
        checked = _md(e.get("observed_at"))
        card = c.Card(
            title=str(e.get("product_name") or ""),
            subtitle=_store_label(e.get("store")),
            status="AVAILABLE",
            # ページに書かれた金額（パック単価か BOX 価格かは区別できないので「定価」とは書かない）
            primary_metric=f"参考価格（ページ記載）{price}" if price.startswith("¥") else "",
            secondary_metric=f"{checked} 確認" if checked else "",
            cta_label="販売ページで確認する" if url else "", cta_href=url or "", cta_external=True,
            cta_kind="secondary", cta_track="restock_click")
        cg.items["restock"].append(Item("restock", "tcg", card))

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

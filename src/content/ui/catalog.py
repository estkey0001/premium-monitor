"""新UIの「目的 × ジャンル」の掲載データと件数。

HOME のジャンル・目的の件数と、各目的ページの一覧は、すべてここで作る（同じ定義で数える）。
値の補正・推測はしない。既存の出力（exports）と表示ガード（home.py）をそのまま使う。

件数の定義（Fake count 禁止。どれも「今その目的のページに掲載している件数」）:

| 目的 | 数えるもの |
|---|---|
| 利益商品 opportunities | 定価で買って買取店に売る案件のうち、定価を確認済み（price_evidence が VERIFIED_*）で、
|                        | 売り先が買取店（出品・成約の推測値ではない）・買取価格の確認が14日以内・見込み利益が0より大きいもの |
| 抽選・予約 lottery | 抽選の runtime の状態で、受付中・締切間近・まもなく開始・日程要確認のもの（bucket < 99）。
|                    | 閲覧時にブラウザで数え直す（締切を過ぎたものは外れる） |
| 在庫再開 restock | TCG の販売・入荷の情報で、今買える（AVAILABLE_NOW）かつ古くないもの |
| せどりルート routes | 利益ルート（main）のうち表示ガード（home.route_reject_reason）を通るもの。
|                     | 売値は買取か条件を満たした成約中央値だけなので、成約データが無い今は0件になりうる |

ジャンルの件数は、そのジャンルの4つの目的の件数の合計。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from src.content.ui import categories as cats
from src.content.ui import components as c
from src.content.ui import home
from src.content.ui import runtime as rt

PURPOSES = ("opportunities", "lottery", "restock", "routes")


@dataclass
class Item:
    """一覧の1件（Card に渡す値と、ジャンル）。"""
    purpose: str
    category: str
    card: c.Card
    sort_key: tuple = ()


@dataclass
class Catalog:
    items: dict[str, list[Item]] = field(default_factory=lambda: {p: [] for p in PURPOSES})
    lottery_cats: dict[str, str] = field(default_factory=dict)      # 抽選の VM の id → ジャンル
    lottery_active: dict[str, bool] = field(default_factory=dict)   # 生成時点で掲載中か

    def count(self, purpose: str, category: str = cats.ALL) -> int:
        """生成時点の件数（抽選は閲覧時にブラウザで数え直す）。"""
        if purpose == "lottery":
            return sum(1 for vid, cat in self.lottery_cats.items()
                       if self.lottery_active.get(vid) and category in (cats.ALL, cat))
        return sum(1 for it in self.items[purpose] if category in (cats.ALL, it.category))

    def category_total(self, category: str) -> int:
        return sum(self.count(p, category) for p in PURPOSES)

    def static_counts(self) -> dict[str, dict[str, int]]:
        """ブラウザで件数を数え直すときの土台（抽選以外。抽選は runtime の状態から数える）。"""
        out: dict[str, dict[str, int]] = {}
        for p in PURPOSES:
            if p == "lottery":
                continue
            out[p] = {k: self.count(p, k) for k in cats.KEYS}
        return out

    def data_json(self) -> str:
        return json.dumps({"static": self.static_counts(), "lot": self.lottery_cats},
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


def _yen(v) -> str:
    try:
        return f"¥{int(float(v)):,}"
    except (TypeError, ValueError):
        return ""


def build(*, model: home.HomeModel, tcg_report: dict | None, profit_routes: dict | None,
          legacy_lotteries: list | None, profit_deals: list[dict] | None,
          product_genres: dict[str, str] | None) -> Catalog:
    genres = product_genres or {}
    cat_of_pid = lambda pid: cats.from_genre(genres.get(str(pid or ""), ""))  # noqa: E731
    cg = Catalog()

    # ── 利益商品: 定価（確認済み）で買って買取店に売る案件（生成側で絞り込み済み） ──
    for d in profit_deals or []:
        net = d.get("net_profit")
        if not (home.price_ok(d.get("official_price")) and home.price_ok(d.get("sell_price"))
                and home.price_ok(net)):
            continue
        rate = d.get("profit_rate")
        rate_txt = f"（{float(rate) * 100:.0f}%）" if isinstance(rate, (int, float)) else ""
        card = c.Card(
            title=str(d.get("title") or ""),
            subtitle=f"定価で購入 → {d.get('sell_shop') or '買取店'}",
            primary_metric=f"見込み利益 +{_yen(net)}{rate_txt}",
            secondary_metric=(f"定価 {_yen(d.get('official_price'))} ／ 買取 {_yen(d.get('sell_price'))}"
                              + (f"（{d['checked']} 確認）" if d.get("checked") else "")),
            cta_label="現行版で詳しく見る", cta_href=str(d.get("href") or ""), cta_external=False,
            cta_kind="secondary", cta_track="product_click")
        cg.items["opportunities"].append(Item("opportunities", cats.from_genre(d.get("genre")), card,
                                              (-float(net),)))

    # ── せどりルート: 表示ガードを通る main ルート ──
    for r in ((profit_routes or {}).get("main_routes") or []):
        if not isinstance(r, dict) or home.route_reject_reason(r):
            continue
        roi = home._num(r.get("roi")) or 0.0
        card = c.Card(
            title=str(r.get("product_name") or ""),
            subtitle=f"{r.get('buy_source') or ''} → {r.get('sell_source') or ''}".strip(" →"),
            primary_metric=f"見込み利益 +{_yen(r.get('net_profit'))}（{roi * 100:.0f}%）",
            secondary_metric=f"仕入れ {_yen(r.get('buy_price'))} ／ 売却 {_yen(r.get('sell_price'))}")
        cg.items["routes"].append(Item("routes", cat_of_pid(r.get("product_id")), card,
                                       (-float(r.get("net_profit") or 0),)))

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
        cat = "tcg" if vm.get("src") == "tcg" else legacy_cat.get(vm["id"], "other")
        cg.lottery_cats[vm["id"]] = cat
        cg.lottery_active[vm["id"]] = model.states[vm["id"]]["bucket"] < rt.BUCKET_HIDDEN
    return cg

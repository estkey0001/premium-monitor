"""UI Phase 6（商品詳細・商品の検索・価格の履歴）のテスト。データはテスト用の架空のもの。

商品詳細は既存の正本（OpportunityView・RouteView・RestockView・LotteryReservationView・price_types・
official_shipping・正規化データ）だけから作り、利益・ROI を計算し直さないこと、確定に使えない価格
（照合未了・古い・状態違い・出品・種別不明）を最安仕入・最高売却・利益に使わないことを確かめる。
"""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest

from src.content.ui import product_detail as pd
from src.content.ui import shell
from src.market import price_history as ph

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_P1 = _load("ui_phase1_helpers_p6", Path(__file__).with_name("test_ui_phase1.py"))
CHROME, _HELPERS, _run, _section = _P1.CHROME, _P1._HELPERS, _P1._run, _P1._section
NOW = _P1.NOW


def _t(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


PRODUCTS = [
    {"product_id": "prod_tcam", "name": "テストカメラ 本体", "genre": "camera", "brand": "TEST", "model": "TC-1",
     "official_price": 200000, "official_url": "https://www.apple.com/jp/shop/buy-test"},
    {"product_id": "prod_tgame", "name": "テストゲーム機", "genre": "game_console", "brand": "TEST", "model": "TG-1",
     "official_price": 60000, "official_url": ""},
    {"product_id": "prod_gr4", "name": "RICOH GR IV", "genre": "camera", "brand": "RICOH", "model": "",
     "official_price": 194800, "official_url": "https://www.ricoh-imaging.co.jp/japan/products/gr-4/"},
]
DEAL = {"product_id": "prod_tcam", "title": "テストカメラ 本体", "genre": "camera", "model": "TC-1", "brand": "TEST",
        "official_price": 200000, "official_checked_at": _t(days=5), "msrp_evidence": "VERIFIED_DATED",
        "stock_status": "在庫あり", "stock_checked_at": _t(minutes=20), "sale_method": "normal", "sell_shop": "買取店A",
        "sell_price": 232000, "sell_checked_at": _t(hours=2), "net_profit": 232000 - 200000 - 1800,
        "user_level": "beginner_easy", "resale_sell": False, "official_url": "https://www.apple.com/jp/shop/buy-test",
        "sell_url": "https://kaitori.example.jp/item/1", "purchase_shipping": 0, "purchase_shipping_status": "FREE_VERIFIED"}


def ob(pid, role, ptype, canon, src, price, at, exact=True, **kw):
    d = {"product_id": pid, "product_name": "TEST", "price_role": role, "price_type": ptype,
         "canonical_price_type": canon, "source_name": src, "price": price, "observed_at": at,
         "is_exact_product_match": exact, "rejection_reason": "", "freshness_basis": "observed",
         "condition": "new_unopened", "link_type": "item", "item_url": "https://jp.mercari.com/item/m48213579146"}
    d.update(kw)
    return d


OBS = [
    ob("prod_tcam", "official", "official_price", "RETAIL", "メーカー公式/定価", 200000, _t(days=5)[:10], exact=False,
       freshness_basis="verified", link_type="official_top", item_url=""),
    ob("prod_tcam", "buy", "shop_sale_price", "RETAIL", "量販店Z", 150000, _t(hours=4)),            # 送料未確認
    ob("prod_tcam", "buy", "flea_listing_price", "LISTING", "フリマ照合未了", 120000, _t(hours=6), exact=False,
       link_type="search"),
    ob("prod_tcam", "buy", "shop_sale_price", "RETAIL", "中古店古い", 110000, _t(days=20),
       rejection_reason="stale_over_14d", freshness_basis="observed_stale"),
    ob("prod_tcam", "buy", "shop_sale_price", "RETAIL", "中古店W", 90000, _t(hours=3), condition="used_a"),  # 状態違い
    ob("prod_tcam", "sell", "buyback_price", "BUYBACK_CASH", "買取店A", 232000, _t(hours=2),
       source_url="https://kaitori.example.jp/item/1"),
    ob("prod_tcam", "sell", "buyback_price", "BUYBACK_CASH", "買取店B照合未了", 299000, _t(hours=3), exact=False,
       link_type="shop_home"),
    ob("prod_tcam", "sell", "buyback_price", "UNKNOWN", "種別不明店", 399000, _t(hours=3)),
    ob("prod_tcam", "sell", "flea_sold_price", "SOLD_MEDIAN", "メルカリ成約", 238000, _t(hours=5), sample_count=14,
       sold_median_eligible=True, sold_period_start=_t(days=30), sold_period_end=_t(hours=5)),
    ob("prod_tcam", "sell", "overseas_sold_price", "SOLD", "eBay成約2件", 260000, _t(days=2), sample_count=2),
    ob("prod_tcam", "buy", "flea_listing_price", "LISTING", "メルカリ出品", 499000, _t(hours=8), sample_count=23),
    ob("prod_tgame", "official", "official_price", "RETAIL", "メーカー公式/定価", 60000, "", exact=False,
       freshness_basis="config_unknown_date", link_type="official_top", item_url=""),
    # GR IV（本番にあった偽ルートと同じ観測。照合未了の検索結果と照合未了の買取）
    ob("prod_gr4", "buy", "shop_sale_price", "LISTING", "Amazon JP (新品出品)", 107491, _t(hours=1), exact=False,
       link_type="unknown", item_url="", source_url="https://www.amazon.co.jp/s?k=RICOH%20GR%20IV"),
    ob("prod_gr4", "sell", "buyback_price", "BUYBACK_CASH", "フジヤカメラ", 151000, _t(hours=1), exact=False,
       link_type="search", item_url="", source_url="https://www.fujiya-camera.co.jp/shop/purchase/list.aspx?keyword=GR"),
]
STOCK = {"entries": {
    "official:prod_tcam:s": {"key": "official:prod_tcam:s", "product_id": "prod_tcam", "product_name": "テストカメラ 本体",
                             "category": "camera", "state": "IN_STOCK", "previous_state": "OUT_OF_STOCK",
                             "last_definite_state": "IN_STOCK", "restocked_at": _t(hours=1), "first_seen_in_stock_at": _t(days=3),
                             "last_checked_at": _t(minutes=20), "store": "TEST公式", "source_type": "official_store",
                             "url": "https://www.apple.com/jp/shop/buy-test", "source_url": "https://www.apple.com/jp/shop/buy-test",
                             "price": 200000, "price_observed_at": _t(days=5)},
    "official:prod_tgame:s": {"key": "official:prod_tgame:s", "product_id": "prod_tgame", "product_name": "テストゲーム機",
                              "category": "game", "state": "UNKNOWN", "previous_state": "UNKNOWN", "last_checked_at": _t(hours=5),
                              "store": "TEST公式", "source_type": "official_store", "url": "", "source_url": ""}},
    "events": [{"key": "official:prod_tcam:s", "kind": "RESTOCK", "previous_state": "OUT_OF_STOCK", "new_state": "IN_STOCK",
                "transition_at": _t(hours=1), "product_id": "prod_tcam", "store": "TEST公式", "source": "official_store"}]}
HISTORY = {"series": {
    "a": {"product_id": "prod_tcam", "kind": "buyback", "source": "買取店A",
          "points": [{"at": _t(days=12), "price": 226000}, {"at": _t(hours=2), "price": 232000}]},
    "b": {"product_id": "prod_tcam", "kind": "retail", "source": "メーカー公式/定価", "points": [{"at": _t(days=5)[:10], "price": 200000}]},
    "c": {"product_id": "prod_tcam", "kind": "buyback", "source": "買取店B", "points": [{"at": _t(days=3), "price": 199000}]}}}
LOTTERY = [{"id": "t-lot", "product_id": "prod_tgame", "product_name": "テストゲーム機 抽選", "brand": "TEST",
            "entry_start_at": (NOW - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
            "entry_end_at": (NOW + timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
            "url": "https://www.apple.com/jp/shop/test-lottery", "entry_form_url": "https://www.apple.com/jp/shop/test-lottery/form"}]
KW = dict(products=PRODUCTS, profit_deals=[DEAL], price_observations=OBS, stock_history=STOCK, price_history=HISTORY,
          legacy_lotteries=LOTTERY, profit_routes={"main_routes": []},
          product_genres={"prod_tcam": "camera", "prod_tgame": "game_console", "prod_gr4": "camera"})


def _ctx(**kw):
    return _P1._ctx(**(KW | kw))


def _catalog_views(**kw):
    ctx = _ctx(**kw)
    model, catalog = shell.build_catalog(ctx)
    return pd.build(products=ctx.products, catalog=catalog, observations=ctx.price_observations,
                    price_history=ctx.price_history, stock_history=ctx.stock_history, now=model.now), catalog


def _product_section(root: str) -> str:
    """商品詳細のページ全体（中に section があるので、次の JSON の script までを切り出す）。"""
    i = root.index('data-nu-page="product"')
    return root[i:root.index('<script type="application/json"', i)]


def _article(root: str, pid: str) -> str:
    i = root.index(f'data-nu-pd="{pid}"')
    return root[i:root.index("</article>", i)]


# ── 表示モデル ─────────────────────────────────────────────────────────

def test_best_buy_and_sell_use_only_canonical_prices():
    views, _ = _catalog_views()
    v = views["prod_tcam"]
    # 最安仕入: 取得原価が分かる確認済みの行だけ（量販店Z は 150,000 と安いが送料未確認。照合未了・古い・状態違いは使わない）
    assert v.best_buy.source == "TEST 公式ストア" and v.best_buy.acquisition == 200000
    srcs = [r.source for r in v.buy_rows]
    assert "中古店W" not in srcs                                         # 状態違いは混ぜない
    q = {r.source: r.quality for r in v.buy_rows}
    assert q["フリマ照合未了"] == pd.UNVERIFIED and q["中古店古い"] == pd.STALE and q["量販店Z"] == pd.VERIFIED
    # 最高の有効な売却価格: 確認済みの買取価格か条件を満たす成約中央値（照合未了 299,000・種別不明 399,000・出品 499,000 は使わない）
    assert v.best_sell.price == 238000 and v.best_sell.price_type == "SOLD_MEDIAN"
    assert "種別不明店" not in [r.source for r in v.sell_rows]
    assert {r.source: r.note for r in v.sold_refs}["eBay成約2件"] == "件数不足"
    # 利益は OpportunityView の値（計算し直さない）
    assert v.opportunity.net_profit == DEAL["net_profit"] and v.required_capital == v.opportunity.acquisition_cost


def test_unknown_shipping_is_not_zero():
    views, _ = _catalog_views()
    g = views["prod_tgame"]
    off = g.buy_rows[0]
    assert off.shipping is None and off.acquisition is None and g.best_buy is None and g.opportunity is None
    assert g.required_capital is None


@pytest.mark.parametrize("mutate, check", [
    ({"is_exact_product_match": False}, lambda v: v.best_sell.price == 238000),         # 照合を外すと買取A は確定から外れる
    ({"canonical_price_type": "UNKNOWN"}, lambda v: "買取店A" not in [r.source for r in v.sell_rows]),
    ({"observed_at": _t(days=20)}, lambda v: next(r for r in v.sell_rows if r.source == "買取店A").quality == pd.STALE),
])
def test_mutations_on_sell_rows_are_safe(mutate, check):
    obs = [dict(o, **mutate) if o["source_name"] == "買取店A" else o for o in OBS]
    views, _ = _catalog_views(price_observations=obs)
    assert check(views["prod_tcam"])


def test_sold_median_to_listing_is_not_a_sell():
    obs = [dict(o, canonical_price_type="LISTING", sold_median_eligible=False) if o["source_name"] == "メルカリ成約" else o
           for o in OBS]
    v = _catalog_views(price_observations=obs)[0]["prod_tcam"]
    assert v.best_sell.price == 232000 and all(r.price_type != "LISTING" for r in v.sell_rows)


def test_shipping_known_to_none_drops_profit():
    v = _catalog_views(profit_deals=[dict(DEAL, purchase_shipping=None)])[0]["prod_tcam"]
    assert v.opportunity is None and any("購入送料" in r for r in v.profit_reasons)


def test_stock_unknown_is_not_available_and_status_priority():
    views, _ = _catalog_views()
    assert views["prod_tcam"].status == "AVAILABLE"
    g = views["prod_tgame"]
    assert g.status == "LOTTERY" and g.lotteries                       # 抽選受付中（在庫ありにはしない）
    stock = json.loads(json.dumps(STOCK))
    stock["entries"]["official:prod_tcam:s"]["state"] = "UNKNOWN"
    v = _catalog_views(stock_history=stock)[0]["prod_tcam"]
    assert v.status != "AVAILABLE" and not v.buy_rows[0].cta_primary


def test_gr4_invalid_route_never_appears():
    views, _ = _catalog_views()
    v = views["prod_gr4"]
    assert v.opportunity is None and v.best_buy is None and v.best_sell is None
    assert {r.source: r.quality for r in v.buy_rows + v.sell_rows}["フジヤカメラ"] == pd.UNVERIFIED
    root = shell.render_root(_ctx())
    art = _article(root, "prod_gr4")
    assert "39,009" not in art and "142,079" not in art
    # 照合未了の価格は参考として出し、ボタン（購入・買取ページ）を付けない
    assert "参考・商品照合未完了" in art and "amazon.co.jp" not in art and "fujiya-camera" not in art


def test_recent_changes_have_evidence_only():
    v = _catalog_views()[0]["prod_tcam"]
    types = [c["type"] for c in v.changes]
    assert "RESTOCK" in types and "SELL_PRICE_CHANGE" in types
    for c in v.changes:
        assert c["changed_at"] and c["source"] and c.get("after")
    # 別の店の価格どうしは比べない（買取店B の1点は変化にならない）
    assert not any(c["source"] == "買取店B" for c in v.changes)


# ── 価格の履歴 ─────────────────────────────────────────────────────────

def test_price_history_real_points_dedupe_and_rejections():
    h = ph.merge(None, OBS)
    keys = set(h["series"])
    assert "prod_tcam|buyback|買取店A" in keys and "prod_tcam|retail|メーカー公式/定価" in keys
    assert "prod_tcam|sold_median|メルカリ成約" in keys and "prod_tcam|listing|メルカリ出品" in keys
    assert not any("照合未了" in k or "種別不明" in k for k in keys)      # 照合未了・種別不明は入れない
    assert "prod_tgame|retail|メーカー公式/定価" not in keys               # 確認日の無い設定値は入れない
    n = sum(len(s["points"]) for s in h["series"].values())
    h2 = ph.merge(json.loads(json.dumps(h)), OBS)                         # 同じ観測を2回足しても増えない
    assert sum(len(s["points"]) for s in h2["series"].values()) == n
    # 日付だけの観測は日付のまま（時刻を足さない）
    assert h["series"]["prod_tcam|retail|メーカー公式/定価"]["points"][0]["at"] == _t(days=5)[:10]
    # 取得失敗（0円・取得失敗）・未来の時刻は入れない
    bad = [ob("prod_x", "sell", "buyback_price", "BUYBACK_CASH", "店", 0, _t(hours=1)),
           ob("prod_x", "sell", "buyback_price", "BUYBACK_CASH", "店", 1000, _t(hours=1), rejection_reason="price_zero"),
           ob("prod_x", "sell", "buyback_price", "BUYBACK_CASH", "店", 1000, (NOW + timedelta(days=3)).isoformat())]
    assert not ph.merge(None, bad, now=NOW)["series"]


def test_price_history_keeps_previous_points():
    first = ph.merge(None, OBS)
    later = [ob("prod_tcam", "sell", "buyback_price", "BUYBACK_CASH", "買取店A", 233000, _t(minutes=5))]
    h = ph.merge(json.loads(json.dumps(first)), later)
    pts = h["series"]["prod_tcam|buyback|買取店A"]["points"]
    assert [p["price"] for p in pts] == [232000, 233000]


def test_history_empty_one_point_and_multi_series_render():
    root = shell.render_root(_ctx())
    gr = _article(root, "prod_gr4")
    assert "価格履歴はまだありません。今後の確認結果から履歴を作成します。" in gr
    cam = _article(root, "prod_tcam")
    assert cam.count("<path class=\"nu-hs") == 1                       # 線は2点以上の系列（買取店A）だけ
    assert "（1点）" in cam and "（2点）" in cam and "間の値は推定していません" in cam
    assert "<circle" in cam


# ── 画面（HTML） ────────────────────────────────────────────────────────

def test_profit_and_roi_are_rendered_not_computed():
    root = shell.render_root(_ctx())
    cam = _article(root, "prod_tcam")
    assert "+¥30,200" in cam and "15.1%" in cam and "取得原価" in cam
    js = root[root.index("function renderProduct"):root.index("function render(moveFocus)")]
    for w in ("net_profit", "roi", "acquisition", "* ", "/ 100", "profit"):
        assert w not in js.replace("data-nu-pd", ""), w


def test_tabs_are_accessible_and_ids_unique():
    root = shell.render_root(_ctx())
    sec = _product_section(root)
    tabs = re.findall(r'<button type="button" role="tab"[^>]*>', sec)
    assert len(tabs) == 3 * len(PRODUCTS)
    for b in tabs:
        assert "aria-selected=" in b and "aria-controls=" in b
    ids = re.findall(r'\sid="([^"]+)"', root)
    assert len(ids) == len(set(ids))
    assert 'role="tablist"' in sec and 'role="tabpanel"' in sec


def test_lottery_cta_requires_human_confirmation():
    from src.content.ui import product_page
    from src.content.ui import runtime as rt
    views, _ = _catalog_views()
    v = views["prod_tgame"]
    lv, st = v.lotteries[0]
    assert st["cta"]["kind"] == "apply"                                # 否定対照: 確認済みなら応募できる
    # 告知の転記を人が確認していない抽選は、受付中でも「応募する」を出さない（runtime の判定のまま）
    lv.vm = dict(lv.vm, unv=True)
    lv.human_confirmed = False
    st2 = rt.derive_runtime_state(lv.vm, NOW)
    v.lotteries = [(lv, st2)]
    html = product_page._lotteries(v)
    assert st2["cta"] is None or st2["cta"]["kind"] != "apply"
    assert "応募する" not in html and "応募ボタンは出していません" in html


def test_links_from_lists_and_search_preserve_ctas():
    root = shell.render_root(_ctx())
    href = 'href="?ui=new&amp;page=product&amp;product_id=prod_tcam"'
    assert href in _section(root, "opportunities")
    assert 'product_id=prod_tgame' in _section(root, "lottery")
    assert 'product_id=prod_tcam' in _section(root, "restock")
    assert href in _section(root, "search") and 'product_id=prod_gr4' in _section(root, "search")
    # 既存のボタンは残す
    assert "公式ストアを開く" in _section(root, "opportunities") and "応募する" in _section(root, "lottery")
    assert "購入する" in _section(root, "restock")


def test_route_rows_link_to_product_detail():
    rf = _load("route_fixtures_p6", Path(__file__).with_name("route_fixtures.py"))
    r = rf.safe_route(NOW, "prod_tcam")
    root = shell.render_root(_ctx(profit_routes={"main_routes": [r]}))
    assert 'product_id=prod_tcam' in _section(root, "routes")


def test_unknown_product_and_unsafe_url():
    p = dict(PRODUCTS[0], product_id="prod_bad", official_url="javascript:alert(1)")
    root = shell.render_root(_ctx(products=PRODUCTS + [p]))
    art = _article(root, "prod_bad")
    assert "javascript:" not in art
    assert "商品が見つかりません" in _product_section(root) and "商品一覧へ戻る" in _product_section(root)


def test_search_only_lists_registered_products():
    root = shell.render_root(_ctx())
    sec = _section(root, "search")
    assert sec.count("data-nu-srow") == len(PRODUCTS)                 # 観測だけの未知の商品は作らない
    assert "条件に一致する商品がありません。ジャンルや検索語を変更してください。" in sec


def test_demo_not_in_production_sources():
    for f in ("src/content/ui/product_detail.py", "src/content/ui/product_page.py", "src/market/price_history.py"):
        assert "DEMO" not in (ROOT / f).read_text(encoding="utf-8")


# ── ブラウザ（DOM） ─────────────────────────────────────────────────────

_PD = _HELPERS + """
function art(){ return R.querySelector('[data-nu-pd]:not([hidden])'); }
function sel(){ var a = art(); return a ? a.querySelector('[aria-selected=true]').getAttribute('data-nu-pdtab') : null; }
"""


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_direct_url_tabs_back_forward(tmp_path):
    # 一覧 → 詳細 → タブ → 戻る（一覧の状態に戻る）
    js2 = _PD + """
    var o = {};
    var link = R.querySelector('[data-nu-page="opportunities"] a.nu-pdlink');
    link.click();
    o.inDetail = state().page; o.pid = art() && art().getAttribute('data-nu-pd'); o.q = location.search;
    art().querySelector('[data-nu-pdtab="history"]').click(); o.tabQ = location.search; o.tab = sel();
    var t = art().querySelector('[data-nu-pdtab="history"]'); t.focus();
    t.dispatchEvent(new KeyboardEvent('keydown', {key: 'ArrowRight', bubbles: true})); o.keyTab = sel();
    R.querySelector('[data-nu-back]').click();
    setTimeout(function(){ o.backQ = location.search; o.backPage = state().page; o.title = document.title; done(o); }, 300);
    """
    o = _run(tmp_path, js2, query="?ui=new&page=opportunities&category=camera&sort=profit", **KW)
    assert o["inDetail"] == "product" and o["pid"] == "prod_tcam" and "category=camera" in o["q"]
    assert "tab=history" in o["tabQ"] and o["tab"] == "history" and o["keyTab"] == "changes"
    assert o["backPage"] == "opportunities" and "sort=profit" in o["backQ"] and "category=camera" in o["backQ"]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_invalid_and_alias_product(tmp_path):
    js = _PD + """
    var o = {miss: !R.querySelector('[data-nu-pd-missing]').hidden, title: document.title, shown: !!art()};
    done(o);
    """
    o = _run(tmp_path, js, query="?ui=new&page=product&product_id=nope", **KW)
    assert o["miss"] is True and o["shown"] is False and o["title"].startswith("商品が見つかりません")
    js2 = _PD + "done({pid: art() && art().getAttribute('data-nu-pd'), tab: sel()});"
    o = _run(tmp_path, js2, query="?ui=new&page=product&product_id=tcam&tab=changes", **KW)
    assert o["pid"] == "prod_tcam" and o["tab"] == "changes"


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_search_filters_and_links(tmp_path):
    js = _PD + """
    var sec = R.querySelector('[data-nu-page="search"]');
    var vis = function(){ return [].slice.call(sec.querySelectorAll('[data-nu-srow]')).filter(function(e){return !e.hidden;}).length; };
    var o = {n: vis(), res: sec.querySelector('[data-nu-sresult]').textContent, val: sec.querySelector('input').value};
    var inp = sec.querySelector('[data-nu-search-input]'); inp.value = 'zzz'; inp.dispatchEvent(new Event('input', {bubbles: true}));
    setTimeout(function(){
      o.empty = !sec.querySelector('[data-nu-sempty]').hidden; o.q = location.search;
      inp.value = 'ricoh'; inp.dispatchEvent(new Event('input', {bubbles: true}));
      setTimeout(function(){
        sec.querySelector('[data-nu-srow]:not([hidden]) a.nu-pdlink').click();
        o.page = state().page; o.pid = art() && art().getAttribute('data-nu-pd');
        history.back();
        setTimeout(function(){ o.backQ = location.search; o.backN = vis(); done(o); }, 300);
      }, 400);
    }, 400);
    """
    o = _run(tmp_path, js, query="?ui=new&page=search&q=ricoh&category=camera", **KW)
    assert o["n"] == 1 and o["res"] == "1件" and o["val"] == "ricoh"
    assert o["empty"] is True and "q=zzz" in o["q"]
    assert o["page"] == "product" and o["pid"] == "prod_gr4"
    assert "q=ricoh" in o["backQ"] and "category=camera" in o["backQ"] and o["backN"] == 1   # 戻ると検索の状態


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_stock_expiry_and_lottery_runtime(tmp_path):
    js = _PD + """
    var o = {};
    var a = R.querySelector('[data-nu-pd="prod_tgame"]');
    o.lot = a.querySelector('[data-nu-pd-status]').textContent.trim();
    o.apply = !!a.querySelector('.nu-pd-lot a[data-nu-cta="apply"]');
    var c = R.querySelector('[data-nu-pd="prod_tcam"]');
    o.cam = c.querySelector('[data-nu-pd-status]').textContent.trim();
    done(o);
    """
    o = _run(tmp_path, js, query="?ui=new&page=product&product_id=prod_tgame", **KW)
    assert "受付中" in o["lot"] and o["apply"] is True and o["cam"] == "購入可能"
    # 在庫の確認から時間が経つと（4時間後）、「購入可能」「購入する」と言わない
    later = NOW + timedelta(hours=4)
    js2 = (_PD + """
    Date.now = function(){ return %d; };
    window.dispatchEvent(new PageTransitionEvent('pageshow'));
    setTimeout(function(){
      var c = R.querySelector('[data-nu-pd="prod_tcam"]');
      done({cam: c.querySelector('[data-nu-pd-status]').textContent.trim(),
            buy: [].slice.call(c.querySelectorAll('a.nu-btn')).map(function(a){return a.textContent;}).join('|')});
    }, 200);
    """ % int(later.timestamp() * 1000))
    o = _run(tmp_path, js2, query="?ui=new&page=product&product_id=prod_tcam", **KW)
    assert o["cam"] == "在庫未確認（更新待ち）" and "購入する" not in o["buy"]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
@pytest.mark.parametrize("width", [320, 390, 640, 700, 768, 1024, 1440])
def test_dom_product_detail_no_overflow(tmp_path, width):
    js = _PD + """
    var o = {};
    ['buy', 'history', 'changes'].forEach(function(k){
      art().querySelector('[data-nu-pdtab="' + k + '"]').click();
      art().querySelectorAll('details').forEach(function(d){ d.open = true; });
      o[k] = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    });
    done(o);
    """
    o = _run(tmp_path, js, width=width, query="?ui=new&page=product&product_id=prod_tcam", **KW)
    assert o == {"buy": 0, "history": 0, "changes": 0}, o
    o = _run(tmp_path, js, width=width, query="?ui=new&page=product&product_id=prod_tgame", **KW)
    assert o == {"buy": 0, "history": 0, "changes": 0}, o


# ── レビューの指摘への回帰テスト ─────────────────────────────────────────────

def test_history_excludes_other_conditions():
    used = [ob("prod_tcam", "sell", "buyback_price", "BUYBACK_CASH", "買取店A", 170000, _t(hours=1), condition="used_a")]
    h = ph.merge(ph.merge(None, OBS, now=NOW), used, now=NOW)
    assert [p["price"] for p in h["series"]["prod_tcam|buyback|買取店A"]["points"]] == [232000]
    assert not [c for c in ph.changes(h, "prod_tcam") if c["before"] == 170000 or c["after"] == 170000]
    # 書式が違っても同じ時刻の観測は1点（二重に足さない）
    same = [dict(OBS[5], observed_at=(NOW - timedelta(hours=2)).astimezone().isoformat())]
    assert len(ph.merge(h, same, now=NOW)["series"]["prod_tcam|buyback|買取店A"]["points"]) == 1


def test_date_only_lottery_end_is_end_of_day():
    lot = dict(LOTTERY[0], entry_start_at=(NOW - timedelta(days=3)).strftime("%Y-%m-%d"),
               entry_end_at=NOW.strftime("%Y-%m-%d"))                       # 締切は今日（日付だけ）
    v = _catalog_views(legacy_lotteries=[lot])[0]["prod_tgame"]
    types = {c["type"]: c for c in v.changes}
    assert "LOTTERY_CLOSE" not in types                                     # 今日いっぱいは受付中
    assert types["LOTTERY_OPEN"]["changed_at"] == (NOW - timedelta(days=3)).strftime("%Y-%m-%d")   # 時刻を作らない


def test_official_row_uses_only_official_stock_and_unknown_type_hidden():
    stock = json.loads(json.dumps(STOCK))
    e = stock["entries"].pop("official:prod_tcam:s")
    stock["entries"]["shop:prod_tcam:x"] = dict(e, key="shop:prod_tcam:x", source_type="retail_ec", store="別の店")
    v = _catalog_views(stock_history=stock)[0]["prod_tcam"]
    off = v.buy_rows[0]
    assert off.source == "TEST 公式ストア" and off.stock_label == "在庫未確認" and not off.cta_primary
    obs = OBS + [ob("prod_tcam", "buy", "shop_sale_price", "UNKNOWN", "種別不明の店頭", 1000, _t(hours=1))]
    assert "種別不明の店頭" not in [r.source for r in _catalog_views(price_observations=obs)[0]["prod_tcam"].buy_rows]
    stale_unv = OBS + [ob("prod_tcam", "buy", "shop_sale_price", "RETAIL", "古い照合未了", 1000, _t(days=20), exact=False)]
    r = next(r for r in _catalog_views(price_observations=stale_unv)[0]["prod_tcam"].buy_rows if r.source == "古い照合未了")
    assert r.quality == pd.STALE and r.note == "商品照合未完了" and not r.cta_label


def test_reason_names_the_price_used_for_the_decision():
    deal = dict(DEAL, official_price=119980, msrp_evidence="CONFIGURED_REFERENCE")
    v = _catalog_views(profit_deals=[deal])[0]["prod_tcam"]
    assert v.opportunity is None and v.profit_reasons[0].startswith("利益の判定は定価 ¥119,980 で行った結果です")


def test_search_rows_have_no_volatile_state_and_ids_are_encoded():
    from src.content.ui import product_page
    root = shell.render_root(_ctx())
    assert "nu-srow__state" not in _section(root, "search") and 'data-nu-switch="all"' in _section(root, "search")
    assert "product_id=a%26b%3Dc" in product_page.link("a&b=c")


def test_price_history_script_keeps_corrupt_file(tmp_path, monkeypatch):
    uph = _load("uph_p6", ROOT / "scripts" / "update_price_history.py")
    out = tmp_path / "price_history.json"
    out.write_text("{broken", encoding="utf-8")
    monkeypatch.setattr(uph, "OUT_PATH", out)
    monkeypatch.setattr(uph, "NPO_PATH", tmp_path / "none.json")
    assert uph.main() == 1 and out.read_text(encoding="utf-8") == "{broken"


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_status_falls_back_after_lottery_closes(tmp_path):
    later = NOW + timedelta(days=3)
    js = _PD + """
    Date.now = function(){ return %d; };
    window.dispatchEvent(new PageTransitionEvent('pageshow'));
    setTimeout(function(){
      var a = R.querySelector('[data-nu-pd="prod_tgame"]');
      done({st: a.querySelector('[data-nu-pd-status]').textContent.trim(),
            lot: a.querySelector('.nu-pd-lot .nu-badge').textContent.trim()});
    }, 200);
    """ % int(later.timestamp() * 1000)
    o = _run(tmp_path, js, query="?ui=new&page=product&product_id=prod_tgame", **KW)
    fallback = _catalog_views()[0]["prod_tgame"].fallback_label
    assert "受付中" not in o["st"] and o["st"] == fallback == "在庫未確認"   # 締め切られたら在庫の記録からの状態に戻る


def test_official_sale_method_state_from_stock_record():
    """在庫再開に出ない公式の記録（抽選の販売方法など）も、今の状態と公式の行の在庫に出す（購入可能にはしない）。"""
    stock = json.loads(json.dumps(STOCK))
    stock["entries"]["official:prod_gr4:s"] = {"key": "official:prod_gr4:s", "product_id": "prod_gr4",
                                               "product_name": "RICOH GR IV", "state": "LOTTERY",
                                               "last_checked_at": _t(hours=2), "source_type": "official_store"}
    v = _catalog_views(stock_history=stock)[0]["prod_gr4"]
    assert v.status == "SALE_METHOD" and v.status_label == "抽選（公式の販売方法）"
    assert v.buy_rows[0].stock_label == "抽選（公式の販売方法）" and not v.buy_rows[0].cta_primary


def test_shop_sale_method_is_not_called_official():
    """公式ストア以外の在庫の記録を「公式」と書かない。"""
    assert pd._entry_status({"state": "LOTTERY", "source_type": "retail_ec"})[1] == "抽選（店の販売方法）"
    assert pd._entry_status({"state": "LOTTERY", "source_type": "official_store"})[1] == "抽選（公式の販売方法）"


def test_reason_skips_missing_deal_price():
    deal = dict(DEAL, official_price=None, msrp_evidence="CONFIGURED_REFERENCE")
    v = _catalog_views(profit_deals=[deal])[0]["prod_tcam"]
    assert not any("¥0" in r for r in v.profit_reasons)


def test_changes_sort_by_time_within_a_day():
    later = {"changed_at": "2026-10-04T18:00:00+09:00"}
    day = {"changed_at": "2026-10-04"}
    newer_day = {"changed_at": "2026-10-05"}
    early = {"changed_at": "2026-10-04T09:00:00+09:00"}
    got = sorted([early, day, later, newer_day], key=pd._change_order, reverse=True)
    assert got == [newer_day, later, early, day]


def test_chart_single_point_has_no_duplicate_axis():
    from src.content.ui import product_page
    v = pd.ProductDetailView(product_id="p", category="camera", product_name="P")
    v.history = [{"product_id": "p", "kind": "retail", "source": "公式", "points": [{"at": _t(hours=1), "price": 1000}]}]
    svg = product_page._chart(v)
    assert svg.count("¥1,000</text>") == 1 and svg.count('class="nu-hs-ax"') == 2 and 'font-size="24"' in svg


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_search_category_keeps_query(tmp_path):
    js = _PD + """
    var a = R.querySelector('[data-nu-page="search"] a[data-nu-switch="camera"]');
    a.click();
    setTimeout(function(){ done({url: location.search, fs: getComputedStyle(R.querySelector('[data-nu-page="search"]')).display}); }, 100);
    """
    o = _run(tmp_path, js, query="?ui=new&page=search&q=GR", **KW)
    assert "q=GR" in o["url"] and "category=camera" in o["url"]


def test_summary_and_profit_evidence_details():
    """想定純利益が先頭・買う条件と ROI つき。最安仕入の内訳・比較外の数。売却は利益の計算に使った売却先。
    利益の根拠は情報元・確認時刻つき、0円の購入送料も行に出し、固定の前提を見分けられる。値は計算し直さない。"""
    root = shell.render_root(_ctx())
    a = _article(root, "prod_tcam")
    summ = a[a.index('class="nu-pd-summary"'):a.index('role="tablist"')]
    assert summ.index("想定純利益") < summ.index("最安仕入（取得原価）")
    assert "TEST 公式ストアで買い、買取店A（買取価格）に ¥232,000 で売る場合（新品・未開封1台・ROI 15.1%）" in summ
    assert "＋ 送料 無料 ＋ 購入時の費用 なし" in summ and "比較外" in summ
    assert "利益の計算に使った売却価格" in summ and "額面の最高は メルカリ成約・成約中央値 ¥238,000" in summ
    pf = a[a.index('nu-pd-profit'):a.index('id="pd-tcam-buy"')]
    assert "買取ページ" in pf and "購入送料" in pf and "<b>無料</b>" in pf and "前提（固定）" in pf
    assert "根拠のうち一番古い確認" in pf and "+¥30,200" in pf and "15.1%" in pf
    # 仕入価格の確認時刻は表の公式の行と同じ（日付だけの確認日。案件の時刻で新しく見せない）
    off_at = _catalog_views()[0]["prod_tcam"].buy_rows[0].checked_at
    assert len(off_at) == 10 and f'{off_at[5:].replace("-", "/")}確認（日付のみ）' in pf
    assert 'data-nu-pd-jump="pd-tcam-pfbox"' in a and 'id="pd-tcam-pfbox"' in a


def test_header_buy_cta_and_reference_rows_folded():
    root = shell.render_root(_ctx())
    a = _article(root, "prod_tcam")
    head = a[:a.index('class="nu-pd-summary"')]
    # 見出しに買う場所のボタン（在庫ありの期限つき）・在庫と価格の確認時刻・照合に使った情報
    assert "TEST 公式ストアで購入する" in head and "data-nu-pd-until" in head
    assert "在庫 " in head and "価格 " in head and "型番 TC-1" in head and "照合に使った情報" not in head
    buy = a[a.index('id="pd-tcam-buy"'):a.index('id="pd-tcam-sell"')]
    main, more = buy.split('class="nu-pd-morerows"')
    assert "フリマ照合未了" not in main and "フリマ照合未了" in more and "参考の仕入れ先" in more
    sell = a[a.index('id="pd-tcam-sell"'):]
    # 主なボタンは利益の計算に使った売却先だけ
    row_a = sell[sell.index("買取店A"):]
    row_a = row_a[:row_a.index("</tr>")]
    assert "利益の計算に使った売却先" in row_a and "nu-btn--primary" in row_a
    row_m = sell[sell.index("メルカリ成約"):]
    assert "nu-btn--primary" not in row_m[:row_m.index("</tr>")]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_jump_to_profit_and_relative_time_with_absolute(tmp_path):
    js = _PD + """
    var a = R.querySelector('[data-nu-pd="prod_tcam"]');
    a.querySelector('[data-nu-pd-jump]').click();
    setTimeout(function(){
      var t = a.querySelector('.nu-pd-state [data-nu-time]');
      done({url: location.search, sel: a.querySelector('[data-nu-pdtab="buy"]').getAttribute('aria-selected'),
            focus: document.activeElement.id, time: t ? t.textContent : ''});
    }, 150);
    """
    o = _run(tmp_path, js, query="?ui=new&page=product&product_id=prod_tcam&tab=history", **KW)
    assert o["sel"] == "true" and o["focus"] == "pd-tcam-pfbox" and "tab=history" not in o["url"]   # 買う・売るのタブに切り替わる
    assert re.search(r"分前確認（本日 \d\d:\d\d）", o["time"])

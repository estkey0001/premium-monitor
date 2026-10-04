"""UI Phase 5（せどりルート）のテスト。

確定ルートは、売値が買取か条件を満たす成約中央値で、両側の商品の同一性・状態・費用がそろったものだけであること、
出品価格（LISTING）が確定ルートや利益にならないことを確かめる。データはテスト用の架空のもの。
"""

from __future__ import annotations

import importlib.util
import re
from datetime import timedelta
from pathlib import Path

import pytest

from src.content.ui import opportunity as opp
from src.content.ui import route_view as rtv
from src.content.ui import shell


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_P1 = _load("ui_phase1_helpers_p5", Path(__file__).with_name("test_ui_phase1.py"))
CHROME, _HELPERS, _run, _section = _P1.CHROME, _P1._HELPERS, _P1._run, _P1._section
NOW = _P1.NOW


def _t(**kw) -> str:
    return (NOW + timedelta(**kw)).isoformat()


def route(pid, sell_type="SOLD_MEDIAN", buy=100000, sell=150000, **kw):
    fee = int(sell * 0.1)
    net = sell - buy - fee - 1500 - 3000
    r = {"product_id": pid, "product_name": f"商品{pid}", "buy_source": "家電量販店X", "sell_source": "メルカリ（成約）",
         "buy_price": buy, "sell_price": sell, "net_profit": net, "roi": net / buy, "platform_fee": fee, "payment_fee": 0,
         "fx_buffer": 0, "shipping_cost": 1500, "safety_margin": 3000, "buy_shipping": 0, "buy_required_cost": 0, "route_confidence": "high",
         "buy_price_evidence": "VERIFIED_CURRENT", "sell_price_evidence": "VERIFIED_CURRENT",
         "sell_canonical_type": sell_type, "buy_canonical_type": "RETAIL", "buy_condition": "new_unopened",
         "sell_condition": "new_unopened", "buy_exact_match": True, "sell_exact_match": True,
         "sell_sample_count": 14, "sell_period": "09/03〜10/02", "sell_period_start": _t(days=-30),
         "sell_period_end": _t(hours=-2), "sell_min": sell - 10000, "sell_max": sell + 12000,
         "buy_observed_at": _t(hours=-3), "sell_observed_at": _t(hours=-2), "buy_url": "https://www.example-store.jp/i/1",
         "buy_item_url": "https://www.example-store.jp/i/1", "sell_url": "https://jp.mercari.com/search?keyword=x",
         "buy_link_type": "item"}
    r.update(kw)
    return r


def _set(*routes, genres=None):
    return opp.build(deals=[], routes=list(routes), product_genres=genres or {}, now=NOW)


def _types(*routes):
    return [rv.route_type for rv in rtv.build(_set(*routes))]


# ── 確定ルートの条件 ─────────────────────────────────────────────────

def test_retail_to_sold_median_eligible():
    assert _types(route("a")) == [rtv.RETAIL_TO_SOLD_MEDIAN]


def test_secondary_to_sold_median_eligible():
    r = route("b", buy_canonical_type="LISTING", buy_condition="used_a", sell_condition="used_a",
              buy_item_url="https://jp.mercari.com/item/m48213579146")
    assert _types(r) == [rtv.SECONDARY_TO_SOLD_MEDIAN]


@pytest.mark.parametrize("mutate, reason", [
    (dict(sell_canonical_type="LISTING"), "sell_type_listing"),                 # 出品を成約にしない
    (dict(sell_canonical_type="UNKNOWN"), "sell_type_unknown"),
    (dict(sell_sample_count=2), "insufficient_sold_samples"),                   # 件数 3 → 2
    (dict(sell_period=""), "insufficient_sold_samples"),                        # 期間を消す
    (dict(buy_observed_at=_t(days=-15)), "stale_buy_price"),
    (dict(sell_observed_at=_t(days=-15)), "stale_sell_price"),
    (dict(buy_exact_match=False), "buy_identity_unverified"),                   # 商品違い
    (dict(sell_exact_match=False), "sell_identity_unverified"),
    (dict(sell_condition="used_a"), "condition_mismatch"),                      # 状態違い
    (dict(buy_condition=""), "condition_mismatch"),
    (dict(platform_fee=None), "costs_unknown"),                                 # 手数料を0円にしない
    (dict(buy_shipping=None), "costs_unknown"),                                 # 購入送料を0円にしない
    (dict(buy_canonical_type="LISTING", buy_item_url=""), "buy_not_item_level"),  # 検索結果の出品価格では買えない
    (dict(buy_shipping=2000), "breakdown_mismatch"),                            # 送料が純利益に入っていない（利益が大きく出る）
    (dict(buy_required_cost=None), "costs_unknown"),                            # 購入時の費用を0円にしない
    (dict(buy_canonical_type="SOLD"), "buy_type_sold"),                         # 成約価格では仕入れられない
    (dict(buy_canonical_type="SOLD_MEDIAN"), "buy_type_sold"),
    (dict(buy_condition="unused"), "condition_mismatch"),                       # 未使用品と新品を組み合わせない
    (dict(buy_condition="used_a", sell_condition="used_a", buy_item_url=""), "buy_not_item_level"),  # 中古で買うなら商品ページ
])
def test_mutations_exclude_route(mutate, reason):
    s = _set(route("a", **mutate))
    assert not s.eligible and reason in s.ineligible[0].reasons, s.ineligible[0].reasons


def test_sample_count_three_is_eligible():
    assert _types(route("a", sell_sample_count=3)) == [rtv.RETAIL_TO_SOLD_MEDIAN]


def test_buyback_routes_are_secondary_tab():
    rvs = rtv.build(_set(route("c", "BUYBACK_CASH", sell_sample_count=None, sell_period="")))
    assert [rv.route_type for rv in rvs] == [rtv.RETAIL_TO_BUYBACK] and rvs[0].tab == "other"


def test_live_amazon_search_route_is_not_confirmed():
    """本番の生成物にあった、検索結果の出品価格（商品の照合が未了）から作られたルートは確定にしない。"""
    r = route("prod_gr4", "BUYBACK_CASH", buy=107491, sell=151000, buy_canonical_type="LISTING",
              buy_source="Amazon JP (新品出品)", buy_exact_match=False, sell_exact_match=False, buy_item_url="",
              buy_url="https://www.amazon.co.jp/s?k=RICOH%20GR%20IV")
    s = _set(r)
    assert not s.eligible and {"buy_identity_unverified", "buy_not_item_level"} <= set(s.ineligible[0].reasons)


def test_duplicate_routes_merged_and_profit_not_recalculated():
    r = route("a")
    rvs = rtv.build(_set(r, dict(r)))
    assert len(rvs) == 1 and rvs[0].net_profit == r["net_profit"] and abs(rvs[0].roi - r["net_profit"] / 100000) < 1e-9


# ── 出品価格の参考 ───────────────────────────────────────────────────

OBS = [{"product_id": "a", "product_name": "商品a", "price_type": "flea_listing_price", "canonical_price_type": "LISTING",
        "source_name": "メルカリ", "price": 160000, "sample_count": 20, "observed_at": _t(hours=-5),
        "freshness_basis": "observed", "source_url": "https://jp.mercari.com/search?keyword=a", "is_exact_product_match": True,
        "condition": "new_unopened"},
       {"product_id": "a", "product_name": "商品a", "price_type": "overseas_listing_price", "canonical_price_type": "UNKNOWN",
        "source_name": "eBay sold(新品)", "price": 170000, "observed_at": _t(days=-20), "freshness_basis": "observed_stale",
        "is_exact_product_match": True, "rejection_reason": "stale_over_14d",
        "source_url": "https://www.ebay.com/sch/i.html?_nkw=a&LH_Sold=1"},
       # 付属品・照合未了・古すぎるものは参考にも出さない
       {"product_id": "a", "product_name": "商品a", "price_type": "shop_sale_price", "canonical_price_type": "LISTING",
        "source_name": "Amazon JP", "price": 7868, "observed_at": _t(hours=-5), "freshness_basis": "observed",
        "is_exact_product_match": False, "accessory_flag": True, "rejection_reason": "accessory_or_wrong_product"},
       {"product_id": "a", "product_name": "商品a", "price_type": "shop_sale_price", "canonical_price_type": "LISTING",
        "source_name": "楽天", "price": 107491, "observed_at": _t(hours=-5), "freshness_basis": "observed",
        "is_exact_product_match": False, "product_match_reason": "unverified_title_price_band_pending"},
       {"product_id": "a", "product_name": "商品a", "price_type": "flea_listing_price", "canonical_price_type": "LISTING",
        "source_name": "ラクマ", "price": 150000, "observed_at": _t(days=-43), "freshness_basis": "observed_stale",
        "is_exact_product_match": True},
       {"product_id": "a", "product_name": "商品a", "price_type": "buyback_price", "canonical_price_type": "BUYBACK_CASH",
        "source_name": "買取店", "price": 140000, "observed_at": _t(hours=-1), "freshness_basis": "observed"}]


def test_listing_refs_are_reference_only():
    refs = rtv.listing_refs(OBS, {"a": "camera"}, now=NOW)
    assert [(r.marketplace, r.price, r.stale) for r in refs] == [("メルカリ", 160000, False), ("eBay", 170000, True)]
    assert refs[1].url == "" and refs[0].condition == "新品未開封"           # 成約の検索ページへのリンクは付けない
    root = shell.render_root(_P1._ctx(price_observations=OBS, product_genres={"a": "camera"}, profit_routes={"main_routes": []}))
    sec = _section(root, "routes")
    ref = sec[sec.index('class="nu-refs"'):]
    assert "出品価格の参考" in ref and "参考情報" in ref and "eBay（出品）" in ref and "sold" not in ref.lower()
    lst = ref[ref.index("data-nu-ref-list"):]
    assert "ROI" not in lst and "純利益" not in lst                               # 参考欄の一覧に利益・ROI を出さない
    assert 'data-nu-count="routes">0件' in root                                   # 参考は件数に数えない


def test_detail_shows_listing_vs_sold_and_breakdown():
    root = shell.render_root(_P1._ctx(profit_routes={"main_routes": [route("a")]}, product_genres={"a": "camera"}))
    sec = _section(root, "routes")
    row = re.search(r'data-nu-route=.*?</article>', sec, re.S).group(0)
    assert "成約中央値・14件" in row and "最安 ¥140,000 ／ 最高 ¥162,000" in row
    assert "＝ 想定純利益" in row and "− 購入送料" in row and "必要な仕入れ資金（取得原価）" in row
    assert "仕入先を見る" in row and "正規店 → 二次流通" in row


# ── 画面の操作（時計を止めた Chrome） ─────────────────────────────────────

_RT = _HELPERS + """
function vis(){ return [].slice.call(R.querySelectorAll('[data-nu-route-list] > [data-nu-route]')).filter(function(e){return !e.hidden;})
  .map(function(e){return e.getAttribute('data-nu-route');}); }
function res(){ return R.querySelector('[data-nu-tresult]').textContent; }
"""


def _many():
    rs = []
    for i in range(21):
        rs.append(route(f"c{i:02d}", buy=100000, sell=150000 + i * 1000, sell_sample_count=3 + i))
    rs.append(route("g1", buy_canonical_type="LISTING", buy_condition="used_a", sell_condition="used_a", buy=40000,
                    sell=70000, buy_source="フリマY", buy_item_url="https://jp.mercari.com/item/m48213579146"))
    rs.append(route("o1", "BUYBACK_CASH", buy=50000, sell=60000, sell_sample_count=None, sell_period="",
                    sell_source="買取店Z", platform_fee=0, net_profit=5500, roi=0.11))
    return rs


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_tabs_sort_filter_search_pagination_history(tmp_path):
    genres = {f"c{i:02d}": "camera" for i in range(21)} | {"g1": "game_console", "o1": "iphone"}
    js = _RT + """
    var o = {};
    o.all = res(); o.p2 = click('[data-nu-tpager] a[href*="page_num=2"]'); o.p2n = vis().length;
    o.sec = click('a[data-nu-tparam="tab"][data-nu-tvalue="secondary"]'); o.secIds = vis();
    o.other = click('a[data-nu-tparam="tab"][data-nu-tvalue="other"]'); o.otherIds = vis();
    o.retail = click('a[data-nu-tparam="tab"][data-nu-tvalue="retail"]'); o.retailRes = res();
    o.samples = click('a[data-nu-tparam="sort"][data-nu-tvalue="samples"]'); o.samplesFirst = vis()[0];
    o.roi = click('a[data-nu-tparam="filter"][data-nu-tvalue="highroi"]'); o.roiRes = res();
    o.game = click('[data-nu-page="routes"] a[data-nu-switch="game"]');          // ゲームの正規→二次は無い
    o.emptyShown = !R.querySelector('[data-nu-tempty="nomatch"]').hidden;
    o.cat = click('[data-nu-page="routes"] a[data-nu-switch="camera"]');
    o.soon = !!R.querySelector('[data-nu-page="routes"] .nu-chip--soon[aria-disabled="true"]');
    o.clear = click('a[data-nu-tparam="filter"][data-nu-tvalue="highroi"]');
    R.querySelector('[data-nu-page="routes"] [data-nu-search-toggle]').click();
    var inp = R.querySelector('[data-nu-page="routes"] [data-nu-search-input]');
    inp.value = '商品c05'; inp.dispatchEvent(new Event('input', {bubbles: true}));
    setTimeout(function(){
      o.search = vis(); history.back();
      setTimeout(function(){ o.back = state(); done(o); }, 80);
    }, 400);
    """
    o = _run(tmp_path, js, query="?ui=new&page=routes", profit_routes={"main_routes": _many()},
             product_genres=genres, legacy_lotteries=[], profit_deals=[])
    assert o["all"] == "23件中 1〜20件" and o["p2n"] == 3
    assert len(o["secIds"]) == 1 and "g1" in o["secIds"][0]          # 二次 → 二次
    assert len(o["otherIds"]) == 1 and "o1" in o["otherIds"][0]
    assert o["retailRes"] == "21件中 1〜20件" and "c20" in o["samplesFirst"]
    # 高ROI（20%以上）: 正規→二次の21件はどれも ROI 20% 以上。ゲームに切り替えると0件 → 条件に合うもの無しの空状態
    assert o["roiRes"] == "21件中 1〜20件" and o["emptyShown"] is True and o["soon"] is True   # 在庫確認済みは準備中
    assert o["search"] and all("c05" in x for x in o["search"])
    assert o["back"]["q"].startswith("?ui=new&page=routes") and "category=camera" in o["back"]["q"]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_home_parity(tmp_path):
    genres = {f"c{i:02d}": "camera" for i in range(21)} | {"g1": "game_console", "o1": "iphone"}
    js = _RT + """
    var o = {};
    o.home = R.querySelector('.nu-purposes [data-nu-count="routes"]') ? R.querySelector('.nu-purposes [data-nu-count="routes"]').textContent : null;
    o.go = click('.nu-topnav a[data-nu-nav="routes"]'); o.list = vis().length;
    o.cam = click('[data-nu-page="routes"] a[data-nu-switch="game"]'); o.game = vis().length;
    o.count = R.querySelector('[data-nu-count="routes"]').textContent;
    done(o);
    """
    o = _run(tmp_path, js, profit_routes={"main_routes": _many()}, product_genres=genres, legacy_lotteries=[], profit_deals=[])
    assert o["list"] == 20 and o["count"] == "1件" and o["game"] == 1      # 1ページ目は20件（全23件）


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
@pytest.mark.parametrize("width", [320, 390, 640, 700, 768, 1024, 1440])
def test_dom_routes_no_overflow(tmp_path, width):
    js = _RT + """
    var o = {s: state()};
    R.querySelectorAll('[data-nu-route-list] details').forEach(function(d){ d.open = true; });
    o.open = state();
    o.cta = [].slice.call(R.querySelectorAll('[data-nu-page="routes"] a.nu-btn')).filter(function(a){return a.offsetParent;})
             .map(function(a){return Math.round(a.getBoundingClientRect().height);});
    done(o);
    """
    o = _run(tmp_path, js, width=width, query="?ui=new&page=routes", profit_routes={"main_routes": _many()[:4]},
             price_observations=OBS, product_genres={"a": "camera"}, legacy_lotteries=[], profit_deals=[])
    for st in (o["s"], o["open"]):
        assert st["sw"] == st["cw"] and st["inner"] == [], (width, st)
    assert o["cta"] and min(o["cta"]) >= 44


def test_no_profit_math_in_router():
    """利益・ROI はブラウザで計算しない（router は data-profit / data-roi の確定値を並べ替えに使うだけ）。"""
    root = shell.render_root(_P1._ctx(profit_routes={"main_routes": [route("a")]}, product_genres={"a": "camera"}))
    block = root[root.index("function renderRoutes"):root.index("function render(")]
    # 売値・仕入れ値・費用の属性を読まない（利益を組み立てる材料が無い）
    for word in ("sell_price", "buy_price", "data-sell", "data-buy", "fee", "shipping"):
        assert word not in block, word
    assert "data-profit" in block and "data-roi" in block

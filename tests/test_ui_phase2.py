"""UI Phase 2（利益商品の一覧）のテスト。

掲載の判定（opportunity.eligibility）・値をそのまま描画すること・HOME の件数との一致・
並べ替え／絞り込み／検索／ページ切り替え／TOP10／戻る・進む・横はみ出し（ヘッドレス Chrome）を確かめる。
データはテスト用の架空のもの（本番の生成物には入らない）。
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

import pytest

from src.content.ui import opportunity as opp
from src.content.ui import shell
from src.tcg.models import JST

def _load_phase1():
    """Phase 1 のテストのブラウザ実行の部品（_run など）を使う（tests はパッケージではないのでパスで読む）。"""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("ui_phase1_helpers", Path(__file__).with_name("test_ui_phase1.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_P1 = _load_phase1()
CHROME, _HELPERS, _run, _section = _P1.CHROME, _P1._HELPERS, _P1._run, _P1._section

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=JST)


def _iso(**kw) -> str:
    return (NOW - timedelta(**kw)).isoformat()


def deal(pid, name, genre="camera", off=200000, sell=230000, *, net=None, stock="在庫あり", checked=None,
         ev="VERIFIED_DATED", level="beginner_easy", resale=False):
    return {"product_id": pid, "title": name, "genre": genre, "official_price": off,
            "official_checked_at": _iso(days=2), "msrp_evidence": ev, "stock_status": stock, "sale_method": "normal",
            "sell_shop": "買取店A", "sell_price": sell, "sell_checked_at": checked or _iso(hours=1),
            "net_profit": (sell - off - 1800) if net is None else net, "user_level": level, "resale_sell": resale,
            "official_url": "https://www.apple.com/jp/shop/", "sell_url": "https://kaitori.example.jp/item/1"}


def route(pid, name, sell_type="BUYBACK_CASH", *, samples=None, period="", buy=60000, sell=78000, **kw):
    r = {"product_id": pid, "product_name": name, "buy_source": "中古店X", "sell_source": "買取店Y",
         "buy_price": buy, "sell_price": sell, "net_profit": sell - buy - 4500, "roi": (sell - buy - 4500) / buy,
         "platform_fee": 0, "payment_fee": 0, "fx_buffer": 0, "shipping_cost": 1500, "safety_margin": 3000,
         "route_confidence": "high", "buy_price_evidence": "VERIFIED_CURRENT", "sell_price_evidence": "VERIFIED_CURRENT",
         "sell_canonical_type": sell_type, "sell_sample_count": samples, "sell_period": period,
         "buy_observed_at": _iso(hours=2), "sell_observed_at": _iso(hours=2), "buy_canonical_type": "RETAIL"}
    r.update(kw)
    return r


def _set(deals=(), routes=(), genres=None):
    return opp.build(deals=list(deals), routes=list(routes), product_genres=genres or {}, now=NOW)


# ── 掲載の判定 ───────────────────────────────────────────────────

def test_eligible_opportunity_appears_with_existing_values():
    s = _set([deal("prod_a", "RICOH GR IV")])
    v, = s.eligible
    assert v.net_profit == 28200 and v.buy_price == 200000 and v.sell_price == 230000
    # 費用の内訳（DEFAULT_COSTS）が既存の純利益と一致し、ROI = 純利益 ÷ 取得原価
    assert v.breakdown_ok and sum(a for _l, a in v.cost_lines) == 1800
    assert v.acquisition_cost == 200000 and abs(v.roi - 28200 / 200000) < 1e-9
    assert v.sell_type_label == "買取価格" and v.stock_label == "在庫あり"


@pytest.mark.parametrize("bad, reason", [
    (route("p1", "出品だけ", "LISTING"), "sell_type_listing"),
    (route("p2", "種別不明", "UNKNOWN"), "sell_type_unknown"),
    (route("p3", "成約が少ない", "SOLD_MEDIAN", samples=2, period="過去30日"), "insufficient_sold_samples"),
    (route("p4", "期間なし", "SOLD_MEDIAN", samples=10), "insufficient_sold_samples"),
    (route("p5", "古い仕入れ値", buy_observed_at=(NOW - timedelta(days=20)).isoformat()), "stale_buy_price"),
    (route("p6", "参考ルート", reference_route=True), "route_flagged"),
    (route("p7", "根拠の無い仕入れ", buy_price_evidence="CONFIGURED_REFERENCE"), "buy_configured_reference"),
    (route("p8", "利益なし", net_profit=0), "no_profit"),
    (route("p9", "極端なROI", sell=500000, net_profit=430000, roi=7.2), "roi_out_of_range"),
])
def test_ineligible_routes_hidden(bad, reason):
    s = _set(routes=[bad])
    assert not s.eligible and reason in s.ineligible[0].reasons


@pytest.mark.parametrize("bad, reason", [
    (deal("p1", "確認日不明の定価", ev="CONFIGURED_REFERENCE"), "buy_configured_reference"),
    (deal("p2", "古い買取価格", checked=(NOW - timedelta(days=15)).isoformat()), "stale_sell_price"),
    (deal("p3", "確認日なし", checked=""), "stale_sell_price"),
    (deal("p4", "フリマへ売る", resale=True), "resale_sell"),
    (deal("p5", "監視中", level="monitoring"), "monitoring"),
])
def test_ineligible_deals_hidden(bad, reason):
    bad = dict(bad)
    if reason == "stale_sell_price" and bad["title"] == "確認日なし":
        bad["sell_checked_at"] = ""
    s = _set([bad])
    assert not s.eligible and reason in s.ineligible[0].reasons


def test_sold_median_route_eligible_with_period_and_samples():
    s = _set(routes=[route("prod_sw", "Switch 2", "SOLD_MEDIAN", samples=14, period="過去30日")],
             genres={"prod_sw": "game_console"})
    v, = s.eligible
    assert v.kind == "to_sold_median" and v.category == "game" and v.sell_type_label == "成約中央値"
    root = shell.render_root(_ctx(deals=[], routes=[route("prod_sw", "Switch 2", "SOLD_MEDIAN", samples=14,
                                                            period="過去30日")], genres={"prod_sw": "game_console"}))
    assert "成約中央値・過去30日 / 14件" in _section(root, "opportunities")


def test_costs_unknown_is_not_zero():
    r = route("p1", "送料不明", shipping_cost=None)
    s = _set(routes=[r])
    assert not s.eligible and "costs_unknown" in s.ineligible[0].reasons


def test_breakdown_mismatch_shows_total_only():
    d = deal("prod_a", "合計だけ", net=20000)                 # 内訳の合計（1,800）と合わない純利益
    v, = _set([d]).eligible
    assert not v.breakdown_ok
    html = _section(shell.render_root(_ctx(deals=[d])), "opportunities")
    assert "費用の内訳は算出前です" in html and "+¥20,000" in html


def test_one_view_per_product_keeps_best_eligible():
    s = _set([deal("prod_a", "A", sell=240000), deal("prod_a", "A", sell=230000),
              deal("prod_a", "A", sell=300000, ev="CONFIGURED_REFERENCE")])
    assert [v.net_profit for v in s.eligible] == [38200]


# ── 描画（値をそのまま）・HOME との一致 ────────────────────────────────

def _ctx(deals=None, routes=None, genres=None, **kw):
    args = dict(tcg_report={"lotteries": [], "events": []}, opportunities={},
                profit_routes={"main_routes": routes if routes is not None else []}, legacy_lotteries=[],
                updated_text="10/03 12:00", now=NOW, profit_deals=deals if deals is not None else [],
                product_genres=genres or {})
    args.update(kw)
    return shell.ShellContext(**args)


MANY_DEALS = ([deal(f"prod_c{i}", f"カメラ{i:02d} とても長い商品名の限定ではない通常版ボディ", "camera", 100000 + i * 1000,
                    112000 + i * 1300, checked=_iso(hours=i)) for i in range(23)]
              + [deal("prod_ip", "iPhone 17 Pro 256GB", "iphone", 179800, 205000, stock="SOLD OUT"),
                 deal("prod_mb", "MacBook Air 13 M4", "pc", 164800, 178000, stock="")])


def test_home_count_parity_and_rendering():
    root = shell.render_root(_ctx(MANY_DEALS))
    sec = _section(root, "opportunities")
    rows = re.findall(r'<tr class="nu-orow" data-nu-oid="[^"]+" data-nu-cat="([a-z]+)"', sec)
    cards = re.findall(r'<li class="nu-ocard" data-nu-oid="[^"]+" data-nu-cat="([a-z]+)"', sec)
    assert len(rows) == len(cards) == 25
    # HOME の「利益商品 ○件」・ジャンルの件数と一覧の件数が一致（ジャンルを選んだときもブラウザが同じ土台から数える）
    assert 'data-nu-count="opportunities">25件' in root
    data = re.search(r'id="nu-catalog">(.*?)</script>', root).group(1)
    import json
    static = json.loads(data)["static"]["opportunities"]
    for k in ("camera", "smartphone", "pc"):
        assert static[k] == rows.count(k)
    # テーブル: 列見出しに scope、金額は右揃えの列、想定純利益・ROI・在庫・確認時刻
    for col in ("商品", "ジャンル", "買う場所", "仕入価格", "売る場所", "売却価格", "想定純利益", "ROI", "在庫・状態", "情報確認"):
        assert 'scope="col"' in sec and f">{col}</th>" in sec
    assert sec.count('class="nu-num nu-profit"') == 25 and "在庫切れ" in sec and "在庫未確認" in sec
    # カード: 買う・売る・想定純利益・ROI・確認時刻・詳細（1段だけ）
    card = sec[sec.index('<li class="nu-ocard"'):]
    card = card[:card.index("</li>")]
    for w in ("<dt>買う</dt>", "<dt>売る</dt>", "想定純利益", "ROI", "data-nu-time=", 'aria-expanded="false"'):
        assert w in card
    assert card.count("<details") == 0                       # 入れ子の開閉を使わない


def test_empty_state_real_zero():
    sec = _section(shell.render_root(_ctx([])), "opportunities")
    assert "現在、条件を満たす利益商品はありません" in sec and "別のジャンルを見る" in sec
    assert 'data-nu-count="opportunities">0件' in shell.render_root(_ctx([]))
    for w in ("sold data", "collector", "API", "HTTP", "parser"):
        assert w not in sec


# ── ブラウザで動かす（Chrome） ─────────────────────────────────────────

_OPP = _HELPERS + """
function vis(){ return [].slice.call(R.querySelectorAll('tr.nu-orow')).filter(function(r){return !r.hidden;})
  .map(function(r){return r.getAttribute('data-nu-oid');}); }
function visCards(){ return [].slice.call(R.querySelectorAll('li.nu-ocard')).filter(function(c){return !c.hidden;})
  .map(function(c){return c.getAttribute('data-nu-oid');}); }
function res(){ return R.querySelector('[data-nu-oresult]').textContent; }
"""


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_sort_filter_search_pagination_and_history(tmp_path):
    js = _OPP + """
    var o = {};
    o.rec = vis(); o.recRes = res(); o.pagerLinks = R.querySelectorAll('[data-nu-pager] a').length;
    o.page2 = click('[data-nu-pager] a[href*="page_num=2"]'); o.p2 = vis(); o.p2Res = res();
    o.profit = click('a[data-nu-oparam="sort"][data-nu-ovalue="profit"]'); o.profitIds = vis().slice(0, 3);
    o.roi = click('a[data-nu-oparam="sort"][data-nu-ovalue="roi"]'); o.roiIds = vis().slice(0, 3);
    o.upd = click('a[data-nu-oparam="sort"][data-nu-ovalue="updated"]'); o.updIds = vis().slice(0, 3);
    o.instock = click('a[data-nu-oparam="filter"][data-nu-ovalue="instock"]'); o.instockIds = vis();
    o.cam = click('[data-nu-page="opportunities"] a[data-nu-switch="camera"]'); o.camRes = res();
    R.querySelector('[data-nu-search-toggle]').click();
    o.formOpen = !R.querySelector('[data-nu-search-form]').hidden;
    var inp = R.querySelector('[data-nu-search-input]'); inp.value = 'カメラ05'; inp.dispatchEvent(new Event('input', {bubbles: true}));
    setTimeout(function(){
      o.search = state(); o.searchIds = vis(); o.searchCards = visCards();
      history.back();
      setTimeout(function(){ o.back = state(); o.backIds = vis().length;
        history.back();
        setTimeout(function(){ o.back2 = state(); history.forward();
          setTimeout(function(){ o.fwd = state(); done(o); }, 80); }, 80); }, 80);
    }, 400);
    """
    o = _run(tmp_path, js, query="?ui=new&page=opportunities", profit_deals=MANY_DEALS, profit_routes={"main_routes": []},
             legacy_lotteries=[], tcg_report={"lotteries": [], "events": []})
    # おすすめ（在庫あり → 既存の確かさ → 利益）で 20件 / ページ、25件なら2ページ
    assert len(o["rec"]) == 20 and o["recRes"] == "25件中 1〜20件" and o["pagerLinks"] >= 3
    assert o["page2"]["q"] == "?ui=new&page=opportunities&page_num=2" and len(o["p2"]) == 5
    assert o["p2Res"] == "25件中 21〜25件"
    # 利益が高い順・ROI が高い順・更新が新しい順
    assert o["profitIds"][0] == "deal:prod_ip" and o["profit"]["q"] == "?ui=new&page=opportunities&sort=profit"
    assert o["roiIds"][0] == "deal:prod_c22"
    assert o["updIds"][0] == "deal:prod_c0"
    # 在庫あり（公式の在庫表示が「在庫あり」のものだけ。在庫切れ・未確認は除く）
    assert "deal:prod_ip" not in o["instockIds"] and "deal:prod_mb" not in o["instockIds"] and len(o["instockIds"]) == 20
    assert o["instock"]["q"] == "?ui=new&page=opportunities&sort=updated&filter=instock"
    assert o["cam"]["q"] == "?ui=new&page=opportunities&sort=updated&filter=instock&category=camera"
    assert o["camRes"].startswith("23件中")
    # 一覧内の検索（URL の q=・テーブルとカードの両方）
    assert o["formOpen"] is True and "q=%E3%82%AB" in o["search"]["q"]
    assert o["searchIds"] == ["deal:prod_c5"] and o["searchCards"] == ["deal:prod_c5"]
    # 戻る・進む（検索は同じ履歴の中で更新するので、戻るとジャンルを選ぶ前の状態）
    assert o["back"]["q"] == "?ui=new&page=opportunities&sort=updated&filter=instock" and o["backIds"] == 20
    assert o["back2"]["q"] == "?ui=new&page=opportunities&sort=updated"
    assert o["fwd"]["q"] == "?ui=new&page=opportunities&sort=updated&filter=instock"


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_top10_from_home_and_category(tmp_path):
    js = _OPP + """
    var o = {};
    o.cat = click('a[data-nu-cat-link="camera"]');
    o.top = click('a.nu-quick[href*="top=10"]'); o.topIds = vis(); o.topRes = res();
    o.note = !R.querySelector('[data-nu-topnote]').hidden;
    o.detail = (function(){ var b = R.querySelector('tr.nu-orow:not([hidden]) [data-nu-toggle]'); b.click();
      return [b.getAttribute('aria-expanded'), !document.getElementById(b.getAttribute('aria-controls')).hidden]; })();
    done(o);
    """
    o = _run(tmp_path, js, profit_deals=MANY_DEALS, profit_routes={"main_routes": []}, legacy_lotteries=[],
             tcg_report={"lotteries": [], "events": []})
    assert o["top"]["q"] == "?ui=new&page=opportunities&top=10&category=camera"
    assert len(o["topIds"]) == 10 and o["topIds"][0] == "deal:prod_c22" and o["topRes"].startswith("上位10件")
    assert o["note"] is True and o["detail"] == ["true", True]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
@pytest.mark.parametrize("width", [320, 390, 640, 700, 768, 1024, 1200, 1440])
def test_dom_opportunities_no_overflow_and_layout(tmp_path, width):
    js = _OPP + """
    var o = {s: state(), table: getComputedStyle(R.querySelector('.nu-otable-wrap')).display,
             cards: getComputedStyle(R.querySelector('.nu-ocards')).display};
    R.querySelectorAll('[data-nu-toggle]').forEach(function(b){ if (b.offsetParent) b.click(); });
    o.open = state();
    done(o);
    """
    o = _run(tmp_path, js, width=width, query="?ui=new&page=opportunities", profit_deals=MANY_DEALS,
             profit_routes={"main_routes": []}, legacy_lotteries=[], tcg_report={"lotteries": [], "events": []})
    for st in (o["s"], o["open"]):
        assert st["sw"] == st["cw"], (width, st["sw"], st["cw"])
        assert st["inner"] == [], (width, st["inner"])
    # 1200px 以上はテーブル、未満はカード（モバイルでテーブルを横スクロールさせない）
    assert (o["table"], o["cards"]) == (("block", "none") if width >= 1200 else ("none", "grid"))


# ── レビュー指摘の再発防止 ───────────────────────────────────────────

def test_stock_older_than_7_days_is_unconfirmed():
    """公式の在庫表示は確認から7日を過ぎたら「在庫未確認」（古い「在庫あり」を出さない）。"""
    old = dict(deal("prod_a", "古い在庫表示"), official_checked_at=_iso(days=8))
    new = deal("prod_b", "新しい在庫表示")
    s = {v.product_id: v for v in _set([old, new]).eligible}
    assert s["prod_a"].stock_label == "在庫未確認" and s["prod_b"].stock_label == "在庫あり"
    html = _section(shell.render_root(_ctx(deals=[new])), "opportunities")
    assert "在庫あり（" in html and "時点）" in html          # 詳細に在庫を確認した日時


def test_reservation_and_lottery_never_in_stock():
    for method, label in (("reservation", "予約"), ("lottery", "抽選")):
        v = opp.stock_from("在庫あり", method)
        assert v != "IN_STOCK" and opp.STOCK_LABELS[v] == label


def test_buy_source_names_brand_store_and_condition():
    d = dict(deal("prod_a", "RICOH GR IV"), brand="RICOH")
    v, = _set([d]).eligible
    assert v.buy_source == "RICOH 公式ストア" and v.buy_price_label == "定価"
    r = route("prod_r", "α7 IV", buy_condition="used_a")
    w, = _set(routes=[r]).eligible
    assert w.buy_price_label.startswith("販売価格・")


def test_buy_type_unknown_route_hidden():
    s = _set(routes=[route("p1", "仕入れ種別不明", buy_canonical_type="UNKNOWN")])
    assert not s.eligible and "buy_type_unknown" in s.ineligible[0].reasons


def test_real_make_route_output_sold_median_without_period_is_hidden():
    """generate_profit_routes._make_route の実際の出力で判定する（集計期間が無い成約中央値は掲載しない）。"""
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location(
        "gpr", Path(__file__).resolve().parents[1] / "scripts" / "generate_profit_routes.py")
    g = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(g)
    base = dict(product_id="prod_sw", product_name="Switch 2", condition="used", observed_at=NOW.isoformat(),
                freshness_basis="observed", confidence="high")
    buy = dict(base, source_name="中古店X", source_id="x", price=40000, price_type="used_sale_price",
               canonical_price_type="RETAIL", item_url="https://shop.example.jp/1")
    sell = dict(base, source_name="フリマ", source_id="m", price=60000, price_type="sold_price",
                sold_median_eligible=True, sample_count=12)
    r = g._make_route(buy, sell, NOW)
    assert r["sell_canonical_type"] == "SOLD_MEDIAN" and r["sell_sample_count"] == 12 and r["sell_period"] == ""
    s = _set(routes=[r])
    assert not s.eligible and "insufficient_sold_samples" in s.ineligible[0].reasons
    # 集計期間が付けば掲載できる（値は _make_route の出力のまま）
    v, = _set(routes=[dict(r, sell_period="過去30日")]).eligible
    assert v.net_profit == r["net_profit"] and v.sell_samples == 12


def test_breakdown_reads_sell_minus_buy_minus_costs():
    html = _section(shell.render_root(_ctx(deals=[deal("prod_a", "RICOH GR IV")])), "opportunities")
    detail = html[html.index('class="nu-break"'):]
    i_sell, i_buy, i_total = detail.index("売却価格"), detail.index("仕入価格"), detail.index("＝ 想定純利益")
    assert i_sell < i_buy < i_total and "−¥200,000" in detail


def test_zero_items_hide_tools_and_table():
    sec = _section(shell.render_root(_ctx([])), "opportunities")
    for cls in ('class="nu-otools"', 'class="nu-otable-wrap"', 'class="nu-ocards"'):
        tag = sec[sec.index(cls):]
        tag = tag[:tag.index(">")]
        assert "data-nu-opp-hide-empty" in tag and " hidden" in tag


ROUTES_CAM = [route(f"prod_r{i}", f"中古カメラ{i}", buy_condition="used_a") for i in range(3)]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_home_genre_count_equals_list_with_routes(tmp_path):
    """せどりルートがあっても、HOME のジャンルの件数 = そのジャンルの利益商品＋抽選＋在庫再開（重ねて数えない）。"""
    js = _OPP + """
    var o = {};
    o.homeCam = R.querySelector('[data-nu-catcount="camera"]').textContent;
    o.cat = click('a[data-nu-cat-link="camera"]');
    o.purpose = R.querySelector('[data-nu-count="opportunities"]').textContent;
    o.list = click('a.nu-purpose[href*="page=opportunities"], [data-nu-page="home"] a[href*="page=opportunities"]');
    o.res = res(); o.ids = vis().length;
    done(o);
    """
    genres = {f"prod_r{i}": "camera" for i in range(3)}
    o = _run(tmp_path, js, profit_deals=[deal("prod_c", "カメラA")], profit_routes={"main_routes": ROUTES_CAM},
             product_genres=genres, legacy_lotteries=[], tcg_report={"lotteries": [], "events": []})
    assert o["ids"] == 4 and o["res"].startswith("4件")
    assert re.sub(r"\D", "", o["homeCam"]) == "4" and re.sub(r"\D", "", o["purpose"]) == "4"


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_top10_excludes_out_of_stock_and_zero_category_hides_tools(tmp_path):
    js = _OPP + """
    var o = {};
    o.top = click('a.nu-quick[href*="top=10"]'); o.topIds = vis();
    o.empty = click('[data-nu-page="opportunities"] a[data-nu-switch="game"]');
    o.toolsHidden = R.querySelector('.nu-otools').hidden; o.wrapHidden = R.querySelector('.nu-otable-wrap').hidden;
    o.emptyShown = !R.querySelector('[data-nu-oempty="none"]').hidden;
    done(o);
    """
    o = _run(tmp_path, js, profit_deals=MANY_DEALS, profit_routes={"main_routes": []}, legacy_lotteries=[],
             tcg_report={"lotteries": [], "events": []})
    assert len(o["topIds"]) == 10 and "deal:prod_ip" not in o["topIds"]      # 在庫切れは TOP10 に入れない
    assert o["toolsHidden"] is True and o["wrapHidden"] is True and o["emptyShown"] is True

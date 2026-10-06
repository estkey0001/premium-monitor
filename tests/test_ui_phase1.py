"""UI Phase 1（ジャンル起点の HOME・目的別ナビゲーション）のテスト。

HTML の構造・件数の定義・データの安全（出品・確認日不明の定価を利益にしない）を確かめ、
ジャンルの保持・戻る/進む・横のはみ出しはヘッドレスの Chrome で実際に動かして確かめる
（Chrome が無い環境では、その部分だけ skip する）。
"""

from __future__ import annotations

import html as html_mod
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.content.ui import catalog as cl
from src.content.ui import categories as cats
from src.content.ui import home, navigation, pages, shell
from src.tcg.models import JST

NOW = datetime(2026, 10, 3, 12, 0, tzinfo=JST)
PCO = "https://www.pokemoncenter-online.com"


def _iso(delta: timedelta) -> str:
    return (NOW + delta).isoformat()


def _lot(i, **kw):
    e = {"tcg": "POKEMON", "product_name": f"ポケカ抽選{i}", "retailer_name": "ポケモンセンターオンライン",
         "lottery_id": f"t{i}", "status": "OPEN", "source_url": f"{PCO}/news/{i}",
         "entry_url": f"{PCO}/lottery/{i}", "verified": True, "confidence": "high", "retail_price": 5400,
         "application_start": _iso(-timedelta(days=1)), "application_end": _iso(timedelta(days=2))}
    e.update(kw)
    return e


# daily_lp_generator._nu_profit_deals が渡す形（掲載の判定は opportunity.eligibility）
DEAL = {"product_id": "prod_gr4", "title": "RICOH GR IV", "genre": "camera", "official_price": 211800,
        "official_checked_at": "2026-09-01T10:00:00+09:00", "msrp_evidence": "VERIFIED_DATED",
        "stock_status": "在庫あり", "sale_method": "normal", "sell_shop": "フジヤカメラ", "sell_identity_verified": True, "sell_price": 240000,
        "sell_checked_at": "2026-10-02T12:00:00+09:00", "net_profit": 26400, "user_level": "beginner_easy",
        "resale_sell": False, "href": "./?from=new#product-gr4",
        # 購入送料は確認済み（Phase 5.2。分からなければ確定にしない）
        "purchase_shipping": 0, "purchase_shipping_status": "FREE_VERIFIED"}
ROUTE = {"product_id": "prod_switch2", "product_name": "Nintendo Switch 2", "buy_source": "店A",
         "sell_source": "買取B", "buy_price": 49980, "sell_price": 60000, "net_profit": 5520, "roi": 0.11,
         "shipping_cost": 1500, "safety_margin": 3000, "platform_fee": 0, "payment_fee": 0, "fx_buffer": 0,
         "route_confidence": "high", "buy_price_evidence": "VERIFIED_CURRENT",
         "sell_price_evidence": "VERIFIED_CURRENT", "sell_canonical_type": "BUYBACK_CASH", "buy_canonical_type": "RETAIL",
         "buy_observed_at": "2026-10-03T09:00:00+09:00", "sell_observed_at": "2026-10-03T09:00:00+09:00",
         "buy_exact_match": True, "sell_exact_match": True, "buy_condition": "new_unopened",
         "sell_condition": "new_unopened", "buy_shipping": 0, "buy_required_cost": 0, "buy_link_type": "item"}
LEGACY = [{"id": "L1", "product_name": "RICOH GR IV 限定", "brand": "RICOH",
           "entry_start_at": (NOW - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
           "entry_end_at": (NOW + timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
           "url": "https://www.ricoh-imaging.co.jp/", "entry_form_url": "https://www.ricoh-imaging.co.jp/form"}]
# exports/tcg/latest.json の events と同じ項目名（store / price / canonical_url / source_url / observed_at）
EVENTS = [{"status": "AVAILABLE_NOW", "event_type": "RESTOCK", "product_name": "ポケカ新弾BOX",
           "store": "POKEMON_CENTER_ONLINE", "price": 5400, "canonical_url": f"{PCO}/product/9",
           "source_url": f"{PCO}/news/9", "observed_at": "2026-10-03T11:55:00+09:00",
           "reported_at": "2026-10-03T11:00:00+09:00", "tcg": "POKEMON"},
          {"status": "AVAILABLE_NOW", "stale": True, "product_name": "古い情報"},
          {"status": "COMING_SOON", "product_name": "発売予定"}]


def _stock_history(events):
    """在庫の状態の履歴（CI の scripts/update_stock_history.py と同じ手順で、TCG のイベントから作る）。"""
    import importlib.util
    from src.market import stock_history as sh
    spec = importlib.util.spec_from_file_location(
        "ush_p1", Path(__file__).resolve().parents[1] / "scripts" / "update_stock_history.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return sh.apply(sh.empty(), mod.tcg_observations({"events": events}), now=NOW)


def _ctx(**kw):
    args = dict(tcg_report={"lotteries": [_lot(1), _lot(2, status="ENDED")], "events": EVENTS},
                stock_history=_stock_history(EVENTS),
                opportunities={}, profit_routes={"main_routes": [ROUTE]}, legacy_lotteries=LEGACY,
                updated_text="10/03 12:00", now=NOW, profit_deals=[DEAL],
                product_genres={"prod_switch2": "game_console"})
    args.update(kw)
    return shell.ShellContext(**args)


def _catalog(ctx):
    model = home.build_home_model(tcg_report=ctx.tcg_report, opportunities=ctx.opportunities,
                                  profit_routes=ctx.profit_routes, legacy_lotteries=ctx.legacy_lotteries,
                                  now=ctx.now)
    return cl.build(model=model, tcg_report=ctx.tcg_report, profit_routes=ctx.profit_routes,
                    legacy_lotteries=ctx.legacy_lotteries, profit_deals=ctx.profit_deals,
                    product_genres=ctx.product_genres, stock_history=ctx.stock_history)


def _section(root: str, page: str) -> str:
    start = root.index(f'data-nu-page="{page}"')
    return root[start:root.index("</section>", start)]


# ── HOME の構成 ───────────────────────────────────────────────────

def test_new_home_renders_categories_purposes_and_quick_links():
    root = shell.render_root(_ctx())
    home_html = _section(root, "home")
    # 順番: ジャンル → 目的 → 補助リンク（巨大な Hero・検索窓・一覧は置かない）
    assert home_html.index("ジャンルから探す") < home_html.index("目的から探す") < home_html.index("nu-quicks")
    assert home_html.count('class="nu-cat"') == 6
    for cat in cats.CATEGORIES:
        assert f'data-nu-cat-link="{cat.key}"' in home_html and f">{cat.label}<" in home_html
    assert home_html.count('data-nu-purpose-link=') == 4
    for p in cl.PURPOSES:
        assert pages.PURPOSE_INFO[p]["label"] in home_html
    assert "<input" not in home_html and "nu-card" not in home_html      # 検索窓・商品カードを並べない
    assert home_html.count('class="nu-quick"') == 1                        # 動くリンクは TOP10 だけ
    assert home_html.count('nu-quick--soon" aria-disabled="true"') == 2 and home_html.count("準備中") >= 2


def test_category_counts_follow_the_definitions():
    cg = _catalog(_ctx())
    # 利益商品: 確認済みの定価の案件（カメラ1）と、ガードを通るルート（ゲーム1）。せどりルートはそのうちのルート
    assert cg.count("opportunities") == 2 and cg.count("opportunities", "camera") == 1
    assert cg.count("opportunities", "game") == 1
    assert cg.count("routes") == 1 and cg.count("routes", "game") == 1
    # 在庫再開: 在庫の履歴で今購入可能なもの（古い・発売予定は数えない）
    assert cg.count("restock") == 1 and cg.count("restock", "tcg") == 1
    # 抽選: 掲載中（ENDED は除く）。旧来の抽選はブランドからカメラ
    assert cg.count("lottery") == 2 and cg.count("lottery", "tcg") == 1 and cg.count("lottery", "camera") == 1
    # ジャンルの件数: せどりルートは利益商品の一部なので重ねて数えない
    assert cg.category_total("camera") == 2 and cg.category_total("tcg") == 2 and cg.category_total("game") == 1
    assert cg.category_total("smartphone") == 0
    data = json.loads(cg.data_json())
    assert data["static"]["routes"]["game"] == 1 and set(data["lot"].values()) == {"tcg", "camera"}
    # HOME の件数表示も同じ値
    root = shell.render_root(_ctx())
    assert 'data-nu-catcount="camera">2件' in root and 'data-nu-count="lottery">2件' in root


def test_genre_mapping():
    assert cats.from_genre("iphone") == "smartphone" and cats.from_genre("game_console") == "game"
    assert cats.from_genre("tablet") == "other" and cats.from_genre("") == "other"
    assert cats.from_text("Sony Interactive Entertainment", "PlayStation 5 Pro") == "game"
    assert cats.from_text("FUJIFILM", "FUJIFILM X100VI") == "camera"
    assert cats.valid("CAMERA") == "camera" and cats.valid("<script>") == cats.ALL


# ── URL・ナビゲーション ─────────────────────────────────────────────

def test_category_state_in_url():
    assert navigation.page_href("opportunities", category="camera") == "?page=opportunities&category=camera"
    assert navigation.page_href("home", category="tcg") == "?category=tcg"
    assert navigation.page_href("lottery", category="all") == "?page=lottery"


def test_purpose_navigation_keeps_category_links():
    root = shell.render_root(_ctx())
    # 目的・上部ナビ・ボトムナビ（HOME 以外）はジャンルを保つ
    for a in re.findall(r'<a [^>]*data-nu-purpose-link="[a-z]+"[^>]*>', root):
        assert "data-nu-keepcat" in a
    top = root[root.index('class="nu-topnav"'):root.index("</nav>", root.index('class="nu-topnav"'))]
    assert top.count("data-nu-keepcat") == 4 and 'data-nu-nav="home"' in top
    bottom = root[root.index('class="nu-bottomnav"'):]
    bottom = bottom[:bottom.index("</nav>")]
    assert bottom.count('class="nu-bottomnav__link"') == 5 and bottom.count("data-nu-keepcat") == 4
    # 目的のページ: 現在地・ジャンルの切り替え（すべて＋6ジャンル）
    for p in cl.PURPOSES:
        sec = _section(root, p)
        assert 'aria-label="現在地"' in sec and sec.count("data-nu-switch=") == 7
        if p == "opportunities":
            assert "data-nu-opp-table" in sec and "data-nu-opp-cards" in sec and 'data-nu-oempty="none"' in sec
        elif p == "lottery":
            # 抽選・予約（UI Phase 3）は1件1要素の一覧と、0件・条件に合うもの無しの空状態
            assert "data-nu-lot-list" in sec and 'data-nu-lempty="none"' in sec and 'data-nu-lempty="nomatch"' in sec
        elif p == "routes":
            # せどりルート（UI Phase 5）は確定ルートの一覧・空状態と、出品価格の参考
            assert "data-nu-route-list" in sec and 'data-nu-tempty="none"' in sec and "data-nu-ref-list" in sec
        elif p == "restock":
            # 在庫再開（UI Phase 4）は購入可能・履歴の空状態と、条件に合うもの無し
            assert "data-nu-rs-list" in sec and 'data-nu-rempty="avail"' in sec and 'data-nu-rempty="history"' in sec
        else:
            assert f'data-nu-list="{p}"' in sec and f'data-nu-empty-for="{p}"' in sec


def test_no_inactive_fake_cta():
    root = shell.render_root(_ctx())
    body = root.split('<script type="application/json"', 1)[0]
    # リンクは必ず行き先を持つ（href="#" や空の href・押しても何も起きない button は無い）
    hrefs = re.findall(r'<a [^>]*?href="([^"]*)"', body)
    assert hrefs and all(h and h != "#" for h in hrefs)
    # button は開閉（詳細・検索）だけで、必ず type="button" と aria-expanded・aria-controls を持つ
    # 商品詳細のタブ（UI Phase 6）は role="tab" で、aria-selected と aria-controls を持つ
    for b in re.findall(r"<button[^>]*>", body):
        if 'role="tab"' in b:
            assert 'type="button"' in b and "aria-selected=" in b and "aria-controls=" in b, b
            continue
        # マイページ（UI Phase 7）: ウォッチ・ジャンルの切り替え（aria-pressed）と、既読・リセットの操作（動く）
        if "aria-pressed=" in b or "data-nu-mp-" in b:
            assert 'type="button"' in b and ("aria-pressed=" in b or "data-nu-mp-" in b), b
            continue
        assert 'type="button"' in b and "aria-expanded=" in b and "aria-controls=" in b, b
    # 押せない部品（準備中）は aria-disabled と「準備中」の文言を持つ
    for el in re.findall(r"<(?:span|input)[^>]*aria-disabled=\"true\"[^>]*>", body):
        assert "<a " not in el
    # 入力欄は、一覧内の検索（利益商品・抽選・予約・在庫再開。動く）以外は準備中で押せない
    inputs = re.findall(r"<input[^>]*>", body)
    # 商品の検索（UI Phase 6）は動く。それ以外の準備中の部品は残る
    assert body.count("準備中") >= 5
    # マイページの設定（UI Phase 7。このブラウザに保存する。動く）も除く
    assert all("disabled" in i or "data-nu-search-input" in i or "data-nu-mp-" in i for i in inputs)
    assert sum("data-nu-search-input" in i for i in inputs) == 5
    for p in ("opportunities", "lottery", "restock", "routes", "search"):
        assert _section(root, p).count("data-nu-search-input") == 1


def test_empty_states_without_sold_data():
    root = shell.render_root(_ctx(profit_routes={"main_routes": []}, profit_deals=[]))
    routes = _section(root, "routes")
    # UI Phase 5: 確定ルートの空状態と、出品価格の参考（別欄）
    assert "現在、成約価格を確認できる利益ルートはありません" in routes and "出品価格ではなく" in routes
    assert re.search(r'<div class="nu-empty" data-nu-tempty="none" role="status">', routes)
    assert "出品価格の参考" in routes
    assert 'data-nu-count="routes">0件' in root
    # 技術的な理由（API・collector など）は出さない
    assert not re.search(r"API|collector|EBAY|HTTP", routes)


# ── データの安全（Phase 0〜0.2 のルールを UI で崩さない） ──────────────────────

def test_listing_or_unconfirmed_sell_route_not_listed():
    bad = dict(ROUTE, sell_canonical_type="LISTING", product_name="出品で計算したルート")
    unknown = dict(ROUTE, sell_canonical_type="UNKNOWN", product_name="種別不明のルート")
    ref = dict(ROUTE, buy_price_evidence="CONFIGURED_REFERENCE", product_name="確認日不明の定価")
    root = shell.render_root(_ctx(profit_routes={"main_routes": [bad, unknown, ref]}))
    from src.content.ui import admin
    public = admin.without_admin(root)
    for name in ("出品で計算したルート", "種別不明のルート", "確認日不明の定価"):
        assert name not in public                     # 一般のページには出さない
    # 運営者向けのページ（UI Phase 9）では、候補から外した理由つきで出す（データ品質の確認のため）
    ad = root[root.find('data-nu-page="admin"'):root.find('<section class="nu-page nu-mp"')]
    assert "出品で計算したルート" in ad and 'data-nu-ad-panel="data-quality"' in ad
    assert 'data-nu-count="routes">0件' in root


def test_profit_deals_exclude_unverified_msrp_and_resale(monkeypatch):
    """利益商品に出すのは、定価を確認済み・売り先が買取店・買取価格の確認が14日以内の案件だけ。
    生成側（_nu_profit_deals）は値を集めるだけで、判定は opportunity.eligibility。"""
    from types import SimpleNamespace

    from src.content.daily_lp_generator import DailyLPGenerator
    from src.content.ui import opportunity as opp
    from src.market import price_evidence as pe
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    g._sell_keys_cache = {(p, s, 240000) for p in ("prod_gr4", "prod_ps5_pro", "prod_x", "prod_y", "prod_old",
                                                   "prod_nodate") for s in ("フジヤカメラ", "メルカリ")}   # 照合済み
    g._msrp_evidence = {"prod_gr4": pe.VERIFIED_CURRENT, "prod_ps5_pro": pe.CONFIGURED_REFERENCE,
                        "prod_x": pe.VERIFIED_DATED, "prod_y": pe.VERIFIED_DATED, "prod_old": pe.VERIFIED_DATED,
                        "prod_nodate": pe.VERIFIED_DATED}
    g._product_info = {}
    # 購入送料は確認済みとする（Phase 5.2。テスト用の記録）
    from src.market import official_shipping as osh
    _ship = {"source": "test", "fee": 0, "status": osh.FREE_VERIFIED, "url": "https://example.com/s",
             "checked_on": "2026-10-05"}
    monkeypatch.setattr(osh, "PRODUCT_SHIPPING", {k: _ship for k in g._msrp_evidence})

    def deal(pid, net, shop="フジヤカメラ", level="beginner_easy", sell=240000):
        return SimpleNamespace(product_id=pid, product_name=pid, category="camera", net_profit_jpy=net,
                               best_buyback_price=sell, best_buyback_shop=shop, user_level=level,
                               official_price_jpy=200000, net_profit_rate=0.1, stock_status="", sale_method="normal",
                               official_url="", best_buyback_url="", buyback_condition="new_unopened")
    fresh = (NOW - timedelta(days=2)).isoformat()
    old = (NOW - timedelta(days=20)).isoformat()

    def row(shop, price, at):
        return {"shop_name": shop, "buyback_price": price, "observed_at": at}
    bybp = {"prod_gr4": [row("フジヤカメラ", 240000, fresh)], "prod_ps5_pro": [row("フジヤカメラ", 240000, fresh)],
            "prod_x": [row("メルカリ", 240000, fresh)], "prod_y": [row("フジヤカメラ", 240000, fresh)],
            "prod_old": [row("フジヤカメラ", 240000, old)]}
    raw = g._nu_profit_deals([deal("prod_gr4", 38200), deal("prod_gr4", 10000),
                              deal("prod_ps5_pro", 38200),                      # 確認日不明の定価
                              deal("prod_x", 38200, shop="メルカリ"),             # 二次流通の売り先
                              deal("prod_y", 38200, level="monitoring"),       # 監視中
                              deal("prod_old", 38200),                         # 買取価格が14日より古い
                              deal("prod_nodate", 38200),                      # 買取価格の確認日が分からない
                              deal("prod_x", -100)], bybp)
    assert len(raw) == 7                                                       # 生成側は絞り込まない（利益0以下だけ除く）
    s = opp.build(deals=raw, routes=[], product_genres={}, now=NOW)
    assert [(v.product_name, v.net_profit) for v in s.eligible] == [("prod_gr4", 38200)]
    why = {v.product_name: v.reasons for v in s.ineligible}
    assert "buy_configured_reference" in why["prod_ps5_pro"] and "resale_sell" in why["prod_x"]
    assert "monitoring" in why["prod_y"] and "stale_sell_price" in why["prod_old"]
    assert "stale_sell_price" in why["prod_nodate"]


def test_no_internal_terms_and_safe_links():
    root = shell.render_root(_ctx())
    # 運営者向けのページ（UI Phase 9。?page=admin）は別。一般のページには内部の言葉を出さない
    from src.content.ui import admin
    body = admin.without_admin(root.split('<script type="application/json"', 1)[0])
    for w in ("EBAY_APP_ID", "Health Score", "suspicious_price", "collector", "HTTP 403"):
        assert w not in body
    for h in re.findall(r'href="([^"]*)"', body):
        assert h.startswith(("?", "./", "#", "https://")) or re.match(r"^[A-Za-z0-9_\-]+/", h), h


# ── ブラウザで動かす（Chrome） ─────────────────────────────────────────

def _chrome() -> str | None:
    for c in (os.environ.get("CHROME_BIN"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")):
        if c and Path(c).exists():
            return c
    return None


CHROME = _chrome()


def _run(tmp_path, scenario_js: str, *, width: int = 1440, query: str = "?ui=new", **ctx_kw) -> dict:
    root = shell.render_root(_ctx(**ctx_kw))
    # ページの時計をテストの時刻（NOW）に固定する（実際の時刻で抽選の状態が変わらないように）
    fake_now = ("<script>(function(){var t=%d;Date.now=function(){return t;};})();</script>"
                % int(NOW.timestamp() * 1000))
    page = ("<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>" + fake_now
            + shell.render_head() + "</head><body>" + root + "<header class='topbar'>old</header>"
            "<pre id='out'></pre><script>window.addEventListener('load',function(){setTimeout(function(){"
            + scenario_js + "},50);});</script></body></html>")
    f = tmp_path / "page.html"
    f.write_text(page, encoding="utf-8")
    res = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", f"--window-size={width},900",
                          "--virtual-time-budget=4000", "--dump-dom", f.as_uri() + query],
                         capture_output=True, text=True, timeout=60)
    start = res.stdout.find('<pre id="out">')
    assert start >= 0, res.stderr[-2000:]
    raw = res.stdout[start + len('<pre id="out">'):res.stdout.find("</pre>", start)]
    return json.loads(html_mod.unescape(raw))


_HELPERS = """
var R=document.getElementById('new-ui-root');
function state(){ return {q: location.search,
  page: [].slice.call(R.querySelectorAll('[data-nu-page]')).filter(function(e){return !e.hidden;})
          .map(function(e){return e.getAttribute('data-nu-page');}).join(),
  top: [].slice.call(R.querySelectorAll('.nu-topnav [aria-current]')).map(function(a){return a.getAttribute('data-nu-nav');}).join(),
  bottom: [].slice.call(R.querySelectorAll('.nu-bottomnav [aria-current]')).map(function(a){return a.getAttribute('data-nu-nav');}).join(),
  bottomHrefs: [].slice.call(R.querySelectorAll('.nu-bottomnav a')).map(function(a){return a.getAttribute('href');}),
  sw: document.documentElement.scrollWidth, cw: document.documentElement.clientWidth,
  // ページ全体だけでなく、主要なブロックの中でもはみ出していないか（ジャンルの切り替えは中だけで横スクロール）
  inner: [].slice.call(R.querySelectorAll('.nu-header__inner, .nu-main, .nu-cats, .nu-purposes, .nu-filter, .nu-list, .nu-footer__inner'))
           .filter(function(e){return e.offsetParent !== null && e.scrollWidth > e.clientWidth + 1;})
           .map(function(e){return e.className + ':' + e.scrollWidth + '/' + e.clientWidth;})}; }
function click(sel){ R.querySelector(sel).click(); return state(); }
function done(o){ document.getElementById('out').textContent = JSON.stringify(o); }
"""


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_category_persists_and_back_forward(tmp_path):
    js = _HELPERS + """
    var o = {};
    o.home = state();
    o.camera = click('a[data-nu-cat-link="camera"]');
    o.campurposeHref = R.querySelector('a[data-nu-purpose-link="opportunities"]').getAttribute('href');
    o.campurposeCount = R.querySelector('.nu-purposes [data-nu-count="lottery"]').textContent;
    o.opp = click('a[data-nu-purpose-link="opportunities"]');
    o.oppItems = [].slice.call(R.querySelectorAll('tr.nu-orow')).filter(function(r){return !r.hidden;}).length;
    o.lottery = click('.nu-topnav a[data-nu-nav="lottery"]');
    o.lotItems = [].slice.call(R.querySelectorAll('[data-nu-lot-list] > [data-nu-lot]')).filter(function(li){return !li.hidden;})
                  .map(function(li){return li.getAttribute('data-nu-cat');});
    o.tcg = click('[data-nu-page="lottery"] a[data-nu-switch="tcg"]');
    o.restock = click('.nu-topnav a[data-nu-nav="restock"]');
    o.restockEmpty = R.querySelector('[data-nu-rempty="avail"]').hidden;
    history.back();
    setTimeout(function(){ o.back = state(); history.back();
      setTimeout(function(){ o.back2 = state(); history.forward();
        setTimeout(function(){ o.fwd = state(); o.homeAgain = click('.nu-topnav a[data-nu-nav="home"]'); done(o); }, 100);
      }, 100);
    }, 100);
    """
    o = _run(tmp_path, js)
    assert o["home"]["page"] == "home" and o["home"]["top"] == "home"
    assert o["camera"]["q"] == "?category=camera" and o["camera"]["page"] == "home"
    assert o["campurposeHref"] == "?page=opportunities&category=camera"
    assert o["campurposeCount"] == "1件"                         # カメラの抽選（旧来の抽選）だけ
    # HOME → カメラ → 利益商品（2クリック）・ジャンルを保つ
    assert o["opp"]["q"] == "?page=opportunities&category=camera" and o["opp"]["top"] == "opportunities"
    assert o["oppItems"] == 1
    assert o["lottery"]["q"] == "?page=lottery&category=camera" and o["lotItems"] == ["camera"]
    assert o["tcg"]["q"] == "?page=lottery&category=tcg"
    assert o["restock"]["q"] == "?page=restock&category=tcg" and o["restockEmpty"] is True
    # 戻る・進む
    assert o["back"]["q"] == "?page=lottery&category=tcg" and o["back"]["page"] == "lottery"
    assert o["back2"]["q"] == "?page=lottery&category=camera"
    assert o["fwd"]["q"] == "?page=lottery&category=tcg"
    # HOME へ戻るとジャンルの絞り込みを外す
    assert o["homeAgain"]["q"] == "" and o["homeAgain"]["page"] == "home"        # UI Phase 8: HOME は ./（クエリなし）


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_direct_url_and_mobile_nav(tmp_path):
    js = _HELPERS + """
    var o = {direct: state()};
    o.crumb = R.querySelector('[data-nu-page="lottery"] [data-nu-crumb-cat]').hidden ? null
            : R.querySelector('[data-nu-page="lottery"] [data-nu-crumb-cat]').textContent;
    o.chip = R.querySelector('[data-nu-page="lottery"] [data-nu-switch][aria-current]').getAttribute('data-nu-switch');
    o.title = document.title;
    o.more = click('.nu-bottomnav a[data-nu-nav="more"]');
    o.routes = click('[data-nu-page="more"] a[href*="page=routes"]');
    done(o);
    """
    o = _run(tmp_path, js, width=390, query="?ui=new&page=lottery&category=tcg")
    d = o["direct"]
    assert d["page"] == "lottery" and d["bottom"] == "lottery"
    assert o["crumb"] == "TCG" and o["chip"] == "tcg" and o["title"].startswith("TCGの抽選・予約")
    # UI Phase 8: 新UIが既定なので、作るリンクに ui=new は付けない（HOME は ./）
    assert d["bottomHrefs"] == ["./", "?page=opportunities&category=tcg",
                                "?page=lottery&category=tcg", "?page=restock&category=tcg",
                                "?page=more&category=tcg"]
    # 「その他」→ せどりルート（ボトムナビは「その他」を現在地にする）
    assert o["more"]["page"] == "more" and o["more"]["bottom"] == "more"
    assert o["routes"]["page"] == "routes" and o["routes"]["bottom"] == "more"
    assert o["routes"]["q"] == "?page=routes&category=tcg"


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
@pytest.mark.parametrize("width", [320, 390, 640, 700, 768, 1024, 1440])
def test_dom_no_horizontal_overflow(tmp_path, width):
    js = _HELPERS + """
    var o = {};
    ['', '&page=opportunities&category=camera', '&page=lottery', '&page=routes', '&page=more', '&page=search']
      .forEach(function(q){ history.replaceState(null, '', location.pathname + '?ui=new' + q);
        window.dispatchEvent(new PopStateEvent('popstate')); o[q || 'home'] = state(); });
    done(o);
    """
    o = _run(tmp_path, js, width=width)
    for key, st in o.items():
        assert st["sw"] == st["cw"], (width, key, st["sw"], st["cw"])
        assert st["inner"] == [], (width, key, st["inner"])


def test_restock_card_uses_real_event_fields():
    root = shell.render_root(_ctx())
    sec = _section(root, "restock")
    # 価格は商品1点の価格と明示されたものだけ（ページの金額がパックか BOX か分からないものは「価格未取得」）
    assert "ポケカ新弾BOX" in sec and "価格未取得" in sec and "¥5,400" not in sec and "10/03 11:00 確認" in sec
    assert "購入可能" in sec and "購入する" in sec
    assert f'href="{PCO}/product/9"' in sec and "古い情報" not in sec and "発売予定" not in sec


def test_footer_and_related_links():
    root = shell.render_root(_ctx())
    assert root.count('<footer class="nu-footer">') == 1 and "掲載情報は取得時点の参考です" in root
    opp, routes = _section(root, "opportunities"), _section(root, "routes")
    assert "せどりルートを見る" in opp and "利益商品を見る" in routes
    assert 'data-nu-topnote hidden' in opp                      # TOP10 の表示は top=10 のときだけ
    assert 'href="?page=opportunities&amp;top=10" data-nu-keepcat' in root


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_top10_and_lottery_order(tmp_path):
    many = [dict(DEAL, product_id=f"prod_m{i}", title=f"商品{i:02d}", net_profit=26400 - i * 1000,
                 sell_price=240000 - i * 1000 + 1800 - 1800) for i in range(12)]
    lots = [_lot(1, application_start=_iso(timedelta(hours=3)), application_end=_iso(timedelta(days=3))),
            _lot(2, application_end=_iso(timedelta(hours=1))),
            _lot(3, application_end=_iso(timedelta(days=2)))]
    js = _HELPERS + """
    var o = {};
    o.top = [].slice.call(R.querySelectorAll('tr.nu-orow')).filter(function(r){return !r.hidden;})
              .map(function(r){return r.querySelector('.nu-oname').textContent;});
    o.note = !R.querySelector('[data-nu-topnote]').hidden;
    o.all = click('[data-nu-topnote] a');
    o.allCount = [].slice.call(R.querySelectorAll('tr.nu-orow')).filter(function(r){return !r.hidden;}).length;
    o.lot = click('.nu-topnav a[data-nu-nav="lottery"]');
    o.order = [].slice.call(R.querySelectorAll('[data-nu-lot-list] > [data-nu-lot]')).filter(function(li){return !li.hidden;})
                .map(function(li){return li.getAttribute('data-nu-lot');});
    done(o);
    """
    o = _run(tmp_path, js, query="?ui=new&page=opportunities&top=10", profit_deals=many,
             tcg_report={"lotteries": lots, "events": []}, legacy_lotteries=[])
    assert o["top"] == [f"商品{i:02d}" for i in range(10)] and o["note"] is True
    assert o["all"]["q"] == "?page=opportunities" and o["allCount"] == 13   # 12件＋ルート1件
    # 抽選は締切間近 → 受付中 → まもなく開始の順
    assert o["order"] == ["t2", "t3", "t1"]

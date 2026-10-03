"""UI Phase 4（在庫再開）のテスト。

restocked_at（再入荷）・last_checked_at（最終確認）・stock_state（今の在庫）を混同しないこと、
古い在庫ありを「購入可能」にしないこと（ブラウザの時計を止めて境目も確かめる）を確認する。データはテスト用の架空のもの。
"""

from __future__ import annotations

import importlib.util
import re
import sqlite3
from datetime import timedelta
from pathlib import Path

import pytest

from src.content.ui import restock_view as rv
from src.content.ui import shell
from src.market import stock_history as sh
from src.market import stock_state as ss


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_P1 = _load("ui_phase1_helpers_p4", Path(__file__).with_name("test_ui_phase1.py"))
_USH = _load("ush_p4", Path(__file__).resolve().parents[1] / "scripts" / "update_stock_history.py")
CHROME, _HELPERS, _run, _section = _P1.CHROME, _P1._HELPERS, _P1._run, _P1._section
NOW = _P1.NOW
PCO = "https://www.pokemoncenter-online.com"


def _t(**kw) -> str:
    return (NOW + timedelta(**kw)).isoformat()


def ob(key, state, at, **kw):
    d = {"key": key, "product_id": kw.pop("pid", f"p_{key}"), "product_name": kw.pop("name", f"商品{key}"),
         "category": kw.pop("genre", "camera"), "store": "公式ストア", "source_type": kw.pop("st", "official_store"),
         "state": state, "observed_at": at, "url": kw.pop("url", "https://www.ricoh-imaging.co.jp/x")}
    d.update(kw)
    return d


def hist(*batches):
    h = sh.empty()
    for b in batches:
        sh.apply(h, b if isinstance(b, list) else [b], now=NOW)
    return h


# ── 状態の遷移（再入荷・在庫確認・重複） ─────────────────────────────────

def test_out_to_in_creates_restock():
    h = hist(ob("a", ss.OUT_OF_STOCK, _t(hours=-5)), ob("a", ss.IN_STOCK, _t(hours=-1)))
    e = h["entries"]["a"]
    assert e["restocked_at"] == _t(hours=-1) and e["state"] == ss.IN_STOCK and e["previous_state"] == ss.OUT_OF_STOCK
    assert [x["kind"] for x in h["events"]] == [sh.EVENT_RESTOCK]


def test_unknown_to_in_is_first_seen_not_restock():
    h = hist(ob("a", ss.UNKNOWN, _t(hours=-5)), ob("a", ss.IN_STOCK, _t(hours=-1)))
    e = h["entries"]["a"]
    assert e["restocked_at"] == "" and e["first_seen_in_stock_at"] == _t(hours=-1)
    assert [x["kind"] for x in h["events"]] == [sh.EVENT_FIRST_SEEN]
    v, = rv.build(h, now=NOW)
    sec = _section(shell.render_root(_P1._ctx(stock_history=h)), "restock")
    assert "在庫確認" in sec and " 再開<" not in sec and v.restocked_at == ""


def test_in_unknown_in_does_not_duplicate():
    h = hist(ob("a", ss.OUT_OF_STOCK, _t(hours=-9)), ob("a", ss.IN_STOCK, _t(hours=-6)),
             ob("a", ss.UNKNOWN, _t(hours=-4)), ob("a", ss.IN_STOCK, _t(hours=-1)))
    assert [x["kind"] for x in h["events"]] == [sh.EVENT_RESTOCK]            # 2回目は再入荷にしない
    assert h["entries"]["a"]["restocked_at"] == _t(hours=-6)


def test_in_to_out_no_longer_purchaseable():
    h = hist(ob("a", ss.OUT_OF_STOCK, _t(hours=-9)), ob("a", ss.IN_STOCK, _t(hours=-3)), ob("a", ss.OUT_OF_STOCK, _t(minutes=-10)))
    v, = rv.build(h, now=NOW)
    assert v.stock_state == ss.OUT_OF_STOCK and not v.available(NOW) and v.restocked_at == _t(hours=-3)
    assert v.label(NOW) == "在庫切れ"


def test_older_observation_does_not_refresh_and_failed_run_keeps_last_checked():
    h = hist(ob("a", ss.IN_STOCK, _t(hours=-1)))
    sh.apply(h, [ob("a", ss.IN_STOCK, _t(hours=-2))], now=NOW)   # 古い観測（前回より新しくない）
    sh.apply(h, [], now=NOW + timedelta(hours=1))                # 取得に失敗した実行（観測なし）
    assert h["entries"]["a"]["last_checked_at"] == _t(hours=-1)


# ── 観測の作り方（価格と在庫の時刻は別・失敗は観測にしない） ───────────────────

def _db(rows):
    con = sqlite3.connect(":memory:")
    con.execute("CREATE TABLE products (id TEXT, name TEXT, genre TEXT, is_active INT, official_stock_status TEXT,"
                " official_stock_observed_at TEXT, official_price_source TEXT, is_lottery INT, official_price INT,"
                " official_price_updated_at TEXT)")
    con.execute("CREATE TABLE product_source_config (product_id TEXT, source_id TEXT, target_url TEXT)")
    for r in rows:
        con.execute("INSERT INTO products VALUES (?,?,?,?,?,?,?,?,?,?)", r)
    return con


def test_price_observation_does_not_create_stock_observation():
    con = _db([("p1", "価格だけ", "camera", 1, "", "", "src_x", 0, 100000, _t(minutes=-5)),
               ("p2", "在庫あり", "camera", 1, "在庫あり", _t(minutes=-5), "src_x", 0, 100000, _t(minutes=-5)),
               ("p3", "抽選", "camera", 1, "SOLD OUT", _t(minutes=-5), "src_x", 1, 100000, _t(minutes=-5))])
    obs = {o["product_id"]: o for o in _USH.official_observations(con)}
    assert set(obs) == {"p2", "p3"}                                 # 在庫の根拠が無いもの（p1）は観測にしない
    assert obs["p2"]["state"] == ss.IN_STOCK and obs["p3"]["state"] == ss.LOTTERY


def test_tcg_observations_only_stock_states():
    rep = _t(minutes=-20)
    events = [{"status": "AVAILABLE_NOW", "event_type": "ONLINE_RESTOCK", "product_name": "A", "store": "S",
               "observed_at": _t(minutes=-1), "reported_at": rep},
              {"status": "AVAILABLE_NOW", "stale": True, "event_type": "RESTOCK", "product_name": "B", "store": "S",
               "reported_at": _t(hours=-9)},
              {"status": "SOLD_OUT", "product_name": "C", "store": "S", "observed_at": _t(minutes=-1), "reported_at": rep},
              {"status": "COMING_SOON", "product_name": "D", "store": "S", "reported_at": rep},
              {"status": "OPEN", "event_type": "LOTTERY", "product_name": "E", "store": "S", "reported_at": rep},
              # 発売日を過ぎただけの販売告知（在庫の根拠が無い）は在庫ありにしない
              {"status": "AVAILABLE_NOW", "event_type": "GENERAL_SALE", "product_name": "F", "store": "S", "reported_at": rep},
              # 報告時刻が無い・日付だけのものは使わない（取得した時刻で代用しない）
              {"status": "AVAILABLE_NOW", "event_type": "RESTOCK", "product_name": "G", "store": "S", "observed_at": rep},
              {"status": "AVAILABLE_NOW", "event_type": "RESTOCK", "product_name": "H", "store": "S", "reported_at": "2026-10-03"},
              # 予約キャンセル分・予約再開は在庫ありにしない（予約受付）
              {"status": "AVAILABLE_NOW", "event_type": "RESERVATION_REOPEN", "product_name": "J", "store": "S",
               "reported_at": rep},
              # 予約・抽選は在庫の明示があっても在庫ありにしない
              {"status": "AVAILABLE_NOW", "event_type": "PREORDER", "sold_out": False, "product_name": "K", "store": "S",
               "reported_at": rep},
              {"status": "AVAILABLE_NOW", "event_type": "LOTTERY", "box_available": True, "product_name": "L", "store": "S",
               "reported_at": rep},
              # 在庫の明示（sold_out=False）がある販売告知は在庫あり
              {"status": "AVAILABLE_NOW", "event_type": "GENERAL_SALE", "sold_out": False, "product_name": "I", "store": "S",
               "reported_at": rep}]
    got = _USH.tcg_observations({"events": events})
    obs = {o["product_name"]: o["state"] for o in got}
    assert obs == {"A": ss.IN_STOCK, "C": ss.OUT_OF_STOCK, "I": ss.IN_STOCK, "J": ss.RESERVATION}
    assert all(o["observed_at"] == rep for o in got)                 # 報告時刻を使う（取得した時刻ではない）


# ── 購入可能の判定（鮮度の境目・URL・予約・抽選） ─────────────────────────

def test_freshness_boundary_python():
    secs = ss.freshness_seconds("official_store")
    h = hist(ob("a", ss.IN_STOCK, _t(seconds=-secs)))
    v, = rv.build(h, now=NOW)
    s = timedelta(seconds=1)
    assert v.available(NOW - s) and not v.available(NOW) and not v.available(NOW + s)
    assert v.label(NOW) == ss.STALE_LABEL


@pytest.mark.parametrize("url", ["javascript:alert(1)", "http://www.ricoh-imaging.co.jp/x", "https://evil.example.com/x",
                                 "https://user@www.ricoh-imaging.co.jp/x", "https://www.ricoh-imaging.co.jp\\@evil.com/"])
def test_unsafe_purchase_url_never_buy(url):
    v, = rv.build(hist(ob("a", ss.IN_STOCK, _t(minutes=-5), url=url)), now=NOW)
    assert v.purchase_url == "" and not v.available(NOW)
    sec = _section(shell.render_root(_P1._ctx(stock_history=hist(ob("a", ss.IN_STOCK, _t(minutes=-5), url=url)))), "restock")
    assert "購入する" not in sec


def test_reservation_and_lottery_never_available():
    h = hist([ob("r", ss.IN_STOCK, _t(days=-3)), ob("l", ss.IN_STOCK, _t(days=-3))],
             [ob("r", ss.RESERVATION, _t(minutes=-5)), ob("l", ss.LOTTERY, _t(minutes=-5))])
    views = rv.build(h, now=NOW)
    assert all(not v.available(NOW) for v in views)
    assert {v.label(NOW) for v in views} == {"予約受付", "抽選"}


def test_profit_only_with_matching_eligible_price():
    deal = dict(_P1.DEAL, product_id="p_a", official_price=100000, sell_price=130000, net_profit=28200,
                official_checked_at=_t(days=-1), sell_checked_at=_t(hours=-1))
    h1 = hist(ob("a", ss.IN_STOCK, _t(minutes=-5), price=100000))
    h2 = hist(ob("a", ss.IN_STOCK, _t(minutes=-5), price=99000))
    for h, want in ((h1, 28200), (h2, None)):
        cg = _P1._catalog(_P1._ctx(stock_history=h, profit_deals=[deal], product_genres={"p_a": "camera"}))
        v, = cg.restock_views
        assert v.profit == want


# ── 一覧の描画・HOME の件数 ───────────────────────────────────────────

def _many():
    obs1, obs2 = [], []
    for i in range(23):
        obs1.append(ob(f"m{i:02d}", ss.OUT_OF_STOCK, _t(days=-1), genre="camera", name=f"カメラ{i:02d}", price=100000 + i))
        obs2.append(ob(f"m{i:02d}", ss.IN_STOCK, _t(minutes=-(i + 1)), genre="camera", name=f"カメラ{i:02d}", price=100000 + i))
    obs1.append(ob("g1", ss.OUT_OF_STOCK, _t(days=-1), genre="game_console", name="ゲーム機X",
                   url="https://www.playstation.com/ja-jp/x"))
    obs2.append(ob("g1", ss.IN_STOCK, _t(hours=-5), genre="game_console", name="ゲーム機X",
                   url="https://www.playstation.com/ja-jp/x"))            # 確認が古い（購入可能ではない）
    return hist(obs1, obs2)


def test_home_count_is_available_only():
    root = shell.render_root(_P1._ctx(stock_history=_many()))
    sec = _section(root, "restock")
    assert sec.count('data-avail="1"') == 23 and sec.count('data-avail="0"') == 1
    assert 'data-nu-count="restock">23件' in root


_RS = _HELPERS + """
function vis(){ return [].slice.call(R.querySelectorAll('[data-nu-rs-list] > [data-nu-rs]')).filter(function(e){return !e.hidden;})
  .map(function(e){return e.getAttribute('data-nu-rs');}); }
function res(){ return R.querySelector('[data-nu-rresult]').textContent; }
"""


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_tabs_sort_search_pagination_history(tmp_path):
    js = _RS + """
    var o = {};
    o.first = vis(); o.res = res();
    o.p2 = click('[data-nu-rpager] a[href*="page_num=2"]'); o.p2ids = vis();
    o.price = click('a[data-nu-rparam="sort"][data-nu-rvalue="price"]'); o.priceIds = vis().slice(0, 2);
    o.hist = click('a[data-nu-rparam="view"][data-nu-rvalue="history"]'); o.histRes = res();
    o.today = click('a[data-nu-rparam="when"][data-nu-rvalue="today"]'); o.todayRes = res();
    o.game = click('[data-nu-page="restock"] a[data-nu-switch="game"]'); o.gameIds = vis();
    o.gameBadge = R.querySelector('[data-nu-rs="g1"] [data-nu-rbadge]').textContent;
    o.gameCta = R.querySelector('[data-nu-rs="g1"] a[data-nu-rcta]').textContent;
    o.avail = click('a[data-nu-rparam="view"][data-nu-rvalue=""]');
    o.availEmpty = !R.querySelector('[data-nu-rempty="avail"]').hidden;
    R.querySelector('[data-nu-page="restock"] [data-nu-search-toggle]').click();
    o.cam = click('[data-nu-page="restock"] a[data-nu-switch="camera"]');
    var inp = R.querySelector('[data-nu-page="restock"] [data-nu-search-input]');
    inp.value = 'カメラ07'; inp.dispatchEvent(new Event('input', {bubbles: true}));
    setTimeout(function(){
      o.search = vis(); history.back();
      setTimeout(function(){ o.back = state(); done(o); }, 80);
    }, 400);
    """
    o = _run(tmp_path, js, query="?ui=new&page=restock", stock_history=_many())
    # 購入可能（既定）: 再開が新しい順。23件 → 20件ずつ
    assert o["res"] == "23件中 1〜20件" and o["first"][0] == "m00" and len(o["p2ids"]) == 3
    assert o["priceIds"] == ["m00", "m01"]
    assert o["histRes"].startswith("24件")                       # 履歴は確認の古いものも含む
    assert o["todayRes"] == "24件中 1〜20件"                     # どれも今日（NOW=12:00 の前）に再開
    assert o["gameIds"] == ["g1"] and o["gameBadge"] == "在庫未確認（更新待ち）" and o["gameCta"] == "販売ページを見る"
    assert o["availEmpty"] is True                               # ゲームで今買えるものは0件
    assert o["search"] == ["m07"]
    # 検索は履歴を積まない。戻ると「購入可能」に切り替えた直後（ジャンル: ゲーム）
    assert o["back"]["q"] == "?ui=new&page=restock&sort=price&when=today&category=game"


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_stale_at_boundary_without_reload(tmp_path):
    """確認の期限ちょうどで「購入可能」→「在庫未確認（更新待ち）」になり、HOME の件数も減る。"""
    secs = ss.freshness_seconds("official_store")
    h = hist(ob("a", ss.IN_STOCK, _t(seconds=-(secs - 60))), ob("b", ss.IN_STOCK, _t(minutes=-5)))
    js = _RS + """
    var o = {};
    var badge = function(k){ return R.querySelector('[data-nu-rs="' + k + '"] [data-nu-rbadge]').textContent; };
    var cnt = function(){ return R.querySelector('.nu-purposes [data-nu-count="restock"]').textContent; };
    o.before = [badge('a'), cnt(), vis()];
    var t0 = Date.now();
    Date.now = function(){ return t0 + 59000; }; window.dispatchEvent(new Event('pageshow'));
    o.sec1 = [badge('a'), cnt()];
    Date.now = function(){ return t0 + 60000; }; window.dispatchEvent(new Event('pageshow'));
    o.at = [badge('a'), cnt(), vis(), R.querySelector('[data-nu-rs="a"] a[data-nu-rcta]').textContent];
    done(o);
    """
    o = _run(tmp_path, js, query="?ui=new&page=restock", stock_history=h)
    assert o["before"][0] == "購入可能" and o["before"][1] == "2件" and set(o["before"][2]) == {"a", "b"}
    assert o["sec1"] == ["購入可能", "2件"]
    assert o["at"][0] == "在庫未確認（更新待ち）" and o["at"][1] == "1件" and o["at"][2] == ["b"]
    assert o["at"][3] == "販売ページを見る"


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
@pytest.mark.parametrize("width", [320, 390, 640, 700, 768, 1024, 1440])
def test_dom_restock_no_overflow(tmp_path, width):
    js = _RS + """
    var o = {s: state(), cta: [].slice.call(R.querySelectorAll('[data-nu-rs-list] a[data-nu-rcta]')).filter(function(a){return a.offsetParent;})
                 .map(function(a){return Math.round(a.getBoundingClientRect().height);})};
    R.querySelectorAll('[data-nu-rs-list] details').forEach(function(d){ d.open = true; });
    o.open = state();
    done(o);
    """
    o = _run(tmp_path, js, width=width, query="?ui=new&page=restock", stock_history=_many())
    for st in (o["s"], o["open"]):
        assert st["sw"] == st["cw"] and st["inner"] == [], (width, st)
    assert o["cta"] and min(o["cta"]) >= 44


def test_no_raw_codes_or_tech_words():
    h = hist(ob("t", ss.OUT_OF_STOCK, _t(days=-1), st="tcg_event", variant="SEALED_SHRINK", genre="tcg",
                url=f"{PCO}/p"), ob("t", ss.IN_STOCK, _t(minutes=-3), st="tcg_event", variant="SEALED_SHRINK",
                                     genre="tcg", url=f"{PCO}/p", purchase_limit="1人1点まで"))
    sec = _section(shell.render_root(_P1._ctx(stock_history=h)), "restock")
    assert "シュリンク付きBOX" in sec and "SEALED_SHRINK" not in sec and "1人1点まで" in sec
    for w in ("collector", "HTTP", "parser", "API", "IN_STOCK<", "OUT_OF_STOCK<"):
        assert w not in sec
    assert re.search(r"制限未確認|1人1点まで", sec)


# ── レビュー指摘の再発防止 ───────────────────────────────────────────

def test_future_observation_rejected():
    h = hist(ob("a", ss.IN_STOCK, _t(days=90)))
    assert h["entries"] == {}
    h = hist(ob("a", ss.IN_STOCK, _t(minutes=-5)), ob("a", ss.IN_STOCK, _t(days=90)), ob("a", ss.OUT_OF_STOCK, _t(minutes=-1)))
    assert h["entries"]["a"]["state"] == ss.OUT_OF_STOCK            # 未来の観測で固まらない


def test_price_and_url_not_carried_over():
    h = hist(ob("a", ss.IN_STOCK, _t(hours=-2), price=100000, price_observed_at=_t(hours=-2)),
             ob("a", ss.IN_STOCK, _t(hours=-1)))
    e = h["entries"]["a"]
    assert e["price"] == "" and e["price_observed_at"] == ""        # 今回の観測に価格が無ければ前回の価格を残さない


def test_stale_without_url_is_still_update_waiting():
    v, = rv.build(hist(ob("a", ss.IN_STOCK, _t(hours=-5), url="")), now=NOW)
    assert v.label(NOW) == ss.STALE_LABEL


def test_date_only_observation_ignored():
    assert hist(ob("a", ss.IN_STOCK, "2026-10-03"))["entries"] == {}


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_detail_state_follows_badge_and_blocked_click_message(tmp_path):
    secs = ss.freshness_seconds("official_store")
    h = hist(ob("a", ss.IN_STOCK, _t(seconds=-(secs - 30))))
    js = _RS + """
    var o = {};
    var row = R.querySelector('[data-nu-rs="a"]'), a = row.querySelector('a[data-nu-rcta]');
    o.before = [row.querySelector('[data-nu-rbadge]').textContent, row.querySelector('[data-nu-rstate]').textContent];
    var t0 = Date.now();
    Date.now = function(){ return t0 + 31000; };              // 期限を過ぎた直後に「購入する」を押す
    var ev = new MouseEvent('click', {bubbles: true, cancelable: true, button: 0});
    var prevented = null;
    a.addEventListener('click', function(e){ prevented = e.defaultPrevented; e.preventDefault(); }, {once: true});
    a.dispatchEvent(ev);
    o.prevented = prevented;
    var notice = R.querySelector('[data-nu-rnotice]');
    o.after = [row.querySelector('[data-nu-rbadge]').textContent, row.querySelector('[data-nu-rstate]').textContent,
               a.textContent, !notice.hidden && notice.getBoundingClientRect().height > 0];
    o.noticeText = notice.textContent;
    done(o);
    """
    # 既定の「購入可能」タブで押す（行は隠れても、お知らせはページの通知欄に見える）
    o = _run(tmp_path, js, query="?ui=new&page=restock", stock_history=h)
    assert o["before"] == ["購入可能", "購入可能"]
    assert "購入可能から外しました" in o["noticeText"]
    assert o["prevented"] is True
    assert o["after"] == ["在庫未確認（更新待ち）", "在庫未確認（更新待ち）", "販売ページを見る", True]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_first_seen_not_in_restock_filters_and_empty_links(tmp_path):
    h = hist(ob("f", ss.IN_STOCK, _t(minutes=-5)),                                     # 初めての在庫確認
             ob("r", ss.OUT_OF_STOCK, _t(hours=-9)), ob("r", ss.IN_STOCK, _t(minutes=-10)))   # 再入荷
    js = _RS + """
    var o = {};
    o.hist = click('a[data-nu-rparam="view"][data-nu-rvalue="history"]'); o.histIds = vis();
    o.today = click('a[data-nu-rparam="when"][data-nu-rvalue="today"]'); o.todayIds = vis();
    o.d24 = click('a[data-nu-rparam="when"][data-nu-rvalue="24h"]'); o.d24Ids = vis();
    o.pc = click('[data-nu-page="restock"] a[data-nu-switch="pc"]');
    o.histEmpty = !R.querySelector('[data-nu-rempty="history"]').hidden;
    o.avail = click('a[data-nu-rparam="view"][data-nu-rvalue=""]');
    o.toLot = !R.querySelector('[data-nu-rs-tolot]').hidden; o.toHist = !R.querySelector('[data-nu-rs-tohist]').hidden;
    o.sortHidden = R.querySelector('[data-nu-page="restock"] .nu-otools__row[data-nu-rs-hide-empty]').hidden;
    done(o);
    """
    o = _run(tmp_path, js, query="?ui=new&page=restock", stock_history=h)
    assert set(o["histIds"]) == {"f", "r"}
    assert o["todayIds"] == ["r"] and o["d24Ids"] == ["r"]                 # 初めての在庫確認は「再開」に入れない
    assert o["histEmpty"] is True and o["toLot"] is True and o["toHist"] is False   # PC は履歴も0件 → 抽選・予約へ
    assert o["sortHidden"] is True

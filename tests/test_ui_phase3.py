"""UI Phase 3（抽選・予約）のテスト。

状態の判定・ボタン・件数・並び順は runtime（Python の derive_runtime_state と JS の deriveLotteryRuntimeState）
だけで決まることを、固定時刻（時計を止めたブラウザ）で確かめる。データはテスト用の架空のもの。
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta

import pytest

from src.content.ui import runtime as rt
from src.content.ui import shell


def _load_phase1():
    import importlib.util
    from pathlib import Path
    spec = importlib.util.spec_from_file_location("ui_phase1_helpers_p3", Path(__file__).with_name("test_ui_phase1.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_P1 = _load_phase1()
CHROME, _HELPERS, _run, _section = _P1.CHROME, _P1._HELPERS, _P1._run, _P1._section
NOW = _P1.NOW                       # 2026-10-03 12:00 JST（ブラウザの時計もこの時刻に止める）
PCO = "https://www.pokemoncenter-online.com"


def _iso(**kw) -> str:
    return (NOW + timedelta(**kw)).isoformat()


def lot(i, **kw):
    e = {"tcg": "POKEMON", "product_name": f"抽選{i:02d}", "retailer_name": "ポケモンセンターオンライン",
         "lottery_id": f"L{i}", "source_url": f"{PCO}/news/{i}", "entry_url": f"{PCO}/lottery/{i}",
         "verified": True, "confidence": "high", "collection_method": "HTML", "event_type": "LOTTERY",
         "application_start": _iso(days=-1), "application_end": _iso(days=2),
         "last_verified_at": _iso(minutes=-5)}
    e.update(kw)
    return e


def release(name, days, **kw):
    e = {"status": "COMING_SOON", "store": "POKEMON_CARD_OFFICIAL", "product_name": name,
         "release_date": (NOW + timedelta(days=days)).strftime("%Y年%m月%d日"), "price": 1200,
         "retail_price_basis": "product_unit", "canonical_url": "https://www.pokemon-card.com/products/x",
         "observed_at": _iso(hours=-2)}
    e.update(kw)
    return e


def _vm(**kw):
    return rt.tcg_vm(lot(1, **kw), 0)


def _state(vm, t):
    return rt.derive_runtime_state(vm, t)


# ── 時刻の境目（Python と JS で同じ） ─────────────────────────────────────

_NODE = shutil.which("node")


def _js(vms, nows):
    harness = ("const R=require(process.argv[1]);let s='';process.stdin.on('data',d=>s+=d).on('end',()=>{"
               "const x=JSON.parse(s);process.stdout.write(JSON.stringify(x.nows.map(n=>x.vms.map("
               "v=>R.deriveLotteryRuntimeState(v,n,x.cfg)))));});")
    res = subprocess.run([_NODE, "-e", harness, str(rt.JS_PATH)], capture_output=True, text=True, check=True,
                         input=json.dumps({"vms": vms, "nows": [rt._ms(t) for t in nows], "cfg": rt.config()}))
    return json.loads(res.stdout)


def _boundary_cases():
    start, end = NOW + timedelta(hours=2), NOW + timedelta(days=3)
    vm = _vm(application_start=start.isoformat(), application_end=end.isoformat())
    s = timedelta(seconds=1)
    return vm, [(start - s, "UPCOMING", "info"), (start, "OPEN", "apply"), (start + s, "OPEN", "apply"),
                (end - s, "ENDING_SOON", "apply"), (end, "CLOSED", "info"), (end + s, "CLOSED", "info")]


def test_start_and_deadline_boundaries():
    vm, cases = _boundary_cases()
    for t, status, cta in cases:
        st = _state(vm, t)
        assert (st["status"], st["cta"]["kind"]) == (status, cta), t
    # 締切ちょうどで「応募する」は消え、件数（bucket < 99）からも外れる
    assert _state(vm, cases[3][0])["bucket"] == rt.BUCKET_ENDING
    assert _state(vm, cases[4][0])["bucket"] == rt.BUCKET_HIDDEN


@pytest.mark.skipif(_NODE is None, reason="node が無い")
def test_boundaries_same_in_browser_runtime():
    vm, cases = _boundary_cases()
    rel = rt.release_vm(release("発売待ち", 1))
    pre = rt.tcg_vm(lot(9, event_type="PREORDER", application_start=_iso(hours=1), application_end=_iso(days=1)), 1)
    d0 = datetime.fromisoformat(rel["rd"] + "T00:00:00+09:00")
    nows = [t for t, _s, _c in cases] + [d0 - timedelta(seconds=1), d0, d0 + timedelta(seconds=1),
                                         NOW, NOW + timedelta(hours=1), NOW + timedelta(days=1)]
    js = _js([vm, rel, pre], nows)
    for t, row in zip(nows, js):
        for v, j in zip([vm, rel, pre], row):
            assert rt.derive_runtime_state(v, t) == j, (v["id"], t)


def test_purchase_period_separate_from_application():
    vm = _vm(application_start=_iso(days=-9), application_end=_iso(days=-6), winner_announcement_at=_iso(days=-3),
             purchase_start=_iso(days=-1), purchase_end=_iso(hours=5), purchase_url=f"{PCO}/buy")
    st = _state(vm, NOW)
    assert st["status"] == "WINNER_PURCHASE_PERIOD" and "購入期限" in st["when"] and st["cd_text"] == "購入期限まで あと5時間"
    assert st["cta"]["kind"] == "purchase" and st["bucket"] == rt.BUCKET_BUY      # 件数に数える（購入期限中）
    assert _state(vm, NOW + timedelta(hours=5))["bucket"] == rt.BUCKET_HIDDEN    # 期限で外れる


def test_result_pending_counted_closed_not_counted():
    pend = _vm(application_start=_iso(days=-5), application_end=_iso(days=-1), winner_announcement_at=_iso(days=2))
    closed = _vm(application_start=_iso(days=-5), application_end=_iso(days=-1))
    assert _state(pend, NOW)["status"] == "RESULT_PENDING" and _state(pend, NOW)["bucket"] < rt.BUCKET_HIDDEN
    assert _state(closed, NOW)["status"] == "CLOSED" and _state(closed, NOW)["bucket"] == rt.BUCKET_HIDDEN


def test_preorder_and_release_labels():
    pre = rt.tcg_vm(lot(2, event_type="PREORDER"), 0)
    st = _state(pre, NOW)
    assert st["label"] == "予約受付中" and st["cta"]["label"] == "予約する"
    assert st["open"] is False                         # 「抽選受付中」の件数には予約を入れない（予約は在庫ありでもない）
    rel = rt.release_vm(release("カードセット", 5))
    st = _state(rel, NOW)
    assert st["status"] == "RELEASE_WAIT" and "発売予定" in st["when"] and st["cta"]["kind"] == "info"
    assert st["cd_text"].startswith("発売まで")


@pytest.mark.parametrize("ev", [
    release("非公式", 3, canonical_url="https://example.com/x", source_url="https://example.com/x"),
    release("http", 3, canonical_url="http://www.pokemon-card.com/x", source_url=""),
    release("年なし", 3, release_date="10月16日"),
    release("古い", 3, stale=True),
    release("発売済み", 3, status="AVAILABLE_NOW"),
])
def test_release_requires_official_https_and_known_date(ev):
    assert rt.release_vm(ev) is None


@pytest.mark.parametrize("url", ["javascript:alert(1)", "data:text/html,x", "vbscript:x", f"http://{PCO[8:]}/l",
                                 "https://www.pokemoncenter-online.com\\@evil.com/", "https://user@www.pokemoncenter-online.com/",
                                 "https://bit.ly/abc", "https://evil.example.com/lottery"])
def test_unsafe_apply_url_never_cta(url):
    st = _state(_vm(entry_url=url), NOW)
    assert st["cta"] is None or st["cta"]["kind"] != "apply"


def test_official_https_apply_allowed():
    st = _state(_vm(), NOW)
    assert st["cta"]["kind"] == "apply" and st["cta"]["url"].startswith("https://www.pokemoncenter-online.com/")


# ── 一覧の描画 ─────────────────────────────────────────────────────

def _ctx(lots=None, events=None, **kw):
    args = dict(tcg_report={"lotteries": lots if lots is not None else [], "events": events or []},
                legacy_lotteries=[], profit_deals=[], profit_routes={"main_routes": []})
    args.update(kw)
    return _P1._ctx(**args)


SET = [
    lot(1, application_end=_iso(hours=6)),                                                 # 締切間近（今日締切）
    lot(2),                                                                                # 受付中
    lot(3, application_start=_iso(hours=3), application_end=_iso(days=3)),                 # まもなく開始
    lot(4, event_type="PREORDER", product_name="予約04", retailer_name="カードショップX"),  # 予約受付中
    lot(5, application_start=_iso(days=-5), application_end=_iso(days=-1), winner_announcement_at=_iso(days=2)),
    lot(6, application_start=_iso(days=-9), application_end=_iso(days=-6), purchase_start=_iso(days=-1),
        purchase_end=_iso(days=1), purchase_url=f"{PCO}/buy/6"),
    lot(7, conflict=True),                                                                 # 日程要確認
    lot(8, collection_method="MANUAL_VERIFIED", verified=False, confidence="medium"),      # 確認待ち
    lot(9, application_start=_iso(days=-30), application_end=_iso(days=-20)),              # 終了（出さない）
]


def test_list_renders_states_and_safety():
    sec = _section(shell.render_root(_ctx(SET, [release("発売待ち10", 4)])), "lottery")
    rows = re.findall(r'<article class="nu-lrow"[^>]*data-nu-lot="([^"]+)"[^>]*data-nu-status="([A-Z_]+)"', sec)
    st = dict(rows)
    assert st["L1"] == "ENDING_SOON" and st["L2"] == "OPEN" and st["L3"] == "UPCOMING" and st["L4"] == "OPEN"
    assert st["L5"] == "RESULT_PENDING" and st["L6"] == "WINNER_PURCHASE_PERIOD" and st["L7"] == "SOURCE_CONFLICT"
    assert any(s == "RELEASE_WAIT" for s in st.values())
    # 「応募する」は公式の https の受付中だけ。確認待ち・日程要確認・開始前・終了には出さない
    for lid in ("L3", "L7", "L8", "L9"):
        row = re.search(r'<article class="nu-lrow"[^>]*data-nu-lot="%s".*?</article>' % lid, sec, re.S).group(0)
        assert "応募する" not in row, lid
    l8 = re.search(r'<article class="nu-lrow"[^>]*data-nu-lot="L8".*?</article>', sec, re.S).group(0)
    assert "確認待ち" in l8
    l7 = re.search(r'<article class="nu-lrow"[^>]*data-nu-lot="L7".*?</article>', sec, re.S).group(0)
    assert "日程要確認" in l7
    # 当選者の購入期間は応募期間と別の行で出す
    l6 = re.search(r'<article class="nu-lrow"[^>]*data-nu-lot="L6".*?</article>', sec, re.S).group(0)
    assert "<dt>応募期間</dt>" in l6 and "<dt>当選者の購入期間</dt>" in l6 and "購入ページ（当選者のみ）" in l6
    # 終了したものは描画しても隠す（件数・一覧に出さない）
    l9 = re.search(r'<article class="nu-lrow"[^>]*data-nu-lot="L9"[^>]*>', sec).group(0)
    assert " hidden" in l9
    # 価格・利益: 価格が無ければ「価格未発表」、利益は根拠が無ければ「算出前」（推測しない）
    assert "価格未発表" in sec and "算出前" in sec and "市場参考 未取得" in sec
    for w in ("collector", "HTTP", "parser", "API"):
        assert w not in sec


def test_profit_only_with_verified_price_and_eligible_sell():
    deal = {"product_id": "prod_cam", "title": "カメラX", "genre": "camera", "official_price": 199800,
            "official_checked_at": _iso(days=-1), "msrp_evidence": "VERIFIED_DATED", "stock_status": "",
            "sale_method": "normal", "sell_shop": "買取店A", "sell_identity_verified": True, "sell_price": 228000, "sell_checked_at": _iso(hours=-1),
            "net_profit": 26400, "user_level": "beginner_easy", "purchase_shipping": 0, "purchase_shipping_status": "FREE_VERIFIED"}
    legacy = [{"id": "lg1", "product_id": "prod_cam", "product_name": "カメラX 抽選", "brand": "メーカー",
               "entry_start_at": (NOW - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
               "entry_end_at": (NOW + timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
               "url": "https://www.ricoh-imaging.co.jp/x", "entry_form_url": "https://www.ricoh-imaging.co.jp/x/f"},
              {"id": "lg2", "product_id": "prod_other", "product_name": "別の抽選", "brand": "メーカー",
               "entry_start_at": (NOW - timedelta(days=1)).strftime("%Y-%m-%d %H:%M"),
               "entry_end_at": (NOW + timedelta(days=2)).strftime("%Y-%m-%d %H:%M"),
               "official_price": "¥99,999（税込）", "url": "https://www.ricoh-imaging.co.jp/y"}]
    root = shell.render_root(_ctx([], legacy_lotteries=legacy, profit_deals=[deal],
                                  product_genres={"prod_cam": "camera", "prod_other": "camera"}))
    sec = _section(root, "lottery")
    lg1 = re.search(r'data-nu-lot="lg1".*?</article>', sec, re.S).group(0)
    assert "¥199,800" in lg1 and "+¥26,400" in lg1 and "買取参考 ¥228,000" in lg1
    lg2 = re.search(r'data-nu-lot="lg2".*?</article>', sec, re.S).group(0)
    # 確認済みの定価が無い旧来の抽選は、読み取った価格（¥99,999）を使わない
    assert "¥99,999" not in lg2 and "未取得" in lg2 and "算出前" in lg2


def test_home_count_parity_static():
    root = shell.render_root(_ctx(SET, [release("発売待ち10", 4)]))
    sec = _section(root, "lottery")
    shown = len(re.findall(r'<article class="nu-lrow"(?![^>]*\shidden)[^>]*>', sec))
    m = re.search(r'id="nu-catalog">(.*?)</script>', root).group(1)
    lot_map = json.loads(m)["lot"]
    active = sum(1 for a in re.findall(r'<article class="nu-lrow"[^>]*data-nu-lot="([^"]+)"(?![^>]*\shidden)', sec)
                 if a in lot_map)
    # 掲載: L1〜L8（L9 は終了）＋発売待ち1件 = 9件。HOME の件数と同じ定義（bucket < 99）
    assert shown == active == 9


# ── ブラウザ（時計を止めた Chrome） ──────────────────────────────────────

_LOT = _HELPERS + """
function vis(){ return [].slice.call(R.querySelectorAll('[data-nu-lot-list] > [data-nu-lot]')).filter(function(e){return !e.hidden;})
  .map(function(e){return e.getAttribute('data-nu-lot');}); }
function res(){ return R.querySelector('[data-nu-lresult]').textContent; }
"""


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_filters_sort_search_history(tmp_path):
    js = _LOT + """
    var o = {};
    o.all = vis(); o.allRes = res();
    o.open = click('a[data-nu-lparam="st"][data-nu-lvalue="open"]'); o.openIds = vis();
    o.today = click('a[data-nu-lparam="st"][data-nu-lvalue="today"]'); o.todayIds = vis();
    o.wait = click('a[data-nu-lparam="st"][data-nu-lvalue="wait"]'); o.waitIds = vis();
    o.result = click('a[data-nu-lparam="st"][data-nu-lvalue="result"]'); o.resultIds = vis();
    o.alltab = click('a[data-nu-lparam="st"][data-nu-lvalue=""]');
    o.dl = click('a[data-nu-lparam="sort"][data-nu-lvalue="deadline"]'); o.dlIds = vis().slice(0, 3);
    o.startS = click('a[data-nu-lparam="sort"][data-nu-lvalue="start"]'); o.startIds = vis().slice(0, 2);
    o.cat = click('[data-nu-page="lottery"] a[data-nu-switch="camera"]'); o.camRes = res();
    o.emptyShown = !R.querySelector('[data-nu-lempty="none"]').hidden;
    o.toolsHidden = R.querySelector('[data-nu-page="lottery"] .nu-otools').hidden;
    o.tcg = click('[data-nu-page="lottery"] a[data-nu-switch="tcg"]');
    R.querySelector('[data-nu-page="lottery"] [data-nu-search-toggle]').click();
    var inp = R.querySelector('[data-nu-page="lottery"] [data-nu-search-input]');
    inp.value = 'カードショップx'; inp.dispatchEvent(new Event('input', {bubbles: true}));
    setTimeout(function(){
      o.search = state(); o.searchIds = vis();
      history.back();
      setTimeout(function(){ o.back = state(); o.backIds = vis().length; done(o); }, 80);
    }, 400);
    """
    o = _run(tmp_path, js, query="?ui=new&page=lottery", tcg_report={"lotteries": SET, "events": [release("発売待ち10", 4)]},
             legacy_lotteries=[], profit_deals=[], profit_routes={"main_routes": []})
    assert len(o["all"]) == 9 and o["allRes"] == "9件中 1〜9件"
    # 行動すべき順: 締切間近 → 受付中 → 当選者購入期間 → まもなく開始 → 日程要確認 → 結果待ち・発売待ち
    assert o["all"][0] == "L1"
    assert set(o["openIds"]) == {"L1", "L2"}                  # 抽選の受付中（予約・確認待ちは入れない）
    assert o["todayIds"] == ["L1"]
    assert "L4" in o["waitIds"] and len(o["waitIds"]) == 2      # 予約受付中＋発売待ち
    assert set(o["resultIds"]) == {"L5", "L6"}
    assert o["open"]["q"] == "?page=lottery&st=open"
    assert o["dlIds"][0] == "L1" and o["dl"]["q"] == "?page=lottery&sort=deadline"
    assert o["startIds"][0] == "L3"
    assert o["camRes"] == "0件" and o["emptyShown"] is True and o["toolsHidden"] is True
    assert o["cat"]["q"] == "?page=lottery&sort=start&category=camera"
    assert o["searchIds"] == ["L4"] and "q=" in o["search"]["q"]
    assert o["back"]["q"] == "?page=lottery&sort=start&category=camera"


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_cta_disappears_at_deadline_without_reload(tmp_path):
    """締切の時刻を過ぎたら、再読み込みなしで「応募する」が消え、件数・一覧からも外れる。"""
    js = _LOT + """
    var o = {};
    var row = function(){ return R.querySelector('[data-nu-lot="L1"]'); };
    o.before = {cta: !!row().querySelector('a[data-nu-cta="apply"]'), hidden: row().hidden,
                status: row().getAttribute('data-nu-status'), count: R.querySelector('.nu-purposes [data-nu-count="lottery"]').textContent};
    var t = Date.now() + 6 * 3600000;             // 締切ちょうど
    Date.now = function(){ return t; };
    window.dispatchEvent(new Event('pageshow'));
    o.after = {cta: !!row().querySelector('a[data-nu-cta="apply"]'), hidden: row().hidden,
               status: row().getAttribute('data-nu-status'), count: R.querySelector('.nu-purposes [data-nu-count="lottery"]').textContent};
    var t2 = Date.now() - 6 * 3600000 + 3 * 3600000;   // 開始の時刻ちょうど（L3）
    Date.now = function(){ return t2; };
    window.dispatchEvent(new Event('pageshow'));
    o.l3 = R.querySelector('[data-nu-lot="L3"]').getAttribute('data-nu-status');
    o.l3cta = !!R.querySelector('[data-nu-lot="L3"] a[data-nu-cta="apply"]');
    done(o);
    """
    o = _run(tmp_path, js, query="?ui=new&page=lottery", tcg_report={"lotteries": SET[:3], "events": []},
             legacy_lotteries=[], profit_deals=[], profit_routes={"main_routes": []})
    assert o["before"] == {"cta": True, "hidden": False, "status": "ENDING_SOON", "count": "3件"}
    assert o["after"]["cta"] is False and o["after"]["hidden"] is True and o["after"]["status"] == "CLOSED"
    assert o["after"]["count"] == "2件"
    assert o["l3"] == "OPEN" and o["l3cta"] is True


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_home_parity_and_direct_url(tmp_path):
    js = _LOT + """
    var o = {};
    o.homeTcg = R.querySelector('.nu-purposes [data-nu-count="lottery"]').textContent;
    o.listTcg = vis().length;
    o.cam = click('a[data-nu-cat-link="camera"]');
    o.homeCam = R.querySelector('.nu-purposes [data-nu-count="lottery"]').textContent;
    o.go = click('.nu-purposes a[data-nu-purpose-link="lottery"]');
    o.listCam = vis().length;
    done(o);
    """
    o = _run(tmp_path, js, query="?ui=new&page=lottery&category=tcg&st=wait",
             tcg_report={"lotteries": SET, "events": [release("発売待ち10", 4)]},
             legacy_lotteries=[], profit_deals=[], profit_routes={"main_routes": []})
    # 直接 URL（category=tcg&st=wait）で開いても絞り込みが効く
    assert o["listTcg"] == 2
    assert o["go"]["q"].startswith("?page=lottery") and "category=camera" in o["go"]["q"]
    assert o["homeCam"] == "0件" and o["listCam"] == 0


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
@pytest.mark.parametrize("width", [320, 390, 640, 700, 768, 1024, 1440])
def test_dom_lottery_no_overflow_and_layout(tmp_path, width):
    js = _LOT + """
    var o = {s: state(), head: getComputedStyle(R.querySelector('.nu-lhead')).display,
             cta: [].slice.call(R.querySelectorAll('[data-nu-lot-list] a[data-nu-cta]')).filter(function(a){return a.offsetParent;})
                    .map(function(a){return Math.round(a.getBoundingClientRect().height);})};
    R.querySelectorAll('[data-nu-lot-list] details').forEach(function(d){ d.open = true; });
    o.open = state();
    done(o);
    """
    o = _run(tmp_path, js, width=width, query="?ui=new&page=lottery",
             tcg_report={"lotteries": SET, "events": [release("発売待ち10", 4)]},
             legacy_lotteries=[], profit_deals=[], profit_routes={"main_routes": []})
    for st in (o["s"], o["open"]):
        assert st["sw"] == st["cw"], (width, st["sw"], st["cw"])
        assert st["inner"] == [], (width, st["inner"])
    # 1024px 以上は行の見出しを出す（比較しやすい行）。それ未満はカード
    assert o["head"] == ("grid" if width >= 1024 else "none")
    assert o["cta"] and min(o["cta"]) >= 44


# ── レビュー指摘の再発防止 ───────────────────────────────────────────

def test_unconfirmed_open_not_called_open():
    vm = _vm(collection_method="MANUAL_VERIFIED", verified=False, confidence="medium")
    st = _state(vm, NOW)
    assert st["status"] == "OPEN" and st["label"] == "受付中（確認待ち）" and st["tone"] == "warning"
    assert st["open"] is False and st["cta"]["kind"] == "info" and st["cta"]["style"] == "secondary"
    assert st["bucket"] < rt.BUCKET_HIDDEN               # 一覧には出す（確認待ちと明示）


@pytest.mark.skipif(_NODE is None, reason="node が無い")
def test_unconfirmed_same_in_browser_runtime():
    vm = _vm(collection_method="MANUAL_VERIFIED", verified=False, confidence="medium")
    nows = [NOW, NOW + timedelta(days=2) - timedelta(seconds=1), NOW + timedelta(days=2)]
    for t, row in zip(nows, _js([vm], nows)):
        assert rt.derive_runtime_state(vm, t) == row[0], t


def test_date_only_deadline_sorts_as_end_of_day():
    from src.content.ui import lottery_page as lp
    assert lp._ms("2026-10-03", end=True) == str(int(datetime.fromisoformat("2026-10-04T00:00:00+09:00").timestamp() * 1000))
    assert lp._ms("2026-10-03") == str(int(datetime.fromisoformat("2026-10-03T00:00:00+09:00").timestamp() * 1000))


def test_conflict_details_do_not_assert_one_schedule():
    sec = _section(shell.render_root(_ctx([lot(7, conflict=True)])), "lottery")
    row = re.search(r'data-nu-lot="L7".*?</article>', sec, re.S).group(0)
    assert "公式情報どうしで食い違っています" in row and "<dt>応募期間</dt>" not in row and "当選発表 " not in row


def test_release_has_no_requirements_and_no_duplicate_link():
    sec = _section(shell.render_root(_ctx([lot(1, region="JP")], [release("発売待ち", 4)])), "lottery")
    rel = re.search(r'data-nu-kind="release".*?</article>', sec, re.S).group(0)
    assert "応募条件" not in rel and "情報元を開く" not in rel        # ボタン（公式情報を見る）と同じ URL を重ねない
    l1 = re.search(r'data-nu-lot="L1".*?</article>', sec, re.S).group(0)
    assert "販売店・地域" not in l1 and ">JP<" not in l1                 # 地域コード JP は出さない
    assert "情報元を開く" in l1                                          # 応募ページと情報元が別なら詳細に出す


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_deadline_sort_keeps_today_date_only_first(tmp_path):
    js = _LOT + """
    var o = {};
    o.dl = click('a[data-nu-lparam="sort"][data-nu-lvalue="deadline"]'); o.ids = vis();
    done(o);
    """
    lots = [lot(1, application_end=_iso(days=3)),
            lot(2, application_end=None, application_end_date=NOW.strftime("%Y-%m-%d"))]   # 今日が締切（時刻未公表）
    o = _run(tmp_path, js, query="?ui=new&page=lottery", tcg_report={"lotteries": lots, "events": []},
             legacy_lotteries=[], profit_deals=[], profit_routes={"main_routes": []})
    assert o["ids"] == ["L2", "L1"]


def test_no_duplicate_winner_line_or_conflict_sort_key():
    sec = _section(shell.render_root(_ctx([lot(5, application_start=_iso(days=-5), application_end=_iso(days=-1),
                                                 winner_announcement_at=_iso(days=2)),
                                             lot(7, conflict=True), lot(3, application_start=_iso(hours=3))])), "lottery")
    l5 = re.search(r'data-nu-lot="L5".*?</article>', sec, re.S).group(0)
    assert "nu-lrow__sub" not in l5                                     # 結果待ちは主の行に当選発表が出る
    l7 = re.search(r'<article class="nu-lrow"[^>]*data-nu-lot="L7"[^>]*>', sec).group(0)
    assert 'data-ae=""' in l7 and 'data-as=""' in l7                  # 食い違う日程で並べない
    l3 = re.search(r'data-nu-lot="L3".*?</article>', sec, re.S).group(0)
    assert "情報元を開く" not in l3                                     # ボタンが公式情報（同じ URL）のときは重ねない

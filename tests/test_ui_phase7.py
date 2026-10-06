"""UI Phase 7: マイページ（ウォッチ・締切・通知と変化の履歴・通知条件。このブラウザに保存）。

データは test_ui_phase6 と同じ架空の商品。利益・ROI はマイページで計算し直さない（確定値をそのまま出す）。
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from datetime import timedelta
from pathlib import Path

import pytest

from src.content.ui import mypage, navigation, product_page, shell
from src.content.ui import opportunity as opp

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


P6 = _load("ui_phase6_for_p7", ROOT / "tests" / "test_ui_phase6.py")
RF = _load("route_fixtures_p7", ROOT / "tests" / "route_fixtures.py")
KW, NOW, CHROME, _run, _HELPERS = P6.KW, P6.NOW, P6.CHROME, P6._run, P6._HELPERS


def _root(**kw):
    return shell.render_root(P6._ctx(**kw))


def _mp(root: str) -> str:
    i = root.index('data-nu-page="mypage"')
    return root[i:root.index("</main>", i)]


def _views(**kw):
    return P6._catalog_views(**kw)[0]


# ── 描画（Python） ────────────────────────────────────────────────────────

def test_page_is_registered_and_linked():
    root = _root()
    assert "mypage" in navigation.PAGES and shell.PAGE_TITLES["mypage"] == "マイページ"
    assert 'data-nu-nav="mypage"' in root and "page=mypage" in root                 # 上部のアイコン・メニュー
    assert len(navigation.BOTTOM_ITEMS) == 5                                          # ボトムナビは増やさない
    mp = _mp(root)
    # 全商品のカードを作って隠しておき、ウォッチ中だけをブラウザで出す（本番の HTML に個人のウォッチは入れない）
    assert mp.count("data-nu-mp-card=") == len(P6.PRODUCTS)
    assert all(" hidden>" in m for m in re.findall(r'<li class="nu-mp-card"[^>]*>', mp))
    assert "このブラウザに保存" in mp and "ログインなし" in mp and "引き継がれません" in mp


def test_no_fake_account_or_sync_state():
    text = re.sub(r"<[^>]+>", " ", _mp(_root()))
    for w in ("ログイン済み", "ログイン中", "同期済み", "クラウドに保存", "通知登録完了", "会員", "プラン", "DEMO", "SAMPLE"):
        assert w not in text, w
    assert not re.search(r"[\w.+-]+@[\w-]+\.[\w.]+", text)
    assert "配信には対応していません" in text                                         # 通知が届くと言わない


def test_card_values_are_canonical_not_recomputed():
    views = _views()
    v = views["prod_tcam"]
    html = mypage._card(v, int(NOW.timestamp() * 1000))
    o = v.opportunity
    assert f'data-net="{int(o.net_profit)}"' in html and f"+¥{int(o.net_profit):,}" in html
    assert f"ROI {o.roi * 100:.1f}%" in html and "買取店A（利益の計算に使った売却先）" in html
    assert f"¥{v.best_buy.acquisition:,}" in html
    # 利益の無い商品は「算出前」（0 円・推測の値を出さない）
    g = mypage._card(views["prod_tgame"], 0)
    assert 'data-net=""' in g and "算出前" in g and "¥0" not in g


@pytest.mark.parametrize("mutate, check", [
    (dict(sell_identity_verified=False), "unverified_sell"),        # 売却側の照合が未了 → 利益なし
    (dict(sell_checked_at=(NOW - timedelta(days=20)).isoformat()), "stale_sell"),   # 古い買取価格 → 利益なし
])
def test_mutations_drop_profit_on_mypage(mutate, check):
    deal = dict(P6.DEAL, **mutate)
    v = _views(profit_deals=[deal])["prod_tcam"]
    html = mypage._card(v, 0)
    assert v.opportunity is None and 'data-net=""' in html and "算出前" in html, check


def test_unknown_stock_is_not_available_on_mypage():
    stock = json.loads(json.dumps(P6.STOCK))
    stock["entries"]["official:prod_tcam:s"]["state"] = "UNKNOWN"
    v = _views(stock_history=stock)["prod_tcam"]
    html = mypage._card(v, 0)
    assert "購入可能" not in html and v.status != "AVAILABLE"


def test_lottery_entries_keep_runtime_gate():
    """締切の一覧は抽選の runtime の判定のまま（人の確認が済んでいない抽選に応募ボタンを出さない）。"""
    from src.content.ui import runtime as rt
    v = _views()["prod_tgame"]
    lv, st = v.lotteries[0]
    assert st["cta"]["kind"] == "apply" and "応募する" in mypage._lottery_entry(v, lv, st)   # 否定対照
    lv.vm = dict(lv.vm, unv=True)
    lv.human_confirmed = False
    st2 = rt.derive_runtime_state(lv.vm, NOW)
    html = mypage._lottery_entry(v, lv, st2)
    assert "応募する" not in html and 'data-nu-lot="' in html


def test_events_only_user_facing_and_current_routes():
    views = _views()
    safe = RF.safe_route(NOW, "prod_tcam")
    rid = opp.route_key(safe)
    at = (NOW - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M JST")
    notes = [
        {"type": "WATCH_TO_BUY", "product_id": "prod_tcam", "route_id": rid, "route_checked": True, "created_at": at,
         "data": {"net_profit": 31000, "roi": 0.15}},
        {"type": "NEW_MAIN", "product_id": "prod_tcam", "route_id": "old", "route_checked": True, "created_at": at,
         "data": {"net_profit": 39009}},                                             # 今は確定ルートでない
        {"type": "ROI_UP", "product_id": "prod_tcam", "route_id": rid, "created_at": at, "data": {}},  # 判定の印なし
        {"type": "HEALTH_ALERT", "product_id": "_health", "created_at": at, "data": {}},          # 管理者向け
        {"type": "SOMETHING_NEW", "product_id": "prod_tcam", "route_id": rid, "route_checked": True, "created_at": at},
        {"type": "WATCH_TO_BUY", "product_id": "prod_unknown", "route_id": rid, "route_checked": True, "created_at": at},
    ]
    evs = mypage.build_events(views, notes, {"main_routes": [safe]}, NOW)
    notices = [e for e in evs if e["kind"] == "notice"]
    assert [(e["label"], e["pid"]) for e in notices] == [("買い時の条件に到達", "prod_tcam")]
    n = notices[0]
    assert "利益 ¥31,000" in n["what"] and n["now"].startswith(views["prod_tcam"].status_label)
    assert all("39,009" not in e["what"] for e in evs)
    # 変化（在庫の再入荷・価格の差）も、根拠のあるものだけ
    ch = [e for e in evs if e["kind"] == "change"]
    assert any(e["label"] == "再入荷" for e in ch) and all(e["pid"] in views for e in ch)
    assert evs == sorted(evs, key=lambda e: e["ms"] or 0, reverse=True)
    li = mypage._event_li(n)
    # 生成時の状態は「生成時点」と書き、ブラウザがカードの今の表示（期限・締切の後の状態）に置き換える
    assert "当時の通知" in li and "生成時点の状態" in li and "data-nu-mp-evnow" in li and "通知 " in li


def test_date_only_event_time_is_not_invented():
    assert "（日付のみ）" in mypage._when("2026-10-02") and "00:00" not in mypage._when("2026-10-02")


def test_watch_buttons_on_lists_and_detail():
    root = _root()
    ids = set(re.findall(r'data-nu-watch="([^"]+)"', root))
    assert ids and ids <= {p["product_id"] for p in P6.PRODUCTS}
    for page in ("search", "opportunities", "lottery"):
        sec = root[root.index(f'data-nu-page="{page}"'):]
        sec = sec[:sec.index('<section class="nu-page')] if '<section class="nu-page' in sec else sec
        assert "data-nu-watch=" in sec, page
    art = P6._article(root, "prod_tcam")
    assert 'class="nu-watch"' in art                                                 # 詳細はラベルつき
    # 主なボタン（購入・応募）より控えめ（nu-btn--primary ではない）
    assert "nu-btn--primary" not in product_page.watch_button("p", "P")


def test_deploy_check_834(tmp_path, monkeypatch):
    root = _root()
    page = "<html><body>" + root + "</body></html>"
    dc = _load("deploy_check_p7", ROOT / "scripts" / "deploy_check.py")

    def run(html, name):
        r = tmp_path / name
        (r / "docs").mkdir(parents=True)
        (r / "docs/index.html").write_text(html, encoding="utf-8")
        for n in ("config", "data", "exports", "src", "scripts"):
            (r / n).symlink_to(ROOT / n)
        monkeypatch.setattr(dc, "PROJECT_ROOT", r)
        monkeypatch.setattr(dc, "PUBLIC_DIR", r / "docs")
        return {x["check"]: x for x in dc._check_data_correctness()}["mypage_safe"]
    assert run(page, "ok")["level"] == "ok"
    net = int(_views()["prod_tcam"].opportunity.net_profit)
    for i, bad in enumerate((page.replace("このブラウザに保存（ログインなし）", "ログイン済み"),
                             page.replace('data-nu-watch="prod_tcam"', 'data-nu-watch="prod_nope"', 1),
                             page.replace(f'data-net="{net}"', 'data-net="99999"', 1))):
        assert run(bad, f"ng{i}")["level"] == "error", i


# ── ブラウザ（Chrome） ─────────────────────────────────────────────────────

_MP = _HELPERS + """
function mp(){ return R.querySelector('[data-nu-page="mypage"]'); }
function shown(){ return [].slice.call(mp().querySelectorAll('[data-nu-mp-card]')).filter(function(c){return !c.hidden;})
  .map(function(c){return c.getAttribute('data-nu-mp-card');}); }
function n(k){ return mp().querySelector('[data-nu-mp-n="' + k + '"]').textContent; }
function go(u){ history.pushState(null, '', u); window.dispatchEvent(new PopStateEvent('popstate')); }
"""


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_watch_flow_persistence_and_storage(tmp_path):
    js = _MP + """
    var o = {};
    o.empty = !mp().querySelector('[data-nu-mp-empty]').hidden; o.n0 = n('watched');
    go('?ui=new&page=product&product_id=prod_tcam');
    var b = R.querySelector('[data-nu-pd="prod_tcam"] [data-nu-watch]'); b.click();
    o.pressed = b.getAttribute('aria-pressed'); o.label = b.textContent.trim();
    // 同じ商品の別の画面のボタンも同じ状態
    o.searchPressed = R.querySelector('[data-nu-page="search"] [data-nu-watch="prod_tcam"]').getAttribute('aria-pressed');
    o.dup = NuStore.add('prod_tcam'); o.invalid = NuStore.add('prod_does_not_exist');
    // 読み直し（再読み込みと同じ: 保存から作り直す）
    NuStore.reload(); go('?ui=new&page=mypage');
    o.after = shown(); o.n1 = n('watched'); o.profit = n('profit');
    o.stored = JSON.parse(localStorage.getItem('premium-monitor.mypage'));
    // 解除
    mp().querySelector('[data-nu-mp-card="prod_tcam"] [data-nu-watch]').click(); o.removed = shown();
    // 壊れた保存・古い版は初期値に戻る（エラーで止まらない）
    localStorage.setItem('premium-monitor.mypage', '{broken'); NuStore.reload(); o.corrupt = NuStore.data().watch.length;
    localStorage.setItem('premium-monitor.mypage', JSON.stringify({v: 99, watch: [{id: 'prod_tcam', at: 1}]}));
    NuStore.reload(); o.schema = NuStore.data().watch.length;
    localStorage.setItem('premium-monitor.mypage', JSON.stringify({v: 1, watch: [{id: 'prod_tcam', at: 1},
      {id: 'prod_tcam', at: 2}, {id: 'not_listed_now', at: 3}, {id: 5}, {id: '<x>'}]})); NuStore.reload();
    o.cleaned = NuStore.data().watch.map(function(w){return w.id;}); o.shownIds = NuStore.ids().map(function(w){return w.id;});
    NuStore.reset(); o.reset = localStorage.getItem('premium-monitor.mypage');
    done(o);
    """
    o = _run(tmp_path, js, query="?ui=new&page=mypage", **KW)
    assert o["empty"] and o["n0"] == "0"
    assert o["pressed"] == "true" and "ウォッチ中" in o["label"] and o["searchPressed"] == "true"
    assert o["dup"] is False and o["invalid"] is False
    assert o["after"] == ["prod_tcam"] and o["n1"] == "1" and o["profit"] == "1"
    assert o["stored"]["v"] == 1 and [w["id"] for w in o["stored"]["watch"]] == ["prod_tcam"]
    assert set(o["stored"]) == {"v", "watch", "prefs", "read"}                       # 秘密の情報は保存しない
    assert o["removed"] == [] and o["corrupt"] == 0 and o["schema"] == 0
    # 重複・形の違う ID は捨て、今の一覧に無い ID は保存に残す（表示しないだけ）
    assert o["cleaned"] == ["prod_tcam", "not_listed_now"] and o["shownIds"] == ["prod_tcam"] and o["reset"] is None


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_notifications_read_threshold_and_sections(tmp_path):
    js = _MP + """
    var o = {};
    NuStore.add('prod_tcam'); NuStore.add('prod_tgame');
    go('?ui=new&page=mypage&section=notifications');
    o.panel = [].slice.call(mp().querySelectorAll('[data-nu-mp-panel]')).filter(function(p){return !p.hidden;})
      .map(function(p){return p.getAttribute('data-nu-mp-panel');});
    var evs = function(){ return [].slice.call(mp().querySelectorAll('[data-nu-mp-evs] [data-nu-mp-ev]')).filter(function(e){return !e.hidden;}); };
    o.events = evs().length; o.unread = n('unread');
    mp().querySelector('[data-nu-mp-readall]').click(); o.unreadAfter = n('unread');
    o.readMarks = evs().map(function(e){return e.querySelector('[data-nu-mp-evstate]').textContent;});
    // 通知条件で種類を絞る（在庫の変化をオフ）
    var ck = mp().querySelector('[data-nu-mp-pref="notify.restock"]'); ck.click();
    o.eventsNoRestock = evs().length;
    // 利益条件の最低ライン: 件数だけが変わり、カードの値（確定値）は変わらない
    var card = mp().querySelector('[data-nu-mp-card="prod_tcam"]'); var net = card.getAttribute('data-net');
    var sel = mp().querySelector('[data-nu-mp-pref="min_profit"]'); sel.value = '30000';
    sel.dispatchEvent(new Event('change', {bubbles: true}));
    o.profitHigh = n('profit'); o.netAfter = card.getAttribute('data-net'); o.netBefore = net;
    o.cardText = card.textContent.indexOf('+¥' + Number(net).toLocaleString('en-US')) >= 0;
    // 戻る（タブは URL の section）
    go('?ui=new&page=mypage&section=settings'); history.back();
    setTimeout(function(){ o.backQ = location.search; o.storage = mp().textContent.indexOf('このブラウザにだけ') >= 0; done(o); }, 300);
    """
    o = _run(tmp_path, js, query="?ui=new&page=mypage", **KW)
    assert o["panel"] == ["notifications"] and o["events"] >= 1 and o["unread"] == str(o["events"])
    assert o["unreadAfter"] == "0" and set(o["readMarks"]) == {"既読"}
    assert o["eventsNoRestock"] < o["events"]
    assert o["profitHigh"] == "1" and o["netAfter"] == o["netBefore"] and o["cardText"]   # 30,200 ≥ 30,000
    assert "section=notifications" in o["backQ"] and o["storage"]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_stock_expiry_and_lottery_deadline(tmp_path):
    later = NOW + timedelta(hours=6)
    js = _MP + """
    NuStore.add('prod_tcam'); NuStore.add('prod_tgame');
    Date.now = function(){ return %d; };
    window.dispatchEvent(new PageTransitionEvent('pageshow'));
    setTimeout(function(){
      go('?ui=new&page=mypage');
      var card = mp().querySelector('[data-nu-mp-card="prod_tcam"]');
      var badge = card.querySelector('[data-nu-mp-status]');
      var stockCell = [].slice.call(card.querySelectorAll('.nu-mp-m')).filter(function(m){return m.querySelector('dt').textContent === '在庫';})[0];
      var lots = [].slice.call(mp().querySelectorAll('[data-nu-mp-lots] [data-nu-mp-pid]')).filter(function(l){return !l.hidden;});
      go('?ui=new&page=mypage&section=notifications');
      var nows = [].slice.call(mp().querySelectorAll('[data-nu-mp-evs] [data-nu-mp-ev]')).filter(function(e){return !e.hidden && e.getAttribute('data-nu-mp-pid') === 'prod_tcam';})
        .map(function(e){return e.querySelector('[data-nu-mp-evnow]').textContent;});
      done({badge: badge.textContent.trim(), stock: stockCell.querySelector('b').textContent,
            lots: lots.map(function(l){return l.querySelector('.nu-badge').textContent.trim();}), nows: nows,
            chip: mp().querySelector('[data-nu-mp-card="prod_tgame"] [data-nu-mp-lotchip]').textContent});
    }, 200);
    """ % int(later.timestamp() * 1000)
    o = _run(tmp_path, js, query="?ui=new&page=mypage", **KW)
    assert "購入可能" not in o["badge"] and "更新待ち" in o["badge"]     # 在庫ありと言える期限（3時間）が過ぎた
    assert "購入可能" not in o["stock"] and "更新待ち" in o["stock"]     # 同じカードの在庫の欄も
    assert o["nows"] and all(n.startswith("今の状態: 在庫未確認（更新待ち）") for n in o["nows"])   # 履歴の「今の状態」も
    assert o["lots"] and "受付中" in o["lots"][0] and o["chip"]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
@pytest.mark.parametrize("width", [500, 640, 700, 768, 1024, 1440])
def test_dom_mypage_no_overflow(tmp_path, width):
    js = _MP + """
    NuStore.add('prod_tcam'); NuStore.add('prod_tgame'); NuStore.add('prod_gr4');
    var o = {};
    ['watchlist', 'notifications', 'settings'].forEach(function(s){
      go('?ui=new&page=mypage&section=' + s);
      o[s] = document.documentElement.scrollWidth - document.documentElement.clientWidth;
    });
    o.small = [].slice.call(mp().querySelectorAll('button, select, .nu-mp-tab, .nu-watch'))
      .filter(function(e){ return e.offsetParent && e.getBoundingClientRect().height < 44; }).length;
    done(o);
    """
    o = _run(tmp_path, js, width=width, query="?ui=new&page=mypage", **KW)
    assert o["watchlist"] <= 0 and o["notifications"] <= 0 and o["settings"] <= 0, o
    assert o["small"] == 0


def test_deploy_check_803_storage_only_in_mypage_store():
    """localStorage はマイページの保存の入口（NuStore）だけ。新UIの既定化（ui）に使えば ERROR。"""
    dc = _load("deploy_check_p7b", ROOT / "scripts" / "deploy_check.py")
    head = shell.render_head()
    page = "<html><head>" + head + "</head><body>" + _root() + "</body></html>"

    def lv(html):
        return {x["check"]: x["level"] for x in dc._check_new_ui(html)}["new_ui_flag_only"]
    assert lv(page) == "ok"
    assert lv(page.replace("</main>", "<script>localStorage.setItem('x','1')</script></main>", 1)) == "error"
    assert lv(page.replace("var GROUPS = ", "var UIKEY = 'ui'; var GROUPS = ", 1)) == "error"

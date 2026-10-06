"""UI Phase 8: 新UIを正式の表示にする。UI Phase 10 で旧UIを削除した（このファイルは Phase 10 の仕様に合わせた）。

- クエリなし・?ui=new・?ui=それ以外・?ui=legacy → 新UI。?ui=legacy（旧表示のブックマーク）は「旧表示は終了しました」と
  小さく知らせ、URL から ui を外す
- 表示は URL だけで決める（cookie・localStorage・過去の設定では切り替えない）
- 作るリンクに ui=new・ui=legacy は付けない（古い URL・ブックマークはそのまま開ける）
"""

from __future__ import annotations

import collections
import importlib.util
import re
import sys
from pathlib import Path

import pytest

from src.content.ui import navigation, shell

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


P6 = _load("ui_phase6_for_p8", ROOT / "tests" / "test_ui_phase6.py")
KW, CHROME, _run, _HELPERS = P6.KW, P6.CHROME, P6._run, P6._HELPERS


def _root(**kw):
    return shell.render_root(P6._ctx(**kw))


def _page():
    return "<html><head>" + shell.render_head() + "</head><body>" + _root() + "</body></html>"


# ── 生成した HTML ──────────────────────────────────────────────────────

def test_head_defaults_to_new_ui_by_url_only():
    head = shell.render_head()
    assert "legacy" not in head and "var d=document.documentElement;d.classList.add('ui-new');" in head
    # UI Phase 10: アーカイブでも新UI。ルーターが動かなければ旧UIではなく静的な案内（#nu-fallback）へ
    assert "/archive/" not in head
    assert "if(!r||r.hidden){d.classList.remove('ui-new');d.classList.add('ui-fallback');}" in head
    for w in ("localStorage", "sessionStorage", "cookie"):                     # URL 以外では決めない
        assert w not in head


def test_links_are_canonical_and_no_legacy_entry():
    root = _root()
    assert navigation.page_href("home") == "./" and navigation.page_href("lottery") == "?page=lottery"
    assert navigation.page_href("home", category="camera") == "?category=camera"
    assert not re.search(r'href="[^"]*[?&](amp;)?ui=', root)                    # 作るリンクに ui= を付けない
    assert "nu-legacy-note" not in root and not re.search(r'href="[^"]*ui=legacy', root)   # 旧表示への入口・案内は無い
    assert 'id="nu-legacy-ended"' in root and "旧表示は終了しました" in root      # 古いブックマークで開いたときの案内
    assert "現行版" not in re.sub(r"<[^>]+>", " ", root)


def test_router_migrates_ui_param_to_new_ui():
    """?ui=…（旧表示・古い ?ui=new）は新UIで開き、URL から ui・from を外す（旧UIへ行く分岐は無い）。"""
    root = _root()
    assert "params.delete('ui'); params.delete('from');" in root
    assert "var LEGACY_URL = params.get('ui') === 'legacy';" in root and "ui-legacy" not in root


def test_no_duplicate_ids_in_page(monkeypatch):
    """ページ全体（静的な案内・新UI）の id が重ならない。旧UIの id は無い（UI Phase 10）。"""
    T = _load("test_new_ui_for_p8", ROOT / "tests" / "test_new_ui.py")
    from src.content.daily_lp_generator import DailyLPGenerator
    # 別のテストが staticmethod を外したまま戻すことがある（その影響を受けないように、ここで決め直す）
    monkeypatch.setattr(DailyLPGenerator, "_load_tcg_report", staticmethod(lambda: {}))
    html, _parts = T._render_lp(monkeypatch, new_ui=True)
    s, e = html.find('<div id="new-ui-root"'), html.find("<!-- /new-ui-root -->")
    new_ids = re.findall(r'\sid="([^"]+)"', html[s:e])
    other_ids = re.findall(r'\sid="([^"]+)"', html[:s] + html[e:])
    assert not [k for k, v in collections.Counter(new_ids).items() if v > 1]
    assert not set(new_ids) & set(other_ids) and set(other_ids) == {"nu-fallback"}
    assert not [i for i in new_ids + other_ids if i.startswith("tab-") or i == "main-tab-nav"]


def test_deploy_check_802_803_835_and_mutations():
    dc = _load("deploy_check_p8", ROOT / "scripts" / "deploy_check.py")
    page = _page()

    def lv(html, key):
        return {x["check"]: x["level"] for x in dc._check_new_ui(html)}[key]
    assert lv(page, "new_ui_default") == "ok" and lv(page, "new_ui_flag_only") == "ok"
    assert lv(page, "legacy_url_compat") == "ok" and lv(page, "no_legacy_ui") == "ok"
    # 既定が旧UIに戻る（ui-new を付けない）
    assert lv(page.replace("d.classList.add('ui-new');", "", 1), "new_ui_default") == "error"
    # 過去の設定（localStorage）で表示を決める
    assert lv(page.replace("var d=document.documentElement;",
                           "var d=document.documentElement;if(localStorage.getItem('ui')){}", 1),
              "new_ui_flag_only") == "error"
    # head が旧UIの判定（?ui=legacy で旧UI）に戻る
    assert lv(page.replace("d.classList.add('ui-new');",
                           "if(new URLSearchParams(location.search).get('ui')==='legacy'){d.classList.add('ui-legacy');}"
                           "else{d.classList.add('ui-new');}", 1), "new_ui_default") == "error"
    # ?ui= を URL から外さない（古い ?ui=legacy の URL のまま残る）
    assert lv(page.replace("params.delete('ui'); params.delete('from');", "", 1), "legacy_url_compat") == "error"
    # 「旧表示は終了しました」の案内が無い
    assert lv(page.replace('id="nu-legacy-ended"', 'id="x"', 1), "legacy_url_compat") == "error"
    # 作るリンクに ui=new・ui=legacy が戻る
    assert lv(page.replace('href="?page=lottery"', 'href="?ui=new&amp;page=lottery"', 1),
              "legacy_url_compat") == "error"
    assert lv(page.replace('href="?page=lottery"', 'href="./?ui=legacy"', 1), "legacy_url_compat") == "error"
    # 旧UIのハッシュの読み替えが壊れる（#tab-health が運営者向けのページに行かない・#product- が商品詳細に行かない）
    assert lv(page.replace("&quot;tab-health&quot;: {&quot;page&quot;: &quot;admin&quot;}",
                           "&quot;tab-health&quot;: {&quot;page&quot;: &quot;home&quot;}", 1),
              "legacy_url_compat") == "error"
    assert lv(page.replace("q.set('page', 'product'); q.set('product_id', PD_ALIAS[alias])", "", 1),
              "legacy_url_compat") == "error"
    # 旧UIの DOM・JS が戻る
    assert lv(page.replace("<body>", '<body><div id="tab-ranking"></div>', 1), "no_legacy_ui") == "error"
    assert lv(page.replace("<body>", "<body><script>function activateTab(t){}</script>", 1), "no_legacy_ui") == "error"


# ── ブラウザ（Chrome） ─────────────────────────────────────────────────────

_S = _HELPERS + """
function vis(sel){ var e = document.querySelector(sel); return !!e && getComputedStyle(e).display !== 'none' && !e.hidden; }
function snap(){ return {cls: document.documentElement.className, newUi: vis('#new-ui-root'), old: vis('header.topbar'),
  note: vis('#nu-legacy-ended'), page: state().page, q: location.search, title: document.title}; }
"""


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
@pytest.mark.parametrize("query, page, q_after, ended", [
    ("", "home", "", False), ("?ui=new", "home", "", False), ("?ui=foo", "home", "", False),
    ("?ui=legacy", "home", "", True), ("?ui=legacy&page=lottery", "lottery", "?page=lottery", True)])
def test_dom_default_and_legacy_routing(tmp_path, query, page, q_after, ended):
    """どの ?ui= でも新UI（旧UIは削除済み）。URL から ui を外し、?ui=legacy のときだけ「旧表示は終了しました」。"""
    o = _run(tmp_path, _S + "done(snap());", query=query, **KW)
    assert "ui-new" in o["cls"].split() and o["newUi"] and o["old"] is False and "ui-legacy" not in o["cls"]
    assert o["page"] == page and o["q"] == q_after and o["note"] is ended


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
@pytest.mark.parametrize("query, page", [("?page=profit", "opportunities"), ("?page=opportunities", "opportunities"),
                                         ("?page=lottery", "lottery"), ("?page=restock", "restock"),
                                         ("?page=routes", "routes"), ("?page=search&q=TEST", "search"),
                                         ("?page=product&product_id=prod_tcam&tab=history", "product"),
                                         ("?page=mypage&section=settings", "mypage"),
                                         ("?ui=new&page=product&product_id=prod_tcam", "product")])
def test_dom_direct_urls_without_ui(tmp_path, query, page):
    o = _run(tmp_path, _S + "done(snap());", query=query, **KW)
    assert o["newUi"] and o["page"] == page and not o["old"]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_back_forward_and_watchlist_across_url_forms(tmp_path):
    js = _S + """
    var o = {};
    // ?ui=new の形で保存したウォッチが、ui の無い URL でも同じに出る（キーも中身も変えない）
    NuStore.add('prod_tcam');
    NuStore.reload();
    R.querySelector('.nu-header a[data-nu-nav="mypage"]').click();
    o.mypage = state().page; o.mq = location.search;
    o.cards = [].slice.call(R.querySelectorAll('[data-nu-mp-card]')).filter(function(c){return !c.hidden;})
      .map(function(c){return c.getAttribute('data-nu-mp-card');});
    // HOME → 利益商品 → 商品詳細 → 戻る → 利益商品
    R.querySelector('.nu-topnav a[data-nu-nav="home"]').click(); o.homeQ = location.search;
    R.querySelector('.nu-topnav a[data-nu-nav="opportunities"]').click(); o.oppQ = location.search;
    R.querySelector('[data-nu-page="opportunities"] a.nu-pdlink').click(); o.pdQ = location.search;
    R.querySelector('[data-nu-back]').click();
    setTimeout(function(){
      o.backPage = state().page; o.backQ = location.search;
      // マイページ → 通知 → 戻る
      R.querySelector('.nu-header a[data-nu-nav="mypage"]').click();
      R.querySelector('[data-nu-page="mypage"] [data-nu-mp-tab="notifications"]').click(); o.notQ = location.search;
      history.back();
      setTimeout(function(){ o.back2 = location.search; o.back2Page = state().page; done(o); }, 300);
    }, 300);
    """
    o = _run(tmp_path, js, query="?ui=new&page=mypage", **KW)
    assert o["mypage"] == "mypage" and o["mq"] == "?page=mypage" and o["cards"] == ["prod_tcam"]
    assert o["homeQ"] == "" and o["oppQ"] == "?page=opportunities"
    assert o["pdQ"].startswith("?page=product&product_id=prod_tcam")
    assert o["backPage"] == "opportunities" and o["backQ"] == "?page=opportunities"
    assert o["notQ"] == "?page=mypage&section=notifications"
    assert o["back2"] == "?page=mypage" and o["back2Page"] == "mypage"


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_hidden_legacy_is_not_focusable(tmp_path):
    js = _S + """
    var old = document.querySelector('header.topbar');
    old.setAttribute('tabindex', '0');
    old.focus();
    done({active: document.activeElement === old, display: getComputedStyle(old).display});
    """
    o = _run(tmp_path, js, query="", **KW)
    assert o["display"] == "none" and o["active"] is False                     # 隠した旧UIにフォーカスが入らない


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
@pytest.mark.parametrize("hash_, page, extra", [("#product-tcam", "product", "product_id=prod_tcam"),
                                                ("#product-nothing_here", "search", "q=nothing+here"),
                                                ("#tab-lottery", "lottery", "")])
def test_dom_legacy_hash_links(tmp_path, hash_, page, extra):
    """旧UIの古いリンク（#product-… など）は、既定の新UIで対応するページに読み替える（商品カード → 商品詳細）。"""
    js = _S + "done(snap());"
    import html as _h
    import json as _j
    import subprocess
    root = shell.render_root(P6._ctx())
    page_html = ("<!doctype html><html lang='ja'><head><meta charset='utf-8'>" + shell.render_head()
                 + "</head><body>" + root + "<header class='topbar'>old</header><pre id='out'></pre>"
                 "<script>window.addEventListener('load',function(){setTimeout(function(){" + js + "},50);});</script></body></html>")
    f = tmp_path / "page.html"
    f.write_text(page_html, encoding="utf-8")
    res = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--window-size=1200,900",
                          "--virtual-time-budget=4000", "--dump-dom", f.as_uri() + hash_],
                         capture_output=True, text=True, timeout=60)
    s = res.stdout.find('<pre id="out">')
    o = _j.loads(_h.unescape(res.stdout[s + len('<pre id="out">'):res.stdout.find("</pre>", s)]))
    assert o["page"] == page and extra in o["q"] and o["newUi"]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_router_failure_shows_static_fallback(tmp_path):
    """新UIのルーター（本文を表示するスクリプト）だけが止まっても、読み込みの終わりに静的な案内を出す
    （白い画面にしない。UI Phase 10 からは旧UIには戻さない）。"""
    import html as _h
    import json as _j
    import subprocess
    root = shell.render_root(P6._ctx())
    marker = "var root = document.getElementById('new-ui-root');"
    assert marker in root
    head_, _, tail = root.rpartition(marker)                 # ルーター（最後のスクリプト）だけを止める
    broken = head_ + "throw new Error('router stopped');" + marker + tail
    js = ("var o={cls:document.documentElement.className,"
          "old:getComputedStyle(document.querySelector('header.topbar')).display!=='none',"
          "fb:getComputedStyle(document.getElementById('nu-fallback')).display!=='none',"
          "fbText:document.getElementById('nu-fallback').innerText};"
          "document.getElementById('out').textContent=JSON.stringify(o);")
    page = ("<!doctype html><html lang='ja'><head><meta charset='utf-8'>" + shell.render_head() + "</head><body>"
            + broken + "<header class='topbar'>old</header><pre id='out'></pre>"
            "<script>window.addEventListener('load',function(){setTimeout(function(){" + js + "},50);});</script>"
            "</body></html>")
    f = tmp_path / "page.html"
    f.write_text(page, encoding="utf-8")
    res = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--window-size=1200,900",
                          "--virtual-time-budget=4000", "--dump-dom", f.as_uri()],
                         capture_output=True, text=True, timeout=60)
    st = res.stdout.find('<pre id="out">')
    o = _j.loads(_h.unescape(res.stdout[st + len('<pre id="out">'):res.stdout.find("</pre>", st)]))
    assert "ui-new" not in o["cls"].split() and "ui-fallback" in o["cls"].split()
    assert o["fb"] is True and o["old"] is False and "JavaScript を有効にすると" in o["fbText"]

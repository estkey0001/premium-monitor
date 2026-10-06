"""UI Phase 10（段階A）: 旧UIを消す前に、旧UIへの依存を外す。

- JS が無い・ルーターが動かなかったとき: 旧UIではなく静的な案内（#nu-fallback。生成時点の値と主なページへのリンク）
- アーカイブ（docs/archive/<日付>.html）: 新UIで出し、「その日の記録」の案内と今のサイトへの戻り道を出す。
  docs/archive/index.html は今のサイトへ転送する（過去の LP のファイルは書き換えない）
- 旧UIにしか無かった注意書き（購入を推奨するものではありません 等）・外部リンク（note など）・クリックの計測を新UIへ
データはすべて架空。
"""

from __future__ import annotations

import html as html_mod
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from src.content.ui import pages, shell

ROOT = Path(__file__).resolve().parent.parent


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


P6 = _load("ui_phase6_for_p10", ROOT / "tests" / "test_ui_phase6.py")
KW, NOW, CHROME = P6.KW, P6.NOW, P6.CHROME
DC = _load("deploy_check_p10", ROOT / "scripts" / "deploy_check.py")


def _root(**kw) -> str:
    return shell.render_root(P6._ctx(**dict(KW, **kw)))


def _page(**kw) -> str:
    return "<html><head>" + shell.render_head() + "</head><body>" + _root(**kw) + "</body></html>"


def _fallback(html: str) -> str:
    s = html.find('<div id="nu-fallback"')
    return html[s:html.find("</ul></div></div>", s)]


def _lv(html: str, key: str) -> str:
    return {x["check"]: x["level"] for x in DC._check_new_ui(html)}[key]


# ── 静的な案内（JS が無い・ルーターが動かない） ───────────────────────────────

def test_fallback_is_static_and_before_root():
    root = _root()
    fb = _fallback(root)
    assert root.count('<div id="nu-fallback"') == 1 and root.find('id="nu-fallback"') < root.find('id="new-ui-root"')
    assert "<h1>" in fb and "JavaScript を有効にすると" in fb and "生成時点の値" in fb
    for href in ('href="./"', 'href="?page=opportunities"', 'href="?page=lottery"', 'href="?page=restock"',
                 'href="?page=routes"', 'href="?page=search"'):
        assert href in fb
    assert not re.search(r"¥0(?![0-9,])|DEMO|<script|<button|<input", fb)          # 値は静的・操作なし
    assert pages.DISCLAIMER in fb and all(html_mod.escape(t) in fb for t in pages.CAUTIONS)   # 注意書きも一緒に
    assert "<main" not in fb and root.count("<main") == 1                               # main は新UIの本文だけ


def test_fallback_counts_and_names_are_the_catalog_values():
    """件数・商品名は新UIの一覧と同じ catalog の生成時点の値（計算し直さない）。"""
    ctx = P6._ctx(**KW)
    _model, catalog = shell.build_catalog(ctx)
    fb = _fallback(shell.render_root(ctx))
    for k in ("opportunities", "restock", "routes", "lottery"):
        assert re.search(rf'href="\?page={k}">[^<]+</a> {catalog.count(k)}件', fb), k
    for v in catalog.opportunity_set.eligible[:10]:
        assert f"<li>{html_mod.escape(v.product_name)}</li>" in fb


def test_deploy_check_837_fallback_and_mutations():
    page = _page()
    assert _lv(page, "static_fallback") == "ok"
    fb_s = page.find('<div id="nu-fallback"')
    fb_e = page.find("</ul></div></div>", fb_s) + len("</ul></div></div>")
    assert _lv(page[:fb_s] + page[fb_e:], "static_fallback") == "error"                       # 案内を消す
    assert _lv(page.replace("JavaScript を有効にすると", "", 1), "static_fallback") == "error"
    assert _lv(page.replace("d.classList.add('ui-fallback');", "", 1), "static_fallback") == "error"  # 旧UIへ戻す
    assert _lv(page.replace("html.ui-fallback #nu-fallback{display:block}", "", 1), "static_fallback") == "error"
    assert _lv(page.replace("生成時点の値", "最新の値", 1).replace("生成時点の値", "最新の値"),
               "static_fallback") == "error"
    assert _lv(page.replace('<h2>ページ</h2>', '<h2>ページ</h2><p>¥0</p>', 1), "static_fallback") == "error"
    # 白い画面になる CSS の欠け（JS が無いとき案内を出す・他を隠す、失敗のとき他を隠す）
    for css in ("html:not(.ui-new):not(.ui-legacy) #nu-fallback,",
                "html:not(.ui-new):not(.ui-legacy) body>*:not(#nu-fallback),",
                "html.ui-fallback body>*:not(#nu-fallback){display:none!important}"):
        assert _lv(page.replace(css, "", 1), "static_fallback") == "error", css
    assert _lv(page.replace("購入を推奨するものではありません", "", 1), "static_fallback") == "error"   # 案内の注意書き
    assert _lv(page.replace("</ul></div></div>", "</ul></div>", 1), "static_fallback") == "error"   # 範囲が読めない


# ── アーカイブ ────────────────────────────────────────────────────────────────

def test_deploy_check_838_archive_and_mutations(tmp_path, monkeypatch):
    (tmp_path / "archive").mkdir()
    bp = _load("build_public_lp_p10", ROOT / "scripts" / "build_public_lp.py")
    bp._write_archive_index(tmp_path / "archive")
    monkeypatch.setattr(DC, "PUBLIC_DIR", tmp_path)
    page = _page()
    assert _lv(page, "archive_new_ui") == "ok"
    # head のスクリプトがアーカイブで新UIを止める（白い画面になる）
    assert _lv(page.replace("else{d.classList.add('ui-new');",
                            "else if(!/\\/archive\\//.test(location.pathname)){d.classList.add('ui-new');", 1),
               "archive_new_ui") == "error"
    assert _lv(page.replace('id="nu-archive-note"', 'id="x-note"', 1), "archive_new_ui") == "error"
    assert _lv(page.replace("a.setAttribute('href', '../' + h.replace(", "a.setAttribute('href', h.replace(", 1),
               "archive_new_ui") == "error"                                       # 別ファイルのリンクが 404 になる
    assert _lv(page.replace("note.hidden = false;", "", 1), "archive_new_ui") == "error"
    (tmp_path / "archive" / "index.html").unlink()
    assert _lv(page, "archive_new_ui") == "error"                                          # 転送が無い


def test_archive_index_redirects_and_sitemap_excludes_it(tmp_path, monkeypatch):
    bp = _load("build_public_lp_p10b", ROOT / "scripts" / "build_public_lp.py")
    arch = tmp_path / "archive"
    arch.mkdir()
    bp._write_archive_index(arch)
    t = (arch / "index.html").read_text(encoding="utf-8")
    assert '<meta http-equiv="refresh" content="0; url=../">' in t and 'href="../"' in t and "noindex" in t
    # 過去の LP（日付のファイル）だけをサイトマップに入れる（index.html は入れない）
    src = (ROOT / "scripts" / "build_public_lp.py").read_text(encoding="utf-8")
    assert 'ARCHIVE_DIR.glob("2*.html")' in src and 'ARCHIVE_DIR.glob("*.html")' not in src


# ── 旧UIから移したもの（注意書き・外部リンク・計測） ─────────────────────────────

def test_footer_has_cautions_moved_from_legacy():
    root = _root()
    foot = root[root.find('<footer class="nu-footer"'):root.find("</footer>")]
    assert "本ページは価格差の監視結果であり、購入を推奨するものではありません。" in foot
    assert "利益を保証するものではありません" in foot and foot.count("<li>") == len(pages.CAUTIONS)
    assert root.count('<footer class="nu-footer"') == 1                                   # 注意書きは1回だけ


def test_footer_cta_links_only_safe_urls():
    links = [("詳細レポート（note）", "https://note.com/example/n/abc", "note_click"),
             ("LINE速報", "javascript:alert(1)", "line_click"), ("Telegram速報", "http://t.me/x", "telegram_click")]
    foot = pages.render_footer("プレ値速報", links)
    assert 'href="https://note.com/example/n/abc"' in foot and 'data-track="note_click"' in foot
    assert "javascript:" not in foot and "http://t.me" not in foot and "LINE速報" not in foot
    assert "詳細レポート" not in pages.render_footer("プレ値速報", None)


def test_generator_cta_links_follow_settings():
    from src.content.daily_lp_generator import DailyLPGenerator
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    g.settings = {"enable_note_cta": True, "note_url": "", "enable_line_cta": True, "line_url": "#"}
    assert g._nu_cta_links() == []                                                         # URL が無い・「#」は出さない
    g.settings = {"enable_note_cta": True, "note_url": "https://note.com/x", "enable_line_cta": False,
                  "line_url": "https://line.me/x"}
    assert g._nu_cta_links() == [("詳細レポート（note）", "https://note.com/x", "note_click")]


def test_tracking_moved_to_new_ui_and_legacy_does_not_double_send():
    root = _root()
    assert "closest('[data-track]')" in root and "gtag('event', ev" in root and "fbq('trackCustom', ev" in root
    src = (ROOT / "src" / "content" / "daily_lp_generator.py").read_text(encoding="utf-8")
    i = src.find("// ── トラッキング ──")
    assert 'if (document.documentElement.classList.contains("ui-new")) return;' in src[i:i + 400]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_root_keeps_box_sizing_and_footer_list_without_legacy_css(tmp_path):
    """旧UIの CSS が無い状態（段階Bの後と同じ）でも、root は border-box・数字は等幅、フッターの注意書きは黒丸つき。"""
    js = _VIS + ("var R=document.getElementById('new-ui-root'),cs=getComputedStyle(R),"
                 "ul=getComputedStyle(R.querySelector('.nu-footer__cautions'));"
                 "done({bs: cs.boxSizing, ff: cs.fontFeatureSettings, ls: ul.listStyleType, pl: ul.paddingLeft});")
    o = _chrome(tmp_path, "page.html", _doc(_root(), js))
    assert o["bs"] == "border-box" and "tnum" in o["ff"] and o["ls"] == "disc" and o["pl"] != "0px"


def test_reset_css_has_zero_specificity():
    """旧UIの全体のリセットを移す。:where で詳細度 0（新UIの個別の margin・padding を上書きしない）。"""
    css = shell.render_head()
    assert ":where(#new-ui-root) *,:where(#new-ui-root) *::before,:where(#new-ui-root) *::after" in css
    assert not re.search(r"(?<!:where\()#new-ui-root \*\s*\{", css)


# ── ブラウザで確かめる ───────────────────────────────────────────────────────

def _chrome(tmp_path: Path, rel: str, page: str, query: str = "") -> dict:
    f = tmp_path / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(page, encoding="utf-8")
    res = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--window-size=390,900",
                          "--virtual-time-budget=4000", "--dump-dom", f.as_uri() + query],
                         capture_output=True, text=True, timeout=60)
    s = res.stdout.find('<pre id="out">')
    assert s >= 0, res.stderr[-2000:]
    return json.loads(html_mod.unescape(res.stdout[s + len('<pre id="out">'):res.stdout.find("</pre>", s)]))


def _doc(root: str, js: str, head: str | None = None) -> str:
    return ("<!doctype html><html lang='ja'><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            + (shell.render_head() if head is None else head) + "</head><body>" + root
            + "<header class='topbar'>old</header><pre id='out'></pre>"
            "<script>window.addEventListener('load',function(){setTimeout(function(){" + js + "},80);});</script>"
            "</body></html>")


_VIS = ("function vis(el){return !!el && getComputedStyle(el).display!=='none' && !el.hidden;}"
        "function done(o){document.getElementById('out').textContent=JSON.stringify(o);}")


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_without_head_script_shows_fallback_not_legacy(tmp_path):
    """JS が無いときと同じ状態（head のスクリプトがクラスを付けない）: 静的な案内だけが見え、旧UI・新UIは見えない。"""
    css_only = shell.render_head().split("<script>", 1)[0]
    root = _root()
    # ルーター・閲覧時のスクリプトも動かさない（JS が無いのと同じ）
    root = re.sub(r"<script>(?!window).*?</script>", "", root, flags=re.S)
    js = _VIS + ("done({fb: vis(document.getElementById('nu-fallback')), old: vis(document.querySelector('header.topbar')),"
                 "nu: vis(document.getElementById('new-ui-root')), sw: document.documentElement.scrollWidth,"
                 "cw: document.documentElement.clientWidth, text: document.getElementById('nu-fallback').innerText});")
    o = _chrome(tmp_path, "page.html", _doc(root, js, head=css_only))
    assert o["fb"] is True and o["old"] is False and o["nu"] is False
    assert "JavaScript を有効にすると" in o["text"] and o["sw"] <= o["cw"]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_new_ui_hides_fallback(tmp_path):
    js = _VIS + ("done({fb: vis(document.getElementById('nu-fallback')), nu: vis(document.getElementById('new-ui-root')),"
                 "cls: document.documentElement.className});")
    o = _chrome(tmp_path, "page.html", _doc(_root(), js))
    assert o["fb"] is False and o["nu"] is True and "ui-new" in o["cls"].split()


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_archive_shows_new_ui_with_snapshot_note(tmp_path):
    """docs/archive/<日付>.html: 新UIで出し、その日の記録の案内を出す。別ファイルへのリンクは今のサイト（1つ上）へ。
    ?page=… のリンクはこの記録の中で動く。"""
    js = _VIS + ("var R=document.getElementById('new-ui-root'),n=document.getElementById('nu-archive-note');"
                 "var a=n.querySelector('a');"
                 "var beta=[].slice.call(R.querySelectorAll('a')).filter(function(x){return /beta\\//.test(x.getAttribute('href'));})"
                 ".map(function(x){return x.getAttribute('href');});"
                 "var lot=R.querySelector('.nu-bottomnav a[data-nu-nav=\"lottery\"]');"
                 "lot.click();"
                 "done({nu: vis(R), fb: vis(document.getElementById('nu-fallback')), note: vis(n),"
                 "date: n.querySelector('[data-nu-archive-date]').textContent, latest: a.getAttribute('href'),"
                 "beta: beta, lotHref: lot.getAttribute('href'), q: location.search, path: location.pathname,"
                 "attr: R.getAttribute('data-nu-archive')});")
    o = _chrome(tmp_path, "archive/2026-10-07.html", _doc(_root(), js))
    assert o["nu"] is True and o["fb"] is False and o["note"] is True
    assert o["date"] == "2026-10-07" and o["attr"] == "2026-10-07" and o["latest"] == "../"
    assert o["beta"] and all(h == "../beta/" for h in o["beta"])
    assert o["lotHref"] == "?page=lottery" and o["q"] == "?page=lottery" and o["path"].endswith("/archive/2026-10-07.html")


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_root_page_has_no_archive_note(tmp_path):
    js = _VIS + ("var R=document.getElementById('new-ui-root');"
                 "done({note: vis(document.getElementById('nu-archive-note')), attr: R.getAttribute('data-nu-archive'),"
                 "beta: [].slice.call(R.querySelectorAll('a')).filter(function(x){return /beta\\//.test(x.getAttribute('href'));})"
                 ".map(function(x){return x.getAttribute('href');})});")
    o = _chrome(tmp_path, "page.html", _doc(_root(), js))
    assert o["note"] is False and o["attr"] is None and "beta/" in o["beta"]


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_tracking_sends_once_per_click(tmp_path):
    stub = "<script>window.__ev=[];window.gtag=function(){window.__ev.push([].slice.call(arguments));};</script>"
    js = _VIS + ("var R=document.getElementById('new-ui-root');var el=R.querySelector('[data-track]');"
                 "el.addEventListener('click',function(e){e.preventDefault();});el.click();"
                 "done({n: window.__ev.length, ev: window.__ev[0] && window.__ev[0][1]});")
    o = _chrome(tmp_path, "page.html", _doc(_root(), js, head=stub + shell.render_head()))
    assert o["n"] == 1 and o["ev"]

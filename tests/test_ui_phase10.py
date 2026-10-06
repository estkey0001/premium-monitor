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
        # 名前・想定純利益・買う先・売る先（新UIの利益商品と同じ値。計算し直さない）
        assert (f"<li><b>{html_mod.escape(v.product_name)}</b>：想定純利益 +¥{int(v.net_profit):,}"
                f"（{html_mod.escape(v.buy_source)}で買い、{html_mod.escape(v.sell_source)}に売る場合）</li>") in fb
    assert catalog.opportunity_set.eligible                                        # 架空の確定案件がある前提


def test_fallback_lists_lotteries_and_restock_at_generation():
    """抽選・予約（生成時点で受付中・予定・発売待ち）と在庫再開（生成時点で購入可能）も、JS 無しで読める。
    状態の文言は閲覧時の判定（runtime）と同じ関数で生成時刻に計算したもの。リンクは https の公式だけ。"""
    from src.content.ui import runtime as rt
    ctx = P6._ctx(**KW)
    model, catalog = shell.build_catalog(ctx)
    fb = _fallback(shell.render_root(ctx))
    shown = [lv for lv in catalog.lottery_views
             if lv.vm and rt.derive_runtime_state(lv.vm, model.now).get("bucket") != rt.BUCKET_HIDDEN
             and rt.derive_runtime_state(lv.vm, model.now).get("status") not in ("ENDED", "CLOSED", "UNKNOWN")]
    assert shown and "<h2>抽選・予約（生成時点の状態）</h2>" in fb
    for lv in shown[:10]:
        assert html_mod.escape(lv.product_name) in fb
    rs = [r for r in catalog.restock_views if r.available(model.now)]
    assert ("<h2>在庫再開（生成時点で購入可能）</h2>" in fb) == bool(rs)
    assert not re.search(r'href="(?!https://|\./|\?)', fb)                          # 外部は https・サイト内は相対だけ
    assert "締切を過ぎた・在庫が無くなったなどの変化は反映されません" in fb
    if len(shown) > 10:                                                            # 10件で切ったら、残りの件数を書く
        assert f"ほか {len(shown) - 10}件（JavaScript を有効にすると全件を見られます）" in fb


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
    for css in ("html:not(.ui-new) #nu-fallback,",
                "html:not(.ui-new) body>*:not(#nu-fallback),",
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
    assert _lv(page.replace("d.classList.add('ui-new');",
                            "if(!/\\/archive\\//.test(location.pathname)){d.classList.add('ui-new');}", 1),
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
    """クリックの計測は新UIのルーターだけ（旧UIの計測のスクリプトは旧UIと一緒に削除した。二重に送らない）。"""
    root = _root()
    assert "closest('[data-track]')" in root and "gtag('event', ev" in root and "fbq('trackCustom', ev" in root
    assert root.count("closest('[data-track]')") == 1
    src = (ROOT / "src" / "content" / "daily_lp_generator.py").read_text(encoding="utf-8")
    assert "// ── トラッキング ──" not in src and "[data-track]" not in src


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


# ── 段階B: 旧UIの削除 ─────────────────────────────────────────────────────────

def _lp(monkeypatch) -> str:
    """生成器で LP 全体（公開する HTML）を作る（DB を使わない）。"""
    T = _load("test_new_ui_for_p10", ROOT / "tests" / "test_new_ui.py")
    from src.content.daily_lp_generator import DailyLPGenerator
    monkeypatch.setattr(DailyLPGenerator, "_load_tcg_report", staticmethod(lambda: {}))
    html, _parts = T._render_lp(monkeypatch, new_ui=True)
    return html


def test_generated_lp_has_no_legacy_ui(monkeypatch):
    """生成した LP に旧UIの DOM・CSS・JS が無い（#800 の目印が1つも無い）。#800 は ok。"""
    html = _lp(monkeypatch)
    assert not [m for m in DC.LEGACY_UI_MARKERS if m in html]
    assert _lv(html, "no_legacy_ui") == "ok"
    assert len(html) < 2_000_000 and "<style>" in html and html.count("<style>") == 1     # CSS は新UIの1つだけ


def test_deploy_check_800_detects_reintroduced_legacy():
    page = _page()
    for marker in ('<div id="tab-beginner"></div>', '<nav id="main-tab-nav"></nav>', '<div class="tab-panel"></div>',
                   "<script>function activateCategory(c){}</script>", "<style>/* SOUBA デザインシステム */</style>",
                   '<div class="nu-legacy-note">旧表示</div>'):
        assert _lv(page.replace("<body>", "<body>" + marker, 1), "no_legacy_ui") == "error", marker


def test_no_legacy_links_in_public_navigation():
    """メニュー・フッター・案内・運営者向けのページ・利益商品に、旧表示への入口が無い。"""
    root = _root()
    assert not re.search(r'href="[^"]*ui=legacy', root) and "旧表示で詳しく見る" not in root
    text = re.sub(r"<[^>]+>", " ", root.split('data-nu-page="admin"')[0])
    assert "旧表示" not in text.replace("旧表示は終了しました", "")


def test_mypage_storage_key_unchanged():
    """マイページの保存（このブラウザの localStorage）のキー・版は変えない（旧UIの削除で消えない）。"""
    root = _root()
    assert "var KEY = 'premium-monitor.mypage'" in root and "window.NuStore = NuStore;" in root


def test_deploy_check_810_vm_fidelity_and_mutations():
    page = _page()
    assert _lv(page, "new_ui_vm_fidelity") == "ok"
    bad = re.sub(r'data-nu-vmcheck="tcg:0;', 'data-nu-vmcheck="tcg:2;', page, count=1)
    assert _lv(bad, "new_ui_vm_fidelity") == "error"
    assert _lv(re.sub(r' data-nu-vmcheck="[^"]*"', "", page, count=1), "new_ui_vm_fidelity") == "error"


def test_deploy_check_839_admin_keeps_legacy_operator_info():
    page = _page()
    assert _lv(page, "admin_has_legacy_operator_info") == "ok"
    for need in ("システムの健康度", "取得の警告（旧表示の警告バーと同じ分類）", "eBay を設定したときに",
                 "せどりルートが成立しない理由"):
        assert _lv(page.replace(need, "（削除）"), "admin_has_legacy_operator_info") == "error", need


def test_deploy_check_840_and_mutation(monkeypatch):
    ok, = DC._check_legacy_intents()
    assert ok["level"] == "ok"
    from src.content.ui import opportunity as opp
    monkeypatch.setattr(opp, "deal_reasons", lambda d, now: ())          # 古い価格・0円・未照合を通してしまう
    bad, = DC._check_legacy_intents()
    assert bad["level"] == "error" and "15日前" in bad["message"]


def test_admin_ai_tasks_of_dropped_candidates_are_hidden():
    """今の確定ルートと照合できない AI の候補の「今日やること」（商品名を含む行）は出さない（旧UIの AI Dashboard と同じ）。"""
    from src.content.ui import admin
    ai = {"todays_opportunities": [{"product": "商品A", "product_id": "pa", "kind": "main", "route_id": "gone"}],
          "today_tasks": ["✅ 商品A を仕入れる（≤¥100,000）", "本日の対象なし（データ取得状況を確認）"]}
    a = admin.build_ai(ai, {"main": set(), "reference": set(), "main_identity": set(), "reference_identity": set()}, None)
    assert a["ops"] == [] and a["tasks"] == ["本日の対象なし（データ取得状況を確認）"]
    # 外した商品の名前を含む、残した別の商品（GR IV と GR IV HDF）の行は隠さない
    rid = "r-hdf"
    ai2 = {"todays_opportunities": [{"product": "RICOH GR IV", "product_id": "p_gr4", "kind": "main", "route_id": "gone"},
                                    {"product": "RICOH GR IV HDF", "product_id": "p_hdf", "kind": "main", "route_id": rid}],
           "today_tasks": ["✅ RICOH GR IV を仕入れる", "✅ RICOH GR IV HDF を仕入れる"]}
    keys = {"main": {rid}, "reference": set(), "main_identity": set(), "reference_identity": set()}
    from src.content.ui import opportunity as opp
    import unittest.mock as _m
    with _m.patch.object(opp, "record_route_ok", lambda rec, k: rec.get("route_id") == rid):
        a2 = admin.build_ai(ai2, keys, None)
    assert [o["product_id"] for o in a2["ops"]] == ["p_hdf"] and a2["tasks"] == ["✅ RICOH GR IV HDF を仕入れる"]


def test_generator_has_no_legacy_renderers():
    """旧UIの描画関数・旧UIだけのための取得が生成器に残っていない（dead code）。"""
    from src.content.daily_lp_generator import DailyLPGenerator
    for name in ("_section_hero", "_section_tabs", "_tab_beginner", "_tab_ranking", "_tab_sedori", "_tab_advanced",
                 "_tab_health", "_deal_card", "_deal_card_monitoring", "_collector_warn_bar_html", "_section_lottery",
                 "_section_tcg", "_ai_dashboard_section", "_capital_dashboard_html", "_execution_html",
                 "_notifications_html", "_coverage_html", "_buyback_comparison", "_nu_old_counts"):
        assert not hasattr(DailyLPGenerator, name), name
    src = (ROOT / "src" / "content" / "daily_lp_generator.py").read_text(encoding="utf-8")
    for fetch in ("list_watch_candidates", "list_sedori_routes", "list_price_history_by_product"):
        assert fetch not in src, fetch
    assert not (ROOT / "src" / "content" / "ui" / "parity.py").exists()


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_admin_sources_no_overflow_at_320(tmp_path):
    """運営者向けの「取得元」は、長い状態の文（アクセス拒否（人の確認が必要。回避はしない）など）や英字の理由コードが
    あっても、320px で横にはみ出さない（バッジは折り返す・箱の列は minmax(0,1fr)）。"""
    P9 = _load("ui_phase9_for_p10", ROOT / "tests" / "test_ui_phase9.py")
    root = shell.render_root(P9._ctx())
    # ヘッドレスの Chrome は幅 500px 未満にできないので、root の幅を 320px にして、中身がはみ出さないかを見る
    js = _VIS + ("history.replaceState(null,'','?page=admin&section=sources');"
                 "window.dispatchEvent(new PopStateEvent('popstate'));"
                 "var R=document.getElementById('new-ui-root');R.style.width='320px';R.style.overflowX='auto';"
                 "setTimeout(function(){done({sw: R.scrollWidth, cw: R.clientWidth,"
                 "sec: vis(document.querySelector('[data-nu-ad-panel=\"sources\"]'))});}, 150);")
    page = _doc(root, js)
    f = tmp_path / "page.html"
    f.write_text(page, encoding="utf-8")
    res = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox", "--window-size=320,900",
                          "--virtual-time-budget=4000", "--dump-dom", f.as_uri()],
                         capture_output=True, text=True, timeout=60)
    s = res.stdout.find('<pre id="out">')
    o = json.loads(html_mod.unescape(res.stdout[s + len('<pre id="out">'):res.stdout.find("</pre>", s)]))
    assert o["sec"] is True and o["cw"] <= 320 and o["sw"] <= o["cw"], o


# ── 旧UIの「販売・入荷・プレミア」の発売予定の後継（レビュー M1） ─────────────────────────

def test_release_date_formats_pokemon_and_onepiece():
    from src.content.ui import runtime as rt
    assert rt.release_date_iso("2026年10月16日（金）") == "2026-10-16"          # ポケモン
    assert rt.release_date_iso("2026.11.21") == "2026-11-21"                  # ONE PIECE
    assert rt.release_date_iso("発売日：2026.10.9（予定）") == "2026-10-09"
    for bad in ("", "未定", "2026.13.40", "12026.1.2", None):
        assert rt.release_date_iso(bad) == "", bad


def _release_ev(name, rd, url="https://www.onepiece-cardgame.com/products/boosters/op18.php"):
    return {"tcg": "ONE_PIECE", "product_name": name, "event_type": "GENERAL_SALE", "status": "COMING_SOON",
            "release_date": rd, "source_url": url, "store": "ONEPIECE_CARD_OFFICIAL"}


def test_onepiece_release_schedule_is_shown_in_lottery_page():
    """公式の発売日が「2026.11.21」の形でも、抽選・予約のページの発売待ちに出る（旧UIでは出ていた）。"""
    from datetime import timedelta
    d = NOW + timedelta(days=30)
    ev = _release_ev("ブースターパック 神の支配【OP-18】", f"{d.year}.{d.month}.{d.day}")
    root = shell.render_root(P6._ctx(**dict(KW, tcg_report={"lotteries": [], "events": [ev]})))
    lot = root[root.index('data-nu-page="lottery"'):root.index('data-nu-page="restock"')]
    assert html_mod.escape("ブースターパック 神の支配【OP-18】") in lot and "発売予定" in lot


def test_deploy_check_841_release_schedule_and_mutation(tmp_path, monkeypatch):
    from datetime import datetime as _dt, timedelta
    from src.tcg.models import JST as _JST
    d = _dt.now(_JST) + timedelta(days=30)
    ev = _release_ev("ブースターパック 神の支配【OP-18】", f"{d.year}.{d.month}.{d.day}")
    report = {"lotteries": [], "events": [ev], "lottery_sources": [], "lottery_coverage": {"configured_sources": 1},
              "source_health": []}
    root = shell.render_root(P6._ctx(**dict(KW, tcg_report=report)))
    (tmp_path / "index.html").write_text("<html><body>" + root + "</body></html>", encoding="utf-8")
    monkeypatch.setattr(DC, "PUBLIC_DIR", tmp_path)
    lv = {x["check"]: x["level"] for x in DC._check_tcg_lottery(report)}
    assert lv["tcg_release_schedule_shown"] == "ok"
    # 発売予定が出ていない（日付が読めずに消えた）なら error
    (tmp_path / "index.html").write_text("<html><body>" + root.replace("神の支配", "x") + "</body></html>",
                                         encoding="utf-8")
    lv = {x["check"]: x["level"] for x in DC._check_tcg_lottery(report)}
    assert lv["tcg_release_schedule_shown"] == "error"


@pytest.mark.skipif(CHROME is None, reason="Chrome が無い")
def test_dom_legacy_ended_note_closes_after_navigation(tmp_path):
    """「旧表示は終了しました」は最初に開いたページだけ。サイトの中で移ったら閉じる。"""
    js = _VIS + ("var R=document.getElementById('new-ui-root'),n=document.getElementById('nu-legacy-ended');"
                 "var first=vis(n);R.querySelector('.nu-bottomnav a[data-nu-nav=\"lottery\"]').click();"
                 "done({first: first, after: vis(n), q: location.search});")
    o = _chrome(tmp_path, "page.html", _doc(_root(), js), "?ui=legacy")
    assert o["first"] is True and o["after"] is False and o["q"] == "?page=lottery"


# ── 利益ルートがある日に、旧UIの文字列を要求する検査で公開が止まらない（レビュー H1） ─────────────────

_REMOVED_LEGACY_KEYS = ("lp_reference_summary", "lp_reference_max_profit", "lp_reference_stale_days",
                        "lp_reference_card_when_zero_main", "lp_main_route_card", "lp_pro_summary",
                        "lp_flea_sold_section", "lp_manual_route_notice", "ai_alert", "sedori_buy_price",
                        "ranking_beginner_consistency", "iphone17pro_in_beginner")


def _route_day(tmp_path, monkeypatch, routes: dict, html_root: str | None = None, now=None) -> dict:
    """その日の利益ルート（routes）で作った公開ページに deploy-check（check()）を当てた結果 {check: result}。"""
    proj = tmp_path / "proj"
    if not proj.exists():
        (proj / "docs").mkdir(parents=True)
        (proj / "exports" / "profit_routes").mkdir(parents=True)
        for child in (ROOT / "exports").iterdir():
            if child.name != "profit_routes":
                (proj / "exports" / child.name).symlink_to(child)
        for n in ("config", "data", "src", "scripts", ".github", "audit_health"):
            if (ROOT / n).exists():
                (proj / n).symlink_to(ROOT / n)
    root = html_root if html_root is not None else shell.render_root(
        P6._ctx(**dict(KW, profit_routes=routes, **({"now": now} if now else {}))))
    (proj / "docs" / "index.html").write_text("<html><head>" + shell.render_head() + "</head><body>" + root
                                              + "</body></html>", encoding="utf-8")
    (proj / "exports" / "profit_routes" / "latest.json").write_text(json.dumps(routes, ensure_ascii=False), "utf-8")
    monkeypatch.setattr(DC, "PROJECT_ROOT", proj)
    monkeypatch.setattr(DC, "PUBLIC_DIR", proj / "docs")
    monkeypatch.setattr(DC, "__file__", str(proj / "scripts" / "deploy_check.py"))   # 一部の検査は __file__ から root を決める
    return {r["check"]: r for r in DC.check()}


def _routes_fixture():
    import importlib.util as _ilu
    from datetime import datetime as _dt, timedelta
    from src.tcg.models import JST as _JST
    spec = _ilu.spec_from_file_location("rf_p10", ROOT / "tests" / "route_fixtures.py")
    RF = _ilu.module_from_spec(spec)
    spec.loader.exec_module(RF)
    now = _dt.now(_JST)
    main = dict(RF.safe_route(now, "prod_tcam"), product_name="テストカメラ 本体", buy_shipping=0,
                reproducibility_score=80)                                # 生成側（generate_profit_routes）が付ける
    ref = dict(RF.safe_route(now, "prod_tgame", sell_type="SOLD", sell_observed_at=(now - timedelta(days=20)).isoformat(),
                             reference_route=True, rejection_reason="overseas_sold_stale(20d)"),
               product_name="テストゲーム機", sell_price_type="overseas_sold_price")
    return now, main, ref


@pytest.mark.parametrize("shape", ["main_and_reference", "reference_only"])
def test_deploy_check_on_route_days_adds_no_errors(tmp_path, monkeypatch, shape):
    """利益ルートがある日（確定1件＋参考1件／確定0件＋参考1件）でも、ルートが無い日と比べて deploy-check の error が
    増えない（旧UIの見出し・クラスを要求する検査で公開が止まらない）。#600（確定ルートが新UIに出ている）・#807 は ok。"""
    now, main, ref = _routes_fixture()
    stamp = now.strftime("%Y-%m-%d %H:%M JST")
    base = _route_day(tmp_path, monkeypatch, {"main_routes": [], "reference_routes": [], "generated_at": stamp})
    routes = {"main_routes": [main] if shape == "main_and_reference" else [], "reference_routes": [ref],
              "generated_at": stamp, "zero_route_diagnostics": {}}
    lv = _route_day(tmp_path, monkeypatch, routes, now=now)
    errors = {k for k, r in lv.items() if r["level"] == "error"}
    base_errors = {k for k, r in base.items() if r["level"] == "error"}
    assert errors <= base_errors, {k: lv[k]["message"][:120] for k in errors - base_errors}
    assert lv["lp_main_routes_shown"]["level"] == "ok" and lv["new_ui_no_zero_price"]["level"] == "ok"
    assert not [k for k in _REMOVED_LEGACY_KEYS + ("lp_zero_stale_reason",) if k in lv]
    if shape == "main_and_reference":
        assert "確定ルート（1件）" in lv["lp_main_routes_shown"]["message"]
        # 否定対照: 確定ルートが新UIのせどりルートに出ていなければ #600 は error
        root = shell.render_root(P6._ctx(**dict(KW, profit_routes=routes, now=now))).replace("テストカメラ 本体", "x")
        assert _route_day(tmp_path, monkeypatch, routes, html_root=root)["lp_main_routes_shown"]["level"] == "error"


def test_deploy_check_does_not_require_strings_the_new_ui_cannot_make():
    """deploy-check が公開ページに「'文字列' in html」を要求するなら、その文字列を新UIのコードが作れること
    （旧UIの見出し・クラスを要求する検査が残ると、条件がそろった日に公開が止まる）。無いことを確かめる検査だけは許す。"""
    import ast
    import glob
    src = (ROOT / "scripts" / "deploy_check.py").read_text(encoding="utf-8")
    code = "".join(open(f, encoding="utf-8").read() for f in glob.glob(str(ROOT / "src/content/ui/*.py"))
                   + glob.glob(str(ROOT / "src/content/ui/*.js"))
                   + [str(ROOT / "src/content/daily_lp_generator.py"), str(ROOT / "src/content/safety.py")])
    code_u = html_mod.unescape(code)
    page = re.compile(r"^(html|_lp_html\w*|_html\w*|root|_body\w*|_lot_text|_fb)$")
    # 無いことを確かめる検査（あれば error/warning）・データから来る文字列・実行時に組み立てる CSS
    allowed = {"line_cta_off", "low_confidence_not_in_lp", "mobile_scroll_nav",
               "new_ui_default", "no_live_label_on_manual", "no_new_product_candidate_label",
               "stale_banner_date_mismatch", "suspicious_price_not_in_lp", "telegram_cta_off",
               "unverified_url_not_linked"}
    found = {}
    tree = ast.parse(src)
    for fn in [n for n in tree.body if isinstance(n, ast.FunctionDef)]:
        tainted = {}
        for st in fn.body:
            miss = []
            for d in ast.walk(st):
                if isinstance(d, ast.Compare) and isinstance(d.left, ast.Constant) and isinstance(d.left.value, str):
                    for op, comp in zip(d.ops, d.comparators):
                        if (isinstance(op, ast.In) and isinstance(comp, ast.Name) and page.match(comp.id)
                                and len(d.left.value) >= 3 and d.left.value not in code and d.left.value not in code_u):
                            miss.append(d.left.value)
                if isinstance(d, ast.Name) and isinstance(d.ctx, ast.Load) and d.id in tainted:
                    miss.extend(tainted[d.id])
            if miss:
                for d in ast.walk(st):
                    if isinstance(d, ast.Assign):
                        for tg in d.targets:
                            for n in ast.walk(tg):
                                if isinstance(n, ast.Name):
                                    tainted[n.id] = miss
            for d in ast.walk(st):
                if isinstance(d, ast.Dict):
                    for k, v in zip(d.keys, d.values):
                        if (isinstance(k, ast.Constant) and k.value == "check" and isinstance(v, ast.Constant)
                                and miss and v.value not in allowed):
                            found.setdefault(v.value, set()).update(miss[:2])
    assert not found, found

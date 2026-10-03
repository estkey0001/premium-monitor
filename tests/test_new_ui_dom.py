"""新UIの DOM 側（lottery_runtime.js の apply / setCta / reorder / setTile とクリック時のガード）を
ヘッドレスの Chrome で実際に動かすテスト。Chrome が無い環境では skip する。

時計は Date.now を差し替えて進める（本番のページには差し替えのコードは入らない）。
"""

from __future__ import annotations

import html as html_mod
import json
import os
import shutil
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.content.ui import shell
from src.tcg.lottery.schema import compute_lottery_status
from src.tcg.models import JST

NOW = datetime(2026, 10, 2, 10, 0, tzinfo=JST)
PCO = "https://www.pokemoncenter-online.com"


def _chrome() -> str | None:
    for c in (os.environ.get("CHROME_BIN"), "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              shutil.which("google-chrome"), shutil.which("chromium"), shutil.which("chromium-browser")):
        if c and Path(c).exists():
            return c
    return None


CHROME = _chrome()
pytestmark = pytest.mark.skipif(CHROME is None, reason="Chrome が無い")


def _ev(i, **kw):
    e = {"tcg": "POKEMON", "product_name": f"抽選{i}", "retailer_name": "ポケモンセンターオンライン",
         "lottery_id": f"t{i}", "source_url": f"{PCO}/news/{i}", "entry_url": f"{PCO}/lottery/{i}",
         "verified": True, "confidence": "high", "retail_price": 5400}
    e.update(kw)
    e["status"] = compute_lottery_status(e, NOW)
    return e


def _page(report: dict, scenario_js: str, *, break_json: bool = False) -> str:
    ctx = shell.ShellContext(tcg_report=report, opportunities={}, profit_routes={},
                             legacy_lotteries=[], now=NOW)
    root = shell.render_root(ctx)
    if break_json:
        root = root.replace('<script type="application/json" id="nu-lot-data">',
                            '<script type="application/json" id="nu-lot-data">{broken', 1)
    fake = ("<script>window.__now=%d;Date.now=function(){return window.__now;};</script>"
            % int(NOW.timestamp() * 1000))
    return ("<!doctype html><html><head><meta charset='utf-8'>" + fake + shell.render_head()
            + "</head><body>" + root + "<header class='topbar'>old</header>"
            + "<pre id='out'></pre><script>" + scenario_js + "</script></body></html>")


def _run(tmp_path, page: str) -> dict:
    f = tmp_path / "page.html"
    f.write_text(page, encoding="utf-8")
    res = subprocess.run([CHROME, "--headless=new", "--disable-gpu", "--no-sandbox",
                          "--virtual-time-budget=3000", "--dump-dom", f.as_uri() + "?ui=new"],
                         capture_output=True, text=True, timeout=60)
    start = res.stdout.find('<pre id="out">')
    assert start >= 0, res.stderr[-2000:]
    raw = res.stdout[start + len('<pre id="out">'):res.stdout.find("</pre>", start)]
    return json.loads(html_mod.unescape(raw))


_SNAP = """
function snap(){
  var r=document.getElementById('new-ui-root');
  var list=r.querySelector('[data-nu-list="lottery"]');
  return {count:+r.querySelector('.nu-purposes [data-nu-count="lottery"]').textContent.replace('件',''),
    shown:[].slice.call(list.querySelectorAll(':scope > li')).filter(function(li){return !li.hidden;})
      .map(function(li){var a=li.querySelector('article'), c=a.querySelector('a[data-nu-cta]');
        return [a.getAttribute('data-nu-lot'), a.getAttribute('data-nu-status'), c?c.getAttribute('data-nu-cta'):null,
                a.querySelector('.nu-badge').textContent.trim(), a.querySelector('.nu-cd').textContent];}),
    emptyHidden:r.querySelector('[data-nu-empty-for="lottery"]').hidden};
}
// 時計を進めて、ページの更新（runtime の判定 → 件数・一覧の数え直し）を走らせる
function at(ms){ window.__now = %d + ms; window.dispatchEvent(new Event('pageshow')); }
""" % int(NOW.timestamp() * 1000)


def test_dom_expiry_and_reorder(tmp_path):
    report = {"lotteries": [
        _ev(1, application_start=(NOW - timedelta(days=1)).isoformat(),
            application_end=(NOW + timedelta(minutes=30)).isoformat()),
        _ev(2, application_start=(NOW + timedelta(minutes=10)).isoformat(),
            application_end=(NOW + timedelta(days=3)).isoformat()),
    ]}
    js = _SNAP + """
    var out = {};
    out.t0 = snap();
    at(10*60000); out.t10 = snap();
    at(30*60000); out.t30 = snap();
    at(5*86400000); out.later = snap();
    document.getElementById('out').textContent = JSON.stringify(out);
    """
    o = _run(tmp_path, _page(report, js))
    assert [x[:3] for x in o["t0"]["shown"]] == [["t1", "ENDING_SOON", "apply"], ["t2", "UPCOMING", "info"]]
    assert o["t0"]["count"] == 2
    assert o["t0"]["shown"][0][4] == "締切まで あと30分"
    # t2 が受付開始（UPCOMING → OPEN）
    assert [x[:3] for x in o["t10"]["shown"]] == [["t1", "ENDING_SOON", "apply"], ["t2", "OPEN", "apply"]]
    # t1 が締切（CTA 消失・一覧から外れる・件数が減る）
    assert [x[:3] for x in o["t30"]["shown"]] == [["t2", "OPEN", "apply"]]
    assert o["t30"]["count"] == 1
    # どちらも終わると空状態
    assert o["later"]["shown"] == [] and o["later"]["count"] == 0 and o["later"]["emptyHidden"] is False


def test_dom_click_guard(tmp_path):
    report = {"lotteries": [_ev(1, application_start=(NOW - timedelta(days=1)).isoformat(),
                                application_end=(NOW + timedelta(minutes=5)).isoformat())]}
    js = _SNAP + """
    var a = document.querySelector('[data-nu-lot="t1"] a[data-nu-cta="apply"]');
    var res = {};
    function tryClick(type){ var ev = new MouseEvent(type, {bubbles:true, cancelable:true, button: type==='auxclick'?1:0});
      var p = null; a.addEventListener(type, function(e){ p = e.defaultPrevented; e.preventDefault(); }, {once:true});
      a.dispatchEvent(ev); return p; }
    res.before = tryClick('click');
    window.__now += 6*60000;
    res.after = tryClick('click');
    res.kind = a.getAttribute('data-nu-cta');
    document.getElementById('out').textContent = JSON.stringify(res);
    """
    o = _run(tmp_path, _page(report, js))
    assert o == {"before": False, "after": True, "kind": "info"}


def test_dom_broken_json_keeps_generated_view(tmp_path):
    report = {"lotteries": [_ev(1, application_start=(NOW - timedelta(days=1)).isoformat(),
                                application_end=(NOW + timedelta(days=3)).isoformat())]}
    js = _SNAP + """
    document.getElementById('out').textContent = JSON.stringify({snap: snap(),
      rootVisible: !document.getElementById('new-ui-root').hidden});
    """
    o = _run(tmp_path, _page(report, js, break_json=True))
    # 判定し直せなくても、生成時点の表示とナビは残る（ページ全体は壊れない）
    assert o["rootVisible"] is True
    assert [x[:3] for x in o["snap"]["shown"]] == [["t1", "OPEN", "apply"]]

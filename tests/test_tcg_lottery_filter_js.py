# -*- coding: utf-8 -*-
"""抽選ページ（docs/tcg-lottery.html）の絞り込みの JS を node で実際に動かす（テスト用の小さな DOM: tests/_mini_dom.js）。

受付中 2 件（A1 はオンライン、A2 は方式不明）と、締切だけ分かる 1 件（D1。オンライン）が混ざるページで:
- 方式のタイル・商品の選択・タブ・状態の絞り込みの後の件数（#cnt）は、締切間近・受付中の段だけを「受付中 N件」と数え、
  表示中のほかの段は「ほか N件」と分けて書く（締切だけの行を受付中に数えない）
- タイルはもう一度押すと解除される
- 締切を過ぎると、見出しの「全N件」・方式のタイル・商品の件数・#cnt が表示時に減り、期限切れの行は一覧から外れる
"""
from __future__ import annotations

import json
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from src.content import tcg_hub_page as page
from tests import test_tcg_hub as t

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node が無い環境")

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "html", "attrs": [], "children": []}
        self.stack = [self.root]
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag == "html":
            self.root["attrs"] = [[k, v if v is not None else ""] for k, v in attrs]
            return
        node = {"tag": tag, "attrs": [[k, v if v is not None else ""] for k, v in attrs], "children": []}
        if tag in ("script", "style"):
            self.skip += 1
        self.stack[-1]["children"].append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip = max(0, self.skip - 1)
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not self.skip and data:
            self.stack[-1]["children"].append(data)


def _tree(html: str) -> dict:
    p = _Tree()
    p.feed(html)
    return p.root


STEPS = r"""
const q = (s) => g.document.querySelector(s), qa = (s) => g.document.querySelectorAll(s);
const shown = () => qa('.ev').filter((e) => !e.hidden && !e.classList.contains('rb-expired')
  && !(e.closest('[data-lt-group]') || {}).hidden && !e.closest('details:not([open])')).map((e) => e.id);
const tick = (ms) => { g.now = ms; (g.window.listeners.pageshow || []).forEach((f) => f()); };
const snap = () => ({ cnt: q('#cnt').textContent, rows: shown(), bar: q('.lt-bar').textContent,
  on: q('[data-ch-count=online]').textContent, st: q('[data-ch-count=store]').textContent,
  pk: (q('[data-pk] small') || { textContent: '' }).textContent, none: !q('#none').hidden });
const out = {};
out.init = snap();
q('[data-ch-btn=online]').click(); out.online = snap(); out.pressed = q('[data-ch-btn=online]').getAttribute('aria-pressed');
q('[data-ch-btn=online]').click(); out.off = snap(); out.pressedOff = q('[data-ch-btn=online]').getAttribute('aria-pressed');
q('[data-ch-btn=store]').click(); out.store = snap(); q('[data-ch-btn=store]').click();
q('[data-pk]').click(); out.pick = snap(); q('[data-pk]').click();
const f = q('#flt'); f.elements.state.value = 'open'; f.dispatchEvent(new g.Event('change')); out.stateOpen = snap();
f.elements.state.value = ''; f.dispatchEvent(new g.Event('change'));
q('[data-tab=open]').click(); out.tabOpen = snap(); q('[data-tab=all]').click();
tick(Date.parse('2026-11-26T01:00:00+09:00'));            // A1（11/25 締切）の締切後
out.afterA1 = snap();
q('[data-ch-btn=online]').click(); out.afterA1online = snap();
return out;
"""


def _run(html: str, now_iso: str) -> dict:
    scripts = page.JS + page.JS_RB + page.JS_LEFT
    src = ("const {run} = require(" + json.dumps(str(ROOT / "tests" / "_mini_dom.js")) + ");"
           "const data = JSON.parse(require('fs').readFileSync(0, 'utf8'));"
           "const res = run(data.tree, data.scripts, Date.parse(data.now), (g) => {" + STEPS + "});"
           "process.stdout.write(JSON.stringify(res));")
    p = subprocess.run(["node", "-e", src], input=json.dumps({"tree": _tree(html), "scripts": scripts, "now": now_iso}),
                       capture_output=True, text=True, timeout=60)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


def _page():
    evs = [t._ev(lottery_id="A1", application_end_date="2026-11-25", application_methods=["web_form"]),
           t._ev(lottery_id="A2", retailer="GEO", retailer_name="ゲオ", application_end_date="2026-11-26"),
           t._ev(lottery_id="D1", retailer="HOBBY_STATION", retailer_name="ホビーステーション", application_start_date=None,
                 application_end_date="2026-11-27")]
    h = t._hub(evs)
    ch = {v["lottery_id"]: page._ch_key(v["channel"]) for v in h["events"]}
    assert ch["A1"] == "online" and ch["D1"] == "online" and ch["A2"] != "online"       # この前提で件数を確かめる
    return page.render_lottery(h)


def test_filters_count_only_open_rows_and_toggle_and_drop_expired():
    r = _run(_page(), "2026-11-20T12:00:00+09:00")
    i = r["init"]
    assert i["cnt"] == "" and i["bar"].startswith("全2件") and i["on"] == "1" and i["pk"] == "受付中 2件"
    assert set(i["rows"]) == {"L-A1", "L-A2", "L-D1"}
    # 方式のタイル: オンラインは受付中 1 件（A1）と、別の段の締切だけの行 1 件（D1）
    assert r["online"]["cnt"] == "受付中 1件・ほか 1件" and set(r["online"]["rows"]) == {"L-A1", "L-D1"} and r["pressed"] == "true"
    # もう一度押すと解除
    assert r["pressedOff"] == "false" and r["off"]["cnt"] == "" and set(r["off"]["rows"]) == {"L-A1", "L-A2", "L-D1"}
    # 店頭は 0 件 → 「該当なし」
    assert r["store"]["cnt"] == "受付中 0件" and r["store"]["rows"] == [] and r["store"]["none"] is True
    # 商品の選択: 商品の件数（受付中 2件）と、絞り込み後の受付中の件数が一致する
    assert r["pick"]["cnt"].startswith("受付中 2件") and {"L-A1", "L-A2"} <= set(r["pick"]["rows"])
    # 状態「受付中」・タブ「受付中」: 締切だけの行は入らない
    assert r["stateOpen"]["cnt"] == "受付中 2件" and set(r["stateOpen"]["rows"]) == {"L-A1", "L-A2"}
    assert r["tabOpen"]["cnt"].startswith("受付中 2件") and "L-D1" not in r["tabOpen"]["rows"]
    # 締切後: 見出し・タイル・商品の件数が減り、期限切れの行（A1）は一覧から外れる
    a = r["afterA1"]
    assert a["bar"].startswith("全1件") and a["on"] == "0" and a["pk"] == "受付中 1件" and "L-A1" not in a["rows"]
    assert r["afterA1online"]["cnt"] == "受付中 0件・ほか 1件" and r["afterA1online"]["rows"] == ["L-D1"]


def test_mini_dom_runs_the_real_page_scripts_without_errors():
    """生成物と同じ組み合わせ（JS + JS_RB + JS_LEFT）を、例外なく動かせる（スクリプトの中の try/catch で隠れた失敗を見逃さないため、
    件数の span が実際に書き換わることも確かめる）。"""
    r = _run(_page(), "2026-11-26T01:00:00+09:00")                   # 生成後に A1 の締切を過ぎた状態で開く
    assert r["init"]["bar"].startswith("全1件") and r["init"]["on"] == "0"

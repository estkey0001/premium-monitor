# -*- coding: utf-8 -*-
"""買取価格の鮮度は、生成時だけでなくページを見る時点でも成立する（8 時間を超えたら FRESH・実行可能・利益・ROI・HOME の利益根拠から外す）。

- 判定規則は src/tcg/runtime_freshness.py の 1 つ。Python と JavaScript が同じ入力で同じ結果になることを node で確かめる（TZ を変えても）。
- 生成時に FRESH だった HTML を fixture にして、表示時刻だけを進める。
"""
from __future__ import annotations

import json
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

from src.tcg import buyback as bb
from src.tcg import runtime_freshness as rf

ROOT = Path(__file__).resolve().parent.parent
JST = bb.JST
NOW = datetime(2026, 11, 22, 12, 0, tzinfo=JST)
MAXH, FUT = 8.0, 5.0
HAS_NODE = shutil.which("node") is not None
needs_node = pytest.mark.skipif(not HAS_NODE, reason="node が無い環境")

# (名前, 取得時刻, 期待)。取得時刻は NOW（12:00 +09:00）からの相対で作る
def _iso(delta: timedelta, tz=JST) -> str:
    return (NOW - delta).astimezone(tz).isoformat(timespec="seconds")


VECTORS = [
    ("7h59m", _iso(timedelta(hours=7, minutes=59)), rf.FRESH),
    ("8h00m（境界。ちょうど 8 時間は FRESH）", _iso(timedelta(hours=8)), rf.FRESH),
    ("8h01m", _iso(timedelta(hours=8, minutes=1)), rf.STALE),
    ("9h", _iso(timedelta(hours=9)), rf.STALE),
    ("未来 +4m（許容内）", _iso(timedelta(minutes=-4)), rf.FRESH),
    ("未来 +5m（境界。許容内）", _iso(timedelta(minutes=-5)), rf.FRESH),
    ("未来 +6m", _iso(timedelta(minutes=-6)), rf.UNKNOWN),
    ("未来 +1 日", _iso(timedelta(days=-1)), rf.UNKNOWN),
    ("UTC（Z）で 7h59m", _iso(timedelta(hours=7, minutes=59), timezone.utc).replace("+00:00", "Z"), rf.FRESH),
    ("UTC（+00:00）で 8h01m", _iso(timedelta(hours=8, minutes=1), timezone.utc), rf.STALE),
    ("-08:00 で 7h59m", _iso(timedelta(hours=7, minutes=59), timezone(timedelta(hours=-8))), rf.FRESH),
    ("-08:00 で 8h01m", _iso(timedelta(hours=8, minutes=1), timezone(timedelta(hours=-8))), rf.STALE),
    ("+05:30 で 8h01m", _iso(timedelta(hours=8, minutes=1), timezone(timedelta(hours=5, minutes=30))), rf.STALE),
    ("小数秒（マイクロ秒）7h59m", (NOW - timedelta(hours=7, minutes=59)).isoformat(), rf.FRESH),
    ("オフセット無し（端末の時刻に依存させない）", "2026-11-22T11:00:00", rf.UNKNOWN),
    ("空", "", rf.UNKNOWN),
    ("None", None, rf.UNKNOWN),
    ("読めない", "yesterday", rf.UNKNOWN),
    ("日付だけ", "2026-11-22", rf.UNKNOWN),
    ("数値", 1700000000, rf.UNKNOWN),
]


@pytest.mark.parametrize("name,iso,expect", VECTORS, ids=[v[0] for v in VECTORS])
def test_python_rule(name, iso, expect):
    assert rf.evaluate(iso, NOW, MAXH, FUT) == expect


def test_threshold_has_a_single_definition_in_config():
    """8 時間・未来の許容は config/tcg_buyback.yaml だけ。Python の関数・ページの属性・JS に数値の複製が無い。"""
    cfg = bb.load_config()
    assert rf.thresholds(cfg) == (8.0, 5.0)
    a = rf.attrs("2026-11-22T11:00:00+09:00", cfg)
    assert 'data-fb-max="8"' in a and 'data-fb-fut="5"' in a and 'data-fb-obs="2026-11-22T11:00:00+09:00"' in a
    assert rf.attrs("x", cfg).startswith('data-fb-obs=""')                                 # 読めない時刻は空（JS は UNKNOWN にする）
    js = rf.JS_FRESHNESS
    assert "480" not in js and "28800" not in js and "*8" not in js.replace(" ", "")      # JS に 8 時間の数値を書かない
    assert "data-fb-max" in js and "data-fb-fut" in js
    # 変更しても Python 側の判定が設定に従う（別の定義を持たない）
    cfg2 = {**cfg, "freshness": {**cfg["freshness"], "observed_max_hours": 2}}
    row = {"shop": "rudeya", "observed_at": _iso(timedelta(hours=3)), "page_asof": _iso(timedelta(hours=3))}
    assert bb.classify_freshness(row, cfg2, NOW)[0] == bb.STALE
    assert bb.classify_freshness(row, cfg, NOW)[0] != bb.STALE


def _node(script: str, tz: str = "UTC") -> str:
    r = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=30, env={"TZ": tz, "PATH": "/usr/bin:/usr/local/bin:/opt/homebrew/bin"})
    assert r.returncode == 0, r.stderr
    return r.stdout


_HARNESS_HEAD = r"""
const vm=require('vm');
const ctx={window:{},document:{querySelectorAll:()=>[],addEventListener:()=>{}},setInterval:()=>0,Date:Date,parseFloat:parseFloat,isFinite:isFinite};
ctx.window.addEventListener=()=>{};
vm.createContext(ctx);
vm.runInContext(%s,ctx);
"""


@needs_node
@pytest.mark.parametrize("tz", ["UTC", "Asia/Tokyo", "America/Los_Angeles", "Pacific/Kiritimati"])
def test_js_matches_python_in_any_timezone(tz):
    """JS の判定が Python と同じ（端末のタイムゾーンに依存しない）。"""
    now_ms = int(NOW.timestamp() * 1000)
    script = (_HARNESS_HEAD % json.dumps(rf.JS_FRESHNESS)) + (
        "const V=%s;const out=V.map(v=>ctx.window.tcgFresh(v,%d,%s,%s));console.log(JSON.stringify(out));"
        % (json.dumps([v[1] for v in VECTORS]), now_ms, MAXH, FUT))
    got = json.loads(_node(script, tz))
    assert got == [rf.evaluate(v[1], NOW, MAXH, FUT) for v in VECTORS], tz
    assert got == [v[2] for v in VECTORS]


# ── HTML を要素の一覧にして、本物の JS（apply）を動かす ──
class _Els(HTMLParser):
    def __init__(self):
        super().__init__()
        self.els: list = []
        self._stale_stack: list = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "data-fb-live" in a or "data-fb-stale" in a:
            self.els.append({"tag": tag, "attrs": {k: ("" if v is None else v) for k, v in a.items()}, "hidden": "hidden" in a,
                             "kind": "live" if "data-fb-live" in a else "stale", "has_why": False, "why": ""})
            if "data-fb-stale" in a:
                self._stale_stack.append(self.els[-1])
        if "data-fb-why" in a and self._stale_stack:
            self._stale_stack[-1]["has_why"] = True


def _elements(html: str) -> list:
    p = _Els()
    p.feed(html)
    return p.els


def _apply(html: str, now: datetime, tz: str = "UTC") -> list:
    """生成した HTML の data-fb-* 要素に、本物の apply(now) を実行した結果（hidden と理由の文）。"""
    els = _elements(html)
    model = json.dumps(els)
    script = (r"""
const vm=require('vm');const E=%s;
function mk(e){const o={attrs:e.attrs,hidden:e.hidden,kind:e.kind,why:{textContent:''},has:e.has_why};
o.getAttribute=k=>(k in o.attrs?o.attrs[k]:null);o.setAttribute=(k,v)=>{o.attrs[k]=v};
o.querySelector=s=>(o.has?o.why:null);return o;}
const els=E.map(mk);
const doc={querySelectorAll:s=>els.filter(e=>(s==='[data-fb-live]'?e.kind==='live':e.kind==='stale')),addEventListener:()=>{}};
const ctx={window:{addEventListener:()=>{}},document:doc,setInterval:()=>0,Date:Date,parseFloat:parseFloat,isFinite:isFinite};
vm.createContext(ctx);vm.runInContext(%s,ctx);ctx.window.tcgFreshApply(%d);
console.log(JSON.stringify(els.map(e=>({kind:e.kind,hidden:e.hidden,why:e.why.textContent,group:e.attrs['data-fb-group']}))));
""" % (model, json.dumps(rf.JS_FRESHNESS), int(now.timestamp() * 1000)))
    return json.loads(_node(script, tz))


def _tcg_html(monkeypatch, obs: datetime) -> str:
    """生成時に FRESH の買取（定価あり・利益あり）を持つ TCG ページ。"""
    import tests.test_tcg_buyback as tb
    from src.content import tcg_hub_page as page_mod
    cfg = tb.CFG
    monkeypatch.setattr(bb, "load_config", lambda path=bb.CONFIG_PATH: cfg)
    h = tb._hub([tb.row(price=8000, jan="4500000000111", obs=obs, asof=obs)])
    return page_mod.render(h, generated_label="x")


def test_generated_html_starts_fail_closed(monkeypatch):
    """生成した HTML では、鮮度に依存する行は最初 hidden（JS が FRESH を確認できたときだけ出る）。参考表示は最初から出ている。"""
    import tests.test_tcg_buyback as tb
    html = _tcg_html(monkeypatch, tb.NOW)
    els = _elements(html)
    live = [e for e in els if e["kind"] == "live"]
    stale = [e for e in els if e["kind"] == "stale"]
    assert len(live) >= 4 and all(e["hidden"] for e in live)
    assert stale and not any(e["hidden"] for e in stale)
    assert all(e["attrs"]["data-fb-max"] == "36" for e in live)                        # fixture の設定（36）から。JS の数値ではない
    assert "価格再確認待ち" in html and "¥8,000" in html


@needs_node
def test_generated_fresh_html_9_hours_later_loses_fresh_executable_profit_roi(monkeypatch):
    """【重要】生成時は FRESH だった HTML の表示時刻だけを進める。最高買取・純利益・ROI・前提が出ず、参考価格と再確認待ちが出る。"""
    import tests.test_tcg_buyback as tb
    obs = tb.NOW
    html = _tcg_html(monkeypatch, obs)
    live_max = int(_elements(html)[0]["attrs"]["data-fb-max"])
    for tz in ("UTC", "Asia/Tokyo", "America/Los_Angeles"):
        fresh_now = _apply(html, obs + timedelta(hours=1), tz)
        assert all(not e["hidden"] for e in fresh_now if e["kind"] == "live"), tz         # 範囲内なら出る
        assert all(e["hidden"] for e in fresh_now if e["kind"] == "stale"), tz
        late = _apply(html, obs + timedelta(hours=live_max, minutes=1), tz)               # 範囲を超えたら
        assert all(e["hidden"] for e in late if e["kind"] == "live"), tz                  # 最高買取・確認・純利益・ROI・前提 = 全て非表示
        stale = [e for e in late if e["kind"] == "stale"]
        assert stale and all(not e["hidden"] for e in stale), tz                          # 参考価格と「価格再確認待ち」
        assert any(f"取得から{live_max}時間以上経過" in e["why"] for e in stale), tz


@needs_node
def test_boundary_and_future_and_missing_in_the_page(monkeypatch):
    import tests.test_tcg_buyback as tb
    obs = tb.NOW
    html = _tcg_html(monkeypatch, obs)
    mx = int(_elements(html)[0]["attrs"]["data-fb-max"])
    at = lambda d: all(not e["hidden"] for e in _apply(html, obs + d) if e["kind"] == "live")  # noqa: E731
    assert at(timedelta(hours=mx))                                                        # ちょうど: FRESH
    assert not at(timedelta(hours=mx, minutes=1))                                         # 1 分超: STALE
    assert not at(timedelta(minutes=-10))                                                 # 表示時刻が取得より前（未来の取得）: 出さない
    broken = html.replace('data-fb-obs="', 'data-fb-obs="x', 1)                           # 読めない時刻
    assert not all(not e["hidden"] for e in _apply(broken, obs) if e["kind"] == "live")
    missing = html.replace('data-fb-obs="' + _elements(html)[0]["attrs"]["data-fb-obs"] + '"', 'data-fb-obs=""', 1)
    assert not all(not e["hidden"] for e in _apply(missing, obs) if e["kind"] == "live")


def test_pnote_premise_is_also_gated(monkeypatch):
    import tests.test_tcg_buyback as tb
    html = _tcg_html(monkeypatch, tb.NOW)
    i = html.index("前提:")
    assert "data-fb-live" in html[html.rfind("<span", 0, i):i]


@needs_node
def test_home_profit_badge_9_hours_later(monkeypatch):
    """HOME の「利益根拠あり」: 生成時は FRESH 相当、8 時間を超えたら出さず「買取価格 再確認待ち」にする。TCG ページと同じ規則・同じ設定値。"""
    from src.content.ui import lottery_card as lc
    cfg = bb.load_config()
    mx = int(rf.thresholds(cfg)[0])
    obs = NOW
    vm = {"id": "lot-1", "prof": {"net": 1800, "roi": 29.0, "single": True, "obs": obs.isoformat()}}
    html = lc._profit_badge(vm)
    els = _elements(html)
    assert [e["kind"] for e in els] == ["live", "stale"] and els[0]["hidden"] and not els[1]["hidden"]      # 最初は fail-closed
    assert els[0]["attrs"]["data-fb-max"] == str(mx) and els[0]["attrs"]["data-fb-group"] == "lot-1"
    ok = _apply(html, obs + timedelta(hours=1))
    assert [e["hidden"] for e in ok] == [False, True]                                                   # 範囲内: 利益根拠あり
    late = _apply(html, obs + timedelta(hours=mx, minutes=1))
    assert [e["hidden"] for e in late] == [True, False]                                                 # 超過: 利益根拠は出ない
    assert _apply(html, obs + timedelta(hours=mx))[0]["hidden"] is False                                # 境界は FRESH（TCG と同じ）
    nots = lc._profit_badge({"id": "lot-2", "prof": {"net": 1800, "roi": 29.0, "single": False, "obs": None}})
    assert _apply(nots, obs)[0]["hidden"] is True                                                       # 取得時刻が無い: 出さない


def test_home_and_tcg_pages_embed_the_same_shared_js():
    """TCG ページと HOME に同じ JS（共通定義）を入れる。別々に書かない。"""
    for f in ("src/content/tcg_hub_page.py", "src/content/ui/shell.py"):
        assert "JS_FRESHNESS" in (ROOT / f).read_text(encoding="utf-8"), f
    assert (ROOT / "src/content/ui/lottery_card.py").read_text(encoding="utf-8").count("data-fb-live") >= 1


def test_highest_and_profit_use_separate_groups(monkeypatch):
    """最高買取の取得時刻と利益の基準の取得時刻が違っても、互いの表示を巻き込まない（片方だけ失効してもグループが別）。"""
    import tests.test_tcg_buyback as tb
    html = _tcg_html(monkeypatch, tb.NOW)
    groups = {e["attrs"]["data-fb-group"] for e in _elements(html)}
    assert any(g.endswith("-pf") for g in groups) and any(not g.endswith("-pf") for g in groups)
    for g in groups:
        if g.endswith("-pf"):
            assert g[:-3] in groups                                                         # 対応する最高買取のグループも別にある


def test_no_buyback_profit_amount_outside_the_freshness_gate(monkeypatch):
    """鮮度の判定（data-fb-live）の外に、買取由来の利益の金額が出ていない（補足・title など。独立監査 H1 の回帰）。"""
    import re
    import tests.test_tcg_buyback as tb
    html = _tcg_html(monkeypatch, tb.NOW)
    assert "+1,800円" in html                                                            # 利益が出ているカードがある fixture
    rest = re.sub(r"<div [^>]*data-fb-live[^>]*>.*?</div>|<span [^>]*data-fb-live[^>]*>.*?</span>", "", html, flags=re.S)
    assert not re.search(r"[+\-−][\d,]+円", rest), re.findall(r".{20}[+\-−][\d,]+円.{10}", rest)[:3]
    assert "29.0%" not in rest                                                           # ROI も同じ

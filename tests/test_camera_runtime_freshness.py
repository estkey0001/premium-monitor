# -*- coding: utf-8 -*-
"""Camera ページの表示時の鮮度（TCG の runtime freshness の再利用）。

- 共通の src/tcg/runtime_freshness.py と JS_FRESHNESS を使う（Camera 専用の JS・判定規則の複製を持たない）。
- 期間は config/camera_routes.yaml の freshness から（在庫 stock_days=2 → 72 時間、価格 executable_days=7 → 192 時間）。
- 観測時刻は各行の checked_at（日付）の 00:00 JST。生成時刻・表示時刻を観測時刻にしない。
- 買値（在庫 72h・価格 192h）と売値（192h）の両方に依存する要素は、期限ごとに入れ子の data-fb-live で包む。
- JS が動かなくても、鮮度に依存する要素は最初から hidden（fail-closed）。取得日つきの過去の参考価格は常時表示。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest

from src.content import camera_market_page as pg
from src.research import camera_routes as cr
from src.tcg import runtime_freshness as rf
from tests.test_camera_conditional_profit import _ended_market, bb, rd
from tests.test_camera_routes import CFG, JST, NOW, build, off, rec
from tests.test_tcg_runtime_freshness import _apply, _elements, needs_node

ROOT = Path(__file__).resolve().parent.parent
D = datetime(2026, 11, 18, 0, 0, tzinfo=JST)                       # 観測日 2026-11-18 の 00:00 JST
STOCK_H = rf.days_to_hours(CFG["freshness"]["stock_days"])           # 72
PRICE_H = rf.days_to_hours(CFG["freshness"]["executable_days"])      # 192
FUT = 5.0


def _buy_market():
    """登録済み・安全側で黒字・2 店・在庫あり = BUY のルートを持つ市場（調査日 2026-11-18）。"""
    rows = [rd(215000, [{"key": "COMPLETE_NO_STAMP", "price": 245000, "evidence": "list+item_page"},
                        {"key": "STAMPED_WARRANTY", "price": 215000, "deduction": 30000}]), bb("買取B", 213000)]
    m = build(rec(official=off(190000), buyback=rows))
    m["research_date"] = "2026-11-18"
    return m


def _render(m, now=NOW, **kw):
    return pg.render(m, now=now, **kw)


# ---------------------------------------------------------------- 共通の仕組みの再利用（複製しない）
def test_page_embeds_the_shared_js_once_and_has_the_hidden_css():
    html = _render(_buy_market())
    assert html.count(rf.JS_FRESHNESS) == 1 and "[data-fb-live][hidden]" in html and "display:none!important" in html
    src = (ROOT / "src/content/camera_market_page.py").read_text(encoding="utf-8")
    assert "runtime_freshness" in src and "JS_FRESHNESS" in src
    assert "function fresh" not in src and "Date.parse" not in src and "tcgFresh" not in src      # 判定規則を Python・JS で重複定義しない


def test_hours_come_from_the_camera_config_not_from_tcg_or_home():
    els = [e for e in _elements(_render(_buy_market())) if e["kind"] == "live"]
    assert {e["attrs"]["data-fb-max"] for e in els} == {f"{STOCK_H:g}", f"{PRICE_H:g}"} == {"72", "192"}
    cfg2 = {**CFG, "freshness": {**CFG["freshness"], "stock_days": 5, "executable_days": 3}}        # 設定を変えれば追従する（直書きでない）
    els2 = [e for e in _elements(_render(_buy_market(), cfg=cfg2)) if e["kind"] == "live"]
    assert {e["attrs"]["data-fb-max"] for e in els2} == {"144", "96"}
    assert "8" not in {e["attrs"]["data-fb-max"] for e in els} and "3" not in {e["attrs"]["data-fb-max"] for e in els}


def test_observed_time_is_the_rows_checked_at_not_the_generation_or_render_time():
    m = _buy_market()
    r = next(x for x in m["routes"] if x["route_type"] == "A")
    expected = {rf.date_obs(r["buy"]["checked_at"]), rf.date_obs(r["sell"]["checked_at"])}
    assert expected == {"2026-11-18T00:00:00+09:00"}
    a = {e["attrs"]["data-fb-obs"] for e in _elements(_render(m, now=NOW)) if e["kind"] == "live"}
    b = {e["attrs"]["data-fb-obs"] for e in _elements(_render(m, now=NOW + timedelta(hours=30))) if e["kind"] == "live"}
    assert a == b == expected                                                                  # 表示（生成）時刻が変わっても観測時刻は変わらない
    m2 = json.loads(json.dumps(m))
    m2["generated_at"] = "2026-11-18T23:59:59+09:00"
    assert {e["attrs"]["data-fb-obs"] for e in _elements(_render(m2)) if e["kind"] == "live"} == expected   # 生成時刻を使わない
    for p_ in m2["products"]:                                                                  # 確認日が読めない行は空 → JS は UNKNOWN にして出さない
        for rt in p_["routes"]:
            if rt.get("buy"):
                rt["buy"] = {**rt["buy"], "checked_at": "不明"}
    obs3 = {e["attrs"]["data-fb-obs"] for e in _elements(_render(m2)) if e["kind"] == "live"}
    assert "" in obs3 and "2026-11-18T00:00:00+09:00" in obs3                                  # 買値の観測時刻だけ空（売値は元のまま）


# ---------------------------------------------------------------- fail-closed
def test_live_elements_start_hidden_and_stale_markers_start_visible():
    els = _elements(_render(_buy_market()))
    live = [e for e in els if e["kind"] == "live"]
    stale = [e for e in els if e["kind"] == "stale"]
    assert len(live) >= 10 and all(e["hidden"] for e in live)                                  # JS が動かなければ出ない
    assert stale and not any(e["hidden"] for e in stale)
    assert {e["attrs"]["data-fb-group"].split("-")[-1] for e in live} >= {"act", "pf", "buy", "plus", "n"}   # 購入可否・利益・件数の各グループ


# ---------------------------------------------------------------- 境界（Python の規則と、本物の JS）
def _ev(obs, now, mx):
    return rf.evaluate(obs, now, mx, FUT)


@pytest.mark.parametrize("mx,days", [(STOCK_H, 2), (PRICE_H, 7)])
def test_boundaries_python_rule(mx, days):
    obs = rf.date_obs("2026-11-18")
    last = D + timedelta(days=days, hours=23, minutes=59)                                       # D+N 23:59
    edge = D + timedelta(days=days + 1)                                                         # D+N+1 00:00（ちょうど max 時間。FRESH）
    assert _ev(obs, last, mx) == rf.FRESH and _ev(obs, edge, mx) == rf.FRESH
    assert _ev(obs, edge + timedelta(minutes=1), mx) == rf.STALE                                # 00:01 で STALE
    assert _ev(obs, D - timedelta(minutes=10), mx) == rf.UNKNOWN                                # 観測より前（未来の観測）は出さない


def _groups(html, now):
    """グループごとの {live が全部見えている, stale が見えている}。"""
    els = _elements(html)
    res = _apply(html, now)
    g: dict = {}
    for e, r in zip(els, res):
        d = g.setdefault(r["group"], {"live_visible": True, "stale_visible": None})
        if e["kind"] == "live":
            d["live_visible"] = d["live_visible"] and not r["hidden"]
        else:
            d["stale_visible"] = not r["hidden"]
    return g


@needs_node
def test_page_groups_follow_stock_72h_and_price_192h_boundaries():
    html = _render(_buy_market())
    at = lambda delta: _groups(html, D + delta)                                                 # noqa: E731
    in_time = at(timedelta(days=2, hours=23, minutes=59))                                      # D+2 23:59: 在庫・価格とも内
    assert all(v["live_visible"] and not v["stale_visible"] for v in in_time.values())
    edge = at(timedelta(days=3))                                                                # D+3 00:00: ちょうど 72h は FRESH
    assert all(v["live_visible"] for v in edge.values())
    past = at(timedelta(days=3, minutes=1))                                                     # D+3 00:01: 在庫が失効
    for name, v in past.items():
        if name.endswith("-act") or name in ("cam-v-buy", "cam-v-n", "cam-v-plus-who"):      # 購入候補・購入できる・今日買えるもの件数・黒字の行の名前（「購入できる」を含む）は消える
            assert not v["live_visible"] and v["stale_visible"], name
        else:
            assert v["live_visible"], name                                                      # 利益・ROI・条件付き試算・黒字の件数は価格の期限（192h）まで残る
    mid = at(timedelta(days=7, hours=23, minutes=59))
    assert {n for n, v in mid.items() if v["live_visible"]} == {n for n, v in past.items() if v["live_visible"]}
    assert all(v["live_visible"] for n, v in at(timedelta(days=8)).items() if n.endswith("-pf") or n.endswith("-cd") or n == "cam-v-plus")   # D+8 00:00: ちょうど 192h
    gone = at(timedelta(days=8, minutes=1))                                                     # D+8 00:01: 価格も失効
    assert all(not v["live_visible"] and v["stale_visible"] for v in gone.values())


# ---------------------------------------------------------------- 漏れの検査（live の外に出ていないか）
class _Leak(HTMLParser):
    """data-fb-live の外にある文字・属性を集める（script/style を除く）。"""
    VOID = {"br", "wbr", "meta", "link", "img", "input", "hr"}

    def __init__(self, words):
        super().__init__()
        self.words, self.stack, self.found, self.skip = words, [], [], 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        a = {k: (v or "") for k, v in attrs}
        if tag not in self.VOID:
            self.stack.append("live" if "data-fb-live" in a else "x")
        if "live" not in self.stack:
            cls = a.get("class", "")
            if "sbadge--buy" in cls or "sbadge--profit" in cls or "BUY" in a.get("title", ""):
                self.found.append(("ATTR", tag, cls, a.get("title", "")))

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1
        if tag not in self.VOID and self.stack:
            self.stack.pop()

    def handle_data(self, d):
        if self.skip or "live" in self.stack:
            return
        for w in self.words:
            if w in d:
                self.found.append((w, d.strip()))


# 値も主張も持たない静的な文（ラベル・0 件・一般説明）だけを許す
ALLOWED_STATIC = {"購入候補のルート", "黒字 0 件", "黒字になるルートは確認できません。",
                  "カードは黒字・様子見が先、赤字・見送りは後に並べています。購入・売却の前に各公式ページで最新の情報を確認してください。"}


def _leaks(html, words):
    p = _Leak(words)
    p.feed(html)
    return [f for f in p.found if f[0] == "ATTR" or f[1] not in ALLOWED_STATIC]


def test_buy_profit_buyable_and_verdict_counts_do_not_leak_outside_live():
    m = _buy_market()
    r = next(x for x in m["routes"] if x["route_type"] == "A")
    assert r["decision"] == cr.BUY and r["net_profit"] == 215000 - 190000 - 1800
    html = _render(m)
    net, cond = f"+¥{r['net_profit']:,}", f"+¥{r['conditional'][0]['net_profit']:,}"
    assert net in html and cond in html and "購入できる" in html and "sbadge--buy" in html            # 出ている（live の中）
    words = ["購入できる", "黒字", "購入候補", "BUY", net, cond, f"{r['roi_pct']}%", f"{r['conditional'][0]['roi_pct']}%"]
    assert _leaks(html, words) == []
    assert _leaks(html, ["今日買えるもの 1", "黒字 1"]) == []                                         # 件数の文字列も live の外に無い


def test_verdict_counts_are_wrapped_and_stale_side_says_pending():
    html = _render(_buy_market())
    els = _elements(html)
    groups = {e["attrs"]["data-fb-group"] for e in els}
    assert {"cam-v-buy", "cam-v-plus", "cam-v-plus-who", "cam-v-n"} <= groups
    for g in ("cam-v-buy", "cam-v-plus", "cam-v-plus-who", "cam-v-n"):
        assert any(e["kind"] == "stale" and e["attrs"]["data-fb-group"] == g for e in els), g          # 期限切れ後に件数だけ残らない
    assert "確認待ち" in html
    n_html = html[html.index("購入候補のルート"):]
    assert re.match(r"購入候補のルート</span><b><span data-fb-live", n_html)                          # 件数は live の中


def test_conditional_amounts_roi_and_reasons_are_gated_even_when_unbuyable():
    m = _ended_market(cr.LOTTERY_ENDED)
    r = next(x for x in m["routes"] if x["route_type"] == "A")
    html = _render(m)
    cond = f"+¥{r['conditional'][0]['net_profit']:,}"
    assert cond in html and "実状態: 抽選は終了" in html
    assert _leaks(html, [cond, f"{r['conditional'][0]['roi_pct']}%", "購入できる", "店舗印なしの場合だけ黒字"]) == []


def test_reference_prices_with_dates_stay_visible_when_everything_expires():
    html = _render(_ended_market(cr.LOTTERY_ENDED))
    plain = re.sub(r"<(script|style).*?</\1>", "", html, flags=re.S)
    p = _Leak(["¥200,000", "¥195,000"])
    p.feed(plain)
    assert any(f[0] == "¥200,000" for f in p.found) and any(f[0] == "¥195,000" for f in p.found)      # live の外（常時表示）に買値・買取価格が残る
    assert "11/18" in re.sub(r"<[^>]+>", "", html) and "過去の参考価格: 買値 ¥200,000・買取 ¥195,000（取得日時点）" in re.sub(r"<[^>]+>", "", html)


def test_nocalc_table_buyable_word_is_gated():
    """『計算できなかった機種』の表の『購入できる』（買う側の在庫）も、表示時に在庫・価格の鮮度を確認できたときだけ出す。"""
    m = build(rec(official=off(200000), buyback=[]))
    m["research_date"] = "2026-11-18"
    html = _render(m)
    assert "購入できる" in html and _leaks(html, ["購入できる"]) == []
    live = [e for e in _elements(html) if e["kind"] == "live" and e["attrs"]["data-fb-group"].startswith("nc")]
    assert {e["attrs"]["data-fb-max"] for e in live} == {"72", "192"}


def test_python_stale_pages_stay_hidden_and_never_show_amounts():
    """生成時点で既に古いものは Python 側で非表示・参考扱い（二重に隠れてよい）。"""
    html = _render(_ended_market(cr.LOTTERY_ENDED), now=NOW + timedelta(days=8))
    text = re.sub(r"<[^>]+>", "", html)
    assert "+¥23,200" not in text and "11.6%" not in text                                       # live の中にも出さない（Python 側で隠す）
    assert "過去の参考: 買取 ¥195,000" in text and "試算は鮮度切れのため非表示" in text
    assert _leaks(html, ["購入できる", "+¥23,200", "11.6%"]) == []


def test_verdict_plus_line_stock_text_is_wrapped_by_stock_and_price_live():
    """黒字の行の名前は「…・購入できる」（在庫）を書くので、在庫（72h）と価格（192h）の両方の観測で包む。"""
    html = _render(_buy_market())
    els = _elements(html)
    who = [e for e in els if e["attrs"].get("data-fb-group") == "cam-v-plus-who"]
    assert any(e["kind"] == "stale" for e in who) and any(e["kind"] != "stale" for e in who)


# ── Reviewer L3: 設定不明（無い・不正）は None / nan（0 日ではない）。0 は正当な設定値（当日 24:00 まで） ──
def test_fb_defaults_fail_closed_to_zero_days_when_config_unreadable(monkeypatch):
    nan = lambda x: x != x  # noqa: E731
    assert nan(pg._FB({}).stock_h) and nan(pg._FB({}).price_h)
    assert nan(pg._FB({"freshness": {"stock_days": -1, "executable_days": "x"}}).stock_h)
    assert nan(pg._FB({"freshness": {"stock_days": 2.5, "executable_days": True}}).price_h)

    def boom():
        raise OSError("config unreadable")
    monkeypatch.setattr(pg, "_load_cfg", boom)
    fb = pg._FB()
    assert nan(fb.stock_h) and nan(fb.price_h)
    # 0 日・整数値の float は有効
    ok = pg._FB({"freshness": {"stock_days": 0, "executable_days": 7.0}})
    assert (ok.stock_h, ok.price_h) == (rf.days_to_hours(0), rf.days_to_hours(7))
    assert pg._days_or_none(0) == 0 and pg._days_or_none(None) is None


def test_fb_unknown_config_attrs_are_never_fresh_in_js():
    fb = pg._FB({})
    html = fb.wrap("<b>x</b>", "g", [("2026-11-25", "price")])
    assert 'data-fb-max="nan"' in html                      # JS は isFinite(maxH) で UNKNOWN_FRESHNESS → live を出さない


# ── Reviewer L4: 期限後の店舗印あり買取価格は取得日つき・理由欄は空・区切りだけにならない ──
def test_reasons_cond_only_has_expired_stub_not_empty_or_lone_separator():
    fb = pg._FB({"freshness": {"stock_days": 2, "executable_days": 7}})
    b = {"checked_at": "2026-11-10"}
    sl = {"checked_at": "2026-11-10"}
    out = pg._reasons_html(["conditional_profit_only"], False, b, sl, (fb, "g1"))
    assert "期限切れ・再確認待ち" in out and "data-fb-stale" in out
    two = pg._reasons_html(["conditional_profit_only", "single_buyback_shop"], False, b, sl, (fb, "g1"))
    assert "期限切れ・再確認待ち" in two and not two.startswith("、") and not two.endswith("、")


def test_safe_side_buy_price_cell_carries_its_check_date():
    fb = pg._FB({"freshness": {"stock_days": 2, "executable_days": 7}})
    b = {"price": 100000, "checked_at": "2026-11-10", "stock": "AVAILABLE", "freshness": "FRESH", "source": "店A"}
    sl = {"price": 120000, "checked_at": "2026-11-09", "freshness": "FRESH", "source": "買取B"}
    r = {"net_profit": 1000, "roi_pct": 1.0, "buy": b, "sell": sl,
         "conditional": [{"key": "no_seal", "sell_price": 130000, "net_profit": 5000, "roi_pct": 4.0, "requires": "x"}]}
    html = pg._conditional_html(r, b, sl, 0, (fb, "g2"))
    assert re.search(r'¥120,000<div class="mut">（<span title="2026-11-09">11/09</span> 確認）</div>', html)

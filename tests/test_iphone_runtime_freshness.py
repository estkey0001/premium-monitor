# -*- coding: utf-8 -*-
"""iPhone ページ（iphone-buyback.html）の鮮度は、生成時だけでなくページを見る時点でも成立する（TCG と同じ共通の判定）。

- 判定規則・JS は src/tcg/runtime_freshness.py（JS_FRESHNESS）の 1 つ。期間は config/iphone_buyback.yaml
  （freshness.page_buy_days = 7 日 → 192 時間、apple_availability_days = 2 日 → 48 時間）。ページのコードに数値を書かない。
- 生成時に FRESH・BUY だった HTML の表示時刻だけを進め、「更新が新しい」・最高買取・純利益・ROI・購入候補・BUY が出なくなることを確かめる。
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest

from src.content import iphone_buyback_page as P
from src.research import weekly_import as wi
from src.tcg import runtime_freshness as rf
from tests.test_iphone_hub import _comp, _row, _sku
from tests.test_tcg_runtime_freshness import _apply, _elements, needs_node

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
D0 = datetime(2026, 11, 17, 12, 0, tzinfo=JST)                    # 調査日・生成時
SKU = "iPhone Duo 1TB"
CFG = wi.load_config()
BUY_H = float((CFG["freshness"]["page_buy_days"] + 1) * 24)        # 7 日 → 192 時間（日付の確認日は 00:00 JST 起点・N 日目の終わりまで）
APPLE_H = float(CFG["freshness"]["apple_availability_days"] * 24)  # 2 日 → 48 時間（時刻つきの ISO なので丸めない）


def _buy_comp(opp="BUY", updated="2026-11-17"):
    rows = [_row(SKU, "a", "店A", 483000), _row(SKU, "b", "店B", 475000)]
    for r in rows:
        r["updated_on"] = updated
    s = _sku(SKU, hx={"shop": "店A", "price": 483000}, net=11400, roi=9.0, opp=opp, rows=rows)
    s["second"], s["third"] = {"shop": "店B", "price": 475000}, {"shop": "店C", "price": 470000}
    s["fresh_source_count"] = 2
    s["best_route"] = "Apple 購入 → 店A"
    s["apple_availability"] = {"status": "BUYABLE", "checked_at": "2026-11-17T10:00:00+09:00", "parts": {"X": True}}
    return _comp([s])


def _html(comp=None, now=D0):
    return P.render(comp or _buy_comp(), now=now)


class _Scan(HTMLParser):
    """live の外に出ている文字を (タグ, 文字) で集める（script・style は除く）。"""

    def __init__(self):
        super().__init__()
        self.stack, self.out, self.live_text = [], [], []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag not in ("br", "meta", "link", "img", "input", "hr"):
            self.stack.append((tag, "data-fb-live" in a, a))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if not data.strip() or any(t in ("script", "style") for t, _l, _a in self.stack):
            return
        inside = any(l for _t, l, _a in self.stack)
        stale = any("data-fb-stale" in a for _t, _l, a in self.stack)
        tag = self.stack[-1][0] if self.stack else ""
        (self.live_text if inside else self.out).append((tag, data.strip(), stale, dict(self.stack[-1][2]) if self.stack else {}))


def _outside(html):
    p = _Scan()
    p.feed(html)
    return p.out


def test_live_elements_start_hidden_so_js_off_fails_closed():
    els = _elements(_html())
    live = [e for e in els if e["kind"] == "live"]
    stale = [e for e in els if e["kind"] == "stale"]
    assert len(live) >= 20 and all(e["hidden"] for e in live)          # JS が動かなければ、最初から出ない
    assert stale and not any(e["hidden"] for e in stale)               # 「再確認待ち」が見える
    assert "[data-fb-live][hidden]" in _html() and rf.JS_FRESHNESS in _html()


def test_obs_and_max_come_from_row_dates_and_config():
    els = [e for e in _elements(_html()) if e["kind"] == "live"]
    obs = {e["attrs"]["data-fb-obs"] for e in els}
    assert obs == {rf.date_obs("2026-11-17"), "2026-11-17T10:00:00+09:00"}   # 行の updated_on（00:00 JST）と Apple の checked_at だけ。生成時刻は無い
    assert not any("2026-11-17T12:00" in o for o in obs)
    for e in els:
        mx = float(e["attrs"]["data-fb-max"])
        assert mx == (APPLE_H if e["attrs"]["data-fb-obs"].endswith("10:00:00+09:00") else BUY_H)
    assert BUY_H == 192.0 and APPLE_H == 48.0
    assert rf.days_to_hours(CFG["freshness"]["page_buy_days"]) == BUY_H


def test_buy_elements_nest_both_price_and_apple_observations():
    html = _html()
    assert re.search(r'data-fb-live[^>]*data-fb-obs="2026-11-17T00:00:00\+09:00"[^>]*hidden><span[^>]*data-fb-live[^>]*data-fb-obs="2026-11-17T10:00:00\+09:00"', html)
    groups = {}
    for e in _elements(html):
        groups.setdefault(e["attrs"]["data-fb-group"], []).append(e)
    assert any(any(x["kind"] == "stale" for x in v) and any(x["kind"] == "live" for x in v) for v in groups.values())


def test_missing_config_is_fail_closed_not_a_hardcoded_default(monkeypatch):
    monkeypatch.setitem(P._FRESH_CFG, "freshness", {})
    # 設定不明は None / nan（0 日ではない）。JS は nan を UNKNOWN_FRESHNESS = 出さない側に倒す
    assert P._days("page_buy_days") is None and P._buy_hours() != P._buy_hours()
    assert P._apple_hours() != P._apple_hours()
    assert P._is_stale_days(0) and P._is_stale_days(None)
    monkeypatch.setitem(P._FRESH_CFG, "freshness", {"page_buy_days": 0, "apple_availability_days": 0})
    assert P._days("page_buy_days") == 0 and P._buy_hours() == 24.0 and not P._is_stale_days(0)   # 0 は正当な設定値


def test_days_normalization_matches_home_and_camera(monkeypatch):
    for v, exp in ((0, 0), (3, 3), (7.0, 7), (True, None), (-1, None), (2.5, None), ("7", None), (None, None)):
        monkeypatch.setitem(P._FRESH_CFG, "freshness", {"page_buy_days": v})
        assert P._days("page_buy_days") == exp, v


def test_price_age_text_is_not_frozen_to_research_date():
    """行の日付の横に『N日前』（調査日基準で固定）を出さない。取得日だけ。"""
    html = _html(now=D0 + timedelta(days=8))
    assert not re.search(r"（\d+日前）", html)


@needs_node
def test_page_9_days_after_loses_fresh_best_profit_roi_and_buy():
    html = _html()
    ok = _apply(html, D0)
    assert all(not e["hidden"] for e in ok if e["kind"] == "live") and all(e["hidden"] for e in ok if e["kind"] == "stale")
    late = _apply(html, D0 + timedelta(days=9))
    assert all(e["hidden"] for e in late if e["kind"] == "live")
    assert all(not e["hidden"] for e in late if e["kind"] == "stale")
    assert "取得 11/17" in html


@needs_node
def test_buy_disappears_when_apple_availability_expires_but_prices_remain():
    """Apple の確認（11/17 10:00 +48h = 11/19 10:00）だけが先に切れる。買取価格（7 日）は残るが、購入候補・BUY・「買い」は出ない。"""
    html = _html()
    els = _elements(html)
    res = _apply(html, datetime(2026, 11, 19, 10, 1, tzinfo=JST))
    apple_dep = {i for i, e in enumerate(els) if e["kind"] == "live" and e["attrs"]["data-fb-obs"].endswith("10:00:00+09:00")}
    assert apple_dep
    assert all(res[i]["hidden"] for i in apple_dep)
    best = [r for e, r in zip(els, res) if e["kind"] == "live" and "-hb" in e["attrs"]["data-fb-group"] and e["attrs"]["data-fb-obs"].startswith("2026-11-17T00")]
    assert best and all(not r["hidden"] for r in best)                 # 最高買取の金額は価格側の期限（7 日）なのでまだ出る


@needs_node
@pytest.mark.parametrize("delta,fresh", [
    (timedelta(days=7, hours=23, minutes=59) - timedelta(hours=12), True),    # D+7 23:59
    (timedelta(days=8) - timedelta(hours=12), True),                          # D+8 00:00（境界。ちょうど 192 時間は FRESH）
    (timedelta(days=8, minutes=1) - timedelta(hours=12), False),              # D+8 00:01
])
def test_price_boundary_in_the_page(delta, fresh):
    comp = _buy_comp()
    comp["skus"][0]["apple_availability"]["checked_at"] = "2026-11-24T23:00:00+09:00"      # Apple 側は境界に関係させない
    html = _html(comp)
    price_live = [e for e in _elements(html) if e["kind"] == "live" and e["attrs"]["data-fb-obs"].startswith("2026-11-17T00")]
    res = _apply(html, D0 + delta)
    els = _elements(html)
    got = [not r["hidden"] for e, r in zip(els, res) if e in price_live]
    assert got and all(g is fresh for g in got)


def test_rf_boundary_vectors_for_config_values():
    obs = rf.date_obs("2026-11-17")
    ev = lambda now: rf.evaluate(obs, now, BUY_H, 5.0)   # noqa: E731
    assert ev(datetime(2026, 11, 24, 23, 59, tzinfo=JST)) == rf.FRESH
    assert ev(datetime(2026, 11, 25, 0, 0, tzinfo=JST)) == rf.FRESH
    assert ev(datetime(2026, 11, 25, 0, 1, tzinfo=JST)) == rf.STALE
    ap = "2026-11-17T10:00:00+09:00"
    assert rf.evaluate(ap, datetime(2026, 11, 19, 10, 0, tzinfo=JST), APPLE_H, 5.0) == rf.FRESH
    assert rf.evaluate(ap, datetime(2026, 11, 19, 10, 1, tzinfo=JST), APPLE_H, 5.0) == rf.STALE
    assert rf.evaluate("", D0, APPLE_H, 5.0) == rf.UNKNOWN


def test_nothing_that_can_expire_leaks_outside_live():
    """期限切れ後に残りうる文字（live の外）に、FRESH バッジ・最高買取・純利益・ROI・BUY・購入候補です・うち更新が新しい N 店が無い。"""
    out = _outside(_html())
    texts = [(t, s) for t, s, st_, _a in out if not st_]            # 「再確認待ち」側（stale）の文は、期限切れ後に見せるためのもの
    flat = " ".join(s for _t, s in texts)
    for bad in ("購入候補です", "うち更新が新しい", "+¥11,400", "9.0%", "BUY（週次の判定）", "購入できる（Apple で確認）", "FRESH（更新が新しい）", "計算上の黒字", "最大利益ルート: Apple"):
        assert bad not in flat, bad
    assert not [x for x in texts if x[0] == "b" and x[1] in ("¥483,000", "+¥11,400", "9.0%", "店A")]          # hero・結論・詳細の最高買取/利益/ROI/売り先は live の中だけ
    assert not [x for x in out if not x[2] and x[1] in ("購入候補", "黒字", "更新が新しい") and x[3].get("title") != "FRESH"]   # バッジ（「更新が新しい」のタイル見出しだけは固定ラベル）
    assert not [x for x in out if "sbadge--buy" in (x[3].get("class") or "") or "sbadge--profit" in (x[3].get("class") or "")]
    # 取得日つきの過去の参考価格は、行の表（金額は常時表示）と stale 側に残る
    assert any("¥483,000" in s for _t, s in texts)
    assert "取得 11/17 の参考価格" in " ".join(s for _t, s, _x, _a in out)


def test_fresh_badge_and_rank_are_gated_per_row():
    html = _html()
    rows = [r for r in re.findall(r"<tr class=.*?</tr>", html, flags=re.S) if 'data-label="順位"' in r]
    assert len(rows) == 2
    for r in rows:
        assert re.search(r'<span[^>]*data-fb-live[^>]*>\s*<span class="sbadge sbadge--info">更新が新しい</span>', r)
        assert re.search(r'class="rk1" data-fb-live', r) or "2 位" in r
        out = [x for x in _outside(r) if not x[2]]
        assert not [x for x in out if x[1] in ("更新が新しい", "1 位", "2 位")]            # 順位・FRESH バッジは live の中だけ


def test_stale_at_generation_stays_python_side():
    """生成時に既に古い行は従来どおり Python が参考扱い（live にしない）。"""
    comp = _buy_comp()
    comp["skus"][0]["rows"][1].update(freshness="STALE", eligible=False)
    html = _html(comp)
    row_b = [r for r in re.findall(r"<tr class=.*?</tr>", html, flags=re.S) if 'data-label="順位"' in r and "店B" in r][0]
    assert "data-fb-live" not in row_b and "更新が古い" in row_b and "ng is-stale" in row_b


def test_real_data_renders_with_old_research_date():
    p = ROOT / "exports" / "iphone_buyback" / "iphone_buyback_comparison.json"
    if not p.exists():
        pytest.skip("実データなし")
    import json
    comp = json.loads(p.read_text(encoding="utf-8"))
    html = P.render(comp, now=datetime(2026, 11, 25, 12, 0, tzinfo=JST))
    assert "<table" in html and rf.JS_FRESHNESS in html
    assert not [x for x in _outside(html) if x[1] == "購入候補です"]


def test_no_hardcoded_periods_in_page_code():
    src = (ROOT / "src/content/iphone_buyback_page.py").read_text(encoding="utf-8")
    code = "\n".join(l.split("#")[0] for l in src.splitlines())
    assert "192" not in code and "48" not in code
    assert not re.search(r"[<>]=?\s*7\b", code)                                 # 「7 日」の直書きが無い（age_banner・今日のおすすめ・_PAGE_STALE も設定から）
    assert not re.search(r"(days|_d)\s*(<=|>)\s*\d", code)
    assert "page_buy_days" in src and "apple_availability_days" in src
    assert "page_buy_days" in (ROOT / "config/iphone_buyback.yaml").read_text(encoding="utf-8")


def test_page_with_no_buy_still_gates_profit_and_count():
    """BUY が 0 件（WAIT）でも、最高買取・純利益・ROI・うち更新が新しい N 店は live の中だけ。"""
    html = _html(_buy_comp(opp="WAIT"))
    out = _outside(html)
    assert not [x for x in out if not x[2] and x[0] == "b" and x[1] in ("¥483,000", "+¥11,400", "9.0%")]
    assert "うち更新が新しい" not in " ".join(s for _t, s, x, _a in out if not x)
    assert "購入候補です" not in " ".join(s for _t, s, _x, _a in out)


def test_every_buy_expression_depends_on_apple_availability_too():
    """購入候補（バッジ・lead・結論の「買い」・BUY の判定）は、買取価格と Apple 購入可否の両方の live の内側にだけある。"""
    html = _html()
    found = []

    class P_(HTMLParser):
        def __init__(self):
            super().__init__()
            self.st = []

        def handle_starttag(self, tag, attrs):
            a = dict(attrs)
            if tag not in ("br", "meta", "link", "input"):
                self.st.append(a)
            if "sbadge--buy" in (a.get("class") or ""):
                found.append(("badge", self._obs()))

        def handle_endtag(self, tag):
            if self.st:
                self.st.pop()

        def _obs(self):
            return {a.get("data-fb-obs") for a in self.st if "data-fb-live" in a}

        def handle_data(self, d):
            if any(w in d for w in ("が購入候補です", "を買い、", "BUY（週次の判定）")) and not any("data-fb-stale" in a for a in self.st):
                found.append((d.strip()[:12], self._obs()))
    P_().feed(html)
    kinds = {k for k, _o in found}
    assert {"badge", "BUY（週次の判定）"} <= kinds and any("購入候補です" in k for k in kinds)
    for k, o in found:
        assert rf.date_obs("2026-11-17") in o and "2026-11-17T10:00:00+09:00" in o, (k, o)


# ── Reviewer L2（ページ側の対応確認）: Apple の確認時刻がオフセットなしなら、ページの parse_aware は None（UNKNOWN）。HOME もこれに合わせた ──
def test_offsetless_apple_checked_at_is_unknown_for_both_page_and_home():
    from src.tcg import runtime_freshness as _rf
    assert _rf.parse_aware("2026-11-20T09:00:00") is None
    assert _rf.parse_aware("2026-11-20T09:00:00+09:00") is not None


def test_unreadable_config_does_not_crash_render_and_fails_closed(monkeypatch):
    """Reviewer M1: load_config が例外を出し設定が空でも、ページ生成は落ちない。属性の max は nan（JS が UNKNOWN にして出さない側）。"""
    def boom():
        raise RuntimeError("config unreadable")
    monkeypatch.setattr(P, "_FRESH_CFG", {})
    monkeypatch.setattr(wi, "load_config", boom)
    assert 'data-fb-max="nan"' in P._buy_attrs("2026-11-25") and 'data-fb-max="nan"' in P._apple_attrs("2026-11-25T10:00:00+09:00")
    html = _html()                                   # 落ちない
    live = [e for e in _elements(html) if e["kind"] == "live"]
    assert live and all(e["attrs"]["data-fb-max"] == "nan" and e["hidden"] for e in live)
    out = _outside(html)
    texts = [(t, s) for t, s, st_, _a in out if not st_]
    assert not [x for x in texts if x[0] == "b" and x[1] in ("¥483,000", "+¥11,400", "9.0%")]      # hero の金額・BUY は live の中だけ
    p = _Scan()
    p.feed(html)
    flat_live = " ".join(s for _t, s, _x, _a in p.live_text)
    assert "¥483,000" in flat_live and "BUY" in flat_live

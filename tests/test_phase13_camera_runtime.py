"""Phase 13（カメラの買取の取得時間）のテスト。

フジヤの取得の間隔（90秒）・robots.txt・正直な User-Agent は変えずに、同じページへのリクエストを減らす:
- 1ページは1回だけ開く（静まらない＝広告・計測のタグの通信が続くだけで、同じ URL を開き直さない）
- 大文字・小文字だけが違う検索語を重ねない
- この実行で取得済みのページに、機種の厳密一致の買取価格があれば使い回す（照合の条件は自分の検索のときと同じ）
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _load():
    spec = importlib.util.spec_from_file_location("p13_camera", ROOT / "scripts" / "update_camera_buyback.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _Page:
    def __init__(self, log, first_goto_fails=False, idle_times_out=True):
        self.log, self.first_goto_fails, self.idle_times_out = log, first_goto_fails, idle_times_out

    def goto(self, url, wait_until=None, timeout=None):
        self.log.append(("goto", wait_until))
        if self.first_goto_fails and sum(1 for x in self.log if x[0] == "goto") == 1:
            raise RuntimeError("net::ERR_ABORTED")
        return types.SimpleNamespace(status=200)

    def wait_for_load_state(self, state, timeout=None):
        self.log.append(("idle", state))
        if self.idle_times_out:
            raise TimeoutError("networkidle")           # 広告・計測のタグで静まらない

    def title(self):
        return "買取検索"

    def inner_text(self, sel):
        return "RICOH GR IV 買取金額 新品同様 ￥151,000"

    def wait_for_selector(self, sel, timeout=None):
        return True

    def content(self):
        return "<html><body>RICOH GR IV 買取金額 新品同様 ￥151,000</body></html>"

    def evaluate(self, js):
        return {"selector_candidates": [], "matched_selectors": [], "hit_count": 1}

    def screenshot(self, **kw):
        return b""


@pytest.fixture
def fake_pw(monkeypatch):
    """playwright.sync_api を偽物にする（ネットワークに出ない）。"""
    log: list = []
    state = {"first_goto_fails": False, "idle_times_out": True}

    class _Browser:
        def new_context(self, **kw):
            log.append(("ua", kw.get("user_agent")))
            return types.SimpleNamespace(new_page=lambda: _Page(log, **state))

        def close(self):
            pass

    class _PW:
        chromium = types.SimpleNamespace(launch=lambda **kw: _Browser())

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False
    mod = types.ModuleType("playwright.sync_api")
    mod.sync_playwright = lambda: _PW()
    monkeypatch.setitem(sys.modules, "playwright", types.ModuleType("playwright"))
    monkeypatch.setitem(sys.modules, "playwright.sync_api", mod)
    waits: list = []
    from src.collectors import polite
    monkeypatch.setattr(polite, "robots_allowed", lambda url: True)
    monkeypatch.setattr(polite, "polite_wait", lambda url, sid=None: waits.append(url))
    return log, state, waits


URL = "https://www.fujiya-camera.co.jp/shop/purchase/list.aspx?keyword=RICOH%20GR%20IV&search=x"


def test_page_is_opened_once_even_if_network_never_idles(fake_pw, tmp_path):
    log, state, waits = fake_pw
    m = _load()
    out = m._fetch_with_playwright(URL, "src_fujiya", "gr4", tmp_path)
    gotos = [x for x in log if x[0] == "goto"]
    assert gotos == [("goto", "domcontentloaded")]           # 開き直さない（以前は networkidle → もう一度）
    assert len(waits) == 1                                   # 間隔の待ちは1回（90秒の間隔そのものは変えない）
    assert out.get("html") and not out.get("reason")
    assert any(x[0] == "ua" and str(x[1]).startswith("PremiumMonitor/") for x in log)   # 正直な User-Agent


def test_page_is_reopened_only_when_it_cannot_be_opened(fake_pw, tmp_path):
    log, state, waits = fake_pw
    state["first_goto_fails"] = True
    m = _load()
    out = m._fetch_with_playwright(URL, "src_fujiya", "gr4", tmp_path)
    assert [x for x in log if x[0] == "goto"] == [("goto", "domcontentloaded")] * 2
    assert len(waits) == 2                                   # 開き直す前にも同じドメインの間隔をあける
    assert out.get("html")


def test_case_only_variants_are_not_fetched_twice(tmp_path, monkeypatch):
    m = _load()
    monkeypatch.setattr(m, "ROOT", tmp_path)
    assert m._ordered_variants("m11", ["Leica M11", "LEICA M11"]) == ["Leica M11"]
    assert m._ordered_variants("x", ["GR III", "gr  iii", "RICOH GR III"]) == ["GR III", "RICOH GR III"]
    # 否定対照: 中身が違う検索語は残す（上限2つ）
    assert m._ordered_variants("x", ["a", "b", "c"]) == ["a", "b"]


def _cand(text, price):
    return {"item_text": text, "text": text, "price": price, "near_buyback": True}


def test_reuse_page_only_with_strict_model_match():
    m = _load()
    # CI（2026-10-07）の「RICOH GR IV」の検索結果の形: GR IV Monochrome・GR IV HDF・GR IV が載る
    page = {"selector_candidates": [
        _cand("RICOH GR IV Monochrome RICOH 買取金額 新品同様 ￥194,000 良品 ￥193,000", 194000),
        _cand("RICOH GR IV HDF RICOH 買取金額 新品同様 ￥194,000 良品 ￥193,000", 194000),
        _cand("RICOH GR IV RICOH 買取金額 新品同様 ￥151,000 良品 ￥150,000", 151000)], "hit_count": 8}
    own = {a: m._select_camera_buyback(page["selector_candidates"], a) for a in ("gr4", "gr4_hdf", "gr4_mono")}
    for alias in ("gr4_hdf", "gr4_mono"):
        r = m._reuse_fujiya_page(alias, [("RICOH GR IV", page)])
        assert own[alias]["price"] in (194000,)                 # 比べる元（自分の検索のときの選定）が空でない
        assert r is not None and r[0] == "RICOH GR IV"
        assert r[2]["price"] == own[alias]["price"] and r[2]["condition"] == own[alias]["condition"]
    # 否定対照: 載っていない機種（GR IIIx）・別の機種（GR III）は使い回さない（自分の検索語で取る）
    assert m._reuse_fujiya_page("gr3x", [("RICOH GR IV", page)]) is None
    assert m._reuse_fujiya_page("gr3", [("RICOH GR IV", page)]) is None
    assert m._reuse_fujiya_page("gr4_hdf", []) is None
    # HDF と Monochrome は互いに除外する（両方の語を含む候補はどちらにも付けない。レビュー L-7）
    both = [_cand("RICOH GR IV HDF Monochrome RICOH 買取金額 新品同様 ￥300,000", 300000)]
    assert m._select_camera_buyback(both, "gr4_hdf").get("price") is None
    assert m._select_camera_buyback(both, "gr4_mono").get("price") is None
    import inspect
    assert "reused_page=bool(_pw.get(\"reused_page\"))" in inspect.getsource(m.main)   # 使い回しを status に残す


def test_fujiya_interval_and_safety_unchanged():
    """90秒の間隔・robots・正直な UA・打ち切りは変えない（短縮は同じページへのリクエストを減らすことだけ）。"""
    import inspect

    import yaml
    m = _load()
    srcs = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    rows = srcs.get("sources", srcs) if isinstance(srcs, dict) else srcs
    fujiya = next(s for s in rows if isinstance(s, dict) and s.get("id") == "src_fujiya")
    assert fujiya["rate_limit_sec"] == 90
    src = inspect.getsource(m._fetch_with_playwright)
    assert "polite.robots_allowed(url)" in src and "polite.polite_wait(url, shop_id)" in src
    assert "user_agent=polite.HONEST_UA" in src
    assert "cutoff.is_cut(shop_id)" in inspect.getsource(m.main)

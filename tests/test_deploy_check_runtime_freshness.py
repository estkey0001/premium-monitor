# -*- coding: utf-8 -*-
"""deploy-check #893〜#895（Camera・iPhone・HOME の表示時の鮮度）の検査関数のテスト。

render 関数に合成データを渡して生成した HTML を、deploy_check の検査関数に通す。
変異（属性を削る・hidden を外す・生成時刻を観測時刻にする・live の外に購入候補を出す など）が、それぞれ検査に落ちることを確かめる。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import deploy_check as dc  # noqa: E402

from src.content import camera_market_page as cam_pg  # noqa: E402
from src.content import iphone_buyback_page as ip_pg  # noqa: E402
from src.content.ui import shell  # noqa: E402
from src.research import camera_routes as cr  # noqa: E402
from tests import test_home_runtime_cards as H  # noqa: E402
from tests.test_camera_conditional_profit import _ended_market  # noqa: E402
from tests.test_camera_routes import CFG as CAM_CFG, NOW as CAM_NOW  # noqa: E402
from tests.test_camera_runtime_freshness import _buy_market  # noqa: E402
from tests.test_iphone_runtime_freshness import CFG as IP_CFG, D0, _buy_comp  # noqa: E402


# ---------------------------------------------------------------- 共通
def _new(base: list, mutated: list) -> list:
    return sorted(set(mutated) - set(base))


def _must_fail(base: list, mutated: list, needle: str) -> None:
    new = _new(base, mutated)
    assert new, "変異を検出できていない"
    assert any(needle in x for x in new), (needle, new)


def _strip_fb_attrs(html: str) -> str:
    """data-fb-* の属性を全部消す（属性なしの要素に戻った退行）。"""
    return re.sub(r' data-fb-(?:live|stale|group|obs|max|fut)(?:="[^"]*")?', "", html).replace(" hidden>", ">")


# ---------------------------------------------------------------- #893 Camera
def _cam(m=None):
    m = m or _ended_market(cr.OUT_OF_STOCK)
    return m, cam_pg.render(m, now=CAM_NOW)


def _cam_problems(html, m):
    return dc.check_camera_runtime_freshness(html, m, CAM_CFG)


def test_camera_clean_page_passes():
    m, h = _cam()
    assert 'data-fb-live' in h and _cam_problems(h, m) == []


def test_camera_buy_page_all_markers_are_inside_live_with_stock_and_both_prices():
    m = _buy_market()
    h = cam_pg.render(m, now=CAM_NOW)
    bad = _cam_problems(h, m)
    # BUY のバッジ・購入候補は 在庫 72h・買値 192h・売値 192h の 3 重の live の中。残る指摘は下の 1 件だけ
    assert all("購入できる" not in x or "在庫" in x for x in bad)
    assert not any("live の外" in x or "しきい値" in x or "観測時刻" in x or "hidden" in x for x in bad), bad


def test_camera_buy_page_passes_cleanly():
    m = _buy_market()
    assert _cam_problems(cam_pg.render(m, now=CAM_NOW), m) == []


def test_camera_hours_come_from_config():
    m, h = _cam()
    cfg2 = {**CAM_CFG, "freshness": {**CAM_CFG["freshness"], "stock_days": 5, "executable_days": 3}}
    assert any("しきい値" in x for x in dc.check_camera_runtime_freshness(h, m, cfg2))      # 設定を変えれば、古い属性は落ちる


def test_camera_mutation_attrs_removed_div_regression():
    m, h = _cam()
    _must_fail(_cam_problems(h, m), _cam_problems(_strip_fb_attrs(h), m), "live の外")
    assert _cam_problems(_strip_fb_attrs(h), m)


def test_camera_mutation_hidden_removed():
    m, h = _cam()
    _must_fail(_cam_problems(h, m), _cam_problems(h.replace(" hidden>", ">", 1) if " data-fb-live" in h else h, m), "hidden が無い")


def test_camera_mutation_generation_time_as_observation():
    m, h = _cam()
    mut = h.replace('data-fb-obs="2026-11-18T00:00:00+09:00"', 'data-fb-obs="2026-11-18T12:00:00+09:00"', 1)
    _must_fail(_cam_problems(h, m), _cam_problems(mut, m), "確認日と一致しない")
    mut2 = re.sub(r'data-fb-obs="[^"]*"', 'data-fb-obs="2026-11-25T19:19:52+09:00"', h, count=1)
    _must_fail(_cam_problems(h, m), _cam_problems(mut2, m), "確認日と一致しない")


def test_camera_mutation_buy_outside_live():
    m, h = _cam()
    for ins in ('<span class="sbadge sbadge--buy">購入候補</span>', "<b>購入できる</b>", '<span class="sbadge sbadge--profit">黒字</span>', "<p>純利益 +¥23,200</p>"):
        mut = h.replace("<main", ins + "<main", 1) if "<main" in h else h.replace("<body>", "<body>" + ins, 1)
        assert mut != h
        assert _new(_cam_problems(h, m), _cam_problems(mut, m)), ins


def test_camera_mutation_conditional_amount_outside_live():
    m, h = _cam()
    mut = re.sub(r'(?:<span data-fb-live[^>]*>){2}(<b class="">\+¥23,200</b>)(?:</span>){2}', r"\1", h)
    assert mut != h, "条件付き試算の金額の live が見つからない"
    _must_fail(_cam_problems(h, m), _cam_problems(mut, m), "条件付き試算")


def test_camera_mutation_conditional_price_and_diff_outside_live():
    """M5: 条件付き試算の行の買取価格・価格差を live の外に出すと落ちる（検査は 2〜5 列目）。"""
    m, h = _cam()
    i = h.index("店舗印なし（条件付き試算）")
    j = h.index("</tr>", i)
    row = h[i:j]
    live = re.compile(r'(?:<span data-fb-live[^>]*>)+(¥\d[\d,]*)(?:</span>)+')
    assert live.search(row), "買取価格の live が見つからない"
    mut = h[:i] + live.sub(r"\1", row, count=1) + h[j:]
    _must_fail(_cam_problems(h, m), _cam_problems(mut, m), "条件付き試算")
    live2 = re.compile(r'(?:<span data-fb-live[^>]*>)+([+−]?¥\d[\d,]*)(?:</span>)+')
    cols = row.split("<td")
    k = next(n for n, c in enumerate(cols) if n == 2)                      # 価格差のセル（th, 買取価格, 価格差の順）
    assert live2.search(cols[k]), "価格差の live が見つからない"
    cols[k] = live2.sub(r"\1", cols[k], count=1)
    mut2 = h[:i] + "<td".join(cols) + h[j:]
    _must_fail(_cam_problems(h, m), _cam_problems(mut2, m), "条件付き試算")


def test_camera_mutation_stale_pair_and_visible():
    m, h = _cam()
    mut = h.replace("data-fb-stale ", "data-fb-stale hidden ", 1)
    _must_fail(_cam_problems(h, m), _cam_problems(mut, m), "最初から hidden")
    mut2 = re.sub(r'data-fb-stale data-fb-group="([^"]*)"', r'data-fb-stale data-fb-group="\1-x"', h, count=1)
    _must_fail(_cam_problems(h, m), _cam_problems(mut2, m), "対になる live が無い")


def test_camera_mutation_js_missing_or_twice_or_css_missing():
    m, h = _cam()
    from src.tcg import runtime_freshness as rf
    _must_fail(_cam_problems(h, m), _cam_problems(h.replace(rf.JS_FRESHNESS, ""), m), "JS")
    _must_fail(_cam_problems(h, m), _cam_problems(h + f"<script>{rf.JS_FRESHNESS}</script>", m), "JS")
    _must_fail(_cam_problems(h, m), _cam_problems(h.replace("[data-fb-live][hidden]", "[x]"), m), "CSS")


def test_camera_mutation_buy_live_missing_an_observation():
    m = _buy_market()
    h = cam_pg.render(m, now=CAM_NOW)
    # BUY の購入候補バッジを、live が 1 重だけの包みにする
    mut = re.sub(r'(<span data-fb-live[^>]*>){3}(<span class="sbadge sbadge--buy">購入候補</span>)(</span>){3}',
                 lambda mm: mm.group(1) + mm.group(2) + "</span>", h)
    assert mut != h
    _must_fail(_cam_problems(h, m), _cam_problems(mut, m), "在庫・買値・売値の観測がそろっていない")


# ---------------------------------------------------------------- #894 iPhone
def _ip(comp=None):
    comp = comp or _buy_comp()
    return comp, ip_pg.render(comp, now=D0)


def _ip_problems(html, comp, src=None):
    return dc.check_iphone_runtime_freshness(html, comp, IP_CFG, src)


def test_iphone_clean_page_passes():
    comp, h = _ip()
    src = (ROOT / "src" / "content" / "iphone_buyback_page.py").read_text(encoding="utf-8")
    assert "data-fb-live" in h and _ip_problems(h, comp, src) == []


def test_iphone_hours_from_config_192_and_48():
    comp, h = _ip()
    mx = set(re.findall(r'data-fb-max="([^"]*)"', h))
    assert mx == {"192", "48"}
    cfg2 = {**IP_CFG, "freshness": {**IP_CFG["freshness"], "page_buy_days": 3}}
    assert any("しきい値" in x for x in dc.check_iphone_runtime_freshness(h, comp, cfg2))


def test_iphone_mutation_attrs_removed_div_regression():
    comp, h = _ip()
    assert _ip_problems(_strip_fb_attrs(h), comp)
    assert any("live の外" in x or "hero" in x for x in _new(_ip_problems(h, comp), _ip_problems(_strip_fb_attrs(h), comp)))


def test_iphone_mutation_hidden_removed_and_stale_hidden():
    comp, h = _ip()
    _must_fail(_ip_problems(h, comp), _ip_problems(h.replace(" hidden>", ">", 1), comp), "hidden が無い")
    _must_fail(_ip_problems(h, comp), _ip_problems(h.replace("data-fb-stale ", "data-fb-stale hidden ", 1), comp), "最初から hidden")


def test_iphone_mutation_generation_time_as_observation():
    comp, h = _ip()
    mut = re.sub(r'data-fb-obs="2026-11-17T00:00:00\+09:00"', 'data-fb-obs="2026-11-17T12:00:00+09:00"', h, count=1)
    _must_fail(_ip_problems(h, comp), _ip_problems(mut, comp), "確認日と一致しない")
    mut2 = h.replace('data-fb-obs="2026-11-17T10:00:00+09:00"', 'data-fb-obs="2026-11-17T12:00:00+09:00"', 1)     # Apple 側を生成時刻に
    _must_fail(_ip_problems(h, comp), _ip_problems(mut2, comp), "確認日と一致しない")


def test_iphone_mutation_value_outside_live():
    comp, h = _ip()
    base = _ip_problems(h, comp)
    for ins in ("<p>iPhone Duo 1TB が購入候補です。</p>", "<em>うち更新が新しい 2 店</em>", '<span class="sbadge sbadge--buy">購入候補</span>',
                '<span class="sbadge sbadge--profit">黒字</span>', '<span class="sbadge sbadge--info">更新が新しい</span>',
                "<b>BUY（週次の判定）</b>", "<b>購入できる（Apple で確認）</b>"):
        mut = h.replace('<div class="hero">', ins + '<div class="hero">', 1)
        assert mut != h
        assert _new(base, _ip_problems(mut, comp)), ins


def test_iphone_top_tile_fresh_heading_is_exempt():
    comp, h = _ip()
    assert 'title="FRESH">更新が新しい</span>' in h and _ip_problems(h, comp) == []


def test_iphone_mutation_hero_value_outside_live():
    comp, h = _ip()
    mut = re.sub(r'(<span title="最高の実行可能買取">最高買取</span>)<b data-fb-live[^>]*>[^<]*</b>', r"\1<b>¥483,000</b>", h, count=1)
    assert mut != h
    _must_fail(_ip_problems(h, comp), _ip_problems(mut, comp), "最高買取")


def _ip_stale_gen_comp():
    """生成時に既に買取が古い（実行可能な最高買取なし・未確認の最高値あり・更新が新しい 0 店）の合成データ。"""
    from tests.test_iphone_hub import _comp, _row, _sku
    r = _row("iPhone Duo 1TB", "a", "店A", 358000, eligible=False, freshness="STALE")
    r["updated_on"] = "2026-11-01"
    s = _sku("iPhone Duo 1TB", hx=None, opp="PASS", rows=[r], unc={"shop": "店A", "price": 358000, "status": "ONE_SOURCE"})
    return _comp([s])


def test_iphone_stale_at_generation_reference_display_passes():
    """生成時 STALE: プレースホルダ・『確認待ち』の未確認最高値・『うち更新が新しい 0 店』が live の外にあっても合格。"""
    comp = _ip_stale_gen_comp()
    h = ip_pg.render(comp, now=D0)
    assert "確認待ち" in h and "うち更新が新しい 0 店" in h
    assert _ip_problems(h, comp) == []


def test_iphone_stale_at_generation_fresh_looking_values_still_fail():
    comp = _ip_stale_gen_comp()
    h = ip_pg.render(comp, now=D0)
    base = _ip_problems(h, comp)
    # 確認待ちの明示を外して金額だけ出す・純利益や ROI の数字を出す・N>0 の更新が新しい店数を出す → 不合格
    muts = [(re.sub(r'<b class="warn">確認待ち</b><em>最高値[^<]*¥358,000.*?</em></div>', "<b>¥358,000</b><em>店A</em></div>", h, count=1, flags=re.S), "最高買取"),
            (h.replace('<span>ROI</span><b>—</b>', '<span>ROI</span><b>9.0%</b>', 1), "ROI"),
            (h.replace('<span>純利益</span><b class="">—</b>', '<span>純利益</span><b class="pos">+¥11,400</b>', 1), "純利益"),
            (h.replace("うち更新が新しい 0 店", "うち更新が新しい 2 店", 1), "更新が新しい")]
    for mut, needle in muts:
        assert mut != h, needle
        _must_fail(base, _ip_problems(mut, comp), needle)


def test_iphone_mutation_buy_live_missing_apple_observation():
    comp, h = _ip()
    mut = re.sub(r'<span data-fb-live data-fb-group="s1-os"[^>]*max="48"[^>]*hidden>(BUY（週次の判定）)</span>', r"\1", h)
    assert mut != h
    _must_fail(_ip_problems(h, comp), _ip_problems(mut, comp), "Apple 側の両方")


def test_iphone_page_code_must_not_hardcode_192_or_le_7():
    assert dc.iphone_page_source_problems("x = 1  # 192 時間\n'''<= 7'''\n") == []                    # コメント・文字列は見ない
    assert dc.iphone_page_source_problems("H = 192\n")
    assert dc.iphone_page_source_problems("def f(d):\n    return d <= 7\n")
    assert dc.iphone_page_source_problems((ROOT / "src" / "content" / "iphone_buyback_page.py").read_text(encoding="utf-8")) == []


def test_iphone_js_and_css_required():
    comp, h = _ip()
    from src.tcg import runtime_freshness as rf
    _must_fail(_ip_problems(h, comp), _ip_problems(h.replace(rf.JS_FRESHNESS, ""), comp), "JS")
    _must_fail(_ip_problems(h, comp), _ip_problems(h.replace("[data-fb-live][hidden]", "[x]"), comp), "CSS")


# ---------------------------------------------------------------- #895 HOME
NOW_MS = int(H.NOW.timestamp() * 1000)


def _home_root(ctx):
    return shell.render_root(ctx)


def _cam_ctx(**kw):
    return H._ctx(home_feed_data={"camera": H._cam([H._route()])}, **kw)


def test_home_green_camera_card_passes_and_is_counted():
    probs, n = dc.check_home_runtime_cards(_home_root(_cam_ctx()), NOW_MS)
    assert probs == [] and n == 1


def test_home_green_iphone_card_has_deadline_note():
    root = _home_root(H._ctx(home_feed_data={"iphone": H._iphone([H._sku()])}))
    probs, n = dc.check_home_runtime_cards(root, NOW_MS)
    assert n == 1 and probs == []


def test_home_green_iphone_card_attrs_are_checked():
    root = _home_root(H._ctx(home_feed_data={"iphone": H._iphone([H._sku()])}))
    probs, n = dc.check_home_runtime_cards(root, NOW_MS)
    assert n == 1 and not any("data-nu-pd-until" in x or "過去" in x or "差し替え" in x for x in probs)     # 期限属性・差し替え文言・JS は問題なし


def test_home_zero_green_cards_still_checks_schema_and_reports_zero():
    root = _home_root(H._ctx())
    probs, n = dc.check_home_runtime_cards(root, NOW_MS)
    assert n == 0 and probs == []                                              # 緑 0 件でも JS のスキーマは検査される（下の変異で落ちる）
    _must_fail(probs, dc.check_home_runtime_cards(root.replace("更新待ち（取得日つきの参考）", "x"), NOW_MS)[0], "差し替える JS")
    _must_fail(probs, dc.check_home_runtime_cards(root.replace("nu-fc__profit", "nu-fc__x"), NOW_MS)[0], "差し替える JS")


def test_home_detects_green_card_attribute_schema_on_synthetic_html():
    """緑のカードが無い本番でも、検査関数が緑カードの期限属性を検出できる（合成 HTML）。"""
    root = _home_root(_cam_ctx())
    base = dc.check_home_runtime_cards(root, NOW_MS)[0]
    nu = re.sub(r' data-nu-pd-until="\d+"', "", root)
    _must_fail(base, dc.check_home_runtime_cards(nu, NOW_MS)[0], "期限（data-nu-pd-until）が無い")
    past = dc.check_home_runtime_cards(root, NOW_MS + 10 * 86400 * 1000)[0]        # 生成時刻より後（期限切れ）に見える
    _must_fail(base, past, "過去")
    nonote = re.sub(r"購入候補は [^<]*までの確認です[^<]*", "", root)
    _must_fail(base, dc.check_home_runtime_cards(nonote, NOW_MS)[0], "注記が無い")
    nostale = root.replace(' data-nu-pd-stale-text="更新待ち"', "")
    _must_fail(base, dc.check_home_runtime_cards(nostale, NOW_MS)[0], "差し替え文言")


def test_home_none_in_buy_untils_is_rejected_but_tcg_inf_is_allowed():
    """Camera・iPhone の購入候補で期限が無いもの（生成側が "none" にする）は不合格。TCG など期限の無い購入可の "inf" は許容。"""
    root = _home_root(_cam_ctx())
    m = re.search(r'data-nu-buy-untils="([^"]*)"', root)
    assert m and "none" not in m.group(1)
    bad = root.replace(m.group(0), f'data-nu-buy-untils="{m.group(1)},none"')
    _must_fail(dc.check_home_runtime_cards(root, NOW_MS)[0], dc.check_home_runtime_cards(bad, NOW_MS)[0], "none")
    ok = root.replace(m.group(0), f'data-nu-buy-untils="{m.group(1)},inf"')
    assert dc.check_home_runtime_cards(ok, NOW_MS)[0] == dc.check_home_runtime_cards(root, NOW_MS)[0]


def test_home_non_green_and_tcg_cards_are_not_counted():
    cond = H._route(profit_status="CONDITIONAL", decision="WATCH", conditional=[{"profit": 30000, "blockers": ["stamp"]}])
    root = _home_root(H._ctx(home_feed_data={"camera": H._cam([cond])}))
    assert dc.check_home_runtime_cards(root, NOW_MS) == ([], 0)


# ---------------------------------------------------------------- deploy_check 全体への組み込み
def test_check_function_is_wired_into_check_and_numbers_are_unique_to_this_block():
    src = (ROOT / "scripts" / "deploy_check.py").read_text(encoding="utf-8")
    assert "_check_runtime_freshness_cam_iphone_home()" in src
    for no in (893, 894, 895):
        assert len(re.findall(rf"_add\({no}, ", src)) == 1


def test_wrapper_returns_three_results_on_real_docs_only_when_pages_exist():
    res = dc._check_runtime_freshness_cam_iphone_home()
    assert {r["check"] for r in res} <= {"camera_runtime_freshness", "iphone_runtime_freshness", "home_runtime_cards"}


def _home_wrapper(tmp_path, monkeypatch, html, mtime=None):
    import os
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    if mtime is not None:
        os.utime(tmp_path / "index.html", (mtime, mtime))
    monkeypatch.setattr(dc, "PUBLIC_DIR", tmp_path)
    return [r for r in dc._check_runtime_freshness_cam_iphone_home() if r["check"] == "home_runtime_cards"]


def test_home_895_uses_embedded_generation_time_not_file_mtime(tmp_path, monkeypatch):
    """L1: 期限が過ぎた後に clone・pull（ファイルの更新時刻が新しい）しても、生成時刻は HTML の値。更新時刻が違っても結果は同じ。"""
    root = _home_root(_cam_ctx())
    old = _home_wrapper(tmp_path, monkeypatch, root, mtime=1_000_000_000)                  # 2001 年
    new = _home_wrapper(tmp_path, monkeypatch, root, mtime=4_000_000_000)                  # 2096 年（期限より後の clone）
    assert [r["level"] for r in old] == ["ok"] and old == new


def test_home_895_fails_when_generation_time_is_missing_or_unreadable(tmp_path, monkeypatch):
    root = _home_root(_cam_ctx())
    stripped = re.sub(r' data-nu-generated-at="[^"]*"', "", root)
    res = _home_wrapper(tmp_path, monkeypatch, stripped)
    assert res and res[0]["level"] == "error" and "生成時刻" in res[0]["message"]
    naive = re.sub(r'(data-nu-generated-at="[^"+]*)\+09:00', r"\1", root)
    assert naive != root
    assert _home_wrapper(tmp_path, monkeypatch, naive)[0]["level"] == "error"


@pytest.mark.parametrize("bad", ["abc", None, float("nan"), float("inf"), -1, True])
def test_iphone_hours_unreadable_config_fails_the_check_without_exception(bad):
    comp, h = _ip()
    for key in ("page_buy_days", "apple_availability_days"):
        cfg = {**IP_CFG, "freshness": {**IP_CFG["freshness"], key: bad}}
        assert dc._iphone_hours(cfg) is None
        out = dc.check_iphone_runtime_freshness(h, comp, cfg)
        assert out and all("設定" in x and "不合格" in x for x in out)
    for cfg in ({}, {"freshness": {}}, {"freshness": {"page_buy_days": 7}}, None):      # 既定値を持たない
        assert dc._iphone_hours(cfg) is None


@pytest.mark.parametrize("bad", ["abc", None, float("nan"), -1])
def test_camera_hours_unreadable_config_fails_the_check_without_default(bad):
    for key in ("stock_days", "executable_days"):
        cfg = {**CAM_CFG, "freshness": {**CAM_CFG["freshness"], key: bad}}
        assert dc._cam_hours(cfg) is None
        out = dc.check_camera_runtime_freshness("<html></html>", {}, cfg)
        assert len(out) == 1 and "設定" in out[0] and "不合格" in out[0]
    assert dc._cam_hours({}) is None and dc._cam_hours({"freshness": {"stock_days": 2}}) is None
    assert dc._cam_hours(CAM_CFG) is not None


# ---------------------------------------------------------------- TCG #852・#853（商品カード tcard）
from src.tcg import runtime_freshness as _rf  # noqa: E402
from tests import test_tcg_cards as TC  # noqa: E402

_TCG_OBS = {TC.NOW.replace(microsecond=0).isoformat()}
_TCG_MX, _TCG_FUT = _rf.thresholds(TC.CFG2)


@pytest.fixture
def tcg_html(monkeypatch):
    rows = TC.ROWS + [TC.row(price=9500, jan=TC.SOLO_JAN)]
    return TC._html(TC._build(rows, [TC._ev("deck", "デッキセット", 1)], monkeypatch=monkeypatch))


def _t853(html, obs_by_pid=None):
    return dc.check_tcg_page_runtime_freshness(html, _TCG_MX, _TCG_FUT, _TCG_OBS, obs_by_pid)


def _t852(html):
    return dc.check_tcg_profit_evidence(html)[0]


def _sub_card(html: str, key: str, fn) -> str:
    """指定カード（data-card-key）の HTML だけに fn を当てる。"""
    m = re.search(r'<article class="tcard"[^>]*data-card-key="%s"' % re.escape(key), html)
    end = html.index("</article>", m.start()) + 10
    return html[:m.start()] + fn(html[m.start():end]) + html[end:]


def _li(card: str, kind: str) -> str:
    return re.search(r"<li data-strip-%s>.*?</li>" % kind, card, re.S).group(0)


def test_tcg_clean_page_passes_both_checks(tcg_html):
    assert _t853(tcg_html) == []
    bad, info = dc.check_tcg_profit_evidence(tcg_html)
    assert bad == [] and info["cards"] >= 2 and info["best"] >= 2 and info["profit"] >= 2


def test_tcg_853_obs_by_product_is_checked(tcg_html):
    assert _t853(tcg_html, {"deck": _TCG_OBS, "solo": _TCG_OBS}) == []
    bad = _t853(tcg_html, {"deck": {"2020-01-01T00:00:00+09:00"}})
    assert any("POKEMON:deck" in x and "元データ" in x for x in bad)


def test_tcg_853_mutation_attrs_removed(tcg_html):
    h = _strip_fb_attrs(tcg_html)
    bad = _t853(h)
    assert bad and any("live の外" in x for x in bad), bad


def test_tcg_853_mutation_hidden_removed(tcg_html):
    h = re.sub(r'(<span data-fb-live[^>]*?) hidden>', r"\1>", tcg_html, count=1)          # 先頭の鮮度判定の live から hidden を外す（応募期限の data-rb-expired の hidden とは別）
    assert h != tcg_html and any("hidden が無い" in x for x in _t853(h))


def test_tcg_853_mutation_stale_hidden(tcg_html):
    h = re.sub(r"(<span data-fb-stale [^>]*)>", r"\1 hidden>", tcg_html, count=1)
    assert any("最初から hidden" in x for x in _t853(h))


def test_tcg_853_mutation_obs_not_offset_iso_or_not_from_source(tcg_html):
    h = tcg_html.replace('data-fb-obs="2026-11-21T18:00:00+09:00"', 'data-fb-obs="2026-11-21 18:00"', 1)
    assert any("観測時刻" in x for x in _t853(h))
    h2 = tcg_html.replace('data-fb-obs="2026-11-21T18:00:00+09:00"', 'data-fb-obs="2026-11-25T09:00:00+09:00"', 1)
    assert any("元データ" in x for x in _t853(h2))


def test_tcg_853_mutation_threshold_differs_from_config(tcg_html):
    h = tcg_html.replace('data-fb-max="36"', 'data-fb-max="9999"', 1)
    assert any("しきい値" in x for x in _t853(h))
    h2 = tcg_html.replace('data-fb-fut="5"', 'data-fb-fut="999"', 1)
    assert any("data-fb-fut" in x for x in _t853(h2))


@pytest.mark.parametrize("kind", ["best", "profit", "diff"])
def test_tcg_853_mutation_strip_amount_outside_live(tcg_html, kind):
    def fn(card):
        li = _li(card, kind)
        inner = re.search(r"<span data-fb-live[^>]*>(.*?)</span><span data-fb-stale", li, re.S).group(1)
        return card.replace(li, li.replace(re.search(r"<span data-fb-live[^>]*>.*?</span>(?=<span data-fb-stale)", li, re.S).group(0), inner))
    h = _sub_card(tcg_html, "POKEMON:deck", fn)
    bad = _t853(h)
    assert any("live の外" in x for x in bad), bad


def test_tcg_853_mutation_best_price_leaks_next_to_live(tcg_html):
    # strip の外（カードの別の場所）への漏れは、利益・黒字・符号付きの金額で検出する
    h2 = _sub_card(tcg_html, "POKEMON:deck", lambda c: c.replace('<div class="tc-img">', '<div class="tc-img"><p>純利益 +1,800円</p>', 1))
    assert any("live の外" in x for x in _t853(h2))
    h3 = _sub_card(tcg_html, "POKEMON:deck", lambda c: c.replace('<div class="tc-img">', '<div class="tc-top" title="利益 +1,800円">', 1))
    assert any("属性" in x for x in _t853(h3))


def test_tcg_853_mutation_other_shop_price_outside_live(tcg_html):
    def fn(card):
        m = re.search(r'<li data-other-shop="[^"]*" data-other-kind="[^"]*">.*?</li>', card, re.S)
        li = m.group(0)
        live = re.search(r"<span data-fb-live[^>]*>(.*?)</span><span data-fb-stale", li, re.S)
        return card.replace(li, li.replace(live.group(0).split("<span data-fb-stale")[0], live.group(1)))
    bad = _t853(_sub_card(tcg_html, "POKEMON:deck", fn))
    assert any("live の外" in x for x in bad), bad


def test_tcg_853_mutation_stale_pair_broken(tcg_html):
    h = re.sub(r'<span data-fb-stale data-fb-group="[pc]\d+-b"', '<span data-fb-stale data-fb-group="zzz"', tcg_html, count=1)
    bad = _t853(h)
    assert any("対になる live が無い" in x or "対になっていない" in x or "対の再確認待ち" in x for x in bad), bad


def test_tcg_853_mutation_live_without_any_stale(tcg_html):
    h = re.sub(r'<span data-fb-stale data-fb-group="c\d+-o0"[^>]*>.*?</span></span>|<span data-fb-stale data-fb-group="[^"]*-o0"[^>]*>.*?</span>', "", tcg_html, count=1, flags=re.S)
    assert any("対になっていない" in x or "対の再確認待ち" in x for x in _t853(h))


def test_tcg_853_mutation_other_rows_share_a_group(tcg_html):
    def fn(card):
        assert re.search(r'data-fb-group="[^"]*-o\d+"', card)
        return re.sub(r'data-fb-group="[^"]*-o\d+"', 'data-fb-group="%s"' % re.search(r'id="([pc]\d+)"', card).group(1), card)
    bad = _t853(_sub_card(tcg_html, "POKEMON:deck", fn))
    assert any("同じ group を共有" in x for x in bad), bad


def test_tcg_853_mutation_nested_div_or_span_inside_live(tcg_html):
    h = re.sub(r'(<b class="amt[^"]*">¥9,500</b>)', r'<span class="x">\1</span>', tcg_html, count=1)
    assert h != tcg_html and any("入れ子" in x for x in _t853(h))
    h2 = re.sub(r'(<b class="amt[^"]*">¥9,500</b>)', r'<div>\1</div>', tcg_html, count=1)
    assert any("入れ子" in x for x in _t853(h2))


def test_tcg_853_mutation_old_structure_dt_without_live(tcg_html):
    h = tcg_html.replace("</main>", '<section class="pcard"><div><dt>最高買取</dt><dd>¥9,000</dd></div></section></main>', 1)
    bad = _t853(h)
    assert any("鮮度の判定なしで" in x for x in bad) and any("旧構造" in x for x in bad), bad


def test_tcg_853_mutation_js_missing_or_twice_or_css_missing(tcg_html):
    assert any("JS" in x for x in _t853(tcg_html.replace(_rf.JS_FRESHNESS, "")))
    assert any("JS" in x for x in _t853(tcg_html.replace("</body>", f"<script>{_rf.JS_FRESHNESS}</script></body>")))
    assert any("CSS" in x for x in _t853(tcg_html.replace("[data-fb-live][hidden]", "[x]")))


def test_tcg_853_mutation_best_live_removed_outlier_row_with_price_and_msrp_live(tcg_html):
    h = _sub_card(tcg_html, "POKEMON:deck", lambda c: c.replace(_li(c, "best"), re.sub(r"<span data-fb-live[^>]*>", "<span>", _li(c, "best"), count=1)))
    assert any("live の外" in x for x in _t853(h))
    h2 = _sub_card(tcg_html, "POKEMON:deck", lambda c: c.replace("<li data-strip-msrp>", "<li data-strip-msrp><span data-fb-live data-fb-group=\"c0\" data-fb-obs=\"2026-11-21T18:00:00+09:00\" data-fb-max=\"36\" data-fb-fut=\"5\" hidden></span>", 1))
    assert any("公式定価に live" in x for x in _t853(h2))


def test_tcg_853_profit_and_badge_obs_must_agree(tcg_html):
    other = "2026-11-21T17:00:00+09:00"
    obs = _TCG_OBS | {other}

    def fn(card):
        return card.replace(re.search(r'(<span data-fb-live data-fb-group="[^"]*" )data-fb-obs="[^"]*"', card).group(0),
                            re.search(r'(<span data-fb-live data-fb-group="[^"]*" )', card).group(1) + f'data-fb-obs="{other}"', 1)
    h = _sub_card(tcg_html, "POKEMON:solo", fn)       # 先頭の live（状態バッジ）だけ別の取得時刻
    bad = dc.check_tcg_page_runtime_freshness(h, _TCG_MX, _TCG_FUT, obs)
    assert any("sell_observed_at" in x for x in bad), bad


def test_tcg_853_outlier_row_must_not_show_a_price(monkeypatch):
    h = TC._html(TC._build([TC.row(price=30000, jan=TC.DECK_JAN)], monkeypatch=monkeypatch))
    assert _t853(h) == []
    assert re.search(r"<li data-strip-best>.*?<small>確認待ち</small>", h, re.S)          # 外れ値: 最高買取は「確認待ち」だけ（価格を出さない）
    h2 = _sub_card(h, "POKEMON:deck", lambda c: c.replace(_li(c, "best"), _li(c, "best").replace('<b class="amt na">—</b>', '<b class="amt na">— ¥30,000 ROI 5%</b>', 1)))
    assert h2 != h and any("live の外" in x for x in _t853(h2))


def test_tcg_853_rb_card_old_checks_are_kept():
    # 販売店 BOX 価格（_rb_card）の行は旧形式（<div live><dt>）のまま。live の付け忘れを検出する
    ok = '<div data-fb-live data-fb-group="rb0" data-fb-obs="2026-11-21T18:00:00+09:00" data-fb-max="36" data-fb-fut="5" hidden><dt>最高買取</dt><dd>¥1</dd></div>'
    ng = ok.replace("data-fb-live ", "").replace(" hidden", "")
    def page(body):
        return "<style>[data-fb-live][hidden]{}</style><main>" + body + "</main><script>" + _rf.JS_FRESHNESS + "</script>"
    assert not any("鮮度の判定なしで" in x for x in _t853(page(ok)))
    assert any("鮮度の判定なしで" in x for x in _t853(page(ng)))


# ---- #852
def test_tcg_852_zero_cards_is_ok_only_when_there_are_no_products():
    bad, info = dc.check_tcg_profit_evidence("<style>.tcard{}</style><main></main>")
    assert bad == [] and info["cards"] == 0                           # 商品が 0 件の入力（空の HTML）だけ「対象なし」で合格
    bad2, _ = dc.check_tcg_profit_evidence("<main><p>商品なし</p></main>")
    assert bad2 == []
    bad3, _ = dc.check_tcg_profit_evidence('<main><h2 id="opportunities">商品と利益（0）</h2></main>')
    assert bad3 == []
    bad4, _ = dc.check_tcg_profit_evidence("<style>.tcard{}</style><main></main>", 3)         # 元データに商品があるのにカード 0 枚（CSS の tcard では合格しない）
    assert any("0 枚" in x for x in bad4)


def test_tcg_852_853_mutation_card_class_renamed_or_articles_removed(tcg_html):
    renamed = tcg_html.replace('<article class="tcard"', '<article class="tc2"')
    assert renamed != tcg_html and ".tcard{" in renamed                                      # CSS には tcard が残っている（旧検査はこれで合格していた）
    gone = re.sub(r"<article class=\"tcard\".*?</article>", "", tcg_html, flags=re.S)
    assert "<article" not in gone
    for h in (renamed, gone):
        b852, i852 = dc.check_tcg_profit_evidence(h)
        assert i852["cards"] == 0 and any("見出しの商品数" in x or "0 枚" in x for x in b852), b852
        assert any("見出しの商品数" in x or "0 枚" in x for x in _t853(h)), _t853(h)
    # 呼び出し側が元データの商品数を渡す場合（見出しも消えた HTML でも空振りしない）
    bare = re.sub(r'<h2 id="opportunities">.*?</h2>', "", gone)
    assert any("0 枚" in x for x in dc.check_tcg_profit_evidence(bare, 1)[0])
    assert any("0 枚" in x for x in dc.check_tcg_page_runtime_freshness(bare, _TCG_MX, _TCG_FUT, _TCG_OBS, None, 1))
    assert dc.check_tcg_profit_evidence(bare, 0)[0] == []                                    # 商品が無い入力は対象なしで合格


def test_tcg_852_853_mutation_one_card_dropped_is_caught_by_heading_count(tcg_html):
    one = re.sub(r"<article class=\"tcard\"[^>]*data-card-key=\"POKEMON:solo\".*?</article>", "", tcg_html, count=1, flags=re.S)
    assert one != tcg_html
    assert any("見出しの商品数" in x for x in dc.check_tcg_profit_evidence(one)[0])
    assert any("見出しの商品数" in x for x in _t853(one))


def test_tcg_853_suspended_small_still_detects_money_and_roi(tcg_html):
    """停止行の <small>（店のページ由来）でも、¥・符号つきの金額・ROI・約N万円は検出する。日本語の文中の数字+円は許す。"""
    base = _sub_card(tcg_html, "POKEMON:deck", lambda c: re.sub(r'(<li data-other-shop="[^"]*" data-other-kind=")[^"]*(">)', r'\1suspended\2', c, count=1))

    def with_text(txt):
        h = re.sub(r'(data-other-kind="suspended">.*?)(</li>)', lambda m: m.group(1) + f'<span class="tc-val"><small>お申込一時停止中{txt}</small></span>' + m.group(2), base, count=1, flags=re.S)
        assert h != base
        return h
    for ok in ("・1,000円以上のみ受付停止", "・0 円にしない", "・5,800円未満は不可"):
        assert not any("買取停止の行" in x for x in _t853(with_text(ok))), ok
    for ng in ("・¥12,000", "・￥12000", "・+12,000円", "・ROI 12.0%", "・約1万円"):
        assert any("買取停止の行" in x for x in _t853(with_text(ng))), ng


def test_tcg_852_mutation_old_structure_returns(tcg_html):
    old = tcg_html.replace('<article class="tcard"', '<section class="pcard"').replace("</article>", "</section>")
    bad = _t852(old)
    assert any("旧構造" in x for x in bad)
    only_old = '<section class="pcard"><div><dt>純利益</dt></div><dt>最高買取</dt></section>'
    assert any("旧構造" in x or "痕跡" in x for x in _t852(only_old))


def test_tcg_852_mutation_best_live_removed_profit_without_best(tcg_html):
    h = _sub_card(tcg_html, "POKEMON:deck", lambda c: c.replace(_li(c, "best"), re.sub(r"<span data-fb-live[^>]*>", "<span>", _li(c, "best"), count=1)))
    assert any("最高買取" in x for x in _t852(h))


def test_tcg_852_mutation_profit_without_msrp(tcg_html):
    h = _sub_card(tcg_html, "POKEMON:deck", lambda c: c.replace(_li(c, "msrp"), "<li data-strip-msrp><em>公式定価</em><span class=\"tc-val\"><b class=\"amt\">未確認</b></span></li>"))
    assert any("公式定価" in x for x in _t852(h))


def test_tcg_852_mutation_best_without_profit_or_reason(tcg_html):
    h = _sub_card(tcg_html, "POKEMON:deck", lambda c: c.replace(_li(c, "profit"), '<li data-strip-profit><em>利益</em></li>'))
    assert any("対応する利益または理由" in x for x in _t852(h))


def test_tcg_852_best_with_reason_and_no_profit_passes(monkeypatch):
    master = [TC._master("deck", "デッキセット"), TC._master("box", "拡張パック BOX", "BOOSTER_BOX", "2026-12-05", pack_price=180, retail_price_basis="pack")]
    h = TC._html(TC._build([TC.row(price=14000, jan=TC.BOX_JAN, name="拡張パック BOX [M6]")], master=master, msrp=[], monkeypatch=monkeypatch))
    bad, info = dc.check_tcg_profit_evidence(h)
    assert bad == [] and info["best"] == 0 and info["profit"] == 0     # 定価が 1 パックだけ: 単位違いで最高買取の欄に金額を出さない・利益も出さない
    assert _t853(h) == []


def test_tcg_852_853_wired_into_check_and_old_inline_regexes_are_gone():
    src = (ROOT / "scripts" / "deploy_check.py").read_text(encoding="utf-8")
    assert "check_tcg_profit_evidence(" in src and "check_tcg_page_runtime_freshness(" in src
    assert "split('<section class=\"pcard\"')" not in src


# ---- #853 独立レビュー L1（検査の穴）と M2（group の新規則）
@pytest.mark.parametrize("where,anchor", [
    ("tc-img", '<div class="tc-img">'),
    ("抽選欄", '<div class="tc-lot" data-lot>'),
    ("他店の行", '<li data-other-shop="rudeya"'),
])
@pytest.mark.parametrize("money", ["¥9,000", "￥9,000", "約1万円", "ROI 5%", "9,000円", "￥ 5800", "+1,800円"])   # 数字のない ￥ だけは金額ではない（L3 で金額の検出を ¥+数字 に限定）
def test_tcg_853_money_outside_live_anywhere_in_the_card_is_caught(tcg_html, where, anchor, money):
    """金額表記（¥・￥・円・%・約N万円）は、カード内の live の外のどこにも置けない（定価の行と商品名・抽選の店名だけ許可）。"""
    def fn(card):
        assert anchor in card, anchor
        if anchor.startswith("<li"):                                              # 他店の <li ...> の開始タグの直後
            return re.sub(r'(<li data-other-shop="rudeya"[^>]*>)', rf"\1<p>{money}</p>", card, count=1)
        return card.replace(anchor, anchor + f"<p>{money}</p>", 1)
    h = _sub_card(tcg_html, "POKEMON:deck", fn)
    assert h != tcg_html and any("live の外" in x for x in _t853(h)), (where, money)


def test_tcg_853_allowed_money_texts_pass_msrp_row_product_name_lottery_shop(tcg_html):
    assert _t853(tcg_html) == []
    named = _sub_card(tcg_html, "POKEMON:deck", lambda c: c.replace("<h3>デッキセット</h3>", "<h3>デッキセット 500円記念 100%</h3>", 1))
    assert _t853(named) == []                                                   # 商品名は許可
    card = re.search(r'<article class="tcard".*?</article>', tcg_html, re.S).group(0)
    assert "¥" in _li(card, "msrp")                                              # 定価の行には金額がある（許可リスト）


def test_tcg_853_best_only_stale_removed_is_caught_even_if_other_stale_remains(tcg_html):
    def fn(card):
        m = re.search(r'<span data-fb-stale data-fb-group="[^"]*-b"[^>]*>.*?</small></span>', card, re.S)
        assert m
        return card.replace(m.group(0), "", 1)
    h = _sub_card(tcg_html, "POKEMON:deck", fn)
    assert h != tcg_html and any("直後に、同じ group の再確認待ち" in x for x in _t853(h)), _t853(h)


def test_tcg_853_diff_note_and_not_the_highest_note_are_required(tcg_html):
    h = _sub_card(tcg_html, "POKEMON:deck", lambda c: c.replace(_li(c, "diff"), _li(c, "diff").replace("・費用未確認", "")))
    assert h != tcg_html and any("費用未確認" in x for x in _t853(h))
    h2 = _sub_card(tcg_html, "POKEMON:deck", lambda c: c.replace("<small>参考</small>", "<small>参考です</small>"))
    assert h2 != tcg_html and any("最高買取にしない" in x for x in _t853(h2))
    h3 = _sub_card(tcg_html, "POKEMON:deck", lambda c: re.sub(r'<li data-strip-diff>.*?</li>', "", c, count=1, flags=re.S))
    assert not any("費用未確認" in x for x in _t853(h3))                        # 差額の行が無ければ（基準店が最高買取の店）ラベルは要らない


def test_tcg_853_group_rules_best_diff_vs_profit_badge_vs_other(tcg_html):
    # 最高買取・差額と利益・状態バッジを同じ group にすると不合格（片方だけ期限切れのとき表示と再確認待ちが食い違う）
    h = re.sub(r'data-fb-group="([pc]\d+)-b"', r'data-fb-group="\1-p"', _sub_card(tcg_html, "POKEMON:deck", lambda c: c))
    assert any("group を共有" in x for x in _t853(h))
    # 最高買取と差額が別 group
    h2 = _sub_card(tcg_html, "POKEMON:deck", lambda c: c.replace(_li(c, "diff"), _li(c, "diff").replace("-b\"", "-x\"")))
    assert any("別の group" in x for x in _t853(h2))
    # 利益と状態バッジの obs が違う
    other = "2026-11-21T17:00:00+09:00"
    h3 = _sub_card(tcg_html, "POKEMON:solo", lambda c: re.sub(r'(data-fb-group="[^"]*-p" )data-fb-obs="[^"]*"', rf'\1data-fb-obs="{other}"', c, count=1))
    assert any("sell_observed_at" in x for x in dc.check_tcg_page_runtime_freshness(h3, _TCG_MX, _TCG_FUT, _TCG_OBS | {other}))


# ---- 独立レビュー L1・L2・L3（#852・#853）
def _unlive_badge(card: str) -> str:
    """状態バッジの live ラッパーだけを外す（バッジの文字は残す）。"""
    return re.sub(r'<span data-fb-live[^>]*>(<b class="sb [^"]*">[^<]*</b>)</span>', r"\1", card, count=1)


def _neg_html(monkeypatch):
    """赤字（買取 5,800 < 定価 6,200）のカードがある HTML。"""
    return TC._html(TC._build([TC.row(price=5800, jan=TC.DECK_JAN)], [TC._ev("deck", "デッキセット", 1)], monkeypatch=monkeypatch))


def _watch_html(monkeypatch):
    """様子見（買取 8,000・定価 6,200 で ROI 30% 未満の黒字ではない状態）のカード。"""
    return TC._html(TC._build([TC.row(price=8000, jan=TC.DECK_JAN)], [TC._ev("deck", "デッキセット", 1)], monkeypatch=monkeypatch))


@pytest.mark.parametrize("label", ["赤字", "様子見", "黒字"])
def test_tcg_853_l1_state_badge_outside_live_is_caught(tcg_html, label):
    h = _sub_card(tcg_html, "POKEMON:deck", lambda c: c.replace("<div class=\"tc-img\">", f'<div class="tc-img"><b class="sb warn">{label}</b>', 1))
    assert h != tcg_html and any("live の外" in x and label in x for x in _t853(h)), label


def test_tcg_853_l1_real_negative_and_watch_cards_with_unwrapped_badge_are_caught(monkeypatch):
    for html_fn, word in ((_neg_html, "赤字"), (_watch_html, "様子見")):
        h = html_fn(monkeypatch)
        assert _t853(h) == [], word
        card_key = "POKEMON:deck"
        m = _sub_card(h, card_key, _unlive_badge)
        if word == "赤字":
            assert 'class="sb ls">赤字<' in h, "赤字バッジが無い（前提が崩れた）"
        assert m != h
        bad = _t853(m)
        assert any("live の外" in x and word in x for x in bad), (word, bad)


def test_tcg_852_l2_reason_must_be_a_reason_word_outside_live(monkeypatch):
    # 最高買取（買取商店）と定価はあるが、費用の分かる基準店（ルデヤ）が受付停止 → 利益は「算出前」（理由の語）
    stopped = {**TC.row(price=12000, jan=TC.DECK_JAN), "accept_state": "STOPPED", "suspended_text": "お申込一時停止中"}
    h = TC._html(TC._build([stopped, TC.row(shop="kaitorishouten", price=9000, jan=TC.DECK_JAN, upd="2026-11-21")], monkeypatch=monkeypatch))
    deck = re.search(r'<article class="tcard"[^>]*data-card-key="POKEMON:deck".*?</article>', h, re.S).group(0)
    assert _t852(h) == [] and "算出前" in _li(deck, "profit")
    def drop_reason(card):
        return card.replace(_li(card, "profit"), '<li data-strip-profit><em>利益</em><span class="tc-val"><b class="amt">-</b><small>ご確認ください</small></span></li>')
    h2 = _sub_card(h, "POKEMON:deck", drop_reason)
    assert h2 != h and any("対応する利益または理由" in x for x in _t852(h2))   # 利益欄に文字はあるが、理由の語がない


def test_tcg_852_l2_reason_word_inside_live_or_stale_does_not_count(tcg_html):
    def fn(card):
        return card.replace(_li(card, "profit"), '<li data-strip-profit><em>利益</em><span class="tc-val"><span data-fb-stale data-fb-group="x">算出前</span></span></li>')
    h = _sub_card(tcg_html, "POKEMON:deck", fn)
    assert any("対応する利益または理由" in x for x in _t852(h))


def test_tcg_853_l3_japanese_prose_with_numbers_and_yen_is_not_money(tcg_html):
    for txt in ("費用が不明（不明を 0 円にしない）", "1000円以上のみ受付停止"):
        h = _sub_card(tcg_html, "POKEMON:deck", lambda c, t=txt: c.replace('<div class="tc-img">', f'<div class="tc-img"><p>{t}</p>', 1))
        assert h != tcg_html and _t853(h) == [], txt


def test_tcg_853_l3_suspended_text_is_not_checked_but_a_price_element_still_is(tcg_html):
    def fn(card):
        return re.sub(r'(<li data-other-shop="[^"]*" data-other-kind=")[^"]*(">)', r'\1suspended\2', card, count=1)
    base = _sub_card(tcg_html, "POKEMON:deck", fn)
    ok = re.sub(r'(data-other-kind="suspended">.*?)(</li>)', r'\1<span class="tc-val"><small>1000円以上のみ受付停止・5,800円未満は不可</small></span>\2', base, count=1, flags=re.S)
    assert ok != base and not any("金額" in x and "受付停止" in x for x in _t853(ok))
    price_leak = re.sub(r'(data-other-kind="suspended">.*?)(</li>)', r'\1<b class="amt">¥9,000</b>\2', base, count=1, flags=re.S)
    assert any("live の外" in x and "9,000" in x for x in _t853(price_leak))      # 価格として出ている要素は検査対象のまま


def test_tcg_853_l3_money_regex_still_detects_real_amounts():
    for t in ("¥9,000", "￥5800", "9,000円", "約1万円", "約 2 万円", "+1,800円", "−500円", "ROI 5%", "ROI 12.5％", "1万円"):
        assert dc._TCG_MONEY_RE.search(t), t
    for t in ("費用が不明（不明を 0 円にしない）", "1000円以上のみ受付停止", "ROI の基準", "0 円にしない", "￥"):
        assert not dc._TCG_MONEY_RE.search(t), t


# ---- 2 ページ化（tcg.html / tcg-lottery.html）: 応募ボタン・抽選のページ・相互リンク（#853 に追加した検査）
@pytest.fixture
def tcg_pages(monkeypatch):
    hub = TC._build(TC.ROWS, [TC._ev("deck", "デッキセット", 1), TC._ev("deck", "デッキセット", 2, verified=False)], monkeypatch=monkeypatch)
    return TC._html(hub), TC._lhtml(hub)


def test_tcg_two_pages_pass_the_new_checks(tcg_pages):
    prod, lot = tcg_pages
    assert dc.check_tcg_apply_buttons(prod, "tcg.html") == [] and dc.check_tcg_lottery_page(prod, lot) == []
    assert "公式ページで応募する" in prod and "公式ページで応募する" in lot


def test_tcg_apply_button_on_unverified_or_not_open_row_is_caught(tcg_pages):
    prod, lot = tcg_pages
    btn = '<a class="btn cta" href="https://draw.geo-online.co.jp/lottery/200" target="_blank" rel="noopener nofollow">公式ページで応募する</a>'
    # 未確認の行（data-verified="0"）に応募ボタンを足す
    bad = re.sub(r'(<tr class="ev[^>]*data-verified="0"[^>]*>.*?<span class="btns">)', lambda m: m.group(1) + btn, lot, count=1, flags=re.S)
    assert bad != lot and any("確認済み以外" in x for x in dc.check_tcg_lottery_page(prod, bad))
    # 期限の切り替え（data-rb-open）の外に出す
    out = lot.replace('<span data-rb-open><a class="btn cta"', '<span><a class="btn cta"', 1)
    assert out != lot and any("data-rb-open" in x for x in dc.check_tcg_lottery_page(prod, out))
    # 行の外・ボタン以外の文字として出す
    assert any("行の外" in x for x in dc.check_tcg_apply_buttons(prod.replace("</main>", btn + "</main>"), "tcg.html"))
    assert any("以外に出ている" in x for x in dc.check_tcg_apply_buttons(prod.replace("</main>", "<p>公式ページで応募する</p></main>"), "tcg.html"))


def test_tcg_lottery_page_must_not_carry_money_and_must_link_back(tcg_pages):
    prod, lot = tcg_pages
    assert any("金額" in x for x in dc.check_tcg_lottery_page(prod, lot.replace("</main>", "<p>買取 ¥9,000</p></main>")))
    live = '<span data-fb-live data-fb-group="x" data-fb-obs="2026-11-21T18:00:00+09:00" data-fb-max="36" data-fb-fut="5" hidden>¥1</span>'
    assert any("data-fb-live" in x for x in dc.check_tcg_lottery_page(prod, lot.replace("</main>", live + "</main>")))
    assert any("相互リンク" in x for x in dc.check_tcg_lottery_page(prod, lot.replace('href="tcg.html"', 'href="x.html"')))
    broken = re.sub(r'href="tcg-lottery\.html#L-[^"]+"', 'href="tcg-lottery.html#L-nothing"', prod, count=1)
    assert broken != prod and any("無い行へのリンク" in x for x in dc.check_tcg_lottery_page(broken, lot))
    old = re.sub(r'(<meta name="tcg-source-generated-at" content=")[^"]*', r"\g<1>2020-01-01T00:00:00+09:00", lot, count=1)
    assert any("2 ページで違う" in x for x in dc.check_tcg_lottery_page(prod, old))
    moved = lot.replace('id="calendar"', 'id="cal-x"').replace("</main>", '<h2 id="calendar">x</h2></main>')
    assert any("カレンダー" in x for x in dc.check_tcg_lottery_page(prod, moved))


def test_tcg_852_suspended_only_price_is_not_counted_as_best_and_needs_its_label(monkeypatch):
    stopped = {**TC.row(price=12000, jan=TC.DECK_JAN), "accept_state": "STOPPED", "suspended_text": "お申込一時停止中"}
    h = TC._html(TC._build([stopped], monkeypatch=monkeypatch))
    bad, info = dc.check_tcg_profit_evidence(h)
    assert bad == [] and _t853(h) == []
    deck = re.search(r'<article class="tcard"[^>]*data-card-key="POKEMON:deck".*?</article>', h, re.S).group(0)
    assert "受付停止中" in _li(deck, "best") and "¥" not in _li(deck, "best")
    h2 = h.replace('hidden><small>受付停止中</small>', 'hidden><b class="amt off">¥12,000</b><small>受付停止中</small>', 1)   # 変異: 最高買取の欄に停止中の金額
    assert h2 != h and any("受付停止・単位違いの金額" in x for x in dc.check_tcg_profit_evidence(h2)[0])


def test_tcg_853_new_checks_are_wired_into_check():
    src = (ROOT / "scripts" / "deploy_check.py").read_text(encoding="utf-8")
    assert "check_tcg_apply_buttons(_h853" in src and "check_tcg_lottery_page(_h853" in src and 'PUBLIC_DIR / "tcg-lottery.html"' in src


# ---- 独立レビュー（第 3 回）: 新しい領域の金額漏れ・応募ボタンの行き先・画像の src と onerror（mut.py・mut2.py の変異）
@pytest.mark.parametrize("name,fn", [
    ("rk_profit_text_outside", lambda p: p.replace('<td class="n" data-label="純利益">', '<td class="n" data-label="純利益"><b>+1,000円</b>', 1)),
    ("rk_badge_outside", lambda p: p.replace('<td class="st">', '<td class="st"><b class="sb pf">黒字</b>', 1)),
    ("rk_sell_yen_outside", lambda p: p.replace('<td class="n" data-label="純利益">', '<td class="n" data-label="純利益"><small>買取商店 ¥9,000</small>', 1)),
    ("thumb_money", lambda p: re.sub(r'(<a class="th"[^>]*>.*?<span>)', r"\1¥9,000 ", p, count=1, flags=re.S)),
    ("soon_money", lambda p: p.replace('<section class="soon"', '<section class="soon"><p>利益 +3,000円</p>', 1)),
    ("stale_note_money", lambda p: p.replace("data-stale-note hidden>", "data-stale-note hidden>最高買取 ¥9,000 ", 1)),
    ("rk_state_word_outside", lambda p: p.replace('<td class="st">', '<td class="st">様子見', 1)),
])
def test_tcg_853_money_outside_live_in_new_regions_is_caught(monkeypatch, name, fn):
    """利益ランキング・画像で選ぶ・締切が近い抽選の帯・鮮度切れの注記: live / stale の外の金額・状態バッジを検出する（許可はランキングの定価と商品名だけ）。"""
    hub = TC._build(TC.ROWS, [TC._ev("deck", "デッキセット", 1)], monkeypatch=monkeypatch)
    hub["cards"][0]["image_url"] = None
    html = TC._html(hub)
    assert _t853(html) == []
    bad = fn(html)
    assert bad != html, name
    assert _t853(bad) or dc.check_tcg_profit_evidence(bad)[0], name


def test_tcg_853_allowed_cells_in_the_ranking_pass(monkeypatch):
    html = TC._html(TC._build(TC.ROWS, monkeypatch=monkeypatch))
    assert '<td class="n" data-label="定価">' in html and _t853(html) == []                    # 定価セル（設定値）の金額は許可


def test_tcg_apply_button_href_js_only_and_images_are_checked(tcg_pages):
    prod, lot = tcg_pages
    assert dc.check_tcg_apply_buttons(prod, "tcg.html") == [] and dc.check_tcg_images(prod, "tcg.html") == []
    m = re.search(r'(<a class="btn cta" href=")([^"]+)(")', prod)
    ext = prod.replace(m.group(0), m.group(1) + "http://evil.example.com/x" + m.group(3), 1)
    assert any("公式ドメイン" in x for x in dc.check_tcg_apply_buttons(ext, "tcg.html"))
    other = prod.replace(m.group(0), m.group(1) + "https://evil.example.com/x" + m.group(3), 1)
    assert any("公式ドメイン" in x for x in dc.check_tcg_apply_buttons(other, "tcg.html"))       # https でも小売の公式ドメインでなければ不合格
    nojs = prod.replace(" data-js-only hidden>公式ページで応募する", ">公式ページで応募する", 1)
    assert nojs != prod and any("JS の無いとき" in x for x in dc.check_tcg_apply_buttons(nojs, "tcg.html"))
    howto = prod.replace("</main>", f"<p>{page_mod.APPLY_HOWTO}</p></main>")
    assert any(page_mod.APPLY_HOWTO in x for x in dc.check_tcg_apply_buttons(howto, "tcg.html"))
    early = prod.replace("<span data-rb-expired hidden>", "<span data-rb-expired>", 1)
    assert early != prod and any("data-rb-expired" in x for x in dc.check_tcg_apply_buttons(early, "tcg.html"))


def test_tcg_images_src_and_onerror_are_checked(monkeypatch):
    from tests._image_permit import permit_all
    ok = ('<div class="pimg pokemon"><img src="https://www.pokemon-card.com/x.jpg" alt="x" onerror="' + _html_attr(page_mod.IMG_ONERROR) + '"></div>'
          '<div class="pimg onepiece"><img src="https://www.onepiece-cardgame.com/x.png" alt="y" onerror="' + _html_attr(page_mod.IMG_ONERROR) + '"></div>')
    assert len(dc.check_tcg_images(ok, "x")) == 2                       # 権利者の利用許可の記録が無い公式画像は不可（本番の記録は空）
    permit_all(monkeypatch)
    assert dc.check_tcg_images(ok, "x") == []
    assert any("src" in x for x in dc.check_tcg_images(ok.replace("www.pokemon-card.com", "evil.example.com", 1), "x"))
    assert any("src" in x for x in dc.check_tcg_images(ok.replace("www.onepiece-cardgame.com", "www.pokemon-card.com", 1), "x"))   # TCG とホストの食い違い
    assert any("src" in x for x in dc.check_tcg_images(ok.replace("x.png", "noimage.png", 1), "x"))
    assert any("onerror" in x for x in dc.check_tcg_images(ok.replace('onerror="var p', 'onerror="fetch(1);var p', 1), "x"))


def _html_attr(s: str) -> str:
    import html as _h
    return _h.escape(s, quote=True)


from src.content import tcg_hub_page as page_mod  # noqa: E402



def test_tcg_853_fake_best_in_a_card_without_buyback_rows_is_caught_with_obs_by_pid(monkeypatch):
    """【Reviewer Low-4】元データに買取の行が無い商品のカードに、偽の最高買取（live）を差し込むと検出する（obs_by_pid 付き）。
    「—」と金額の両方が最高買取の欄にある形も、obs_by_pid が無くても検出する。"""
    stopped = {**TC.row(price=12000, jan=TC.DECK_JAN), "accept_state": "STOPPED", "suspended_text": "お申込一時停止中"}
    h = TC._html(TC._build([stopped], monkeypatch=monkeypatch))
    by_pid = {"deck": _TCG_OBS}
    assert _t853(h, by_pid) == []
    box = re.search(r'<article class="tcard"[^>]*data-card-key="POKEMON:box".*?</article>', h, re.S).group(0)
    gid = re.search(r'id="([^"]+)"', box).group(1)
    obs = next(iter(_TCG_OBS))
    fake = (f'<span data-fb-live data-fb-group="{gid}-b" data-fb-obs="{obs}" data-fb-max="{_TCG_MX:g}" data-fb-fut="{_TCG_FUT:g}" hidden>'
            f'<b class="amt">¥12,000</b></span><span data-fb-stale data-fb-group="{gid}-b" data-fb-max="{_TCG_MX:g}">再確認待ち</span>')
    h2 = _sub_card(h, "POKEMON:box", lambda c: c.replace(_li(c, "best"), _li(c, "best").replace("</span></li>", fake + "</span></li>", 1)))
    assert h2 != h
    assert any("元データ（buyback.json）の買取の行が無い" in x for x in _t853(h2, by_pid))
    assert any("「—」と金額" in x for x in dc.check_tcg_profit_evidence(h2)[0])


def test_tcg_853_ranking_allows_only_the_product_name_link(monkeypatch):
    """【Reviewer Low-1】利益ランキングで許すのは商品名のリンクの文字と公式定価のセルだけ（td.nm の中のほかの要素は許さない）。"""
    html = TC._html(TC._build(TC.ROWS, monkeypatch=monkeypatch))
    assert _t853(html) == []
    roi = html.replace('<td class="nm">', '<td class="nm"><small>ROI 30%</small>', 1)
    assert roi != html and any("利益ランキング" in x for x in _t853(roi))
    named = re.sub(r'(<td class="nm"><a [^>]*>)', r"\1500円記念 ", html, count=1)
    assert named != html and _t853(named) == []                                            # 商品名のリンクの中の数字+円は許可

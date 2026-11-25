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

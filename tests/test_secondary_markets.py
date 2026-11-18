"""二次流通の取得可否・手数料の状態・ルート C/D・secondary_refresh（資格情報の値は出さない・未取得を 0 件にしない）。"""
from __future__ import annotations

import copy
import json

import pytest

from src.research import camera_refresh as cf
from src.research import camera_routes as cr
from src.research import secondary_markets as sm
from src.research import secondary_refresh as sr
from test_camera_refresh import CFG, NAMES, NOW, SHIP0, research, write_dir
from test_camera_routes import bb, build, lst, off, rec, route, sold, _two_shops

MCFG = sm.load_config()
SECRET = "SUPER-SECRET-VALUE-123"


@pytest.fixture(autouse=True)
def _no_adapters():
    sm.clear_adapters()
    yield
    sm.clear_adapters()


def _fees(**over):
    c = copy.deepcopy(CFG)
    for k, v in over.items():
        c["fees"][k].update(v)
    return c


# ---- 手数料の状態 ----
def test_fee_status_is_strict():
    assert cr.fee_status(CFG["fees"]["mercari"]) == "CONFIRMED"
    assert cr.fee_status(CFG["fees"]["yahoo_flea"]) == "UNVERIFIED"
    assert cr.fee_status(CFG["fees"]["rakuma"]) == "UNKNOWN" and cr.fee_status(CFG["fees"]["ebay"]) == "UNKNOWN"
    assert cr.fee_status({"rate": 0.1, "confirmed": True}) == "UNKNOWN"                          # 古い confirmed: true を信用しない
    assert cr.fee_status({"rate": 0.1, "status": "CONFIRMED"}) == "UNKNOWN"                      # 本文を読んだ印が無い
    assert cr.fee_status({"rate": 0, "status": "CONFIRMED", "evidence_read_body": True}) == "UNKNOWN"   # 0 円では確定しない
    assert cr.fee_status(None) == "UNKNOWN"


def _sold3(market="メルカリ"):
    return [{**sold(250000 + i, f"2026-11-1{i}", market=market, n=i)} for i in range(3)]


def test_route_d_needs_confirmed_fee_and_unverified_is_not_calculated():
    flea = [{**sold(250000 + i, f"2026-11-1{i}", n=i), "market": "Yahoo!フリマ", "url": f"https://paypayfleamarket.yahoo.co.jp/item/z12345678{i}"} for i in range(3)]
    b = route(build(rec(official=off(200000), sold=flea)), "B")
    assert b["profit_status"] == cr.NOT_CALCULATED and "fee_unconfirmed" in b["reasons"] and b["fee_status"] == "UNVERIFIED"
    c = route(build(rec(official=off(200000), sold=_sold3()), cfg=CFG), "B")
    assert c["profit_status"] == cr.PROFITABLE and c["fee_status"] == "CONFIRMED" and c["costs"]["selling_fee"] > 0
    # 手数料が UNKNOWN に落ちたらメルカリでも計算しない（0 円として利益を出さない）
    d = route(build(rec(official=off(200000), sold=_sold3()), cfg=_fees(mercari={"status": "UNKNOWN"})), "B")
    assert d["profit_status"] == cr.NOT_CALCULATED


def test_buyback_routes_have_no_selling_fee():
    a = route(build(rec(official=off(200000), buyback=_two_shops())), "A")
    assert a["fee_status"] == "NOT_APPLICABLE" and a["costs"]["selling_fee"] == 0


# ---- 市場ごとの取得可否 ----
def _st(mid, env, **kw):
    return sm.market_status(mid, MCFG["markets"][mid], env, **kw)


def test_default_markets_are_blocked_not_empty():
    rep = sm.market_report({"products": []}, MCFG, {}, fees=CFG["fees"])
    by = {m["market"]: m for m in rep}
    assert [m["market"] for m in rep] == ["mercari", "yahoo_auction", "yahoo_flea", "rakuma", "ebay"]       # 優先順位
    assert by["yahoo_auction"]["status"] == sm.NOT_SUPPORTED
    assert all(m["status"] in (sm.BLOCKED, sm.NOT_SUPPORTED) for m in rep)
    assert all(m["listing_rows"] is None and m["sold_rows"] is None for m in rep)                            # 0 件ではなく未取得
    assert sm.blocked_treated_as_empty(rep) == 0
    assert by["ebay"]["credentials"] == sm.NOT_CONFIGURED and by["mercari"]["credentials"] == sm.NOT_REQUIRED
    assert by["mercari"]["fee_status"] == "CONFIRMED" and by["ebay"]["fee_rate"] is None


def test_blocked_with_zero_rows_would_be_flagged():
    rep = sm.market_report({"products": []}, MCFG, {}, fees=CFG["fees"])
    rep[0]["listing_rows"] = 0                                                       # 未取得を 0 件と書いたら品質違反として数える
    assert sm.blocked_treated_as_empty(rep) == 1


def test_ebay_credentials_ladder_and_secret_never_printed():
    env = {"EBAY_CLIENT_ID": "id-" + SECRET, "EBAY_CLIENT_SECRET": SECRET}
    s1 = _st("ebay", env)
    assert s1["status"] == sm.BLOCKED and s1["reason"] == "official_api_not_enabled" and s1["credentials"] == sm.CONFIGURED
    env["ENABLE_EBAY_API"] = "true"
    s2 = _st("ebay", env)
    assert s2["reason"] == "adapter_not_implemented" and s2["status"] == sm.BLOCKED          # キーがあっても受け皿だけの間は取得扱いにしない
    sm.register_adapter("ebay", lambda mid, e: [])
    assert _st("ebay", env)["reason"] == "adapter_not_run"                          # 登録しただけでは取得扱いにしない
    s3 = _st("ebay", env, adapters_ran={"ebay"})
    assert s3["status"] == sm.PARTIAL and s3["listing_access"] == sm.AVAILABLE and s3["sold_access"] == sm.BLOCKED     # 成約は審査制で未承認
    env["EBAY_INSIGHTS_APPROVED"] = "true"
    assert _st("ebay", env, adapters_ran={"ebay"})["status"] == sm.AVAILABLE
    assert SECRET not in json.dumps([s1, s2, s3], ensure_ascii=False)


def test_adapter_failure_is_failed_not_empty():
    env = {"EBAY_CLIENT_ID": "a", "EBAY_CLIENT_SECRET": "b", "ENABLE_EBAY_API": "true"}

    def boom(mid, e):
        raise RuntimeError(SECRET)
    sm.register_adapter("ebay", boom)
    rows, errs, ran = sm.run_adapters(env)
    assert rows == [] and errs == {"ebay": "adapter_error:RuntimeError"} and SECRET not in json.dumps(errs)
    s = _st("ebay", env, adapter_error=errs["ebay"])
    assert s["status"] == sm.FAILED and s["listing_rows"] is None


def test_adapter_not_called_without_credentials_or_enable():
    called = []
    sm.register_adapter("ebay", lambda mid, e: called.append(1) or [])
    sm.run_adapters({})
    sm.run_adapters({"EBAY_CLIENT_ID": "a", "EBAY_CLIENT_SECRET": "b"})          # 有効化していない
    assert called == []


def test_rows_from_research_file_make_a_market_partial():
    m_ = build(rec(official=off(200000), buyback=_two_shops(), listing=[{**lst(150000, market="メルカリ"), "url": "https://jp.mercari.com/item/m12345678901"}]))
    rep = sm.market_report(m_, MCFG, {}, fees=CFG["fees"])
    mer = next(m for m in rep if m["market"] == "mercari")
    assert mer["status"] == sm.PARTIAL and mer["reason"] == "rows_from_research_file" and mer["listing_rows"] == 1 and mer["sold_rows"] is None
    assert next(m for m in rep if m["market"] == "rakuma")["status"] == sm.BLOCKED          # 他の市場は未取得のまま


# ---- ルート C / D ----
def test_route_c_uses_listing_low_and_buyback_not_listing_high():
    low = {**lst(150000, cond="NEW", market="メルカリ"), "url": "https://jp.mercari.com/item/m12345678901"}
    high = {**lst(999999, cond="NEW", market="メルカリ"), "url": "https://jp.mercari.com/item/m12345678902"}
    m_ = build(rec(official=off(200000), buyback=_two_shops(), listing=[low, high]))
    c = route(m_, "C")
    assert c["buy"]["price"] == 150000 and c["sell"]["price_type"] == "BUYBACK_PRICE" and c["profit_status"] in (cr.PROFITABLE, cr.NO_PROFIT)
    assert c["decision"] != cr.BUY                                                    # 二次流通の仕入れは自動 BUY にしない
    sec = m_["products"][0]["secondary"]["listing"]
    assert sec["NEW"]["high"] == 999999 and all(r["sell"] is None or r["sell"]["price"] != 999999 for r in m_["routes"])


def test_route_d_needs_sold_median_with_samples():
    low = {**lst(150000, cond="NEW", market="メルカリ"), "url": "https://jp.mercari.com/item/m12345678901"}
    few = _sold3()[:2]
    d = route(build(rec(official=off(200000), listing=[low], sold=few)), "D")
    assert d["profit_status"] == cr.NOT_CALCULATED and d["sell"] is None or d["sell"]["price_type"] != "LISTING_HIGH"
    assert d["profit_status"] == cr.NOT_CALCULATED
    ok = route(build(rec(official=off(200000), listing=[low], sold=_sold3())), "D")
    assert ok["profit_status"] != cr.NOT_CALCULATED and ok["sell"]["price_type"] == "SOLD_MEDIAN" and ok["sell"]["evidence"]["sample_count"] == 3
    assert ok["costs"]["selling_fee"] > 0 and ok["fee_status"] == "CONFIRMED"


# ---- secondary_refresh ----
def test_secondary_refresh_dry_run_and_apply(tmp_path, monkeypatch, capsys):
    d = write_dir(tmp_path, research())
    monkeypatch.setattr(cf, "EXPORT_DIR", tmp_path / "export")
    monkeypatch.setattr(cf, "WEEKLY_ROOT", tmp_path)
    monkeypatch.setattr(cf, "_build_page", lambda: None)
    monkeypatch.setattr(cf, "OBS_PATH", tmp_path / "none.json")
    for k in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "ENABLE_EBAY_API"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("src.research.secondary_refresh.datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))
    rc = sr.main(["--dir", str(d)])
    out = json.loads(capsys.readouterr().out)
    assert out["mode"] == "DRY_RUN" and not (tmp_path / "export").exists()                 # dry-run は書かない
    assert out["markets_succeeded"] == [] and set(out["markets_blocked"]) == set(out["markets_attempted"])
    assert out["routes_C_calculated"] == 0 and out["routes_D_calculated"] == 0 and out["listing_rows"] == 0 and out["sold_rows"] == 0
    assert out["market_status"]["mercari"]["listing_rows"] is None and rc in (0, 2)
    rc = sr.main(["--dir", str(d), "--apply"])
    out2 = json.loads(capsys.readouterr().out)
    pub = json.loads((tmp_path / "export" / cf.MARKET_FILE).read_text(encoding="utf-8"))
    hist = json.loads((tmp_path / "export" / cf.HISTORY_FILE).read_text(encoding="utf-8"))
    assert out2["mode"] == "APPLY" and pub["secondary_markets"] and all(m["listing_rows"] is None for m in pub["secondary_markets"])
    assert pub["quality"]["blocked_treated_as_empty"] == 0 and pub["quality"]["unknown_fee_used"] == 0
    assert hist["snapshots"][-1]["secondary_markets"][0]["market"] == "mercari" and "secondary" in hist["snapshots"][-1]


def test_page_shows_blocked_as_not_fetched_and_fee_status(tmp_path):
    from src.content import camera_market_page as pg
    st = cf.refresh(write_dir(tmp_path, research()), "2026-11-18", now=NOW, cfg=CFG, obs_doc={}, names=NAMES,
                    official_shipping_fn=SHIP0, fixed_cost_fn=lambda: 1800, env={})
    html = pg.render(cf._public_market(st), now=NOW)
    assert "二次流通の取得状況" in html and "未取得" in html and "取得できない（未取得）" in html
    assert "提供されていない（未取得）" in html and "未登録" in html
    assert "出品や成約が無いという意味ではありません" in html
    assert "Secondary Sold" in html and "<th>費用</th>" in html


# ---- レビュー指摘の回帰 ----
@pytest.mark.parametrize("url,exp", [
    ("https://jp.mercari.com/item/m12345678901", "mercari"), ("https://notmercari.com/item/x", None), ("https://evilfril.jp/x", None),
    ("https://item.fril.jp/abc123", "rakuma"), ("https://shop.ebay.com/itm/1", "ebay"), ("https://www.ebay.com/itm/1", "ebay"),
    ("https://evilebay.com/itm/1", None), ("https://paypayfleamarket.yahoo.co.jp/item/z1", "yahoo_flea"),
    ("https://xpaypayfleamarket.yahoo.co.jp/item/z1", None), ("https://page.auctions.yahoo.co.jp/jp/auction/x1", "yahoo_auction"),
    ("https://notauctions.yahoo.co.jp/x", None)])
def test_market_from_url_is_exact_host(url, exp):
    assert cr.market_from_url(url) == exp


def test_fee_status_bounds_and_confirmed_on():
    base = {"rate": 0.1, "status": "CONFIRMED", "evidence_read_body": True, "confirmed_on": "2026-11-18"}
    assert cr.fee_status(base) == "CONFIRMED"
    assert cr.fee_status({**base, "rate": 10}) == "UNKNOWN" and cr.fee_status({**base, "rate": 1}) == "UNKNOWN"
    assert cr.fee_status({**base, "confirmed_on": None}) == "UNKNOWN" and cr.fee_status({**base, "confirmed_on": "さっき"}) == "UNKNOWN"


def test_listing_high_market_and_checked_at_come_from_their_own_rows():
    low = {**lst(150000, cond="NEW", market="メルカリ", day="2026-11-14"), "url": "https://jp.mercari.com/item/m12345678901"}
    high = {**lst(300000, cond="NEW", market="ラクマ", day="2026-11-18"), "url": "https://item.fril.jp/abc12345"}
    sec = build(rec(official=off(200000), listing=[low, high]))["products"][0]["secondary"]["listing"]["NEW"]
    assert sec["low_market"] == "メルカリ" and sec["high_market"] == "ラクマ" and sec["checked_at"] == "2026-11-14"      # 最安の行の確認日


def test_sold_summary_checked_at_is_the_oldest_row():
    rows = [{**sold(250000 + i, f"2026-11-1{i}", n=i), "checked_at": d} for i, d in enumerate(["2026-11-18", "2026-11-12", "2026-11-18"])]
    s = next(iter(build(rec(official=off(200000), sold=rows))["products"][0]["secondary"]["sold"].values()))
    assert s["checked_at"] == "2026-11-12"


def test_adapter_error_stays_visible_even_with_research_rows():
    m_ = build(rec(official=off(200000), buyback=_two_shops(), listing=[{**lst(150000, market="eBay"), "url": "https://www.ebay.com/itm/123456789"}]))
    env = {"EBAY_CLIENT_ID": "a", "EBAY_CLIENT_SECRET": "b", "ENABLE_EBAY_API": "true"}
    rep = sm.market_report(m_, MCFG, env, fees=CFG["fees"], adapter_errors={"ebay": "adapter_error:RuntimeError"})
    e = next(m for m in rep if m["market"] == "ebay")
    assert e["api_error"] == "adapter_error:RuntimeError" and e["listing_rows"] == 1


def test_page_does_not_write_zero_for_unfetched(tmp_path):
    from src.content import camera_market_page as pg
    st = cf.refresh(write_dir(tmp_path, research()), "2026-11-18", now=NOW, cfg=CFG, obs_doc={}, names=NAMES,
                    official_shipping_fn=SHIP0, fixed_cost_fn=lambda: 1800, env={})
    kinds = pg._kinds(cf._public_market(st)["summary"], cf._public_market(st))
    assert kinds.count("未取得（全市場）") == 2 and "0 件" not in kinds.split("Secondary Listings")[1]


def test_future_confirmed_on_is_not_confirmed():
    f = {"rate": 0.1, "status": "CONFIRMED", "evidence_read_body": True, "confirmed_on": "2099-01-01"}
    assert cr.fee_status(f) == "UNKNOWN"

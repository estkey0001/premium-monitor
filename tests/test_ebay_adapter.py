"""eBay 二次流通アダプター: 資格情報なしの安全・モックの契約（fixture は本番データではない）・同一性・状態・通貨・利益の抑止・表示。"""
from __future__ import annotations

import json
import urllib.request

import pytest

from src.research import camera_refresh as cf
from src.research import camera_routes as cr
from src.research import ebay_adapter as ea
from src.research import secondary_markets as sm
from src.research import secondary_refresh as sr
from test_camera_refresh import CFG, NAMES, NOW, SHIP0, research, write_dir
from test_camera_routes import _two_shops, build, off, rec, route

SECRET = "EBAY-SECRET-VALUE-XYZ-987"
CRED = {"EBAY_CLIENT_ID": "id-" + SECRET, "EBAY_CLIENT_SECRET": SECRET}
LIVE = {**CRED, "ENABLE_EBAY_API": "true"}
APPROVED = {**LIVE, "EBAY_INSIGHTS_APPROVED": "true", "EBAY_SOLD_LICENSE_CONFIRMED": "true"}


@pytest.fixture(autouse=True)
def _guard(monkeypatch):
    """実通信は禁止（テストは http_get / token_fn を差し込む）。アダプターを標準の状態に戻す。"""
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: calls.append(a) or (_ for _ in ()).throw(RuntimeError("network blocked")))
    monkeypatch.setattr(ea, "fx_state", lambda cur, now, path=None: _FX.get(cur) or {"status": "UNKNOWN", "rate": None, "checked_at": None, "currency": cur})
    _FX.clear()
    _FX["JPY"] = {"status": "NOT_NEEDED", "rate": 1.0, "checked_at": None, "currency": "JPY"}
    sm.clear_adapters()
    sm.register_default_adapters()
    yield calls


_FX: dict = {}


def fx_ok(rate=150.0):
    _FX["USD"] = {"status": "CONFIRMED", "rate": rate, "checked_at": "2026-11-17", "currency": "USD"}


def never(*a, **k):
    raise AssertionError("通信してはいけない")


def item(title="Ricoh GR IV Digital Camera", price="1500.00", cond="1000", iid="v1|123456789012|0", **kw):
    d = {"itemId": iid, "title": title, "price": {"value": price, "currency": "USD"}, "conditionId": cond,
         "itemWebUrl": f"https://www.ebay.com/itm/{iid.split('|')[1]}?hash=x", "buyingOptions": ["FIXED_PRICE"],
         "shippingOptions": [{"shippingCost": {"value": "60.00", "currency": "USD"}}], "itemLocation": {"country": "US"}}
    d.update(kw)
    return d


def sale(title="Ricoh GR IV Digital Camera", price="1400.00", cond="1000", iid="123456780001", day="2026-11-10T03:00:00.000Z"):
    return {"itemId": f"v1|{iid}|0", "title": title, "lastSoldPrice": {"value": price, "currency": "USD"}, "conditionId": cond,
            "itemWebUrl": f"https://www.ebay.com/itm/{iid}", "lastSoldDate": day}


def fake_http(listing=None, sold=None, fail=None, calls=None):
    def _get(url, headers):
        if calls is not None:
            calls.append(url)
        if fail:
            return {"status": fail, "data": None, "retry_after": None, "exc": RuntimeError("x")}
        if "marketplace_insights" in url:
            return {"status": 200, "data": {"itemSales": sold or [], "total": len(sold or []), "offset": 0, "limit": 200}, "retry_after": None, "exc": None}
        return {"status": 200, "data": {"itemSummaries": listing or []}, "retry_after": None, "exc": None}
    return _get


def tok_ok(scope):
    return "T-" + SECRET, "OK"


def run(env, **kw):
    return ea.fetch("ebay", env, now=NOW, **kw)


# ---- 資格情報なし / 無効 / dry-run: 通信 0・例外 0 ----
def test_no_credentials_is_not_configured_with_zero_network(_guard):
    r = run({}, http_get=never, token_fn=never)
    assert r.status == sm.NOT_CONFIGURED and r.reason == "official_api_not_configured" and r.records == [] and r.stats["requests"] == 0
    assert r.listing_access == sm.NOT_CONFIGURED and r.sold_access == sm.NOT_CONFIGURED
    assert _guard == []


@pytest.mark.parametrize("env,reason", [(CRED, "official_api_not_enabled"), ({**LIVE, "API_DRY_RUN": "true"}, "api_dry_run")])
def test_credentials_but_disabled_or_dry_run_makes_no_request(env, reason, _guard):
    r = run(env, http_get=never, token_fn=never)
    assert r.status == sm.BLOCKED and r.reason == reason and r.stats["requests"] == 0 and r.records == [] and _guard == []


def test_app_id_alias_counts_as_credentials():
    assert ea.has_credentials({"EBAY_APP_ID": "a", "EBAY_CLIENT_SECRET": "b"}) and not ea.has_credentials({"EBAY_CLIENT_ID": "a"})
    assert sm.credential_state(sm.load_config()["markets"]["ebay"], {"EBAY_APP_ID": "a", "EBAY_CLIENT_SECRET": "b"}) == sm.CONFIGURED


def test_secondary_refresh_without_credentials_zero_requests_and_no_fake_data(tmp_path, monkeypatch, capsys, _guard):
    d = write_dir(tmp_path, research())
    monkeypatch.setattr(cf, "EXPORT_DIR", tmp_path / "export")
    monkeypatch.setattr(cf, "WEEKLY_ROOT", tmp_path)
    monkeypatch.setattr(cf, "_build_page", lambda: None)
    monkeypatch.setattr(cf, "OBS_PATH", tmp_path / "none.json")
    for k in ("EBAY_CLIENT_ID", "EBAY_APP_ID", "EBAY_CLIENT_SECRET", "ENABLE_EBAY_API"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr("src.research.secondary_refresh.datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))
    sr.main(["--dir", str(d), "--apply"])
    out = json.loads(capsys.readouterr().out)
    eb = out["ebay"]
    assert eb["status"] == "NOT_CONFIGURED" and eb["listing_status"] == "NOT_CONFIGURED" and eb["sold_status"] == "NOT_CONFIGURED"
    assert eb["credentials_configured"] is False and eb["network_requests"] == 0 and eb["profit_routes_calculated"] == 0
    assert out["market_status"]["ebay"]["listing_rows"] is None and out["market_status"]["ebay"]["sold_rows"] is None   # 出品 0 件・成約 0 件と書かない
    pub = json.loads((tmp_path / "export" / cf.MARKET_FILE).read_text(encoding="utf-8"))
    assert pub["quality"]["blocked_treated_as_empty"] == 0
    assert not any(o["source"] == "eBay" for p in pub["products"] for o in p["observations"])        # 公開データに eBay の行は 0
    assert _guard == []


# ---- 出品（Browse）の契約 ----
def test_listing_parse_identity_condition_and_semantics():
    fx_ok()
    items = [item(),                                                                                   # 採用: GR IV・新品
             item("Ricoh GR IV HDF Highlight Diffusion Filter Edition", iid="v1|123456789013|0"),     # GR IV としては別の版 → 同一性で除外
             item("Ricoh GR IIIx Digital Camera", iid="v1|123456789014|0"),                             # 別の機種
             item("Ricoh GR IV Monochrome", iid="v1|123456789015|0"),                                   # 別の版
             item("Ricoh GR IV camera for parts not working", iid="v1|123456789016|0"),                 # ジャンク
             item(iid="v1|123456789017|0", cond="2000"),                                                # 整備品
             item(iid="v1|123456789018|0", buyingOptions=["AUCTION"]),                                  # オークション（現在価格は希望価格ではない）
             {**item(), "itemId": "x", "itemWebUrl": "https://www.ebay.com/sch/i.html?_nkw=gr"}]         # 商品ページの URL も ID も読めない
    r = run(LIVE, http_get=fake_http(listing=items), token_fn=tok_ok, products=(("RICOH GR IV", "Ricoh GR IV"),))
    rows = r.records[0]["listing"]
    assert len(rows) == 1 and rows[0]["condition"] == cr.UNOPENED and rows[0]["price_type"] == "LISTING"
    st = r.stats
    assert st["items_found"] == 8 and st["listing_matched"] == 1 and st["rejected_identity"] == 3 and st["rejected_condition"] == 2
    assert st["rejected_not_fixed_price"] == 1 and st["rejected_no_price_or_url"] == 1
    w = rows[0]
    assert w["currency"] == "USD" and w["price_original"] == 1500.0 and w["price_jpy"] == 225000 and w["fx_status"] == "CONFIRMED"
    assert w["shipping_original"] == 60.0 and w["import_duty_status"] == "UNKNOWN" and w["location"] == "US" and w["checked_at"] and w["url"].startswith("https://www.ebay.com/itm/")
    assert r.status == sm.PARTIAL and r.listing_access == sm.AVAILABLE and r.sold_access == sm.PENDING_APPROVAL and r.reason == "api_listing_only"


def test_hdf_and_x100vi_identity_are_not_mixed():
    fx_ok()
    r = run(LIVE, http_get=fake_http(listing=[item("Ricoh GR IV HDF Digital Camera"), item("Ricoh GR IV Digital Camera", iid="v1|123456789022|0")]),
            token_fn=tok_ok, products=(("RICOH GR IV HDF", "Ricoh GR IV HDF"),))
    assert [x["item_title"] for x in r.records[0]["listing"]] == ["Ricoh GR IV HDF Digital Camera"]      # 通常の GR IV を HDF に混ぜない
    r2 = run(LIVE, http_get=fake_http(listing=[item("Fujifilm X100VI Silver"), item("Fujifilm X100V Silver", iid="v1|123456789023|0")]),
             token_fn=tok_ok, products=(("FUJIFILM X100VI", "Fujifilm X100VI"),))
    assert len(r2.records[0]["listing"]) == 1


@pytest.mark.parametrize("cid,txt,exp", [("1000", "", cr.UNOPENED), ("1500", "", cr.LIKE_NEW), ("2750", "", cr.LIKE_NEW), ("3000", "", cr.USED),
                                         ("", "New", cr.UNOPENED), ("", "Used", cr.USED), ("", "", cr.UNKNOWN), ("", "Weird", cr.UNKNOWN)])
def test_condition_normalization(cid, txt, exp):
    assert ea._condition({"conditionId": cid, "condition": txt})[0] == exp


def test_listing_request_is_browse_fixed_price_and_never_finding_api():
    url, h = ea.build_browse_request("Ricoh GR IV")
    assert url.startswith("https://api.ebay.com/buy/browse/v1/item_summary/search?") and "FIXED_PRICE" in url and "deliveryCountry:JP" in url
    assert h["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US" and "Authorization" not in h and "findItems" not in url


# ---- 成約（Insights）の扱い ----
def test_listing_only_when_sold_not_approved_makes_no_sold_median(_guard):
    fx_ok()
    calls = []
    r = run(LIVE, http_get=fake_http(listing=[item()], calls=calls), token_fn=tok_ok, products=(("RICOH GR IV", "Ricoh GR IV"),))
    assert r.status == sm.PARTIAL and r.sold_access == sm.PENDING_APPROVAL and r.records[0]["sold"] == []
    assert not any("marketplace_insights" in u for u in calls)                                           # 承認前は成約を取りに行かない
    r2 = run({**LIVE, "EBAY_INSIGHTS_APPROVED": "true"}, http_get=fake_http(listing=[item()]), token_fn=tok_ok, products=(("RICOH GR IV", "Ricoh GR IV"),))
    assert r2.sold_access == sm.PENDING_APPROVAL and r2.stats["sold_reason"] == "sold_license_unconfirmed"  # ライセンス未確認でも取らない


def test_insights_denied_by_ebay_is_pending_approval_not_failed():
    def tok(scope):
        return (None, "PENDING_EBAY_APPROVAL") if "insights" in scope else ("T", "OK")
    r = run(APPROVED, http_get=fake_http(listing=[item()]), token_fn=tok, products=(("RICOH GR IV", "Ricoh GR IV"),))
    assert r.status == sm.PARTIAL and r.sold_access == sm.PENDING_APPROVAL


def test_sold_parse_with_confirmed_fx_and_available():
    fx_ok()
    sales = [sale(iid=f"12345678000{i}") for i in range(3)] + [sale("Ricoh GR IIIx", iid="123456780009"), sale(iid="123456780008", day="")]
    r = run(APPROVED, http_get=fake_http(listing=[item()], sold=sales), token_fn=tok_ok, products=(("RICOH GR IV", "Ricoh GR IV"),))
    s = r.records[0]["sold"]
    assert r.status == sm.AVAILABLE and r.sold_access == sm.AVAILABLE and len(s) == 3 and r.stats["rejected_identity"] == 1
    assert s[0]["price_original"] == 1400.0 and s[0]["price_jpy"] == 210000 and s[0]["sold_at"].startswith("2026-11-10") and s[0]["price_type"] == "SOLD"
    assert r.stats["rejected_no_price_or_url"] == 1                                                      # 成約日時が無い行は取得時刻で代用しない


# ---- 失敗は空にしない ----
def test_token_failure_is_failed_and_page_shows_not_fetched():
    r = run(LIVE, http_get=never, token_fn=lambda s: (None, "AUTH_FAILED"))
    assert r.status == sm.FAILED and r.reason == "browse_token_auth_failed" and r.records == []
    m = sm.market_status("ebay", sm.load_config()["markets"]["ebay"], LIVE, detail=r)
    assert m["status"] == sm.FAILED and m["listing_rows"] is None and m["sold_rows"] is None


def test_listing_http_failure_is_failed():
    r = run(LIVE, http_get=fake_http(fail=401), token_fn=tok_ok, products=(("RICOH GR IV", "Ricoh GR IV"),))
    assert r.status == sm.FAILED and r.records == [] and "listing_error" in r.stats


def test_adapter_exception_becomes_failed_in_run_adapters(monkeypatch):
    def boom(mid, env):
        raise RuntimeError(SECRET)
    boom.self_gated = True
    sm.register_adapter("ebay", boom)
    rows, errs, ran, details = sm.run_adapters_full(LIVE)
    assert rows == [] and errs == {"ebay": "adapter_error:RuntimeError"} and SECRET not in json.dumps(errs) and "ebay" in ran


def test_registered_and_called_even_without_credentials():
    rows, errs, ran, details = sm.run_adapters_full({})
    assert "ebay" in ran and details["ebay"].status == sm.NOT_CONFIGURED and rows == [] and errs == {}


# ---- 通貨・手数料・仕入れ: 利益の抑止 ----
def _ebay_listing(price_jpy=225000, fx="UNKNOWN", rate=None):
    return {"market": "eBay", "item_title": "RICOH GR IV HDF", "condition": "UNOPENED", "price_jpy": price_jpy, "price_original": 1500.0,
            "currency": "USD", "fx_status": fx, "fx_rate": rate, "fx_checked_at": "2026-11-17" if rate else None, "region": "EBAY_US",
            "url": "https://www.ebay.com/itm/123456789012", "checked_at": "2026-11-18", "purchasable_now": True, "result": "FOUND"}


def test_unconfirmed_fx_listing_is_displayed_in_original_currency_only():
    m = build(rec(official=off(200000), buyback=_two_shops(), listing=[_ebay_listing(price_jpy=None)]))
    p = m["products"][0]
    assert p["secondary"]["listing"] == {} and p["secondary"]["listing_foreign"]["NEW|USD"]["low"] == 1500.0           # 円の価格にしない
    assert p["secondary"]["listing_foreign"]["NEW|USD"]["fx_status"] == "UNKNOWN"
    c = route(m, "C")
    assert c["profit_status"] == cr.NOT_CALCULATED and c["net_profit"] is None and "cross_border_cost_unknown" in c["reasons"] and "fx_unconfirmed" in c["reasons"]
    assert c["decision"] != cr.BUY


def test_confirmed_fx_listing_still_not_a_route_c_buy_because_cost_unknown():
    m = build(rec(official=off(200000), buyback=_two_shops(), listing=[_ebay_listing(price_jpy=225000, fx="CONFIRMED", rate=150.0)]))
    c = route(m, "C")
    assert c["profit_status"] == cr.NOT_CALCULATED and c["net_profit"] is None and c["buy"] is None
    assert "cross_border_cost_unknown" in c["reasons"] and "fx_unconfirmed" not in c["reasons"]
    assert m["products"][0]["secondary"]["listing"] == {}                                                              # 国内の最安にも混ぜない


def test_fx_mismatch_and_unconfirmed_with_jpy_value_are_rejected():
    bad = _ebay_listing(price_jpy=999, fx="CONFIRMED", rate=150.0)                                                     # 円換算が合わない
    m = build(rec(official=off(200000), buyback=_two_shops(), listing=[bad]))
    o = next(o for o in m["products"][0]["observations"] if o["kind"] == "listing")
    assert "fx_mismatch" in o["reasons"]
    sneaky = _ebay_listing(price_jpy=225000, fx="UNKNOWN")                                                             # 為替未確認なのに円の値
    o2 = next(o for o in build(rec(official=off(200000), listing=[sneaky]))["products"][0]["observations"] if o["kind"] == "listing")
    assert o2["price"] is None and "fx_unconfirmed" in o2["reasons"]


def _ebay_sold(i, fx="CONFIRMED"):
    return {"market": "eBay", "item_title": "RICOH GR IV HDF", "condition": "NEW", "price_jpy": 300000 + i if fx == "CONFIRMED" else None,
            "price_original": 2000.0 + i / 150, "currency": "USD", "fx_status": fx, "fx_rate": 150.0 if fx == "CONFIRMED" else None,
            "fx_checked_at": "2026-11-17" if fx == "CONFIRMED" else None, "url": f"https://www.ebay.com/itm/12345678000{i}",
            "sold_at": f"2026-11-1{i}", "checked_at": "2026-11-18", "result": "FOUND"}


def test_sold_with_unconfirmed_fx_makes_no_median():
    m = build(rec(official=off(200000), sold=[_ebay_sold(i, fx="UNKNOWN") for i in range(3)]))
    assert m["products"][0]["secondary"]["sold"] == {}                                                                 # 為替未確認の成約は SOLD_MEDIAN にしない
    assert route(m, "B")["profit_status"] == cr.NOT_CALCULATED


def test_ebay_sold_median_never_gives_a_profit_while_fee_is_unknown():
    rows = [_ebay_sold(i) for i in range(3)]
    m = build(rec(official=off(200000), sold=rows))
    assert any("eBay" in k for k in m["products"][0]["secondary"]["sold"])
    b = route(m, "B")
    assert b["profit_status"] == cr.NOT_CALCULATED and "fee_unconfirmed" in b["reasons"] and b["net_profit"] is None and b["fee_status"] == "UNKNOWN"
    domestic = {**rec(official=off(200000), sold=rows, listing=[{"market": "メルカリ", "item_title": "RICOH GR IV HDF", "condition": "NEW", "price_jpy": 150000,
                                                              "url": "https://jp.mercari.com/item/m12345678901", "checked_at": "2026-11-18", "purchasable_now": True, "result": "FOUND"}])}
    d = route(build(domestic), "D")
    assert d["profit_status"] == cr.NOT_CALCULATED and "fee_unconfirmed" in d["reasons"] and d["net_profit"] is None


# ---- 秘密 ・表示 ----
def test_secret_never_appears_in_result_or_summary():
    fx_ok()
    r = run(APPROVED, http_get=fake_http(listing=[item()], sold=[sale()]), token_fn=tok_ok, products=(("RICOH GR IV", "Ricoh GR IV"),))
    m = sm.market_status("ebay", sm.load_config()["markets"]["ebay"], APPROVED, detail=r)
    blob = json.dumps([r.public(), m], ensure_ascii=False, default=str)
    assert SECRET not in blob and "T-" + SECRET not in blob and "Bearer" not in blob


def test_page_shows_not_configured_and_never_zero_for_ebay(tmp_path):
    from src.content import camera_market_page as pg
    d = research()
    rep = cf.refresh(write_dir(tmp_path, d), "2026-11-18", now=NOW, cfg=CFG, obs_doc={}, names=NAMES, official_shipping_fn=SHIP0,
                     fixed_cost_fn=lambda: 1800, env={}, adapter_details=sm.run_adapters_full({})[3], adapters_ran={"ebay"})
    html = pg.render(cf._public_market(rep), now=NOW)
    eb = next(m for m in rep["secondary_markets"] if m["market"] == "ebay")
    assert eb["status"] == "NOT_CONFIGURED" and eb["listing_rows"] is None and eb["sold_rows"] is None
    assert "未設定（NOT_CONFIGURED・未取得）" in html
    row = html.split("eBay</th>")[1].split("</tr>")[0]
    assert "未取得" in row and "0 件" not in row


def test_page_renders_foreign_listing_without_yen_conversion():
    from src.content import camera_market_page as pg
    m = build(rec(official=off(200000), buyback=_two_shops(), listing=[_ebay_listing(price_jpy=None)]))
    sec = m["products"][0]["secondary"]
    html = pg._secondary({"product": "RICOH GR IV HDF", "secondary": sec})
    assert "海外の出品中" in html and "USD 1,500.00" in html and "円換算なし" in html and "仕入れの利益計算には使いません" in html


# ---- レビュー・監査の指摘の回帰 ----
def test_module_imports_without_circularity():
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-c", "import src.research.ebay_adapter as e; import src.research.secondary_markets as s; assert 'ebay' in s._ADAPTERS"],
                       capture_output=True, text=True, cwd=str(ea.PROJECT_ROOT))
    assert r.returncode == 0, r.stderr


def test_failed_side_drops_partial_rows():
    fx_ok()
    calls = {"n": 0}

    def flaky(url, headers):
        calls["n"] += 1
        if "marketplace_insights" in url and calls["n"] > 3:
            return {"status": 500, "data": None, "retry_after": None, "exc": RuntimeError("x")}
        if "marketplace_insights" in url:
            return {"status": 200, "data": {"itemSales": [sale(iid=f"12345678010{i}") for i in range(3)], "total": 400, "offset": 0, "limit": 200, "next": "n"}, "retry_after": None, "exc": None}
        return {"status": 200, "data": {"itemSummaries": [item()]}, "retry_after": None, "exc": None}
    r = run(APPROVED, http_get=flaky, token_fn=tok_ok, sleep_fn=None, products=(("RICOH GR IV", "Ricoh GR IV"),)) if False else \
        run(APPROVED, http_get=flaky, token_fn=tok_ok, products=(("RICOH GR IV", "Ricoh GR IV"),))
    assert r.sold_access == sm.FAILED and all(x["sold"] == [] for x in r.records)             # 途中までの成約から中央値を作らない
    assert any(x["listing"] for x in r.records)                                                # 出品は成功しているので残る


def test_listing_failure_drops_listing_rows():
    fx_ok()
    n = {"i": 0}

    def second_fails(url, headers):
        n["i"] += 1
        if n["i"] == 1:
            return {"status": 200, "data": {"itemSummaries": [item()]}, "retry_after": None, "exc": None}
        return {"status": 401, "data": None, "retry_after": None, "exc": RuntimeError("x")}
    r = run(LIVE, http_get=second_fails, token_fn=tok_ok, products=(("RICOH GR IV", "Ricoh GR IV"), ("RICOH GR IV HDF", "Ricoh GR IV HDF")))
    assert r.status == sm.FAILED and r.records == []


def test_truncated_sold_is_marked():
    fx_ok()

    def endless(url, headers):
        if "marketplace_insights" in url:
            return {"status": 200, "data": {"itemSales": [], "total": 1000, "offset": 0, "limit": 200, "next": "n"}, "retry_after": None, "exc": None}
        return {"status": 200, "data": {"itemSummaries": []}, "retry_after": None, "exc": None}
    r = run(APPROVED, http_get=endless, token_fn=tok_ok, products=(("RICOH GR IV", "Ricoh GR IV"),))
    assert r.stats.get("truncated") is True


@pytest.mark.parametrize("title", ["Ricoh GR IV Leather Case Strap Only", "Battery DB-120 Charger for Ricoh GR IV", "Ricoh GR IV box only",
                                   "Ricoh GR IV Instruction Manual", "Ricoh GR IV Screen Protector", "Ricoh GR IV lens cap hood", "Ricoh GR IV Silicone Case Cover"])
def test_english_accessories_are_rejected(title):
    st: dict = {}
    assert ea.listing_row("RICOH GR IV", item(title), now=NOW, checked_at="x", fx_cache={}, stats=st) is None and st["rejected_identity"] == 1


def test_auction_with_fixed_price_option_is_rejected():
    st: dict = {}
    assert ea.listing_row("RICOH GR IV", item(buyingOptions=["FIXED_PRICE", "AUCTION"]), now=NOW, checked_at="x", fx_cache={}, stats=st) is None
    assert st["rejected_not_fixed_price"] == 1


def test_ebay_url_without_currency_is_still_cross_border():
    row = {"market": "eBay", "item_title": "RICOH GR IV HDF", "condition": "NEW", "price_jpy": 150000, "url": "https://www.ebay.com/itm/123456789012",
           "checked_at": "2026-11-18", "purchasable_now": True, "shipping_jpy": 1000, "result": "FOUND"}
    m = build(rec(official=off(200000), buyback=_two_shops(), listing=[row]))
    assert m["products"][0]["secondary"]["listing"] == {}
    assert "cross_border_cost_unknown" in route(m, "C")["reasons"]


def test_old_or_incomplete_fx_claim_is_not_confirmed():
    old = {**_ebay_listing(price_jpy=225000, fx="CONFIRMED", rate=150.0), "fx_checked_at": "2026-06-01"}
    o = next(o for o in build(rec(official=off(200000), listing=[old]))["products"][0]["observations"] if o["kind"] == "listing")
    assert "fx_unconfirmed" in o["reasons"]
    no_po = {**_ebay_listing(price_jpy=1500, fx="CONFIRMED", rate=150.0)}
    no_po.pop("price_original")
    o2 = next(o for o in build(rec(official=off(200000), listing=[no_po]))["products"][0]["observations"] if o["kind"] == "listing")
    assert "fx_unconfirmed" in o2["reasons"]
    sold_old = [{**_ebay_sold(i), "fx_checked_at": "2026-06-01"} for i in range(3)]
    assert build(rec(official=off(200000), sold=sold_old))["products"][0]["secondary"]["sold"] == {}


def test_confirmed_ebay_fee_still_does_not_make_a_profit_route():
    import copy
    cfg = copy.deepcopy(CFG)
    cfg["fees"]["ebay"] = {"label": "eBay", "rate": 0.13, "status": "CONFIRMED", "evidence_read_body": True, "confirmed_on": "2026-11-18"}
    b = route(build(rec(official=off(200000), sold=[_ebay_sold(i) for i in range(3)]), cfg=cfg), "B")
    assert b["profit_status"] == cr.NOT_CALCULATED and "cross_border_sell_cost_unknown" in b["reasons"] and b["net_profit"] is None


def test_carried_ebay_row_keeps_currency_fields():
    from src.research import camera_refresh as cf2
    o = {"source": "eBay", "price": 225000, "condition": "NEW", "currency": "USD", "price_original": 1500.0, "fx_status": "CONFIRMED", "fx_rate": 150.0,
         "fx_checked_at": "2026-11-17", "region": "EBAY_US"}
    r = cf2._row_of(o)
    assert r["currency"] == "USD" and r["price_original"] == 1500.0 and r["fx_checked_at"] == "2026-11-17" and r["region"] == "EBAY_US"


def test_public_adapter_stats_use_attempted_at_not_checked_at():
    r = run({}, http_get=never, token_fn=never)
    m = sm.market_status("ebay", sm.load_config()["markets"]["ebay"], {}, detail=r)
    assert "attempted_at" in m["adapter"] and "checked_at" not in m["adapter"]


def test_ebay_sold_without_currency_is_not_a_median():
    rows = []
    for i in range(3):
        r = _ebay_sold(i)
        for k in ("currency", "price_original", "fx_status", "fx_rate", "fx_checked_at", "region"):
            r.pop(k, None)
        rows.append(r)
    assert build(rec(official=off(200000), sold=rows))["products"][0]["secondary"]["sold"] == {}


def test_truncated_sold_is_failed_and_rows_dropped():
    fx_ok()

    def endless(url, headers):
        if "marketplace_insights" in url:
            return {"status": 200, "data": {"itemSales": [sale(iid=f"12345679{len(url) % 10}{n:03d}") for n in range(3)], "total": 1000, "offset": 0, "limit": 200, "next": "n"},
                    "retry_after": None, "exc": None}
        return {"status": 200, "data": {"itemSummaries": [item()]}, "retry_after": None, "exc": None}
    r = run(APPROVED, http_get=endless, token_fn=tok_ok, products=(("RICOH GR IV", "Ricoh GR IV"),))
    assert r.sold_access == sm.FAILED and r.stats["sold_reason"] == "sold_incomplete" and all(x["sold"] == [] for x in r.records)
    assert r.status == sm.PARTIAL and r.records[0]["listing"]                      # 出品は残る


@pytest.mark.parametrize("title", ["Ricoh GR IV Tempered Glass Screen Guard", "Ricoh GR IV Thumb Grip", "Ricoh GR IV Tripod", "Ricoh GR IV Metal Cage"])
def test_more_accessories_rejected(title):
    st: dict = {}
    assert ea.listing_row("RICOH GR IV", item(title), now=NOW, checked_at="x", fx_cache={}, stats=st) is None


# ---- canary / 付属品つきの本体 ----
@pytest.mark.parametrize("title,exp", [
    ("Fujifilm X100VI Silver Digital Camera with Leather Case and Strap", False), ("Fujifilm X100VI Camera Body + Original Battery and Charger", False),
    ("Ricoh GR IV Digital Camera", False), ("Fujifilm X100VI Black Mirrorless Camera Body Only", False),
    ("Leather Case for Fujifilm X100VI", True), ("Fujifilm X100VI Camera Strap Only", True), ("Battery NP-W126S for X100VI", True),
    ("Screen Protector X100VI Camera", True), ("Ricoh GR IV box only", True), ("Ricoh GR IV Instruction Manual", True)])
def test_bundle_with_body_is_kept_and_accessory_only_is_rejected(title, exp):
    assert ea.is_accessory_only(title) is exp


def test_canary_blocked_without_credentials_makes_no_request(_guard):
    rep = ea.browse_canary({}, http_get=never, token_fn=never, now=NOW)
    assert rep["verdict_hint"] == "BLOCKED:no_credentials" and rep["browse"]["requests"] == 0 and rep["sold"]["requests"] == 0 and _guard == []
    for env, hint in ((CRED, "BLOCKED:not_enabled"), ({**LIVE, "API_DRY_RUN": "true"}, "BLOCKED:api_dry_run")):
        assert ea.browse_canary(env, http_get=never, token_fn=never, now=NOW)["verdict_hint"] == hint


def test_canary_one_request_one_product_never_touches_sold():
    fx_ok()
    calls = []
    items = [item("Fujifilm X100VI Silver Digital Camera"), item("Leather Case for Fujifilm X100VI", iid="v1|123456789031|0"),
             item("Fujifilm X100V Silver", iid="v1|123456789032|0"), item("Fujifilm X100VI with Case and Strap Camera", iid="v1|123456789033|0")]
    rep = ea.browse_canary({**APPROVED, "API_DRY_RUN": "false", "EBAY_INSIGHTS_APPROVED": "false", "EBAY_SOLD_LICENSE_CONFIRMED": "false"},
                           http_get=fake_http(listing=items, calls=calls), token_fn=tok_ok, now=NOW)
    assert len(calls) == 1 and "marketplace_insights" not in calls[0] and "limit=10" in calls[0]
    b = rep["browse"]
    assert b["http_status"] == 200 and b["returned"] == 4 and b["matched"] == 2 and b["rejected"]["total"] == 2 and rep["oauth"]["status"] == "SUCCESS"
    assert rep["sold"]["requests"] == 0 and rep["profit"] == "NOT_CALCULATED" and rep["verdict_hint"] == "PASS"
    assert rep["listings"][0]["currency"] == "USD" and rep["listings"][0]["price"] == 1500.0
    assert SECRET not in json.dumps(rep, ensure_ascii=False) and "Bearer" not in json.dumps(rep)


def test_canary_oauth_failure_and_http_failure_are_reported_not_hidden():
    r1 = ea.browse_canary({**LIVE, "API_DRY_RUN": "false"}, http_get=never, token_fn=lambda s: (None, "AUTH_FAILED"), now=NOW)
    assert r1["oauth"]["status"] == "FAILED" and r1["verdict_hint"].startswith("BLOCKED:oauth")
    r2 = ea.browse_canary({**LIVE, "API_DRY_RUN": "false"}, http_get=fake_http(fail=403), token_fn=tok_ok, now=NOW)
    assert r2["browse"]["http_status"] == 403 and r2["verdict_hint"] == "BLOCKED:browse_http_403" and "listings" not in r2


def test_credentials_are_stripped_and_token_error_code_is_diagnosed(monkeypatch):
    from src.collectors.api import ebay_insights as ei
    monkeypatch.setenv("EBAY_CLIENT_ID", "  idvalue-123456\n")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "secretvalue-123456\n")
    assert ei.credentials() == ("idvalue-123456", "secretvalue-123456")
    assert ei._error_code(b'{"error":"invalid_client","error_description":"client authentication failed"}') == "invalid_client"
    assert ei._error_code(b'{"error":"Bad Value With Spaces"}') is None and ei._error_code(b"not json") is None


def test_canary_oauth_failure_includes_only_safe_diagnostic(monkeypatch):
    from src.collectors.api import ebay_insights as ei
    monkeypatch.setattr(ei, "LAST_TOKEN_ERROR", {"http_status": 401, "error": "invalid_client", "secret": SECRET})
    rep = ea.browse_canary({**LIVE, "API_DRY_RUN": "false"}, http_get=never, token_fn=lambda s: (None, "AUTH_FAILED"), now=NOW)
    assert rep["oauth"]["http_status"] == 401 and rep["oauth"]["error"] == "invalid_client" and SECRET not in json.dumps(rep)


def test_credential_shape_never_contains_values_and_detects_environment():
    s = ea.credential_shape({"EBAY_CLIENT_ID": "App-Name-PRD-abcdef123456", "EBAY_CLIENT_SECRET": "PRD-sec ret\n"})
    assert s["client_id_environment"] == "PRD" and s["client_secret_has_inner_whitespace"] is True and s["client_id_has_inner_whitespace"] is False
    assert "abcdef" not in json.dumps(s) and "sec" not in json.dumps(s).replace("secret", "")
    assert ea.credential_shape({"EBAY_CLIENT_ID": "x-SBX-1"})["client_id_environment"] == "SBX"
    rep = ea.browse_canary({**LIVE, "API_DRY_RUN": "false"}, http_get=never, token_fn=lambda s_: (None, "AUTH_FAILED"), now=NOW)
    assert rep["oauth"]["credential_shape"]["client_secret_length"] == len(SECRET) and SECRET not in json.dumps(rep)

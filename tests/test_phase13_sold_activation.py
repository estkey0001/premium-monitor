"""Phase 13（成約の有効化と CI の組み込み: eBay Marketplace Insights の canary・関門・段階）のテスト。

本番の eBay は資格情報・承認・ライセンスの確認が無い（通信0）ので、応答の形は fixture で確かめる。
各テストには、誤りを入れると失敗する否定対照も付ける。
"""

from __future__ import annotations

import importlib.util
import json
import re
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST).replace(microsecond=0)

GATE_ENV = ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_APP_ID", "ENABLE_EBAY_API", "API_DRY_RUN",
            "EBAY_API_STAGE", "EBAY_INSIGHTS_APPROVED", "EBAY_SOLD_LICENSE_CONFIRMED", "EBAY_SOLD_CANARY",
            "EBAY_SOLD_CANARY_PRODUCT", "EBAY_SOLD_STAGE")
FAKE_ID, FAKE_SECRET = "FakeClientId-P13-abcdef", "FakeClientSecret-P13-123456"
FAKE_TOKEN = "v^1.1#i^1#p^3#r^0#I^3#f^0#t^FakeToken-P13"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


P12 = _load(ROOT / "tests" / "test_phase12_sold.py", "p13_from_p12_sold")


@pytest.fixture
def clean_env(monkeypatch):
    for k in GATE_ENV:
        monkeypatch.delenv(k, raising=False)
    return monkeypatch


def _all_gates(mp, **over):
    env = {"EBAY_CLIENT_ID": FAKE_ID, "EBAY_CLIENT_SECRET": FAKE_SECRET, "EBAY_INSIGHTS_APPROVED": "true",
           "EBAY_SOLD_LICENSE_CONFIRMED": "true", "ENABLE_EBAY_API": "true", "API_DRY_RUN": "false"}
    env.update(over)
    for k, v in env.items():
        if v is None:
            mp.delenv(k, raising=False)
        else:
            mp.setenv(k, v)


@pytest.fixture
def script(clean_env, tmp_path):
    """collect_ebay_sold を、書き込み先を tmp に向け、ネットワークを禁止して読む。"""
    import urllib.request
    m = _load(ROOT / "scripts" / "collect_ebay_sold.py", "p13_collect_ebay_sold")
    for name in ("STATUS_PATH", "CANARY_PATH", "ROLLOUT_PATH", "HISTORY_PATH"):
        setattr(m, name, tmp_path / f"{name.lower()}.json")
    calls = []

    def _no_network(*a, **k):
        calls.append(a)
        raise AssertionError("ネットワークに出た")
    clean_env.setattr(urllib.request, "urlopen", _no_network)
    m.network_calls = calls
    return m


def _iso(days_ago: float) -> str:
    return (NOW - timedelta(days=days_ago)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _item(n: int, *, title="Sony PlayStation 5 Pro Console CFI-7000 New Sealed", cond="1000", days=1.0,
          usd="1750.00", sold=True):
    it = {"itemId": f"v1|3955{n:08d}|0", "title": title, "itemWebUrl": f"https://www.ebay.com/itm/3955{n:08d}",
          "conditionId": cond, "lastSoldPrice": {"value": usd, "currency": "USD"}}
    if sold:
        it["lastSoldDate"] = _iso(days)
    return it


def _fake_api(m, mp, pages: dict, *, token=FAKE_TOKEN, token_status="OK"):
    """token の取得と検索の応答を差し替える（pages: 商品の検索語の一部 → itemSales）。"""
    from src.collectors.api import ebay_insights as ei
    mp.setattr(m, "_fetch_token", lambda: (token, ei.ST_OK) if token_status == "OK" else (None, token_status))
    seen = []

    def http_get(url, headers):
        seen.append((url, headers))
        for key, items in pages.items():
            if key in url:
                return {"status": 200, "data": {"total": len(items), "offset": 0, "limit": 200,
                                                "itemSales": items}, "retry_after": None, "exc": None}
        return {"status": 200, "data": {"total": 0, "itemSales": []}, "retry_after": None, "exc": None}
    mp.setattr(m, "_http_get", http_get)
    import src.market.product_identity_resolver as pir
    mp.setattr(pir, "build_products_index", lambda *a, **k: {})
    mp.setattr(pir, "ProductIdentityResolver", lambda *a, **k: P12._Resolver())
    import src.collectors.api.market_apis as ma
    mp.setattr(ma, "load_fx_rate", lambda cur: {"rate": 150.0, "source": "fixture", "observed_at": "2026-10-07"})
    return seen


# ── #64 資格情報なし・#66 承認なし・#71 ライセンスなし: 通信0・CI を失敗にしない ───────────────────

@pytest.mark.parametrize("env,status", [
    ({}, "PENDING_USER_CONFIGURATION"),
    ({"EBAY_CLIENT_ID": FAKE_ID, "EBAY_CLIENT_SECRET": FAKE_SECRET}, "PENDING_EBAY_APPROVAL"),
    ({"EBAY_CLIENT_ID": FAKE_ID, "EBAY_CLIENT_SECRET": FAKE_SECRET, "EBAY_INSIGHTS_APPROVED": "true"},
     "PENDING_LICENSE_CONFIRMATION"),
    ({"EBAY_CLIENT_ID": FAKE_ID, "EBAY_CLIENT_SECRET": FAKE_SECRET, "EBAY_INSIGHTS_APPROVED": "true",
      "EBAY_SOLD_LICENSE_CONFIRMED": "true"}, "DISABLED"),              # 取得の明示が無い
    ({"EBAY_CLIENT_ID": FAKE_ID, "EBAY_CLIENT_SECRET": FAKE_SECRET, "EBAY_INSIGHTS_APPROVED": "true",
      "EBAY_SOLD_LICENSE_CONFIRMED": "true", "ENABLE_EBAY_API": "true"}, "DRY_RUN"),  # API_DRY_RUN 未指定
    ({"EBAY_CLIENT_ID": FAKE_ID, "EBAY_CLIENT_SECRET": FAKE_SECRET, "EBAY_INSIGHTS_APPROVED": "true",
      "EBAY_SOLD_LICENSE_CONFIRMED": "true", "ENABLE_EBAY_API": "false", "API_DRY_RUN": "false"}, "DISABLED"),
])
def test_missing_gate_means_no_network(script, clean_env, capsys, env, status):
    for k, v in env.items():
        clean_env.setenv(k, v)
    if "API_DRY_RUN" not in env and env.get("ENABLE_EBAY_API") == "true":
        clean_env.setenv("API_DRY_RUN", "true")
    assert script.main([]) == 0                                   # CI を失敗にしない
    assert script.network_calls == []                             # 通信0
    body = json.loads(script.STATUS_PATH.read_text(encoding="utf-8"))
    assert body["status"] == status and body["skipped"] is True and body["network_used"] is False
    assert not script.CANARY_PATH.exists() and not script.HISTORY_PATH.exists()
    out = capsys.readouterr().out + script.STATUS_PATH.read_text(encoding="utf-8")
    assert FAKE_SECRET not in out and FAKE_ID not in out          # #65 秘密の値を出さない


def test_enable_switch_alone_is_not_enough(clean_env):
    """ENABLE_EBAY_API=true だけでは取りに行かない（資格情報・承認・ライセンスが要る）。"""
    from src.collectors.api import ebay_insights as ei
    clean_env.setenv("ENABLE_EBAY_API", "true")
    clean_env.setenv("API_DRY_RUN", "false")
    assert ei.status() == ei.ST_PENDING
    _all_gates(clean_env)
    assert ei.status() == ei.ST_OK
    for k, want in (("EBAY_INSIGHTS_APPROVED", ei.ST_PENDING_APPROVAL),
                    ("EBAY_SOLD_LICENSE_CONFIRMED", ei.ST_PENDING_LICENSE)):
        clean_env.setenv(k, "false")
        assert ei.status() == want
        clean_env.setenv(k, "true")


def test_status_file_is_not_rewritten_for_time_only(script, clean_env):
    """状態は中身が変わったときだけ書く（時刻だけの更新で生成物を毎日変えない）。"""
    script.main([])
    first = script.STATUS_PATH.read_text(encoding="utf-8")
    assert script._write_if_changed(script.STATUS_PATH, {**json.loads(first), "generated_at": "2099-01-01"}) is False
    assert script.STATUS_PATH.read_text(encoding="utf-8") == first
    clean_env.setenv("EBAY_CLIENT_ID", FAKE_ID)
    clean_env.setenv("EBAY_CLIENT_SECRET", FAKE_SECRET)
    script.main([])                                               # 状態が変わった → 書く
    assert json.loads(script.STATUS_PATH.read_text(encoding="utf-8"))["status"] == "PENDING_EBAY_APPROVAL"


# ── #65 資格情報があるときも秘密の値を出さない・#68 token を伏せる ──────────────────────────────

def test_secrets_never_in_outputs(script, clean_env, capsys):
    _all_gates(clean_env)
    _fake_api(script, clean_env, {"CFI-7000": [_item(1)]})
    assert script.main([]) == 0
    text = capsys.readouterr().out + "".join(
        p.read_text(encoding="utf-8") for p in (script.STATUS_PATH, script.CANARY_PATH) if p.exists())
    for s in (FAKE_ID, FAKE_SECRET, FAKE_TOKEN, "v^1.1#", "Bearer", "Basic "):
        assert s not in text


def test_bare_token_is_masked_and_mutation_is_caught(clean_env, monkeypatch):
    from src.collectors.api import ebay_insights as ei
    assert FAKE_TOKEN not in ei.redact(f"token={FAKE_TOKEN} {FAKE_TOKEN}")
    assert FAKE_TOKEN not in ei.dumps_safe({"x": FAKE_TOKEN})
    # 否定対照: 伏せる処理を外すと、token が残る（テストと deploy-check #845 が気づく）
    monkeypatch.setattr(ei, "_BARE_TOKEN", re.compile(r"(?!x)x"))
    assert FAKE_TOKEN in ei.redact(f"{FAKE_TOKEN}")
    dc = _load(ROOT / "scripts" / "deploy_check.py", "p13_deploy_check_mut")
    res = {r["check"]: r for r in dc._check_phase13_ebay_sold()}
    assert res["ebay_sold_gates"]["level"] == "error"


# ── #66 403（承認なし）・401（資格情報の誤り）・#67 429 と HTTP-date の Retry-After ─────────────────

def test_token_403_is_pending_approval(script, clean_env):
    from src.collectors.api import ebay_insights as ei
    _all_gates(clean_env)
    _fake_api(script, clean_env, {}, token=None, token_status=ei.status_from_error("permanent_403"))
    assert script.main([]) == 0
    body = json.loads(script.STATUS_PATH.read_text(encoding="utf-8"))
    assert body["status"] == "PENDING_EBAY_APPROVAL" and not script.CANARY_PATH.exists()
    assert ei.status_from_error("permanent_401") == ei.ST_AUTH_FAILED
    assert ei.status_from_error("permanent_400") == ei.ST_PENDING_APPROVAL       # invalid_scope
    assert ei.status_from_error("rate_limited_long_retry_after") == ei.ST_RATE_LIMITED


def test_search_403_stops_and_reports_approval(clean_env):
    from src.collectors.api import ebay_insights as ei
    calls, stats = [], {}

    def http_get(url, headers):
        calls.append(url)
        return {"status": 403, "data": None, "retry_after": None, "exc": None}
    recs, rej = ei.collect("prod_ps5_pro", "PS5 Pro", resolver=P12._Resolver(), now=NOW, fx_rate=150.0,
                           http_get=http_get, token="t", stats=stats)
    assert recs == [] and len(calls) == 1                          # 恒久エラーは再試行しない
    assert ei.status_from_error(stats["error_kind"]) == ei.ST_PENDING_APPROVAL


def test_retry_after_http_date():
    from src.collectors.api import api_runtime as rt
    now = NOW.timestamp()
    assert rt.parse_retry_after("30") == 30.0
    assert rt.parse_retry_after(format_datetime(NOW.astimezone(timezone.utc) + timedelta(seconds=45),
                                                usegmt=True), now=now) == pytest.approx(45, abs=1)
    assert rt.parse_retry_after(format_datetime(NOW.astimezone(timezone.utc) - timedelta(hours=1),
                                                usegmt=True), now=now) == 0.0
    assert rt.parse_retry_after("not a date") is None and rt.parse_retry_after(None) is None


def test_429_with_long_http_date_does_not_wait():
    """429 で長い待ち（HTTP-date で10分後）を求められたら、待たずに止める（CI を延ばさない）。"""
    from src.collectors.api import api_runtime as rt
    later = format_datetime(datetime.now(timezone.utc) + timedelta(minutes=10), usegmt=True)
    sleeps, calls = [], []

    def fn():
        calls.append(1)
        return {"status": 429, "data": None, "retry_after": later, "exc": None}
    res = rt.retry_with_backoff(fn, max_retries=3, sleep_fn=sleeps.append)
    assert res["ok"] is False and res["error_kind"] == "rate_limited_long_retry_after"
    assert len(calls) == 1 and sleeps == []
    # 短い HTTP-date なら、その秒数だけ待って再試行する
    soon = format_datetime(datetime.now(timezone.utc) + timedelta(seconds=20), usegmt=True)
    sleeps.clear()
    calls.clear()
    rt.retry_with_backoff(lambda: calls.append(1) or {"status": 429, "data": None, "retry_after": soon,
                                                      "exc": None}, max_retries=1, sleep_fn=sleeps.append)
    assert len(calls) == 2 and 15 <= sleeps[0] <= 26


# ── #63 本番に近い成約の場面（3件・2件・期限切れ・状態違い・同一性違い・出品を同時に） ──────────────────

def test_production_like_sold_scenario(clean_env):
    from src.collectors.api import ebay_insights as ei
    from src.market import sold_history as sh
    items = [
        _item(1, days=1, usd="1750.00"), _item(2, days=2, usd="1720.00"), _item(3, days=3, usd="1780.00"),
        _item(4, days=40, usd="1500.00"),                                     # 期限切れ（14日の期間の外）
        _item(5, cond="2000", usd="1300.00"),                                 # 整備品（混ぜない）
        _item(6, cond="3000", usd="1200.00"),                                 # 中古（新品と混ぜない）
        _item(7, title="Sony PlayStation 5 Slim CFI-2000 New", usd="500.00"),  # 同一性違い
        _item(8, sold=False, usd="1999.00"),                                  # 出品（成約日時なし）
    ]
    recs, rej = ei.to_sold_records(items, product_id="prod_ps5_pro", resolver=P12._Resolver(), fx_rate=150.0,
                                   now=NOW, fx_meta={"source": "fixture", "observed_at": "2026-10-07"})
    assert rej == {"refurbished_condition": 1, "identity_unverified": 1, "no_sold_at": 1}
    assert {r.condition for r in recs} == {"new_unopened", "used"}
    assert all("fixture" in r.note for r in recs)                             # 為替の出どころを残す
    other = [replace(r, product_id="prod_gr4", identity="prod_gr4", item_url=r.item_url + "9")
             for r in recs if r.condition == "new_unopened"][:2]              # 別の商品は2件だけ
    obs = sh.median_observations(recs + other, NOW)
    med = [o for o in obs if o["sold_median_eligible"]]
    assert len(med) == 1 and med[0]["product_id"] == "prod_ps5_pro" and med[0]["sample_count"] == 3
    assert med[0]["price"] == 1750 * 150 and med[0]["condition"] == "new_unopened"
    ref = [o for o in obs if not o["sold_median_eligible"]]
    assert {o["product_id"] for o in ref} == {"prod_ps5_pro", "prod_gr4"}     # 中古1件・別商品2件は参考だけ
    assert sum(1 for o in ref if o["product_id"] == "prod_gr4") == 2
    assert all(o["condition"] != "new_unopened" for o in ref if o["product_id"] == "prod_ps5_pro")


def test_identity_mutation_rejects_model_mismatch(clean_env):
    from src.collectors.api import ebay_insights as ei
    good = _item(1)
    recs, _ = ei.to_sold_records([good], product_id="prod_ps5_pro", resolver=P12._Resolver(), fx_rate=150.0,
                                 now=NOW)
    assert len(recs) == 1
    bad = {**good, "title": "Sony PlayStation 5 Digital CFI-2016 New"}       # 型番違い
    recs, rej = ei.to_sold_records([bad], product_id="prod_ps5_pro", resolver=P12._Resolver(), fx_rate=150.0,
                                   now=NOW)
    assert recs == [] and rej == {"identity_unverified": 1}


def test_route_mutation_three_to_two(tmp_path):
    """3件 → 確定ルート1件。1件減らして2件 → 確定は消えて参考だけ。"""
    from src.market.sold_history import median_observations
    three = [P12._rec(1, 260000, 1), P12._rec(2, 255000, 2), P12._rec(3, 265000, 3)]
    for sub in ("a", "b"):
        (tmp_path / sub).mkdir()
    d3 = P12._routes(tmp_path / "a", P12._buy(*P12.RETAIL), median_observations(three, NOW))
    assert len(d3["main_routes"]) == 1 and d3["main_routes"][0]["sell_sample_count"] == 3
    d2 = P12._routes(tmp_path / "b", P12._buy(*P12.RETAIL), median_observations(three[:2], NOW))
    assert d2["main_routes"] == [] and len(d2["reference_routes"]) == 1


# ── #24・#26・#27 canary は履歴に書かない・合格の後だけ段階で書く・#28 冪等 ─────────────────────────

def test_canary_writes_report_but_not_history(script, clean_env):
    _all_gates(clean_env)
    _fake_api(script, clean_env, {"CFI-7000": [_item(1), _item(2), _item(3), _item(4, sold=False)]})
    assert script.main([]) == 0
    rep = json.loads(script.CANARY_PATH.read_text(encoding="utf-8"))
    assert rep["passed"] is True and rep["accepted"] == 3 and rep["returned"] == 4
    assert rep["rejection_reasons"] == {"no_sold_at": 1} and rep["licence"] == "CONFIRMED"
    assert rep["marketplace"] == "EBAY_US" and rep["query"] == "PlayStation 5 Pro CFI-7000"
    assert rep["sold_dates"]["first"] and rep["conditions"] == {"new_unopened": 3}
    assert len(rep["item_ids"]) == 3 and rep["price_range_jpy"] == [262500, 262500]
    assert not script.HISTORY_PATH.exists()                                  # canary は履歴に書かない
    assert json.loads(script.STATUS_PATH.read_text(encoding="utf-8"))["mode"] == "canary"


def test_canary_failure_is_not_passed(script, clean_env):
    _all_gates(clean_env)
    _fake_api(script, clean_env, {"CFI-7000": [_item(1, title="PS5 controller charging stand CFI-7000")]})
    script.main([])
    rep = json.loads(script.CANARY_PATH.read_text(encoding="utf-8"))
    assert rep["passed"] is False and rep["accepted"] == 0
    # 合格していないので、canary を外しても履歴には書かない（canary のまま）
    clean_env.setenv("EBAY_SOLD_CANARY", "false")
    assert script.is_canary_mode() is True


def test_history_after_canary_pass_is_idempotent(script, clean_env):
    _all_gates(clean_env, EBAY_SOLD_CANARY="false")
    script.CANARY_PATH.write_text(json.dumps({"passed": True, "product_id": "prod_ps5_pro"}), encoding="utf-8")
    page = {"CFI-7000": [_item(1), _item(2), _item(3)]}
    _fake_api(script, clean_env, page)
    script.main([])
    hist = json.loads(script.HISTORY_PATH.read_text(encoding="utf-8"))["records"]
    assert len(hist) == 3 and all(r["title"] == "" for r in hist)            # 取得元の商品名は保存しない
    roll = json.loads(script.ROLLOUT_PATH.read_text(encoding="utf-8"))
    assert roll["stages"]["1"]["passed"] is True and roll["stages"]["1"]["targets"] == ["prod_ps5_pro"]
    # 同じ出品をもう一度取っても増えない（同じ item ID）。ファイルも書き直さない（時刻だけの更新をしない）
    before = (script.HISTORY_PATH.read_text(encoding="utf-8"), script.ROLLOUT_PATH.read_text(encoding="utf-8"))
    script.main([])
    assert len(json.loads(script.HISTORY_PATH.read_text(encoding="utf-8"))["records"]) == 3
    assert (script.HISTORY_PATH.read_text(encoding="utf-8"), script.ROLLOUT_PATH.read_text(encoding="utf-8")) == before
    # 同じ出品の新しい成約（数量の多い出品）は置き換え（件数は増えない）
    _fake_api(script, clean_env, {"CFI-7000": [_item(1, days=0.5, usd="1800.00"), _item(2), _item(3)]})
    script.main([])
    recs = json.loads(script.HISTORY_PATH.read_text(encoding="utf-8"))["records"]
    assert len(recs) == 3 and max(r["sold_price"] for r in recs) == 1800 * 150


def test_licence_gate_blocks_history_write(script, clean_env):
    """ライセンスの確認が無ければ、canary の合格があっても履歴に書かない（通信もしない）。"""
    _all_gates(clean_env, EBAY_SOLD_CANARY="false", EBAY_SOLD_LICENSE_CONFIRMED="false")
    script.CANARY_PATH.write_text(json.dumps({"passed": True, "product_id": "prod_ps5_pro"}), encoding="utf-8")
    seen = _fake_api(script, clean_env, {"CFI-7000": [_item(1), _item(2), _item(3)]})
    script.main([])
    assert seen == [] and not script.HISTORY_PATH.exists()
    assert json.loads(script.STATUS_PATH.read_text(encoding="utf-8"))["status"] == "PENDING_LICENSE_CONFIRMATION"


def test_stage_gate_failure_does_not_write_history(script, clean_env):
    """段階の関門（重複・同一性の誤り・取得の失敗）を通らなければ、履歴に書かず段階も上げない。"""
    _all_gates(clean_env, EBAY_SOLD_CANARY="false")
    script.CANARY_PATH.write_text(json.dumps({"passed": True, "product_id": "prod_ps5_pro"}), encoding="utf-8")
    dup = _item(1)
    _fake_api(script, clean_env, {"CFI-7000": [dup, dict(dup)]})              # 同じ出品が2回（重複）
    script.main([])
    assert not script.HISTORY_PATH.exists()
    roll = json.loads(script.ROLLOUT_PATH.read_text(encoding="utf-8"))
    assert roll["stages"]["1"]["passed"] is False and roll["stages"]["1"]["gate"]["duplicates"] == 1
    clean_env.setenv("EBAY_SOLD_STAGE", "3")
    assert script.allowed_stage("3") == "1"                                  # 段階1を通っていない → 上げない


def test_canary_pass_is_tied_to_product(script, clean_env):
    """合格の後に canary の商品を変えたら、新しい商品で canary をやり直す（履歴に書かない）。"""
    clean_env.setenv("EBAY_SOLD_CANARY", "false")
    script.CANARY_PATH.write_text(json.dumps({"passed": True, "product_id": "prod_ps5_pro"}), encoding="utf-8")
    assert script.is_canary_mode() is False
    clean_env.setenv("EBAY_SOLD_CANARY_PRODUCT", "prod_x100vi")
    assert script.is_canary_mode() is True


def test_stage_gate_checks_identity_independently(script, clean_env):
    """resolver が通しても、取得元の商品名に型番・名前の目印が無ければ関門を通さない（レビュー M-2）。"""
    from src.market.sold_history import SoldRecord
    base = dict(product_id="prod_ps5_pro", source="ebay_insights", item_url="https://www.ebay.com/itm/395500000001",
                sold_price=262500, sold_at=_iso(1), condition="new_unopened", identity="prod_ps5_pro",
                identity_verified=True, observed_at=NOW.isoformat())
    ok = SoldRecord(**base, title="Sony PlayStation 5 Pro Console CFI-7000")
    assert script.stage_gate([ok], {}, {}, "")["passed"] is True
    wrong = SoldRecord(**base, title="Sony PlayStation 5 Slim Console CFI-2000")      # resolver の誤りを想定
    g = script.stage_gate([wrong], {}, {}, "")
    assert g["identity_errors"] == 1 and g["passed"] is False
    # 目印に一致しても型・版の違う語があれば通さない（Q3 43・GR IV HDF）
    q343 = SoldRecord(**{**base, "product_id": "prod_q3", "identity": "prod_q3"}, title="Leica Q3 43 Camera")
    hdf = SoldRecord(**{**base, "product_id": "prod_gr4", "identity": "prod_gr4"}, title="Ricoh GR IV HDF")
    assert script.stage_gate([q343], {}, {}, "")["identity_errors"] == 1
    assert script.stage_gate([hdf], {}, {}, "")["identity_errors"] == 1
    import re as _re
    assert any(_re.search(p, "sony alpha 1 ii body") for p in script.IDENTITY_MARKERS["prod_a1ii"])
    assert not any(_re.search(p, "camera 12 lens kit") for p in script.IDENTITY_MARKERS["prod_a1ii"])


def test_canary_product_override_only_within_staged(clean_env):
    m = _load(ROOT / "scripts" / "collect_ebay_sold.py", "p13_ces_override")
    clean_env.setenv("EBAY_SOLD_CANARY_PRODUCT", "prod_x100vi")
    assert m.canary_target()[0] == "prod_x100vi"
    clean_env.setenv("EBAY_SOLD_CANARY_PRODUCT", "prod_unknown_x")
    assert m.canary_target()[0] == "prod_ps5_pro"
    assert len(m.STAGED) == 10 and max(m.STAGE_SIZES.values()) == 10          # 全商品には広げない


# ── #72 CI の workflow ──────────────────────────────────────────────────

def test_workflow_has_safe_ebay_sold_step():
    wf = (ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    m = re.search(r"- name: eBay SOLD \(Marketplace Insights\)\n(.*?)(?=\n      - name: )", wf, re.S)
    assert m, "eBay SOLD のステップが無い"
    step = m.group(1)
    for need in ("python scripts/collect_ebay_sold.py", "continue-on-error: true",
                 "secrets.EBAY_CLIENT_ID", "secrets.EBAY_CLIENT_SECRET",
                 "vars.ENABLE_EBAY_API || 'false'", "vars.EBAY_INSIGHTS_APPROVED || 'false'",
                 "vars.EBAY_SOLD_LICENSE_CONFIRMED || 'false'", "vars.EBAY_SOLD_CANARY || 'true'",
                 "vars.EBAY_SOLD_STAGE || '1'", "vars.API_DRY_RUN || 'true'"):
        assert need in step, need
    assert wf.index("- name: eBay SOLD (Marketplace Insights)") < wf.index(
        "- name: Generate normalized price observations")
    commit = wf.split("- name: Commit and push", 1)[1]
    assert "exports/sold_history/" in commit
    assert "git pull --rebase --autostash origin main" in commit and "if ! git push origin main" in commit
    assert "-X theirs" not in commit and "git rebase --abort" in commit      # 人の変更を黙って上書きしない
    resale = re.search(r"- name: Collect resale prices\n(.*?)(?=\n      - name: )", wf, re.S).group(1)
    assert "vars.ENABLE_RAKUTEN_API || 'false'" in resale and "vars.ENABLE_YAHOO_API || 'false'" in resale


def test_deploy_check_phase13_passes_now():
    dc = _load(ROOT / "scripts" / "deploy_check.py", "p13_deploy_check_ok")
    res = {r["check"]: r for r in dc._check_phase13_ebay_sold()}
    assert res["ebay_sold_gates"]["level"] == "ok", res["ebay_sold_gates"]["message"]
    assert res["ebay_finding_api_removed"]["level"] == "ok", res["ebay_finding_api_removed"]["message"]


# ── 廃止された Finding API を呼ばない・楽天 / Yahoo の停止スイッチ ─────────────────────────────

def test_finding_api_is_never_called_even_with_client_id(clean_env, monkeypatch):
    import urllib.request
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: calls.append(a))
    clean_env.setenv("EBAY_CLIENT_ID", FAKE_ID)
    clean_env.setenv("EBAY_APP_ID", FAKE_ID)
    from src.collectors.api.market_apis import ebay_fetch_items
    assert ebay_fetch_items("PlayStation 5 Pro") is None
    from src.collectors.overseas import ebay_completed as ec
    monkeypatch.setattr(ec, "get_usd_jpy", lambda: (150.0, "fixture"))
    r = ec.EbayCompletedCollector().collect("prod_ps5_pro", "ps5_pro", ["PlayStation 5 Pro"])
    assert r.collector_method == "html_blocked" and r.price_jpy == 0
    assert calls == []


@pytest.mark.parametrize("api,key,fn", [("RAKUTEN", "RAKUTEN_APP_ID", "rakuten_ichiba_search"),
                                        ("YAHOO", "YAHOO_SHOPPING_APP_ID", "yahoo_shopping_search")])
def test_rakuten_yahoo_switch_off_means_no_network(clean_env, monkeypatch, api, key, fn):
    import urllib.request
    from src.collectors.api import official_apis as oa
    calls = []
    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: calls.append(a))
    monkeypatch.delenv(key, raising=False)
    assert getattr(oa, fn)("PlayStation 5 Pro") is None                      # キーなし → 通信0
    monkeypatch.setenv(key, "fake-key-123456")
    monkeypatch.delenv(f"ENABLE_{api}_API", raising=False)
    assert getattr(oa, fn)("PlayStation 5 Pro") is None                      # 明示が無い → 通信0
    for v in ("false", "disabled"):
        monkeypatch.setenv(f"ENABLE_{api}_API", v)
        assert getattr(oa, fn)("PlayStation 5 Pro") is None                  # 停止・知らない値 → 通信0
    assert calls == []
    monkeypatch.setenv(f"ENABLE_{api}_API", "true")
    assert getattr(oa, "rakuten_available" if api == "RAKUTEN" else "yahoo_shopping_available")() is True


# ── TCG: robots.txt に到達できないことと禁止を混ぜない ───────────────────────────────────

@pytest.mark.parametrize("robots,blocked,unreachable,state", [
    ("disallowed", True, False, "SOURCE_BLOCKED"),
    ("unknown", False, True, "SOURCE_UNREACHABLE"),
])
def test_tcg_robots_unreachable_is_not_blocked(robots, blocked, unreachable, state):
    from src.collectors.tcg.base import BaseTcgCollector
    from src.tcg.lottery.registry import STATE_LABELS, source_state

    class _R:
        def robots_status(self, url):
            return robots

        def get_crawl_delay(self, url):
            return None
    c = BaseTcgCollector()
    c._robots = _R()
    assert c._fetch("https://example.com/news") is None                     # どちらも取りに行かない
    assert bool(c.health.get("blocked")) is blocked and bool(c.health.get("unreachable")) is unreachable
    assert c.health["robots"] == ("robots_disallowed" if robots == "disallowed" else "robots_unreachable")
    st = source_state({"adapter": None}, c.health, 0)
    assert st == state and STATE_LABELS[st] == ("アクセス拒否" if blocked else "接続できない")
    reason = c.funnel.status_reason()
    assert ("robots.txt に到達できない" in reason) is unreachable and ("アクセス拒否" in reason) is blocked


def test_rate_limit_stops_remaining_products(script, clean_env):
    """1商品目で 429（長い待ち）が返ったら、残りの商品へ送らない（監査 M-1）。HTTP の回数で上限を数える（L-1）。"""
    _all_gates(clean_env, EBAY_SOLD_CANARY="false", EBAY_SOLD_STAGE="3")
    script.CANARY_PATH.write_text(json.dumps({"passed": True, "product_id": "prod_ps5_pro"}), encoding="utf-8")
    script.ROLLOUT_PATH.write_text(json.dumps({"stages": {"1": {"passed": True}}}), encoding="utf-8")
    _fake_api(script, clean_env, {})
    later = format_datetime(datetime.now(timezone.utc) + timedelta(minutes=10), usegmt=True)
    seen = []
    clean_env.setattr(script, "_http_get", lambda url, h: seen.append(url) or {
        "status": 429, "data": None, "retry_after": later, "exc": None})
    assert script.main([]) == 0
    assert len(seen) == 1                                                    # 2商品目・3商品目へは送らない
    body = json.loads(script.STATUS_PATH.read_text(encoding="utf-8"))
    assert body["status"] == "RATE_LIMITED" and not script.HISTORY_PATH.exists()


def test_request_budget_counts_retries(clean_env):
    from src.collectors.api import ebay_insights as ei
    calls = []

    def http_get(url, headers):
        calls.append(url)
        return {"status": 503, "data": None, "retry_after": None, "exc": None}
    budget = [ei.MAX_REQUESTS_PER_RUN]
    ei.collect("prod_ps5_pro", "PS5 Pro", resolver=P12._Resolver(), now=NOW, fx_rate=150.0, http_get=http_get,
               token="t", request_budget=budget, sleep_fn=lambda s: None)
    assert len(calls) == 3 and budget == [ei.MAX_REQUESTS_PER_RUN - 3]       # 再試行の分も数える
    calls.clear()
    budget = [1]
    ei.collect("prod_ps5_pro", "PS5 Pro", resolver=P12._Resolver(), now=NOW, fx_rate=150.0, http_get=http_get,
               token="t", request_budget=budget, sleep_fn=lambda s: None)
    assert len(calls) == 1 and budget == [0]                                 # 上限ちょうどでも超えない

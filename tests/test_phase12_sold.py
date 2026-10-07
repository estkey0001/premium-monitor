"""Phase 12（売却データ: SOLD・SOLD_MEDIAN・eBay Marketplace Insights）のテスト。

本番の eBay は資格情報が無い（PENDING_USER_CONFIGURATION）ので、応答の形は fixture で確かめる。
各テストには、誤りを入れると失敗する否定対照も付ける。
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST).replace(microsecond=0)


def _load_script(name: str):
    spec = importlib.util.spec_from_file_location(f"p12s_{name}", ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _rec(i=1, price=260000, days=1.0, cond="new_unopened", pid="prod_ps5_pro", **kw):
    from src.market.sold_history import SoldRecord
    base = dict(product_id=pid, source="ebay_insights", item_url=f"https://www.ebay.com/itm/39{i:07d}11",
                sold_price=price, sold_at=(NOW - timedelta(days=days)).isoformat(), condition=cond,
                identity=pid, identity_verified=True, observed_at=NOW.isoformat())
    base.update(kw)
    return SoldRecord(**base)


# ── SOLD の1件の条件 ───────────────────────────────────────────────────────

def test_valid_sold_record():
    from src.market.sold_history import record_reasons
    assert record_reasons(_rec()) == ()


@pytest.mark.parametrize("change,reason", [
    ({"sold_at": ""}, "no_sold_at"),                                              # 成約日時なし（取得時刻で代用しない）
    ({"item_url": "https://www.ebay.com/sch/i.html?_nkw=ps5"}, "no_item_url"),      # 検索結果
    ({"item_url": "https://www.ebay.com/itm/00000001"}, "dummy_url"),
    ({"identity_verified": False}, "identity_unverified"),
    ({"identity": ""}, "identity_unverified"),
    ({"condition": "unknown"}, "unknown_condition"),
    ({"sold_price": 0}, "invalid_price"),
    ({"sold_at": (NOW + timedelta(days=5)).isoformat()}, "sold_at_in_future"),
])
def test_invalid_sold_record_mutations(change, reason):
    from src.market.sold_history import record_reasons
    assert reason in record_reasons(replace(_rec(), **change))


def test_sold_dedupe_and_idempotent_reimport():
    from src.market.sold_history import merge
    a = _rec(1)
    h, st = merge([], [a, _rec(2), _rec(3)])
    assert st["added"] == 3
    # 同じ成約（同じ取得元・商品ページ・成約日時）をもう一度取っても足さない。observed_at も新しくしない
    again = replace(a, observed_at=(NOW + timedelta(hours=5)).isoformat(),
                    item_url=a.item_url + "?hash=item123")
    h2, st2 = merge(h, [again])
    assert st2 == {"added": 0, "updated": 0, "duplicate": 1, "rejected": {}} and len(h2) == 3
    assert h2[0].observed_at == a.observed_at
    # 使えない成約は履歴に入れない（理由を数える）
    h3, st3 = merge(h2, [replace(_rec(9), sold_at="")])
    assert len(h3) == 3 and st3["rejected"] == {"no_sold_at": 1}


def test_sold_history_persists_across_runs(tmp_path):
    from src.market import sold_history as sh
    p = tmp_path / "sold.json"
    h, _ = sh.merge([], [_rec(1), _rec(2)])
    sh.save(h, NOW, p)
    back = sh.load(p)
    assert back == h
    h2, st = sh.merge(back, [_rec(1), _rec(3)])           # 次の実行: 1件は重複、1件は新規
    assert st["added"] == 1 and st["duplicate"] == 1 and len(h2) == 3
    assert sh.load(tmp_path / "none.json") == []


# ── SOLD_MEDIAN ─────────────────────────────────────────────────────────

def test_median_needs_three_samples_and_period():
    from src.market.sold_history import median_observations, median_stats
    three = [_rec(1, 260000, 1), _rec(2, 255000, 2), _rec(3, 265000, 3)]
    obs = median_observations(three, NOW)
    assert len(obs) == 1
    o = obs[0]
    assert o["price"] == 260000 and o["sample_count"] == 3 and o["sold_median_eligible"] is True
    assert o["sold_period_start"] and o["sold_period_end"] and o["canonical_price_type"] == "SOLD_MEDIAN"
    assert o["observed_at"] == three[0].sold_at                    # 最新の成約日時（取得時刻ではない）
    # 否定対照: 2件なら中央値を作らない（成約1件ずつの参考の行だけ。2件の中央値 257,500 は出さない。監査 H4）
    two = median_observations(three[:2], NOW)
    assert sorted(o["price"] for o in two) == [255000, 260000]
    assert all(o["sold_median_eligible"] is False and o["canonical_price_type"] == "SOLD"
               and o["sample_count"] == 1 and o["item_url"].startswith("https://www.ebay.com/itm/")
               and "中央値" not in o["source_name"] for o in two)
    assert median_stats(three[:2], NOW)[0]["status"] == "insufficient_samples"


def test_stale_sold_outside_period_is_excluded():
    from src.market.normalized_prices import STALE_DAYS
    from src.market.sold_history import median_observations, median_stats
    recs = [_rec(1, 260000, 1), _rec(2, 255000, 2), _rec(3, 900000, STALE_DAYS + 3)]   # 1件は期間外
    st = median_stats(recs, NOW)[0]
    assert st["sample_count"] == 2 and st["status"] == "insufficient_samples"
    assert all(o["sold_median_eligible"] is False for o in median_observations(recs, NOW))


def test_conditions_are_not_mixed():
    from src.market.sold_history import median_stats
    recs = [_rec(1, 260000, 1), _rec(2, 255000, 2), _rec(3, 150000, 2, cond="used_b"),
            _rec(4, 140000, 3, cond="used_a")]
    by = {s["condition_family"]: s for s in median_stats(recs, NOW)}
    assert by["new"]["sample_count"] == 2 and by["used"]["sample_count"] == 2


def test_listing_never_counts_as_sold():
    """出品（LISTING）は成約中央値の件数にも値にも入らない（price_types の正本）。"""
    from src.market import price_types as pt
    s = [pt.MarketSample(price=100, price_type=pt.LISTING, identity="x", item_url="https://www.ebay.com/itm/123456789",
                         sold_at=NOW.isoformat()) for _ in range(5)]
    st = pt.sold_median(s, identity="x", period_start=NOW - timedelta(days=14), period_end=NOW)
    assert st["sample_count"] == 0 and st["status"] == "insufficient_samples"


def test_median_observation_identity_follows_samples():
    from src.market.normalized_prices import make_observation
    kw = dict(product_id="p", price_role="sell", price_type="overseas_sold_price", condition="new_unopened",
              price=1000, observed_at=NOW.isoformat(), confidence="high", link_type="none",
              extraction_method="sold_median", sample_count=3, sold_median_eligible=True,
              sold_period_start=(NOW - timedelta(days=14)).isoformat(), sold_period_end=NOW.isoformat())
    assert make_observation(NOW, **kw, sold_median_identity_verified=True)["is_exact_product_match"] is True
    # 否定対照: 標本の同一性を確かめていない集計は照合済みにしない
    assert make_observation(NOW, **kw)["is_exact_product_match"] is False


# ── ルート（RETAIL_TO_SOLD_MEDIAN・SECONDARY_TO_SOLD_MEDIAN） ──────────────────

def _buy(url, price_type, source, market):
    from src.market.normalized_prices import _extraction_method, classify_link_type, make_observation
    o = make_observation(NOW, product_id="prod_ps5_pro", product_name="PlayStation 5 Pro", source_id=source,
                         source_name=source, market_type=market, price_role="buy", price_type=price_type,
                         condition="new_unopened", price=137980,
                         observed_at=(NOW - timedelta(hours=1)).isoformat(), confidence="high",
                         source_url=url, item_url=url, link_type=classify_link_type(url, True, "buy"),
                         extraction_method=_extraction_method("auto_scraped"),
                         price_context="PlayStation 5 Pro CFI-7100B01")
    o["shipping"] = 0                 # 送料・購入時の費用が分かっている（fixture）
    o["required_cost"] = 0
    return o


def _routes(tmp_path, buy, sells):
    m = _load_script("generate_profit_routes")
    (tmp_path / "npo.json").write_text(json.dumps({"observations": [buy] + sells}, ensure_ascii=False),
                                       encoding="utf-8")
    m.NPO_PATH = tmp_path / "npo.json"
    m.OUT_DIR = tmp_path / "out"
    m.main()
    return json.loads((tmp_path / "out" / "latest.json").read_text(encoding="utf-8"))


RETAIL = ("https://www.amazon.co.jp/dp/B0DGY63Z2H", "shop_sale_price", "Amazon", "domestic_retail")
SECONDARY = ("https://page.auctions.yahoo.co.jp/jp/auction/x123456789", "flea_listing_price", "ヤフオク", "flea")


@pytest.mark.parametrize("buy_args", [RETAIL, SECONDARY], ids=["retail", "secondary"])
def test_three_sold_make_one_confirmed_route(tmp_path, buy_args):
    from src.content.ui import opportunity as opp
    from src.market.sold_history import median_observations
    sells = median_observations([_rec(1, 260000, 1), _rec(2, 255000, 2), _rec(3, 265000, 3)], NOW)
    d = _routes(tmp_path, _buy(*buy_args), sells)
    assert len(d["main_routes"]) == 1 and not d.get("excluded_routes")
    r = d["main_routes"][0]
    assert r["buy_price"] == 137980 and r["sell_price"] == 260000 and r["sell_sample_count"] == 3
    assert r["sell_period_start"] and r["sell_period_end"] and r["sell_canonical_type"] == "SOLD_MEDIAN"
    # 費用（海外の手数料 13%+4%+3%・送料 5,000・安全余裕 5,000）は生成側の計算のまま
    assert r["net_profit"] == 260000 - 137980 - round(260000 * 0.13) - round(260000 * 0.04) \
        - round(260000 * 0.03) - 5000 - 5000
    assert opp.route_reasons(r, NOW) == ()


def test_two_sold_make_reference_only(tmp_path):
    from src.market.sold_history import median_observations
    sells = median_observations([_rec(1, 260000, 1), _rec(2, 255000, 2)], NOW)
    d = _routes(tmp_path, _buy(*RETAIL), sells)
    assert d["main_routes"] == [] and len(d["reference_routes"]) == 1


def test_unverified_buy_identity_blocks_route(tmp_path):
    """否定対照: 仕入れ側の同一性が未確認なら確定にしない。"""
    from src.market.sold_history import median_observations
    sells = median_observations([_rec(1, 260000, 1), _rec(2, 255000, 2), _rec(3, 265000, 3)], NOW)
    b = _buy(*RETAIL)
    b["is_exact_product_match"] = False
    d = _routes(tmp_path, b, sells)
    assert d["main_routes"] == []


def test_marketplace_item_urls_are_item_level():
    from src.market.normalized_prices import classify_link_type
    assert classify_link_type("https://page.auctions.yahoo.co.jp/jp/auction/x123456789", True, "buy") == "item"
    assert classify_link_type("https://jp.mercari.com/item/m12345678901", False, "buy") == "item_unverified"
    # 検索結果・ダミーは商品ページにしない
    assert classify_link_type("https://auctions.yahoo.co.jp/search/search?p=ps5", True, "buy") == "search"
    assert classify_link_type("https://jp.mercari.com/item/m00000000001", True, "buy") != "item"


def test_build_observations_reads_sold_history(tmp_path, monkeypatch):
    """成約の履歴があるときだけ成約中央値の観測が加わる（空なら何も足さない）。"""
    from src.db.database import Database
    from src.market import normalized_prices as npm
    from src.market import sold_history as sh
    db = Database(str(tmp_path / "t.db"))
    db.init_schema()
    db.connection.execute("INSERT INTO products (id, name, genre, brand, retail_price, is_active, created_at, "
                          "updated_at) VALUES ('prod_ps5_pro', 'PS5 Pro', 'game_console', 'Sony', 137980, 1, 'x', 'x')")
    db.connection.commit()
    db.connection.row_factory = __import__("sqlite3").Row
    monkeypatch.setattr(sh, "load", lambda path=None: [_rec(1, 260000, 1), _rec(2, 255000, 2), _rec(3, 265000, 3)])
    med = [r for r in npm.build_observations(db.connection, NOW) if r.get("extraction_method") == "sold_median"]
    assert len(med) == 1 and med[0]["product_name"] == "PS5 Pro" and med[0]["sold_median_eligible"]
    # 否定対照: 履歴が空なら成約中央値の観測は無い
    monkeypatch.setattr(sh, "load", lambda path=None: [])
    assert not [r for r in npm.build_observations(db.connection, NOW) if r.get("extraction_method") == "sold_median"]


# ── eBay Marketplace Insights（資格情報なし・fixture） ───────────────────────

@pytest.fixture
def no_ebay_env(monkeypatch):
    for k in ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_APP_ID", "ENABLE_EBAY_API", "API_DRY_RUN",
              "EBAY_API_STAGE", "EBAY_INSIGHTS_APPROVED", "EBAY_SOLD_LICENSE_CONFIRMED", "EBAY_SOLD_CANARY",
              "EBAY_SOLD_CANARY_PRODUCT", "EBAY_SOLD_STAGE"):
        monkeypatch.delenv(k, raising=False)


def test_ebay_not_configured_is_pending(no_ebay_env, monkeypatch):
    from src.collectors.api import ebay_insights as ei
    assert ei.status() == ei.ST_PENDING and ei.token_request() is None
    # App ID だけでは足りない（成約の API はクライアントの秘密も要る）
    monkeypatch.setenv("EBAY_APP_ID", "app-only-123456")
    assert ei.status() == ei.ST_PENDING
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "sec-123456789")
    # Phase 13: 資格情報だけでは足りない（承認 → ライセンスの確認が要る）
    assert ei.status() == ei.ST_PENDING_APPROVAL
    monkeypatch.setenv("EBAY_INSIGHTS_APPROVED", "true")
    assert ei.status() == ei.ST_PENDING_LICENSE
    monkeypatch.setenv("EBAY_SOLD_LICENSE_CONFIRMED", "true")
    assert ei.status() == ei.ST_DISABLED                    # 有効にすると明示していなければ使わない
    monkeypatch.setenv("ENABLE_EBAY_API", "true")
    assert ei.status() == ei.ST_OK
    monkeypatch.setenv("ENABLE_EBAY_API", "false")
    assert ei.status() == ei.ST_DISABLED                    # 停止スイッチを守る
    monkeypatch.setenv("ENABLE_EBAY_API", "true")
    monkeypatch.setenv("API_DRY_RUN", "1")
    assert ei.status() == ei.ST_DRY_RUN


def test_ebay_stage_needs_canary_pass(no_ebay_env, monkeypatch, tmp_path, capsys):
    """段階を上げても、canary の合格の記録が無ければ1商品だけ。

    Phase 13: canary に合格しても一気に広げない。EBAY_SOLD_CANARY=false の明示と、前の段階の合格
    （rollout.json）があって初めて 1 → 3 → 10 商品と上がる。10商品より先には広げない。
    """
    m = _load_script("collect_ebay_sold")
    monkeypatch.setattr(m, "CANARY_PATH", tmp_path / "canary.json")
    monkeypatch.setattr(m, "ROLLOUT_PATH", tmp_path / "rollout.json")
    monkeypatch.setenv("EBAY_API_STAGE", "all")
    monkeypatch.setenv("EBAY_SOLD_STAGE", "10")
    monkeypatch.setenv("EBAY_SOLD_CANARY", "false")

    def _plan():
        assert m.main(["--dry-run"]) == 0
        return [r["product_id"] for r in json.loads(capsys.readouterr().out)["requests"]]
    assert _plan() == ["prod_ps5_pro"]                     # canary の合格なし → canary の1商品
    (tmp_path / "canary.json").write_text(json.dumps({"passed": True, "product_id": "prod_ps5_pro"}), encoding="utf-8")
    assert len(_plan()) == 1                               # 合格しても、段階1を通るまでは1商品
    (tmp_path / "rollout.json").write_text(json.dumps({"stages": {"1": {"passed": True}}}), encoding="utf-8")
    assert len(_plan()) == 3                               # 段階1を通った → 3商品まで
    (tmp_path / "rollout.json").write_text(
        json.dumps({"stages": {"1": {"passed": True}, "3": {"passed": True}}}), encoding="utf-8")
    assert len(_plan()) == 10 == len(m.STAGED)             # 10商品が上限（全商品には広げない）
    monkeypatch.setenv("EBAY_SOLD_STAGE", "all")
    assert len(_plan()) == 1                               # 知らない段階は1商品


def test_ebay_request_builder():
    from src.collectors.api import ebay_insights as ei
    url, headers = ei.build_search_request(q="PS5 Pro", sold_from=NOW - timedelta(days=90), sold_to=NOW,
                                           limit=999, offset=200)
    assert url.startswith(ei.SEARCH_URL + "?")
    assert "limit=200" in url and "offset=200" in url                       # 上限200
    assert "lastSoldDate:[" in url and "conditionIds:{1000}" in url
    assert "Authorization" not in headers and headers["X-EBAY-C-MARKETPLACE-ID"] == "EBAY_US"
    with pytest.raises(ValueError):
        ei.build_search_request()


def test_secrets_are_redacted(no_ebay_env, monkeypatch):
    from src.collectors.api import ebay_insights as ei
    monkeypatch.setenv("EBAY_CLIENT_ID", "MyClientId-ABCDEF")
    monkeypatch.setenv("EBAY_CLIENT_SECRET", "SuperSecretValue-123")
    url, headers, body = ei.token_request()
    assert headers["Authorization"].startswith("Basic ")
    text = ("Authorization: Bearer v^1.1#i^1#abc.def Basic QWxhZGRpbjpvcGVu access_token=eyJabc "
            "client_secret: SuperSecretValue-123 MyClientId-ABCDEF")
    red = ei.redact(text)
    for secret in ("v^1.1#i^1#abc.def", "QWxhZGRpbjpvcGVu", "eyJabc", "SuperSecretValue-123", "MyClientId-ABCDEF"):
        assert secret not in red
    plan = ei.dumps_safe(ei.dry_run_plan([("prod_ps5_pro", "PS5 Pro")], NOW))
    assert "SuperSecretValue-123" not in plan and "MyClientId-ABCDEF" not in plan and "Basic" not in plan


# eBay の応答の形（item_sales/search。値は fixture）
EBAY_PAGE1 = {
    "total": 6, "offset": 0, "limit": 3, "next": "https://api.ebay.com/...offset=3",
    "itemSales": [
        {"itemId": "v1|395512345678|0", "title": "Sony PlayStation 5 Pro Console CFI-7000 2TB New Sealed",
         "itemWebUrl": "https://www.ebay.com/itm/395512345678?hash=x", "conditionId": "1000",
         "lastSoldDate": (NOW - timedelta(days=1)).astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
         "lastSoldPrice": {"value": "1750.00", "currency": "USD"}},
        {"itemId": "v1|395512345679|0", "title": "PS5 Pro CFI-7000 New",              # 成約日時なし
         "itemWebUrl": "https://www.ebay.com/itm/395512345679", "conditionId": "1000",
         "lastSoldPrice": {"value": "1700.00", "currency": "USD"}},
        {"itemId": "v1|395512345680|0", "title": "PS5 Pro controller charging stand",   # 付属品
         "itemWebUrl": "https://www.ebay.com/itm/395512345680", "conditionId": "1000",
         "lastSoldDate": NOW.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
         "lastSoldPrice": {"value": "40.00", "currency": "USD"}},
    ]}
EBAY_PAGE2 = {"total": 6, "offset": 3, "limit": 3, "itemSales": [
    {"itemId": "v1|395512345681|0", "title": "Sony PlayStation 5 Pro Console CFI-7000 New",
     "itemWebUrl": "https://www.ebay.com/itm/395512345681", "conditionId": "9999",            # 状態不明
     "lastSoldDate": NOW.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
     "lastSoldPrice": {"value": "1720.00", "currency": "USD"}}]}


class _Resolver:
    """ProductIdentityResolver の代わり（タイトルに CFI-7000 があり付属品語が無いときだけ同じ商品）。"""

    def resolve(self, source_title="", expected_product_id=None, **kw):
        from types import SimpleNamespace
        ok = "CFI-7000" in source_title and "controller" not in source_title.lower()
        return SimpleNamespace(matched_product_id=expected_product_id if ok else None,
                               identity_confidence="high" if ok else "low",
                               accessory_flag="controller" in source_title.lower(),
                               capacity_match=None, model_match=ok)


def test_ebay_canary_fixture_parses_only_valid_sold(no_ebay_env):
    from src.collectors.api import ebay_insights as ei
    calls = []

    def http_get(url, headers):
        calls.append((url, headers))
        assert headers["Authorization"] == "Bearer TOKEN-x"
        return {"status": 200, "data": EBAY_PAGE1 if "offset=0" in url else EBAY_PAGE2,
                "retry_after": None, "exc": None}

    recs, rej = ei.collect("prod_ps5_pro", "PS5 Pro CFI-7000", resolver=_Resolver(), now=NOW, fx_rate=150.0,
                           http_get=http_get, token="TOKEN-x")
    assert len(calls) == 2                                          # 次のページまで（MAX_PAGES 以内）
    assert len(recs) == 1
    r = recs[0]
    assert r.item_url == "https://www.ebay.com/itm/395512345678" and r.sold_price == 262500
    assert r.condition == "new_unopened" and r.identity_verified and r.sold_at
    assert rej.get("no_sold_at") == 1 and rej.get("identity_unverified") == 1 and rej.get("unknown_condition") == 1


def test_ebay_429_is_not_retried_forever(no_ebay_env):
    from src.collectors.api import ebay_insights as ei
    calls, sleeps = [], []

    def http_get(url, headers):
        calls.append(url)
        return {"status": 429, "data": None, "retry_after": 1, "exc": None}

    recs, rej = ei.collect("prod_ps5_pro", "PS5 Pro", resolver=_Resolver(), now=NOW, fx_rate=150.0,
                           http_get=http_get, token="t", sleep_fn=sleeps.append)
    assert recs == [] and len(calls) <= 3 and any(k.startswith("request_") for k in rej)


def test_ebay_request_budget_is_shared(no_ebay_env):
    from src.collectors.api import ebay_insights as ei
    calls = []

    def http_get(url, headers):
        calls.append(url)
        return {"status": 200, "data": EBAY_PAGE1, "retry_after": None, "exc": None}

    budget = [1]
    ei.collect("prod_ps5_pro", "PS5 Pro", resolver=_Resolver(), now=NOW, fx_rate=150.0, http_get=http_get,
               token="t", request_budget=budget)
    ei.collect("prod_gr4", "GR IV", resolver=_Resolver(), now=NOW, fx_rate=150.0, http_get=http_get,
               token="t", request_budget=budget)
    assert len(calls) == 1 and budget == [0]


def test_ebay_script_dry_run_without_credentials(no_ebay_env, capsys):
    m = _load_script("collect_ebay_sold")
    assert m.main(["--dry-run"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["status"] == "PENDING_USER_CONFIGURATION" and out["credentials_present"] is False
    assert [r["product_id"] for r in out["requests"]] == ["prod_ps5_pro"]       # canary は1商品だけ


# ── 本番に近い場面（#66）・ルートが0件の日（#67）・ルートがある日（#68）の deploy-check ──────────

def _p10():
    spec = importlib.util.spec_from_file_location("ui_phase10_for_p12", ROOT / "tests" / "test_ui_phase10.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _production_like_routes(tmp_path) -> dict:
    """PS5 Pro: 成約3件（＋期間外の古い成約1件）→ 確定ルート。GR IV: 成約2件 → 参考ルート。
    出品（LISTING）は仕入れ側の観測にだけあり、売値にしない。"""
    from src.market.normalized_prices import _extraction_method, classify_link_type, make_observation
    from src.market.sold_history import median_observations
    sold = [_rec(1, 260000, 1), _rec(2, 255000, 2), _rec(3, 265000, 3),
            _rec(4, 990000, 40),                                                # 期間外の古い成約（使わない）
            _rec(5, 300000, 1, pid="prod_gr4"), _rec(6, 310000, 2, pid="prod_gr4")]
    sells = median_observations(sold, NOW)
    buy_ps5 = _buy(*RETAIL)
    gr_url = "https://page.auctions.yahoo.co.jp/jp/auction/g987654321"
    buy_gr4 = make_observation(NOW, product_id="prod_gr4", product_name="RICOH GR IV", source_id="src_yahoo_auction",
                               source_name="ヤフオク", market_type="flea", price_role="buy",
                               price_type="flea_listing_price", condition="new_unopened", price=180000,
                               observed_at=(NOW - timedelta(hours=2)).isoformat(), confidence="high",
                               source_url=gr_url, item_url=gr_url, link_type=classify_link_type(gr_url, True, "buy"),
                               extraction_method=_extraction_method("auto_scraped"), price_context="RICOH GR IV")
    buy_gr4["shipping"] = 0
    buy_gr4["required_cost"] = 0
    # 出品価格（海外の出品）は売値にならない
    listing = make_observation(NOW, product_id="prod_ps5_pro", source_id="src_ebay", source_name="eBay 出品",
                               market_type="overseas", price_role="buy", price_type="overseas_listing_price",
                               condition="new_unopened", price=400000, observed_at=NOW.isoformat(),
                               confidence="medium", link_type="none", extraction_method="manual")
    m = _load_script("generate_profit_routes")
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "npo.json").write_text(json.dumps({"observations": [buy_ps5, buy_gr4, listing] + sells},
                                                  ensure_ascii=False), encoding="utf-8")
    m.NPO_PATH = tmp_path / "npo.json"
    m.OUT_DIR = tmp_path / "out"
    m.main()
    return json.loads((tmp_path / "out" / "latest.json").read_text(encoding="utf-8"))


def test_production_like_scenario(tmp_path, monkeypatch):
    from src.collectors.polite import ShopCutoff
    d = _production_like_routes(tmp_path)
    main, ref = d["main_routes"], d["reference_routes"]
    assert [(r["product_id"], r["sell_sample_count"]) for r in main] == [("prod_ps5_pro", 3)]
    # 成約2件は中央値にしない。参考ルートの売値は成約1件の価格（件数 1）
    assert [(r["product_id"], r["sell_sample_count"], r["sell_price"]) for r in ref] == [("prod_gr4", 1, 310000)]
    assert all(r["sell_price"] != 400000 for r in main + ref)                   # 出品は売値にしない
    assert main[0]["sell_price"] == 260000                                         # 期間外の 990,000 は入らない
    # ブロックされた取得元は打ち切る・条件付きの買取価格（ネットオフ）は取らない
    sc = ShopCutoff()
    sc.record("iosys", False, "http_403")
    assert sc.is_cut("iosys")
    from src.collectors.buyback_netoff import NetoffCsvCollector
    conditional = ('<p class="pricelist_title">iPhone 17 Pro</p><p class="pricelist_capacity">256GB</p>'
                   '<p class="pricelist_text">未開封品</p><p class="pricelist_num">159,600</p>'
                   '<p>※ 特典 適用後の買取価格です。</p>')
    assert NetoffCsvCollector()._parse_price(conditional, "iphone17pro256", "") is None


def test_deploy_check_with_sold_routes_adds_no_errors(tmp_path, monkeypatch):
    """成約中央値の確定ルート1件・参考ルート1件がある日も、ルートが無い日と比べて deploy-check の error が増えない。"""
    P10 = _p10()
    d = _production_like_routes(tmp_path / "gen")
    stamp = NOW.strftime("%Y-%m-%d %H:%M JST")
    base = P10._route_day(tmp_path, monkeypatch, {"main_routes": [], "reference_routes": [], "generated_at": stamp})
    routes = {"main_routes": d["main_routes"], "reference_routes": d["reference_routes"], "generated_at": stamp,
              "zero_route_diagnostics": {}}
    lv = P10._route_day(tmp_path, monkeypatch, routes, now=NOW)
    errors = {k for k, r in lv.items() if r["level"] == "error"}
    base_errors = {k for k, r in base.items() if r["level"] == "error"}
    assert errors <= base_errors, {k: lv[k]["message"][:160] for k in errors - base_errors}
    assert lv["lp_main_routes_shown"]["level"] == "ok" and "確定ルート（1件）" in lv["lp_main_routes_shown"]["message"]
    assert lv["sold_semantics"]["level"] == "ok" and lv["source_safety"]["level"] == "ok"
    assert lv["api_secret_safety"]["level"] == "ok"
    # ルートが0件の日も #844 などは ok（#67）
    assert base["sold_semantics"]["level"] == "ok"
    # 否定対照: 件数の足りない成約を売値にした確定ルートは #844 が error
    bad = dict(d["main_routes"][0], sell_sample_count=2)
    lv2 = P10._route_day(tmp_path, monkeypatch, dict(routes, main_routes=[bad]), now=NOW)
    assert lv2["sold_semantics"]["level"] == "error"


def test_median_without_period_is_not_eligible():
    """期間（開始・終了）の無い成約中央値は、件数が足りていても確定の売値にしない。"""
    from src.market import price_types as pt
    from src.market.normalized_prices import make_observation
    ok = {"price_type": pt.SOLD_MEDIAN, "status": "ok", "sample_count": 3,
          "period_start": (NOW - timedelta(days=14)).isoformat(), "period_end": NOW.isoformat()}
    assert pt.is_sold_median_eligible(ok)
    for k in ("period_start", "period_end"):
        assert not pt.is_sold_median_eligible(dict(ok, **{k: ""})), k
    o = make_observation(NOW, product_id="p", price_role="sell", price_type="overseas_sold_price",
                         condition="new_unopened", price=1000, observed_at=NOW.isoformat(), confidence="high",
                         sample_count=3, sold_median_eligible=True, sold_period_start="", sold_period_end="")
    assert o["sold_median_eligible"] is False

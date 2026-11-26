# -*- coding: utf-8 -*-
"""TCG の二次流通の価格の種類・人が確認した成約の台帳・想定利益（監査 H-1）の回帰固定。

変異的なケース: 出品を成約として入れる・sold_at 無し・1件だけ・単位違い・古い成約・料率不明 など。
"""
from datetime import datetime, timedelta

import pytest

from src.tcg import market_prices as mp
from src.tcg import secondary
from src.tcg.scoring import buy_now_signal

NOW = datetime(2026, 11, 26, 12, 0, tzinfo=mp.JST)
PID = "pokemon-test-box"
UNITS = {PID: "BOX"}
CFG = {"path": "x.csv", "min_samples": 3, "fresh_days": 14, "publish_market_names": False,
       "product_units": {}, "costs": {"outbound_shipping_jpy": 800, "payout_fee_jpy": {"mercari": 200}, "other_jpy": 0}}
FEES = {"mercari": {"rate": 0.10, "status": "CONFIRMED", "evidence_read_body": True},
        "rakuma": {"rate": None, "status": "UNKNOWN", "evidence_read_body": False},
        "yahoo_flea": {"rate": 0.05, "status": "UNVERIFIED", "evidence_read_body": False}}


def _row(**kw):
    base = {"product_id": PID, "market": "mercari", "price_kind": "SOLD", "price": "12000", "currency": "JPY",
            "sold_at": (NOW - timedelta(days=2)).isoformat(), "condition": "SEALED_SHRINK", "unit": "BOX",
            "source_url": "https://jp.mercari.com/item/m12345678901", "verified_at": (NOW - timedelta(days=1)).isoformat(),
            "note": ""}
    base.update(kw)
    return base


def _write(tmp_path, rows, header=mp.LEDGER_COLUMNS):
    p = tmp_path / "ledger.csv"
    lines = [",".join(header)] + [",".join(str(r.get(c, "")) for c in header) for r in rows]
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return p


def _three(tmp_path, prices=(12000, 12500, 13000), **kw):
    rows = [_row(price=str(p), source_url=f"https://jp.mercari.com/item/m1234567890{i + 1}", **kw)
            for i, p in enumerate(prices)]
    return _write(tmp_path, rows)


def _load(path):
    return mp.load_ledger(path, cfg=CFG, units=UNITS, now=NOW)


# ── 台帳の入口 ─────────────────────────────────────────────────────────

def test_missing_ledger_is_empty(tmp_path):
    res = _load(tmp_path / "none.csv")
    assert res.exists is False and res.records == [] and res.rejected == []


def test_ledger_path_env_override(tmp_path):
    p = tmp_path / "private.csv"
    assert mp.ledger_path(CFG, env={mp.LEDGER_ENV: str(p)}) == p
    assert mp.ledger_path(CFG, env={}) == mp.PROJECT_ROOT / "x.csv"


def test_valid_sold_row_is_accepted(tmp_path):
    res = _load(_write(tmp_path, [_row()]))
    assert len(res.records) == 1 and res.records[0].sale_phase == mp.ACTUAL_SALE


@pytest.mark.parametrize("kind", ["LISTING", "LISTING_LOW", "LISTING_HIGH", "BID", "BID_PRICE", "ASK",
                                  "BUYBACK_PRICE", "SOLD_MEDIAN", "flea_listing_price", "listing"])
def test_listing_kinds_are_not_accepted_as_sold(tmp_path, kind):
    res = _load(_write(tmp_path, [_row(price_kind=kind)]))
    assert res.records == []
    assert "not_a_sale_kind" in res.rejected[0]["reasons"]


def test_unknown_price_kind_rejected(tmp_path):
    res = _load(_write(tmp_path, [_row(price_kind="MARKET")]))
    assert res.records == [] and "unknown_price_kind" in res.rejected[0]["reasons"]


def test_sold_without_sold_at_rejected(tmp_path):
    res = _load(_write(tmp_path, [_row(sold_at="")]))
    assert res.records == [] and "no_sold_at" in res.rejected[0]["reasons"]


def test_sold_at_in_future_rejected(tmp_path):
    res = _load(_write(tmp_path, [_row(sold_at=(NOW + timedelta(days=3)).isoformat(),
                                       verified_at=(NOW + timedelta(days=3)).isoformat())]))
    assert res.records == [] and "sold_at_in_future" in res.rejected[0]["reasons"]


def test_without_verified_at_rejected(tmp_path):
    res = _load(_write(tmp_path, [_row(verified_at="")]))
    assert res.records == [] and "no_verified_at" in res.rejected[0]["reasons"]


def test_verified_before_sold_rejected(tmp_path):
    res = _load(_write(tmp_path, [_row(verified_at=(NOW - timedelta(days=5)).isoformat())]))
    assert "verified_before_sold" in res.rejected[0]["reasons"]


def test_unit_mismatch_rejected(tmp_path):
    res = _load(_write(tmp_path, [_row(unit="PACK")]))
    assert res.records == [] and "unit_mismatch" in res.rejected[0]["reasons"]


def test_unknown_product_unit_rejected(tmp_path):
    res = _load(_write(tmp_path, [_row(product_id="other-product")]))
    assert res.records == [] and "product_unit_unknown" in res.rejected[0]["reasons"]


@pytest.mark.parametrize("cond", ["", "UNKNOWN", "新品"])
def test_unknown_condition_rejected(tmp_path, cond):
    res = _load(_write(tmp_path, [_row(condition=cond)]))
    assert res.records == [] and "unknown_condition" in res.rejected[0]["reasons"]


def test_foreign_currency_not_converted(tmp_path):
    res = _load(_write(tmp_path, [_row(currency="USD", price="80")]))
    assert res.records == [] and "currency_not_jpy" in res.rejected[0]["reasons"]


@pytest.mark.parametrize("url,why", [
    ("", "no_source_url"),
    ("https://jp.mercari.com/search?keyword=box", "not_item_url"),
    ("https://jp.mercari.com/item/m00000000001", "dummy_url"),
    ("http://snkrdunk.example.jp/products/1", "dummy_url"),
    ("https://shop.example-card.jp/search?q=box", "not_item_url"),
    ("https://shop-card.jp/", "not_item_url"),
    ("http://shop-card.jp/item/123", "source_url_not_https"),
])
def test_source_url_must_be_item_page(tmp_path, url, why):
    res = _load(_write(tmp_path, [_row(source_url=url)]))
    assert res.records == [] and why in res.rejected[0]["reasons"]


def test_buyback_market_rejected(tmp_path):
    res = _load(_write(tmp_path, [_row(market="card_shop_buyback")]))
    assert res.records == [] and "buyback_is_not_a_sale" in res.rejected[0]["reasons"]


def test_duplicate_row_counted_once_and_verified_at_does_not_add(tmp_path):
    a = _row()
    b = _row(verified_at=NOW.isoformat())        # 確認日だけ新しい同じ成約
    res = _load(_write(tmp_path, [a, b]))
    assert len(res.records) == 1 and res.duplicates == 1


def test_conflicting_rows_for_same_page_dropped(tmp_path):
    res = _load(_write(tmp_path, [_row(price="12000"), _row(price="19000")]))
    assert res.records == [] and len(res.conflicts) == 1


def test_legacy_format_rows_unused(tmp_path):
    legacy = ("product_id", "product_name", "tcg", "source", "price", "shrink_status",
              "condition", "observed_at", "url", "note")
    p = tmp_path / "legacy.csv"
    p.write_text(",".join(legacy) + "\n"
                 + f"{PID},x,POKEMON,mercari,12000,SEALED_SHRINK,,2026-11-25,https://jp.mercari.com/item/m12345678901,\n",
                 encoding="utf-8")
    res = _load(p)
    assert res.records == [] and res.rejected[0]["reasons"] == ["legacy_format_no_price_kind"]


# ── 相場の要約 ─────────────────────────────────────────────────────────

def test_single_sale_is_reference_not_market(tmp_path):
    res = _load(_write(tmp_path, [_row()]))
    s = mp.sold_summary(res.records, PID, now=NOW, cfg=CFG)
    assert s[mp.SOLD_MEDIAN] is None and s["sold_status"] == mp.SOLD_INSUFFICIENT
    assert s[mp.LAST_SALE] == 12000 and s["label"] == "参考（1件）"


def test_three_fresh_sales_give_median(tmp_path):
    res = _load(_three(tmp_path))
    s = mp.sold_summary(res.records, PID, now=NOW, cfg=CFG)
    assert s[mp.SOLD_MEDIAN] == 12500 and s[mp.SOLD_COUNT] == 3 and s["sold_status"] == mp.SOLD_OK
    assert s["executable"] is False
    assert "markets" not in s and s["market_count"] == 1      # 既定ではサービス名を出さない


def test_old_sales_are_stale_even_if_recently_verified(tmp_path):
    old = (NOW - timedelta(days=30)).isoformat()
    res = _load(_three(tmp_path, sold_at=old, verified_at=NOW.isoformat()))
    assert len(res.records) == 3
    s = mp.sold_summary(res.records, PID, now=NOW, cfg=CFG)
    assert s[mp.SOLD_MEDIAN] is None and s["stale_excluded"] == 3 and s["sold_status"] == mp.SOLD_NONE


def test_preorder_and_early_sales_not_in_median(tmp_path):
    rows = [_row(price_kind=k, price="30000", source_url=f"https://jp.mercari.com/item/m9876543210{i}")
            for i, k in enumerate(["PREORDER_TRADE", "EARLY_SALE", "PREORDER_TRADE"])]
    res = _load(_write(tmp_path, rows))
    s = mp.sold_summary(res.records, PID, now=NOW, cfg=CFG)
    assert s[mp.SOLD_MEDIAN] is None and s[mp.SOLD_COUNT] == 0
    assert s["preorder_trade_count"] == 2 and s["early_sale_count"] == 1


def test_outlier_excluded_from_count(tmp_path):
    res = _load(_write(tmp_path, [_row(price=str(p), source_url=f"https://jp.mercari.com/item/m1234567890{i}")
                                  for i, p in enumerate((12000, 12500, 13000, 200000))]))
    s = mp.sold_summary(res.records, PID, now=NOW, cfg=CFG)
    assert s["outliers_excluded"] == 1 and s[mp.SOLD_MEDIAN] == 12500


def test_conditions_not_mixed(tmp_path):
    rows = [_row(condition="SHRINK_REMOVED", price=str(p), source_url=f"https://jp.mercari.com/item/m1234567890{i}")
            for i, p in enumerate((9000, 9200, 9400))]
    res = _load(_write(tmp_path, rows))
    assert mp.sold_summary(res.records, PID, now=NOW, cfg=CFG)[mp.SOLD_MEDIAN] is None
    assert mp.sold_summary(res.records, PID, condition="SHRINK_REMOVED", now=NOW, cfg=CFG)[mp.SOLD_MEDIAN] == 9200


def test_listing_reference_has_no_profit():
    obs = [{"product_id": PID, "price_kind": "LISTING", "price": 15000.0, "shrink_status": "SEALED_SHRINK"},
           {"product_id": PID, "price_kind": "LISTING", "price": 18000.0, "shrink_status": "SEALED_SHRINK"},
           {"product_id": PID, "price_kind": "SOLD", "price": 99999.0, "shrink_status": "SEALED_SHRINK"}]
    c = mp.listing_reference(obs, PID)
    assert (c[mp.LISTING_LOW], c[mp.LISTING_HIGH], c["listing_count"]) == (15000, 18000, 2)
    assert c["profit_yen"] is None and c["profit_status"] == mp.NOT_CALCULATED and c["executable"] is False


def test_snapshot_keeps_kinds_separate(tmp_path):
    res = _load(_three(tmp_path))
    snap = mp.market_snapshot(PID, records=res.records,
                              listings=[{"product_id": PID, "price_kind": "LISTING", "price": 20000.0}],
                              retail_price=7200, buyback_price=11000, bid_price=10000, now=NOW, cfg=CFG)
    assert set(mp.PRICE_KINDS) <= set(snap)
    assert snap[mp.SOLD_MEDIAN] == 12500 and snap[mp.LISTING_LOW] == 20000 and snap[mp.BUYBACK_PRICE] == 11000


# ── B 想定利益 ─────────────────────────────────────────────────────────

def _ok_summary(tmp_path):
    return mp.sold_summary(_load(_three(tmp_path)).records, PID, now=NOW, cfg=CFG)


def test_expected_profit_with_confirmed_costs(tmp_path):
    r = mp.expected_profit(_ok_summary(tmp_path), 7200, sell_market="mercari", cfg=CFG, fees=FEES)
    # 12500 − 7200 − 1250 − 800 − 200 − 0
    assert r["profit_yen"] == 3050 and r["status"] == mp.PROFITABLE
    assert r["executable"] is False and r["label"] == "想定"


@pytest.mark.parametrize("market", ["rakuma", "yahoo_flea", "snkrdunk"])
def test_unconfirmed_fee_rate_is_not_calculated(tmp_path, market):
    r = mp.expected_profit(_ok_summary(tmp_path), 7200, sell_market=market, cfg=CFG, fees=FEES)
    assert r["status"] == mp.NOT_CALCULATED and r["profit_yen"] is None
    assert "fee_rate_unconfirmed" in r["reasons"]


def test_unknown_shipping_is_not_zero(tmp_path):
    cfg = {**CFG, "costs": {**CFG["costs"], "outbound_shipping_jpy": None}}
    r = mp.expected_profit(_ok_summary(tmp_path), 7200, sell_market="mercari", cfg=cfg, fees=FEES)
    assert r["status"] == mp.NOT_CALCULATED and "shipping_unknown" in r["reasons"]


def test_unknown_payout_fee_is_not_zero(tmp_path):
    cfg = {**CFG, "costs": {**CFG["costs"], "payout_fee_jpy": {}}}
    r = mp.expected_profit(_ok_summary(tmp_path), 7200, sell_market="mercari", cfg=cfg, fees=FEES)
    assert r["status"] == mp.NOT_CALCULATED and "payout_fee_unknown" in r["reasons"]


def test_single_sale_gives_no_expected_profit(tmp_path):
    s = mp.sold_summary(_load(_write(tmp_path, [_row(price="50000")])).records, PID, now=NOW, cfg=CFG)
    r = mp.expected_profit(s, 7200, sell_market="mercari", cfg=CFG, fees=FEES)
    assert r["profit_yen"] is None and "sold_median_not_stable" in r["reasons"]


def test_default_config_never_calculates_profit(tmp_path):
    """既定の設定（送料・振込手数料が未確認）では、想定利益は必ず NOT_CALCULATED。"""
    r = mp.expected_profit(_ok_summary(tmp_path), 7200, sell_market="mercari")
    assert r["status"] == mp.NOT_CALCULATED


# ── secondary.py の経路（H-1） ─────────────────────────────────────────

def _event(premium):
    return {"source_type": "OFFICIAL", "status": "AVAILABLE_NOW", "stale": False, "premium": premium}


def test_listings_never_make_premium_or_buy_now():
    """出品（eBay 等）を何件入れても premium_percent は出ず、buy_now にならない。"""
    obs = [{"product_id": PID, "source": "ebay", "price": float(p), "shrink_status": "SEALED_SHRINK",
            "price_kind": "LISTING", "sale_phase": None} for p in (30000, 31000, 32000, 33000)]
    prem = secondary.premium_for_product(PID, 7200, obs, now=NOW)
    assert prem["premium_percent"] is None and prem["insufficient_samples"] is True
    assert prem["listing_reference"]["listing_count"] == 4
    assert prem["excluded_not_sold"] == 4 and prem["executable"] is False
    from src.tcg.models import ST_AVAILABLE_NOW
    ev = {**_event(prem), "status": ST_AVAILABLE_NOW}
    assert buy_now_signal(ev, prem)["buy_now"] is False


def test_untyped_observations_are_not_used():
    """price_kind の無い観測（旧形式）は成約として扱わない。"""
    obs = [{"product_id": PID, "source": "mercari", "price": float(p), "shrink_status": "SEALED_SHRINK"}
           for p in (30000, 31000, 32000)]
    assert secondary.premium_for_product(PID, 7200, obs, now=NOW)["premium_percent"] is None


def test_stale_sold_observations_not_used(tmp_path):
    p = _three(tmp_path, prices=(30000, 31000, 32000), sold_at=(NOW - timedelta(days=20)).isoformat(),
               verified_at=NOW.isoformat())
    obs = secondary.load_secondary_observations(p, now=NOW, units=UNITS)
    assert len(obs) == 3
    assert secondary.premium_for_product(PID, 7200, obs, now=NOW)["premium_percent"] is None


def test_verified_fresh_sales_give_premium(tmp_path):
    obs = secondary.load_secondary_observations(_three(tmp_path), now=NOW, units=UNITS)
    prem = secondary.premium_for_product(PID, 7200, obs, now=NOW)
    assert prem["market_median"] == 12500 and prem["premium_percent"] is not None
    assert prem["price_basis"] == mp.SOLD_MEDIAN and prem["sample_sources"] == []


def test_listing_csv_rows_do_not_reach_secondary(tmp_path):
    rows = [_row(price_kind="LISTING", price=str(p), source_url=f"https://jp.mercari.com/item/m1234567890{i}")
            for i, p in enumerate((30000, 31000, 32000))]
    assert secondary.load_secondary_observations(_write(tmp_path, rows), now=NOW, units=UNITS) == []


def test_ebay_observations_are_listings(monkeypatch):
    monkeypatch.setenv("ENABLE_EBAY_API", "true")
    monkeypatch.setenv("API_DRY_RUN", "false")
    monkeypatch.setenv("EBAY_APP_ID", "dummy")
    obs = secondary.fetch_ebay_observations(
        PID, "box", fetcher=lambda kw: [{"title": "Box sealed shrink", "listing_price_original": 100.0,
                                         "currency": "USD", "url": "https://www.ebay.com/itm/123", "condition": "New"}],
        fx_loader=lambda c: {"rate": 150.0})
    assert obs[0]["price_kind"] == "LISTING"


def test_repo_ledger_header_and_empty():
    """リポジトリの既定の台帳はヘッダだけ（値を作らない）。"""
    text = (mp.PROJECT_ROOT / "data" / "tcg_secondary_prices.csv").read_text(encoding="utf-8").strip().splitlines()
    assert text[0].split(",") == list(mp.LEDGER_COLUMNS) and len(text) == 1

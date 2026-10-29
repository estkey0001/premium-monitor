"""Market Research Coverage Wave 3: 仕入れ値の証拠（現金・ポイント・クーポン・キャンペーン）・Apple の部品番号の照会・TCG の質と検知の許容。

HTML は構造を保った合成の文字列。通信はしない。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from src.research import candidates as rc
from src.research import retail_lookup as rl
from src.tcg import event_quality as eq

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=JST)
FRESH = "2026-10-29T10:00:00+09:00"


# ── 価格の証拠 ───────────────────────────────────────────────────────────────────

def _e(**k):
    return {"name": "x", "price": 100000, "url": "u", "jan": "4900000000001", "model": "X", **k}


def test_points_are_never_subtracted_from_the_cash_price():
    pe = rl.price_evidence(_e(points=10000))
    assert pe["listed_price"] == 100000 and pe["effective_price"] == 100000 and pe["points"] == 10000   # 現金 100,000・ポイントは別
    assert pe["price_conditions"] == [] and pe["price_basis"] == rl.BASIS_UNCONDITIONAL


def test_cashback_is_kept_separate_and_not_a_discount():
    pe = rl.price_evidence(_e(cashback=5000))
    assert pe["effective_price"] == 100000 and pe["cashback"] == 5000


def test_immediate_unconditional_discount_is_applied_but_coupon_is_not():
    assert rl.price_evidence(_e(immediate_discount=3000))["effective_price"] == 97000
    pe = rl.price_evidence(_e(price=90000, required_coupon="会員限定 1万円クーポン", regular_price=100000))
    assert pe["effective_price"] == 100000 and rl.COND_COUPON in pe["price_conditions"] and pe["price_basis"] == rl.BASIS_REGULAR
    unknown = rl.price_evidence(_e(price=90000, required_coupon="アプリ限定クーポン"))
    assert unknown["effective_price"] == 90000 and unknown["price_basis"] == rl.BASIS_CONDITIONAL_UNKNOWN     # 通常価格が不明 → 高優先にしない


@pytest.mark.parametrize("field,cond", [("member_only", rl.COND_MEMBER), ("limited_quantity", rl.COND_LIMITED),
                                         ("campaign_conditions", rl.COND_CAMPAIGN), ("required_coupon", rl.COND_COUPON)])
def test_member_app_first_time_and_limited_offers_are_conditional(field, cond):
    value = True if field in ("member_only", "limited_quantity") else "条件あり"
    pe = rl.price_evidence(_e(price=80000, regular_price=100000, **{field: value}))
    assert cond in pe["price_conditions"] and pe["effective_price"] == 100000                # 条件つきの値引きは現金の仕入れ値に使わない


def test_campaign_price_is_kept_separate_from_regular_price():
    pe = rl.price_evidence(_e(price=80000, campaign_price=80000, campaign_conditions="Galaxy Week 10%OFF", regular_price=88000))
    assert pe["campaign_price"] == 80000 and pe["regular_price"] == 88000 and pe["effective_price"] == 88000
    assert pe["campaign_conditions"] == "Galaxy Week 10%OFF"


def test_unreadable_or_zero_price_is_not_purchasable_and_discount_cannot_make_it_free():
    assert rl.price_evidence(_e(price=0))["effective_price"] is None
    assert rl.price_evidence(_e(price=5000, immediate_discount=5000))["effective_price"] is None


def _idx(entries, adapter_id="nikon_direct", at=FRESH):
    return {adapter_id: {"entries": entries, "observed_at": at}}


def test_lookup_carries_evidence_and_uses_regular_price_for_conditional_offers():
    idx = _idx([{"name": "Nikon Z9 ボディ", "price": 90000, "url": "u", "jan": "4960759900001", "model": "Z9",
                 "required_coupon": "初回限定", "regular_price": 100000, "points": 5000}])
    r = rl.lookup({"basis": "JAN", "value": "4960759900001", "name": "Nikon Z9 ボディ"}, idx)
    assert r["status"] == rl.MATCHED and r["price"] == 100000 and r["listed_price"] == 90000 and r["points"] == 5000
    assert r["source_type"] == rl.OFFICIAL_DIRECT and r["price_conditions"] == [rl.COND_COUPON] and "初回限定" not in str(r["price"])


def test_lookup_picks_the_lowest_unconditional_cash_price_among_sources():
    class Other(rl.RetailAdapter):
        adapter_id, retailer, source_type, brands = "other_ec", "他の店", rl.AUTHORIZED_RETAILER, ("nikon",)
    idx = {**_idx([{"name": "Nikon Z9 ボディ", "price": 100000, "url": "u1", "jan": "4960759900001", "model": "Z9"}]),
           "other_ec": {"entries": [{"name": "Nikon Z9 ボディ", "price": 95000, "url": "u2", "jan": "4960759900001", "model": "Z9"}],
                        "observed_at": FRESH}}
    r = rl.lookup({"basis": "JAN", "value": "4960759900001", "name": "Nikon Z9 ボディ"}, idx, (rl.NikonDirectAdapter(), Other()))
    assert r["retailer"] == "他の店" and r["price"] == 95000 and r["source_type"] == rl.AUTHORIZED_RETAILER
    assert r["alternatives"] == [{"retailer": "ニコンダイレクト", "source_type": rl.OFFICIAL_DIRECT, "price": 100000, "status": rl.MATCHED,
                                "availability": rl.AVAIL_UNKNOWN}]


def test_wrong_capacity_or_color_kit_part_number_is_not_matched():
    entries = [{"name": "iPhone 17 Pro 256GB", "price": 190000, "url": "u", "jan": "", "model": "MAAA3J/A"},
               {"name": "iPhone 17 Pro 512GB", "price": 220000, "url": "u", "jan": "", "model": "MAAB3J/A"}]
    ident = {"basis": "JAN", "value": "4549995000001", "name": "iPhone 17 Pro 512GB MAAB3J/A", "part_number": "MAAB3J/A"}
    r = rl.lookup(ident, _idx(entries, "apple_jp"))
    assert r["status"] == rl.MATCHED and r["price"] == 220000                                    # 部品番号の完全一致（容量違いの行は選ばない）
    assert rl.lookup({**ident, "part_number": "MAAC3J/A"}, _idx(entries, "apple_jp"))["status"] == rl.NO_MATCH
    assert rl.lookup({**ident, "part_number": ""}, _idx(entries, "apple_jp"))["status"] == rl.NO_MATCH   # 名前だけでは引かない


def test_apple_adapter_reads_part_numbers_and_never_claims_stock():
    html = ('<script>{"sku":"MAAA3","partNumber":"MAAA3J/A","price":{"fullPrice":190000},"category":"iphone","name":"iPhone 17 Pro 256GB シルバー"}'
            '{"sku":"MAAB3","partNumber":"MAAB3J/A","price":{"fullPrice":220000},"category":"iphone","name":"iPhone 17 Pro 512GB シルバー"}'
            '{"sku":"ZZZZ3","partNumber":"ZZZZ3J/A","price":{"fullPrice":9000},"category":"accessories","name":"ケース"}</script>')
    e = rl.AppleStoreAdapter().parse_index(html, "https://www.apple.com/jp/shop/buy-iphone/iphone-17")
    assert [(x["model"], x["price"], x["availability"]) for x in e] == [("MAAA3J/A", 190000, rl.AVAIL_UNKNOWN), ("MAAB3J/A", 220000, rl.AVAIL_UNKNOWN)]
    assert rl.ready_for_triage({"name": "iPhone 17 Pro 256GB MAAA3J/A"}) is True


# ── apply_lookups: 仕入れ値の安全 ─────────────────────────────────────────────────

def _dp(price=130000, at=FRESH):
    return {"candidate_id": "dp_x", "kind": "DISCOVERED_PRODUCT_CANDIDATE", "status": rc.DISCOVERED, "name": "Nikon Z9 ボディ",
            "identity_basis": "JAN", "observed_sell_price": price, "observed_at": at, "retail_price_hint": None,
            "missing_requirements": ["CANONICAL_UNREGISTERED", "OFFICIAL_PRICE_UNKNOWN"]}


def _lk(**k):
    base = {"status": "MATCHED", "retailer": "店", "source_type": "AUTHORIZED_RETAILER", "product_url": "u", "price": 100000, "listed_price": 100000,
            "availability_state": "IN_STOCK", "observed_at": FRESH, "identity_evidence": {"basis": "JAN"}, "price_basis": "UNCONDITIONAL",
            "price_conditions": [], "points": 0, "cashback": 0}
    base.update(k)
    return base


def test_points_do_not_create_a_positive_spread():
    # 現金の仕入れ 100,000 / 買取 95,000 → ポイント 10,000 を現金扱いにすれば 5,000 の黒字に見えるが、候補にしない
    r = rc.apply_lookups([_dp(price=95000)], {"dp_x": _lk(points=10000)}, NOW, FRESH)[0]
    assert r["status"] == rc.REJECTED and rc.NO_SPREAD in r["missing_requirements"] and r["retail_points"] == 10000
    # 黒字の候補では、ポイントは別の項目（参考の差）として残す
    ok = rc.apply_lookups([_dp(price=130000)], {"dp_x": _lk(points=10000)}, NOW, FRESH)[0]
    assert ok["status"] == rc.RESEARCH_CANDIDATE and ok["raw_spread_hint"] == 30000 and ok["spread_if_points_counted"] == 40000


def test_conditional_acquisition_price_is_research_only_never_high_priority():
    lk = _lk(price=100000, listed_price=80000, price_conditions=["COUPON_REQUIRED"], price_basis="REGULAR_PRICE")
    r = rc.apply_lookups([_dp(price=125000)], {"dp_x": lk}, NOW, FRESH)[0]
    assert r["status"] == rc.RESEARCH_CANDIDATE and r["research_class"] == rc.STANDARD_RESEARCH and rc.ACQUISITION_CONDITIONAL in r["missing_requirements"]
    assert r["raw_spread_hint"] == 25000                                                          # 差は通常価格（クーポンを使わない）で計算
    unknown = rc.apply_lookups([_dp(price=125000)], {"dp_x": _lk(price=80000, price_conditions=["CAMPAIGN_CONDITIONAL"],
                                                                  price_basis="CONDITIONAL_UNKNOWN_REGULAR")}, NOW, FRESH)[0]
    assert unknown["research_class"] == rc.STANDARD_RESEARCH and rc.ACQUISITION_CONDITIONAL in unknown["missing_requirements"]


def test_clean_unconditional_lookup_is_high_priority_and_route_is_retail_to_buyback():
    r = rc.apply_lookups([_dp(price=125000)], {"dp_x": _lk(availability_state="IN_STOCK")}, NOW, FRESH)[0]
    assert r["research_class"] == rc.HIGH_PRIORITY_RESEARCH and r["route_type"] == rc.RETAIL_TO_BUYBACK
    assert r["retail_source_type"] == "AUTHORIZED_RETAILER" and rc.STOCK_UNKNOWN not in r["missing_requirements"]
    unk = rc.apply_lookups([_dp(price=125000)], {"dp_x": _lk(availability_state="UNKNOWN")}, NOW, FRESH)[0]
    assert rc.STOCK_UNKNOWN in unk["missing_requirements"]                                        # 在庫が分からないことは理由に残す


def test_stale_retail_is_rejected_and_never_confirmed():
    stale = rc.apply_lookups([_dp(price=125000)], {"dp_x": _lk(observed_at="2026-10-25T10:00:00+09:00")}, NOW, FRESH)[0]
    assert stale["status"] == rc.DISCOVERED and "retail_price" not in stale
    ok = rc.apply_lookups([_dp(price=125000)], {"dp_x": _lk()}, NOW, FRESH)[0]
    assert ok["status"] != rc.VERIFIED


# ── TCG の質・優先順位・検知の許容 ──────────────────────────────────────────────────

def _ev(**k):
    base = {"retailer": "CARD_LABO", "event_type": "LOTTERY", "status": "OPEN", "published_at": "2026-10-27T00:00:00+09:00",
            "observed_at": "2026-10-29T08:00:00+09:00", "application_start_date": "2026-10-28", "application_end_date": "2026-10-31",
            "winner_announcement_date": "2026-11-01", "purchase_start_date": "2026-11-02", "purchase_end_date": "2026-11-08"}
    base.update(k)
    return base


def test_event_quality_counts_each_field_and_by_source():
    items = [_ev(), _ev(winner_announcement_date=None, retailer="HOBBY_STATION"),
             _ev(purchase_start_date=None, entry_url="https://x.example/e"), _ev(status="ENDED")]
    r = eq.evaluate(items, NOW)
    q = r["quality"]
    assert q["active_events"] == 3 and q["with_application_start"] == 3 and q["with_winner_announcement"] == 2
    assert q["with_purchase_window"] == 2 and q["with_action_url"] == 1 and q["fully_dated"] == 1
    assert r["quality_by_source"]["HOBBY_STATION"]["active_events"] == 1


def test_priority_follows_the_fixed_order():
    assert eq.priority_of(_ev(status="UPCOMING"), NOW) == eq.P_UPCOMING
    assert eq.priority_of(_ev(status="ENDING_SOON"), NOW) == eq.P_DEADLINE_SOON
    assert eq.priority_of(_ev(application_end_date="2026-10-29"), NOW) == eq.P_DEADLINE_SOON          # 24 時間以内に終わる
    assert eq.priority_of(_ev(event_type="PREORDER"), NOW) == eq.P_PREORDER_OPEN
    assert eq.priority_of(_ev(event_type="FIRST_COME"), NOW) == eq.P_FIRST_COME
    assert eq.priority_of(_ev(event_type="RESTOCK"), NOW) == eq.P_RESTOCK
    assert eq.priority_of(_ev(), NOW) == eq.P_ACTIVE_LOTTERY
    assert eq.PRIORITIES.index(eq.P_DEADLINE_SOON) < eq.PRIORITIES.index(eq.P_ACTIVE_LOTTERY) < eq.PRIORITIES.index(eq.P_UPCOMING)


def test_fast_lane_measures_duration_age_and_remaining_without_claiming_first_seen():
    r = eq.evaluate([_ev(), _ev(application_start_date="2026-10-29", application_end_date="2026-10-29")], NOW)
    f = r["fast_lane"]
    assert r["first_seen_available"] is False                                                       # 初めて見た時刻は保持していない
    assert f["events_measured"] == 2 and sorted(x["application_duration_hours"] for x in r["events"]) == [24.0, 96.0]   # 日付の終わりは 23:59:59
    e = r["events"][0]
    assert e["precision"] == "date" and "age_at_observation_hours" in e and "remaining_at_observation_hours" in e
    assert f["date_precision_events"] == 2 and f["suggested_max_detection_interval_hours"] >= 1
    assert "detection_delay_hours" not in e                                                          # 検知の遅れとは呼ばない（上限でも実測でもない）


def test_event_quality_survives_garbage_and_empty_input():
    for bad in (None, [], [None, 3, "x"], [{"status": "OPEN"}], [{"status": "OPEN", "application_end_date": "壊れた"}]):
        r = eq.evaluate(bad, NOW)
        assert r["quality"]["active_events"] == (1 if bad and isinstance(bad[-1], dict) else 0)
        assert r["fast_lane"]["events_measured"] == 0


def test_public_summary_exposes_event_aggregates_only():
    products = [{"id": "p1", "name": "既存商品", "genre": "camera", "jan": "", "part_numbers": []}]
    rep, _ = rc.build(products=products, observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), now=NOW,
                      tcg_events=[_ev(product_name="秘密の商品名", source_url="https://x.example/secret")])
    s = rc.public_summary(rep)
    assert s["tcg_event_quality"]["active_events"] == 1 and s["tcg_priority"]["ACTIVE_LOTTERY"] == 1
    text = json.dumps(s, ensure_ascii=False)
    assert "秘密の商品名" not in text and "x.example" not in text and "CARD_LABO" not in text
    assert "tcg_events" not in s and "tcg_events" in rc.PRIVATE_KEYS


# ── Canon（JAN ↔ 商品コードの表） ────────────────────────────────────────────────────

CANON_LD = ('<script type="application/ld+json">{"@type":"Product","name":"EOS R6 Mark II ボディー","offers":{"@type":"Offer",'
            '"url":"https://store.canon.jp/online/g/g5666C001/","price":"319000"}}</script>')


def test_canon_table_is_well_formed_unique_and_only_current_official_codes():
    import yaml
    from pathlib import Path
    doc = yaml.safe_load((Path(__file__).resolve().parent.parent / "config" / "canon_codes.yaml").read_text(encoding="utf-8"))
    items = doc["items"]
    jans, codes = [i["jan"] for i in items], [i["code"] for i in items]
    assert len(set(jans)) == len(jans) == len(codes) == len(set(codes)) and len(items) >= 15
    assert all(len(j) == 13 and j.startswith("4549292") for j in jans)                           # キヤノンの JAN の接頭辞
    import re
    assert all(re.fullmatch(r"\d{4}C\d{3}", c) for c in codes)                                  # 整備済みの別コード（EOS-… 形式）を入れない
    assert {i["kind"] for i in items} == {"body", "kit"} and doc["checked_on"]
    assert rl.CanonStoreAdapter.table().keys() == set(jans)


def test_canon_lookup_uses_only_the_table_and_never_matches_by_name():
    ad = rl.CanonStoreAdapter()
    ident = {"basis": "JAN", "value": "4549292200508", "name": "Canon EOS R6 Mark II ボディ"}
    assert ad.item_key(ident) == "5666C001" and ad.supports(ident)
    assert not ad.supports({**ident, "value": "4549292299999"})                                  # 表に無い JAN は引かない
    assert not ad.supports({"basis": "MODEL_CODE", "value": "5666C001", "name": "EOS R6 Mark II"})  # JAN 以外では引かない
    assert not ad.supports({"basis": "MODEL_CODE", "value": "4549292200508", "name": "Canon EOS R6 Mark II"})   # JAN の値でも、基準が JAN でなければ引かない
    assert ad.item_key({"basis": "JAN", "value": "4549292200577", "name": "Canon EOS R6 Mark II ボディ"}) == "5666C010"   # キットは別の JAN・別のコード
    idx = {"canon_store": {"entries": ad.parse_item(CANON_LD, "5666C001"), "covered": ["5666C001"], "observed_at": FRESH}}
    r = rl.lookup(ident, idx)
    assert r["status"] == rl.MATCHED and r["price"] == 319000 and r["availability_state"] == rl.AVAIL_UNKNOWN   # 納期の文言から在庫を作らない
    kit = rl.lookup({**ident, "value": "4549292200577"}, idx)
    assert kit["status"] == rl.UNSUPPORTED                                                       # キットのページは取っていない（ボディーの価格を流用しない）


def test_canon_parse_item_falls_back_to_the_order_summary_and_rejects_ambiguous_or_wrong_pages():
    ad = rl.CanonStoreAdapter()
    body = "<html><p>5812C001</p><p>ご注文概要 価格 111,100 円(税込)</p></html>"
    assert ad.parse_item(body, "5812C001")[0]["price"] == 111100
    assert ad.parse_item("<p>ご注文概要 価格 111,100 円(税込)</p><p>ご注文概要 価格 120,000 円(税込)</p><p>5812C001</p>", "5812C001") == []
    assert ad.parse_item(body, "5666C001") == []                                                 # 商品コードがページに無い（別の商品のページ）
    assert ad.parse_item("<html>5666C001 価格なし</html>", "5666C001") == []
    assert ad.parse_item(CANON_LD.replace("g5666C001", "g9999C001"), "5666C001") == []         # 構造化データの URL の商品コードが違う


def test_run_lookups_reaches_canon_by_jan_and_apple_by_part_number_with_polite_fetch_only():
    cands = [{"candidate_id": "dp_c", "name": "デジタル一眼カメラ Canon EOS R6 Mark II ボディ", "identity_basis": "JAN", "jan": "4549292200508",
              "observed_sell_price": 300000, "observed_at": FRESH},
             {"candidate_id": "dp_a", "name": "iPhone 17 Pro 512GB シルバー MAAB3J/A SIMフリー", "identity_basis": "JAN", "jan": "4549995000001",
              "observed_sell_price": 260000, "observed_at": FRESH},
             {"candidate_id": "dp_k", "name": "Canon EOS R6 Mark II RF24-105L キット", "identity_basis": "JAN", "jan": "4549292200577",
              "observed_sell_price": 400000, "observed_at": FRESH}]
    apple_html = ('{"sku":"MAAB3","partNumber":"MAAB3J/A","price":{"fullPrice":220000},"category":"iphone","name":"iPhone 17 Pro 512GB シルバー"}')
    calls = []

    def fetch(url):
        calls.append(url)
        if "store.canon.jp" in url:
            return (CANON_LD, "") if "5666C001" in url else (None, "timeout")
        if "apple.com" in url:
            return (apple_html, "") if url.endswith("iphone-17") else ("{}", "")
        return (None, "not_found")
    rec = rl.run_lookups(cands, NOW, fetch)
    assert rec["lookups"]["dp_c"]["status"] == rl.MATCHED and rec["lookups"]["dp_c"]["price"] == 319000
    assert rec["lookups"]["dp_a"]["status"] == rl.MATCHED and rec["lookups"]["dp_a"]["price"] == 220000
    assert rec["lookups"].get("dp_k", {}).get("status") != rl.MATCHED                           # キットのページが取れなければ、ボディーの価格を流用しない
    assert any("g5666C001" in u for u in calls) and any("g5666C010" in u for u in calls)
    assert all(u.startswith(("https://store.canon.jp/", "https://www.apple.com/")) for u in calls)   # 取得はこの2社だけ（他社の一覧は取らない）


def test_apple_part_number_must_match_exactly_not_by_prefix():
    entries = [{"name": "iPhone 17 Pro 256GB", "price": 190000, "url": "u", "jan": "", "model": "MAAB3J/A"}]
    ident = {"basis": "JAN", "value": "4549995000001", "name": "iPhone 17 Pro 256GB MAAB4J/A", "part_number": "MAAB4J/A"}   # 先頭4文字が同じ別の部品番号
    assert rl.lookup(ident, _idx(entries, "apple_jp"))["status"] == rl.NO_MATCH


def test_part_number_only_identification_is_partial_and_never_high_priority():
    lk = _lk(identity_evidence={"basis": "JAN", "method": "part_exact"})
    r = rc.apply_lookups([_dp(price=125000)], {"dp_x": lk}, NOW, FRESH)[0]
    assert r["status"] == rc.RESEARCH_CANDIDATE and rc.IDENTITY_PARTIAL in r["missing_requirements"] and r["research_class"] == rc.STANDARD_RESEARCH
    exact = rc.apply_lookups([_dp(price=125000)], {"dp_x": _lk(identity_evidence={"basis": "JAN", "method": "jan_exact"})}, NOW, FRESH)[0]
    assert rc.IDENTITY_PARTIAL not in exact["missing_requirements"] and exact["research_class"] == rc.HIGH_PRIORITY_RESEARCH


def test_unconditional_price_wins_over_a_cheaper_conditional_one_across_sources():
    class Other(rl.RetailAdapter):
        adapter_id, retailer, source_type, brands = "other_ec", "他の店", rl.AUTHORIZED_RETAILER, ("nikon",)
    idx = {**_idx([{"name": "Nikon Z9 ボディ", "price": 100000, "url": "u1", "jan": "4960759900001", "model": "Z9"}]),
           "other_ec": {"entries": [{"name": "Nikon Z9 ボディ", "price": 80000, "url": "u2", "jan": "4960759900001", "model": "Z9",
                                      "required_coupon": "アプリ限定"}], "observed_at": FRESH}}
    r = rl.lookup({"basis": "JAN", "value": "4960759900001", "name": "Nikon Z9 ボディ"}, idx, (rl.NikonDirectAdapter(), Other()))
    assert r["retailer"] == "ニコンダイレクト" and r["price"] == 100000                          # 条件つきの安い価格を、条件なしの価格に優先しない


def test_public_fast_lane_keeps_fractional_hours_and_uses_the_real_key_names():
    items = [_ev(application_start="2026-10-29T10:00:00+09:00", application_end="2026-10-29T10:30:00+09:00",
                 observed_at="2026-10-29T10:10:00+09:00", published_at="2026-10-29T10:05:00+09:00", status="OPEN")]
    products = [{"id": "p1", "name": "既存商品", "genre": "camera", "jan": "", "part_numbers": []}]
    rep, _ = rc.build(products=products, observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), now=NOW, tcg_events=items)
    f = rc.public_summary(rep)["tcg_fast_lane"]
    assert f["median_application_duration_hours"] == 0.5 and "tolerated_age_at_observation_hours_p25" in f


def test_canon_page_marked_as_discontinued_is_not_a_purchase_price():
    ad = rl.CanonStoreAdapter()
    ended = CANON_LD + "<p>この商品は販売を終了しました。</p>"
    assert ad.parse_item(ended, "5666C001") == []                                                # 販売終了のページの価格は仕入れ値にしない
    assert ad.parse_item(CANON_LD, "5666C001")[0]["price"] == 319000

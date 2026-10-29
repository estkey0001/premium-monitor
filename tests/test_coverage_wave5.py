"""Market Research Coverage Wave 5: 利益が出やすい市場のシグナル・TCG の優先度・検知の間隔のシミュレーション・取得の並列化と同一実行のキャッシュ。

通信はしない（合成の値だけ）。AI の予測価格は使わない。シグナルは並べ替えの点で、確定・actionable を作らない。
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timedelta, timezone

from src.research import candidates as rc
from src.research import retail_lookup as rl
from src.research import signals as sg
from src.research import triage as tr
from src.tcg import profit_dense as pdn

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=JST)
FRESH = "2026-10-29T10:00:00+09:00"


# ── 発売からの経過 ───────────────────────────────────────────────────────────────────

def test_new_release_is_prioritised_over_an_established_product():
    new = sg.release_signal("2026-10-20", NOW)
    old = sg.release_signal("2025-01-01", NOW)
    assert new["release_state"] == sg.REL_NEW and new["days_since_release"] == 9
    assert old["release_state"] == sg.REL_ESTABLISHED
    assert sg.profit_density(release=new)["signal_points"] > sg.profit_density(release=old)["signal_points"] == 0


def test_unknown_or_unreadable_release_is_not_boosted_and_never_guessed():
    for v in (None, "", "壊れた", "2026-13-99"):
        r = sg.release_signal(v, NOW)
        assert r == {"release_state": sg.REL_UNKNOWN, "days_since_release": None}
        assert sg.profit_density(release=r)["signal_points"] == 0


def test_future_release_is_upcoming_not_new():
    r = sg.release_signal("2026-11-13", NOW)
    assert r["release_state"] == sg.REL_UPCOMING and r["days_since_release"] is None
    assert sg.profit_density(release=r)["signal_points"] == 0                                       # まだ発売前。買えないので加点しない


# ── 限定・特別（公式の根拠が必要） ───────────────────────────────────────────────────

def test_limited_requires_official_evidence():
    ok = sg.limited_signal(official_name="Nikon Z f 限定カラー", official_url="https://nij.nikon.com/x/", official=True)
    assert ok["limited"] and ok["limited_kind"] == "limited"
    # 公式でない・URL が無い・名前が無いときは、語があっても付けない（買取店の名前・推測で限定にしない）
    assert not sg.limited_signal(official_name="限定カラー", official_url="https://shop.example/x", official=False)["limited"]
    assert not sg.limited_signal(official_name="限定カラー", official_url="", official=True)["limited"]
    assert not sg.limited_signal(official_name="", official_url="https://x.example/", official=True)["limited"]
    assert not sg.limited_signal(official_name="Nikon Z9 ボディ", official_url="https://nij.nikon.com/x/", official=True)["limited"]


def test_ambiguous_words_are_limited_only_with_a_structured_official_field():
    """Special・特別・周年・記念などの曖昧な語は、語の一致だけでは限定にしない（Wave 6 Stage W）。公式の構造化された項目があるときだけ採用する。"""
    names = ("30th CELEBRATION 拡張パック", "スペシャルデッキセット", "10周年 記念モデル", "特別なケース付き", "Special Pack")
    for n in names:
        assert not sg.limited_signal(official_name=n, official_url="https://o.example/", official=True)["limited"]
    kinds = {sg.limited_signal(official_name=n, official_url="https://o.example/", official=True, structured_limited=True)["limited_kind"]
             for n in names[:3]}
    assert kinds == {"anniversary", "special"}
    # 構造化された項目があっても、公式でない・URL が無いなら付けない
    assert not sg.limited_signal(official_name="特別版", official_url="", official=True, structured_limited=True)["limited"]
    assert not sg.limited_signal(official_name="特別版", official_url="https://o.example/", official=False, structured_limited=True)["limited"]
    # 明確な語は、公式の名前にあればそれだけで根拠になる
    assert sg.limited_signal(official_name="数量限定セット", official_url="https://o.example/", official=True)["limited"]


# ── 供給の逼迫 ───────────────────────────────────────────────────────────────────────

def test_stock_unknown_is_not_supply_pressure():
    for avail in ("", "UNKNOWN", "IN_STOCK"):
        assert sg.supply_signals(availability=avail, official=True) == []


def test_official_out_of_stock_is_supply_pressure_but_a_non_official_single_source_is_not():
    assert sg.supply_signals(availability="OUT_OF_STOCK", official=True) == [sg.SUP_OUT_OF_STOCK]
    assert sg.supply_signals(availability="OUT_OF_STOCK", official=False) == []                     # 公式でない 1 つの取得元の在庫なしは数えない
    assert sg.SUP_MULTI_UNAVAILABLE in sg.supply_signals(availability="", official=False, unavailable_sources=2)
    assert sg.SUP_MULTI_UNAVAILABLE not in sg.supply_signals(availability="", official=False, unavailable_sources=1)     # 1 つだけでは複数と言わない


def test_tcg_supply_signals_lottery_restock_and_short_window():
    s = sg.supply_signals(event_type="LOTTERY", application_hours=24, lottery_active=True)
    assert sg.SUP_LOTTERY_ONLY in s and sg.SUP_SHORT_WINDOW in s
    assert sg.SUP_RESTOCK in sg.supply_signals(event_type="RESTOCK")
    assert sg.SUP_SHORT_WINDOW not in sg.supply_signals(event_type="LOTTERY", application_hours=96)
    assert sg.SUP_SHORT_WINDOW not in sg.supply_signals(application_hours=None)                     # 応募の長さが分からなければ短いと言わない


# ── 買取の勢い ───────────────────────────────────────────────────────────────────────

def _row(sell, retail, cat="camera", **k):
    return {"observed_sell_price": sell, "retail_price": retail, "category": cat, **k}


def test_buyback_rise_needs_a_previous_observation_and_a_real_rise():
    assert sg.BUY_RISING in sg.buyback_signals(_row(106000, None), prev_sell=100000)
    assert sg.BUY_RISING not in sg.buyback_signals(_row(100000, None), prev_sell=100000)
    assert sg.BUY_RISING not in sg.buyback_signals(_row(102000, None), prev_sell=100000)           # 3% 未満
    assert sg.BUY_RISING not in sg.buyback_signals(_row(130000, None), prev_sell=None)             # 前回が無ければ、上がったと言わない
    assert sg.profit_density(buyback=[sg.BUY_RISING])["signal_points"] > 0


def test_buyback_close_to_retail_and_above_category_median():
    rows = [_row(95000, 100000), _row(80000, 100000), _row(82000, 100000), _row(70000, 100000)]
    med = sg.category_medians(rows)
    assert abs(med["camera"] - 0.81) < 1e-9                                                         # 0.70・0.80・0.82・0.95 の中央値
    top = sg.buyback_signals(rows[0], medians=med)
    assert sg.BUY_NEAR_RETAIL in top and sg.BUY_ABOVE_MEDIAN in top
    assert sg.buyback_signals(rows[3], medians=med) == []


def test_category_median_needs_enough_samples():
    assert sg.category_medians([_row(90000, 100000), _row(80000, 100000)]) == {}                    # 標本が少ない品目は基準にしない


def test_suspicious_or_conditional_price_gets_no_momentum_and_no_points():
    assert sg.buyback_signals(_row(190000, 100000, suspicious=True), prev_sell=100000) == []
    assert sg.buyback_signals(_row(190000, 100000, retail_conditions=["クーポン"]), prev_sell=100000) == []
    d = sg.profit_density(release={"release_state": sg.REL_NEW}, limited={"limited": True}, supply=[sg.SUP_OUT_OF_STOCK],
                          buyback=[sg.BUY_RISING], positive_spread=True, suspicious=True)
    assert d["signal_points"] == 0 and d["signal_reasons"] == ["suspicious_no_boost"]


def test_prev_sell_lookup_only_across_runs_and_not_when_stale():
    raw = {"buyback_prices": {"dp_a": {"price": 100000, "at": "2026-10-28T10:00:00+09:00"},
                              "dp_old": {"price": 90000, "at": "2026-09-01T10:00:00+09:00"},
                              "dp_bad": {"price": "x", "at": FRESH}}}
    f = rc.prev_sell_lookup(raw, rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN, NOW)
    assert f({"candidate_id": "dp_a"}) == 100000
    assert f({"candidate_id": "dp_old"}) is None and f({"candidate_id": "dp_bad"}) is None and f({"candidate_id": "dp_zz"}) is None
    for st in (rc.LEDGER_NOT_AVAILABLE, rc.LEDGER_NEW_THIS_RUN, rc.LEDGER_REUSED_WITHIN_RUN, rc.LEDGER_CORRUPT):
        assert rc.prev_sell_lookup(raw, st, NOW) is None                                            # 実行をまたいで引き継げていない日は比べない
    assert rc.prev_sell_lookup(None, rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN, NOW) is None


# ── 候補への組み込み（確定にしない・個別は非公開） ────────────────────────────────────

def _dp(cid="dp_1", price=130000, name="Nikon Z9 ボディ", **k):
    return {"candidate_id": cid, "kind": "DISCOVERED_PRODUCT_CANDIDATE", "status": rc.DISCOVERED, "name": name,
            "identity_basis": "JAN", "jan": "4960759900000", "observed_sell_price": price, "observed_at": FRESH,
            "retail_price_hint": None, "missing_requirements": ["CANONICAL_UNREGISTERED", "OFFICIAL_PRICE_UNKNOWN"], **k}


def _lk(**k):
    base = {"status": "MATCHED", "retailer": "ニコンダイレクト", "source_type": "OFFICIAL_DIRECT", "product_url": "https://nij.nikon.com/a/",
            "price": 100000, "listed_price": 100000, "availability_state": "IN_STOCK", "observed_at": FRESH,
            "identity_evidence": {"basis": "JAN", "matched_name": "Z9 ボディ"}, "price_basis": "UNCONDITIONAL",
            "price_conditions": [], "points": 0, "cashback": 0}
    base.update(k)
    return base


def test_out_of_stock_official_lookup_leaves_a_supply_signal_but_no_price_or_spread():
    d = _dp()
    rc.apply_lookups([d], {"dp_1": _lk(status="NOT_PURCHASABLE", price=None, availability_state="OUT_OF_STOCK")}, NOW, FRESH)
    assert d["retail_availability"] == "OUT_OF_STOCK" and d["retail_source_type"] == "OFFICIAL_DIRECT"
    assert d.get("retail_price") is None and d["status"] == rc.DISCOVERED                          # 価格は仕入れ値に使わない・調査候補にもしない


def test_stale_out_of_stock_lookup_is_not_a_supply_signal():
    d = _dp()
    rc.apply_lookups([d], {"dp_1": _lk(status="NOT_PURCHASABLE", price=None, availability_state="OUT_OF_STOCK",
                                       observed_at="2026-10-20T10:00:00+09:00")}, NOW, FRESH)
    assert "retail_availability" not in d                                                           # 古い在庫なしを、今日の逼迫にしない


def test_unavailable_sources_counts_alternatives():
    d = _dp()
    rc.apply_lookups([d], {"dp_1": _lk(alternatives=[
        {"status": "NOT_PURCHASABLE", "retailer": "A", "source_type": "X", "price": None, "availability": "OUT_OF_STOCK"},
        {"status": "NOT_PURCHASABLE", "retailer": "C", "source_type": "X", "price": None, "availability": "IN_STOCK"},    # 価格が読めないだけ
        {"status": "MATCHED", "retailer": "B", "source_type": "X", "price": 1, "availability": "IN_STOCK"}])}, NOW, FRESH)
    assert d["retail_unavailable_sources"] == 1


def test_unreadable_price_with_stock_is_not_a_supply_signal():
    d = _dp()
    rc.apply_lookups([d], {"dp_1": _lk(status="NOT_PURCHASABLE", price=None, availability_state="IN_STOCK")}, NOW, FRESH)
    assert "retail_availability" not in d and d.get("retail_unavailable_sources") == 0               # 在庫ありで価格のパースに失敗しただけ。逼迫にしない
    rows, counts = _annotate([d])
    assert rows[0]["supply_signals"] == [] and counts["supply_pressure_candidates"] == 0


def test_rejected_or_ineligible_rows_get_no_signals_and_are_not_counted():
    rej = _dp("dp_r", 120000)
    rc.apply_lookups([rej], {"dp_r": _lk(price=130000)}, NOW, FRESH)                                 # 買取 < 小売 → NO_SPREAD で REJECTED
    assert rej["status"] == rc.REJECTED
    rows, counts = _annotate([rej])
    assert rows[0]["signal_points"] == 0 and rows[0]["signal_reasons"] == ["not_eligible"]
    assert counts["positive_spread_candidates"] == 0 and counts["limited_candidates"] == 0
    stale = _dp("dp_s", 120000, observed_at="2026-10-20T10:00:00+09:00")                             # 買取の観測が 3 日超
    rc.apply_lookups([stale], {"dp_s": _lk(identity_evidence={"basis": "JAN", "matched_name": "Z9 限定"})}, NOW, FRESH)
    rows, counts = _annotate([stale])
    assert rows[0]["signal_points"] == 0 and counts["limited_candidates"] == 0


def test_positive_spread_points_need_a_real_lookup_and_no_doubt():
    hint = _dp("dp_h", 120000, retail_price_hint=100000)                                              # ヒント由来（照会なし）
    rc.apply_lookups([hint], None, NOW, None)
    rows, counts = _annotate([hint])
    assert counts["positive_spread_candidates"] == 0
    part = _dp("dp_p", 120000)
    rc.apply_lookups([part], {"dp_p": _lk(identity_evidence={"basis": "JAN", "method": "part_exact", "matched_name": "x"})}, NOW, FRESH)
    assert "IDENTITY_PARTIAL" in part["missing_requirements"]
    rows, counts = _annotate([part])
    assert counts["positive_spread_candidates"] == 0


def test_conditional_acquisition_is_not_boosted():
    d = _dp("dp_c", 120000)
    rc.apply_lookups([d], {"dp_c": _lk(price_basis="CONDITIONAL_UNKNOWN_REGULAR", price_conditions=["クーポン"])}, NOW, FRESH)
    assert "ACQUISITION_CONDITIONAL" in d["missing_requirements"]
    rows, _ = _annotate([d])
    assert rows[0]["signal_points"] == 0


def _annotate(rows):
    tri = tr.triage(rows, NOW, lookup_ready_of=lambda c: True,
                    lookup_results={c["candidate_id"]: {"status": "MATCHED"} for c in rows if c.get("retail_price") is not None})
    counts = sg.annotate_buyback_rows(tri["rows"], NOW)
    return tri["rows"], counts


def test_signals_never_change_status_or_create_confirmed():
    d = _dp(price=190000)
    rc.apply_lookups([d], {"dp_1": _lk(identity_evidence={"basis": "JAN", "matched_name": "Z f 限定カラー"})}, NOW, FRESH)
    before = (d["status"], d["research_class"])
    rows, counts = _annotate([d])
    assert (rows[0]["status"], rows[0]["research_class"]) == before
    assert rows[0]["status"] != rc.VERIFIED and counts["limited_candidates"] == 1


def test_suspicious_spread_stays_unboosted_and_not_high_priority():
    d = _dp(price=300000)                                                                           # 小売 10 万円・買取 30 万円 = 誤価格の疑い
    rc.apply_lookups([d], {"dp_1": _lk()}, NOW, FRESH)
    assert "PRICE_ANOMALY_SUSPECTED" in d["missing_requirements"] and d["research_class"] == rc.STANDARD_RESEARCH
    rows, _ = _annotate([d])
    assert rows[0]["signal_points"] == 0 and rows[0]["status"] == rc.RESEARCH_CANDIDATE


def test_exact_identity_is_kept_and_stock_unknown_is_counted_as_not_pressure():
    d = _dp(price=110000)
    rc.apply_lookups([d], {"dp_1": _lk(availability_state="UNKNOWN")}, NOW, FRESH)
    assert d["identity_status"] == "IDENTITY_CONFIRMED" and d["retail_identity_evidence"]["basis"] == "JAN"
    rows, counts = _annotate([d])
    assert rows[0]["supply_signals"] == [] and counts["supply_pressure_candidates"] == 0 and counts["stock_unknown_not_counted"] == 1
    assert counts["positive_spread_candidates"] == 1


def test_build_report_carries_signal_metrics_and_private_tcg_rows():
    products = [{"id": "p", "name": "既存", "genre": "camera", "jan": "", "part_numbers": []}]
    rep, _ = rc.build(products=products, observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), now=NOW,
                      catalog=[], retail_lookups=None, tcg_events=[])
    assert set(rep["metrics"]["research_signals"]) >= {"new_release_candidates", "limited_candidates", "supply_pressure_candidates",
                                                       "buyback_rising_candidates", "positive_spread_candidates", "active_tcg_priority"}
    assert "tcg_priority_events" in rep and rep["metrics"]["tcg_detection_simulation"]["events_measured"] == 0


def test_queue_is_ordered_by_triage_plus_signal_points():
    hi, lo = _dp("dp_hi", 120000, name="Nikon Z9 ボディ"), _dp("dp_lo", 120000, name="Nikon Z8 ボディ")
    rc.apply_lookups([hi, lo], {"dp_hi": _lk(identity_evidence={"basis": "JAN", "matched_name": "Z9 限定モデル"}), "dp_lo": _lk()}, NOW, FRESH)
    tri = tr.triage([hi, lo], NOW, lookup_ready_of=lambda c: True, lookup_results={"dp_hi": {"status": "MATCHED"}, "dp_lo": {"status": "MATCHED"}})
    sg.annotate_buyback_rows(tri["rows"], NOW)
    by = {r["candidate_id"]: r for r in tri["rows"]}
    assert by["dp_hi"]["signal_points"] > by["dp_lo"]["signal_points"]
    assert by["dp_hi"]["triage"]["score"] == by["dp_lo"]["triage"]["score"]


def test_public_summary_has_signal_counts_only_and_signal_fields_are_private():
    products = [{"id": "p1", "name": "既存商品", "genre": "camera", "jan": "", "part_numbers": []}]
    ev = {"status": "OPEN", "event_type": "LOTTERY", "retailer": "CARD_LABO", "product_name": "秘密の商品名", "product_id": "pid-secret",
          "product_match": "exact", "application_start_date": "2026-10-28", "application_end_date": "2026-10-29",
          "entry_url": "https://x.example/secret"}
    msrp = {"verified": [{"product_id": "pid-secret", "name": "30th CELEBRATION 限定", "retail_price": 5000, "release_date": "2026-10-20",
                          "source": "official_product_api", "official_url": "https://o.example/p"}]}
    rep, _ = rc.build(products=products, observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), now=NOW,
                      tcg_events=[ev], tcg_msrp=msrp)
    s = rc.public_summary(rep)
    assert s["research_signals"]["active_tcg_priority"] == 1 and s["tcg_profit_dense"]["tcg_msrp_linked_active"] == 1
    assert s["tcg_detection_simulation"]["events_measured"] == 1
    text = json.dumps(s, ensure_ascii=False)
    for secret in ("秘密の商品名", "pid-secret", "x.example", "30th", "o.example", "CARD_LABO"):
        assert secret not in text
    for k in ("release", "limited_signal", "supply_signals", "buyback_signals", "signal_points", "signal_reasons",
              "tcg_priority_events", "buyback_prices", "msrp_linked", "msrp_price", "retail_unavailable_sources"):
        assert k in rc.PRIVATE_KEYS and k not in s


def test_buyback_prices_are_private_state_and_not_in_the_public_summary(tmp_path):
    products = [{"id": "p1", "name": "既存商品", "genre": "camera", "jan": "", "part_numbers": []}]
    rep, state = rc.build(products=products, observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), now=NOW)
    pub = rc.write_outputs(rep, state, tmp_path / "priv", tmp_path / "pub", "run-1")
    assert "buyback_prices" not in pub
    saved = json.loads((tmp_path / "priv" / "state.json").read_text(encoding="utf-8"))
    assert "buyback_prices" in saved and "candidates" in saved


# ── TCG ──────────────────────────────────────────────────────────────────────────────

def _ev(**k):
    base = {"status": "OPEN", "event_type": "LOTTERY", "retailer": "CARD_LABO", "product_name": "商品", "product_id": "pid-1",
            "product_match": "exact", "provisional_product": False, "application_start_date": "2026-10-27",
            "application_end_date": "2026-10-31", "winner_announcement_date": "2026-11-01", "purchase_start_date": "2026-11-02",
            "purchase_end_date": "2026-11-05", "entry_url": "https://shop.example/e/1"}
    base.update(k)
    return base


MSRP = {"verified": [{"product_id": "pid-1", "name": "30th 数量限定 拡張パック", "retail_price": 5400, "release_date": "2026-10-20",
                      "source": "official_product_api", "official_url": "https://o.example/p"}]}


def test_active_lottery_is_boosted_over_an_ended_event_and_upcoming():
    r = pdn.evaluate([_ev(), _ev(status="ENDED"), _ev(status="UPCOMING", product_id=None)], MSRP, NOW)
    assert len(r["events"]) == 2                                                                    # 終了済みは優先度の対象にしない
    assert r["events"][0]["signal_points"] >= r["events"][1]["signal_points"]


def test_deadline_soon_gets_more_points_than_a_regular_active_lottery():
    soon = _ev(status="ENDING_SOON", application_end_date="2026-10-29")
    reg = _ev()
    r = {x["priority"]: x["signal_points"] for x in pdn.evaluate([soon, reg], None, NOW)["events"]}
    assert r["DEADLINE_SOON"] > 0 and r["ACTIVE_LOTTERY"] > 0


def test_complete_event_is_the_only_actionable_one_and_incomplete_is_not():
    full = pdn.completeness(_ev(), NOW)
    assert full["completeness"] == 7 and full["actionable_event"] and full["missing"] == []
    for drop in ({"entry_url": None}, {"winner_announcement_date": None}, {"purchase_end_date": None}, {"application_end_date": None},
                 {"product_id": None, "product_match": "none"}, {"provisional_product": True}):
        c = pdn.completeness(_ev(**drop), NOW)
        assert not c["actionable_event"] and c["completeness"] < 7 and c["missing"]
    r = pdn.evaluate([_ev(entry_url=None), _ev()], None, NOW)["counts"]
    assert r["tcg_actionable_events"] == 1 and r["tcg_incomplete_active"] == 1


def test_msrp_links_only_by_exact_product_id_never_by_name():
    linked = pdn.evaluate([_ev()], MSRP, NOW)
    assert linked["counts"]["tcg_msrp_linked_active"] == 1 and linked["events"][0]["msrp_price"] == 5400
    assert linked["counts"]["tcg_new_release"] == 1 and linked["counts"]["tcg_limited"] == 1       # 公式の商品名・発売日に根拠がある
    for ev in (_ev(product_id="pid-other"), _ev(product_id=None), _ev(product_match="fuzzy"), _ev(product_name="30th 数量限定 拡張パック", product_id=None)):
        r = pdn.evaluate([ev], MSRP, NOW)
        assert r["counts"]["tcg_msrp_linked_active"] == 0 and r["events"][0]["msrp_price"] is None
        assert r["counts"]["tcg_new_release"] == 0 and r["counts"]["tcg_limited"] == 0             # 結べなければ、発売直後・限定とも言わない


def test_msrp_from_a_non_official_source_gives_no_limited_signal():
    m = {"verified": [{**MSRP["verified"][0], "source": "manual_note"}]}
    assert pdn.evaluate([_ev()], m, NOW)["counts"]["tcg_limited"] == 0


def test_tcg_evaluate_survives_garbage():
    for bad in (None, [], [None, 3, "x"], [{"status": "OPEN"}], [{"status": "OPEN", "application_end_date": "壊れた"}]):
        for m in (None, {}, {"verified": [None, 3]}):
            r = pdn.evaluate(bad, m, NOW)
            assert set(r) == {"counts", "events"}


def test_no_profit_is_computed_for_tcg_events():
    r = pdn.evaluate([_ev()], MSRP, NOW)["events"][0]
    assert not any(k in r for k in ("profit", "raw_spread", "spread", "expected_price", "predicted_price"))


def test_detection_simulation_is_monotonic_and_separates_short_windows():
    items = [_ev(application_start_date="2026-10-27", application_end_date="2026-10-27"),        # 1 日（約 24 時間）
             _ev(application_start_date="2026-10-20", application_end_date="2026-10-30"),        # 11 日
             _ev(application_start_date=None, application_end_date=None)]                         # 測れない
    s = pdn.simulate_detection(items, NOW)
    assert s["events_measured"] == 2
    missed = [s[f"h{h}_missed"] for h in (24, 12, 6, 3)]
    lost = [s[f"h{h}_lost_half"] for h in (24, 12, 6, 3)]
    assert missed == sorted(missed, reverse=True) and lost == sorted(lost, reverse=True)           # 間隔が短いほど取りこぼしは増えない
    assert s["h3_missed"] == 0 and s["h3_lost_half"] < s["h24_lost_half"] and s["latency_hours"] == pdn.PIPELINE_LATENCY_HOURS
    assert s["h24_lost_half"] >= s["h24_missed"]


def test_detection_simulation_survives_empty_and_garbage():
    assert pdn.simulate_detection(None, NOW)["events_measured"] == 0
    assert pdn.simulate_detection([None, 3, {"x": 1}], NOW)["h24_missed"] == 0


# ── 取得の並列化・同一実行のキャッシュ ───────────────────────────────────────────────

def test_run_fetch_cache_avoids_a_second_request_in_the_same_run_and_keeps_failures():
    calls = []

    def fetch(url):
        calls.append(url)
        return (None, "site_blocked") if "blocked" in url else ("<html/>", "")
    c = rl.RunFetchCache(fetch)
    assert c("https://a.example/1") == ("<html/>", "") and c("https://a.example/1") == ("<html/>", "")
    assert c("https://a.example/blocked") == (None, "site_blocked") and c("https://a.example/blocked") == (None, "site_blocked")
    assert calls == ["https://a.example/1", "https://a.example/blocked"] and c.requests == 2 and c.hits == 2   # 遮断の後に同じ URL を取り直さない


def test_run_fetch_cache_is_memory_only_per_instance():
    a, b = rl.RunFetchCache(lambda u: ("A", "")), rl.RunFetchCache(lambda u: ("B", ""))
    assert a("u")[0] == "A" and b("u")[0] == "B"                                                    # 別の実行（別のインスタンス）の値を使わない


def test_fetch_all_runs_adapters_in_parallel_and_isolates_a_failure():
    started, lock = [], threading.Lock()

    def slow(f):
        with lock:
            started.append(time.monotonic())
        time.sleep(0.3)
        return {"entries": [1]}

    def boom(f):
        raise RuntimeError("x")
    t0 = time.monotonic()
    out = rl._fetch_all({"a": slow, "b": slow, "c": slow, "d": boom}, None)
    elapsed = time.monotonic() - t0
    assert out == {"a": {"entries": [1]}, "b": {"entries": [1]}, "c": {"entries": [1]}, "d": {}}   # 失敗した取得器だけ空
    assert elapsed < 0.8                                                                            # 順に取れば 0.9 秒以上かかる
    assert rl._fetch_all({}, None) == {}


def test_run_lookups_reports_actual_requests_and_cache_hits_and_still_matches():
    html = ('<html><script type="application/ld+json">{"@type":"Product","name":"x"}</script></html>')
    calls = []

    def fetch(url):
        calls.append(url)
        return html, ""
    rec = rl.run_lookups([], NOW, fetch)
    assert rec["http_actual"] == 0 and rec["http_cache_hits"] == 0 and calls == []
    assert set(rec) >= {"http_requested", "http_budget", "http_actual", "http_cache_hits"}


def test_detection_latency_is_included_and_a_zero_latency_run_is_never_worse():
    items = [_ev(application_start_date="2026-10-27", application_end_date="2026-10-27")]            # 約 24 時間の応募
    with_latency = pdn.simulate_detection(items, NOW)
    ideal = pdn.simulate_detection(items, NOW, latency_hours=0)
    assert with_latency["h24_lost_half"] > ideal["h24_lost_half"]                                    # 実行の遅れを入れると、取りこぼしが増える
    huge = pdn.simulate_detection(items, NOW, latency_hours=30)
    assert huge["h3_missed"] == 1.0                                                                  # 遅れが応募の長さを超えれば、間隔を短くしても見つけられない


def test_expired_event_with_open_status_is_ignored_by_the_tcg_priority():
    r = pdn.evaluate([_ev(application_start_date="2026-01-01", application_end_date="2026-01-02")], MSRP, NOW)
    assert r["events"] == [] and r["counts"]["active_tcg_priority"] == 0


def test_an_open_lottery_alone_is_not_high_density_but_demand_evidence_is():
    plain = pdn.evaluate([_ev(product_id=None, product_match="none")], None, NOW)["counts"]
    assert plain["active_tcg_priority"] == 0                                                          # 抽選が開いているだけ（二重の加点）では数えない
    soon = pdn.evaluate([_ev(status="ENDING_SOON", application_end_date="2026-10-29", product_id=None, product_match="none")], None, NOW)["counts"]
    assert soon["active_tcg_priority"] == 1
    linked = pdn.evaluate([_ev()], MSRP, NOW)["counts"]
    assert linked["active_tcg_priority"] == 1

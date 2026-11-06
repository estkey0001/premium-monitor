"""Coverage Wave 7b: 運営者向けの作業キュー（今日、人が何を確認すべきか。最大 10 件）。

通信はしない（合成の候補だけ）。**順位が高くても確定ではない。** 確定・actionable・通知・顧客向けの画面に影響させない。
"""
from __future__ import annotations

import json
import random
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.research import candidates as C
from src.research import operator_queue as oq

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=JST)
FRESH = "2026-11-06T09:00:00+09:00"
OLD = "2026-11-01T09:00:00+09:00"
ROOT = Path(__file__).resolve().parent.parent


def _c(cid="c1", *, spread=20000, missing=(), observed=FRESH, status=C.RESEARCH_CANDIDATE, momentum=None, signals=0, name="商品A", **k):
    row = {"candidate_id": cid, "status": status, "product_identity": {"product_id": "p-" + cid, "name": name, "genre": "camera"},
           "known_cost_spread": spread, "raw_spread": spread, "missing_requirements": list(missing), "exclusion_reasons": list(missing),
           "sell_observed_at": observed, "last_seen_at": NOW.isoformat(), "source": {"buy": "official", "sell": "店X"},
           "source_url": {"buy": "https://buy.example/1", "sell": "https://sell.example/1"}, "observed_buy_price": 100000,
           "observed_sell_price": 100000 + (spread or 0), "signal_points": signals}
    if momentum is not None:
        row["momentum"] = momentum
    row.update(k)
    return row


def _dp(cid="dp1", *, spread=15000, missing=(C.OFFICIAL_UNVERIFIED, C.PURCHASE_SHIPPING_UNKNOWN, C.CANONICAL_UNREGISTERED), observed=FRESH, **k):
    row = {"candidate_id": cid, "status": C.RESEARCH_CANDIDATE, "kind": "DISCOVERED_PRODUCT_CANDIDATE", "name": "未登録の商品", "identity_basis": "JAN",
           "identity_value": "4900000000000", "identity_status": "IDENTITY_CONFIRMED", "shop": "店Y", "observed_sell_price": 80000,
           "observed_at": observed, "raw_spread_hint": spread, "retail_price": 65000, "missing_requirements": list(missing),
           "source_url": "https://shop.example/x", "retail_url": "https://retail.example/x", "signal_points": 0}
    row.update(k)
    return row


def _ev(retailer="CARD_LABO", name="商品T", *, status="OPEN", hours=12.0, precision="datetime", channel="UNKNOWN", application_url=None, msrp=False,
        product_id="pid-1", match="exact", store="店舗1", signal=0, requirements=(), **k):
    row = {"retailer": retailer, "product_name": name, "product_id": product_id, "product_match": match, "provisional_product": False,
           "event_type": "LOTTERY", "status": status, "hours_to_deadline": hours, "application_end_precision": precision,
           "application_end": "2026-11-07T00:00:00+09:00", "channel": channel, "application_url": application_url,
           "announcement_url": "https://ann.example/1", "msrp_linked": msrp, "signal_points": signal, "store": store,
           "requirements": list(requirements), "quality": "partial"}
    row.update(k)
    return row


def _q(cands=(), dps=(), tcg=(), **k):
    return oq.build(candidates=list(cands), product_candidates=list(dps), tcg_events=list(tcg), now=NOW, **k)


def _row(res, cid):
    return next(r for r in res["queue"] if r["candidate_id"] == cid)


# ── 区分（URGENT / HIGH / MEDIUM / LOW）───────────────────────────────────────────────

def test_urgent_needs_positive_spread_exact_identity_fresh_sell_and_only_one_or_two_allowed_gaps():
    for miss in ((C.PURCHASE_SHIPPING_UNKNOWN,), (C.STOCK_UNKNOWN,), (C.NEEDS_CORROBORATION,), (C.PURCHASE_SHIPPING_UNKNOWN, C.STOCK_UNKNOWN)):
        assert _row(_q([_c(missing=miss)]), "c1")["priority"] == oq.URGENT, miss
    three = (C.PURCHASE_SHIPPING_UNKNOWN, C.STOCK_UNKNOWN, C.NEEDS_CORROBORATION)
    assert _row(_q([_c(missing=three)]), "c1")["priority"] == oq.HIGH                     # 3 個以上不足 → URGENT にしない
    assert _row(_q([_c(missing=(C.PURCHASE_SHIPPING_UNKNOWN, C.OFFICIAL_UNVERIFIED))]), "c1")["priority"] == oq.HIGH   # 許した種類以外が残る
    assert _row(_q([_c(spread=0, missing=(C.STOCK_UNKNOWN,))]), "c1")["priority"] != oq.URGENT                         # 価格差が正でない
    assert _row(_q([_c(spread=None, missing=(C.STOCK_UNKNOWN,))]), "c1")["priority"] != oq.URGENT
    assert _row(_q([_c(missing=(C.IDENTITY_PARTIAL, C.STOCK_UNKNOWN))]), "c1")["priority"] != oq.URGENT               # 同一性が一部だけ


def test_high_medium_and_low_classes():
    for miss in ((C.OFFICIAL_UNVERIFIED,), (C.CANONICAL_UNREGISTERED,), (C.IDENTITY_PARTIAL,), (C.ABOVE_GENRE_MAX,)):
        assert _row(_q([_c(missing=miss)]), "c1")["priority"] == oq.HIGH, miss
    assert _row(_q([_c(spread=0, signals=12)]), "c1")["priority"] == oq.MEDIUM                  # 価格差は無いが新型などの信号がある
    assert _row(_q([_c(spread=0)]), "c1")["priority"] == oq.LOW
    for miss in ((C.PRICE_ANOMALY_SUSPECTED,), (C.SELL_REJECTED,), (C.IDENTITY_UNCONFIRMED,), (C.GENERIC_SELL_URL,)):
        assert _row(_q([_c(missing=miss)]), "c1")["priority"] == oq.LOW, miss                  # 誤価格の疑い・同一性が弱い・店のトップ


def test_stale_candidates_are_demoted_never_left_urgent():
    r = _row(_q([_c(missing=(C.SELL_STALE, C.STOCK_UNKNOWN))]), "c1")
    assert r["priority"] == oq.LOW and r["next_action"] == oq.WAIT_FOR_FRESH_PRICE and r["stale"]
    r = _row(_q([_c(missing=(C.BUY_STALE,))]), "c1")
    assert r["priority"] == oq.LOW and r["next_action"] == oq.WAIT_FOR_FRESH_PRICE
    r = _row(_q([_c(missing=(C.STOCK_UNKNOWN,), observed=OLD)]), "c1")                          # 観測が 72 時間より古い
    assert r["priority"] == oq.LOW and r["stale"] and r["next_action"] == oq.WAIT_FOR_FRESH_PRICE
    res = _q([_c("gone", status=C.STALE, missing=["NOT_SEEN_THIS_RUN"])])                      # 今回見えなかった候補はキューに入れず、件数だけ
    assert res["queue"] == [] and res["counts"]["stale_demoted"] == 1


def test_quarantined_price_raises_research_order_but_is_never_confirmation():
    for miss in ((C.NEEDS_CORROBORATION,), (C.ABOVE_GENRE_MAX,), (C.PRICE_SPIKE,)):
        r = _row(_q([_c(missing=miss)]), "c1")
        assert r["quarantined"] and r["priority"] in (oq.URGENT, oq.HIGH), miss
        assert "status" not in r and "confirmed" not in r and "actionable" not in r                # 確定・actionable の項目を持たない
    assert _q([_c(missing=(C.ABOVE_GENRE_MAX,))])["counts"]["quarantined_in_queue"] == 1
    # 誤価格の疑いは差を加点しない
    bad = _row(_q([_c(spread=90000, missing=(C.PRICE_ANOMALY_SUSPECTED,))]), "c1")
    assert not any(p.startswith("spread+") for p in bad["score_parts"])


def test_positive_spread_orders_before_smaller_spread_within_a_class():
    res = _q([_c("small", spread=5000, missing=(C.OFFICIAL_UNVERIFIED,)), _c("big", spread=60000, missing=(C.OFFICIAL_UNVERIFIED,))])
    assert [r["candidate_id"] for r in res["queue"]] == ["big", "small"]
    assert _row(res, "big")["score"] > _row(res, "small")["score"]


def test_momentum_adds_points_only_when_usable_and_not_quarantined():
    mom = {"momentum_state": "RISING", "previous_price": 100000, "current_price": 108000, "delta_yen": 8000, "delta_percent": 8.0,
           "momentum_usable": True, "momentum_quarantined": False}
    base = _row(_q([_c(missing=(C.OFFICIAL_UNVERIFIED,))]), "c1")["score"]
    up = _row(_q([_c(missing=(C.OFFICIAL_UNVERIFIED,), momentum=mom)]), "c1")
    assert up["score"] == base + 10 and "momentum_rising+10" in up["score_parts"] and up["momentum"]["delta_yen"] == 8000
    for patch in ({"momentum_usable": False}, {"momentum_quarantined": True}, {"momentum_usable": True, "momentum_quarantined": True}):
        r = _row(_q([_c(missing=(C.OFFICIAL_UNVERIFIED,), momentum={**mom, **patch})]), "c1")
        assert r["score"] == base, patch                                                       # 隔離された価格・条件を満たさない急騰は加点しない
    stale = _row(_q([_c(missing=(C.SELL_STALE,), momentum=mom)]), "c1")
    assert "momentum_rising+10" not in stale["score_parts"]                                    # 古い候補に急騰の加点をしない


# ── 次の行動 ─────────────────────────────────────────────────────────────────────

def test_next_action_follows_the_missing_evidence():
    cases = {C.OFFICIAL_UNVERIFIED: oq.VERIFY_OFFICIAL_PRICE, C.PURCHASE_SHIPPING_UNKNOWN: oq.VERIFY_SHIPPING, C.STOCK_UNKNOWN: oq.VERIFY_STOCK,
             C.IDENTITY_PARTIAL: oq.VERIFY_IDENTITY, C.IDENTITY_UNCONFIRMED: oq.VERIFY_IDENTITY, C.CANONICAL_UNREGISTERED: oq.REGISTER_CANONICAL_PRODUCT,
             C.NEEDS_CORROBORATION: oq.FIND_CORROBORATING_SOURCE, C.ABOVE_GENRE_MAX: oq.FIND_CORROBORATING_SOURCE,
             C.PRICE_ANOMALY_SUSPECTED: oq.FIND_CORROBORATING_SOURCE, C.RETAIL_PRICE_MISSING: oq.VERIFY_RETAIL_PRICE,
             C.GENERIC_SELL_URL: oq.VERIFY_BUYBACK, C.CONDITION_UNKNOWN: oq.VERIFY_BUYBACK, C.SELL_STALE: oq.WAIT_FOR_FRESH_PRICE}
    for reason, action in cases.items():
        assert _row(_q([_c(missing=(reason,))]), "c1")["next_action"] == action, reason
    assert oq.next_actions([]) == []
    assert oq.next_actions([C.STOCK_UNKNOWN, C.OFFICIAL_UNVERIFIED, C.PURCHASE_SHIPPING_UNKNOWN]) == [
        oq.VERIFY_OFFICIAL_PRICE, oq.VERIFY_SHIPPING, oq.VERIFY_STOCK]                          # 決まった優先順（主の行動が先頭）


def test_completed_evidence_lowers_missing_and_recomputes_priority_and_next_action():
    before = _row(_q([_c(missing=(C.OFFICIAL_UNVERIFIED, C.PURCHASE_SHIPPING_UNKNOWN))]), "c1")
    after = _row(_q([_c(missing=(C.PURCHASE_SHIPPING_UNKNOWN,))]), "c1")                        # 運営者が公式の価格を確認した
    assert len(after["missing_evidence"]) < len(before["missing_evidence"])
    assert before["next_action"] == oq.VERIFY_OFFICIAL_PRICE and after["next_action"] == oq.VERIFY_SHIPPING
    assert before["priority"] == oq.HIGH and after["priority"] == oq.URGENT and after["score"] > before["score"]


# ── 買取起点の未登録商品 ────────────────────────────────────────────────────────────

def test_discovered_products_are_high_with_canonical_registration_and_never_auto_registered():
    r = _row(_q(dps=[_dp()]), "dp1")
    assert r["genre"] == oq.G_DISCOVERED and r["priority"] == oq.HIGH and oq.REGISTER_CANONICAL_PRODUCT in r["next_actions"]
    assert r["next_action"] == oq.VERIFY_OFFICIAL_PRICE                                         # 公式の確認が先・正本への登録は人が確かめてから
    partial = _row(_q(dps=[_dp(identity_status="IDENTITY_PARTIAL", missing=(C.OFFICIAL_UNVERIFIED, C.IDENTITY_PARTIAL, C.CANONICAL_UNREGISTERED))]), "dp1")
    assert partial["next_action"] == oq.VERIFY_IDENTITY and not partial["product"]["identity_confirmed"]
    skipped = _q(dps=[_dp(status=C.DISCOVERED), _dp("rej", status=C.REJECTED)])                 # 研究候補でないものは入れない
    assert skipped["queue"] == []


# ── TCG ─────────────────────────────────────────────────────────────────────────

def test_tcg_deadline_boost_only_for_timestamped_deadlines():
    near = _row(_q(tcg=[_ev(hours=10.0, precision="datetime")]), _tcg_id())
    assert near["priority"] == oq.URGENT and near["deadline_boosted"] and "deadline_boost+27" in near["score_parts"]      # 20 + (24-10)/2（近いほど高い）
    mid = _row(_q(tcg=[_ev(hours=60.0, precision="datetime")]), _tcg_id())
    assert mid["priority"] == oq.HIGH and "deadline_boost+10" in mid["score_parts"]
    date_only = _row(_q(tcg=[_ev(hours=10.0, precision="date")]), _tcg_id())                    # 日付だけの締切は URGENT にも大きな加点にもしない
    assert date_only["priority"] != oq.URGENT and "deadline_boost+3" in date_only["score_parts"] and oq.VERIFY_DEADLINE in date_only["next_actions"]
    unknown = _row(_q(tcg=[_ev(hours=None, precision="")]), _tcg_id())
    assert "deadline_boost+0" in unknown["score_parts"] and not unknown["deadline_boosted"] and oq.VERIFY_DEADLINE in unknown["next_actions"]
    far = _row(_q(tcg=[_ev(hours=200.0)]), _tcg_id())
    assert not far["deadline_boosted"]
    assert near["score"] > mid["score"] > far["score"]


def _tcg_id(retailer="CARD_LABO", name="商品T"):
    return oq._tcg_group_key({"retailer": retailer, "product_name": name, "event_type": "LOTTERY"})


def test_tcg_missing_application_url_is_verify_application_url_and_never_actionable():
    r = _row(_q(tcg=[_ev(channel="UNKNOWN", application_url=None)]), _tcg_id())
    assert oq.VERIFY_APPLICATION_URL in r["next_actions"] and "APPLICATION_URL_UNVERIFIED" in r["missing_evidence"]
    assert "actionable" not in r and "actionable" not in r["evidence"] and r["evidence"]["status"] in ("OPEN", "UPCOMING")
    ok = _row(_q(tcg=[_ev(application_url="https://draw.geo-online.co.jp/lottery/1")]), _tcg_id())
    assert oq.VERIFY_APPLICATION_URL not in ok["next_actions"]                                  # 応募の URL が確認できていれば不要
    for ch in ("SNS", "APP", "STORE_COUNTER", "MEMBER_LOGIN"):
        s = _row(_q(tcg=[_ev(channel=ch)]), _tcg_id())                                          # 公式ドメインに応募ページが無い経路は、条件の確認が次の行動
        assert oq.VERIFY_APPLICATION_URL not in s["next_actions"] and oq.VERIFY_ELIGIBILITY in s["next_actions"], ch


def test_tcg_identity_msrp_and_grouping():
    r = _row(_q(tcg=[_ev(product_id="", match="none", msrp=False)]), _tcg_id())
    assert r["next_action"] == oq.VERIFY_PRODUCT_IDENTITY and oq.VERIFY_MSRP in r["next_actions"] and not r["product"]["identity_confirmed"]
    linked = _row(_q(tcg=[_ev(msrp=True)]), _tcg_id())
    assert oq.VERIFY_MSRP not in linked["next_actions"] and linked["evidence"]["msrp_linked"]
    many = _q(tcg=[_ev(store=f"店{i}", hours=10.0 + i) for i in range(5)] + [_ev(name="別の商品", store="店9")])
    assert len(many["queue"]) == 2                                                              # 同じ小売・商品・種類は 1 件にまとめる
    g = _row(many, _tcg_id())
    assert g["evidence"]["store_count"] == 5 and g["evidence"]["hours_to_deadline"] == 10.0 and g["genre"] == oq.G_TCG
    assert _q(tcg=[_ev(status="WINNER_ANNOUNCED"), _ev(status="ENDED", name="終了")])["queue"] == []   # 応募の対象でない状態は入れない


def test_tcg_and_products_are_separated_by_genre_and_classes_order_the_queue():
    res = _q([_c("c1", missing=(C.OFFICIAL_UNVERIFIED,))], [_dp()], [_ev(hours=5.0)])
    genres = {r["genre"] for r in res["queue"]}
    assert genres == {oq.G_PRODUCT, oq.G_DISCOVERED, oq.G_TCG}
    assert [r["priority"] for r in res["queue"]] == sorted((r["priority"] for r in res["queue"]), key=oq._CLASS_ORDER.get)


# ── 順序の安定・上限・件数 ──────────────────────────────────────────────────────────

def test_queue_is_deterministic_and_ties_break_by_class_score_spread_freshness_then_id():
    items = [_c(f"c{i:02d}", spread=20000, missing=(C.OFFICIAL_UNVERIFIED,)) for i in range(6)]    # 同点
    ref = [r["candidate_id"] for r in _q(items)["queue"]]
    assert ref == sorted(ref)                                                                  # 同点は候補の ID の昇順
    for seed in range(5):
        shuffled = items[:]
        random.Random(seed).shuffle(shuffled)
        assert [r["candidate_id"] for r in _q(shuffled)["queue"]] == ref
    newer = [_c("a", observed="2026-11-05T09:00:00+09:00", missing=(C.OFFICIAL_UNVERIFIED,)),
             _c("b", observed="2026-11-06T09:00:00+09:00", missing=(C.OFFICIAL_UNVERIFIED,))]   # 点・差が同じなら新しい観測が先
    assert [r["candidate_id"] for r in _q(newer)["queue"]] == ["b", "a"]
    assert [r["rank"] for r in _q(items)["queue"]] == list(range(1, 7))


def test_queue_is_capped_at_ten_and_counts_match_the_queue():
    items = [_c(f"c{i:02d}", spread=1000 * (i + 1), missing=(C.OFFICIAL_UNVERIFIED,)) for i in range(14)]
    res = _q(items)
    n = res["counts"]
    assert len(res["queue"]) == 10 == n["queue_count"] and n["candidates_considered"] == 14
    assert n["urgent_count"] + n["high_count"] + n["medium_count"] + n["low_count"] == 10
    assert n["high_all"] == 14 and n["positive_spread_not_confirmed"] == 14
    assert [r["candidate_id"] for r in res["queue"]][0] == "c13"                                # 差が大きいものが先
    assert _q(items, max_queue=3)["counts"]["queue_count"] == 3
    empty = _q()
    assert empty["queue"] == [] and empty["counts"]["queue_count"] == 0


# ── 非公開・公開・確定への非依存 ────────────────────────────────────────────────────

def test_public_summary_has_only_aggregate_counts_and_private_queue_is_private():
    res = _q([_c("secret-id", name="秘密の商品名", missing=(C.STOCK_UNKNOWN,))], [_dp()], [_ev()])
    report = {"schema": 1, "type": "RESEARCH_CANDIDATES", "generated_at": NOW.isoformat(), "candidates": [], "counts": {}, "metrics": {
        "operator_queue": res["counts"], "operator_queue_next_actions": res["next_action_counts"]}, "operator_queue": res}
    summary = C.public_summary(report)
    pub = json.dumps(summary, ensure_ascii=False)
    for secret in ("secret-id", "秘密の商品名", "sell.example", "buy.example", "未登録の商品", "ann.example", "4900000000000"):
        assert secret not in pub, secret
    assert "operator_queue" not in summary and summary["operator_queue_counts"]["queue_count"] == 3
    assert all(isinstance(v, int) for v in summary["operator_queue_counts"].values())
    assert all(isinstance(v, int) for v in summary["operator_queue_next_actions"].values())
    assert set(summary["operator_queue_counts"]) <= set(C.COVERAGE_KEYS["operator_queue_counts"])
    assert set(summary["operator_queue_next_actions"]) <= set(C.COVERAGE_KEYS["operator_queue_next_actions"])
    assert {"operator_queue", "queue", "next_action", "missing_evidence", "score"} <= C.PRIVATE_KEYS


def test_write_outputs_puts_the_queue_only_in_the_private_directory(tmp_path):
    res = _q([_c("secret-id", name="秘密の商品名", missing=(C.STOCK_UNKNOWN,))])
    report = {"schema": 1, "type": "RESEARCH_CANDIDATES", "generated_at": NOW.isoformat(), "candidates": [], "counts": {}, "metrics": {
        "operator_queue": res["counts"], "operator_queue_next_actions": res["next_action_counts"]}, "operator_queue": res}
    C.write_outputs(report, {}, tmp_path / "priv", tmp_path / "pub", "run1")
    assert (tmp_path / "priv" / "operator_queue.json").exists() and [p.name for p in (tmp_path / "pub").iterdir()] == ["summary.json"]
    assert "秘密の商品名" in (tmp_path / "priv" / "operator_queue.json").read_text(encoding="utf-8")
    assert "秘密の商品名" not in (tmp_path / "pub" / "summary.json").read_text(encoding="utf-8")


def test_public_counts_and_next_action_keys_are_consistent_with_the_module():
    res = _q([_c()])
    assert set(res["counts"]) == set(oq.PUBLIC_COUNT_KEYS) == set(C.COVERAGE_KEYS["operator_queue_counts"])
    assert set(res["next_action_counts"]) == set(oq.PUBLIC_NEXT_ACTION_KEYS) == set(C.COVERAGE_KEYS["operator_queue_next_actions"])


def test_the_queue_module_has_no_dependency_on_confirmation_notification_or_network():
    src = (ROOT / "src" / "research" / "operator_queue.py").read_text(encoding="utf-8")
    code = re.sub(r'"""(?:.|\n)*?"""', "", src)
    for banned in ("notifiers", "actionability", "eligibility", "profit_formula", "price_evidence", "requests", "urllib", "httpx", "playwright", "send_",
                   "outbox", "telegram"):
        assert banned not in code, banned
    assert not re.search(r"\bVERIFIED\b", code)                                       # 確定の状態（VERIFIED）を扱わない（OFFICIAL_UNVERIFIED は別の語）


def test_queue_rows_never_change_candidate_status_or_confirmation_fields():
    cands = [_c("c1", missing=(C.STOCK_UNKNOWN,))]
    snapshot = json.dumps(cands, sort_keys=True, ensure_ascii=False)
    _q(cands)
    assert json.dumps(cands, sort_keys=True, ensure_ascii=False) == snapshot                    # 入力（候補）を書き換えない


def test_build_integrates_the_queue_privately_without_changing_candidates_or_public_counts():
    """`candidates.build` が作業キューを非公開の項目に作り、公開の集計には件数だけを出す（候補の状態は変えない）。"""
    ev = {"status": "OPEN", "event_type": "LOTTERY", "retailer": "CARD_LABO", "source_type": "STORE_OFFICIAL", "tcg": "POKEMON", "product_name": "商品T",
          "product_id": "pid-1", "product_match": "exact", "application_start": "2026-11-06T09:00:00+09:00", "application_end": "2026-11-07T10:00:00+09:00",
          "source_url": "https://www.c-labo.jp/shop/x/blog/1", "region": "JP", "store_name": "店舗1"}
    report, _state = C.build(products=[], observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), now=NOW, tcg_events=[ev],
                             tcg_msrp={"verified": []})
    q = report["operator_queue"]
    assert q["counts"]["tcg_queue_count"] == 1 and q["queue"][0]["genre"] == oq.G_TCG and report["metrics"]["operator_queue"] == q["counts"]
    assert q["queue"][0]["priority"] == oq.URGENT and q["queue"][0]["evidence"]["hours_to_deadline"] == 22.0     # 時刻つきの締切まで 22 時間
    summary = C.public_summary(report)
    assert summary["operator_queue_counts"]["queue_count"] == 1 and "operator_queue" not in summary
    assert "商品T" not in json.dumps(summary, ensure_ascii=False)
    assert summary["actionable"] is None or summary["actionable"] == 0 or isinstance(summary["actionable"], int)


def test_admin_shows_only_the_count_of_todays_candidates_never_individual_entries():
    from src.content.ui import admin
    res = _q([_c("secret-id", name="秘密の商品名", missing=(C.STOCK_UNKNOWN,))], [_dp()], [_ev()])
    summary = C.public_summary({"schema": 1, "type": "RESEARCH_CANDIDATES", "generated_at": NOW.isoformat(), "candidates": [], "counts": {},
                                "metrics": {"operator_queue": res["counts"], "operator_queue_next_actions": res["next_action_counts"]}, "operator_queue": res})
    view = admin.build_research(summary)
    assert view is not None                                                                    # 公開の集計は個別の項目の検査を通る
    html = admin._research({"research": view})
    assert "今日確認すべき候補" in html and "3件" in html
    for secret in ("secret-id", "秘密の商品名", "sell.example", "buy.example", "4900000000000", "VERIFY_", "STOCK_UNKNOWN", "商品T"):
        assert secret not in html, secret


def test_urgent_identity_gate_works_on_its_own_for_discovered_products():
    """同一性の確かさ（identity_status）は、足りない証拠の一覧とは別に URGENT の条件になる（未登録商品は同一性の状態だけで分かる）。"""
    ok = _row(_q(dps=[_dp(missing=(C.STOCK_UNKNOWN,))]), "dp1")
    assert ok["priority"] == oq.URGENT
    part = _row(_q(dps=[_dp(missing=(C.STOCK_UNKNOWN,), identity_status="IDENTITY_PARTIAL")]), "dp1")
    assert part["priority"] != oq.URGENT and not part["product"]["identity_confirmed"]


def test_stale_candidates_are_penalised_in_the_score_as_well_as_the_class():
    stale = _row(_q([_c(missing=(C.SELL_STALE,))]), "c1")
    fresh = _row(_q([_c(missing=(C.OFFICIAL_UNVERIFIED,))]), "c1")                              # 不足の数は同じ（1 個）
    assert "stale-30" in stale["score_parts"] and "stale-30" not in fresh["score_parts"]
    assert stale["score"] < fresh["score"] - 25


def test_public_summary_filters_even_when_the_metrics_carry_extra_private_keys():
    res = _q([_c("secret-id", name="秘密の商品名", missing=(C.STOCK_UNKNOWN,))])
    dirty = {**res["counts"], "queue": res["queue"], "candidate_ids": ["secret-id"], "secret": 1}
    report = {"schema": 1, "type": "RESEARCH_CANDIDATES", "generated_at": NOW.isoformat(), "candidates": [], "counts": {},
              "metrics": {"operator_queue": dirty, "operator_queue_next_actions": {**res["next_action_counts"], "product": "秘密の商品名"}}}
    pub = json.dumps(C.public_summary(report), ensure_ascii=False)
    assert "secret-id" not in pub and "秘密の商品名" not in pub and '"queue"' not in pub and "secret" not in pub


def test_tcg_rows_carry_the_deadline_with_its_precision_for_the_queue():
    from src.tcg import profit_dense as pdn
    base = {"status": "OPEN", "event_type": "LOTTERY", "retailer": "CARD_LABO", "source_type": "STORE_OFFICIAL", "tcg": "POKEMON", "product_name": "商品T",
            "product_id": "pid-1", "product_match": "exact", "application_start": "2026-11-06T09:00:00+09:00", "source_url": "https://www.c-labo.jp/x/1"}
    timed = pdn.evaluate([{**base, "application_end": "2026-11-07T10:00:00+09:00"}], None, NOW)["events"][0]
    assert timed["application_end_precision"] == "datetime" and timed["hours_to_deadline"] == 22.0 and timed["product_name"] == "商品T"
    only_date = pdn.evaluate([{**base, "application_end": None, "application_end_date": "2026-11-07"}], None, NOW)["events"][0]
    assert only_date["application_end_precision"] == "date" and only_date["hours_to_deadline"] is not None      # 日付だけは精度 date（時刻に見せない）
    none = pdn.evaluate([{**base, "application_end": None}], None, NOW)["events"]
    assert none[0]["application_end_precision"] == "" and none[0]["hours_to_deadline"] is None


# ══ 最終ゲート（reviewer H1 / M1〜M4・auditor M1 / M2）══════════════════════════════════════

def test_unreadable_missing_or_future_observation_times_are_never_fresh():
    for v in ("", "garbage", None, "2030-01-01T00:00:00+09:00", "2026-11-06T20:00:00+09:00"):      # 欠落・解釈不能・未来（時計より 1 時間を超えて先）
        r = _row(_q([_c(missing=(C.STOCK_UNKNOWN,), observed=v)]), "c1")
        assert r["priority"] == oq.LOW and r["stale"] and r["next_action"] == oq.WAIT_FOR_FRESH_PRICE, v
    near = _row(_q([_c(missing=(C.STOCK_UNKNOWN,), observed="2026-11-06T12:30:00+09:00")]), "c1")  # 時計の誤差の範囲（30 分先）は許す
    assert near["priority"] == oq.URGENT
    res = _q([_c("future", missing=(C.OFFICIAL_UNVERIFIED,), observed="2030-01-01T00:00:00+09:00"), _c("ok", missing=(C.OFFICIAL_UNVERIFIED,))])
    assert [r["candidate_id"] for r in res["queue"]][0] == "ok"                                    # 未来の時刻が並びで有利にならない


def test_tiny_spreads_are_not_urgent_or_high():
    for spread in (1, 100, 499):
        r = _row(_q([_c(spread=spread, missing=(C.PURCHASE_SHIPPING_UNKNOWN,))]), "c1")
        assert r["priority"] in (oq.MEDIUM, oq.LOW) and r["priority"] != oq.URGENT, spread
    assert _row(_q([_c(spread=500, missing=(C.PURCHASE_SHIPPING_UNKNOWN,))]), "c1")["priority"] == oq.URGENT     # 下限ちょうどは通る
    big = _q([_c("tiny", spread=1, missing=(C.PURCHASE_SHIPPING_UNKNOWN,)), _c("big", spread=80000, missing=(C.OFFICIAL_UNVERIFIED,))])
    assert [r["candidate_id"] for r in big["queue"]][0] == "big"                                  # 1 円差が価格差の大きい候補を押し出さない


def test_positive_spread_with_other_missing_evidence_is_high_and_has_a_next_action():
    for miss in (C.BUY_NOT_ITEM_LEVEL, C.RETAIL_PRICE_MISSING, C.CONDITION_UNKNOWN, C.CONDITION_MISMATCH, C.SELL_SAMPLE_INSUFFICIENT,
                 C.OFFICIAL_NOT_SOLD, C.ACQUISITION_CONDITIONAL):
        r = _row(_q([_c(missing=(miss,))]), "c1")
        assert r["priority"] == oq.HIGH and r["next_action"] is not None, miss                     # 価格差が正の候補を MEDIUM に埋もれさせない・行動が無いものを残さない
    many = _row(_q([_c(missing=(C.OFFICIAL_UNVERIFIED, C.CANONICAL_UNREGISTERED, C.IDENTITY_PARTIAL, C.NEEDS_CORROBORATION, C.RETAIL_PRICE_MISSING))]), "c1")
    assert many["priority"] == oq.MEDIUM                                                           # 足りない証拠が多すぎる（5 個以上）


def test_tcg_urgent_needs_a_confirmed_product_and_tcg_slots_are_capped():
    unconfirmed = _row(_q(tcg=[_ev(match="none", product_id="", hours=5.0)]), _tcg_id())
    assert unconfirmed["priority"] != oq.URGENT and oq.VERIFY_PRODUCT_IDENTITY in unconfirmed["next_actions"]
    assert _row(_q(tcg=[_ev(hours=5.0)]), _tcg_id())["priority"] == oq.URGENT                      # 同一性が確かなら URGENT
    many_tcg = [_ev(name=f"商品{i}", product_id=f"pid-{i}", hours=5.0) for i in range(10)]
    prods = [_c(f"prod{i}", spread=80000 - i, missing=(C.OFFICIAL_UNVERIFIED,)) for i in range(8)]
    res = _q(prods, tcg=many_tcg)
    ids = [r["candidate_id"] for r in res["queue"]]
    assert len(ids) == 10 and sum(1 for r in res["queue"] if r["genre"] == oq.G_TCG) == oq.TCG_MAX_IN_QUEUE   # TCG は上限まで・確かな商品が残る
    assert sum(1 for i in ids if i.startswith("prod")) == 6
    few = _q([prods[0]], tcg=many_tcg)
    assert "prod0" in [r["candidate_id"] for r in few["queue"]] and len(few["queue"]) == 10                 # 商品が少なければ空きを TCG で埋める
    only_tcg = _q(tcg=many_tcg)
    assert len(only_tcg["queue"]) == 10                                                           # 空きがあるときだけ、残りの TCG で埋める
    assert [r["rank"] for r in only_tcg["queue"]] == list(range(1, 11))


def test_tcg_group_aggregates_all_stores_not_only_the_nearest_deadline():
    a = _ev(store="店A", hours=5.0, application_url=None, match="none", product_id="")
    b = _ev(store="店B", hours=30.0, application_url="https://draw.geo-online.co.jp/lottery/1", match="exact", product_id="pid-1")
    r = _row(_q(tcg=[a, b]), _tcg_id())
    assert r["evidence"]["store_count"] == 2 and r["evidence"]["application_urls"] == ["https://draw.geo-online.co.jp/lottery/1"]
    assert oq.VERIFY_APPLICATION_URL not in r["next_actions"] and oq.VERIFY_PRODUCT_IDENTITY not in r["next_actions"]   # どれかの店舗で確認できている
    assert r["product"]["identity_confirmed"] and r["evidence"]["hours_to_deadline"] == 5.0
    unidentified = _q(tcg=[_ev(name="", product_id="", match="none", store="店1"), _ev(name="", product_id="", match="none", store="店2")])
    assert len(unidentified["queue"]) == 2                                                          # 商品名も ID も無いイベントを 1 件にまとめない


def test_momentum_bonus_needs_a_confirmed_identity():
    mom = {"momentum_state": "RISING", "previous_price": 100000, "current_price": 108000, "delta_yen": 8000, "delta_percent": 8.0,
           "momentum_usable": True, "momentum_quarantined": False}
    r = _row(_q([_c(missing=(C.IDENTITY_UNCONFIRMED,), momentum=mom)]), "c1")
    assert "momentum_rising+10" not in r["score_parts"]                                           # 同一性が確かでない候補に急騰の加点をしない


def test_broken_inputs_never_raise_and_build_survives_an_internal_failure(monkeypatch):
    weird = [_c("a", signal_points="x"), _c("b", product_identity="str"), _c("c", spread=20000.0, missing=(C.STOCK_UNKNOWN,)),
             _c("d", spread=float("nan")), _c("e", spread=True), "not a dict", None, {"status": C.RESEARCH_CANDIDATE}]
    res = _q(weird, [_dp(signal_points="x"), {"status": C.RESEARCH_CANDIDATE}], [_ev(signal="x"), {"status": "OPEN"}, "x"], max_queue=None)
    assert isinstance(res["queue"], list) and len(res["queue"]) <= 10
    assert _row(_q([_c(spread=20000.0, missing=(C.STOCK_UNKNOWN,))]), "c1")["priority"] == oq.URGENT          # 小数の価格差も読む
    assert oq._int("x", 5) == 5 and oq._int(None) == 0 and oq._int(float("inf")) == 0 and oq._int(True) == 0 and oq._int(3.7) == 3
    # 組み立てが失敗しても調査レポート全体を止めない（空のキューにする）
    monkeypatch.setattr(oq, "_tcg_items", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))     # build() が必ず呼ぶ部品を壊す
    report, _s = C.build(products=[], observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), now=NOW, tcg_events=[])
    assert report["operator_queue"]["queue"] == [] and report["metrics"]["operator_queue"]["queue_count"] == 0


def test_unreadable_or_future_times_sort_as_the_oldest_among_otherwise_equal_stale_candidates():
    """並べ替えの鍵（鮮度）だけで、未来・読めない時刻が有利にならない（どちらも古い扱いで LOW・点も同じ）。"""
    res = _q([_c("fut", missing=(C.OFFICIAL_UNVERIFIED,), observed="2030-01-01T00:00:00+09:00"),
              _c("old", missing=(C.OFFICIAL_UNVERIFIED,), observed=OLD),
              _c("bad", missing=(C.OFFICIAL_UNVERIFIED,), observed="garbage")])
    rows = {r["candidate_id"]: r for r in res["queue"]}
    assert {r["priority"] for r in rows.values()} == {oq.LOW} and len({r["score"] for r in rows.values()}) == 1
    assert [r["candidate_id"] for r in res["queue"]][0] == "old"                                   # 読める過去の時刻が先・未来と読めない時刻は最後


# ══ 最終ゲート（2 回目: reviewer M1 / auditor M1 ほか）══════════════════════════════════════

def test_quarantined_spread_is_capped_so_it_never_outranks_a_clean_candidate():
    res = _q([_c("quar", spread=300000, missing=(C.ABOVE_GENRE_MAX, C.NEEDS_CORROBORATION, C.OFFICIAL_UNVERIFIED)),
              _c("clean", spread=20000, missing=(C.OFFICIAL_UNVERIFIED,))])
    quar, clean = _row(res, "quar"), _row(res, "clean")
    assert f"spread+{oq.QUARANTINE_SPREAD_CAP}" in quar["score_parts"] and quar["quarantined"]
    assert [r["candidate_id"] for r in res["queue"]][0] == "clean" and clean["score"] > quar["score"]          # きれいな候補が先
    small = _row(_q([_c("q2", spread=5000, missing=(C.ABOVE_GENRE_MAX,))]), "q2")
    assert "spread+5" in small["score_parts"]                                                                 # 上限以下はそのまま


def test_a_failed_build_is_visible_in_the_public_counts_and_the_log_has_no_input_values(monkeypatch, caplog):
    secret = "SECRET-VALUE-123"
    monkeypatch.setattr(oq, "_tcg_items", lambda *a, **k: (_ for _ in ()).throw(KeyError(secret)))
    with caplog.at_level("WARNING"):
        report, _s = C.build(products=[], observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), now=NOW, tcg_events=[])
    assert report["metrics"]["operator_queue"]["queue_build_failed"] == 1 and report["operator_queue"]["error"] == "operator_queue_failed"
    assert "KeyError" in caplog.text and secret not in caplog.text                                       # 型名だけ。値はログに出さない
    summary = C.public_summary(report)
    assert summary["operator_queue_counts"]["queue_build_failed"] == 1 and summary["operator_queue_counts"]["queue_count"] == 0
    assert "error" not in json.dumps(summary) and secret not in json.dumps(summary)
    from src.content.ui import admin
    html = admin._research({"research": admin.build_research(summary)})
    assert "組み立てに失敗しました" in html                                                              # 0 件と失敗を区別して見せる
    monkeypatch.undo()                                                                                  # 壊した部品を元に戻してから、正常時は 0 件であることを確かめる
    ok = _q([_c()])
    assert ok["counts"]["queue_build_failed"] == 0 and oq.empty(NOW)["counts"]["queue_build_failed"] == 1


def test_signals_alone_do_not_lift_weak_identity_or_quarantined_candidates_out_of_low():
    mom = {"momentum_state": "RISING", "momentum_usable": True, "momentum_quarantined": True, "delta_yen": 5000, "delta_percent": 5.0,
           "previous_price": 100000, "current_price": 105000}
    for kw in ({"missing": (C.IDENTITY_PARTIAL,), "spread": None, "signals": 40}, {"missing": (C.IDENTITY_PARTIAL,), "spread": None, "momentum": {**mom, "momentum_quarantined": False}},
               {"missing": (C.ABOVE_GENRE_MAX,), "spread": None, "signals": 40}, {"missing": (), "spread": None, "momentum": mom}):
        assert _row(_q([_c(**kw)]), "c1")["priority"] == oq.LOW, kw
    assert _row(_q([_c(missing=(), spread=None, signals=40)]), "c1")["priority"] == oq.MEDIUM            # 同一性が確かで隔離されていなければ MEDIUM


def test_expired_tcg_deadline_with_open_status_is_low_and_asks_for_the_deadline():
    r = _row(_q(tcg=[_ev(hours=-0.1)]), _tcg_id())
    assert r["priority"] == oq.LOW and oq.VERIFY_DEADLINE in r["next_actions"] and not r["deadline_boosted"]
    assert _row(_q(tcg=[_ev(hours=0.0)]), _tcg_id())["priority"] == oq.URGENT                           # ちょうど締切の時刻は過ぎていない


def test_tcg_hours_of_mixed_or_wrong_types_never_raise_and_booleans_are_not_hours():
    res = _q(tcg=[_ev(store="店1", hours="soon"), _ev(store="店2", hours=5.0), _ev(store="店3", hours=None)])
    assert res["queue"][0]["evidence"]["hours_to_deadline"] == 5.0                                      # 文字列・None は読まず、数値の締切を代表にする
    for bad in (True, False, "5", float("nan"), float("inf")):
        r = _row(_q(tcg=[_ev(hours=bad)]), _tcg_id())
        assert r["priority"] != oq.URGENT and r["evidence"]["hours_to_deadline"] is None, bad
    assert oq._num(5) == 5 and oq._num(2.5) == 2.5 and oq._num(True) is None and oq._num("x") is None and oq._num(None) is None


def test_missing_requirements_of_wrong_types_are_read_safely():
    assert oq._reasons("STOCK_UNKNOWN") == {"STOCK_UNKNOWN"} and oq._reasons(None) == set() and oq._reasons(5) == set() and oq._reasons({"a": 1}) == set()
    assert oq._reasons([C.STOCK_UNKNOWN, None, 3, ["x"], ""]) == {C.STOCK_UNKNOWN}
    r = _row(_q([_c(missing=(), missing_requirements=C.STOCK_UNKNOWN)]), "c1")                          # 文字列 1 つは 1 つの理由（1 文字ずつにしない）
    assert r["missing_evidence"] == [C.STOCK_UNKNOWN] and r["priority"] == oq.URGENT and r["next_action"] == oq.VERIFY_STOCK
    res = _q([_c("x", missing_requirements=None), _c("y", missing_requirements=[None, [1]]), _c("z", missing_requirements={"k": 1})])
    assert len(res["queue"]) == 3                                                                       # 例外にしない


def test_positive_spread_without_visible_gaps_still_gets_a_default_next_action():
    r = _row(_q([_c(missing=(), spread=20000)]), "c1")
    assert r["next_action"] == oq.VERIFY_OFFICIAL_PRICE
    assert _row(_q([_c(missing=(), spread=0)]), "c1")["next_action"] is None                            # 価格差が無ければ付けない


# ══ 最終ゲート（3 回目: auditor M1 / reviewer M1・M2 ほか）══════════════════════════════════

def test_tcg_from_a_failed_or_unhealthy_collection_is_not_urgent_or_high():
    ev = _ev(hours=5.0)
    assert _row(_q(tcg=[ev]), _tcg_id())["priority"] == oq.URGENT
    old = _row(_q(tcg=[ev], tcg_fresh=False), _tcg_id())                                          # 収集が失敗して前回のデータが残った日
    assert old["priority"] == oq.LOW and old["stale"] and old["next_action"] == oq.WAIT_FOR_FRESH_PRICE
    ok = _row(_q(tcg=[ev], tcg_healthy_sources={"CARD_LABO"}), _tcg_id())
    assert ok["priority"] == oq.URGENT and not ok["stale"]
    bad = _row(_q(tcg=[ev], tcg_healthy_sources={"GEO"}), _tcg_id())                              # この取得元は今回健全でない
    assert bad["priority"] == oq.LOW and bad["stale"]
    assert _row(_q(tcg=[ev], tcg_healthy_sources=None), _tcg_id())["priority"] == oq.URGENT       # 不明（渡されない）なら制限しない


def test_build_passes_the_tcg_input_freshness_to_the_queue():
    ev = {"status": "OPEN", "event_type": "LOTTERY", "retailer": "CARD_LABO", "source_type": "STORE_OFFICIAL", "tcg": "POKEMON", "product_name": "商品T",
          "product_id": "pid-1", "product_match": "exact", "application_start": "2026-11-06T09:00:00+09:00", "application_end": "2026-11-07T10:00:00+09:00",
          "source_url": "https://www.c-labo.jp/shop/x/blog/1", "region": "JP", "store_name": "店舗1"}
    kw = dict(products=[], observations=[], msrp_evidence={}, official_meta={}, verified_pids=set(), now=NOW, tcg_events=[ev], tcg_msrp={"verified": []})
    fresh, _s = C.build(**kw)
    stale, _s = C.build(**kw, tcg_input_fresh=False)
    assert fresh["operator_queue"]["queue"][0]["priority"] == oq.URGENT
    assert stale["operator_queue"]["queue"][0]["priority"] == oq.LOW and stale["operator_queue"]["queue"][0]["stale"]
    unhealthy, _s = C.build(**kw, tcg_healthy_sources={"GEO"})
    assert unhealthy["operator_queue"]["queue"][0]["priority"] == oq.LOW


def test_urgent_tcg_events_are_ordered_by_how_close_the_deadline_is():
    res = _q(tcg=[_ev(name=f"T{h}", product_id=f"p{h}", hours=float(h)) for h in (23, 2, 12, 1)])
    assert [r["evidence"]["hours_to_deadline"] for r in res["queue"]] == [1.0, 2.0, 12.0, 23.0]
    assert all(r["priority"] == oq.URGENT for r in res["queue"])
    same = _q(tcg=[_ev(name=f"T{i}", product_id=f"p{i}", hours=6.0) for i in range(3)])             # 同じ近さなら、決まった鍵（ID）で安定
    assert [r["candidate_id"] for r in same["queue"]] == sorted(r["candidate_id"] for r in same["queue"])


def test_tcg_keeps_a_minimum_of_slots_even_when_many_products_are_high():
    prods = [_c(f"h{i}", spread=3000 + i, missing=(C.OFFICIAL_UNVERIFIED,)) for i in range(12)]
    ev = _ev(hours=48.0, msrp=True, signal=8)                                                      # 締切 48 時間・定価に結べる（HIGH）
    res = _q(prods, tcg=[ev])
    assert any(r["genre"] == oq.G_TCG for r in res["queue"]) and len(res["queue"]) == 10             # 商品の HIGH が 10 件以上でも TCG が残る
    res2 = _q(prods, tcg=[_ev(name=f"T{i}", product_id=f"p{i}", hours=48.0) for i in range(5)])
    n = sum(1 for r in res2["queue"] if r["genre"] == oq.G_TCG)
    assert oq.TCG_MIN_IN_QUEUE <= n <= oq.TCG_MAX_IN_QUEUE


def test_urgent_tcg_displaces_low_waiting_products_but_not_high_products():
    waiting = [_c(f"w{i}", missing=(C.SELL_STALE,)) for i in range(10)]                             # LOW（新しい価格を待つだけ）
    urgent = [_ev(name=f"T{i}", product_id=f"p{i}", hours=float(i + 1)) for i in range(6)]
    res = _q(waiting, tcg=urgent)
    assert sum(1 for r in res["queue"] if r["genre"] == oq.G_TCG) == 6                              # 期限つきの URGENT の TCG が、待つだけの行に負けて外れない
    high = [_c(f"h{i}", spread=60000 + i, missing=(C.OFFICIAL_UNVERIFIED,)) for i in range(8)]
    res2 = _q(high, tcg=urgent)
    assert sum(1 for r in res2["queue"] if r["genre"] == oq.G_TCG) == oq.TCG_MAX_IN_QUEUE            # HIGH の商品は押し出さない


def test_tcg_group_representative_is_the_nearest_live_deadline_and_urgent_needs_its_identity():
    open_store = _row(_q(tcg=[_ev(store="s1", hours=-2.0), _ev(store="s2", hours=10.0)]), _tcg_id())
    assert open_store["priority"] == oq.URGENT and open_store["evidence"]["hours_to_deadline"] == 10.0   # 期限切れの行が、開いている店舗を隠さない
    only_expired = _row(_q(tcg=[_ev(store="s1", hours=-2.0), _ev(store="s2", hours=-5.0)]), _tcg_id())
    assert only_expired["priority"] == oq.LOW
    fuzzy_first = _row(_q(tcg=[_ev(store="s1", hours=1.0, match="fuzzy", product_id=""), _ev(store="s2", hours=8.0)]), _tcg_id())
    assert fuzzy_first["priority"] != oq.URGENT                                                      # 代表（最も近い締切）の同一性が確かでない
    assert fuzzy_first["product"]["identity_confirmed"]                                              # 表示と次の行動は、どれかの店舗で確認できていれば確認済み


def _ev_raw(**raw):
    ev = _ev()
    ev.update(raw)                                                                                  # 補助関数の型変換を通さず、壊れた値をそのまま入れる
    return ev


def test_tcg_requirements_of_wrong_types_do_not_break_the_queue():
    for bad in (5, True, {"a": 1}, None, "FOLLOW", ["FOLLOW", None, 3]):
        res = _q([_c()], tcg=[_ev_raw(requirements=bad)])
        assert len(res["queue"]) == 2, bad
    r = _row(_q(tcg=[_ev_raw(requirements="FOLLOW")]), _tcg_id())
    assert r["evidence"]["requirements"] == ["FOLLOW"] and oq.VERIFY_ELIGIBILITY in r["next_actions"]


def test_medium_candidates_always_get_a_next_action_and_quarantined_rows_get_no_momentum_bonus():
    for spread in (0, -5000, None):
        r = _row(_q([_c(spread=spread, signals=12, missing=())]), "c1")
        assert r["priority"] == oq.MEDIUM and r["next_action"] == oq.VERIFY_RETAIL_PRICE, spread
    mom = {"momentum_state": "RISING", "previous_price": 100000, "current_price": 108000, "delta_yen": 8000, "delta_percent": 8.0,
           "momentum_usable": True, "momentum_quarantined": False}
    q = _row(_q([_c(missing=(C.ABOVE_GENRE_MAX,), momentum=mom)]), "c1")                             # 行が隔離されている（momentum の隔離フラグは False）
    assert "momentum_rising+10" not in q["score_parts"]


def test_time_boundaries_for_staleness_and_the_tcg_urgent_window():
    at = lambda h: (NOW - timedelta(hours=h)).isoformat()                                            # noqa: E731
    assert not _row(_q([_c(missing=(C.STOCK_UNKNOWN,), observed=at(72))]), "c1")["stale"]            # ちょうど 72 時間は新しい
    assert _row(_q([_c(missing=(C.STOCK_UNKNOWN,), observed=at(72.1))]), "c1")["stale"]
    assert _row(_q(tcg=[_ev(hours=24.0)]), _tcg_id())["priority"] == oq.URGENT                       # ちょうど 24 時間は URGENT
    assert _row(_q(tcg=[_ev(hours=24.1)]), _tcg_id())["priority"] == oq.HIGH
    assert _row(_q(tcg=[_ev(hours=0.0)]), _tcg_id())["priority"] == oq.URGENT and _row(_q(tcg=[_ev(hours=-0.01)]), _tcg_id())["priority"] == oq.LOW

"""Coverage Wave 7c-1: 公式の価格が確認できない原因の分類・価格の種類・作業キューの次の行動。

通信はしない（合成の値だけ）。**数値のために証拠を弱めない**: 条件つきの価格・ポイントは現金の確定の仕入れ値にしない。
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from src.research import candidates as C
from src.research import evidence_gap as eg
from src.research import operator_queue as oq
from src.research import retail_lookup as rl

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=JST)
ROOT = Path(__file__).resolve().parent.parent


# ── 価格の種類 ───────────────────────────────────────────────────────────────────

def _pe(**k):
    base = {"price": 100000, "regular_price": 0, "immediate_discount": 0, "required_coupon": "", "campaign_conditions": "", "campaign_price": 0,
            "member_only": False, "limited_quantity": False, "points": 0, "cashback": 0}
    base.update(k)
    return rl.price_evidence(base)


def test_regular_and_unconditional_sale_are_confirmable_cash_prices():
    r = _pe()
    assert r["price_type"] == eg.REGULAR and r["confirmable"] and r["effective_price"] == 100000
    s = _pe(immediate_discount=5000)                                                              # 条件なしで誰でも使える即時値引き
    assert s["price_type"] == eg.SALE and s["confirmable"] and s["effective_price"] == 95000


def test_coupon_membership_and_campaign_prices_are_conditional_and_never_confirmable():
    cp = _pe(required_coupon="SAVE10", price=90000, regular_price=100000)
    assert cp["price_type"] == eg.COUPON and not cp["confirmable"] and cp["effective_price"] == 100000       # クーポン後の価格を仕入れ値にしない
    mem = _pe(member_only=True, price=92000, regular_price=100000)
    assert mem["price_type"] == eg.MEMBERSHIP and not mem["confirmable"] and mem["effective_price"] == 100000
    camp = _pe(campaign_conditions="期間限定 2,000円引き", price=98000)
    assert camp["price_type"] == eg.CONDITIONAL and not camp["confirmable"]
    lim = _pe(limited_quantity=True, price=95000)
    assert lim["price_type"] == eg.CONDITIONAL and not lim["confirmable"]
    assert _pe(campaign_price=88000)["price_type"] == eg.CONDITIONAL                                  # キャンペーン価格だけ（条件の説明なし）も条件つき


def test_points_and_cashback_are_references_never_subtracted_from_cash():
    p = _pe(points=5000)
    assert p["price_type"] == eg.REGULAR and p["effective_price"] == 100000 and p["reference_types"] == [eg.POINTS]    # 現金から引かない
    both = _pe(points=3000, cashback=2000)
    assert both["reference_types"] == [eg.POINTS, eg.CASHBACK] and both["effective_price"] == 100000 and both["price_type"] == eg.REGULAR
    sale_pts = _pe(immediate_discount=1000, points=9000)
    assert sale_pts["price_type"] == eg.SALE and sale_pts["effective_price"] == 99000


def test_price_type_priority_and_unknown_and_bad_inputs():
    assert _pe(price=0)["price_type"] == eg.UNKNOWN and not _pe(price=0)["confirmable"]
    both = _pe(required_coupon="X", member_only=True, price=90000, regular_price=100000)
    assert both["price_type"] == eg.COUPON                                                           # クーポンが先
    assert eg.price_type_of(None)["price_type"] == eg.UNKNOWN and eg.price_type_of("x")["price_type"] == eg.UNKNOWN
    assert eg.price_type_of({"listed_price": True, "price_conditions": None})["price_type"] == eg.UNKNOWN   # 真偽値は価格にしない
    assert eg.price_type_of({"listed_price": 1000, "points": "x", "cashback": None})["reference_types"] == []
    assert set(eg.PRICE_TYPES) == {eg.REGULAR, eg.SALE, eg.COUPON, eg.MEMBERSHIP, eg.CONDITIONAL, eg.UNKNOWN}
    assert eg.CONFIRMABLE_TYPES == {eg.REGULAR, eg.SALE}


def test_lookup_result_carries_the_price_type_and_apply_lookups_marks_conditional_rows():
    now = NOW
    row = {"candidate_id": "dp1", "kind": "DISCOVERED_PRODUCT_CANDIDATE", "status": C.DISCOVERED, "name": "X", "identity_basis": "JAN",
           "identity_value": "4900000000000", "shop": "店Y", "observed_sell_price": 130000, "observed_at": "2026-11-06T09:00:00+09:00",
           "retail_price_hint": None, "missing_requirements": ["CANONICAL_UNREGISTERED", "IDENTITY_NOT_VERIFIED_BY_OFFICIAL"]}

    def lk(**k):
        pe = rl.price_evidence({"price": 100000, **k})
        return {"status": "MATCHED", "price": pe["effective_price"], "observed_at": "2026-11-06T10:00:00+09:00", "retailer": "店Z",
                "source_type": "AUTHORIZED_RETAILER", "product_url": "https://r.example/p", "availability_state": "IN_STOCK",
                "identity_evidence": {"method": "jan_exact", "attributes_verified": True}, **{k2: v for k2, v in pe.items() if k2 != "effective_price"}}
    clean = C.apply_lookups([dict(row)], {"dp1": lk()}, now, "2026-11-06T10:00:00+09:00")[0]
    assert clean["retail_price_type"] == eg.REGULAR and clean["retail_confirmable"] and C.ACQUISITION_CONDITIONAL not in clean["missing_requirements"]
    coupon = C.apply_lookups([dict(row)], {"dp1": lk(required_coupon="X", price=90000, regular_price=100000)}, now, "2026-11-06T10:00:00+09:00")[0]
    assert coupon["retail_price_type"] == eg.COUPON and not coupon["retail_confirmable"] and C.ACQUISITION_CONDITIONAL in coupon["missing_requirements"]
    assert coupon["research_class"] == C.STANDARD_RESEARCH                                           # 条件つきは高優先にしない
    pts = C.apply_lookups([dict(row)], {"dp1": lk(points=8000)}, now, "2026-11-06T10:00:00+09:00")[0]
    assert pts["retail_price_type"] == eg.REGULAR and pts["retail_reference_types"] == [eg.POINTS] and pts["retail_price"] == 100000


def test_price_type_counts_are_aggregate_only_and_count_rejected_conditionals():
    rows = [{"retail_price_type": t, "retail_reference_types": refs} for t, refs in
            ((eg.REGULAR, []), (eg.REGULAR, [eg.POINTS]), (eg.SALE, []), (eg.COUPON, []), (eg.MEMBERSHIP, [eg.CASHBACK]), (eg.CONDITIONAL, []), (eg.UNKNOWN, []))]
    c = eg.price_type_counts(rows + [{"retail_price_type": "bogus"}, None, "x"])
    assert c["REGULAR"] == 2 and c["SALE"] == 1 and c["COUPON"] == 1 and c["MEMBERSHIP"] == 1 and c["CONDITIONAL"] == 1 and c["UNKNOWN"] == 1
    assert c["with_points"] == 1 and c["with_cashback"] == 1 and c["rejected_conditional"] == 3
    assert set(c) == set(C.COVERAGE_KEYS["price_type_counts"])


# ── 公式の価格が確認できない原因 ────────────────────────────────────────────────────

def _gap(**k):
    base = dict(evidence="UNKNOWN", meta={"url": "https://official.example/p", "source_id": "src_x"}, official_not_sold=False, source_blocked=False)
    base.update(k)
    return eg.official_gap_cause(**base)


def test_each_official_gap_cause_and_the_fixed_order():
    assert _gap(official_not_sold=True) == eg.SALE_ENDED
    assert _gap(meta={"official_not_sold": True, "url": "https://o.example/p"}) == eg.SALE_ENDED
    assert _gap(meta={"identity_mismatch": True, "url": "https://o.example/p"}) == eg.IDENTITY_NOT_MATCHED
    assert _gap(meta={}) == eg.SOURCE_NOT_IMPLEMENTED and _gap(meta=None) == eg.SOURCE_NOT_IMPLEMENTED and _gap(meta={"url": " "}) == eg.SOURCE_NOT_IMPLEMENTED
    assert _gap(source_blocked=True) == eg.SOURCE_BLOCKED
    assert _gap(evidence="STALE") == eg.VERIFICATION_STALE
    assert _gap(evidence="CONFIGURED_REFERENCE") == eg.CONFIGURED_PRICE_ONLY
    assert _gap(evidence="UNKNOWN") == eg.PRICE_NOT_FOUND
    assert _gap(evidence="UNKNOWN", meta={"source_id": "src_x"}) == eg.SOURCE_NOT_IMPLEMENTED                  # URL が無ければ価格を読みようがない
    assert _gap(evidence="VERIFIED_CURRENT") == eg.UNKNOWN_CAUSE and _gap(evidence="bogus") == eg.UNKNOWN_CAUSE      # 確認済みは不足ではない
    # 順序: 販売終了 > 商品の不一致 > 取得元が未登録 > 遮断 > 古い
    assert _gap(official_not_sold=True, source_blocked=True, evidence="STALE", meta={"identity_mismatch": True}) == eg.SALE_ENDED
    assert _gap(source_blocked=True, evidence="STALE", meta={"identity_mismatch": True, "url": "https://o.example/p"}) == eg.IDENTITY_NOT_MATCHED
    assert _gap(source_blocked=True, meta={}) == eg.SOURCE_NOT_IMPLEMENTED
    assert _gap(source_blocked=True, evidence="STALE") == eg.SOURCE_BLOCKED


def test_gap_counts_cover_every_cause_and_ignore_other_rows():
    rows = [{"official_gap": eg.SALE_ENDED}, {"official_gap": eg.SALE_ENDED}, {"official_gap": eg.VERIFICATION_STALE}, {"official_gap": "bogus"}, {}, None, "x"]
    c = eg.gap_counts(rows)
    assert c[eg.SALE_ENDED] == 2 and c[eg.VERIFICATION_STALE] == 1 and sum(c.values()) == 3 and set(c) == set(eg.GAP_CAUSES) == set(C.COVERAGE_KEYS["official_gap_counts"])


def test_the_evidence_gap_module_has_no_network_notification_or_confirmation_dependency():
    code = re.sub(r'"""(?:.|\n)*?"""', "", (ROOT / "src" / "research" / "evidence_gap.py").read_text(encoding="utf-8"))
    for banned in ("requests", "urllib", "httpx", "playwright", "notifiers", "outbox", "eligibility", "actionability", "proxy", "stealth", "captcha"):
        assert banned not in code, banned
    imports = [ln.strip() for ln in code.splitlines() if re.match(r"\s*(from|import)\s", ln)]
    assert set(imports) <= {"from __future__ import annotations", "from datetime import datetime, timedelta, timezone"}, imports    # 標準ライブラリの日時だけ（他の部品・通信に依存しない）


# ── 調査候補への接続と作業キュー ────────────────────────────────────────────────────

PRODUCTS = [{"id": "p1", "name": "調査用ダミー商品XYZ", "genre": "camera", "jan": "4900000000011", "part_numbers": []}]


def _off(**kw):
    base = {"product_id": "p1", "price_role": "official", "price_type": "official_price", "canonical_price_type": "RETAIL", "price": 100000,
            "source_id": "official", "condition": "new_unopened", "link_type": "official_top", "is_fresh": True, "freshness_basis": "config_unknown_date",
            "accessory_flag": False, "wrong_model_flag": False, "is_exact_product_match": False}
    base.update(kw)
    return base


def _good_sell(**kw):
    base = {"product_id": "p1", "price_role": "sell", "price_type": "buyback_price", "canonical_price_type": "BUYBACK_CASH", "price": 150000, "source_id": "s1",
            "source_name": "店A", "condition": "new_unopened", "is_exact_product_match": True, "link_type": "item", "is_fresh": True,
            "freshness_basis": "observed", "accessory_flag": False, "wrong_model_flag": False, "rejection_reason": "",
            "observed_at": "2026-11-06T09:00:00+09:00", "item_url": "https://s.example/1"}
    base.update(kw)
    return base


def _build(ev="CONFIGURED_REFERENCE", meta=None, blocked=None, **kw):
    rep, _st = C.build(products=PRODUCTS, observations=[_off(), _good_sell()], msrp_evidence={"p1": ev}, official_meta={"p1": meta} if meta is not None else {},
                       verified_pids=set(), now=NOW, blocked_sources=blocked, **kw)
    return rep


def test_candidate_rows_carry_the_gap_cause_and_the_queue_follows_it():
    rep = _build(ev="STALE", meta={"url": "https://official.example/p", "source_id": "official"})
    c = rep["candidates"][0]
    assert c["official_gap"] == eg.VERIFICATION_STALE and C.OFFICIAL_UNVERIFIED in c["missing_requirements"]
    q = rep["operator_queue"]["queue"][0]
    assert q["official_gap"] == eg.VERIFICATION_STALE and q["next_action"] == oq.VERIFY_OFFICIAL_PRICE
    ended = _build(ev="CONFIGURED_REFERENCE", meta={"official_not_sold": True, "url": "https://official.example/p", "source_id": "official"})
    cq = ended["operator_queue"]["queue"][0]
    assert ended["candidates"][0]["official_gap"] == eg.SALE_ENDED
    assert cq["next_action"] == oq.VERIFY_RETAIL_PRICE and oq.VERIFY_OFFICIAL_PRICE not in cq["next_actions"]      # 公式が売っていないので公式を確認しても変わらない
    blocked = _build(ev="UNKNOWN", meta={"url": "https://official.example/p", "source_id": "official", "source_blocked": True})
    assert blocked["candidates"][0]["official_gap"] == eg.SOURCE_BLOCKED
    shop_blocked = _build(ev="UNKNOWN", meta={"url": "https://official.example/p", "source_id": "official"}, blocked={"official"})
    assert shop_blocked["candidates"][0]["official_gap"] == eg.PRICE_NOT_FOUND                      # 買取店の遮断の集合は、公式の取得元の遮断ではない（混ぜない）
    assert blocked["operator_queue"]["queue"][0]["next_action"] == oq.VERIFY_OFFICIAL_PRICE                       # 遮断は回避せず、人が公式ページで確認する
    nosrc = _build(ev="UNKNOWN", meta={})
    assert nosrc["candidates"][0]["official_gap"] == eg.SOURCE_NOT_IMPLEMENTED


def test_public_summary_has_only_gap_and_price_type_counts():
    rep = _build(ev="STALE", meta={"url": "https://official.example/p", "source_id": "official"})
    s = C.public_summary(rep)
    assert s["official_gap_counts"][eg.VERIFICATION_STALE] == 1 and sum(s["official_gap_counts"].values()) == 1
    assert set(s["price_type_counts"]) == set(C.COVERAGE_KEYS["price_type_counts"])
    pub = json.dumps(s, ensure_ascii=False)
    for secret in ("official.example", "調査用ダミー商品", "s.example", "official_gap\"", "retail_price_type"):
        assert secret not in pub, secret
    assert {"official_gap", "retail_price_type", "retail_confirmable", "retail_reference_types"} <= C.PRIVATE_KEYS


def test_official_not_sold_alone_asks_for_a_retail_price_not_an_official_check():
    q = oq.build(candidates=[{"candidate_id": "c", "status": C.RESEARCH_CANDIDATE, "product_identity": {"product_id": "p", "name": "N"},
                              "known_cost_spread": 20000, "missing_requirements": [C.OFFICIAL_NOT_SOLD], "sell_observed_at": "2026-11-06T09:00:00+09:00"}],
                 product_candidates=[], tcg_events=[], now=NOW)["queue"][0]
    assert q["next_action"] == oq.VERIFY_RETAIL_PRICE and q["priority"] == oq.HIGH
    both = oq.build(candidates=[{"candidate_id": "c", "status": C.RESEARCH_CANDIDATE, "product_identity": {"product_id": "p", "name": "N"},
                                 "known_cost_spread": 20000, "missing_requirements": [C.OFFICIAL_UNVERIFIED, C.OFFICIAL_NOT_SOLD],
                                 "official_gap": "SALE_ENDED", "sell_observed_at": "2026-11-06T09:00:00+09:00"}],
                    product_candidates=[], tcg_events=[], now=NOW)["queue"][0]
    assert both["next_actions"][0] == oq.VERIFY_RETAIL_PRICE and oq.VERIFY_OFFICIAL_PRICE not in both["next_actions"]


def test_queue_is_recomputed_after_official_evidence_is_added():
    """運営者が公式の価格を確認すると（証拠が増えると）、次回の run で足りない証拠が減り、HIGH → URGENT になりうる（強制はしない）。"""
    before = _build(ev="CONFIGURED_REFERENCE", meta={"url": "https://official.example/p", "source_id": "official"})
    bq = before["operator_queue"]["queue"][0]
    assert bq["priority"] == oq.HIGH and bq["next_action"] == oq.VERIFY_OFFICIAL_PRICE
    after = _build(ev="VERIFIED_CURRENT", meta={"url": "https://official.example/p", "source_id": "official"})
    cands = [c for c in after["candidates"] if c["status"] == C.RESEARCH_CANDIDATE]
    assert not cands or all(C.OFFICIAL_UNVERIFIED not in c["missing_requirements"] for c in cands)           # 公式の不足が消える
    assert all(c["candidate_id"] != bq["candidate_id"] or "official_gap" not in c for c in after["candidates"])   # 確認済みなら原因は付かない
    no_evidence = _build(ev="CONFIGURED_REFERENCE", meta={"url": "https://official.example/p", "source_id": "official"})
    assert no_evidence["operator_queue"]["queue"][0]["priority"] == oq.HIGH                                  # 証拠が見つからなければ HIGH のまま（昇格を強制しない）


def test_a_conditional_price_type_alone_blocks_confirmation_even_if_other_condition_fields_are_missing():
    """価格の種類だけが条件つき（他の条件の項目が空・基準が UNCONDITIONAL）でも、確定の仕入れ値・高優先に使わない（層ごとの単独検証）。"""
    row = {"candidate_id": "dp1", "kind": "DISCOVERED_PRODUCT_CANDIDATE", "status": C.DISCOVERED, "name": "X", "identity_basis": "JAN",
           "identity_value": "4900000000000", "shop": "店Y", "observed_sell_price": 130000, "observed_at": "2026-11-06T09:00:00+09:00",
           "retail_price_hint": None, "missing_requirements": ["CANONICAL_UNREGISTERED", "IDENTITY_NOT_VERIFIED_BY_OFFICIAL"]}
    for ptype in ("COUPON", "MEMBERSHIP", "CONDITIONAL"):
        lk = {"status": "MATCHED", "price": 100000, "observed_at": "2026-11-06T10:00:00+09:00", "retailer": "店Z", "source_type": "AUTHORIZED_RETAILER",
              "product_url": "https://r.example/p", "availability_state": "IN_STOCK", "identity_evidence": {"method": "jan_exact", "attributes_verified": True},
              "price_basis": "UNCONDITIONAL", "price_conditions": [], "price_type": ptype, "confirmable": False, "reference_types": []}
        r = C.apply_lookups([dict(row)], {"dp1": lk}, NOW, "2026-11-06T10:00:00+09:00")[0]
        assert C.ACQUISITION_CONDITIONAL in r["missing_requirements"] and r["research_class"] == C.STANDARD_RESEARCH, ptype
    ok = dict(lk, price_type="REGULAR", confirmable=True)
    r = C.apply_lookups([dict(row)], {"dp1": ok}, NOW, "2026-11-06T10:00:00+09:00")[0]
    assert C.ACQUISITION_CONDITIONAL not in r["missing_requirements"]


def test_public_summary_filters_the_gap_and_price_type_counts_to_the_allowed_keys():
    rep = _build(ev="STALE", meta={"url": "https://official.example/p", "source_id": "official"})
    rep["metrics"]["official_gap_counts"] = {**rep["metrics"]["official_gap_counts"], "secret_product": 1, "SALE_ENDED": "x"}
    rep["metrics"]["price_type_counts"] = {**rep["metrics"]["price_type_counts"], "candidate": 3}
    s = C.public_summary(rep)
    assert "secret_product" not in s["official_gap_counts"] and "SALE_ENDED" not in s["official_gap_counts"] and "candidate" not in s["price_type_counts"]


def test_rejected_conditional_counts_cover_coupon_membership_and_conditional():
    for t in (eg.COUPON, eg.MEMBERSHIP, eg.CONDITIONAL):
        assert eg.price_type_counts([{"retail_price_type": t}])["rejected_conditional"] == 1, t
    for t in (eg.REGULAR, eg.SALE, eg.UNKNOWN):
        assert eg.price_type_counts([{"retail_price_type": t}])["rejected_conditional"] == 0, t


def test_admin_shows_only_the_counts_of_each_official_gap_cause():
    from src.content.ui import admin
    rep = _build(ev="STALE", meta={"url": "https://official.example/p", "source_id": "official"})
    view = admin.build_research(C.public_summary(rep))
    assert view is not None                                                                         # 公開の集計は個別の項目の検査を通る
    html = admin._research({"research": view})
    assert "公式の価格が確認できない原因" in html and "確認が古い 1件" in html
    for secret in ("official.example", "調査用ダミー商品", "VERIFICATION_STALE", "SALE_ENDED", "official_gap"):
        assert secret not in html, secret
    none = admin._research({"research": admin.build_research(C.public_summary(_build(ev="VERIFIED_CURRENT", meta={"url": "u", "source_id": "s"})))})
    assert "公式の価格が確認できない原因" not in none                                                  # 原因が無ければ出さない


# ══ 最終ゲート（reviewer H1 / M1〜M3・auditor L1 / L2）══════════════════════════════════════

def _recheck(*rows):
    return {"generated_at": NOW.isoformat(), "results": [{"product_id": p, "status": st, "observed_at": at, "url": "https://o.example/" + p} for p, st, at in rows]}


def _flags(sig, pid):
    """gap_url（根拠のページ。分類専用）を除いた、原因の旗だけ。"""
    return {k: v for k, v in sig.get(pid, {}).items() if k != "gap_url"}


def _ident(states):
    return lambda p: (states.get(p.get("id"), "IDENTITY_CONFIRMED"), "")


def test_official_signals_come_from_fresh_recheck_records_and_the_registry_identity():
    fresh = (NOW - timedelta(hours=3)).isoformat()
    sig = eg.official_signals(_recheck(("a", "blocked", fresh), ("b", "failed", fresh), ("c", "unchanged", fresh), ("d", "changed", fresh)),
                              [{"id": "e"}, {"id": "f"}, {"id": "g"}, {"id": "h"}, {"id": "i"}], NOW,
                              _ident({"e": "PARTIAL_IDENTITY", "f": "AMBIGUOUS", "g": "NEEDS_USER_DECISION", "h": "DISCONTINUED", "i": "IDENTITY_CONFIRMED"}))
    assert _flags(sig, "a") == {"source_blocked": True} and _flags(sig, "b") == {"recheck_failed": True}
    assert _flags(sig, "c") == {"recheck_matched": True} and _flags(sig, "d") == {"price_changed": True}   # 一致は記録の更新待ち・価格の変化は人が確かめる旗
    assert sig["e"] == {"identity_mismatch": True}                                                  # 型番・JAN の登録はあるが公式の証拠が無い
    assert sig["f"] == sig["g"] == {"identity_undecided": True}                                    # どの版かが決まっていない（曖昧・判断待ち）
    assert sig["h"] == {"registry_sale_ended": True} and "i" not in sig                             # 登録簿の販売終了は分類専用の旗・確認済みは不足ではない


def test_official_signals_ignore_stale_future_unreadable_and_broken_records():
    old = (NOW - timedelta(hours=37)).isoformat()
    future = (NOW + timedelta(hours=3)).isoformat()
    edge = (NOW - timedelta(hours=36)).isoformat()
    sig = eg.official_signals(_recheck(("old", "blocked", old), ("fut", "blocked", future), ("bad", "blocked", "garbage"), ("none", "blocked", ""), ("edge", "blocked", edge)),
                              [], NOW, _ident({}))
    assert {p for p in sig if _flags(sig, p)} == {"edge"}                                            # 古い遮断・未来・読めない時刻は使わない（ちょうど 36 時間は使う）
    for doc in (None, [], "x", {"results": None}, {"results": ["x", None, 5, {"status": "blocked"}]}):
        out = eg.official_signals(doc, [None, "x", {"id": ""}], NOW, _ident({}))                    # 壊れた入力で例外にしない・旗を立てない
        assert all(_flags(out, p) == {} for p in out), doc
    boom = eg.official_signals({}, [{"id": "z"}], NOW, lambda p: (_ for _ in ()).throw(RuntimeError("x")))
    assert boom == {}                                                                              # 同一性を判断できない商品は旗を立てない（推測しない）


def test_gap_cause_order_after_the_wiring_fix():
    url = {"url": "https://o.example/p", "source_id": "s"}
    assert _gap(meta={"source_id": "s"}, evidence="STALE") == eg.SOURCE_NOT_IMPLEMENTED                 # URL が無ければ、確認が古いとは言えない（根拠のページが無い）
    assert _gap(meta={"source_id": "s", "identity_mismatch": True}) == eg.SOURCE_NOT_IMPLEMENTED       # 取得元の未登録が同一性より先
    assert _gap(meta={**url, "identity_mismatch": True}, source_blocked=True, evidence="STALE") == eg.IDENTITY_NOT_MATCHED
    assert _gap(meta={**url, "source_blocked": True}) == eg.SOURCE_BLOCKED                           # meta のフラグでも遮断
    assert _gap(meta={**url, "recheck_failed": True}, evidence="STALE") == eg.PAGE_CHANGED             # 再確認でページを取得したが価格を読めない
    assert _gap(meta={**url, "source_blocked": True, "recheck_failed": True}) == eg.SOURCE_BLOCKED
    assert _gap(meta={**url, "source_blocked": True}, evidence="VERIFIED_CURRENT") == eg.UNKNOWN_CAUSE   # 確認済みなら、遮断されていても不足ではない
    assert _gap(meta={**url, "recheck_failed": True}, evidence="VERIFIED_DATED") == eg.UNKNOWN_CAUSE
    assert eg.PAGE_CHANGED in eg.GAP_CAUSES and eg.PAGE_CHANGED in C.COVERAGE_KEYS["official_gap_counts"]


def test_queue_next_action_follows_each_gap_cause():
    def action(gap, missing=(C.OFFICIAL_UNVERIFIED,)):
        r = oq.build(candidates=[{"candidate_id": "c", "status": C.RESEARCH_CANDIDATE, "product_identity": {"product_id": "p", "name": "N"}, "known_cost_spread": 20000,
                                  "missing_requirements": list(missing), "official_gap": gap, "sell_observed_at": "2026-11-06T09:00:00+09:00"}],
                     product_candidates=[], tcg_events=[], now=NOW)["queue"][0]
        return r["next_action"]
    assert action("SALE_ENDED") == oq.VERIFY_RETAIL_PRICE and action("SOURCE_NOT_IMPLEMENTED") == oq.REGISTER_OFFICIAL_SOURCE
    assert action("IDENTITY_NOT_MATCHED") == oq.VERIFY_IDENTITY
    for gap in ("SOURCE_BLOCKED", "VERIFICATION_STALE", "CONFIGURED_PRICE_ONLY", "PRICE_NOT_FOUND", "PAGE_CHANGED", "UNKNOWN_CAUSE", None):
        assert action(gap) == oq.VERIFY_OFFICIAL_PRICE, gap                                         # 遮断は回避せず、人が公式ページで確認する
    assert oq.REGISTER_OFFICIAL_SOURCE in oq.NEXT_ACTIONS and "next_REGISTER_OFFICIAL_SOURCE" in oq.PUBLIC_NEXT_ACTION_KEYS
    assert "next_REGISTER_OFFICIAL_SOURCE" in C.COVERAGE_KEYS["operator_queue_next_actions"]
    res = oq.build(candidates=[{"candidate_id": "c", "status": C.RESEARCH_CANDIDATE, "product_identity": {"product_id": "p", "name": "N"}, "known_cost_spread": 20000,
                                "missing_requirements": [C.OFFICIAL_UNVERIFIED], "official_gap": "SOURCE_NOT_IMPLEMENTED", "sell_observed_at": "2026-11-06T09:00:00+09:00"}],
                   product_candidates=[], tcg_events=[], now=NOW)
    assert res["next_action_counts"]["next_REGISTER_OFFICIAL_SOURCE"] == 1 and res["next_action_counts"]["next_VERIFY_OFFICIAL_PRICE"] == 0


def test_build_candidates_uses_the_meta_flags_for_blocked_and_page_changed_sources():
    blocked = _build(ev="STALE", meta={"url": "https://o.example/p", "source_id": "official", "source_blocked": True})
    assert blocked["candidates"][0]["official_gap"] == eg.SOURCE_BLOCKED                           # 買取店の遮断（blocked_sources）とは別に、公式の再確認の遮断で発火する
    changed = _build(ev="STALE", meta={"url": "https://o.example/p", "source_id": "official", "recheck_failed": True})
    assert changed["candidates"][0]["official_gap"] == eg.PAGE_CHANGED
    notimpl = _build(ev="STALE", meta={"source_id": "official"})
    assert notimpl["candidates"][0]["official_gap"] == eg.SOURCE_NOT_IMPLEMENTED and notimpl["operator_queue"]["queue"][0]["next_action"] == oq.REGISTER_OFFICIAL_SOURCE


def test_the_generator_feeds_recheck_and_registry_signals_into_the_official_meta():
    src = (ROOT / "src" / "content" / "daily_lp_generator.py").read_text(encoding="utf-8")
    assert '"official_recheck", "latest.json"' in src and "official_meta=_official_meta," in src
    assert "_reg.identity_state" in src                                                            # 公式の登録簿の同一性の判断を入力にする
    assert "_eg.merge_signals(_official_meta, _eg.official_signals(" in src                         # 作った旗を official_meta に流し込む（URL は無いときだけ補う）


def test_price_type_is_unknown_when_the_cash_price_cannot_be_confirmed_and_conditions_are_read_safely():
    for listed, disc in ((1000, 2000), (1000, 1000)):                                              # 値引きが価格以上 = 現金の価格が確定できない
        r = rl.price_evidence({"price": listed, "immediate_discount": disc})
        assert r["effective_price"] is None and r["price_type"] == eg.UNKNOWN and not r["confirmable"], (listed, disc)
    assert eg.price_type_of({"listed_price": 10000, "immediate_discount": 10000, "effective_price": None})["confirmable"] is False
    assert eg.price_type_of({"listed_price": 10000, "price_conditions": "COUPON_REQUIRED"})["price_type"] == eg.COUPON     # 文字列 1 つは 1 つの条件（文字の集合にしない）
    assert eg.price_type_of({"listed_price": 10000, "price_conditions": "MEMBER_ONLY"})["price_type"] == eg.MEMBERSHIP
    for broken in (5, True, {"a": 1}, 3.5):
        r = eg.price_type_of({"listed_price": 10000, "price_conditions": broken})
        assert r["price_type"] == eg.CONDITIONAL and not r["confirmable"], broken                   # 壊れた条件は条件なしとは読まず、条件つき（確定に使わない）側に倒す
    assert eg.price_type_of({"listed_price": 10000, "price_conditions": None})["price_type"] == eg.REGULAR and eg.price_type_of({"listed_price": 10000, "price_conditions": []})["price_type"] == eg.REGULAR


# ══ 最終ゲート（2 回目: reviewer M1〜M3・auditor L1 / L2）══════════════════════════════════════

def _rc(status, reason="", at=None, pid="p", url="https://o.example/p"):
    return {"results": [{"product_id": pid, "status": status, "reason": reason, "url": url, "observed_at": at or (NOW - timedelta(hours=2)).isoformat()}]}


def test_recheck_statuses_map_to_the_right_flags():
    U = "https://o.example/p"
    def sig(status, reason=""):
        return eg.official_signals(_rc(status, reason), [], NOW, _ident({})).get("p", {})
    assert sig("blocked", "site_blocked") == {"gap_url": U, "source_blocked": True}
    assert sig("failed", "timeout") == {"gap_url": U, "source_blocked": True}                      # 取得失敗・到達不能（理由あり）は遮断・到達不能の側
    assert sig("failed", "") == {"gap_url": U, "recheck_failed": True}                               # ページは取れたが型番・価格を読めない
    assert sig("sale_ended") == {"gap_url": U, "recheck_sale_ended": True}
    assert sig("changed") == {"gap_url": U, "price_changed": True}
    assert sig("unchanged") == {"gap_url": U, "recheck_matched": True} and sig("bogus") == {"gap_url": U}


def test_recheck_url_is_classification_only_and_never_touches_the_buy_side_url():
    """再確認の記録の URL は分類専用の gap_url。`meta["url"]`（候補の買い側の URL・送料の判定に使われる）には触らない。"""
    sig = eg.official_signals(_rc("failed", ""), [], NOW, _ident({}))
    meta = eg.merge_signals({"p": {"url": "", "source_id": "s"}}, sig)
    assert meta["p"]["url"] == "" and meta["p"]["gap_url"] == "https://o.example/p" and meta["p"]["recheck_failed"]   # url は空のまま
    assert eg.official_gap_cause(evidence="STALE", meta=meta["p"]) == eg.PAGE_CHANGED                # 根拠のページがあるので「取得元が未登録」と誤判定しない
    keep = eg.merge_signals({"p": {"url": "https://registered.example/x"}}, sig)
    assert keep["p"]["url"] == "https://registered.example/x"
    assert eg.merge_signals({}, sig)["p"].get("url") is None and eg.merge_signals({}, sig)["p"]["gap_url"] == "https://o.example/p"
    assert eg.merge_signals({"p": {"url": ""}}, {"p": {"url": "https://x.example/"}})["p"]["url"] == ""      # url の旗が来ても上書きしない（予約）
    no_http = eg.official_signals(_rc("failed", "", url="javascript:x"), [], NOW, _ident({}))
    assert "gap_url" not in no_http.get("p", {})                                                     # https 以外は根拠にしない
    old_url = eg.official_signals(_rc("unchanged", at=(NOW - timedelta(hours=99)).isoformat()), [], NOW, _ident({}))
    assert old_url["p"] == {"gap_url": "https://o.example/p"}                                        # URL は古い記録でも補う（旗は立てない）


def test_the_gap_url_never_changes_the_candidate_buy_url_or_shipping():
    """分類専用の URL は、候補の買い側の URL（source_url.buy）・送料の判定に影響しない（実際に build_candidates を通して確かめる）。"""
    base = {"source_id": "official", "url": ""}
    plain = _build(ev="CONFIGURED_REFERENCE", meta=dict(base))
    with_gap = _build(ev="CONFIGURED_REFERENCE", meta={**base, "gap_url": "https://www.apple.com/jp/shop/buy-iphone/iphone-17"})
    a, b = plain["candidates"][0], with_gap["candidates"][0]
    assert a["source_url"]["buy"] == b["source_url"]["buy"]                                          # 買い側の URL は変わらない
    for k in ("known_costs", "known_cost_spread", "raw_net_spread", "shipping_unknown", "route_type", "observed_buy_price"):
        assert a[k] == b[k], k                                                                       # 送料・費用・経路・価格は変わらない
    assert a["official_gap"] == eg.SOURCE_NOT_IMPLEMENTED and b["official_gap"] != eg.SOURCE_NOT_IMPLEMENTED   # 分類だけが変わる


def test_sale_ended_and_price_changed_become_gap_causes():
    url = {"url": "https://o.example/p", "source_id": "s"}
    assert _gap(meta={**url, "official_not_sold": True}) == eg.SALE_ENDED                              # 再確認でページに販売終了の表示があった
    assert _gap(meta={**url, "price_changed": True}, evidence="STALE") == eg.PRICE_CHANGED
    assert _gap(meta={**url, "price_changed": True}, evidence="VERIFIED_CURRENT") == eg.UNKNOWN_CAUSE
    assert _gap(meta={**url, "recheck_failed": True, "price_changed": True}) == eg.PAGE_CHANGED
    assert eg.PRICE_CHANGED in eg.GAP_CAUSES and eg.PRICE_CHANGED in C.COVERAGE_KEYS["official_gap_counts"]


def test_official_signals_do_not_fail_on_timezone_mismatches():
    naive = datetime(2026, 11, 6, 12, 0)                                                              # タイムゾーンなしの現在時刻は JST とみなす
    sig = eg.official_signals(_rc("blocked", "site_blocked", at="2026-11-06T10:00:00+09:00"), [], naive, _ident({}))
    assert sig["p"]["source_blocked"] is True
    sig2 = eg.official_signals(_rc("blocked", "x", at="2026-11-06T10:00:00"), [], NOW, _ident({}))     # 記録の時刻がタイムゾーンなし
    assert sig2["p"]["source_blocked"] is True
    for at in ("0001-01-01T00:00:00+09:00", "9999-12-31T23:59:59+09:00"):
        assert "source_blocked" not in eg.official_signals(_rc("blocked", "x", at=at), [], NOW, _ident({})).get("p", {}), at


def test_the_generator_wraps_the_signal_building_so_a_failure_does_not_lose_the_research_report():
    src = (ROOT / "src" / "content" / "daily_lp_generator.py").read_text(encoding="utf-8")
    i = src.index("_eg.merge_signals(")
    block = src[src.rfind("try:", 0, i):i + 700]
    assert "except Exception as _exc" in block and "旗なしで続ける" in block                              # 原因の分類は付加の情報（失敗しても調査候補の生成を続ける）


# ══ 最終ゲート（3 回目: reviewer M-1〜M-3・auditor L-1 / L-3〜L-6）══════════════════════════════

def test_recheck_failure_reasons_are_classified_by_what_they_mean_and_stay_in_sync_with_polite():
    from src.collectors import polite
    def sig(why):
        return {k: v for k, v in eg.official_signals(_rc("failed", why), [], NOW, _ident({})).get("p", {}).items() if k != "gap_url"}
    for why in polite.CUTOFF_IMMEDIATE:                                                              # polite の遮断の語彙は、すべて遮断として読む（語彙が増えても取りこぼさない）
        assert sig(why) == {"source_blocked": True}, why
    for why in ("timeout", "connection_error", "ssl_error", "service_unavailable", "http_500", "http_502", "http_503", "http_504"):
        assert sig(why) == {"source_blocked": True}, why                                              # 到達できなかった（人が確認）
    for why in ("http_404", "http_410", "moved", "empty_html", "price_not_found", "no_data", "html_failed", "", "something_new"):
        assert sig(why) == {"recheck_failed": True}, why                                              # ページ側の理由・未知・理由なしは、遮断と断定しない
    assert set(polite.CUTOFF_COUNTED) - {"playwright_error"} <= (eg._BLOCKED_REASONS | eg._UNREACHABLE_REASONS | eg._PAGE_REASONS)   # 語彙の取りこぼし防止（このスクリプトは urllib で取得）


def test_recheck_sale_ended_is_used_for_the_cause_only_and_never_switches_the_buy_route():
    sig = eg.official_signals(_rc("sale_ended"), [], NOW, _ident({}))
    assert sig["p"] == {"gap_url": "https://o.example/p", "recheck_sale_ended": True} and "official_not_sold" not in sig["p"]
    assert _gap(meta={"url": "https://o.example/p", "source_id": "s", "recheck_sale_ended": True}) == eg.SALE_ENDED
    meta = {"url": "https://official.example/p", "source_id": "official", "recheck_sale_ended": True}
    rep = _build(ev="CONFIGURED_REFERENCE", meta=meta)
    c = rep["candidates"][0]
    assert c["official_gap"] == eg.SALE_ENDED and c["route_type"] == C.RETAIL_TO_BUYBACK                # 再確認のヒューリスティックだけで、買い側の経路を中古・二次に切り替えない
    assert C.OFFICIAL_NOT_SOLD not in c["missing_requirements"]
    registry = _build(ev="CONFIGURED_REFERENCE", meta={**meta, "official_not_sold": True, "recheck_sale_ended": False})
    assert registry["candidates"][0]["official_gap"] == eg.SALE_ENDED                                # 登録簿の販売終了は従来どおり


def test_undecided_identity_comes_before_registering_an_official_source():
    sig = eg.official_signals({}, [{"id": "a"}, {"id": "b"}, {"id": "c"}, {"id": "d"}], NOW,
                              _ident({"a": "NEEDS_USER_DECISION", "b": "AMBIGUOUS", "c": "PARTIAL_IDENTITY", "d": "IDENTITY_CONFIRMED"}))
    assert sig["a"] == {"identity_undecided": True} and sig["b"] == {"identity_undecided": True}
    assert sig["c"] == {"identity_mismatch": True} and "d" not in sig
    assert _gap(meta={"identity_undecided": True}) == eg.IDENTITY_NOT_MATCHED                           # URL が無くても、どの版かが決まっていないなら同一性が先
    assert _gap(meta={"identity_mismatch": True}) == eg.SOURCE_NOT_IMPLEMENTED                           # 型番・JAN の登録はある（公式の証拠が無いだけ）なら、まず公式ページを登録
    assert _gap(meta={"identity_undecided": True}, official_not_sold=True) == eg.SALE_ENDED


def test_recheck_urls_must_be_plain_https_urls_with_a_host_and_no_credentials():
    for bad in ("https://o.example../p", "https://o.example/p\u200b", "https://o.example/\u202e", "https://user:pw@evil.example/", "https://", "https://x y", "http://o.example/p", "http://oo.example/p", "ftp://oo.example/p", "https://o.example\\evil/p", "https://-bad.example/",
                "https://bad..example/", "https://nodot/", "https://o.example:abc/", "https://o.example:123456/", "https://ex ample.com/", "https://o.example\n/p", "https://o.example/p x", "https://o.example/p\tq", "https://o.example/p\x00", "https://o.example/p\x7f",
                "https://o.example/p\u200b", "https://o.example/p\u202e", "https://日本語.jp/", "https://127.0.0.1/x", "https://1.2.3.4/x", "https://0x7f.1/",
                "https://2130706433/", "https://o.example:0/x", "https://o.example:99999/x", "https://o.example:65536/x"):
        assert "gap_url" not in eg.official_signals(_rc("unchanged", url=bad), [], NOW, _ident({})).get("p", {}), repr(bad)
    for ok in ("https://o.example/p", "https://www.sony.jp/a?b=1", "https://store.example:8443/x", "HTTPS://o.example/p", "https://o.example./p",
               "https://o.example/日本語", "https://o.example/p?q=日本", "https://xn--wgv71a119e.jp/x"):                 # 大文字のスキーム・末尾ドット・パスの日本語・punycode は通す
        assert eg.official_signals(_rc("unchanged", url=ok), [], NOW, _ident({}))["p"]["gap_url"] == ok, ok


def test_price_type_reads_the_condition_fields_too_and_counts_ignore_unhashable_values():
    for k in ({"required_coupon": "X"}, {"member_only": True}, {"campaign_price": 900}, {"campaign_conditions": "期間限定"}, {"limited_quantity": True}):
        r = eg.price_type_of({"listed_price": 1000, "effective_price": 1000, **k})                   # price_conditions が無い入力でも、条件つき（緩くならない）
        assert r["price_type"] in (eg.COUPON, eg.MEMBERSHIP, eg.CONDITIONAL) and not r["confirmable"], k
    assert eg.price_type_of({"listed_price": 1000, "effective_price": 1000})["price_type"] == eg.REGULAR
    assert eg.gap_counts([{"official_gap": ["x"]}, {"official_gap": {"a": 1}}, {"official_gap": eg.SALE_ENDED}])[eg.SALE_ENDED] == 1
    assert eg.price_type_counts([{"retail_price_type": ["a"]}, {"retail_price_type": {"b": 1}}, {"retail_price_type": eg.REGULAR}])["REGULAR"] == 1
    assert eg.merge_signals({"p": None, "q": "x"}, {"p": {"price_changed": True}, "q": {"gap_url": "https://o.example/q"}}) == {
        "p": {"price_changed": True}, "q": {"gap_url": "https://o.example/q"}}                           # 壊れたメタでも落ちない


def test_registry_sale_ended_is_a_classification_flag_only():
    """公式の登録簿で販売終了（DISCONTINUED）の商品は、「取得元が未登録」でなく SALE_ENDED（公式ページの登録を促さない）。買い側の経路は変えない。"""
    sig = eg.official_signals({}, [{"id": "a"}, {"id": "b"}], NOW, _ident({"a": "DISCONTINUED", "b": "IDENTITY_CONFIRMED"}))
    assert sig == {"a": {"registry_sale_ended": True}}
    assert "official_not_sold" not in sig["a"]
    assert _gap(meta={"registry_sale_ended": True}) == eg.SALE_ENDED and _gap(meta={"registry_sale_ended": True, "url": ""}) == eg.SALE_ENDED
    rep = _build(ev="CONFIGURED_REFERENCE", meta={"source_id": "official", "url": "", "registry_sale_ended": True})
    c = rep["candidates"][0]
    assert c["official_gap"] == eg.SALE_ENDED and c["route_type"] == C.RETAIL_TO_BUYBACK and C.OFFICIAL_NOT_SOLD not in c["missing_requirements"]
    q = rep["operator_queue"]["queue"][0]
    assert q["next_action"] == oq.VERIFY_RETAIL_PRICE and oq.REGISTER_OFFICIAL_SOURCE not in q["next_actions"]          # 販売終了の商品に公式ページの登録を促さない


def test_a_fresh_matching_recheck_is_its_own_cause_not_stale_or_configured():
    sig = eg.official_signals(_rc("unchanged"), [], NOW, _ident({}))
    assert sig["p"] == {"gap_url": "https://o.example/p", "recheck_matched": True}
    meta = eg.merge_signals({"p": {"url": "https://o.example/p", "source_id": "s"}}, sig)["p"]
    for ev in ("STALE", "CONFIGURED_REFERENCE", "UNKNOWN"):
        assert eg.official_gap_cause(evidence=ev, meta=meta) == eg.RECHECK_MATCHED, ev                # 昨夜の再確認で一致 = 公式の確認のやり直しではなく、記録の更新待ち
    assert eg.official_gap_cause(evidence="VERIFIED_CURRENT", meta=meta) == eg.UNKNOWN_CAUSE
    assert eg.official_gap_cause(evidence="STALE", meta={**meta, "recheck_failed": True}) == eg.PAGE_CHANGED   # 失敗・価格の変化・遮断は一致より先
    assert eg.official_gap_cause(evidence="STALE", meta={**meta, "price_changed": True}) == eg.PRICE_CHANGED
    assert eg.official_gap_cause(evidence="STALE", meta={**meta, "source_blocked": True}) == eg.SOURCE_BLOCKED
    assert eg.official_gap_cause(evidence="STALE", meta={**meta, "identity_mismatch": True}) == eg.IDENTITY_NOT_MATCHED   # 同一性を弱めない
    old = eg.official_signals(_rc("unchanged", at=(NOW - timedelta(hours=99)).isoformat()), [], NOW, _ident({}))
    assert "recheck_matched" not in old["p"]                                                         # 古い一致は使わない（古い確認を今日のものにしない）
    assert eg.RECHECK_MATCHED in eg.GAP_CAUSES and eg.RECHECK_MATCHED in C.COVERAGE_KEYS["official_gap_counts"]
    rep = _build(ev="CONFIGURED_REFERENCE", meta=meta)
    assert rep["candidates"][0]["official_gap"] == eg.RECHECK_MATCHED and rep["operator_queue"]["queue"][0]["next_action"] == oq.VERIFY_OFFICIAL_PRICE


def test_the_registry_verified_urls_count_as_a_source_page_but_only_for_the_classification():
    reg = {"a": {"url": "https://www.apple.com/jp/shop/x"}, "b": {"url": "http://insecure.example/x"}, "c": "x", 5: {"url": "https://o.example/y"}}
    sig = eg.official_signals({}, [], NOW, _ident({}), verified_urls=reg)
    assert sig == {"a": {"gap_url": "https://www.apple.com/jp/shop/x"}}
    fresh = eg.official_signals(_rc("unchanged", pid="a", url="https://recheck.example/a"), [], NOW, _ident({}), verified_urls=reg)
    assert fresh["a"]["gap_url"] == "https://recheck.example/a"                                      # 再確認の記録の URL を優先
    meta = eg.merge_signals({"a": {"url": "", "source_id": "s"}}, sig)
    assert eg.official_gap_cause(evidence="CONFIGURED_REFERENCE", meta=meta["a"]) == eg.CONFIGURED_PRICE_ONLY   # 根拠のページがあるので「取得元が未登録」にしない
    assert meta["a"]["url"] == ""                                                                    # 買い側の url は変えない
    assert eg.official_signals({}, [], NOW, _ident({}), verified_urls="x") == {}


def test_merge_signals_writes_only_the_allowed_classification_keys():
    out = eg.merge_signals({"p": {"url": "https://reg.example/x"}},
                           {"p": {"gap_url": "https://g.example/x", "official_not_sold": True, "url": "https://evil.example/", "verified": True, "recheck_matched": True}})
    assert out["p"] == {"url": "https://reg.example/x", "gap_url": "https://g.example/x", "recheck_matched": True}   # 買い側の経路・URL を決めるキーは書かない
    assert eg.SIGNAL_KEYS == {"gap_url", "source_blocked", "recheck_failed", "recheck_sale_ended", "registry_sale_ended", "price_changed", "recheck_matched",
                              "identity_undecided", "identity_mismatch"}
    assert "official_not_sold" not in eg.SIGNAL_KEYS and "url" not in eg.SIGNAL_KEYS


def test_official_signals_tolerate_non_list_results_and_non_string_product_ids():
    sig = eg.official_signals({"results": 5}, [{"id": "a"}], NOW, _ident({"a": "PARTIAL_IDENTITY"}))
    assert sig == {"a": {"identity_mismatch": True}}                                                 # results が壊れていても、登録簿の旗は残す
    assert eg.official_signals({"results": {"x": 1}}, [], NOW, _ident({})) == {}
    bad_ids = eg.official_signals({"results": [{"product_id": ["x"], "status": "blocked", "reason": "site_blocked", "observed_at": NOW.isoformat(), "url": "https://o.example/p"}]},
                                  [], NOW, _ident({}))
    assert bad_ids == {}                                                                              # 商品 ID が文字列でない記録は使わない


def test_the_generator_passes_the_registry_verified_urls():
    src = (ROOT / "src" / "content" / "daily_lp_generator.py").read_text(encoding="utf-8")
    assert "verified_urls=_reg.VERIFIED_URLS" in src


def test_sale_ended_does_not_let_a_phantom_official_price_spread_raise_the_priority():
    """公式が販売終了と分類された商品の価格差は、存在しない公式価格から出た値。優先度・点・価格差の表示に使わない（6 回目の auditor M-1）。"""
    def row(gap):
        return oq.build(candidates=[{"candidate_id": "c", "status": C.RESEARCH_CANDIDATE, "product_identity": {"product_id": "p", "name": "N"},
                                     "known_cost_spread": 48200, "missing_requirements": [C.OFFICIAL_UNVERIFIED], "official_gap": gap,
                                     "sell_observed_at": "2026-11-06T09:00:00+09:00"}], product_candidates=[], tcg_events=[], now=NOW)["queue"][0]
    ended, other = row("SALE_ENDED"), row("SOURCE_BLOCKED")
    assert other["priority"] == oq.HIGH and other["spread"]["used"] == 48200
    assert ended["priority"] != oq.HIGH and ended["priority"] != oq.URGENT and ended["spread"]["used"] is None
    assert not any(p.startswith("spread+") for p in ended["score_parts"]) and ended["score"] < other["score"]
    assert ended["next_action"] == oq.VERIFY_RETAIL_PRICE


def test_https_url_check_rejects_non_ascii_digit_ports():
    assert eg._https_url_ok("https://a.example:443/") and not eg._https_url_ok("https://a.example:٤٤٣/")


def test_sale_ended_keeps_the_real_spread_of_the_secondary_retail_route():
    """小売店・二次の価格を買値にした経路（SECONDARY_TO_BUYBACK）の価格差は実在する。販売終了でも消さない（7 回目の reviewer M1）。"""
    def row(route):
        return oq.build(candidates=[{"candidate_id": "c", "status": C.RESEARCH_CANDIDATE, "product_identity": {"product_id": "p", "name": "N"},
                                     "known_cost_spread": 18200, "missing_requirements": [C.OFFICIAL_UNVERIFIED], "official_gap": "SALE_ENDED", "route_type": route,
                                     "sell_observed_at": "2026-11-06T09:00:00+09:00"}], product_candidates=[], tcg_events=[], now=NOW)["queue"][0]
    assert row(C.SECONDARY_TO_BUYBACK)["spread"]["used"] == 18200 and row(C.SECONDARY_TO_BUYBACK)["priority"] == oq.HIGH
    assert row(C.RETAIL_TO_BUYBACK)["spread"]["used"] is None


def test_https_url_check_does_not_raise_on_huge_ports():
    assert eg._https_url_ok("https://a.example:" + "9" * 5000 + "/x") is False and eg._https_url_ok("https://a.example:99999/") is False
    assert eg.official_signals({"results": [{"product_id": "p", "url": "https://a.example:" + "9" * 5000, "status": "blocked",
                                             "observed_at": "2026-11-06T20:41:00+09:00"}]}, [], NOW, lambda *_: "") is not None

"""Wave 7e-1（観測性）: 公式の状態・期限の正本・確認日時・最終状態・実行の記録・台帳の公開集計。

確定・actionable・通知の基準は変えない（判定を読むだけ）。通信しない（合成の値だけ）。
"""
from __future__ import annotations

import importlib.util
import json
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
import yaml

from src.market import normalized_prices as npr
from src.market import official_registry as reg
from src.ops import health_alert as ha
from src.research import candidates as rc
from src.research import official_state as ost

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
TODAY = date(2026, 11, 9)


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


RO = _load("scripts/run_observability.py", "run_observability_t")
AUDIT = _load("scripts/audit_official_sources.py", "audit_official_sources_t")


@pytest.fixture()
def fake_registry(monkeypatch):
    """合成の登録簿（実データに依存しない）。"""
    v = {"prod_x": {"source": "s", "url": "https://o.example/x", "price": 1000, "checked_on": "2026-11-01", "price_kind": "official_direct"},
         "prod_m": {"source": "s", "url": "https://o.example/m", "price": 2000, "checked_on": "2026-08-01", "price_kind": "msrp"}}
    monkeypatch.setattr(reg, "VERIFIED_URLS", v)
    _fake_identity(monkeypatch)
    return v


def _fake_identity(monkeypatch):
    """合成の正本の商品と公式の証拠（型番 MODEL-X・MODEL-M）。"""
    prods = {"prod_x": {"id": "prod_x", "name": "X", "model_number": "MODEL-X"},
             "prod_m": {"id": "prod_m", "name": "M", "model_number": "MODEL-M"}}
    monkeypatch.setattr(reg, "canonical_products", lambda: prods)
    monkeypatch.setattr(reg, "IDENTITY_EVIDENCE", {**reg.IDENTITY_EVIDENCE, "prod_x": {"model_number": "MODEL-X"},
                                                   "prod_m": {"model_number": "MODEL-M"}})
    return prods


def _res(pid="prod_x", url="https://o.example/x", price=1000, status="unchanged", day="2026-11-08", **k):
    mdl = {"prod_x": "MODEL-X", "prod_m": "MODEL-M"}.get(pid, "")
    return {"product_id": pid, "url": url, "model": mdl, "match": mdl, "recorded_price": price, "price": price if status in ("unchanged", "changed") else None,
            "status": status, "observed_at": f"{day}T10:00:00+09:00", **k}


# ---------------- 公式の状態 ----------------
def test_every_canonical_product_is_classified_exactly_once_and_zero_states_are_present():
    products = [p for p in yaml.safe_load((ROOT / "config" / "products.yaml").read_text(encoding="utf-8"))["products"]]
    prods = [{"id": p["id"]} for p in products]
    states = ost.classify_products(prods, {}, {})
    counts = ost.state_counts(states, len(prods))                # 合計が商品数と違えば例外
    assert len(states) == len(prods) == sum(counts.values())
    assert tuple(counts) == ost.STATES and len(ost.STATES) == 12
    assert counts[ost.VERIFIED_CURRENT] == 0 and counts[ost.PAGE_CHANGED] == 0   # 0 件の状態も出る
    dup = ost.classify_products([{"id": "a"}, {"id": "a"}, {"id": "b"}, {}, None], {}, {})
    assert sorted(dup) == ["a", "b"]                               # 同じ ID は 1 件・壊れた要素は無視


def test_state_total_mismatch_raises_and_unknown_state_is_counted_as_unknown():
    with pytest.raises(ValueError):
        ost.state_counts({"a": "UNKNOWN"}, 2)
    assert ost.state_counts({"a": "bogus"}, 1)[ost.UNKNOWN] == 1


def test_verified_states_sum_equals_the_existing_verified_count():
    """確認済みの状態の合計 == price_evidence.PROFIT_ELIGIBLE の商品数（期限の考え方を変えない）。"""
    from src.market import price_evidence as pe
    prods = [{"id": f"p{i}"} for i in range(6)]
    ev = {"p0": pe.VERIFIED_CURRENT, "p1": pe.VERIFIED_DATED, "p2": pe.STALE, "p3": pe.CONFIGURED_REFERENCE, "p4": pe.UNKNOWN}
    st = ost.classify_products(prods, ev, {"p2": {"url": "https://o.example/p"}})
    assert ost.verified_total(ost.state_counts(st, 6)) == sum(1 for e in ev.values() if pe.is_profit_eligible(e)) == 2


@pytest.mark.parametrize("evidence,meta,expected", [
    ("VERIFIED_CURRENT", {}, "VERIFIED_CURRENT"),
    ("VERIFIED_DATED", {}, "VERIFIED_DATED"),
    ("STALE", {"official_not_sold": True, "url": "https://o.example/p"}, "SALE_ENDED"),
    ("STALE", {"registry_sale_ended": True}, "SALE_ENDED"),
    ("STALE", {"identity_undecided": True}, "IDENTITY_NOT_MATCHED"),
    ("STALE", {}, "SOURCE_NOT_REGISTERED"),
    ("STALE", {"url": "https://o.example/p", "source_blocked": True}, "SOURCE_BLOCKED"),
    ("STALE", {"url": "https://o.example/p", "recheck_failed": True}, "PAGE_CHANGED"),
    ("STALE", {"url": "https://o.example/p", "price_changed": True}, "PRICE_CHANGED"),
    ("STALE", {"url": "https://o.example/p", "recheck_matched": True}, "RECHECK_MATCHED"),
    ("STALE", {"url": "https://o.example/p"}, "STALE"),
    ("CONFIGURED_REFERENCE", {"url": "https://o.example/p"}, "CONFIGURED_REFERENCE"),
    ("UNKNOWN", {"url": "https://o.example/p"}, "UNKNOWN"),
])
def test_state_follows_the_existing_cause_vocabulary(evidence, meta, expected):
    assert ost.official_state_of(evidence=evidence, meta=meta) == expected


def test_broken_inputs_never_raise():
    for ev, meta in ((None, None), ("x", "y"), (5, [1]), ({}, {"url": 3})):
        assert ost.official_state_of(evidence=ev, meta=meta) in ost.STATES


def test_individual_official_states_are_private_and_public_summary_only_has_counts():
    assert {"official_states", "official_state", "first_ledger_state"} <= rc.PRIVATE_KEYS
    rep = {"schema": 1, "type": "RESEARCH_CANDIDATES", "generated_at": "2026-11-09T12:00:00+09:00", "candidates": [], "counts": {},
           "official_states": {"secret_product": "SALE_ENDED"}, "ledger_restore_status": "RESTORED_FROM_PREVIOUS_RUN",
           "metrics": {"official_state_counts": {"SALE_ENDED": 1, "secret_product": 4}}}
    pub = rc.public_summary(rep)
    s = json.dumps(pub, ensure_ascii=False)
    assert "secret_product" not in s and "official_states" not in pub
    assert tuple(pub["official_state_counts"]) == ost.STATES and pub["official_state_counts"]["SALE_ENDED"] == 1


# ---------------- 期限の正本 ----------------
def test_official_direct_is_14_days_and_msrp_is_180_days(fake_registry):
    rows = {r["product_id"]: r for r in reg.verification_status([], today=TODAY)}
    assert rows["prod_x"]["stale_days"] == npr.official_stale_days("prod_x") == 14
    assert rows["prod_m"]["stale_days"] == npr.official_stale_days("prod_m") == 180
    assert rows["prod_x"]["days_left"] == 14 - 8 and not rows["prod_x"]["expired"]            # 11-01 から 8 日
    assert rows["prod_m"]["days_left"] == 180 - 100 and not rows["prod_m"]["expired"]          # 08-01 から 100 日


def test_switch2_msrp_does_not_raise_a_false_expiry_alert_any_more():
    """確認日 2026-10-08・希望小売価格（180 日）の Switch 2 は、期限切れ（HIGH）にしない。"""
    row = {r["product_id"]: r for r in reg.verification_status([], today=TODAY)}["prod_switch2"]
    assert row["stale_days"] == 180 and not row["expired"] and row["days_left"] > 100
    assert ha._official_alerts({"official_status": [row]}) == []
    # 公式直販は 14 日のまま、切れれば文言は実際の日数を示す
    expired = dict(row, stale_days=14, days_left=-3, expired=True, last_verified="2026-10-20")
    al = ha._official_alerts({"official_status": [expired]})
    assert al and al[0]["severity"] == ha.HIGH and "期限 14 日" in al[0]["details"]
    long_ = ha._official_alerts({"official_status": [dict(row, stale_days=180, days_left=2, expired=False)]})
    assert long_ and "期限 180 日" in long_[0]["details"] and "再確認が unchanged になれば延びる" not in long_[0]["details"]


def test_alert_expiry_and_price_evidence_use_the_same_day_count():
    for r in reg.verification_status([], today=TODAY):
        assert r["stale_days"] == npr.official_stale_days(r["product_id"])


# ---------------- 確認日時 ----------------
def test_original_verified_at_keeps_the_human_check_day(fake_registry):
    row = {r["product_id"]: r for r in reg.verification_status([], today=TODAY)}["prod_x"]
    assert row["original_verified_at"] == "2026-11-01" == fake_registry["prod_x"]["checked_on"]
    assert row["last_verified_at"] == row["last_verified"] == "2026-11-01"        # 再確認が無ければ人の確認日のまま


def test_recheck_matched_refreshes_last_verified_at_to_the_real_fetch_day(fake_registry):
    ls = reg.advance_last_state({}, [_res(day="2026-11-08")], TODAY)
    e = ls["prod_x"]
    assert e["last_verified_at"] == "2026-11-08" and e["last_recheck_result"] == "unchanged" and e["failure_streak_days"] == 0
    row = {r["product_id"]: r for r in reg.verification_status([], today=TODAY, last_state=ls)}["prod_x"]
    assert row["last_verified_at"] == "2026-11-08" and row["original_verified_at"] == "2026-11-01"   # 人の確認日は保持される
    assert row["last_recheck_result"] == "unchanged" and row["last_recheck_at"].startswith("2026-11-08")


@pytest.mark.parametrize("status", ["failed", "blocked"])
def test_failed_and_blocked_do_not_refresh_nor_roll_back_last_verified_at(fake_registry, status):
    base = reg.advance_last_state({}, [_res(day="2026-11-05")], TODAY)
    after = reg.advance_last_state(base, [_res(status=status, day="2026-11-09")], TODAY)
    assert after["prod_x"]["last_verified_at"] == "2026-11-05"                 # 取得できなかった日は進まない・戻らない
    assert after["prod_x"]["last_recheck_result"] == status


@pytest.mark.parametrize("status", ["sale_ended", "changed"])
def test_sale_ended_and_changed_do_not_refresh_and_invalidate_the_earlier_verification(fake_registry, status):
    """確認済みを外す側の観測（販売終了・価格の変化）は確認日を進めず、それまでの確認日も引き継がない（Wave 7e-1 レビュー M-1）。"""
    base = reg.advance_last_state({}, [_res(day="2026-11-05")], TODAY)
    after = reg.advance_last_state(base, [_res(status=status, day="2026-11-09")], TODAY)
    assert after["prod_x"]["last_verified_at"] == "" and after["prod_x"]["last_recheck_result"] == status
    # 翌日以降に取得の失敗・遮断が続いても、古い確認日（11-05）を復活させない
    nxt = reg.advance_last_state(after, [_res(status="blocked", day="2026-11-10")], date(2026, 11, 10))
    assert nxt["prod_x"]["last_verified_at"] == ""
    # 実際に一致した再確認が来たときだけ確認日が戻る
    back = reg.advance_last_state(nxt, [_res(day="2026-11-10")], date(2026, 11, 10))
    assert back["prod_x"]["last_verified_at"] == "2026-11-10"


def test_future_last_verified_at_in_the_previous_state_is_dropped_not_stuck(fake_registry):
    prev = {"prod_x": {"url": "https://o.example/x", "price": 1000, "last_verified_at": "2099-01-01", "last_verified_by": "x",
                       "last_recheck_at": "", "last_recheck_result": "", "failure_streak_days": 0, "last_failure_day": ""}}
    out = reg.advance_last_state(prev, [_res(day="2026-11-08")], TODAY)
    assert out["prod_x"]["last_verified_at"] == "2026-11-08"                     # 未来の日付で固着せず、実際の再確認で更新される


def test_derive_last_state_builds_the_state_from_the_history_alone(fake_registry):
    hist = [_res(day="2026-11-04"), _res(status="failed", day="2026-11-05"), _res(status="failed", day="2026-11-09")]
    st = reg.derive_last_state(hist, TODAY)
    assert st["prod_x"]["last_verified_at"] == "2026-11-04" and st["prod_x"]["failure_streak_days"] == 2
    assert reg.derive_last_state([], TODAY) == {} and reg.derive_last_state(None, TODAY) == {}


def test_state_built_from_history_matches_the_history_based_status(fake_registry):
    """最終状態が無い初回は履歴全体から作る。履歴のあるうちに作れば、窓が切れても同じ確認日・連続失敗が残る（レビュー M-2）。"""
    hist = [_res(day="2026-11-04"), _res(status="failed", day="2026-11-05"), _res(status="failed", day="2026-11-06"),
            _res(status="blocked", day="2026-11-07")]
    want = {r["product_id"]: r for r in reg.verification_status(hist, today=TODAY)}["prod_x"]
    init = reg.advance_last_state({}, hist, TODAY)
    got = {r["product_id"]: r for r in reg.verification_status([], today=TODAY, last_state=init)}["prod_x"]            # 履歴の窓が切れた後
    for k in ("last_verified", "days_left", "consecutive_failures", "expired"):
        assert got[k] == want[k], k
    assert got["last_verified"] == "2026-11-04" and got["consecutive_failures"] == 3


def test_msrp_lineup_confirmation_does_not_extend_the_verification_day(fake_registry):
    base = reg.advance_last_state({}, [_res(day="2026-11-05")], TODAY)
    after = reg.advance_last_state(base, [_res(day="2026-11-09", verified_by="msrp_lineup")], TODAY)
    assert after["prod_x"]["last_verified_at"] == "2026-11-05"


def test_result_for_a_different_recorded_price_or_url_does_not_refresh(fake_registry):
    base = reg.advance_last_state({}, [_res(day="2026-11-05")], TODAY)
    for bad in (_res(day="2026-11-09", price=999), _res(day="2026-11-09", url="https://o.example/other")):
        after = reg.advance_last_state(base, [bad], TODAY)
        assert after["prod_x"]["last_verified_at"] == "2026-11-05"


def test_future_timestamps_are_ignored_everywhere(fake_registry):
    ls = reg.advance_last_state({}, [_res(day="2026-12-31")], TODAY)
    assert "prod_x" not in ls or ls["prod_x"]["last_verified_at"] == ""
    fake_registry["prod_x"]["checked_on"] = "2026-12-31"                         # 登録簿の確認日が未来: 無効 = 確認日なし = 期限切れ（安全側）
    row = {r["product_id"]: r for r in reg.verification_status([], today=TODAY)}["prod_x"]
    assert row["last_verified"] == "" and row["expired"] and row["original_verified_at"] == ""
    hist = [_res(day="2026-12-31")]
    row2 = {r["product_id"]: r for r in reg.verification_status(hist, today=TODAY)}["prod_x"]
    assert row2["last_verified"] == ""                                            # 未来の再確認の日付で確認日が進まない


def test_last_state_survives_the_history_window_rolling_over(fake_registry):
    ls = reg.advance_last_state({}, [_res(day="2026-11-08")], TODAY)
    # 履歴の窓が切れて（履歴が空）、さらに今日は失敗した: それでも確認日は 11-08 のまま（登録簿の 11-01 へ戻らない）
    ls2 = reg.advance_last_state(ls, [_res(status="failed", day="2026-11-09")], TODAY)
    row = {r["product_id"]: r for r in reg.verification_status([], today=TODAY, last_state=ls2)}["prod_x"]
    assert row["last_verified"] == "2026-11-08" and row["consecutive_failures"] == 1
    # 履歴が無くても連続失敗の日数は続く（同じ日の失敗は 1 日と数える）
    ls3 = reg.advance_last_state(ls2, [_res(status="blocked", day="2026-11-09")], TODAY)
    assert ls3["prod_x"]["failure_streak_days"] == 1
    ls4 = reg.advance_last_state(ls3, [_res(status="failed", day="2026-11-10")], date(2026, 11, 10))
    assert ls4["prod_x"]["failure_streak_days"] == 2
    ls5 = reg.advance_last_state(ls4, [_res(day="2026-11-10")], date(2026, 11, 10))
    assert ls5["prod_x"]["failure_streak_days"] == 0                              # 成功が挟まれば戻る


def test_last_state_is_not_carried_over_when_the_registry_record_changed(fake_registry):
    ls = reg.advance_last_state({}, [_res(day="2026-11-08")], TODAY)
    fake_registry["prod_x"]["price"] = 1100                                      # 登録簿の価格を直した（人の確認）
    assert "prod_x" not in reg.advance_last_state(ls, [], TODAY)
    row = {r["product_id"]: r for r in reg.verification_status([], today=TODAY, last_state=ls)}["prod_x"]
    assert row["last_verified"] == "2026-11-01"                                  # 古い最終状態を新しい記録の確認にしない


def test_advance_last_state_is_idempotent_for_the_same_day(fake_registry):
    a = reg.advance_last_state({}, [_res(day="2026-11-08")], TODAY)
    b = reg.advance_last_state(a, [_res(day="2026-11-08")], TODAY)
    assert a == b


def test_advance_last_state_never_raises_on_broken_input(fake_registry):
    out = reg.advance_last_state("x", [None, 5, {}, {"product_id": None}, {"product_id": "prod_x", "observed_at": "bad"}], TODAY)
    assert out == {}


def _recheck_db(tmp_path, results, hist, *, registry_day="2026-11-01", monkeypatch=None):
    """apply_recheck を、合成の latest.json・history.json（公開済みの再確認の履歴）で動かし、確認日を進める UPDATE を返す。"""
    latest = tmp_path / "latest.json"
    latest.write_text(json.dumps({"results": results}), encoding="utf-8")
    if hist is not None:
        (tmp_path / "history.json").write_text(json.dumps({"results": hist}), encoding="utf-8")
    calls = []

    class _C:
        def execute(self, sql, params=()):
            calls.append((sql, params))

            class _R:
                rowcount = 1

                def fetchone(self):
                    return None
            return _R()

        def commit(self):
            pass
    AUDIT.VERIFIED_URLS["prod_x"] = {"source": "s", "url": "https://o.example/x", "price": 1000, "checked_on": registry_day, "price_kind": "official_direct"}
    try:
        AUDIT.apply_recheck(_C(), {"prod_x": {"id": "prod_x", "model_number": "MODEL-X"}}, latest)
    finally:
        AUDIT.VERIFIED_URLS.pop("prod_x", None)
    return [c for c in calls if c[0].lstrip().upper().startswith("UPDATE products SET OFFICIAL_PRICE_UPDATED_AT")
            or "official_price_updated_at=?" in c[0] and c[0].lstrip().upper().startswith("UPDATE")]


@pytest.fixture()
def fake_identity(monkeypatch):
    _fake_identity(monkeypatch)


def test_apply_recheck_carries_the_last_real_verification_when_today_failed(tmp_path, monkeypatch, fake_identity):
    monkeypatch.setattr(AUDIT, "NOW", datetime(2026, 11, 9, 12, 0, tzinfo=JST))
    hist = [_res(day="2026-11-05"), _res(status="failed", day="2026-11-09")]
    ups = _recheck_db(tmp_path, [_res(status="failed", day="2026-11-09")], hist)
    assert any(p[0] == "2026-11-05" for _s, p in ups)                              # 今日の失敗でも、前回の実際の確認日へ戻らず引き継ぐ


def test_apply_recheck_does_not_use_history_after_changed_or_sale_ended(tmp_path, monkeypatch, fake_identity):
    monkeypatch.setattr(AUDIT, "NOW", datetime(2026, 11, 9, 12, 0, tzinfo=JST))
    for st in ("changed", "sale_ended"):
        hist = [_res(day="2026-11-05"), _res(status=st, day="2026-11-09")]
        ups = _recheck_db(tmp_path, [_res(status=st, day="2026-11-09")], hist)
        assert not any(p and p[0] == "2026-11-05" for _s, p in ups), st


def test_apply_recheck_does_not_revive_an_old_verification_after_sale_ended_then_blocked(tmp_path, monkeypatch, fake_identity):
    """Wave 7e-1 レビュー M-1 の再現: 11-10 一致 → 11-11 販売終了 → 11-12 遮断。11-12 の DB が 11-10 の確認日に戻らない。"""
    monkeypatch.setattr(AUDIT, "NOW", datetime(2026, 11, 12, 12, 0, tzinfo=JST))
    hist = [_res(status=st, day=day) for day, st in (("2026-11-10", "unchanged"), ("2026-11-11", "sale_ended"), ("2026-11-12", "blocked"))]
    ups = _recheck_db(tmp_path, [_res(status="blocked", day="2026-11-12")], hist, registry_day="2026-10-21")
    assert not any(p and p[0] in ("2026-11-10", "2026-11-11") for _s, p in ups)


def test_apply_recheck_carry_also_updates_the_source_config_verified_day(tmp_path, monkeypatch, fake_identity):
    monkeypatch.setattr(AUDIT, "NOW", datetime(2026, 11, 9, 12, 0, tzinfo=JST))
    calls = []

    class _C:
        def execute(self, sql, params=()):
            calls.append((sql, params))

            class _R:
                rowcount = 1
            return _R()

        def commit(self):
            pass
    (tmp_path / "latest.json").write_text(json.dumps({"results": [_res(status="failed", day="2026-11-09")]}), encoding="utf-8")
    (tmp_path / "history.json").write_text(json.dumps({"results": [_res(day="2026-11-05")]}), encoding="utf-8")
    AUDIT.VERIFIED_URLS["prod_x"] = {"source": "s", "url": "https://o.example/x", "price": 1000, "checked_on": "2026-11-01", "price_kind": "official_direct"}
    try:
        AUDIT.apply_recheck(_C(), {"prod_x": {"id": "prod_x", "model_number": "MODEL-X"}}, tmp_path / "latest.json")
    finally:
        AUDIT.VERIFIED_URLS.pop("prod_x", None)
    assert any("product_source_config" in sql and "last_verified_at" in sql and p[0] == "2026-11-05" for sql, p in calls)


def test_official_state_counts_ignore_non_numeric_values_without_raising():
    rep = {"schema": 1, "type": "RESEARCH_CANDIDATES", "generated_at": "2026-11-09T12:00:00+09:00", "candidates": [], "counts": {},
           "metrics": {"official_state_counts": {"SALE_ENDED": "x", "STALE": None, "UNKNOWN": 3, "VERIFIED_CURRENT": True}}}
    pub = rc.public_summary(rep)["official_state_counts"]
    assert tuple(pub) == ost.STATES and pub["UNKNOWN"] == 3 and pub["SALE_ENDED"] == 0 and pub["VERIFIED_CURRENT"] == 0


def test_apply_recheck_ignores_future_or_stale_or_mismatched_history(tmp_path, monkeypatch, fake_identity):
    monkeypatch.setattr(AUDIT, "NOW", datetime(2026, 11, 9, 12, 0, tzinfo=JST))
    for hist in ([_res(day="2026-12-31")],                                              # 未来
                 [_res(day="2026-10-01")],                                              # 登録簿の確認日より古い（戻さない）
                 [_res(price=999, day="2026-11-05")],                                   # 記録と違う
                 [_res(day="2026-11-05", model="WRONG", match="WRONG")]):               # 型番が違う
        ups = _recheck_db(tmp_path, [_res(status="failed", day="2026-11-09")], hist)
        assert not any(p and p[0] in ("2026-12-31", "2026-10-01", "2026-11-05") for _s, p in ups), hist


# ---------------- 確認日の引き継ぎの同一性（Wave 7e-1 受入前の修正） ----------------
def test_identity_inheritance_exact_model_is_inherited(fake_registry):
    st = reg.derive_last_state([_res(day="2026-11-08")], TODAY)
    assert st["prod_x"]["last_verified_at"] == "2026-11-08"


def test_identity_inheritance_wrong_model_is_not_inherited(fake_registry):
    # 同じ商品 ID・同じ URL・同じ価格でも、結果の型番が正本と違えば確認日にしない
    for model in ("WRONG", "MODEL-M", "model-x", ""):
        st = reg.derive_last_state([_res(day="2026-11-08", model=model, match="WRONG")], TODAY)
        assert st["prod_x"]["last_verified_at"] == "", model
    row = {r["product_id"]: r for r in reg.verification_status([_res(day="2026-11-08", model="WRONG")], today=TODAY)}["prod_x"]
    assert row["last_verified"] == "2026-11-01"                                    # 人の確認日のまま（進まない）


def test_identity_inheritance_same_url_but_other_products_model_is_not_inherited(fake_registry):
    st = reg.derive_last_state([_res(day="2026-11-08", model="MODEL-M", match="MODEL-M")], TODAY)
    assert st["prod_x"]["last_verified_at"] == ""


def test_identity_inheritance_when_the_canonical_model_changed_later(fake_registry, monkeypatch):
    """過去の結果は旧い型番（MODEL-X）で確認した。正本の型番が変わった後は、旧い型番の確認を引き継がない。"""
    hist = [_res(day="2026-11-08")]
    assert reg.derive_last_state(hist, TODAY)["prod_x"]["last_verified_at"] == "2026-11-08"
    prods = {"prod_x": {"id": "prod_x", "name": "X", "model_number": "MODEL-Y"}}
    monkeypatch.setattr(reg, "canonical_products", lambda: prods)
    monkeypatch.setattr(reg, "IDENTITY_EVIDENCE", {**reg.IDENTITY_EVIDENCE, "prod_x": {"model_number": "MODEL-Y"}})
    assert reg.derive_last_state(hist, TODAY)["prod_x"]["last_verified_at"] == ""


def test_identity_inheritance_name_only_is_not_inherited(fake_registry, monkeypatch):
    # 照合の値が無い・型番が無い（商品名だけ）結果
    r = _res(day="2026-11-08")
    for bad in ({**r, "match": ""}, {k: v for k, v in r.items() if k not in ("model", "match")}, {**r, "name": "X", "model": None}):
        assert reg.derive_last_state([bad], TODAY)["prod_x"]["last_verified_at"] == ""
    # 公式の証拠が無い商品（商品名だけで識別している）は、結果が型番を持っていても引き継がない
    monkeypatch.setattr(reg, "IDENTITY_EVIDENCE", {k: v for k, v in reg.IDENTITY_EVIDENCE.items() if k != "prod_x"})
    assert reg.derive_last_state([r], TODAY)["prod_x"]["last_verified_at"] == ""
    # 正本の商品が見つからない・正本が読めない（空）ときも引き継がない
    monkeypatch.setattr(reg, "canonical_products", lambda: {})
    assert reg.derive_last_state([r], TODAY)["prod_x"]["last_verified_at"] == ""


def test_changed_then_failed_old_verified_date_does_not_return(fake_registry):
    hist = [_res(day="2026-11-05"), _res(status="changed", day="2026-11-06"), _res(status="failed", day="2026-11-07"),
            _res(status="failed", day="2026-11-08")]
    assert reg.derive_last_state(hist, TODAY)["prod_x"]["last_verified_at"] == ""
    row = {r["product_id"]: r for r in reg.verification_status(hist, today=TODAY)}["prod_x"]
    assert row["last_verified"] == "" and row["expired"]                           # 登録簿の確認日にも、再確認の 11-05 にも戻らない（Auditor M-1）


def test_sale_ended_then_blocked_old_verified_date_does_not_return(fake_registry):
    hist = [_res(day="2026-11-05"), _res(status="sale_ended", day="2026-11-06"), _res(status="blocked", day="2026-11-07")]
    assert reg.derive_last_state(hist, TODAY)["prod_x"]["last_verified_at"] == ""
    row = {r["product_id"]: r for r in reg.verification_status(hist, today=TODAY)}["prod_x"]
    assert row["last_verified"] == "" and row["expired"]


def test_human_recheck_after_invalidation_restores_the_registry_day(fake_registry):
    hist = [_res(status="sale_ended", day="2026-11-03"), _res(status="failed", day="2026-11-04")]
    row = {r["product_id"]: r for r in reg.verification_status(hist, today=TODAY)}["prod_x"]
    assert row["last_verified"] == "" and row["expired"]                           # 登録簿 11-01 は無効化 11-03 より前
    fake_registry["prod_x"]["checked_on"] = "2026-11-05"                           # 人が無効化の後に確かめ直した
    row = {r["product_id"]: r for r in reg.verification_status(hist, today=TODAY)}["prod_x"]
    assert row["last_verified"] == "2026-11-05" and not row["expired"]


def test_valid_unchanged_after_invalidation_recovers_only_with_exact_identity(fake_registry):
    base = [_res(day="2026-11-05"), _res(status="sale_ended", day="2026-11-06")]
    wrong = base + [_res(day="2026-11-07", model="WRONG", match="WRONG")]
    assert reg.derive_last_state(wrong, TODAY)["prod_x"]["last_verified_at"] == ""        # 型番が違う一致では復帰しない
    ok = wrong + [_res(day="2026-11-08")]
    assert reg.derive_last_state(ok, TODAY)["prod_x"]["last_verified_at"] == "2026-11-08"  # 型番が一致した再確認で復帰する


def test_variant_group_identity_requires_the_exact_sku_group():
    prods = reg.canonical_products()
    ev = reg.IDENTITY_EVIDENCE["prod_iphoneair_256"]
    grp = ",".join(sorted(ev["variant_skus"]))
    p = prods["prod_iphoneair_256"]
    assert not p.get("model_number")
    assert reg.recheck_identity_ok("prod_iphoneair_256", {"model": "", "match": grp}, p)
    assert not reg.recheck_identity_ok("prod_iphoneair_256", {"model": "", "match": "OTHER"}, p)
    assert not reg.recheck_identity_ok("prod_iphoneair_256", {"model": "", "match": ""}, p)
    assert not reg.recheck_identity_ok("prod_iphoneair_256", {"model": "", "match": grp}, None)


def test_jan_only_product_identity_requires_the_evidence_edition_or_jan():
    p = reg.canonical_products()["prod_switch2"]
    assert not p.get("model_number") and p.get("jan_code")
    ed = reg.IDENTITY_EVIDENCE["prod_switch2"]["edition"]
    assert reg.recheck_identity_ok("prod_switch2", {"model": "", "match": f"Nintendo Switch 2 本体 {ed}"}, p)
    assert reg.recheck_identity_ok("prod_switch2", {"model": "", "match": p["jan_code"]}, p)
    assert not reg.recheck_identity_ok("prod_switch2", {"model": "", "match": "Nintendo Switch 2 本体 別の版"}, p)
    assert not reg.recheck_identity_ok("prod_switch2", {"model": "X", "match": f"Nintendo Switch 2 本体 {ed}"}, p)


def test_latest_changed_or_sale_ended_result_leaves_no_verified_day_in_the_status(fake_registry):
    for st in ("changed", "sale_ended"):
        hist = [_res(day="2026-11-05"), _res(status=st, day="2026-11-08")]
        row = {r["product_id"]: r for r in reg.verification_status(hist, today=TODAY)}["prod_x"]
        assert row["last_verified"] == "" and row["expired"] and row["last_recheck_result"] == st


def test_every_real_recheck_target_has_a_result_shape_that_passes_the_identity_check():
    """実際の再確認の対象（_targets）が作る model・match が、正本の商品に対する同一性の確認を通る（引き継ぎが全部止まっていない）。"""
    ro = _load("scripts/recheck_official.py", "recheck_official_t7e1")
    prods = reg.canonical_products()
    checked = 0
    for t in ro._targets():
        r = {"product_id": t["product_id"], "model": t["model"], "match": t["match"]}
        if reg.identity_state(dict(prods[t["product_id"]], id=t["product_id"]))[0] == "IDENTITY_CONFIRMED":
            assert reg.recheck_identity_ok(t["product_id"], r, prods[t["product_id"]]), t["product_id"]
            checked += 1
    assert checked >= 10


# ---------------- 個別の最終状態を新しく公開・保存しない ----------------
def test_no_new_individual_last_state_file_is_written_or_read():
    for rel in ("scripts/recheck_official.py", "scripts/audit_official_sources.py", "scripts/operator_health_alert.py",
                "scripts/deploy_check.py", "src/market/official_registry.py", ".github/workflows/daily_lp.yml"):
        txt = (ROOT / rel).read_text(encoding="utf-8")
        assert "last_state.json" not in txt.replace("last_state.json が", "").replace("last_state.json は", "") or rel == "scripts/deploy_check.py", rel
    assert not (ROOT / "exports" / "official_recheck" / "last_state.json").exists()


def test_history_is_kept_by_days_so_verified_days_do_not_fall_out_of_the_window():
    ro = _load("scripts/recheck_official.py", "recheck_official_t7e1b")
    now = datetime(2026, 11, 10, 12, 0, tzinfo=JST)
    old = {"product_id": "a", "observed_at": "2026-09-01T10:00:00+09:00"}
    recent = {"product_id": "a", "observed_at": "2026-10-20T10:00:00+09:00"}
    out = ro.trim_history([old, recent, {"product_id": "a"}, None], now)
    assert out == [recent]                                                        # 35 日より古い・日時の無いものは落とす
    assert ro.HISTORY_DAYS > 14                                                    # 公式直販の期限（14 日）より長い
    many = [{"product_id": "a", "observed_at": "2026-11-09T10:00:00+09:00"}] * (ro.HISTORY_LIMIT + 50)
    assert len(ro.trim_history(many, now)) == ro.HISTORY_LIMIT


def test_public_aggregates_stay_public_and_individual_state_is_not_in_the_public_summary():
    rep = {"schema": 1, "type": "RESEARCH_CANDIDATES", "generated_at": "2026-11-09T12:00:00+09:00", "candidates": [], "counts": {},
           "metrics": {"official_state_counts": {s: 1 for s in ost.STATES}}, "official_states": {"prod_secret": "STALE"}}
    pub = json.dumps(rc.public_summary(rep), ensure_ascii=False)
    assert "prod_secret" not in pub and "official_states" not in pub and "last_verified" not in pub
    assert tuple(rc.public_summary(rep)["official_state_counts"]) == ost.STATES


# ---------------- 実行の記録 ----------------
N0 = datetime(2026, 11, 9, 11, 28, 49, tzinfo=timezone.utc)
ENV = {"GITHUB_EVENT_NAME": "schedule", "GITHUB_RUN_ATTEMPT": "1", "SCHEDULE_CRON": "17 3 * * *"}


def test_cron_schedule_delay_is_started_at_minus_scheduled_for():
    r = RO.start_record(ENV, N0, "daily")
    assert r["scheduled_for"] == "2026-11-09T03:17:00Z" and r["started_at"] == "2026-11-09T11:28:49Z"
    assert r["schedule_delay_seconds"] == 29509                                       # 約 8.2 時間（2026-11-09 の実測）
    # 予定の時刻より前に開始した（前日の予定）
    early = RO.start_record(ENV, datetime(2026, 11, 9, 2, 0, tzinfo=timezone.utc), "daily")
    assert early["scheduled_for"] == "2026-11-08T03:17:00Z"


def test_manual_and_rerun_delay_is_null():
    assert RO.start_record({**ENV, "GITHUB_EVENT_NAME": "workflow_dispatch"}, N0, "daily")["schedule_delay_seconds"] is None
    assert RO.start_record({**ENV, "GITHUB_EVENT_NAME": "workflow_dispatch"}, N0, "daily")["trigger"] == "manual"
    assert RO.start_record({**ENV, "GITHUB_RUN_ATTEMPT": "2"}, N0, "daily")["schedule_delay_seconds"] is None
    assert RO.start_record({**ENV, "GITHUB_RUN_ATTEMPT": "x"}, N0, "daily")["schedule_delay_seconds"] is None
    assert RO.start_record({**ENV, "SCHEDULE_CRON": "*/5 * * * *"}, N0, "daily")["schedule_delay_seconds"] is None   # 読めない cron
    assert RO.start_record({k: v for k, v in ENV.items() if k != "SCHEDULE_CRON"}, N0, "daily")["scheduled_for"] is None
    assert RO.start_record({**ENV, "GITHUB_EVENT_NAME": "push"}, N0, "daily")["trigger"] == "other"


def test_public_run_record_has_only_the_allowed_keys_and_no_detail(tmp_path):
    rec = RO.start_record(ENV, N0, "daily")
    pub = RO.public_record(rec, N0 + timedelta(seconds=6311), "daily")
    assert tuple(pub) == RO.PUBLIC_KEYS == ("last_run_at", "runtime_seconds", "schedule_delay_seconds", "trigger", "lane")
    assert pub["runtime_seconds"] == 6311 and pub["schedule_delay_seconds"] == 29509 and pub["trigger"] == "schedule" and pub["lane"] == "daily"
    # 壊れた・無い記録は null（例外にしない）。時計が逆行した値・異常に長い値は捨てる
    for bad in (None, {}, "x", {"started_at": "bad"}):
        p = RO.public_record(bad, N0, "daily")
        assert p["runtime_seconds"] is None and p["schedule_delay_seconds"] is None and p["trigger"] == "other"
    assert RO.public_record(rec, N0 - timedelta(seconds=5), "daily")["runtime_seconds"] is None
    assert RO.public_record(rec, N0 + timedelta(days=3), "daily")["runtime_seconds"] is None
    assert RO.public_record({**rec, "schedule_delay_seconds": -5}, N0, "daily")["schedule_delay_seconds"] is None


def test_run_timing_cli_writes_private_start_and_public_finish_and_never_fails(tmp_path):
    assert RO.main(["start", "--lane", "daily"], root=tmp_path, env=ENV, now=N0) == 0
    assert (tmp_path / ".private" / "ops" / "run_timing_daily.json").exists()
    assert RO.main(["finish", "--lane", "daily"], root=tmp_path, now=N0 + timedelta(seconds=100)) == 0
    doc = json.loads((tmp_path / "exports" / "ops" / "run_timing_daily.json").read_text(encoding="utf-8"))
    assert set(doc) == set(RO.PUBLIC_KEYS) | {"schema", "type", "audience"} and doc["runtime_seconds"] == 100
    assert RO.main(["bogus"], root=tmp_path) == 0 and RO.main(["start", "--lane", "BAD LANE!"], root=tmp_path) == 0
    # 開始の記録が無い・壊れていても finish は null で書く
    (tmp_path / ".private" / "ops" / "run_timing_daily.json").write_text("{broken", encoding="utf-8")
    assert RO.main(["finish", "--lane", "daily"], root=tmp_path, now=N0) == 0
    assert json.loads((tmp_path / "exports" / "ops" / "run_timing_daily.json").read_text(encoding="utf-8"))["runtime_seconds"] is None


def test_run_timing_lanes_are_separate_files(tmp_path):
    RO.main(["start", "--lane", "daily"], root=tmp_path, env=ENV, now=N0)
    RO.main(["start", "--lane", "fast"], root=tmp_path, env={**ENV, "SCHEDULE_CRON": "5 */12 * * *"}, now=N0)
    assert (tmp_path / ".private" / "ops" / "run_timing_daily.json").exists() and (tmp_path / ".private" / "ops" / "run_timing_fast.json").exists()


def test_workflow_records_run_timing_without_secrets_and_never_stops_the_run():
    wf = yaml.safe_load((ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8"))
    steps = {s["name"]: s for s in wf["jobs"]["update-lp"]["steps"]}
    for name in ("Run timing (start)", "Run timing (finish)"):
        s = steps[name]
        assert s.get("continue-on-error") is True and "secrets." not in json.dumps(s)
    assert steps["Run timing (start)"]["env"]["SCHEDULE_CRON"] == "${{ github.event.schedule }}"
    names = [s["name"] for s in wf["jobs"]["update-lp"]["steps"]]
    assert names.index("Run timing (start)") < names.index("Install dependencies") and names.index("Run timing (finish)") < names.index("Deploy check")


# ---------------- Research Ledger の観測性 ----------------
def test_restore_status_is_not_overwritten_by_the_same_run_reuse():
    run = "gh-1-1"
    # 最初の生成（前回の台帳を引き継げた）
    assert rc.ledger_restore_status({"run_id": "gh-0-1", "candidates": {}}, rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN, run) == rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN
    # 同じ実行の再生成（REUSED）は、最初の生成が残した値を引き継ぐ
    raw = {"run_id": run, "candidates": {}, "first_ledger_state": rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN}
    assert rc.ledger_restore_status(raw, rc.LEDGER_REUSED_WITHIN_RUN, run) == rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN
    # 別の実行の値・語彙が不正・無いものは UNKNOWN（REUSED を復元の結果にしない）
    for bad in ({"run_id": "other", "first_ledger_state": "RESTORED_FROM_PREVIOUS_RUN"}, {"run_id": run, "first_ledger_state": "SECRET"},
                {"run_id": run}, None, "x", {"run_id": run, "first_ledger_state": rc.LEDGER_REUSED_WITHIN_RUN}):
        assert rc.ledger_restore_status(bad, rc.LEDGER_REUSED_WITHIN_RUN, run) == "UNKNOWN"


def test_restore_status_persists_through_write_outputs_and_the_next_generation(tmp_path):
    run = "gh-7-1"
    rep, state = {"schema": 1, "type": "RESEARCH_CANDIDATES", "generated_at": "2026-11-09T12:00:00+09:00", "candidates": [], "counts": {},
                  "ledger_state": rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN, "ledger_restore_status": rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN,
                  "official_states": {}, "metrics": {}}, {}
    summ = rc.write_outputs(rep, state, tmp_path / "priv", tmp_path / "pub", run)
    assert summ["ledger_restore_status"] == rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN and summ["cross_run_restored"] is True
    raw = json.loads((tmp_path / "priv" / "state.json").read_text(encoding="utf-8"))
    assert raw["first_ledger_state"] == rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN
    # 2 回目の生成（同じ実行）: 台帳の状態は REUSED_WITHIN_RUN でも、復元の結果は 1 回目のまま
    state2, _prev = rc.classify_ledger(raw, run, True)
    assert state2 == rc.LEDGER_REUSED_WITHIN_RUN
    restore2 = rc.ledger_restore_status(raw, state2, run)
    assert restore2 == rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN
    rep2 = dict(rep, ledger_state=state2, ledger_restore_status=restore2)
    summ2 = rc.write_outputs(rep2, state, tmp_path / "priv", tmp_path / "pub", run)
    assert summ2["ledger_state"] == "REUSED_WITHIN_RUN" and summ2["ledger_restore_status"] == rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN   # 互換: 従来の項目はそのまま
    assert json.loads((tmp_path / "priv" / "state.json").read_text(encoding="utf-8"))["first_ledger_state"] == rc.LEDGER_RESTORED_FROM_PREVIOUS_RUN


def test_ledger_public_aggregate_is_fixed_vocabulary_only_and_leaks_nothing():
    rep = {"schema": 1, "type": "RESEARCH_CANDIDATES", "generated_at": "2026-11-09T12:00:00+09:00", "candidates": [], "counts": {},
           "ledger_restore_status": "SECRET_VALUE", "first_ledger_state": "SECRET",
           "metrics": {"research_signals": {"momentum_observed": 338, "momentum_not_comparable": 0},
                       "tcg_detection_delay": {"measured": 2, "unknown_published_at": 1, "source_gap_excluded": 1,
                                               "previously_observable_excluded": 1, "already_processed": 5, "secret_event": 9}}}
    pub = rc.public_summary(rep)
    s = json.dumps(pub, ensure_ascii=False)
    assert pub["ledger_restore_status"] == "UNKNOWN" and pub["cross_run_restored"] is False and pub["ledger_version"] == rc.SCHEMA
    assert pub["momentum_comparable"] is True and pub["detection_delay_measured"] == 2 and pub["detection_delay_unknown"] == 3
    assert "SECRET" not in s and "secret_event" not in s and "first_ledger_state" not in pub
    assert pub["tcg_detection_delay"]["already_processed"] == 5
    not_cmp = rc.public_summary({**rep, "metrics": {"research_signals": {"momentum_observed": 10, "momentum_not_comparable": 3}}})
    assert not_cmp["momentum_comparable"] is False
    assert rc.public_summary({**rep, "metrics": {}})["momentum_comparable"] is False


def test_detection_delay_counts_add_up_with_already_processed():
    """new_after_baseline == measured + 測れなかった（3 種）+ 前の run で処理済み（件数が説明できる）。"""
    from src.tcg import detection_delay as dd
    import inspect
    src = inspect.getsource(dd)
    assert 'counts["already_processed"] += 1' in src and '"already_processed": 0' in src


def test_state_file_contains_no_secret_and_the_official_state_file_is_private(tmp_path):
    rep = {"schema": 1, "type": "RESEARCH_CANDIDATES", "generated_at": "2026-11-09T12:00:00+09:00", "candidates": [], "counts": {},
           "ledger_state": rc.LEDGER_NEW_THIS_RUN, "official_states": {"prod_a": "SALE_ENDED"}, "metrics": {}}
    summ = rc.write_outputs(rep, {}, tmp_path / "priv", tmp_path / "pub", "r")
    assert "prod_a" not in json.dumps(summ) and "prod_a" not in (tmp_path / "pub" / "summary.json").read_text(encoding="utf-8")
    assert json.loads((tmp_path / "priv" / "official_state.json").read_text(encoding="utf-8"))["states"] == {"prod_a": "SALE_ENDED"}
    assert not (tmp_path / "pub" / "official_state.json").exists()

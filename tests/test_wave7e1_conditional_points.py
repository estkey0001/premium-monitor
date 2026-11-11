"""Wave 7e-1: 条件つきの仕入れ値（クーポン・キャンペーン・会員限定）の行には点を付けない（Wave 5 の変異テスト負債の解消）。

通信はしない（合成の値だけ）。`SUSPICIOUS_REASONS` から ACQUISITION_CONDITIONAL を外すと、条件つきの値引きを
現金の仕入れ値のように扱って点（調べる順番）を付けてしまう。それを固定する。
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from src.research import candidates as rc
from src.research import signals as sg
from src.research import triage as tr

JST = timezone(timedelta(hours=9))
NOW = datetime(2026, 10, 29, 12, 0, tzinfo=JST)
FRESH = "2026-10-29T10:00:00+09:00"


def _dp(price=120000):
    return {"candidate_id": "dp_x", "kind": "DISCOVERED_PRODUCT_CANDIDATE", "status": rc.DISCOVERED, "name": "Nikon Z f 限定カラー",
            "identity_basis": "JAN", "observed_sell_price": price, "observed_at": FRESH, "retail_price_hint": None,
            "missing_requirements": ["CANONICAL_UNREGISTERED", "OFFICIAL_PRICE_UNKNOWN"]}


def _lk(**k):
    base = {"status": "MATCHED", "retailer": "公式", "source_type": "OFFICIAL_DIRECT", "product_url": "https://www.example.com/p/1",
            "price": 100000, "listed_price": 100000, "availability_state": "OUT_OF_STOCK", "observed_at": FRESH,
            "identity_evidence": {"basis": "JAN", "matched_name": "Nikon Z f 限定カラー"}, "price_basis": "UNCONDITIONAL",
            "price_type": "REGULAR", "price_conditions": [], "points": 0, "cashback": 0}
    base.update(k)
    return base


def _annotated(lookup):
    d = _dp()
    rc.apply_lookups([d], {"dp_x": lookup}, NOW, FRESH)
    tri = tr.triage([d], NOW, lookup_ready_of=lambda c: True, lookup_results={"dp_x": {"status": "MATCHED"}})
    sg.annotate_buyback_rows(tri["rows"], NOW)
    return tri["rows"][0]


def test_conditional_evidence_with_empty_conditions_gets_no_points_and_is_quarantined():
    for kw in ({"price_basis": "CAMPAIGN"}, {"price_type": "COUPON"}, {"price_type": "MEMBERSHIP"}, {"price_type": "CONDITIONAL"}):
        r = _annotated(_lk(**kw))                                    # price_conditions は空（条件の文言が無くても、種類だけで条件つきと判定する）
        assert r["retail_conditions"] == []
        assert "ACQUISITION_CONDITIONAL" in r["missing_requirements"], kw
        assert r["signal_points"] == 0 and r["signal_reasons"] == ["suspicious_no_boost"], kw
        assert sg.is_quarantined(r), kw


def test_same_row_without_the_conditional_requirement_does_get_points():
    base = _annotated(_lk())
    assert "ACQUISITION_CONDITIONAL" not in base["missing_requirements"]
    assert base["signal_points"] > 0                                 # 限定の公式・在庫なしなどで点が付く（比較用）
    # 同じ行から ACQUISITION_CONDITIONAL だけを足すと、点が 0 になる（SUSPICIOUS_REASONS が効いている）
    tri_row = {**base, "missing_requirements": list(base["missing_requirements"]) + ["ACQUISITION_CONDITIONAL"]}
    sg.annotate_buyback_rows([tri_row], NOW)
    assert tri_row["signal_points"] == 0 and tri_row["signal_reasons"] == ["suspicious_no_boost"]
    assert "ACQUISITION_CONDITIONAL" in sg.SUSPICIOUS_REASONS


def test_regular_price_without_conditions_is_not_marked_conditional():
    r = _annotated(_lk(price_basis="UNCONDITIONAL", price_type="REGULAR", price_conditions=[]))
    assert "ACQUISITION_CONDITIONAL" not in r["missing_requirements"]
    assert r["retail_conditions"] == [] and not sg.is_quarantined(r)

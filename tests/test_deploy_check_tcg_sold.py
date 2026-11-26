# -*- coding: utf-8 -*-
"""#896・#897: TCG の二次流通の成約の台帳と、プレミア率の根拠の検査。"""
import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("dc_sold", Path(__file__).resolve().parents[1] / "scripts" / "deploy_check.py")
dc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dc)


def _item(pct, basis="SOLD_MEDIAN", n=3):
    return {"product_id": "p", "premium": {"premium_percent": pct, "price_basis": basis, "sealed_sample_count": n}}


def test_premium_from_sold_median_with_enough_samples_passes():
    assert dc.check_tcg_premium_basis([_item(30.0), _item(None, basis=None, n=0)], 3) == []


def test_premium_from_listing_or_few_samples_is_flagged():
    assert dc.check_tcg_premium_basis([_item(30.0, basis="LISTING_LOW")], 3) == ["p"]
    assert dc.check_tcg_premium_basis([_item(30.0, basis=None)], 3) == ["p"]
    assert dc.check_tcg_premium_basis([_item(30.0, n=1)], 3) == ["p"]


def test_current_repository_passes_896_897():
    rows = dc._check_tcg_sold_ledger()
    assert [r["check"] for r in rows] == ["tcg_sold_ledger_only_sales", "tcg_premium_from_sold_median_only"]
    assert all(r["level"] == "ok" for r in rows), rows

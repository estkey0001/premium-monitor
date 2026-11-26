# -*- coding: utf-8 -*-
"""Wave 8 の監査の指摘への対応: PLANT は登録しない・拒否リストが読めなければ発見のエンジンを止める。
（ONE PIECE 公式ショップの応募条件の原文を出さないことは tests/test_coverage_wave8.py で確かめる）"""
import pytest

from src.discovery.engine import urlpolicy
from src.tcg.lottery import pipeline, registry


def test_plant_is_not_collected_until_permission_is_confirmed():
    assert "plant_lottery" not in pipeline._adapters()
    src = (registry.__file__ and open(registry.__file__, encoding="utf-8").read())
    i = src.index('_src("PLANT"')
    entry = src[i:src.index("_src(", i + 5)]
    assert "CM_UNAVAILABLE" in entry and "adapter=" not in entry and "terms/web.html" in entry


def test_unreadable_policy_list_stops_the_engine(tmp_path):
    bad = tmp_path / "c.yaml"
    bad.write_text("candidates: [::: 壊れた yaml", encoding="utf-8")
    with pytest.raises(RuntimeError):
        urlpolicy.policy_excluded_domains(bad)
    with pytest.raises(RuntimeError):
        urlpolicy.policy_excluded_domains(tmp_path / "missing.yaml")


def test_current_policy_list_is_readable_and_not_empty():
    assert urlpolicy.policy_excluded_domains()

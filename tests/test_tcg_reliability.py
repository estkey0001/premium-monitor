# -*- coding: utf-8 -*-
"""TCG データの更新が安全に続く構造（workflow の同時実行・Python 3.11 ゲート・古いページの検知）を固定する。"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
WF = ROOT / ".github" / "workflows"


def _wf(name: str) -> dict:
    return yaml.safe_load((WF / name).read_text(encoding="utf-8"))


def _steps(name: str) -> list:
    return list(_wf(name)["jobs"].values())[0]["steps"]


def test_every_workflow_that_pushes_data_shares_one_concurrency_group_without_cancel():
    """main へ commit / push する workflow は、同じ group で待機させる（実行中のデータ収集を途中で取り消さない）。"""
    pushers = []
    for f in sorted(WF.glob("*.yml")):
        text = f.read_text(encoding="utf-8")
        if "git push" in text:
            pushers.append(f.name)
            c = yaml.safe_load(text)["concurrency"]
            assert c["cancel-in-progress"] is False, f.name
    assert pushers == ["daily_lp.yml"]                       # push するのは Daily LP だけ（他に増えたらここで気付く）
    assert _wf("daily_lp.yml")["concurrency"]["group"] == "daily-lp-update"


def test_daily_lp_checks_out_latest_main_after_waiting():
    """待機した実行は、キューに入った時点の古いコミットではなく最新の main から始める（衝突の原因）。"""
    co = next(s for s in _steps("daily_lp.yml") if str(s.get("uses", "")).startswith("actions/checkout"))
    assert co["with"]["ref"] == "main"


def test_py311_gate_runs_before_collection_and_is_not_optional():
    steps = _steps("daily_lp.yml")
    names = [s.get("name") for s in steps]
    i = names.index("Python 3.11 gate")
    assert i < names.index("Install Playwright browsers")    # 収集・生成・push より前
    g = steps[i]
    assert not g.get("continue-on-error")                     # 失敗したらこの実行は commit せず止まる
    for needle in ("sys.version_info[:2] == (3, 11)", "compileall", "pytest", "test_tcg_buyback.py", "test_tcg_hub.py"):
        assert needle in g["run"], needle


def test_py311_gate_workflow_is_read_only_and_uses_real_311():
    wf = _wf("py311_gate.yml")
    assert wf["permissions"] == {"contents": "read"}
    text = (WF / "py311_gate.yml").read_text(encoding="utf-8")
    assert "git push" not in text and "git commit" not in text and "secrets." not in text
    sp = next(s for s in _steps("py311_gate.yml") if str(s.get("uses", "")).startswith("actions/setup-python"))
    assert str(sp["with"]["python-version"]) == "3.11"


def test_stale_tcg_html_is_detected_by_850(tmp_path):
    """生成に失敗して古い tcg.html が残ったとき、#850 の判定が不一致（= Errors）になる。"""
    from deploy_check import tcg_page_matches_source
    lot = tmp_path / "lotteries.json"
    lot.write_text(json.dumps({"generated_at": "2026-11-21T19:47:31+09:00"}), encoding="utf-8")
    page = tmp_path / "tcg.html"
    meta = '<html><head><meta name="tcg-source-generated-at" content="%s"></head></html>'
    page.write_text(meta % "2026-11-21T12:43:22+09:00", encoding="utf-8")                  # 古いページ
    assert tcg_page_matches_source(lot, page)[0] is False
    page.write_text(meta % "2026-11-21T19:47:31+09:00", encoding="utf-8")                  # 新しいページ
    assert tcg_page_matches_source(lot, page)[0] is True
    page.write_text("<html><head></head></html>", encoding="utf-8")                        # meta が無い
    assert tcg_page_matches_source(lot, page)[0] is False
    page.unlink()                                                                           # ページが無い
    assert tcg_page_matches_source(lot, page)[0] is False
    lot.write_text("{", encoding="utf-8")                                                   # 元データが壊れている
    page.write_text(meta % "", encoding="utf-8")
    assert tcg_page_matches_source(lot, page)[0] is False


def test_850_in_deploy_check_uses_the_tested_function():
    """#850 は、上のテストで確かめた関数をそのまま使っている（本物の deploy-check でも古いページ fixture で Errors 1 を確認済み）。"""
    src = (ROOT / "scripts" / "deploy_check.py").read_text(encoding="utf-8")
    assert 'tcg_page_matches_source(_lot850, PUBLIC_DIR / "tcg.html")' in src
    assert '_add(850, "tcg_page_matches_source", _ok850' in src


def test_deploy_check_has_workflow_checks():
    src = (ROOT / "scripts" / "deploy_check.py").read_text(encoding="utf-8")
    assert "workflow_checkout_latest_main" in src and "workflow_py311_gate" in src

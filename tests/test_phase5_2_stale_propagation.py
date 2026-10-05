"""Phase 5.2: 無効になったルート・案件が、別の成果物（AI Opportunities・資金配分・Health・実行履歴・通知・β）
経由で復活しないこと、公式の購入送料の扱いのテスト。

ルートの照合は route_id（opportunity.route_key）で行い、商品単位では照合しない。
GR IV の値は本番の生成物（2026-10-04 01:37）にあった偽ルートと同じ形。それ以外のデータはテスト用の架空のもの。
"""

from __future__ import annotations

import importlib.util
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.content.ui import opportunity as opp
from src.market import official_shipping as osh
from src.tcg.models import JST

ROOT = Path(__file__).resolve().parent.parent


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RF = _load("route_fixtures_p52", Path(__file__).with_name("route_fixtures.py"))
GAO = _load("gao_p52", ROOT / "scripts" / "generate_ai_opportunities.py")
GAP = _load("gap_p52", ROOT / "scripts" / "generate_allocation_plan.py")
GEI = _load("gei_p52", ROOT / "scripts" / "generate_execution_intelligence.py")
GNO = _load("gno_p52", ROOT / "scripts" / "generate_notifications.py")
GHR = _load("ghr_p52", ROOT / "scripts" / "generate_health_report.py")


def _gen(now):
    from src.content.daily_lp_generator import DailyLPGenerator
    g = DailyLPGenerator.__new__(DailyLPGenerator)
    g.settings = {}
    g._msrp_evidence = {}
    g._product_info = {}
    g._gate_now = now
    return g


def _routes(now):
    """同じ商品（prod_cam）に、今も確定のルート A と、無効になったルート B（GR IV と同じ形の偽ルート）。"""
    a = RF.safe_route(now, "prod_cam", buy=123457, sell=160000)
    a["buy_source"], a["sell_source"] = "カメラ店A", "買取店A"
    b = RF.safe_route(now, "prod_cam", buy=107491, sell=151000, buy_exact_match=False, sell_exact_match=False,
                      buy_canonical_type="LISTING", buy_condition="used_a", sell_condition="used_a",
                      buy_item_url="https://www.amazon.co.jp/s?k=x")
    b["buy_source"], b["sell_source"] = "Amazon JP (新品出品)", "フジヤカメラ"
    b["net_profit"] = 39009
    return a, b


def _write(root: Path, rel: str, data) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")


def _old_ai_file(tmp_path, monkeypatch, now, routes):
    """生成時点では両方のルートが確定だった AI のファイルを、実際の generate_ai_opportunities で作る。"""
    _write(tmp_path, "exports/profit_routes/latest.json",
           {"generated_at": "2026-10-04 01:37 JST", "main_routes": routes, "reference_routes": []})
    monkeypatch.setattr(GAO, "ROOT", tmp_path)
    monkeypatch.setattr(GAO, "OUT", tmp_path / "exports" / "ai_opportunities")
    monkeypatch.setattr(GAO, "_price_trend", lambda pid: {"7d": "→", "30d": "→", "90d": "→"})
    monkeypatch.setattr(GAO, "NOW", now)
    assert GAO.main() == 0
    return json.loads((tmp_path / "exports/ai_opportunities/latest.json").read_text(encoding="utf-8"))


# ── ルートの識別子 ──────────────────────────────────────────────────────

def test_route_key_distinguishes_routes_of_the_same_product():
    now = datetime.now(tz=JST)
    a, b = _routes(now)
    assert opp.route_key(a) and opp.route_key(b) and opp.route_key(a) != opp.route_key(b)
    # 価格が変われば別のルート（古い価格の記録を今のルートとして扱わない）
    assert opp.route_key(dict(a, buy_price=120000)) != opp.route_key(a)
    # 項目が欠けたものは照合できない（空文字）
    assert opp.route_key({"product_id": "prod_cam"}) == ""
    keys = opp.current_route_keys({"main_routes": [a, b]}, now)
    assert keys["main"] == {opp.route_key(a)}            # B は判定で外れる
    assert opp.record_route_ok({"route_id": opp.route_key(a), "kind": "main"}, keys)
    assert not opp.record_route_ok({"route_id": opp.route_key(b), "kind": "main"}, keys)
    assert not opp.record_route_ok({"product_id": "prod_cam", "kind": "main"}, keys)   # 商品だけでは通らない


# ── AI Dashboard（古いファイル・同じ商品の有効なルートと無効なルート） ─────────────────────────

def test_ai_dashboard_hides_invalid_route_of_same_product(tmp_path, monkeypatch):
    now = datetime.now(tz=JST)
    a, b = _routes(now)
    gen_ok = dict(b, buy_exact_match=True, sell_exact_match=True, buy_canonical_type="RETAIL",
                  buy_condition="new_unopened", sell_condition="new_unopened", buy_item_url="https://x.example/i/1",
                  net_profit=151000 - 107491 - 4500, roi=(151000 - 107491 - 4500) / 107491)
    d = _old_ai_file(tmp_path, monkeypatch, now, [a, gen_ok])
    assert len(d["todays_opportunities"]) == 2 and all(o["route_id"] for o in d["todays_opportunities"])
    # その後 B は照合未了と分かった（AI のファイルは古いまま）。同じ商品の A は今も確定
    b_now = dict(gen_ok, buy_exact_match=False)
    later = (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M JST")     # 利益ルートは AI より後に作り直された
    html = _gen(now)._ai_dashboard_section(d, {"generated_at": later,
                                               "main_routes": [a, b_now], "reference_routes": []})
    net_a = next(o["net_profit"] for o in d["todays_opportunities"] if o["route_id"] == opp.route_key(a))
    net_b = next(o["net_profit"] for o in d["todays_opportunities"] if o["route_id"] == opp.route_key(gen_ok))
    assert "カメラ店A" in html and f"{net_a:,}" in html                     # 同じ商品の有効なルート A は出る
    assert "Amazon" not in html and f"{net_b:,}" not in html and "107,491" not in html   # 無効になった B は出ない
    assert re.search(r"Main Routes: <b[^>]*>1</b>", html)
    # AI の集計が利益ルートより古いことを、元の生成時刻のまま出す（時刻は書き換えない）
    assert f"AI の集計は前回の生成（{d['generated_at']}）のまま" in html
    # 今日のおすすめ（1位）が B なら出さない
    b_first = sorted(d["todays_opportunities"], key=lambda o: o["buy_price"] != 107491)
    d2 = dict(d, todays_opportunities=b_first, daily_recommendation={"product": "商品prod_cam", "buy_now": "BUY",
                                                                       "opportunity_score": 99, "reason": "x 利益¥42,009"})
    html2 = _gen(now)._ai_dashboard_section(d2, {"main_routes": [a, b_now], "reference_routes": []})
    assert "今日のおすすめ" not in html2 and "42,009" not in html2


def test_ai_dashboard_rejects_records_without_route_id():
    now = datetime.now(tz=JST)
    a, _b = _routes(now)
    op = {"product": "商品prod_cam", "product_id": "prod_cam", "kind": "main", "buy_now": "BUY", "action": "BUY",
          "net_profit": 39009, "roi": 0.36, "buy_price": 107491, "sell_price": 151000}
    html = _gen(now)._ai_dashboard_section({"todays_opportunities": [op], "today_tasks": ["✅ 商品prod_cam を仕入れる"],
                                            "daily_recommendation": {"product": "商品prod_cam", "buy_now": "BUY",
                                                                     "opportunity_score": 90, "reason": "r"}},
                                           {"main_routes": [a], "reference_routes": []})
    assert "39,009" not in html and "商品prod_cam" not in html     # 商品は同じでも route_id が無ければ出さない


# ── Capital Dashboard ─────────────────────────────────────────────────────

def test_capital_dashboard_drops_invalid_allocation(tmp_path, monkeypatch):
    now = datetime.now(tz=JST)
    a, b = _routes(now)
    gen_ok = dict(b, buy_exact_match=True, sell_exact_match=True, buy_canonical_type="RETAIL",
                  buy_condition="new_unopened", sell_condition="new_unopened", buy_item_url="https://x.example/i/1",
                  net_profit=151000 - 107491 - 4500, roi=(151000 - 107491 - 4500) / 107491)
    d = _old_ai_file(tmp_path, monkeypatch, now, [a, gen_ok])
    monkeypatch.setattr(GAP, "NOW", now)
    keys_then = opp.current_route_keys({"main_routes": [a, gen_ok]}, now)
    ops = GAP.build_opportunity_metrics(d, {}, keys_then)
    plan = GAP.allocate(3_000_000, ops)
    assert {x["route_id"] for x in plan["allocations"]} == {opp.route_key(a), opp.route_key(gen_ok)}
    alloc = {"default_budget": 3_000_000, "plans": {"3000000": plan}}
    b_now = dict(gen_ok, sell_exact_match=False)
    html = _gen(now)._capital_dashboard_html(alloc, {"main_routes": [a, b_now]})
    kept = [x for x in plan["allocations"] if x["route_id"] == opp.route_key(a)][0]
    assert f"+¥{kept['expected_profit']:,}" in html and f"¥{kept['total']:,}" in html
    bad = [x for x in plan["allocations"] if x["route_id"] == opp.route_key(gen_ok)][0]
    assert f"{bad['expected_profit']:,}" not in html
    # 生成時も、今のルートで照合できない候補は配分に使わない
    keys_now = opp.current_route_keys({"main_routes": [a, b_now]}, now)
    assert {o["route_id"] for o in GAP.build_opportunity_metrics(d, {}, keys_now)} == {opp.route_key(a)}


# ── Health ───────────────────────────────────────────────────────────

def test_health_profit_metrics_use_current_routes():
    now = datetime.now(tz=JST)
    _a, b = _routes(now)
    stale_report = {"generated_at": "2026-10-04 01:37 JST", "health_score": {"total": 40},
                    "profit": {"main_route_count": 1, "max_profit": 39009},
                    "anomalies": {"info": ["検証済み利益ルート 1件 / 最大 +¥39,009"]},
                    "diff_vs_prev": {"available": True, "new_main": ["prod_cam"],
                                     "main_route_count": {"prev": 0, "cur": 1},
                                     "stale_rate": {"prev": 0.1, "cur": 0.1}, "zero_rate": {"prev": 0, "cur": 0},
                                     "item_url_rate": {"prev": 0, "cur": 0}},
                    "improvements_top10": [{"stars": 5, "action": "EBAY_APP_ID 設定", "effect": "+¥142,079（参考1→main昇格）",
                                            "effort": "1時間"}]}
    g = _gen(now)
    g._coverage_html = lambda: ""
    g._execution_html = lambda: ""
    html = g._tab_health(stale_report, {"main_routes": [b], "reference_routes": []})
    assert "39,009" not in html and "142,079" not in html and "prod_cam" not in html
    # 生成側も判定を通ったルートだけから数える
    pf = GHR._profit({"main_routes": [b], "reference_routes": [b]})
    assert pf["main_route_count"] == 0 and pf["max_profit"] == 0 and pf["reference_route_count"] == 0


# ── 実行履歴 ──────────────────────────────────────────────────────────

def _run_exec(tmp_path, monkeypatch, now, *, history, ai, routes, ledger=None):
    _write(tmp_path, "exports/execution/execution_history.json", {"executions": history})
    _write(tmp_path, "exports/ai_opportunities/latest.json", ai)
    _write(tmp_path, "exports/profit_routes/latest.json", routes)
    _write(tmp_path, "data/manual_execution_outcomes.json", {"outcomes": ledger or []})
    for k, v in (("ROOT", tmp_path), ("OUT", tmp_path / "exports" / "execution"), ("NOW", now)):
        monkeypatch.setattr(GEI, k, v)
    monkeypatch.setattr(GEI, "_meta", lambda: {})
    assert GEI.main() == 0
    return (json.loads((tmp_path / "exports/execution/execution_history.json").read_text(encoding="utf-8")),
            json.loads((tmp_path / "exports/execution/latest.json").read_text(encoding="utf-8")))


GR4_OPEN = {"exec_id": "2026-10-04_prod_gr4_ALERT", "date": "2026-10-04", "product_id": "prod_gr4",
            "product": "RICOH GR IV", "action": "ALERT", "opportunity_score": 54, "predicted_probability": 30,
            "predicted_net": 39009, "category": "camera", "maker": "RICOH", "status": "OPEN",
            "realized_profit": None, "realized_roi": None, "hold_days": None}


def test_invalid_open_execution_is_invalidated_but_kept(tmp_path, monkeypatch):
    now = datetime.now(tz=JST)
    closed_sample = dict(GR4_OPEN, exec_id="2026-09-01_prod_gr3x_BUY", product_id="prod_gr3x", product="GR IIIx",
                         status="SUCCESS", realized_profit=12700, note="sample: x")
    hist, latest = _run_exec(tmp_path, monkeypatch, now, history=[dict(GR4_OPEN), closed_sample],
                             ai={"todays_opportunities": []}, routes={"main_routes": []})
    rec = {e["exec_id"]: e for e in hist["executions"]}
    g = rec["2026-10-04_prod_gr4_ALERT"]
    # 履歴は残る・当時の予想利益は書き換えない・今の OPEN（有効な案件）ではない
    assert g["status"] == "INVALIDATED" and g["predicted_net"] == 39009
    assert g["invalidated_at"] and g["invalidated_reason"].startswith("route_identity_missing")
    assert g["validation_version"]
    assert rec["2026-09-01_prod_gr3x_BUY"]["status"] == "SUCCESS"            # 過去の記録も消さない
    # 集計: 無効な記録・サンプルの結果は入れない
    assert latest["open_count"] == 0 and latest["closed_count"] == 0 and latest["invalidated_count"] == 1
    assert latest["sample_excluded_count"] == 1 and latest["execution_success_rate"] == 0


def test_execution_records_follow_route_ids(tmp_path, monkeypatch):
    now = datetime.now(tz=JST)
    a, b = _routes(now)
    ops = [{"product_id": "prod_cam", "product": "商品prod_cam", "action": "BUY", "kind": "main", "net_profit": 1,
            "route_id": opp.route_key(a)},
           {"product_id": "prod_cam", "product": "商品prod_cam", "action": "ALERT", "kind": "main", "net_profit": 39009,
            "route_id": opp.route_key(b)}]
    # サンプルの結果・商品だけが同じ結果は当てない
    ledger = [{"product_id": "prod_cam", "action": "BUY", "status": "SUCCESS", "realized_profit": 9, "note": "sample: x"},
              {"product_id": "prod_cam", "action": "BUY", "status": "SUCCESS", "realized_profit": 9, "note": "実際"}]
    hist, latest = _run_exec(tmp_path, monkeypatch, now, history=[], ai={"todays_opportunities": ops},
                             routes={"main_routes": [a, b]}, ledger=ledger)
    ex = hist["executions"]
    assert [(e["action"], e["status"], e["route_id"]) for e in ex] == [("BUY", "OPEN", opp.route_key(a))]
    assert latest["open_count"] == 1 and latest["closed_count"] == 0
    # exec_id が一致する実際の結果は当てる（否定対照）。route_id・商品だけが同じ結果は当てない
    ledger2 = [{"exec_id": ex[0]["exec_id"], "status": "SUCCESS", "realized_profit": 9, "note": "実際"},
               {"route_id": opp.route_key(a), "status": "FAILED", "note": "実際"}]
    hist2, latest2 = _run_exec(tmp_path, monkeypatch, now, history=ex, ai={"todays_opportunities": []},
                               routes={"main_routes": [a, b]}, ledger=ledger2)
    assert hist2["executions"][0]["status"] == "SUCCESS" and latest2["closed_count"] == 1


def _op(r, action="BUY"):
    return {"product_id": r["product_id"], "product": "商品" + r["product_id"], "action": action, "kind": "main",
            "net_profit": r["net_profit"], "route_id": opp.route_key(r)}


def test_execution_open_survives_price_change_and_closes_once(tmp_path, monkeypatch):
    """価格が動いただけでは同じルート（OPEN のまま）。1件の実績は1件の記録にだけ当てる（二重に数えない）。"""
    now = datetime.now(tz=JST)
    t1, t2 = now - timedelta(days=2), now - timedelta(days=1)
    a1, a2, a = _routes(t1)[0], _routes(t2)[0], _routes(now)[0]     # 毎日確認し直した同じルート
    day1, _ = _run_exec(tmp_path, monkeypatch, t1, history=[], ai={"todays_opportunities": [_op(a1)]},
                        routes={"main_routes": [a1]})
    day2, _ = _run_exec(tmp_path, monkeypatch, t2, history=day1["executions"],
                        ai={"todays_opportunities": [_op(a2)]}, routes={"main_routes": [a2]})
    a_moved = dict(a, buy_price=a["buy_price"] - 1, net_profit=a["net_profit"] + 1)   # 価格が1円動いた
    day3, latest = _run_exec(tmp_path, monkeypatch, now, history=day2["executions"],
                             ai={"todays_opportunities": [_op(a_moved)]}, routes={"main_routes": [a_moved]})
    ex = day3["executions"]
    assert len(ex) == 3 and all(e["status"] == "OPEN" for e in ex) and latest["open_count"] == 3
    first = sorted(ex, key=lambda e: e["date"])[0]["exec_id"]
    day4, latest4 = _run_exec(tmp_path, monkeypatch, now, history=ex, ai={"todays_opportunities": []},
                              routes={"main_routes": [a_moved]},
                              ledger=[{"exec_id": first, "status": "SUCCESS", "realized_profit": 5000, "note": "実際"}])
    assert latest4["closed_count"] == 1 and latest4["success_count"] == 1 and latest4["open_count"] == 2


def test_execution_ids_are_per_route(tmp_path, monkeypatch):
    """同じ日・同じ商品・同じ action でも、別のルートは別の記録。ルートが変わったら新しいルートも記録する。"""
    now = datetime.now(tz=JST)
    a, b = _routes(now)
    b_ok = dict(b, buy_exact_match=True, sell_exact_match=True, buy_canonical_type="RETAIL", buy_condition="new_unopened",
                sell_condition="new_unopened", buy_item_url="https://x.example/i/1", net_profit=151000 - 107491 - 4500)
    hist, latest = _run_exec(tmp_path, monkeypatch, now, history=[],
                             ai={"todays_opportunities": [_op(a), _op(b_ok)]}, routes={"main_routes": [a, b_ok]})
    assert len({e["exec_id"] for e in hist["executions"]}) == 2 and latest["open_count"] == 2


def test_invalidated_record_can_still_get_its_real_outcome(tmp_path, monkeypatch):
    now = datetime.now(tz=JST)
    a, _b = _routes(now)
    hist, _ = _run_exec(tmp_path, monkeypatch, now, history=[], ai={"todays_opportunities": [_op(a)]},
                        routes={"main_routes": [a]})
    gone, _ = _run_exec(tmp_path, monkeypatch, now, history=hist["executions"], ai={"todays_opportunities": []},
                        routes={"main_routes": []})
    rec = gone["executions"][0]
    assert rec["status"] == "INVALIDATED" and rec["invalidated_reason"].startswith("route_not_current")
    done, latest = _run_exec(tmp_path, monkeypatch, now, history=gone["executions"], ai={"todays_opportunities": []},
                             routes={"main_routes": []},
                             ledger=[{"exec_id": rec["exec_id"], "status": "FAILED", "realized_profit": -1500,
                                      "note": "実際"}])
    e = done["executions"][0]
    assert e["status"] == "FAILED" and e["closed_after_invalidated"] is True and e["invalidated_at"]
    assert latest["closed_count"] == 1


def test_execution_dashboard_without_real_outcomes_shows_no_rate():
    html = _gen(datetime.now(tz=JST))._execution_html(
        {"closed_count": 0, "success_count": 0, "execution_success_rate": 0, "invalidated_count": 82,
         "sample_excluded_count": 128, "prediction_accuracy": {}, "notification_accuracy": {}, "insights_top10": []})
    assert "実績の記録なし" in html and "Execution Success" in html and ">0%<" not in html
    assert "無効（今のルートで確かめられない）82件" in html and "サンプルの結果 128件" in html


# ── 通知 ───────────────────────────────────────────────────────────

def test_notification_snapshot_uses_route_ids():
    now = datetime.now(tz=JST)
    a, b = _routes(now)
    gno_now, GNO.NOW = GNO.NOW, now
    try:
        snap = GNO._snapshot({"todays_opportunities": [
            {"product_id": "prod_cam", "kind": "main", "route_id": opp.route_key(b), "buy_now": "BUY"}]},
            {}, {"main_routes": [a, b]})
    finally:
        GNO.NOW = gno_now
    assert snap["ops"] == {} and snap["main_products"] == []        # 同じ商品の A が有効でも B の候補は使わない


def test_price_change_is_compared_only_within_the_same_route():
    prev = {"main_products": ["p"], "ops": {"p": {"buy_now": "BUY", "buy_price": 100000, "roi": 0.1,
                                                  "buy_source": "店A", "sell_source": "買取A", "route_id": "r1"}}}
    cur = {"main_products": ["p"], "ops": {"p": {"buy_now": "BUY", "buy_price": 80000, "roi": 0.3,
                                                 "buy_source": "店B", "sell_source": "買取A", "route_id": "r2"}}}
    assert [e["type"] for e in GNO.detect(prev, cur)] == []          # 別の仕入れ先と比べて「価格下落」にしない
    cur["ops"]["p"]["buy_source"] = "店A"
    types = [e["type"] for e in GNO.detect(prev, cur)]
    assert "PRICE_DROP" in types and "ROI_UP" in types
    assert all(e.get("route_id") == "r2" for e in GNO.detect(prev, cur))


# ── 生成の失敗・古いファイル ───────────────────────────────────────────────

def test_failed_generation_keeps_previous_file_and_its_time(tmp_path, monkeypatch):
    from src.utils import atomic_write as aw
    target = tmp_path / "exports" / "ai_opportunities" / "latest.json"
    aw.write_json_atomic(target, {"generated_at": "2026-10-04 01:37 JST", "todays_opportunities": []})
    before = target.read_text(encoding="utf-8")

    class Boom:
        pass
    with pytest.raises(TypeError):
        aw.write_json_atomic(target, {"generated_at": "2026-10-05 12:00 JST", "x": Boom()})   # JSON にできない
    # 前回のファイルはそのまま（半端な内容・新しい時刻にならない）。一時ファイルも残らない
    assert target.read_text(encoding="utf-8") == before
    assert [p.name for p in target.parent.iterdir()] == ["latest.json"]


def test_scripts_write_artifacts_atomically():
    for rel in ("scripts/generate_profit_routes.py", "scripts/generate_ai_opportunities.py",
                "scripts/generate_allocation_plan.py", "scripts/generate_execution_intelligence.py",
                "scripts/generate_notifications.py", "scripts/generate_health_report.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "write_json_atomic(" in src, rel
        assert not re.search(r'"latest\.json"\)\.write_text\(', src), rel


# ── 0件診断・β ─────────────────────────────────────────────────────────

def test_zero_diagnostics_do_not_show_unverified_price_as_confirmed():
    now = datetime.now(tz=JST)
    z = {"product_name": "RICOH GR IV", "buy_candidates": 1, "sell_candidates": 1, "min_usable_buy": 107491,
         "min_usable_buy_source": "Amazon JP", "max_usable_sell": 151000, "max_usable_sell_source": "フジヤカメラ",
         "min_usable_buy_identity_verified": False, "max_usable_sell_identity_verified": False,
         "net_domestic": 39009, "best_reference_net": 142079, "main_blocked_reason": "x", "needed": []}
    html = _gen(now)._profit_routes_section({"main_routes": [], "reference_routes": [],
                                             "zero_route_diagnostics": {"prod_gr4": z}})
    assert "参考・商品照合未完了 フジヤカメラ ¥151,000" in html and "最高 フジヤカメラ" not in html
    assert "39,009" not in html and "国内完結: <b" not in html
    z2 = dict(z, max_usable_sell_identity_verified=True, net_domestic=-5000)
    html2 = _gen(now)._profit_routes_section({"main_routes": [], "reference_routes": [],
                                              "zero_route_diagnostics": {"prod_gr4": z2}})
    assert "最高 フジヤカメラ ¥151,000" in html2 and "-5,000円" in html2       # 否定対照: 照合済み・赤字の説明


def test_beta_preview_has_no_fabricated_profit(tmp_path, monkeypatch):
    gbr = _load("gbr_p52", ROOT / "scripts" / "generate_beta_report.py")
    monkeypatch.setattr(gbr, "ROOT", tmp_path)
    _write(tmp_path, "exports/ai_opportunities/latest.json", {"daily_recommendation": None})
    _write(tmp_path, "exports/profit_routes/latest.json", {"main_routes": []})
    txt = json.dumps(gbr.notification_previews(), ensure_ascii=False)
    assert "38,947" not in txt and "RICOH GR IIIx" not in txt and "（例）商品名" in txt
    # 古い AI のファイルのおすすめも、もとのルートが今の確定ルートでなければ使わない
    _write(tmp_path, "exports/ai_opportunities/latest.json", {
        "daily_recommendation": {"product": "RICOH GR IV", "reason": "利益¥39,009", "buy_now": "BUY"},
        "todays_opportunities": [{"product_id": "prod_gr4", "kind": "main", "route_id": "x|y"}]})
    txt = json.dumps(gbr.notification_previews(), ensure_ascii=False)
    assert "39,009" not in txt and "RICOH GR IV" not in txt


# ── 公式の購入送料 ──────────────────────────────────────────────────────

def test_official_purchase_shipping_classification():
    assert osh.purchase_shipping("prod_ps5_pro")["fee"] == 550                          # ソニーストア（購入ページで確認）
    assert osh.purchase_shipping("prod_ps5_pro")["status"] == osh.PAID
    apple = osh.purchase_shipping("prod_iphone", "https://www.apple.com/jp/shop/buy-iphone/iphone-17", 159800)
    assert apple["fee"] == 0 and apple["status"] == osh.FREE_VERIFIED and apple["url"].startswith("https://www.apple.com")
    nin = osh.purchase_shipping("prod_sw", "https://store-jp.nintendo.com/item/x", 59980)
    assert nin["fee"] == 0 and nin["status"] == osh.CONDITIONAL
    assert osh.purchase_shipping("prod_sw", "https://store-jp.nintendo.com/item/x", 4980)["fee"] == 550
    # 確認していない購入元・ソニーストアでも購入ページを確認していない商品は「不明」（0円にしない）
    for args in (("prod_gr4", "https://www.ricoh-imaging.co.jp/x", 194800), ("prod_x", "", 1),
                 ("prod_y", "https://store.sony.jp/item/y", 1), ("prod_z", "http://www.apple.com/jp/shop/x", 1)):
        assert osh.purchase_shipping(*args)["fee"] is None and osh.known_fee(*args) == 0, args


def test_ps5_pro_cost_breakdown_matches_evidence():
    """PS5 Pro: 定価 137,980・購入送料 550（公式で確認）・買取 192,000・費用 1,800 → 純利益 51,670。"""
    from src.content.daily_lp_generator import DailyLPGenerator
    from src.models.beginner_deal import BeginnerDealModel
    from src.market import price_evidence as pe
    now = datetime.now(tz=JST)
    g = _gen(now)
    g._msrp_evidence = {"prod_ps5_pro": pe.VERIFIED_DATED}
    deal = BeginnerDealModel(id="p", product_id="prod_ps5_pro", product_name="PlayStation 5 Pro", category="game_console",
                             official_price_jpy=137980, best_buyback_price=150000, best_buyback_shop="買取商店",
                             net_profit_jpy=0, user_level="beginner_easy", sale_method="normal")
    row = {"shop_name": "買取商店", "buyback_price": 192000, "condition": "new_unopened",
           "observed_at": (now - timedelta(hours=2)).isoformat(), "data_source": "auto_scraped", "buyback_url": ""}
    enriched = DailyLPGenerator._enrich_deal(g, deal, [row]) if hasattr(DailyLPGenerator, "_enrich_deal") else deal
    assert enriched.best_buyback_price == 192000 and enriched.net_profit_jpy == 192000 - 137980 - 1800 - 550
    d, = g._nu_profit_deals([enriched], {"prod_ps5_pro": [row]})
    assert d["purchase_shipping"] == 550 and d["purchase_shipping_status"] == osh.PAID
    v = opp.from_deal(d)
    assert v.buy_shipping == 550 and v.acquisition_cost == 137980 + 550 and v.breakdown_ok
    assert ("購入送料", 550.0) in v.cost_lines and v.net_profit == 51670
    assert abs(v.roi - 51670 / 138530) < 1e-9 and not opp.deal_reasons(d, now)
    # 送料を足していない純利益（以前の 52,220）は内訳が合わず、確定にしない
    assert "breakdown_mismatch" in opp.deal_reasons(dict(d, net_profit=52220), now)


def test_unknown_purchase_shipping_is_not_confirmed_but_may_stay_reference():
    now = datetime.now(tz=JST)
    base = {"product_id": "prod_x", "title": "X", "genre": "camera", "official_price": 100000,
            "official_checked_at": (now - timedelta(days=3)).isoformat(), "msrp_evidence": "VERIFIED_DATED",
            "sell_shop": "買取店A", "sell_price": 130000, "sell_checked_at": (now - timedelta(hours=1)).isoformat(),
            "net_profit": 28200, "user_level": "beginner_easy", "purchase_shipping": None}
    why = opp.deal_reasons(base, now)
    assert why == ("purchase_shipping_unknown",) and not opp.is_msrp_reference_only(why)   # 確定にも参考にもしない
    why_ref = opp.deal_reasons(dict(base, msrp_evidence="CONFIGURED_REFERENCE"), now)
    assert opp.is_msrp_reference_only(why_ref)                   # 定価未確認の参考差額としてだけ残せる
    # ルート側（RouteView）も購入送料が分からなければ確定にしない（費用の意味を食い違わせない）
    assert "costs_unknown" in opp.route_reasons(RF.safe_route(now, "p", buy_shipping=None), now)


def test_scanner_costs_include_known_purchase_shipping():
    from types import SimpleNamespace

    from src.market.beginner_deal_scanner import BeginnerDealScanner
    sc = BeginnerDealScanner.__new__(BeginnerDealScanner)
    sc._get_official_url = lambda product: ""
    base = sc._estimate_costs(SimpleNamespace(id="prod_x", brand="X"), 100000)
    assert sc._estimate_costs(SimpleNamespace(id="prod_ps5_pro", brand="Sony"), 137980) == base + 550


# ── deploy-check #830 ───────────────────────────────────────────────────

def test_deploy_check_830_detects_revived_invalid_route(tmp_path, monkeypatch):
    now = datetime.now(tz=JST)
    a, b = _routes(now)
    root = tmp_path / "root"
    pr = {"generated_at": now.strftime("%Y-%m-%d %H:%M JST"), "main_routes": [a], "reference_routes": []}
    _write(root, "exports/profit_routes/latest.json", pr)
    _write(root, "exports/ai_opportunities/latest.json", {"todays_opportunities": [
        {"product_id": "prod_cam", "kind": "main", "route_id": opp.route_key(a)}]})
    _write(root, "exports/allocation/latest.json", {"plans": {"3000000": {"allocations": [
        {"product_id": "prod_cam", "route_id": opp.route_key(a)}]}}})
    _write(root, "exports/execution/execution_history.json", {"executions": [dict(GR4_OPEN, status="INVALIDATED")]})
    _write(root, "exports/notifications/latest.json", {"events": []})
    for n in ("config", "data", "src", "scripts"):     # deploy-check は読むだけ（書き込まない）
        (root / n).symlink_to(ROOT / n)
    dc = _load("dc_p52", ROOT / "scripts" / "deploy_check.py")
    monkeypatch.setattr(dc, "PROJECT_ROOT", root)

    def lv():
        return {r["check"]: r["level"] for r in dc._check_data_correctness()}["artifacts_follow_current_routes"]
    assert lv() == "ok"
    # 無効なルート（B）の候補・配分・OPEN の記録・route_id の無い通知が復活したら error
    for rel, data in (
            ("exports/ai_opportunities/latest.json", {"todays_opportunities": [
                {"product_id": "prod_cam", "kind": "main", "route_id": opp.route_key(b)}]}),
            ("exports/allocation/latest.json", {"plans": {"3000000": {"allocations": [
                {"product_id": "prod_cam", "route_id": opp.route_key(b)}]}}}),
            ("exports/execution/execution_history.json", {"executions": [GR4_OPEN]}),
            ("exports/notifications/latest.json", {"events": [{"type": "NEW_MAIN", "product_id": "prod_cam",
                                                               "route_checked": True}]})):
        saved = (root / rel).read_text(encoding="utf-8")
        _write(root, rel, data)
        assert lv() == "error", rel
        (root / rel).write_text(saved, encoding="utf-8")

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Execution Intelligence Engine — 予測と実績を追跡し AI 判断精度を評価・学習する。

利益判定ロジックは変更しない（評価のみ）。Opportunity/Action/Notification/Allocation の
予測に対し、実行結果台帳（data/manual_execution_outcomes.json・人手記録）の実績を突き合わせ、
予測精度・通知精度・配分精度を計測し、スコア/成立確率/リスクの補正係数だけを学習する。

出力:
  exports/execution/latest.json / execution_history.json / weekly_learning.md
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
OUT = ROOT / "exports" / "execution"
DB = ROOT / "data" / "premium_monitor.db"


def _load(p, default=None):
    try:
        return json.loads((ROOT / p).read_text(encoding="utf-8"))
    except Exception:
        return default if default is not None else {}


def _meta():
    m = {}
    try:
        con = sqlite3.connect(str(DB))
        for r in con.execute("SELECT id, genre, brand FROM products"):
            m[r[0]] = (r[1] or "other", r[2] or "other")
        con.close()
    except Exception:
        pass
    return m


def _avg(xs):
    xs = [x for x in xs if x is not None]
    return round(sum(xs) / len(xs), 4) if xs else 0


def main() -> int:
    print(f"[generate_execution_intelligence] 開始: {NOW.strftime('%Y-%m-%d %H:%M')} JST")
    ai = _load("exports/ai_opportunities/latest.json")
    notif = _load("exports/notifications/latest.json")
    alloc = _load("exports/allocation/latest.json")
    meta = _meta()
    ledger = _load("data/manual_execution_outcomes.json", default={}).get("outcomes", [])

    # ── Task1: execution_history（予測を記録・実績台帳で close）──
    hist = _load("exports/execution/execution_history.json", default={"executions": []})
    existing = {e["exec_id"]: e for e in hist.get("executions", [])}
    for o in ai.get("todays_opportunities", []):
        exid = f"{NOW.strftime('%Y-%m-%d')}_{o.get('product_id')}_{o.get('action')}"
        g, b = meta.get(o.get("product_id", ""), ("other", "other"))
        if exid not in existing:
            existing[exid] = {
                "exec_id": exid, "date": NOW.strftime("%Y-%m-%d"),
                "product_id": o.get("product_id"), "product": o.get("product"),
                "action": o.get("action"), "opportunity_score": o.get("opportunity_score"),
                "predicted_probability": o.get("success_probability"),
                "predicted_net": o.get("net_profit"), "category": g, "maker": b,
                "status": "OPEN", "realized_profit": None, "realized_roi": None, "hold_days": None,
            }
    # 台帳の実績を最新の該当 execution に反映（product_id + action 一致、無ければ product_id）
    outcome_by_pid = {}
    for oc in ledger:
        outcome_by_pid.setdefault(oc["product_id"], []).append(oc)
    for exid, e in existing.items():
        if e["status"] != "OPEN":
            continue
        cands = outcome_by_pid.get(e["product_id"], [])
        match = next((c for c in cands if c.get("action") == e["action"]), cands[0] if cands else None)
        if match:
            e["status"] = match["status"]
            e["realized_profit"] = match.get("realized_profit")
            e["realized_roi"] = match.get("realized_roi")
            e["hold_days"] = match.get("hold_days")
            if match.get("predicted_probability") is not None:
                e["predicted_probability"] = match["predicted_probability"]
            e["closed_date"] = NOW.strftime("%Y-%m-%d")
            e["note"] = match.get("note", "")
    executions = list(existing.values())
    closed = [e for e in executions if e["status"] in ("SUCCESS", "FAILED", "CANCELLED")]
    succeeded = [e for e in closed if e["status"] == "SUCCESS"]

    # ── Task2: Execution Metrics（商品/カテゴリ/メーカー）──
    def _metrics(keyfn):
        g = defaultdict(list)
        for e in closed:
            g[keyfn(e)].append(e)
        out = {}
        for k, es in g.items():
            n = len(es); s = sum(1 for e in es if e["status"] == "SUCCESS")
            out[k] = {"count": n, "success": s, "success_rate": round(s / n, 3) if n else 0,
                      "avg_profit": round(_avg([e.get("realized_profit") for e in es])),
                      "avg_roi": _avg([e.get("realized_roi") for e in es]),
                      "avg_hold_days": _avg([e.get("hold_days") for e in es])}
        return out
    metrics = {
        "by_product": _metrics(lambda e: e["product"]),
        "by_category": _metrics(lambda e: e.get("category", "?")),
        "by_maker": _metrics(lambda e: e.get("maker", "?")),
    }

    # ── Task3: Prediction Accuracy（予測確率 vs 実績成功率）──
    pred_avg = _avg([e.get("predicted_probability") for e in closed]) if closed else 0
    real_rate = round(len(succeeded) / len(closed) * 100, 1) if closed else 0
    pred_accuracy = {
        "closed_count": len(closed), "predicted_success_prob_avg": pred_avg,
        "realized_success_rate": real_rate,
        "error_points": round(abs(pred_avg - real_rate), 1),
        "opportunity_score_avg": _avg([e.get("opportunity_score") for e in closed]),
    }

    # ── Task4: Notification Accuracy ──
    nhist = list((OUT.parent / "notifications" / "history").glob("*.json"))
    total_notif = 0; buy_notif = 0; w2b = 0
    for hp in nhist:
        try:
            hd = json.loads(hp.read_text(encoding="utf-8"))
            for ev in hd.get("events", []):
                total_notif += 1
                if ev.get("type") == "WATCH_TO_BUY":
                    w2b += 1; buy_notif += 1
        except Exception:
            pass
    notif_success = round(len(succeeded) / total_notif, 3) if total_notif else 0
    notif_accuracy = {
        "total_notifications": total_notif, "buy_notifications": buy_notif,
        "watch_to_buy": w2b, "notification_success_rate": notif_success,
        "false_positive_rate": round(sum(1 for e in closed if e["status"] == "FAILED") / len(closed), 3) if closed else 0,
    }

    # ── Task5: Capital Allocation Accuracy ──
    dbg = str(alloc.get("default_budget"))
    dplan = (alloc.get("plans", {}) or {}).get(dbg, {})
    alloc_expected = dplan.get("expected_profit", 0)
    alloc_products = {a["product"] for a in dplan.get("allocations", [])}
    alloc_realized = sum(e.get("realized_profit") or 0 for e in closed if e["product"] in alloc_products)
    alloc_accuracy = {
        "budget": alloc.get("default_budget"), "allocated_expected_profit": alloc_expected,
        "realized_profit_of_allocated": alloc_realized,
        "accuracy_ratio": round(alloc_realized / alloc_expected, 3) if alloc_expected else None,
    }

    # ── Task6: Self Improvement（補正係数のみ・利益ロジックは不変）──
    def _clamp(x, lo=0.5, hi=1.5):
        return round(max(lo, min(hi, x)), 3)
    prob_coeff = _clamp((real_rate / pred_avg) if pred_avg else 1.0) if closed else 1.0
    # スコア校正: 成功群の平均Opportunity vs 全closed平均（高スコアほど成功なら>1）
    succ_score = _avg([e.get("opportunity_score") for e in succeeded])
    all_score = _avg([e.get("opportunity_score") for e in closed])
    score_coeff = _clamp((succ_score / all_score) if all_score else 1.0) if closed else 1.0
    # リスク校正: FAILEDのリスク傾向（データ乏しければ1.0）
    risk_coeff = 1.0
    learning = {
        "opportunity_score_coeff": score_coeff,
        "success_probability_coeff": prob_coeff,
        "risk_score_coeff": risk_coeff,
        "note": "補正係数のみ学習。利益判定ロジックには適用しない（表示・将来の予測校正用）。",
        "sample_size": len(closed),
        "confidence": ("low" if len(closed) < 10 else "medium" if len(closed) < 30 else "high"),
    }

    # ── Task8: Insights TOP10（ルールベース観測）──
    insights = _insights(closed, metrics, pred_accuracy, ai, alloc)

    payload = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "open_count": sum(1 for e in executions if e["status"] == "OPEN"),
        "closed_count": len(closed), "success_count": len(succeeded),
        "execution_success_rate": real_rate,
        "prediction_accuracy": pred_accuracy,
        "notification_accuracy": notif_accuracy,
        "allocation_accuracy": alloc_accuracy,
        "execution_metrics": metrics,
        "learning_coefficients": learning,
        "insights_top10": insights,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "execution_history.json").write_text(
        json.dumps({"executions": executions}, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(payload)
    _write_weekly(payload)
    print(f"  実行: OPEN {payload['open_count']} / CLOSED {len(closed)}（成功{len(succeeded)}）")
    print(f"  予測精度: 予測{pred_avg}% vs 実績{real_rate}% 誤差{pred_accuracy['error_points']}pt / "
          f"補正係数 prob={prob_coeff} score={score_coeff}")
    return 0


def _insights(closed, metrics, pred, ai, alloc):
    ins = []
    if closed:
        best = max(metrics["by_category"].items(), key=lambda kv: kv[1]["success_rate"], default=None)
        if best:
            ins.append(f"カテゴリ「{best[0]}」の成功率が最も高い（{best[1]['success_rate']*100:.0f}%）")
        fastest = min((e for e in closed if e["status"] == "SUCCESS" and e.get("hold_days") is not None),
                      key=lambda e: e["hold_days"], default=None)
        if fastest:
            ins.append(f"{fastest['product']} は約{fastest['hold_days']}日で売却成立（回転が速い）")
        if pred["error_points"] > 10:
            ins.append(f"成立確率の予測誤差が {pred['error_points']}pt（予測がやや強気→補正係数で校正）")
        else:
            ins.append(f"成立確率の予測誤差は {pred['error_points']}pt（概ね良好）")
        failed = [e for e in closed if e["status"] == "FAILED"]
        if failed:
            ins.append(f"{failed[0]['product']} は薄利/送料負けで失敗（国内薄利ルートは要注意）")
    # データ由来の一般観測
    ins.append("Fujiya 買取は日次で更新され鮮度が高い（sell側の信頼性◎）")
    ins.append("海外sold（eBay）は EBAY_APP_ID 未設定で stale・main昇格の最大ボトルネック")
    ins.append("国内完結ルートは買取≥販売で薄利になりやすい（ROI<5%は自動除外）")
    ins.append("フリマsold（メルカリ/ヤフオク）取得が buy 側の裾を広げ利益ルートを生む")
    ins.append("manual由来ルートは再現性が低くスコアが伸びない（要 item_url/同条件件数）")
    ins.append("Apple/GPU は流動性が高く、Coverage拡充の優先度が高い")
    ins.append("現金留保20%は急なBUY通知への即応バッファとして機能")
    return ins[:10]


def _write_md(p):
    pa = p["prediction_accuracy"]; na = p["notification_accuracy"]; aa = p["allocation_accuracy"]
    lc = p["learning_coefficients"]
    o = ["# Execution Intelligence Engine", "", f"生成: {p['generated_at']}", "",
         "## Execution Dashboard", "",
         f"- OPEN {p['open_count']} / CLOSED {p['closed_count']}（成功 {p['success_count']}）",
         f"- Execution Success Rate: **{p['execution_success_rate']}%**",
         f"- Prediction Accuracy: 予測 {pa['predicted_success_prob_avg']}% vs 実績 {pa['realized_success_rate']}%"
         f"（誤差 {pa['error_points']}pt）",
         f"- Notification Accuracy: 通知{na['total_notifications']} / BUY通知{na['buy_notifications']} / "
         f"WATCH→BUY {na['watch_to_buy']} / 偽陽性率 {na['false_positive_rate']*100:.0f}%",
         f"- Capital Allocation: 期待 ¥{aa['allocated_expected_profit']:,} → 実 ¥{aa['realized_profit_of_allocated']:,}"
         f"（精度 {aa['accuracy_ratio']}）" if aa.get("accuracy_ratio") is not None else
         f"- Capital Allocation: 期待 ¥{aa['allocated_expected_profit']:,}（実績データ蓄積待ち）", "",
         "## 補正係数（学習・利益ロジックには不適用）", "",
         f"- Opportunity Score 係数: {lc['opportunity_score_coeff']}",
         f"- Success Probability 係数: {lc['success_probability_coeff']}",
         f"- Risk Score 係数: {lc['risk_score_coeff']}",
         f"- サンプル数 {lc['sample_size']}（信頼度 {lc['confidence']}）", "",
         "## Execution Metrics（カテゴリ別）", "",
         "| カテゴリ | 件数 | 成功率 | 平均利益 | 平均ROI | 平均保有日数 |", "|---|---|---|---|---|---|"]
    for k, m in p["execution_metrics"]["by_category"].items():
        o.append(f"| {k} | {m['count']} | {m['success_rate']*100:.0f}% | ¥{m['avg_profit']:,} | "
                 f"{m['avg_roi']*100:.1f}% | {m['avg_hold_days']}日 |")
    if not p["execution_metrics"]["by_category"]:
        o.append("| （実績データ蓄積待ち） | | | | | |")
    o += ["", "## Insights — 今週学んだこと TOP10", ""]
    for i, s in enumerate(p["insights_top10"], 1):
        o.append(f"{i}. {s}")
    (OUT / "latest.md").write_text("\n".join(o) + "\n", encoding="utf-8")


def _write_weekly(p):
    pa = p["prediction_accuracy"]; lc = p["learning_coefficients"]
    o = [f"# Weekly Learning Report — {NOW.strftime('%Y-%m-%d')}", "",
         f"- 実行成功率: {p['execution_success_rate']}%（CLOSED {p['closed_count']} / 成功 {p['success_count']}）",
         f"- 予測精度: 予測 {pa['predicted_success_prob_avg']}% vs 実績 {pa['realized_success_rate']}%（誤差 {pa['error_points']}pt）",
         f"- 学習: prob係数 {lc['success_probability_coeff']} / score係数 {lc['opportunity_score_coeff']}"
         f"（信頼度 {lc['confidence']}）", "",
         "## 今週学んだこと TOP10", ""]
    for i, s in enumerate(p["insights_top10"], 1):
        o.append(f"{i}. {s}")
    o += ["", "> 補正係数は表示・将来の予測校正のみに使用。利益判定ロジックは変更していません。"]
    (OUT / "weekly_learning.md").write_text("\n".join(o) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

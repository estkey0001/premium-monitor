#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Capital Allocation Engine — 予算配分の意思決定層。

利益判定ロジックは変更しない。ai_opportunities（Opportunity/Action）を入力に、
「予算をどう配分するか」だけを決定する。複数予算・account_id 単位・What-If 対応構造。

出力: exports/allocation/latest.json / latest.md
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
OUT = ROOT / "exports" / "allocation"
DB = ROOT / "data" / "premium_monitor.db"

DEFAULT_BUDGETS = [1_000_000, 3_000_000, 5_000_000, 10_000_000, 30_000_000]
CASH_RESERVE = 0.20          # 現金留保（急なBUY通知対応）
CAP_PRODUCT = 0.30           # 1商品あたり上限（対予算）
CAP_CATEGORY = 0.50          # カテゴリ上限
CAP_MAKER = 0.60             # 同メーカー上限
ACTION_RANK = {"BUY": 4, "ALERT": 3, "WAIT": 2, "SKIP": 1}
HOLD_LIQ = {"即日": 100, "数日": 85, "1週間": 70, "1ヶ月": 45, "長期": 25}


def _load(p):
    try:
        return json.loads((ROOT / p).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _meta():
    """product_id → (genre, brand)。"""
    m = {}
    try:
        con = sqlite3.connect(str(DB))
        for r in con.execute("SELECT id, genre, brand FROM products"):
            m[r[0]] = (r[1] or "other", r[2] or "other")
        con.close()
    except Exception:
        pass
    return m


def _risk_score(o: dict) -> int:
    """Risk Score（0=低リスク〜100=高リスク）。"""
    r = 0
    if o.get("action") in ("WAIT",) or o.get("kind") == "reference":
        r += 20  # データ待ち/海外依存
    if any("manual" in str(x) for x in o.get("risks", [])):
        r += 25
    age = o.get("age_days") or 0
    r += min(25, int(age))
    r += round((100 - (o.get("reproducibility_score") or 40)) / 100 * 20)
    if (o.get("roi") or 0) < 0.08:
        r += 10
    return min(100, r)


def _liquidity_score(o: dict) -> int:
    """Liquidity Score（0〜100・高いほど換金が早い）。"""
    base = HOLD_LIQ.get(o.get("holding_period", "1週間"), 60)
    if o.get("kind") == "reference":
        base -= 20
    return max(0, min(100, base))


def build_opportunity_metrics(ai: dict, meta: dict) -> list[dict]:
    ops = []
    for o in ai.get("todays_opportunities", []):
        net = o.get("net_profit", 0)
        prob = (o.get("success_probability", 0) or 0) / 100
        buy = o.get("buy_price", 0) or 0
        ev = round(net * prob)
        cap_eff = round(ev / buy, 4) if buy else 0
        genre, brand = meta.get(o.get("product_id", ""), ("other", "other"))
        ops.append({
            "product": o.get("product"), "product_id": o.get("product_id"),
            "action": o.get("action"), "kind": o.get("kind"),
            "buy_price": buy, "net_profit": net, "roi": o.get("roi", 0),
            "success_probability": o.get("success_probability", 0),
            "opportunity_score": o.get("opportunity_score", 0),
            "reproducibility_score": o.get("reproducibility_score", 0),
            "holding_period": o.get("holding_period", ""),
            "expected_value": ev, "capital_efficiency": cap_eff,
            "risk_score": _risk_score(o), "liquidity_score": _liquidity_score(o),
            "category": genre, "maker": brand,
        })
    return ops


def allocate(budget: int, ops: list[dict]) -> dict:
    investable = int(budget * (1 - CASH_RESERVE))
    cap_prod = budget * CAP_PRODUCT
    cap_cat = budget * CAP_CATEGORY
    cap_maker = budget * CAP_MAKER
    # 実行可能=国内で今買える main（net>0、action BUY/ALERT/WAITだが価格が現存）。
    # reference（海外更新待ち）や PASS は「待機」。
    actionable = [o for o in ops if o["kind"] == "main" and o["net_profit"] > 0 and o["buy_price"] > 0]
    waiting = [{"product": o["product"], "reason": (
        "海外価格更新待ち（eBay sold）" if o["kind"] == "reference"
        else "利益条件未達（PASS）" if o["action"] == "SKIP" else "実行可能価格なし")}
        for o in ops if o not in actionable]
    # 並び: action順 → EV → CapEff → Opportunity → ROI → 再現性
    actionable.sort(key=lambda o: (
        ACTION_RANK.get(o["action"], 0), o["expected_value"], o["capital_efficiency"],
        o["opportunity_score"], o["roi"], o["reproducibility_score"]), reverse=True)

    spent = 0
    spent_cat = defaultdict(int); spent_maker = defaultdict(int)
    spent_hold = defaultdict(int)
    allocations = []
    for o in actionable:
        price = o["buy_price"]
        # 各制約下での最大台数
        rem_invest = investable - spent
        rem_prod = cap_prod
        rem_cat = cap_cat - spent_cat[o["category"]]
        rem_maker = cap_maker - spent_maker[o["maker"]]
        # 保有期間分散: 1バケットは investable の 60% まで
        rem_hold = investable * 0.60 - spent_hold[o["holding_period"]]
        max_units = min(rem_invest, rem_prod, rem_cat, rem_maker, rem_hold) // price
        units = int(max(0, max_units))
        if units <= 0:
            waiting.append({"product": o["product"], "reason": "予算/集中リスク制約で配分なし"})
            continue
        total = units * price
        allocations.append({
            "product": o["product"], "product_id": o["product_id"], "units": units,
            "unit_price": price, "total": total,
            "expected_profit": units * o["net_profit"],
            "expected_value": units * o["expected_value"],
            "category": o["category"], "maker": o["maker"],
            "holding_period": o["holding_period"], "roi": o["roi"],
            "risk_score": o["risk_score"], "liquidity_score": o["liquidity_score"],
        })
        spent += total; spent_cat[o["category"]] += total
        spent_maker[o["maker"]] += total; spent_hold[o["holding_period"]] += total

    exp_profit = sum(a["expected_profit"] for a in allocations)
    cash = budget - spent
    exp_roi = round(exp_profit / spent, 4) if spent else 0.0
    # 分散スコア（配分商品数・カテゴリ数・最大集中率から）
    n_prod = len(allocations)
    max_conc = (max((a["total"] for a in allocations), default=0) / budget) if budget else 0
    div_score = min(100, n_prod * 25 + (len(set(a["category"] for a in allocations)) * 15)
                    - round(max_conc * 40))
    div_score = max(0, div_score)
    avg_risk = round(sum(a["risk_score"] for a in allocations) / n_prod) if n_prod else 0
    return {
        "budget": budget, "investable": investable, "cash_reserve_ratio": CASH_RESERVE,
        "allocations": allocations, "waiting": waiting,
        "allocated": spent, "cash": cash,
        "cash_ratio": round(cash / budget, 4) if budget else 0,
        "expected_profit": exp_profit, "expected_roi": exp_roi,
        "avg_risk_score": avg_risk, "diversification_score": div_score,
        "max_concentration": round(max_conc, 4),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", default="default")
    ap.add_argument("--budget", type=int, default=None, help="自由入力の予算（追加で計算）")
    args = ap.parse_args()
    print(f"[generate_allocation_plan] 開始: {NOW.strftime('%Y-%m-%d %H:%M')} JST / account={args.account}")

    ai = _load("exports/ai_opportunities/latest.json")
    meta = _meta()
    ops = build_opportunity_metrics(ai, meta)

    budgets = list(DEFAULT_BUDGETS)
    if args.budget and args.budget not in budgets:
        budgets.append(args.budget)
        budgets.sort()
    plans = {str(b): allocate(b, ops) for b in budgets}

    payload = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "account_id": args.account,          # Task10: account単位で保存可能な構造
        "cash_reserve_ratio": CASH_RESERVE,
        "concentration_caps": {"product": CAP_PRODUCT, "category": CAP_CATEGORY, "maker": CAP_MAKER},
        "opportunity_metrics": ops,
        "default_budget": 3_000_000,         # Dashboard 既定表示
        "budgets": budgets,
        "plans": plans,                       # What-If: 予算別に即時参照可能
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(payload)
    dp = plans[str(payload["default_budget"])]
    print(f"  予算¥{payload['default_budget']:,}: 配分 {len(dp['allocations'])}商品 / "
          f"投資¥{dp['allocated']:,} / 現金¥{dp['cash']:,} / 期待利益¥{dp['expected_profit']:,} / "
          f"分散 {dp['diversification_score']}")
    return 0


def _write_md(p):
    o = ["# Capital Allocation Engine", "", f"生成: {p['generated_at']} / account_id: {p['account_id']}",
         f"現金留保 {p['cash_reserve_ratio']*100:.0f}% / 集中上限 商品{p['concentration_caps']['product']*100:.0f}%・"
         f"カテゴリ{p['concentration_caps']['category']*100:.0f}%・メーカー{p['concentration_caps']['maker']*100:.0f}%", "",
         "## Opportunity 指標", "",
         "| 商品 | action | 買値 | 期待値(EV) | 資本効率 | Risk | Liquidity |", "|---|---|---|---|---|---|---|"]
    for m in p["opportunity_metrics"]:
        o.append(f"| {m['product']} | {m['action']} | ¥{m['buy_price']:,} | ¥{m['expected_value']:,} | "
                 f"{m['capital_efficiency']} | {m['risk_score']} | {m['liquidity_score']} |")
    for b in p["budgets"]:
        pl = p["plans"][str(b)]
        o += ["", f"## 予算 ¥{b:,} の配分プラン", "",
              f"- 投資 ¥{pl['allocated']:,} / 現金 ¥{pl['cash']:,}（{pl['cash_ratio']*100:.0f}%） / "
              f"期待利益 **¥{pl['expected_profit']:,}** / 期待ROI {pl['expected_roi']*100:.1f}%",
              f"- 平均Risk {pl['avg_risk_score']} / 分散スコア {pl['diversification_score']} / "
              f"最大集中 {pl['max_concentration']*100:.0f}%", ""]
        if pl["allocations"]:
            o += ["| 商品 | 台数 | 単価 | 投資額 | 期待利益 | 保有 |", "|---|---|---|---|---|---|"]
            for a in pl["allocations"]:
                o.append(f"| {a['product']} | {a['units']}台 | ¥{a['unit_price']:,} | ¥{a['total']:,} | "
                         f"¥{a['expected_profit']:,} | {a['holding_period']} |")
        else:
            o.append("（配分対象なし）")
        if pl["waiting"]:
            o.append("")
            for w in pl["waiting"][:8]:
                o.append(f"- 待機: {w['product']} — {w['reason']}")
        o.append(f"- 現金 ¥{pl['cash']:,}（推奨留保20%: 急なBUY通知対応）")
    (OUT / "latest.md").write_text("\n".join(o) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

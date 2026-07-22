#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AI Opportunities Engine — Today's Opportunities を生成する。

外部LLMは使用しない。完全ルールベースで、同じ入力なら同じ結果になる（決定論的）。
利益判定ロジックは変更しない。profit_routes / health の結果を入力に、
Opportunity Score・BUY/WATCH/PASS・AI Summary・Why・Risk・保有期間・今日のおすすめを算出。

出力: exports/ai_opportunities/latest.json / latest.md
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
OUT = ROOT / "exports" / "ai_opportunities"


DB_PATH = ROOT / "data" / "premium_monitor.db"


def _load(p):
    try:
        return json.loads((ROOT / p).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _dom_fee(buy: int) -> int:
    return 1500 + max(3000, round(buy * 0.02))


def _next_update() -> str:
    """次回データ更新予測。workflow は毎日 12:00 JST（cron 03:00 UTC）。"""
    noon = NOW.replace(hour=12, minute=0, second=0, microsecond=0)
    if NOW < noon:
        return f"次回自動更新: 本日 {noon.strftime('%H:%M')}頃（買取/価格 日次取得）"
    nxt = noon + timedelta(days=1)
    return f"次回自動更新: 明日 {nxt.strftime('%H:%M')}頃（通常24時間以内）"


def _price_trend(product_id: str) -> dict:
    """買取価格の簡易トレンド（7d/30d/90d）。↑上昇 / ↓下降 / → 横ばい・データ不足。"""
    import sqlite3
    out = {"7d": "→", "30d": "→", "90d": "→"}
    try:
        con = sqlite3.connect(str(DB_PATH))
        rows = con.execute(
            "SELECT buyback_price, observed_at FROM buyback_prices "
            "WHERE product_id=? AND buyback_price>0 AND data_source!='fetch_failed'",
            (product_id,)).fetchall()
        con.close()
    except Exception:
        return out
    pts = []
    for price, oa in rows:
        try:
            dt = datetime.fromisoformat(str(oa))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
            age = (NOW - dt.astimezone(JST)).total_seconds() / 86400
            pts.append((age, price))
        except Exception:
            pass
    if len(pts) < 2:
        return out

    def _arrow(win):
        inside = [p for a, p in pts if a <= win]
        older = [p for a, p in pts if win < a <= win * 3]
        if not inside or not older:
            return "→"
        mi = sorted(inside)[len(inside) // 2]
        mo = sorted(older)[len(older) // 2]
        if mi > mo * 1.02:
            return "↑"
        if mi < mo * 0.98:
            return "↓"
        return "→"
    out["7d"] = _arrow(7)
    out["30d"] = _arrow(30)
    out["90d"] = _arrow(90)
    return out


def _stars(score: int) -> str:
    n = 5 if score >= 85 else 4 if score >= 70 else 3 if score >= 55 else 2 if score >= 40 else 1
    return "★" * n + "☆" * (5 - n)


def _score(c: dict) -> tuple[int, dict]:
    """Opportunity Score(100)。利益30/ROI20/鮮度15/再現性15/データ品質10/confidence10。
    減点: manual -10 / stale(14日超) -20。"""
    net = c["net_profit"]; roi = c["roi"]; age = c.get("age_days") or 99
    is_main = c["kind"] == "main"
    repro = c.get("reproducibility_score", 40)
    conf = c.get("route_confidence", "medium")
    b = {}
    b["利益"] = min(30, round(net / 20000 * 30))          # ¥2万で30点満点
    b["ROI"] = min(20, round(roi * 100 / 15 * 20))        # 15%で20点満点
    b["鮮度"] = 15 if age <= 1 else 12 if age <= 3 else 8 if age <= 7 else 4 if age <= 14 else 0
    b["再現性"] = round(repro / 100 * 15)
    b["データ品質"] = 10 if is_main else 5
    b["confidence"] = 10 if conf == "high" else 6 if conf == "medium" else 2
    penalty = 0
    if c.get("is_manual_curated"):
        penalty -= 10
    if age > 14:
        penalty -= 20
    b["減点(manual/stale)"] = penalty
    total = max(0, min(100, sum(b.values())))
    return total, b


def _buy_decision(c: dict, score: int) -> str:
    """BUY: main成立 & ROI>=8% & Opportunity>=80 / WATCH: reference または Opportunity>=50 / PASS: その他。"""
    if c["kind"] == "main" and c["roi"] >= 0.08 and score >= 80:
        return "BUY"
    if c["kind"] == "reference" or score >= 50:
        return "WATCH"
    return "PASS"


def _holding(c: dict) -> str:
    """保有期間: 即日/数日/1週間/1ヶ月/長期。"""
    overseas = c.get("route_type", "").endswith("overseas") or c["kind"] == "reference"
    if overseas:
        return "1ヶ月"
    if c["kind"] == "main":
        if (c.get("age_days") or 99) <= 1:
            return "即日"
        return "数日"
    return "1週間"


def _confidence(c: dict, score: int) -> str:
    if c["kind"] == "main" and score >= 70:
        return "high"
    if score >= 50:
        return "medium"
    return "low"


def _risks(c: dict) -> list[str]:
    r = []
    age = c.get("age_days") or 99
    if c.get("is_manual_curated"):
        r.append("manualデータ由来（購入可否・状態要確認）")
    if age > 14:
        r.append(f"stale（{age:.0f}日前・main計算除外水準）")
    elif age > 7:
        r.append(f"鮮度低（{age:.0f}日前）")
    if c.get("route_type", "").endswith("overseas") or c["kind"] == "reference":
        r.append("海外依存（為替・関税・輸送）")
        r.append("送料・決済手数料が大きい")
    if (c.get("same_condition_count") or 0) < 3:
        r.append("同条件件数不足（再現性低）")
    if c["roi"] < 0.08:
        r.append("価格変動で赤字化リスク（薄利）")
    pid = c.get("product_id", "").lower()
    if any(k in pid for k in ("gr", "x100", "gfx", "a7", "z8", "z9")):
        r.append("アクセサリー混在に注意（本体判定要確認）")
    return r or ["特筆すべきリスクなし（現物確認は必須）"]


def _summary(c: dict, score: int) -> str:
    """AI Summary（3行以内）。"""
    stars = _stars(score)
    if c["kind"] == "main":
        l1 = "現在もっとも有望な国内利益ルートです。" if score >= 70 else "国内で成立している利益ルートです。"
        l2 = f"利益 ¥{c['net_profit']:,} / ROI {c['roi']*100:.0f}%。"
        l3 = f"{c.get('sell_source','買取店')}買取が高水準です。"
    else:
        l1 = "海外売却で成立見込みの参考ルートです。"
        l2 = f"eBay更新後の想定利益 ¥{c['net_profit']:,} / ROI {c['roi']*100:.0f}%。"
        l3 = "現在は海外価格の更新待ちです。"
    return f"{stars}\n{l1}\n{l2}\n{l3}"


def _why(c: dict) -> list[str]:
    w = []
    if c["kind"] == "main":
        w.append("main route 成立（国内完結で利益）")
    else:
        w.append("reference route（海外sold更新で成立見込み）")
    if c["roi"] >= 0.08:
        w.append(f"ROIが8%以上（{c['roi']*100:.0f}%）")
    elif c["roi"] >= 0.05:
        w.append(f"ROIが5%以上（{c['roi']*100:.0f}%）")
    age = c.get("age_days") or 99
    if age <= 1:
        w.append("価格更新1日以内")
    elif age <= 8:
        w.append(f"価格 {age:.0f}日前（比較的新鮮）")
    else:
        w.append(f"価格 {age:.0f}日前（要更新）")
    if (c.get("reproducibility_score") or 0) >= 55:
        w.append(f"再現性スコア {c['reproducibility_score']}（中〜高）")
    if c.get("route_confidence") == "high":
        w.append("route confidence high")
    return w


def build_candidates(pr: dict) -> list[dict]:
    cands = []
    for r in pr.get("main_routes", []):
        cands.append({
            "kind": "main", "product_id": r["product_id"], "product_name": r["product_name"],
            "buy_source": r["buy_source"], "buy_price": r["buy_price"], "sell_source": r["sell_source"],
            "sell_price": r["sell_price"], "net_profit": r["net_profit"], "roi": r["roi"],
            "route_type": r["route_type"], "route_confidence": r["route_confidence"],
            "reproducibility_score": r.get("reproducibility_score", 40),
            "is_manual_curated": r.get("is_manual_curated", False),
            "same_condition_count": r.get("same_condition_count", 0),
            "age_days": round(max(r.get("buy_observed_age_days") or 0, r.get("sell_observed_age_days") or 0), 1),
        })
    seen = {}
    for r in pr.get("reference_routes", []):
        pid = r["product_id"]
        if pid not in seen or r["net_profit"] > seen[pid]["net_profit"]:
            seen[pid] = r
    for pid, r in sorted(seen.items()):
        cands.append({
            "kind": "reference", "product_id": pid, "product_name": r["product_name"],
            "buy_source": r["buy_source"], "buy_price": r["buy_price"], "sell_source": r["sell_source"],
            "sell_price": r["sell_price"], "net_profit": r["net_profit"], "roi": r["roi"],
            "route_type": r["route_type"], "route_confidence": r.get("route_confidence", "low"),
            "reproducibility_score": r.get("reproducibility_score", 30),
            "is_manual_curated": False, "same_condition_count": 0,
            "age_days": round(r.get("sell_observed_age_days") or 99, 1),
        })
    return cands


def main() -> int:
    print(f"[generate_ai_opportunities] 開始: {NOW.strftime('%Y-%m-%d %H:%M')} JST")
    pr = _load("exports/profit_routes/latest.json")
    health = _load("audit_health/health_report.json")
    health_score = (health.get("health_score", {}) or {}).get("total")

    cands = build_candidates(pr)
    ops = []
    for c in cands:
        score, breakdown = _score(c)
        decision = _buy_decision(c, score)
        # ── Action Engine ──
        sell = c["sell_price"]; buy = c["buy_price"]
        # ROI8% を満たす仕入れ上限（国内）= (sell - fee) / 1.08
        exp_buy = int((sell - _dom_fee(buy)) / 1.08) if sell else buy
        exp_sell = sell
        if decision == "BUY":
            action = "BUY"
            action_reason = "成立条件を満たしています。仕入れ→売却を実行できます。"
        elif decision == "PASS":
            action = "SKIP"
            action_reason = "現時点では利益条件を満たしません。見送り推奨。"
        elif c["kind"] == "reference":
            action = "WAIT"
            action_reason = "eBay sold 更新（EBAY_APP_ID 設定）後に BUY 候補へ昇格します。海外価格の更新待ちです。"
        elif c["roi"] < 0.08:
            action = "WAIT"
            gap = max(0, buy - exp_buy)
            action_reason = f"あと ¥{gap:,} 価格が下がれば ROI8%（BUY候補）になります。"
        else:
            # ROI は8%以上だが Opportunity Score<80（manual等）。価格アラートで監視。
            action = "ALERT"
            action_reason = f"価格が ¥{exp_buy:,} 以下になったら通知（BUY化を狙う）。"
        # 成立確率（ルールベース）
        if c["kind"] == "main":
            prob = max(30, min(95, round(c.get("reproducibility_score", 40) * 0.9 + (10 if c["age_days"] and c["age_days"] <= 7 else 0))))
        else:
            prob = 30
        # タイムライン（現在→監視→成立→通知）
        stages = ["候補", "監視", "成立", "通知"]
        if decision == "BUY":
            cur_stage = "成立"
        elif action in ("WAIT", "ALERT"):
            cur_stage = "監視"
        else:
            cur_stage = "候補"
        ops.append({
            "product": c["product_name"], "product_id": c["product_id"], "kind": c["kind"],
            "opportunity_score": score, "score_breakdown": breakdown,
            "buy_now": decision, "confidence": _confidence(c, score),
            "action": action, "action_reason": action_reason,
            "alert_threshold": exp_buy if action in ("ALERT", "WAIT") else None,
            "expected_buy_price": exp_buy, "expected_sell_price": exp_sell,
            "buy_conditions": {
                "buy": f"{c['buy_source']} ≤ ¥{exp_buy:,}",
                "sell": f"{c['sell_source']} ≥ ¥{exp_sell:,}",
                "roi": "ROI ≥ 8%",
            },
            "next_update": _next_update(),
            "price_trend": _price_trend(c["product_id"]),
            "success_probability": prob,
            "timeline": {"stages": stages, "current": cur_stage},
            "summary": _summary(c, score), "why": _why(c), "risks": _risks(c),
            "holding_period": _holding(c),
            "net_profit": c["net_profit"], "roi": round(c["roi"], 4),
            "reproducibility_score": c.get("reproducibility_score", 0),
            "buy_source": c["buy_source"], "buy_price": c["buy_price"],
            "sell_source": c["sell_source"], "sell_price": c["sell_price"],
            "age_days": c.get("age_days"),
        })
    # Task9 ランキング: Opportunity → 利益 → ROI → 再現性（決定論的）
    ops.sort(key=lambda x: (x["opportunity_score"], x["net_profit"], x["roi"],
                            x["reproducibility_score"]), reverse=True)
    for i, o in enumerate(ops, 1):
        o["priority"] = i
    top10 = ops[:10]

    # Task8 今日のおすすめ（priority 1・理由100文字以内）
    daily = None
    if top10:
        t = top10[0]
        reason = (f"{t['product']}: {t['buy_now']}。"
                  f"{'国内成立' if t['kind']=='main' else '海外更新後見込み'} "
                  f"利益¥{t['net_profit']:,}/ROI{t['roi']*100:.0f}%/Score{t['opportunity_score']}")[:100]
        daily = {"product": t["product"], "buy_now": t["buy_now"],
                 "opportunity_score": t["opportunity_score"], "reason": reason}

    # Task10 Health連携
    if health_score is None:
        health_note = ""
    elif health_score < 60:
        health_note = "現在データ品質低下中"
    elif health_score >= 80:
        health_note = "データ品質は良好です"
    else:
        health_note = "データ品質は標準的です"

    # Task9 今日やること（上位候補の Action を行動文に変換）
    _act_verb = {
        "BUY": lambda o: f"✅ {o['product']} を仕入れる（{o['buy_source']} ≤¥{o['expected_buy_price']:,}）",
        "ALERT": lambda o: f"🔔 {o['product']} を監視（¥{o['alert_threshold']:,}以下で通知）",
        "WAIT": lambda o: f"⏳ {o['product']} は待機（{o['action_reason']}）",
        "SKIP": lambda o: f"⏭ {o['product']} は見送り",
    }
    today_tasks = [_act_verb.get(o["action"], lambda x: x["product"])(o) for o in top10[:5]]
    if not today_tasks:
        today_tasks = ["本日の対象なし（データ取得状況を Health タブで確認）"]

    payload = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "health_score": health_score, "health_note": health_note,
        "main_route_count": sum(1 for o in ops if o["kind"] == "main"),
        "reference_route_count": sum(1 for o in ops if o["kind"] == "reference"),
        "today_tasks": today_tasks,
        "daily_recommendation": daily,
        "todays_opportunities": top10,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(payload)
    _c = {"BUY": 0, "WATCH": 0, "PASS": 0}
    for o in top10:
        _c[o["buy_now"]] += 1
    print(f"  Opportunities: {len(top10)} / BUY {_c['BUY']} WATCH {_c['WATCH']} PASS {_c['PASS']} "
          f"/ Health {health_score}（{health_note}）")
    return 0


def _write_md(p):
    o = ["# AI Opportunities Engine — Today's Opportunities", "",
         f"生成: {p['generated_at']}",
         f"Health Score: {p['health_score']}（{p['health_note']}） / "
         f"main {p['main_route_count']} / reference {p['reference_route_count']}", ""]
    o += ["## 今日やること", ""]
    for t in p.get("today_tasks", []):
        o.append(f"- {t}")
    d = p.get("daily_recommendation")
    o += ["", "## 今日のおすすめ", ""]
    if d:
        o.append(f"> **{d['product']}**（{d['buy_now']} / Score {d['opportunity_score']}）")
        o.append(f"> {d['reason']}")
    else:
        o.append("> 本日は候補なし")
    if p["health_note"]:
        o += ["", f"**{p['health_note']}**"]
    o += ["", "## Opportunity Ranking TOP10", ""]
    _act = {"BUY": "🟢 BUY", "ALERT": "🔔 ALERT", "WAIT": "⏳ WAIT", "SKIP": "⏭ SKIP"}
    for c in p["todays_opportunities"]:
        tl = c["timeline"]
        tl_str = " → ".join((f"**{s}**" if s == tl["current"] else s) for s in tl["stages"])
        o += [f"### #{c['priority']} {c['product']} — {_act.get(c['action'], c['action'])}（Score {c['opportunity_score']}/100・成立確率 {c['success_probability']}%）",
              f"- {c['summary'].splitlines()[0]}",
              "  " + " ".join(c["summary"].splitlines()[1:]),
              f"- Action: {c['action']} — {c['action_reason']}",
              f"- 成立条件: {c['buy_conditions']['buy']} ／ {c['buy_conditions']['sell']} ／ {c['buy_conditions']['roi']}",
              f"- 想定仕入 ¥{c['expected_buy_price']:,} / 想定売却 ¥{c['expected_sell_price']:,}"
              + (f" ／ 🔔 ¥{c['alert_threshold']:,}以下で通知" if c.get('alert_threshold') else ""),
              f"- 価格トレンド: 7d {c['price_trend']['7d']} / 30d {c['price_trend']['30d']} / 90d {c['price_trend']['90d']}",
              f"- {c['next_update']}",
              f"- タイムライン: {tl_str}",
              f"- 期待: 利益 ¥{c['net_profit']:,} / ROI {c['roi']*100:.1f}% / confidence {c['confidence']}",
              f"- 保有期間: {c['holding_period']}",
              f"- Why: {'; '.join(c['why'])}",
              f"- Risk: {' / '.join(c['risks'])}", ""]
    if not p["todays_opportunities"]:
        o.append("（本日は候補なし）")
    (OUT / "latest.md").write_text("\n".join(o) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

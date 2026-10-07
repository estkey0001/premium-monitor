#!/usr/bin/env python3
"""本番データの量と質の計測（Phase 11。読むだけ。生成物を書き換えない）。

CI の生成物（exports/・audit_health/・data/lottery_events.csv）から、次を数える。
- 指標: 監視商品・確定の利益商品・確定/参考ルート・定価の確認・買取（新しい/古い/失敗/確定）・成約・出品・在庫・TCG・健康度
- 商品 × データの種類（定価・買取・在庫・出品・成約・抽選/予約）の網羅表（CONFIRMED / REFERENCE / STALE / MISSING /
  FAILED / NOT_IMPLEMENTED）
- 利益商品の候補が、どの段階（定価の確認 → 新しい売値 → 照合 → 費用 → 利益 → 掲載）で何件落ちるか

判定はやり直さない。確定の売値は normalized_prices.confirmed_sell_keys、ルートは opportunity.confirmed_routes /
reference_routes、利益商品の候補の理由は opportunity_diagnostics（opportunity.eligibility の結果）をそのまま使う。

使い方:
  python scripts/production_coverage_metrics.py                 # 指標を JSON で表示
  python scripts/production_coverage_metrics.py --md OUT.md --json OUT.json --title "Phase 11 Baseline"
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

DATA_TYPES = ("RETAIL", "BUYBACK", "STOCK", "LISTING", "SOLD", "LOTTERY")
STATES = ("CONFIRMED", "REFERENCE", "STALE", "MISSING", "FAILED", "NOT_IMPLEMENTED")
# 利益商品の候補が落ちる段階（opportunity_diagnostics の分類の理由 → 段階）。上から順に判定する
FUNNEL = (
    ("verified_buy", {"no_buy_price", "unverified_buy_price"}),
    ("fresh_sell", {"no_sell_price", "stale_buyback", "unknown_type", "no_sold_period", "insufficient_sold_samples"}),
    ("identity", {"invalid_identity"}),
    ("shipping", {"missing_costs"}),
    ("profitable", {"no_profit"}),
    ("actionable", {"other"}),
)


def _load(rel: str) -> dict:
    p = ROOT / rel
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _now():
    from src.tcg.models import now_jst
    return now_jst()


def collect(now: datetime | None = None) -> dict:
    """指標・網羅表・段階ごとの件数をまとめて返す（読むだけ）。"""
    from src.content.ui import opportunity as opp
    from src.market import normalized_prices as npx

    now = now or _now()
    diag = _load("exports/opportunity_diagnostics/latest.json")
    npo = _load("exports/normalized_price_observations/latest.json")
    obs = [o for o in npo.get("observations") or [] if isinstance(o, dict)]
    routes = _load("exports/profit_routes/latest.json")
    collector = _load("exports/collector_report/latest.json")
    stock = _load("exports/stock_history/latest.json")
    tcg = _load("exports/tcg/latest.json")
    health = _load("audit_health/health_report.json")
    products = [p for p in (diag.get("retail_prices") or {}).get("products") or [] if isinstance(p, dict)]
    pids = [p["product_id"] for p in products]

    # ── 買取 ──
    buyback = [o for o in obs if o.get("price_role") == "sell" and o.get("canonical_price_type") == "BUYBACK_CASH"]
    confirmed_keys = npx.confirmed_sell_keys(obs)
    confirmed_buyback_products = sorted({k[0] for k in confirmed_keys})
    shops = [s for s in collector.get("shop_detail") or [] if isinstance(s, dict)]
    summ = collector.get("summary") or {}
    tried = int(summ.get("ok") or 0) + int(summ.get("failed") or 0)
    # ── 成約・出品 ──
    sold_rows = [o for o in obs if o.get("canonical_price_type") in ("SOLD", "SOLD_MEDIAN")]
    listing_rows = [o for o in obs if o.get("canonical_price_type") == "LISTING"]
    sold = diag.get("sold") or {}
    valid_sold = sum(int((v or {}).get("valid_sold") or 0) for v in sold.values() if isinstance(v, dict))
    # ── 在庫 ──
    entries = [e for e in (stock.get("entries") or {}).values() if isinstance(e, dict)]
    stock_states = Counter(str(e.get("state") or "UNKNOWN") for e in entries)
    diag_stock = (diag.get("stock") or {}).get("states") or {}
    # ── TCG ──
    lots = [e for e in tcg.get("lotteries") or [] if isinstance(e, dict)]
    events = [e for e in tcg.get("events") or [] if isinstance(e, dict)]
    preorder = [e for e in lots + events if str(e.get("event_type") or "").upper() == "PREORDER"]
    first_come = [e for e in events if str(e.get("event_type") or "").upper() in ("FIRST_COME", "AVAILABLE_NOW")]
    restock_ev = [e for e in events if str(e.get("event_type") or "").upper() == "RESTOCK"]
    src_health = Counter(str(h.get("status") or "") for h in tcg.get("source_health") or [] if isinstance(h, dict))
    # ── ルート ──
    main = opp.confirmed_routes(routes.get("main_routes"), now)
    ref = opp.reference_routes(routes.get("reference_routes"), now)
    retail = (diag.get("retail_prices") or {}).get("summary") or {}

    metrics = {
        "generated_from": {"diagnostics": diag.get("generated_at"), "observations": npo.get("generated_at"),
                           "collector": collector.get("generated_at"), "routes": routes.get("generated_at"),
                           "tcg": tcg.get("generated_at"), "health": health.get("generated_at")},
        "products": len(pids),
        "confirmed_opportunities": int(diag.get("eligible_count") or 0),
        "opportunity_candidates": int(diag.get("candidate_count") or 0),
        "confirmed_routes": len(main),
        "reference_routes": len(ref),
        "verified_retail": int(retail.get("verified") or 0),
        "unverified_retail": int(retail.get("reference") or 0),
        "buyback_rows": len(buyback),
        "fresh_buyback": sum(1 for o in buyback if o.get("is_fresh")),
        "stale_buyback": sum(1 for o in buyback if not o.get("is_fresh")),
        "confirmed_buyback_rows": len(confirmed_keys),
        "confirmed_buyback_products": len(confirmed_buyback_products),
        "buyback_attempts": tried,
        "buyback_success": int(summ.get("ok") or 0),
        "buyback_success_rate": round(int(summ.get("ok") or 0) / tried, 3) if tried else None,
        "buyback_shops": len(shops),
        "buyback_shops_failed_all": sum(1 for s in shops if int(s.get("ok") or 0) == 0),
        "valid_sold": valid_sold,
        "sold_rows": len(sold_rows),
        "eligible_sold_median": int((diag.get("sold_median") or {}).get("eligible") or 0),
        "listing_rows": len(listing_rows),
        "stock_in_stock": int(diag_stock.get("IN_STOCK") or 0),
        "stock_out_of_stock": int(diag_stock.get("OUT_OF_STOCK") or 0),
        "stock_unknown": int(diag_stock.get("UNKNOWN") or 0),
        "stock_other": {k: v for k, v in diag_stock.items() if k not in ("IN_STOCK", "OUT_OF_STOCK", "UNKNOWN")},
        "stock_history_entries": len(entries),
        "stock_history_states": dict(stock_states),
        "restock_events": len([e for e in stock.get("events") or [] if isinstance(e, dict)
                               and e.get("kind") == "RESTOCK"]),
        "tcg_lotteries": len(lots),
        "tcg_lottery_status": dict(Counter(str(e.get("status") or "") for e in lots)),
        "tcg_events": len(events),
        "tcg_event_types": dict(Counter(f'{e.get("event_type")}/{e.get("status")}' for e in events)),
        "tcg_preorder": len(preorder),
        "tcg_first_come": len(first_come),
        "tcg_restock": len(restock_ev),
        "tcg_source_health": dict(src_health),
        "system_health": (health.get("health_score") or {}).get("total"),
        "exclusion_reasons": diag.get("exclusion_reasons") or {},
    }
    return {"metrics": metrics, "funnel": funnel(diag), "matrix": matrix(
        pids, products, obs, confirmed_keys, entries, routes, now)}


def funnel(diag: dict) -> list[dict]:
    """利益商品の候補が、どの段階で何件落ちるか（理由は opportunity_diagnostics の分類。上の段階から順に数える）。"""
    from src.market import opportunity_diagnostics as od
    cands = [c for c in diag.get("candidates") or [] if isinstance(c, dict)]       # 外した候補（理由つき）だけ
    passed = int(diag.get("eligible_count") or 0)                                 # 確定の案件は全段階を通る
    left = list(cands)
    out = [{"stage": "candidates", "count": len(left) + passed, "dropped": 0, "reasons": {}}]
    for stage, reasons in FUNNEL:
        keep, drop = [], Counter()
        for c in left:
            hit = [r for r in c.get("reasons") or [] if od._reason(r) in reasons or r in reasons]
            if hit:
                for r in hit:
                    drop[od._reason(r) if od._reason(r) in reasons else r] += 1
            else:
                keep.append(c)
        out.append({"stage": stage, "count": len(keep) + passed, "dropped": len(left) - len(keep),
                    "reasons": dict(drop)})
        left = keep
    return out


def matrix(pids, products, obs, confirmed_keys, entries, routes, now) -> dict:
    """商品 × データの種類の網羅表（状態の数と、商品ごとの状態）。"""
    retail_ev = {p["product_id"]: str(p.get("evidence") or "") for p in products}
    conf_pids = {k[0] for k in confirmed_keys}
    by_pid: dict[str, list] = {}
    for o in obs:
        by_pid.setdefault(str(o.get("product_id") or ""), []).append(o)
    stock_by = {}
    for e in entries:
        stock_by.setdefault(str(e.get("product_id") or ""), []).append(e)
    lot_names = set()
    try:
        with open(ROOT / "data" / "lottery_events.csv", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                lot_names.add(str(r.get("product_name") or ""))
    except OSError:
        pass
    names = {p["product_id"]: str(p.get("product") or "") for p in products}
    rows = {}
    for pid in pids:
        rows_o = by_pid.get(pid, [])
        bb = [o for o in rows_o if o.get("price_role") == "sell" and o.get("canonical_price_type") == "BUYBACK_CASH"]
        ev = retail_ev.get(pid, "")
        retail = ("CONFIRMED" if ev.startswith("VERIFIED") else "STALE" if ev == "STALE"
                  else "REFERENCE" if ev == "CONFIGURED_REFERENCE" else "MISSING")
        if pid in conf_pids:
            buy = "CONFIRMED"
        elif any(o.get("is_fresh") and (o.get("price") or 0) > 0 for o in bb):
            buy = "REFERENCE"
        elif any((o.get("price") or 0) > 0 for o in bb):
            buy = "STALE"
        elif bb:
            buy = "FAILED"
        else:
            buy = "MISSING"
        st = [e for e in stock_by.get(pid, [])]
        stock_state = ("CONFIRMED" if any(e.get("state") in ("IN_STOCK", "OUT_OF_STOCK", "LOTTERY", "RESERVATION")
                                          for e in st) else "MISSING")
        listing = "REFERENCE" if any(o.get("canonical_price_type") == "LISTING" or
                                     (o.get("price_role") == "buy" and (o.get("price") or 0) > 0) for o in rows_o) \
            else "MISSING"
        sold_rows = [o for o in rows_o if o.get("canonical_price_type") in ("SOLD", "SOLD_MEDIAN")]
        sold = ("CONFIRMED" if any(o.get("sold_median_eligible") for o in sold_rows)
                else "REFERENCE" if sold_rows else "NOT_IMPLEMENTED")
        lot = "CONFIRMED" if names.get(pid) in lot_names else "MISSING"
        rows[pid] = {"name": names.get(pid, pid), "RETAIL": retail, "BUYBACK": buy, "STOCK": stock_state,
                     "LISTING": listing, "SOLD": sold, "LOTTERY": lot}
    totals = {t: dict(Counter(r[t] for r in rows.values())) for t in DATA_TYPES}
    return {"totals": totals, "products": rows}


def to_markdown(res: dict, title: str) -> str:
    m, f, mx = res["metrics"], res["funnel"], res["matrix"]
    lines = [f"# {title}", "", "CI の生成物から `scripts/production_coverage_metrics.py` で計測した（読むだけ）。", "",
             "## 生成物の時刻", ""]
    for k, v in m["generated_from"].items():
        lines.append(f"- {k}: {v or '—'}")
    lines += ["", "## 指標", "", "| 指標 | 値 |", "|---|---:|"]
    for k, v in m.items():
        if k in ("generated_from",):
            continue
        lines.append(f"| {k} | {json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v} |")
    lines += ["", "## 利益商品の候補の段階（上から順に落ちる件数）", "", "| 段階 | 残り | 落ちた | 理由 |",
              "|---|---:|---:|---|"]
    for s in f:
        lines.append(f"| {s['stage']} | {s['count']} | {s['dropped']} | "
                     f"{json.dumps(s['reasons'], ensure_ascii=False) if s['reasons'] else ''} |")
    lines += ["", "## 網羅表（商品 × データの種類）", "", "| 種類 | " + " | ".join(STATES) + " |",
              "|---|" + "---:|" * len(STATES)]
    for t in DATA_TYPES:
        lines.append(f"| {t} | " + " | ".join(str(mx["totals"][t].get(s, 0)) for s in STATES) + " |")
    lines += ["", "### 商品ごと", "", "| 商品 | " + " | ".join(DATA_TYPES) + " |",
              "|---|" + "---|" * len(DATA_TYPES)]
    for pid, r in sorted(mx["products"].items(), key=lambda kv: kv[1]["name"]):
        lines.append(f"| {r['name']} | " + " | ".join(r[t] for t in DATA_TYPES) + " |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--md", help="Markdown の出力先")
    ap.add_argument("--json", help="JSON の出力先")
    ap.add_argument("--title", default="Production Coverage")
    a = ap.parse_args(argv)
    res = collect()
    if a.md:
        Path(a.md).parent.mkdir(parents=True, exist_ok=True)
        Path(a.md).write_text(to_markdown(res, a.title), encoding="utf-8")
    if a.json:
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    if not (a.md or a.json):
        print(json.dumps(res["metrics"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())

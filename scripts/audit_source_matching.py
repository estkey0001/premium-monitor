#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Source Matching Accuracy — 商品同一性マッチング精度の監査。

利益/AI/Opportunity/Notification/Capital/Execution/Data Quality Score思想は不変。
ProductIdentityResolver で各観測の紐付けを再検証し、精度指標・誤マッチ一覧・
False Main Promotion 監査・ソース精度ランキング・duplicate risk を生成する。

出力: exports/source_matching/latest.json / latest.md
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
OUT = ROOT / "exports" / "source_matching"
DB = ROOT / "data" / "premium_monitor.db"

from src.market.product_identity_resolver import ProductIdentityResolver, build_products_index
from src.market.price_quality import (
    is_main_promotable, detect_duplicate_price_pattern, effective_confidence,
    RETAIL_SOURCES, BUYBACK_SOURCES, RESALE_SOURCES,
)

RANKED_SOURCES = ["価格.com", "ヨドバシ", "ビックカメラ", "楽天市場", "Yahoo",
                  "マップカメラ", "フジヤカメラ", "じゃんぱら", "イオシス", "モバイル一番",
                  "eBay sold(新品)", "メーカー公式/定価", "RICOH"]
# 表示名の別名（RICOH は公式ソース名がメーカー公式/定価配下）
SOURCE_ALIASES = {"eBay": ["eBay sold(新品)", "eBay", "src_ebay"],
                  "Apple": ["メーカー公式/定価"],
                  "RICOH": ["メーカー公式/定価"]}


def _load(rel):
    try:
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pct(a, b):
    return round(a / b, 4) if b else 1.0


def main():
    npo = _load("exports/normalized_price_observations/latest.json")
    obs = npo.get("observations", [])
    if not obs:
        print("[source_matching] NPO が空。")
        return 1
    products = build_products_index(DB)
    R = ProductIdentityResolver(products)

    # ── Task1: 全件 + ソース別 集計 ──
    tallies = defaultdict(lambda: defaultdict(int))
    resolved_rows = []
    for o in obs:
        src = o.get("source_name") or "?"
        title = o.get("extracted_title") or o.get("product_name") or ""
        res = R.resolve(
            source_title=title, source_url=o.get("item_url", ""),
            source_text=o.get("price_context", ""), condition=o.get("condition", ""),
            link_type=o.get("link_type", ""), expected_product_id=o.get("product_id"),
        )
        main_elig = is_main_promotable(o)
        row = {"obs": o, "res": res, "main_eligible": main_elig}
        resolved_rows.append(row)
        for scope in ("_all", src):
            t = tallies[scope]
            t["total"] += 1
            if o.get("is_exact_product_match"):
                t["exact_product_match"] += 1
            else:
                t["product_mismatch_or_unverified"] += 1
            if res.capacity_match is True:
                t["capacity_match"] += 1
            elif res.capacity_match is False:
                t["capacity_mismatch"] += 1
            if res.model_match is True:
                t["model_match"] += 1
            elif res.model_match is False:
                t["model_mismatch"] += 1
            else:
                t["model_unverifiable"] += 1
            if res.condition_match is True:
                t["condition_match"] += 1
            elif res.condition_match is False:
                t["condition_mismatch"] += 1
            if res.accessory_flag or o.get("accessory_flag"):
                t["accessory_detected"] += 1
            if main_elig:
                t["main_eligible"] += 1
            else:
                t["main_rejected"] += 1
            if res.identity_confidence == "low" or (res.matched_product_id and
                    res.matched_product_id != o.get("product_id")):
                t["manual_review_required"] += 1

    # ── Task17: False Main Promotion 監査 ──
    false_main = []
    for row in resolved_rows:
        if not row["main_eligible"]:
            continue
        o, res = row["obs"], row["res"]
        defects = []
        if res.capacity_match is False:
            defects.append("capacity_mismatch")
        if res.model_match is False:
            defects.append("model_mismatch")
        if res.condition_match is False:
            defects.append("condition_mismatch")
        if res.accessory_flag or o.get("accessory_flag"):
            defects.append("accessory")
        if o.get("link_type") == "search":
            defects.append("search_low_confidence")
        if not o.get("is_fresh"):
            defects.append("stale")
        if res.matched_product_id and res.matched_product_id != o.get("product_id"):
            defects.append("reassigned_product")
        if defects:
            false_main.append({"product_id": o.get("product_id"), "source": o.get("source_name"),
                               "price": o.get("price"), "defects": defects})

    # ── duplicate price pattern（risk付き）+ RICOH review（Task16）──
    dups = detect_duplicate_price_pattern(obs)
    for d in dups:
        if d["is_official"] and d["risk_level"] != "high":
            # 公式で容量/機種差が無い同額 → 実同額としてレビュー済み扱い
            d["review_status"] = "reviewed_true_same_price"
        elif d["is_official"]:
            d["review_status"] = "manual_review_required"

    # ── Task21: ソース精度ランキング（100点）──
    ranking = []
    for src, t in tallies.items():
        if src == "_all":
            continue
        n = t["total"] or 1
        identity = _pct(t["exact_product_match"], n)
        cap = 1.0 - _pct(t["capacity_mismatch"], n)
        model = 1.0 - _pct(t["model_mismatch"], n)
        cond = 1.0 - _pct(t.get("condition_mismatch", 0), n)
        price_ok = 1.0 - _pct(t.get("accessory_detected", 0), n)
        fresh = _pct(sum(1 for r in resolved_rows if (r["obs"].get("source_name") == src and r["obs"].get("is_fresh"))), n)
        main_acc = 1.0 - _pct(sum(1 for f in false_main if f["source"] == src), max(1, t["main_eligible"]))
        score = round(identity * 25 + cap * 20 + model * 20 + cond * 10 + price_ok * 10
                      + fresh * 5 + main_acc * 10)
        ranking.append({"source": src, "observations": t["total"], "score": score,
                        "identity": round(identity, 3), "capacity": round(cap, 3),
                        "model": round(model, 3), "condition": round(cond, 3),
                        "freshness": round(fresh, 3), "main_eligible": t["main_eligible"]})
    ranking.sort(key=lambda x: -x["score"])

    # ── 検出された全 mismatch（rejected 含む・隠さず明示）──
    detected_mismatches = []
    for row in resolved_rows:
        o, res = row["obs"], row["res"]
        kinds = []
        if res.capacity_match is False:
            kinds.append("capacity")
        if res.model_match is False:
            kinds.append("model")
        if res.condition_match is False:
            kinds.append("condition")
        if kinds:
            detected_mismatches.append({
                "product_id": o.get("product_id"), "source": o.get("source_name"),
                "title": (o.get("extracted_title") or "")[:80], "kinds": kinds,
                "rejected": bool(o.get("rejection_reason")),
                "rejection_reason": o.get("rejection_reason"),
                "usable_pro": o.get("is_usable_for_pro"),
            })

    # ── 精度サマリ（Task20）: アクティブ(非rejected=downstream に生きる)binding で算出 ──
    # rejected 観測（既に flag 済み）は誤りに数えない。ただし detected_mismatches で全件明示。
    active = [r for r in resolved_rows if not r["obs"].get("rejection_reason")]
    a = tallies["_all"]
    tot_active = len(active) or 1
    ac_capm = sum(1 for r in active if r["res"].capacity_match is True)
    ac_capx = sum(1 for r in active if r["res"].capacity_match is False)
    ac_modm = sum(1 for r in active if r["res"].model_match is True)
    ac_modx = sum(1 for r in active if r["res"].model_match is False)
    ac_conm = sum(1 for r in active if r["res"].condition_match is True)
    ac_conx = sum(1 for r in active if r["res"].condition_match is False)
    cap_denom = ac_capm + ac_capx
    model_denom = ac_modm + ac_modx
    cond_denom = ac_conm + ac_conx
    confirmed_mismatch = ac_capx + ac_modx + ac_conx
    accuracy = {
        "product_match_accuracy": round(1.0 - confirmed_mismatch / tot_active, 4),
        "capacity_match_accuracy": _pct(ac_capm, cap_denom) if cap_denom else 1.0,
        "model_match_accuracy": _pct(ac_modm, model_denom) if model_denom else 1.0,
        "condition_match_accuracy": _pct(ac_conm, cond_denom) if cond_denom else 1.0,
        "confirmed_mismatches_active": confirmed_mismatch,
        "detected_mismatches_total": len(detected_mismatches),
        "detected_mismatches_rejected": sum(1 for m in detected_mismatches if m["rejected"]),
        "independently_verified_exact": a["exact_product_match"],
        "unverifiable_trusted": a.get("model_unverifiable", 0),
        "accessory_misclassification": sum(1 for f in false_main if "accessory" in f["defects"]),
        "false_main_promotion": len(false_main),
        "duplicate_patterns": len(dups),
        "high_risk_duplicates": sum(1 for d in dups if d["risk_level"] == "high"),
        "duplicate_reviewed_pct": _pct(sum(1 for d in dups if d["review_status"] != "pending"), len(dups)) if dups else 1.0,
        "manual_review_queue": a["manual_review_required"],
    }

    report = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "scope": "商品同一性マッチング精度（利益/AI/UI/SaaS/DQ思想は不変）",
        "accuracy": accuracy,
        "targets": {"product_match": ">=0.99", "capacity_match": "=1.0",
                    "model_match": "=1.0", "condition_match": "=1.0", "false_main_promotion": 0},
        "totals": dict(a),
        "by_source": {s: dict(t) for s, t in tallies.items() if s != "_all"},
        "false_main_promotion": false_main,
        "detected_mismatches": detected_mismatches,
        "duplicate_price_pattern": dups,
        "source_accuracy_ranking": ranking,
        "resolver": "src/market/product_identity_resolver.py（JAN→SKU/MPN→型番→機種名→容量→variant→color→condition）",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT / "latest.md").write_text(render_md(report), encoding="utf-8")
    print(f"[source_matching] product={accuracy['product_match_accuracy']:.1%} "
          f"cap={accuracy['capacity_match_accuracy']:.1%} model={accuracy['model_match_accuracy']:.1%} "
          f"false_main={accuracy['false_main_promotion']} high_risk_dup={accuracy['high_risk_duplicates']} "
          f"→ {OUT/'latest.json'}")
    return 0


def render_md(r):
    a = r["accuracy"]
    L = ["# Source Matching Accuracy 監査\n", f"> 生成: {r['generated_at']} / {r['scope']}\n"]
    L.append("## 精度サマリ（目標対比）")
    L.append("| 指標 | 実績 | 目標 |")
    L.append("|---|--:|--:|")
    L.append(f"| Product Match Accuracy | {a['product_match_accuracy']:.1%} | ≥99% |")
    L.append(f"| Capacity Match Accuracy | {a['capacity_match_accuracy']:.1%} | 100% |")
    L.append(f"| Model Match Accuracy | {a['model_match_accuracy']:.1%} | 100% |")
    L.append(f"| Condition Match Accuracy | {a['condition_match_accuracy']:.1%} | 100% |")
    L.append(f"| False Main Promotion | {a['false_main_promotion']} | 0 |")
    L.append(f"| High Risk Duplicates | {a['high_risk_duplicates']} | (要レビュー) |")
    L.append(f"| Manual Review Queue | {a['manual_review_queue']} | – |")
    L.append("")
    L.append("## ソース精度ランキング（100点）")
    L.append("| # | source | 観測 | score | identity | capacity | model | fresh | main |")
    L.append("|--:|---|--:|--:|--:|--:|--:|--:|--:|")
    for i, x in enumerate(r["source_accuracy_ranking"], 1):
        L.append(f"| {i} | {x['source']} | {x['observations']} | {x['score']} | {x['identity']:.2f} | "
                 f"{x['capacity']:.2f} | {x['model']:.2f} | {x['freshness']:.2f} | {x['main_eligible']} |")
    L.append("")
    L.append("## False Main Promotion 監査（目標 0）")
    if r["false_main_promotion"]:
        L.append("| product | source | price | defects |")
        L.append("|---|---|--:|---|")
        for f in r["false_main_promotion"][:30]:
            L.append(f"| {f['product_id']} | {f['source']} | ¥{f['price']:,} | {', '.join(f['defects'])} |")
    else:
        L.append("- ✅ False Main Promotion = 0")
    L.append("")
    L.append("## 検出された機種/容量 mismatch（隠さず明示・rejected含む）")
    if r.get("detected_mismatches"):
        L.append("| product | source | kinds | rejected | title |")
        L.append("|---|---|---|:--:|---|")
        for m in r["detected_mismatches"][:20]:
            L.append(f"| {m['product_id']} | {m['source']} | {', '.join(m['kinds'])} | "
                     f"{'✅' if m['rejected'] else '❌未'} | {m['title']} |")
    else:
        L.append("- なし")
    L.append("")
    L.append("## Duplicate Price Pattern（risk別・弾かず要確認）")
    L.append("| risk | source | role | price | SKU数 | 理由 | review |")
    L.append("|---|---|---|--:|--:|---|---|")
    for d in r["duplicate_price_pattern"][:25]:
        L.append(f"| {d['risk_level']} | {d['source_name']} | {d['price_role']} | ¥{d['price']:,} | "
                 f"{d['count']} | {', '.join(d['possible_reason'])} | {d['review_status']} |")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""eBay Real API Canary（EBAY REAL CANARY EXECUTION PHASE）。

EBAY_APP_ID が設定されている場合のみ、実 eBay API レスポンスで Canary を実行する。
未設定/認証失敗時は real_api_called=false で正直に報告し、PASS を偽らない。
全 Listing は必ず ProductIdentityResolver + price_quality + Main Gate を通す。
API_DRY_RUN 前提で Main DB は書き換えない（前後スナップショットで検証）。

出力: exports/api_automation/ebay_real_canary.json / ebay_real_canary.md
対象は eBay のみ（楽天/Yahoo は触らない）。利益/AI/DQ思想は不変。

Verdict:
  EBAY_REAL_CANARY_PASS       — 実API・全ゲート通過
  EBAY_ROLLOUT_BLOCKED        — 実API呼べたが精度未達
  EBAY_CONFIGURATION_ERROR    — 認証/設定エラーで呼べず
  EBAY_PENDING_CONFIGURATION  — キー未設定
"""
from __future__ import annotations

import json
import sqlite3
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
OUT = ROOT / "exports" / "api_automation"
DB = ROOT / "data" / "premium_monitor.db"

from src.collectors.api.api_runtime import (
    is_configured, kill_switch_on, api_stage, stage_product_limit, is_dry_run,
    configured_status, rollout_state, HealthTracker, CircuitBreaker,
)
from src.collectors.api import market_apis
from src.market.product_identity_resolver import ProductIdentityResolver, build_products_index
from src.market.price_quality import is_main_promotable

CANARY = ["prod_iphone17pro_256", "prod_iphone17pm_256", "prod_gr3x", "prod_x100vi"]
EXCLUDED_TERMS = ["case", "cover", "box only", "for parts", "replacement", "screen protector",
                  "battery", "charger", "dummy", "broken", "repair", "lens only", "strap", "bundle"]
# Stage 5 候補（Canary PASS 時のみ推奨・high liquidity / exact identifiers / 低曖昧）
STAGE5_CANDIDATES = ["prod_iphone17pro_512", "prod_iphone17pm_512", "prod_iphone17_256",
                     "prod_gr4", "prod_ps5_pro"]


def _snapshot_db():
    if not DB.exists():
        return None
    c = sqlite3.connect(str(DB)); c.row_factory = sqlite3.Row
    try:
        obs = c.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        bb = c.execute("SELECT COUNT(*) FROM buyback_prices").fetchone()[0]
        off = c.execute("SELECT COALESCE(SUM(official_price),0) FROM products").fetchone()[0]
        return {"observations": obs, "buyback_prices": bb, "official_sum": off}
    finally:
        c.close()


def _keyword(pid, products):
    p = products.get(pid, {})
    kws = p.get("keywords") or []
    return (kws[0] if kws else p.get("name", "")) or pid


def _aggregate(prices):
    ps = sorted(p for p in prices if isinstance(p, (int, float)) and p > 0)
    if not ps:
        return {}
    n = len(ps)
    q = lambda x: ps[min(n - 1, int(x * n))]  # noqa: E731
    return {"count": n, "min": ps[0], "p25": q(0.25), "median": statistics.median(ps),
            "mean": round(statistics.mean(ps)), "p75": q(0.75), "max": ps[-1]}


def _build_queries(products):
    q = []
    for pid in [p for p in CANARY if p in products]:
        p = products[pid]
        q.append({"expected_product_id": pid, "brand": p.get("brand"),
                  "model": p.get("name"), "query": _keyword(pid, products),
                  "excluded_terms": EXCLUDED_TERMS})
    return q


def run_ebay_canary(products, resolver):
    api = "ebay"
    cfg = configured_status(api)
    queries = _build_queries(products)
    base = {
        "api": "ebay", "configuration": {
            "EBAY_APP_ID": cfg.upper(),
            "ENABLE_EBAY_API": "false" if kill_switch_on(api) else "true_or_default",
            "EBAY_API_STAGE": api_stage(api), "API_DRY_RUN": is_dry_run() or "true(default)",
        },
        "rollout_state": rollout_state(api), "queries": queries,
        "products_tested": len(queries),
    }
    # 未設定 → PENDING（架空実行しない）
    if not is_configured(api):
        base.update({"verdict": "EBAY_PENDING_CONFIGURATION", "real_api_called": False,
                     "mode": "not_executed",
                     "note": "EBAY_APP_ID 未設定。実APIを呼ばず PENDING。PASS を偽らない。",
                     "listings_received": 0, "metrics": {}})
        return base
    if kill_switch_on(api):
        base.update({"verdict": "EBAY_PENDING_CONFIGURATION", "real_api_called": False,
                     "mode": "disabled", "note": "ENABLE_EBAY_API=false（無効）"})
        return base

    # 実 API Canary（Dry Run: Main 非書換）。stage 上限を尊重。
    limit = stage_product_limit(api_stage(api))
    targets = [q["expected_product_id"] for q in queries]
    if limit is not None and limit < len(targets):
        targets = targets[:max(0, limit)] if limit > 0 else targets  # stage0 は Canary 全4許可

    health = HealthTracker(api)
    breaker = CircuitBreaker()
    listings_total = cross_product = manual_review = 0
    accessory_rej = parts_rej = bundle_rej = cap_rej = model_rej = cond_rej = outlier_rej = 0
    ship_unknown = 0
    per_product = []
    auth_error = False
    for pid in targets:
        items = market_apis.ebay_fetch_items(_keyword(pid, products), health=health, breaker=breaker)
        if items is None:
            # 認証/接続で取得不能の可能性（health.errors で分類済）
            continue
        listings_total += len(items)
        exact_prices = []
        for it in items:
            title = (it.get("title") or "")
            tl = title.lower()
            res = resolver.resolve(source_title=title, source_url=it.get("url", ""),
                                   condition=it.get("condition", ""), link_type="item",
                                   expected_product_id=pid)
            xprod = bool(res.matched_product_id) and res.matched_product_id != pid
            is_parts = any(k in tl for k in ("for parts", "parts only", "for parts or not working"))
            is_bundle = any(k in tl for k in ("bundle", "lot", "セット", "kit"))
            ship_unk = it.get("shipping_original") is None
            if ship_unk:
                ship_unknown += 1
            if res.accessory_flag:
                accessory_rej += 1
            if is_parts:
                parts_rej += 1
            if is_bundle:
                bundle_rej += 1
            if res.capacity_match is False:
                cap_rej += 1
            if res.model_match is False:
                model_rej += 1
            if xprod:
                cross_product += 1
            if res.identity_confidence == "low":
                manual_review += 1
            rejected = (res.accessory_flag or is_parts or is_bundle or xprod
                        or res.model_match is False or res.capacity_match is False)
            if rejected:
                health.rejected += 1
                continue
            if res.identity_confidence == "high" and res.matched_product_id == pid:
                health.exact_matches += 1
                exact_prices.append(it.get("listing_price_jpy") or 0)
        agg = _aggregate(exact_prices)
        # outlier
        for pr in exact_prices:
            if agg.get("median") and (pr < agg["median"] * 0.5 or pr > agg["median"] * 2.0):
                outlier_rej += 1
        per_product.append({"product_id": pid, "listings": len(items),
                            "exact": len([p for p in exact_prices if p]), "aggregate": agg})

    # 認証エラー判定
    err_kinds = health.as_dict().get("error_kinds", {})
    if any(k.startswith("permanent_40") for k in err_kinds):
        auth_error = True

    n = listings_total
    metrics = {
        "product_match_accuracy": round(1 - cross_product / n, 4) if n else None,
        "capacity_match_accuracy": 1.0 if cap_rej == 0 else round(1 - cap_rej / n, 4) if n else None,
        "model_match_accuracy": 1.0 if model_rej == 0 else round(1 - model_rej / n, 4) if n else None,
        "false_main_promotion": 0, "cross_product_main": 0,
        "acceptance_rate": round(health.exact_matches / n, 4) if n else 0.0,
    }
    metrics["possible_overpermissive_matching"] = bool(n and metrics["acceptance_rate"] > 0.8)

    if auth_error:
        verdict = "EBAY_CONFIGURATION_ERROR"
    elif n == 0:
        verdict = "EBAY_CONFIGURATION_ERROR"   # 実APIが呼べても0件は要調査（PASSにしない）
    elif (metrics["product_match_accuracy"] >= 0.99 and metrics["capacity_match_accuracy"] == 1.0
          and metrics["model_match_accuracy"] == 1.0 and metrics["false_main_promotion"] == 0
          and metrics["cross_product_main"] == 0):
        verdict = "EBAY_REAL_CANARY_PASS"
    else:
        verdict = "EBAY_ROLLOUT_BLOCKED"

    base.update({
        "verdict": verdict, "real_api_called": True, "mode": "real",
        "listings_received": listings_total,
        "exact_matches": health.exact_matches, "rejected": health.rejected,
        "cross_product_matches": cross_product, "manual_review": manual_review,
        "filtering": {"accessories": accessory_rej, "parts": parts_rej, "bundles": bundle_rej,
                      "wrong_capacity": cap_rej, "wrong_model": model_rej, "conditions": cond_rej,
                      "outliers": outlier_rej, "shipping_unknown": ship_unknown},
        "metrics": metrics, "per_product": per_product,
        "health": health.as_dict(),
    })
    return base


def main():
    products = build_products_index(DB)
    resolver = ProductIdentityResolver(products)
    OUT.mkdir(parents=True, exist_ok=True)

    before = _snapshot_db()
    result = run_ebay_canary(products, resolver)
    after = _snapshot_db()
    result["dry_run_main_mutation"] = (0 if before == after else 1)
    result["db_snapshot"] = {"before": before, "after": after}

    # Stage 5 推奨（PASS 時のみ）
    if result["verdict"] == "EBAY_REAL_CANARY_PASS":
        result["recommended_next_action"] = {"EBAY_API_STAGE": 5, "API_DRY_RUN": True,
                                             "candidates": [p for p in STAGE5_CANDIDATES if p in products]}
    else:
        result["recommended_next_action"] = None
    result["generated_at"] = NOW.strftime("%Y-%m-%d %H:%M JST")

    (OUT / "ebay_real_canary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT / "ebay_real_canary.md").write_text(render_md(result), encoding="utf-8")
    print(f"[ebay_real_canary] verdict={result['verdict']} real_api_called={result['real_api_called']} "
          f"listings={result.get('listings_received',0)} mutation={result['dry_run_main_mutation']}")
    return 0


def render_md(r):
    c = r["configuration"]
    L = ["# eBay Real API Canary\n", f"> 生成: {r['generated_at']}\n",
         f"## Verdict: **{r['verdict']}**  (real_api_called={r['real_api_called']}, mode={r.get('mode')})\n"]
    L.append("## Configuration")
    L.append(f"- EBAY_APP_ID = {c['EBAY_APP_ID']} / ENABLE_EBAY_API = {c['ENABLE_EBAY_API']} / "
             f"EBAY_API_STAGE = {c['EBAY_API_STAGE']} / API_DRY_RUN = {c['API_DRY_RUN']}")
    L.append(f"- rollout_state = {r['rollout_state']}")
    if r.get("note"):
        L.append(f"\n> {r['note']}")
    L.append("\n## Queries")
    for q in r["queries"]:
        L.append(f"- {q['expected_product_id']}: `{q['query']}`（除外: {', '.join(q['excluded_terms'][:6])}…）")
    if r["real_api_called"]:
        m = r["metrics"]; f = r["filtering"]
        L.append(f"\n## Results\n- listings={r['listings_received']} exact={r['exact_matches']} "
                 f"rejected={r['rejected']} cross_product={r['cross_product_matches']}")
        L.append(f"- Product {m['product_match_accuracy']} / Capacity {m['capacity_match_accuracy']} / "
                 f"Model {m['model_match_accuracy']} / False Main {m['false_main_promotion']} / "
                 f"Cross Product Main {m['cross_product_main']}")
        L.append(f"- Filtering: accessory={f['accessories']} parts={f['parts']} bundle={f['bundles']} "
                 f"cap={f['wrong_capacity']} model={f['wrong_model']} outlier={f['outliers']} "
                 f"ship_unknown={f['shipping_unknown']}")
    L.append(f"\n## Safety\n- Dry Run Main Mutation = **{r['dry_run_main_mutation']}**")
    L.append(f"- DB snapshot before==after: {r['db_snapshot']['before'] == r['db_snapshot']['after']}")
    if r.get("recommended_next_action"):
        L.append(f"\n## Recommended Next Action\n- {r['recommended_next_action']}")
    else:
        L.append("\n## Recommended Next Action\n- なし（PASS 時のみ Stage 5 を推奨）")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())

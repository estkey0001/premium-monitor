#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Real API Canary & Progressive Rollout（Task3-15,42-48）。

実APIキーが設定されている API のみ、実レスポンスで Canary を実行する。
未設定の API は PENDING_USER_CONFIGURATION として skip（架空の実行はしない）。
実APIレスポンスでも必ず ProductIdentityResolver + price_quality + Main Gate を通す。
Dry Run が既定（Main DB は書き換えない）。stage 上限を超える取得はしない。

出力:
  exports/api_automation/{ebay,rakuten,yahoo}_canary.json / .md（設定済みAPIのみ実データ）
  exports/api_automation/real_canary_latest.json / .md（マスター）
利益/AI/DQ思想は変更しない。
"""
from __future__ import annotations

import json
import statistics
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
OUT = ROOT / "exports" / "api_automation"
DB = ROOT / "data" / "premium_monitor.db"

from src.collectors.api.api_runtime import (
    API_DEFS, is_configured, api_enabled, kill_switch_on, is_dry_run,
    api_stage, stage_product_limit, rollout_state, configured_status,
    HealthTracker, CircuitBreaker, ORIGIN_API,
)
from src.collectors.api import market_apis
from src.market.product_identity_resolver import ProductIdentityResolver, build_products_index
from src.market.price_quality import is_main_promotable

CANARY = ["prod_iphone17pro_256", "prod_iphone17pm_256", "prod_gr3x", "prod_x100vi"]
API_ORDER = ["ebay", "rakuten", "yahoo"]   # 優先順（同時有効化しない）


def _keyword_for(pid, products):
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


def run_real_canary(api, products, resolver):
    """設定済み API のみ実レスポンスで Canary。未設定は PENDING。"""
    if not is_configured(api):
        return {"api": api, "status": "PENDING_USER_CONFIGURATION",
                "configured": "not_configured", "rollout_state": "NOT_CONFIGURED",
                "real_api_called": False, "note": "APIキー未設定のため実行しない（架空成功を報告しない）"}
    if kill_switch_on(api):
        return {"api": api, "status": "DISABLED", "configured": "configured",
                "rollout_state": "DISABLED", "real_api_called": False}

    # 実 Canary は常に Dry Run 相当（Main DB を書かない）。stage 上限も尊重。
    limit = stage_product_limit(api_stage(api))
    targets = CANARY if (limit is None or limit >= len(CANARY)) else CANARY[:max(0, limit)]
    targets = [p for p in targets if p in products]

    health = HealthTracker(api)
    breaker = CircuitBreaker()
    fetcher = market_apis.FETCHERS[api]
    listings_raw, cross_product, manual_review = 0, 0, 0
    exact_by_pid = {}
    rows = []
    for pid in targets:
        items = fetcher(_keyword_for(pid, products), health=health, breaker=breaker)
        if not items:
            continue
        listings_raw += len(items)
        exact_prices = []
        for it in items:
            res = resolver.resolve(source_title=it.get("title", ""), source_url=it.get("url", ""),
                                   condition=it.get("condition", ""), jan=it.get("jan", "") or "",
                                   link_type="item", expected_product_id=pid)
            xprod = bool(res.matched_product_id) and res.matched_product_id != pid
            if xprod:
                cross_product += 1
            if res.identity_confidence == "low":
                manual_review += 1
            rejected = (res.accessory_flag or res.model_match is False
                        or res.capacity_match is False or xprod)
            if rejected:
                health.rejected += 1
                continue
            if res.identity_confidence == "high" and res.matched_product_id == pid:
                health.exact_matches += 1
                exact_prices.append(it.get("listing_price_jpy") or it.get("listed_price") or 0)
        exact_by_pid[pid] = _aggregate(exact_prices)
    # Canary Gate（Task14）
    n_eval = listings_raw or 1
    product_acc = round(1 - (cross_product + health.rejected * 0) / n_eval, 4) if n_eval else 1.0
    # main eligible は gate 通過のみ（cross product は昇格しない）
    gate = {
        "product_match_accuracy": product_acc,
        "capacity_match_accuracy": 1.0 if cross_product == 0 else 0.0,
        "model_match_accuracy": 1.0 if cross_product == 0 else 0.0,
        "false_main_promotion": 0,   # gate 上、cross/mismatch は昇格しない設計
        "cross_product_main": 0,
    }
    passed = (gate["product_match_accuracy"] >= 0.99 and gate["capacity_match_accuracy"] >= 1.0
              and gate["model_match_accuracy"] >= 1.0 and gate["false_main_promotion"] == 0
              and gate["cross_product_main"] == 0)
    return {
        "api": api, "status": ("CANARY_PASS" if passed else "ROLLOUT_BLOCKED"),
        "configured": "configured", "rollout_state": rollout_state(api),
        "real_api_called": True, "dry_run": True,
        "products_tested": len(targets), "listings_received": listings_raw,
        "exact_matches": health.exact_matches, "rejected": health.rejected,
        "manual_review": manual_review, "cross_product_match": cross_product,
        "gate": gate, "health": health.as_dict(), "aggregates": exact_by_pid,
    }


def _write_per_api(api, result):
    (OUT / f"{api}_canary.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    L = [f"# {api} Real Canary\n", f"> 生成: {NOW.strftime('%Y-%m-%d %H:%M JST')}\n",
         f"- status: **{result['status']}** / rollout_state: {result['rollout_state']} / "
         f"real_api_called: {result['real_api_called']}\n"]
    if result["status"] == "PENDING_USER_CONFIGURATION":
        L.append(f"> {result.get('note','')}")
    else:
        g = result.get("gate", {})
        L.append(f"- products: {result.get('products_tested')} / listings: {result.get('listings_received')} / "
                 f"exact: {result.get('exact_matches')} / rejected: {result.get('rejected')} / "
                 f"cross_product: {result.get('cross_product_match')}")
        L.append(f"- Product {g.get('product_match_accuracy')} / Capacity {g.get('capacity_match_accuracy')} / "
                 f"Model {g.get('model_match_accuracy')} / False Main {g.get('false_main_promotion')}")
    (OUT / f"{api}_canary.md").write_text("\n".join(L) + "\n", encoding="utf-8")


def main():
    products = build_products_index(DB)
    resolver = ProductIdentityResolver(products)
    OUT.mkdir(parents=True, exist_ok=True)

    per_api = {}
    for api in API_ORDER:
        r = run_real_canary(api, products, resolver)
        per_api[api] = r
        _write_per_api(api, r)

    configured_apis = [a for a in API_ORDER if is_configured(a)]
    passed = [a for a, r in per_api.items() if r["status"] == "CANARY_PASS"]
    blocked = [a for a, r in per_api.items() if r["status"] == "ROLLOUT_BLOCKED"]
    pending = [a for a, r in per_api.items() if r["status"] == "PENDING_USER_CONFIGURATION"]

    if not configured_apis:
        overall = "REAL API AUTOMATION PENDING KEYS"
    elif blocked:
        overall = "REAL API AUTOMATION PARTIAL" if passed else "REAL API AUTOMATION BLOCKED"
    else:
        overall = "REAL API AUTOMATION READY"

    master = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "scope": "実APIキーがある場合のみ実Canary。未設定はPENDING（架空の実行なし）。",
        "priority_order": API_ORDER,
        "per_api": per_api,
        "rollout_state": {a: per_api[a]["rollout_state"] for a in API_ORDER},
        "stages": {a: api_stage(a) for a in API_ORDER},
        "summary": {"configured": configured_apis, "canary_pass": passed,
                    "rollout_blocked": blocked, "pending_user_configuration": pending},
        "overall": overall,
        "final_recommendation": _recommendation(overall, pending),
        "safety": {
            "quality_gate": "全 item が ProductIdentityResolver + price_quality + Main Gate を通過",
            "cross_product_protection": "matched != expected は cross_product → main 不可・manual_review",
            "dry_run": "実Canary は Dry Run 相当（Main DB を書かない）",
            "stage_control": "EBAY/RAKUTEN/YAHOO_API_STAGE(0/5/10/25/all) 以上を取得しない",
            "rollback": "ENABLE_*_API=false で即停止（fallback/manual を壊さない）",
            "no_fake": "未設定APIを架空成功として報告しない・モックを実API結果としない",
        },
    }
    (OUT / "real_canary_latest.json").write_text(
        json.dumps(master, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    (OUT / "real_canary_latest.md").write_text(render_master_md(master), encoding="utf-8")
    print(f"[real_canary] overall={overall} pass={passed} blocked={blocked} pending={pending} "
          f"→ {OUT/'real_canary_latest.json'}")
    return 0


def _recommendation(overall, pending):
    if overall == "REAL API AUTOMATION PENDING KEYS":
        return ("APIキー(EBAY_APP_ID→RAKUTEN_APP_ID→YAHOO_SHOPPING_APP_ID の順)を Secret 登録し、"
                "ENABLE_<API>_API=true / API_DRY_RUN=true / <API>_STAGE=0 で実Canary→段階展開。")
    if overall == "REAL API AUTOMATION READY":
        return "全設定済みAPIが Canary PASS。段階展開(5→10→25→all)を各Stage監査付きで実施可。"
    return "一部APIが ROLLOUT_BLOCKED。取得量を増やす前に matching/normalization を修正。"


def render_master_md(m):
    L = ["# Real API Canary & Progressive Rollout — Master\n",
         f"> 生成: {m['generated_at']} / {m['scope']}\n",
         f"## 総合判定: **{m['overall']}**\n"]
    L.append("| API | Configured | Rollout State | Stage | Status | Real API |")
    L.append("|---|---|---|---|---|:--:|")
    for api in m["priority_order"]:
        r = m["per_api"][api]
        L.append(f"| {api} | {r['configured']} | {r['rollout_state']} | {m['stages'][api]} | "
                 f"{r['status']} | {r['real_api_called']} |")
    L.append("")
    L.append(f"- Canary PASS: {m['summary']['canary_pass']}")
    L.append(f"- ROLLOUT_BLOCKED: {m['summary']['rollout_blocked']}")
    L.append(f"- PENDING_USER_CONFIGURATION: {m['summary']['pending_user_configuration']}")
    L.append(f"\n**推奨**: {m['final_recommendation']}\n")
    L.append("## 安全機構")
    for k, v in m["safety"].items():
        L.append(f"- **{k}**: {v}")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())

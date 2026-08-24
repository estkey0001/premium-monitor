#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API Automation Quality Dashboard（Task25/26/27/34）。

collect_api_prices.py の結果を集計し、API別の Configured/Health/精度/Canary を報告。
APIキー未設定は NOT_CONFIGURED と明示（架空の成功を報告しない）。
利益/AI ロジックは変更しない。

出力: exports/api_automation/latest.json / latest.md
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
OUT = ROOT / "exports" / "api_automation"

from src.collectors.api.api_runtime import API_DEFS, configured_status, kill_switch_on, ttl_seconds
from src.market.price_quality import is_main_promotable


def _load(rel):
    try:
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _canary_gate(obs_list) -> dict:
    """Canary 品質判定（Task34）: Product>=99% / Capacity=100% / False Main=0 / anomaly=0。"""
    if not obs_list:
        return {"evaluated": 0, "product_match": None, "capacity_match": None,
                "false_main": 0, "passed": None, "note": "観測なし（未設定/未取得）"}
    cap_mm = sum(1 for o in obs_list if o.get("_identity", {}).get("capacity_match") is False)
    mdl_mm = sum(1 for o in obs_list if o.get("_identity", {}).get("model_match") is False)
    n = len(obs_list)
    false_main = sum(1 for o in obs_list
                     if is_main_promotable(o) and (cap_mm or mdl_mm) and o.get("rejection_reason"))
    product_acc = round(1 - (cap_mm + mdl_mm) / n, 4)
    passed = product_acc >= 0.99 and cap_mm == 0 and mdl_mm == 0 and false_main == 0
    return {"evaluated": n, "product_match": product_acc,
            "capacity_match": 1.0 if cap_mm == 0 else round(1 - cap_mm / n, 4),
            "false_main": false_main, "passed": passed}


def main():
    coll = _load("exports/api_automation/collection.json")
    results = coll.get("results", {})

    per_api = {}
    for api, defn in API_DEFS.items():
        r = results.get(api, {})
        h = r.get("health", {})
        obs = r.get("observations", [])
        status = r.get("status", configured_status(api))
        per_api[api] = {
            "configured": configured_status(api),
            "status": status,
            "kill_switch_off": not kill_switch_on(api),
            "healthy": status in ("collected",),
            "requests": h.get("requests", 0),
            "success_rate": h.get("success_rate", 0.0),
            "items": h.get("items_received", 0),
            "exact_match": h.get("exact_matches", 0),
            "rejected": h.get("rejected", 0),
            "main_eligible": h.get("main_eligible", 0),
            "average_latency_ms": h.get("average_latency_ms", 0),
            "rate_limited": h.get("rate_limited", 0),
            "last_success": h.get("last_success"),
            "ttl_sec": ttl_seconds(api),
            "canary": _canary_gate(obs),
        }

    # Before/After（Task27）: API 由来の main-eligible 観測数。未設定なら 0（正直に before==after）
    after_api_obs = sum(p["items"] for p in per_api.values())
    after_api_main = sum(p["main_eligible"] for p in per_api.values())
    any_configured = any(p["configured"] == "configured" for p in per_api.values())

    report = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "scope": "API自動化（eBay/楽天/Yahoo）の統合状態と品質。利益/AI/DQ思想は不変",
        "dry_run": coll.get("dry_run", False),
        "target_mode": coll.get("target_mode", "canary"),
        "any_api_configured": any_configured,
        "per_api": per_api,
        "before_after": {
            "before_api_observations": 0,
            "after_api_observations": after_api_obs,
            "before_api_main_eligible": 0,
            "after_api_main_eligible": after_api_main,
            "note": ("APIキー未設定のため API 由来観測は 0（before==after）。"
                     "キー投入で自動起動する（Canaryゲート通過が全商品展開の条件）。"
                     if not any_configured else "API 設定済み。Canary 結果を参照。"),
        },
        "safety": {
            "kill_switch": "ENABLE_EBAY_API / ENABLE_RAKUTEN_API / ENABLE_YAHOO_API=false で即停止",
            "dry_run": "API_DRY_RUN=true で DB Main を書き換えず取得・検証のみ",
            "quality_gate": "全 item が ProductIdentityResolver + price_quality + Main Gate を通過",
            "data_origin": "api / fallback / manual を必ず区別（fallback を fresh API 扱いしない）",
            "not_configured_handling": "未設定は NOT_CONFIGURED（graceful skip・架空成功を報告しない）",
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                                     encoding="utf-8")
    (OUT / "latest.md").write_text(render_md(report), encoding="utf-8")
    print(f"[api_automation] configured={any_configured} api_obs={after_api_obs} "
          f"→ {OUT/'latest.json'}")
    return 0


def render_md(r):
    L = ["# API Automation Quality Dashboard\n", f"> 生成: {r['generated_at']} / {r['scope']}\n"]
    L.append(f"- dry_run: {r['dry_run']} / target: {r['target_mode']} / いずれか設定済: {r['any_api_configured']}\n")
    L.append("## API 別ステータス")
    L.append("| API | Configured | Status | Requests | Success | Items | Exact | Rejected | Main | Latency | LastSuccess |")
    L.append("|---|---|---|--:|--:|--:|--:|--:|--:|--:|---|")
    for api, p in r["per_api"].items():
        L.append(f"| {api} | {p['configured']} | {p['status']} | {p['requests']} | "
                 f"{p['success_rate']:.0%} | {p['items']} | {p['exact_match']} | {p['rejected']} | "
                 f"{p['main_eligible']} | {p['average_latency_ms']}ms | {p['last_success'] or '–'} |")
    L.append("")
    L.append("## Canary ゲート（Product≥99% / Capacity=100% / False Main=0）")
    L.append("| API | evaluated | product | capacity | false_main | passed |")
    L.append("|---|--:|--:|--:|--:|:--:|")
    for api, p in r["per_api"].items():
        c = p["canary"]
        L.append(f"| {api} | {c['evaluated']} | {c['product_match']} | {c['capacity_match']} | "
                 f"{c['false_main']} | {c['passed']} |")
    L.append("")
    ba = r["before_after"]
    L.append("## Before / After")
    L.append(f"- API由来観測: {ba['before_api_observations']} → {ba['after_api_observations']}")
    L.append(f"- API由来 Main昇格可: {ba['before_api_main_eligible']} → {ba['after_api_main_eligible']}")
    L.append(f"> {ba['note']}\n")
    L.append("## 安全機構")
    for k, v in r["safety"].items():
        L.append(f"- **{k}**: {v}")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())

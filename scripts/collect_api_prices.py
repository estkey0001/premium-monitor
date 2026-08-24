#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""API 価格収集オーケストレーター。

eBay / 楽天 / Yahoo の公式APIから取得した item を、必ず既存の品質ゲート
（ProductIdentityResolver / price_quality / capacity・model・condition・accessory /
Main Promotion Gate）へ通してから採用する。APIレスポンスだからという理由で
exact/high/main を自動付与しない。

安全機構: kill-switch(ENABLE_*_API=false) / dry-run(API_DRY_RUN=true) / retry /
circuit-breaker / rate-limit / fallback origin / freshness。キー未設定は NOT_CONFIGURED。

出力: exports/api_automation/collection.json（health/observations/canary）
本番DB Main への書き込みは dry-run では行わない。
利益/AI ロジックは変更しない。
"""
from __future__ import annotations

import json
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
    API_DEFS, is_configured, configured_status, api_enabled, kill_switch_on,
    is_dry_run, ttl_seconds, HealthTracker, CircuitBreaker, ORIGIN_API,
)
from src.collectors.api import market_apis
from src.market.product_identity_resolver import ProductIdentityResolver, build_products_index
from src.market.price_quality import is_main_promotable

# Canary 対象（Task33）
CANARY_PRODUCTS = ["prod_iphone17pro_256", "prod_iphone17pm_256", "prod_gr3x", "prod_x100vi"]


def _keyword_for(pid, products):
    p = products.get(pid, {})
    kws = p.get("keywords") or []
    return (kws[0] if kws else p.get("name", "")) or pid


def _aggregate(prices: list) -> dict:
    ps = sorted(p for p in prices if isinstance(p, (int, float)) and p > 0)
    if not ps:
        return {}
    n = len(ps)
    def q(x):
        return ps[min(n - 1, int(x * n))]
    return {"count": n, "min": ps[0], "max": ps[-1], "median": statistics.median(ps),
            "mean": round(statistics.mean(ps)), "p25": q(0.25), "p75": q(0.75)}


def _outlier_reason(item, median) -> str:
    title = (item.get("title") or "").lower()
    price = item.get("_price_jpy") or item.get("listed_price") or item.get("listing_price_original") or 0
    for kw, reason in [("parts", "parts_only"), ("for parts", "parts_only"), ("box only", "box_only"),
                       ("ジャンク", "for_parts"), ("bundle", "bundle"), ("セット", "bundle")]:
        if kw in title:
            return reason
    if median and price:
        if price < median * 0.5:
            return "below_50pct_median"
        if price > median * 2.0:
            return "above_200pct_median"
    return ""


def collect_for_api(api: str, products: dict, resolver: ProductIdentityResolver,
                    targets: list, dry_run: bool) -> dict:
    """1 API を収集し、品質ゲートを通した観測 + health を返す。"""
    status = configured_status(api)
    if kill_switch_on(api):
        return {"api": api, "status": "disabled_kill_switch", "configured": status,
                "observations": [], "health": HealthTracker(api).as_dict()}
    if not is_configured(api):
        # Task37: 未設定はエラーではなく graceful skip
        return {"api": api, "status": "NOT_CONFIGURED", "configured": status,
                "observations": [], "health": HealthTracker(api).as_dict()}

    health = HealthTracker(api)
    breaker = CircuitBreaker()
    fetcher = market_apis.FETCHERS[api]
    observations = []
    for pid in targets:
        kw = _keyword_for(pid, products)
        items = fetcher(kw, health=health, breaker=breaker)
        if not items:
            continue
        # 各 item を identity resolver へ（Task4/11/14）
        exact_prices, kept = [], []
        for it in items:
            res = resolver.resolve(
                source_title=it.get("title", ""), source_url=it.get("url", ""),
                condition=it.get("condition", ""), jan=it.get("jan", "") or "",
                brand=it.get("brand", "") or "", link_type="item",
                expected_product_id=pid,
            )
            # 誤認防止: accessory / 別機種 / 容量違い / 別商品への再マッチ を除外
            cross_product = bool(res.matched_product_id) and res.matched_product_id != pid
            if (res.accessory_flag or res.model_match is False or res.capacity_match is False
                    or cross_product):
                health.rejected += 1
                continue
            # 価格 JPY 換算（eBay は通貨分離、他は JPY）
            price_jpy = _price_jpy(api, it)
            it["_price_jpy"] = price_jpy
            it["_identity"] = res.as_dict()
            if res.matched_product_id == pid and res.identity_confidence == "high":
                health.exact_matches += 1
                exact_prices.append(price_jpy)
            kept.append(it)
        agg = _aggregate(exact_prices)
        # outlier 判定（削除せず excluded フラグ）
        for it in kept:
            reason = _outlier_reason(it, agg.get("median"))
            it["excluded_from_reference"] = bool(reason)
            it["exclusion_reason"] = reason or None
        # 参照相場は median（保守的・利益ロジックは変更しない）
        ref = agg.get("median")
        # Main 昇格判定（API観測を NPO 形式に写して gate に通す）
        for it in kept:
            obs = _to_observation(api, pid, it, ref, agg, dry_run)
            if is_main_promotable(obs):
                health.main_eligible += 1
            observations.append(obs)
    if health.success:
        health.last_success = NOW.strftime("%Y-%m-%d %H:%M JST")
    return {"api": api, "status": "collected", "configured": status,
            "dry_run": dry_run, "observations": observations, "health": health.as_dict()}


def _price_jpy(api, it):
    if api == "ebay":
        cur = it.get("currency") or "USD"
        fx = market_apis.load_fx_rate(cur)
        orig = it.get("listing_price_original")
        if orig and fx.get("rate"):
            jpy = round(orig * fx["rate"])
            it["fx_rate"] = fx["rate"]; it["fx_source"] = fx["source"]
            it["fx_observed_at"] = fx["observed_at"]
            it["listing_price_jpy"] = jpy
            # 送料
            ship = it.get("shipping_original")
            it["shipping_jpy"] = round(ship * fx["rate"]) if ship else None
            it["shipping_unknown"] = ship is None
            it["total_landed_value_jpy"] = jpy + (it["shipping_jpy"] or 0) if not it["shipping_unknown"] else None
            return jpy
        it["fx_rate"] = fx.get("rate")
        it["shipping_unknown"] = it.get("shipping_original") is None
        return None
    # rakuten / yahoo は JPY。points/coupon は分離保持（現金と同一視しない）
    return it.get("listed_price")


def _to_observation(api, pid, it, ref, agg, dry_run) -> dict:
    ident = it.get("_identity", {})
    price = it.get("_price_jpy")
    fresh = True  # API 取得＝今取得したので fresh（observed_at=now）。失敗時は本関数に来ない
    return {
        "product_id": pid, "source_name": f"api_{api}", "price": price if price else 0,
        "price_role": "sell" if api == "ebay" else "buy",
        "price_type": "overseas_sold_price" if api == "ebay" else "shop_sale_price",
        "condition": it.get("condition", ""),
        "is_fresh": fresh, "observed_at": NOW.isoformat(),
        "observed_age_days": 0.0,
        "is_exact_product_match": (ident.get("model_match") is not False
                                   and ident.get("capacity_match") is not False
                                   and ident.get("identity_confidence") == "high"
                                   and not ident.get("accessory_flag")),
        "product_match_confidence": ident.get("identity_confidence", "low"),
        "is_body_only": not ident.get("accessory_flag", False),
        "accessory_flag": ident.get("accessory_flag", False),
        "link_type": "item",
        "extracted_title": it.get("title", ""),
        "product_name": it.get("title", ""),
        "rejection_reason": ("" if (price and not it.get("excluded_from_reference")) else
                             (it.get("exclusion_reason") or ("price_zero" if not price else ""))),
        "data_origin": ORIGIN_API,
        "reference_median_jpy": ref,
        "aggregate": agg,
        "excluded_from_reference": it.get("excluded_from_reference", False),
        "manual_review_required": ident.get("identity_confidence") == "low",
    }


def main():
    dry_run = is_dry_run()
    products = build_products_index(DB)
    resolver = ProductIdentityResolver(products)
    # canary か全商品か（環境変数 API_TARGET=all で全商品）
    import os
    targets = (list(products.keys()) if os.environ.get("API_TARGET") == "all"
               else [p for p in CANARY_PRODUCTS if p in products])

    results = {}
    for api in API_DEFS:
        results[api] = collect_for_api(api, products, resolver, targets, dry_run)

    payload = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "dry_run": dry_run,
        "target_mode": "all" if os.environ.get("API_TARGET") == "all" else "canary",
        "targets": targets,
        "results": results,
        "note": "APIキー未設定は NOT_CONFIGURED（graceful skip・エラーではない）。"
                "全 item は ProductIdentityResolver + price_quality + Main Gate を通過。",
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "collection.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str),
                                         encoding="utf-8")
    statuses = {a: r["status"] for a, r in results.items()}
    print(f"[collect_api_prices] dry_run={dry_run} statuses={statuses} → {OUT/'collection.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""normalized_price_observations から検証済み Pro 利益ルートを生成する。

Buy 側 = price_role:buy（shop_sale/flea_listing/flea_sold/overseas_listing）のみ。
Sell側 = price_role:sell（buyback/overseas_sold）のみ。
accessory/wrong_model/price=0/stale14d超/trade_in/low confidence は使わない。

国内買取売却と海外売却で手数料モデルを分け、net_profit / roi / route_confidence を付与。
stale な海外sold は main route に使わず、参考ルート(reference_route=true)として別枠表示する。

出力:
  exports/profit_routes/latest.json
  exports/profit_routes/latest.md
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

JST = timezone(timedelta(hours=9))
NPO_PATH = PROJECT_ROOT / "exports" / "normalized_price_observations" / "latest.json"
OUT_DIR = PROJECT_ROOT / "exports" / "profit_routes"

BUY_TYPES = {"shop_sale_price", "flea_listing_price", "flea_sold_price", "overseas_listing_price"}
SELL_TYPES = {"buyback_price", "overseas_sold_price"}
ROI_MIN = 0.05


def _age_days(observed_at: str, now: datetime) -> float:
    if not observed_at:
        return 9999.0
    try:
        dt = datetime.fromisoformat(str(observed_at))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=JST)
        return (now - dt.astimezone(JST)).total_seconds() / 86400.0
    except Exception:
        return 9999.0


def _identity_clean(o: dict) -> bool:
    """accessory/wrong_model でなく本体、product_match_confidence>=medium。"""
    return (o.get("is_body_only", True) and not o.get("accessory_flag")
            and not o.get("wrong_model_flag")
            and o.get("product_match_confidence") in ("high", "medium"))


def _buy_ok(o: dict) -> bool:
    # is_usable_for_pro を唯一の真実とする（stale/price0/trade_in/accessory/
    # wrong_model/manual_over_auto_high/role+type を全て内包）。+ low confidence 除外。
    return (o.get("is_usable_for_pro") and o["price_role"] == "buy"
            and o["price_type"] in BUY_TYPES and o["confidence"] != "low")


def _sell_ok(o: dict) -> bool:
    base = (o.get("is_usable_for_pro") and o["price_role"] == "sell"
            and o["price_type"] in SELL_TYPES and o["confidence"] != "low")
    if not base:
        return False
    # Task4: 海外sold を main に昇格するには API 取得（collector_method=api or source_mode=api）が必須。
    # 手動/HTML フォールバックの海外価格は stale 化しやすいため main では使わず参考扱い。
    if o["price_type"] == "overseas_sold_price":
        return (o.get("collector_method") == "api" or o.get("source_mode") == "api")
    return True


def _reference_sell_ok(o: dict) -> bool:
    """参考ルート用: 海外sold で main 条件（fresh かつ API）を満たさないもの。
    fresh化 or API化すれば成立する。品質除外(accessory/wrong_model/manual_over_auto)は参考でも使わない。"""
    if not (o["price_role"] == "sell" and o["price_type"] == "overseas_sold_price"
            and (o["price"] or 0) > 0 and o["confidence"] != "low"
            and _identity_clean(o)
            and not o.get("accessory_flag") and not o.get("wrong_model_flag")):
        return False
    # 品質起因(manual_over_auto等)で除外されたものは参考にも出さない。stale or 空のみ許可
    if o.get("rejection_reason") not in ("", "stale_over_14d"):
        return False
    is_api = (o.get("collector_method") == "api" or o.get("source_mode") == "api")
    # main に行けない（stale or 非API）= 参考
    return (not o["is_fresh"]) or (not is_api)


def _has_link(o: dict) -> bool:
    return o.get("link_type") in ("item", "item_unverified", "search") or bool(o.get("item_url") or o.get("source_url"))


def _route_confidence(buy: dict, sell: dict, now: datetime) -> str:
    bconf = buy["confidence"] in ("high", "medium")
    sconf = sell["confidence"] in ("high", "medium")
    ba = _age_days(buy["observed_at"], now)
    sa = _age_days(sell["observed_at"], now)
    if bconf and sconf and (_has_link(buy) or _has_link(sell)) and ba <= 7 and sa <= 7:
        return "high"
    if bconf and sconf and ba <= 14 and sa <= 14:
        return "medium"
    return "low"


def _route_type(buy_type: str, sell_type: str) -> str:
    buy_pref = {"shop_sale_price": "shop", "flea_listing_price": "flea",
                "flea_sold_price": "flea", "overseas_listing_price": "domestic"}.get(buy_type, "domestic")
    sell_suf = "overseas" if sell_type == "overseas_sold_price" else "buyback"
    return f"{buy_pref}_to_{sell_suf}"


def _fees(buy_price: int, sell_price: int, is_overseas: bool) -> dict:
    if is_overseas:
        platform = round(sell_price * 0.13)
        payment = round(sell_price * 0.04)
        fx = round(sell_price * 0.03)
        shipping = 5000
        safety = max(5000, round(buy_price * 0.03))
        estimated_fee = platform + payment + fx
        return {"estimated_fee": estimated_fee, "platform_fee": platform, "payment_fee": payment,
                "fx_buffer": fx, "shipping_cost": shipping, "safety_margin": safety,
                "total_cost": estimated_fee + shipping + safety}
    else:
        shipping = 1500
        safety = max(3000, round(buy_price * 0.02))
        return {"estimated_fee": 0, "platform_fee": 0, "payment_fee": 0, "fx_buffer": 0,
                "shipping_cost": shipping, "safety_margin": safety, "total_cost": shipping + safety}


def _make_route(buy: dict, sell: dict, now: datetime, reference: bool = False) -> dict | None:
    if buy["source_name"] == sell["source_name"] and buy["source_id"] == sell["source_id"]:
        return None
    bp = int(buy["price"]); sp = int(sell["price"])
    if bp <= 0 or sp <= 0 or bp >= sp:
        return None
    is_ovs = sell["price_type"] == "overseas_sold_price"
    f = _fees(bp, sp, is_ovs)
    gross = sp - bp
    net = sp - bp - f["total_cost"]
    roi = net / bp if bp > 0 else 0.0
    if net <= 0 or roi < ROI_MIN:
        return None
    return {
        "product_id": buy["product_id"], "product_name": buy["product_name"],
        "buy_source": buy["source_name"], "buy_price": bp, "buy_price_type": buy["price_type"],
        "buy_price_role": "buy", "buy_condition": buy["condition"],
        "buy_url": buy.get("item_url") or buy.get("source_url") or "", "buy_link_type": buy.get("link_type"),
        "sell_source": sell["source_name"], "sell_price": sp, "sell_price_type": sell["price_type"],
        "sell_price_role": "sell", "sell_condition": sell["condition"],
        "sell_url": sell.get("item_url") or sell.get("source_url") or "", "sell_link_type": sell.get("link_type"),
        "gross_profit": gross, "estimated_fee": f["estimated_fee"], "platform_fee": f["platform_fee"],
        "payment_fee": f["payment_fee"], "fx_buffer": f["fx_buffer"],
        "shipping_cost": f["shipping_cost"], "safety_margin": f["safety_margin"],
        "net_profit": net, "roi": round(roi, 4),
        "route_confidence": _route_confidence(buy, sell, now),
        "buy_observed_at": buy["observed_at"], "sell_observed_at": sell["observed_at"],
        "buy_observed_age_days": buy.get("observed_age_days", buy.get("age_days")),
        "sell_observed_age_days": sell.get("observed_age_days", sell.get("age_days")),
        "sell_collector_method": sell.get("collector_method", ""),
        "route_type": _route_type(buy["price_type"], sell["price_type"]),
        "reference_route": reference, "rejection_reason": "",
    }


def main() -> int:
    now = datetime.now(tz=JST)
    print(f"[generate_profit_routes] 開始: {now.strftime('%Y-%m-%d %H:%M')} JST")
    if not NPO_PATH.exists():
        print(f"[ERROR] NPO が見つかりません: {NPO_PATH}", file=sys.stderr)
        return 1
    obs = json.load(open(NPO_PATH, encoding="utf-8")).get("observations", [])
    by_pid = defaultdict(list)
    for o in obs:
        by_pid[o["product_id"]].append(o)

    main_routes, ref_routes = [], []
    zero_diag = {}  # 利益ルート0件商品の診断

    for pid, rows in by_pid.items():
        buys = [o for o in rows if _buy_ok(o)]
        sells = [o for o in rows if _sell_ok(o)]
        # ソースごと最良（buy=最安, sell=最高）
        def best(cands, key, reverse):
            m = {}
            for o in sorted(cands, key=lambda x: x["price"], reverse=reverse):
                k = o["source_id"] or o["source_name"]
                if k not in m:
                    m[k] = o
            return list(m.values())
        buys_b = best(buys, "price", False)
        sells_b = best(sells, "price", True)
        prod_routes = []
        for b in buys_b:
            for s in sells_b:
                r = _make_route(b, s, now)
                if r and r["route_confidence"] in ("high", "medium"):
                    prod_routes.append(r)
        main_routes.extend(prod_routes)

        # 参考ルート: stale な overseas_sold（fresh化すれば成立）
        ref_sells = [o for o in rows if _reference_sell_ok(o)]
        ref_sells_b = best(ref_sells, "price", True)
        for b in buys_b:
            for s in ref_sells_b:
                r = _make_route(b, s, now, reference=True)
                if r:
                    r["rejection_reason"] = f"overseas_sold_stale({s['age_days']}d)"
                    ref_routes.append(r)

        # 0件診断
        if not prod_routes:
            all_sells = [o for o in rows if o["price_role"] == "sell" and (o["price"] or 0) > 0]
            reasons = Counter(o["rejection_reason"] for o in rows if o["rejection_reason"])
            ovs_stale = [o for o in rows if o["price_type"] == "overseas_sold_price"
                         and not o["is_fresh"] and (o["price"] or 0) > 0]
            # eBay sold fresh化で成立する候補
            whatif = []
            for r in ref_routes:
                if r["product_id"] == pid:
                    whatif.append({"sell": r["sell_source"], "sell_price": r["sell_price"],
                                   "net_if_fresh": r["net_profit"], "roi": r["roi"]})
            zero_diag[pid] = {
                "product_name": rows[0]["product_name"] if rows else pid,
                "buy_candidates": len(buys), "sell_candidates": len(sells),
                "rejection_top5": reasons.most_common(5),
                "stale_excluded": sum(1 for o in rows if not o["is_fresh"]),
                "overseas_stale": len(ovs_stale),
                "fresh_overseas_whatif_top5": sorted(whatif, key=lambda x: -x["net_if_fresh"])[:5],
            }

    main_routes.sort(key=lambda r: r["net_profit"], reverse=True)
    ref_routes.sort(key=lambda r: r["net_profit"], reverse=True)

    # eBay API 設定状況（overseas_prices/latest.json から）
    ebay_api_configured = False
    overseas_source_mode = "manual"
    try:
        _ovp = PROJECT_ROOT / "exports" / "overseas_prices" / "latest.json"
        if _ovp.exists():
            _ovd = json.loads(_ovp.read_text(encoding="utf-8"))
            ebay_api_configured = bool(_ovd.get("ebay_app_id_configured"))
            overseas_source_mode = _ovd.get("source_mode", "manual")
    except Exception:
        pass

    by_product = Counter(r["product_name"] for r in main_routes)
    by_conf = Counter(r["route_confidence"] for r in main_routes)
    by_rtype = Counter(r["route_type"] for r in main_routes)
    payload = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "ebay_api_configured": ebay_api_configured,
        "overseas_source_mode": overseas_source_mode,
        "summary": {
            "main_route_count": len(main_routes),
            "reference_route_count": len(ref_routes),
            "by_product": dict(by_product),
            "by_confidence": dict(by_conf),
            "by_route_type": dict(by_rtype),
            "max_profit": (max(main_routes, key=lambda r: r["net_profit"]) if main_routes else None),
            "max_roi": (max(main_routes, key=lambda r: r["roi"]) if main_routes else None),
            "zero_route_products": len(zero_diag),
        },
        "main_routes": main_routes,
        "reference_routes": ref_routes,
        "zero_route_diagnostics": zero_diag,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(OUT_DIR / "latest.md", payload, now)
    print(f"  main利益ルート: {len(main_routes)} / 参考ルート(海外sold stale): {len(ref_routes)} "
          f"/ 0件商品: {len(zero_diag)}")
    print(f"  → {OUT_DIR / 'latest.json'}")
    return 0


def _write_md(path: Path, p: dict, now: datetime) -> None:
    s = p["summary"]
    o = ["# Pro 利益ルート（normalized_price_observations 由来・検証済み）", "",
         f"生成: {p['generated_at']}", "",
         f"- **main 利益ルート: {s['main_route_count']}件**（route_confidence high/medium のみ）",
         f"- 参考ルート(海外sold stale・要fresh化): {s['reference_route_count']}件",
         f"- confidence別: {s['by_confidence']} / route_type別: {s['by_route_type']}", ""]
    if s["max_profit"]:
        mp = s["max_profit"]
        o.append(f"- 最大利益: {mp['product_name']} +¥{mp['net_profit']:,}（{mp['buy_source']}→{mp['sell_source']}, ROI {mp['roi']:.0%}）")
    if s["max_roi"]:
        mr = s["max_roi"]
        o.append(f"- 最大ROI: {mr['product_name']} ROI {mr['roi']:.0%}（+¥{mr['net_profit']:,}）")
    o += ["", "## main 利益ルート", "",
          "| product | buy | buy¥ | sell | sell¥ | net | ROI | conf | type |",
          "|---|---|---|---|---|---|---|---|---|"]
    for r in p["main_routes"][:50]:
        o.append(f"| {r['product_name'][:16]} | {r['buy_price_type']} | ¥{r['buy_price']:,} | {r['sell_price_type']} "
                 f"| ¥{r['sell_price']:,} | **+¥{r['net_profit']:,}** | {r['roi']:.0%} | {r['route_confidence']} | {r['route_type']} |")
    if not p["main_routes"]:
        o.append("| (main利益ルート0件) | | | | | | | | |")
    o += ["", "## 参考ルート（海外sold が stale・fresh化すれば成立）", "",
          "| product | buy¥ | sell(海外sold)¥ | 潜在net | ROI | stale |", "|---|---|---|---|---|---|"]
    for r in p["reference_routes"][:20]:
        o.append(f"| {r['product_name'][:16]} | ¥{r['buy_price']:,} | ¥{r['sell_price']:,} "
                 f"| +¥{r['net_profit']:,} | {r['roi']:.0%} | {r['rejection_reason']} |")
    if p["zero_route_diagnostics"]:
        o += ["", "## 0件商品の診断", ""]
        for pid, z in p["zero_route_diagnostics"].items():
            o.append(f"### {z['product_name']}")
            o.append(f"- buy候補 {z['buy_candidates']} / sell候補 {z['sell_candidates']} / stale除外 {z['stale_excluded']} / 海外sold stale {z['overseas_stale']}")
            o.append(f"- 除外理由TOP5: {z['rejection_top5']}")
            if z["fresh_overseas_whatif_top5"]:
                o.append("- eBay sold を fresh化すると成立する候補:")
                for w in z["fresh_overseas_whatif_top5"]:
                    o.append(f"  - {w['sell']} ¥{w['sell_price']:,} → 潜在 +¥{w['net_if_fresh']:,}（ROI {w['roi']:.0%}）")
            o.append("")
    path.write_text("\n".join(o) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

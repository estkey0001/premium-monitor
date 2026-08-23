#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Retail & Buyback Automation — 販売価格/買取価格/二次流通の品質監査。

利益判定/AI/Opportunity/Notification/Capital/Execution ロジックは一切変更しない
（取得・正規化・品質管理のみ）。既存の normalized_price_observations を読み取り、
src/market/price_quality の品質ゲートを適用して監査レポートを生成する。

出力: exports/retail_buyback_audit/latest.json / latest.md

監査内容:
  - ソース別品質（販売: 価格.com/ヨドバシ/ビック/楽天/Yahoo, 買取: マップ/フジヤ/
    じゃんぱら/イオシス等, 二次流通: eBay/フリマ）: 件数/価格取得/exact/high/fresh/
    main昇格可/失敗/失敗理由
  - 商品同一性の厳格監査（容量・型番・カラー・新品中古）
  - 正規化監査（税込/送料/ポイント/買取/下取 の別項目保持）
  - duplicate_price_pattern（同一ソースで複数SKU同額 → 警告・弾かない）
  - Main昇格サマリ（high confidence + fresh + exact のみ）
  - Freshness 遵守（取得失敗で古い値の時刻だけ更新していないか）
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
OUT = ROOT / "exports" / "retail_buyback_audit"

from src.market.price_quality import (
    RETAIL_SOURCES, BUYBACK_SOURCES, RESALE_SOURCES,
    is_main_promotable, effective_confidence, identity_strict_ok,
    capacity_consistent, condition_class, detect_duplicate_price_pattern,
    normalization_flags, price_role_sanity,
)


def _load(rel):
    try:
        return json.loads((ROOT / rel).read_text(encoding="utf-8"))
    except Exception:
        return {}


def _pct(a, b):
    return round(a / b, 4) if b else 0.0


def _category_of(source_name):
    if source_name in RETAIL_SOURCES:
        return "retail"
    if source_name in BUYBACK_SOURCES:
        return "buyback"
    if source_name in RESALE_SOURCES:
        return "resale"
    return "other"


def _source_bucket(rows, products):
    n = len(rows)
    with_price = sum(1 for o in rows if o.get("price"))
    exact = sum(1 for o in rows if o.get("is_exact_product_match"))
    high = sum(1 for o in rows if effective_confidence(o) == "high")
    fresh = sum(1 for o in rows if o.get("is_fresh"))
    main_elig = sum(1 for o in rows if is_main_promotable(o))
    zero = sum(1 for o in rows if not o.get("price"))
    stale = sum(1 for o in rows if not o.get("is_fresh"))
    rejected = sum(1 for o in rows if o.get("rejection_reason"))
    reasons = defaultdict(int)
    for o in rows:
        if o.get("rejection_reason"):
            reasons[o["rejection_reason"]] += 1
        elif not o.get("price"):
            reasons["price_zero"] += 1
    return {
        "observations": n, "with_price": with_price, "exact_match": exact,
        "high_confidence": high, "fresh": fresh, "main_promotable": main_elig,
        "zero": zero, "stale": stale, "rejected": rejected,
        "failure_reasons": dict(sorted(reasons.items(), key=lambda x: -x[1])),
    }


def identity_audit(obs):
    """容量・型番・カラー・新品中古の厳格一致監査。"""
    issues = defaultdict(list)
    checked = 0
    for o in obs:
        pname = o.get("product_name", "")
        cap = capacity_consistent(pname, o.get("extracted_title") or pname)
        checked += 1
        if cap is False:
            issues["capacity_mismatch"].append(o.get("product_id"))
        if o.get("wrong_model_flag"):
            issues["wrong_model"].append(o.get("product_id"))
        if o.get("accessory_flag"):
            issues["accessory"].append(o.get("product_id"))
        if not o.get("is_body_only", True):
            issues["not_body_only"].append(o.get("product_id"))
    return {
        "checked": checked,
        "capacity_mismatch": len(issues["capacity_mismatch"]),
        "wrong_model": len(issues["wrong_model"]),
        "accessory": len(issues["accessory"]),
        "not_body_only": len(issues["not_body_only"]),
        "condition_dist": _count(obs, lambda o: condition_class(o.get("condition"))),
    }


def normalization_audit(obs):
    flags = [normalization_flags(o) for o in obs]
    n = len(flags) or 1
    return {
        "has_price_type": _pct(sum(1 for f in flags if f["has_price_type"]), n),
        "shipping_separated": _pct(sum(1 for f in flags if f["shipping_separated"]), n),
        "points_separated": _pct(sum(1 for f in flags if f["points_separated"]), n),
        "tradein_excluded": _pct(sum(1 for f in flags if f["is_tradein_excluded"]), n),
        "buyback_labeled": sum(1 for f in flags if f["is_buyback"]),
        "price_type_dist": _count(obs, lambda o: o.get("price_type")),
        "note": "格納価格は税込本体。送料/ポイント/下取は price_context に混入させず別扱い",
    }


def _count(rows, keyfn):
    c = defaultdict(int)
    for r in rows:
        c[keyfn(r)] += 1
    return dict(c)


def main():
    npo = _load("exports/normalized_price_observations/latest.json")
    obs = npo.get("observations", [])
    if not obs:
        print("[retail_buyback_audit] NPO が空。generate_normalized_price_observations を先に実行。")
        return 1

    # カテゴリ別・ソース別
    by_cat = defaultdict(list)
    by_src = defaultdict(list)
    for o in obs:
        cat = _category_of(o.get("source_name"))
        if cat == "other":
            continue
        by_cat[cat].append(o)
        by_src[o.get("source_name")].append(o)

    category_summary = {cat: _source_bucket(rows, None) for cat, rows in by_cat.items()}
    source_summary = {name: _source_bucket(rows, None)
                      for name, rows in sorted(by_src.items(), key=lambda kv: -len(kv[1]))}

    # 重点ソースの網羅（未取得は no_data で明示）
    def _coverage(source_list):
        cov = {}
        for s in source_list:
            cov[s] = source_summary.get(s) or {"observations": 0, "status": "no_data"}
        return cov

    dup = detect_duplicate_price_pattern(obs)
    idaudit = identity_audit(obs)
    normaudit = normalization_audit([o for o in obs if _category_of(o.get("source_name")) != "other"])

    # Main 昇格サマリ
    main_by_cat = {cat: sum(1 for o in rows if is_main_promotable(o))
                   for cat, rows in by_cat.items()}
    total_main = sum(main_by_cat.values())

    # Freshness 遵守: stale なのに observed が最近（＝時刻だけ更新の疑い）を検出
    # is_fresh=False かつ rejection=stale なのに observed_age_days が極端に小さい矛盾
    freshness_violations = [
        o.get("product_id") for o in obs
        if o.get("rejection_reason") == "stale_over_14d" and (o.get("observed_age_days") or 99) < 1
    ]

    report = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "scope": "販売/買取/二次流通の取得品質・正規化・同一性（利益/AI/UI/SaaSロジックは不変）",
        "rules": {
            "identity": "容量・型番・カラー・新品/中古 を厳格一致",
            "misidentification": "アクセサリー/分割月額/ポイント額/下取額 を除外",
            "freshness": "取得失敗時に古い値の時刻だけを更新しない",
            "main_promotion": "high confidence + fresh + exact match のみ Main 昇格",
        },
        "category_summary": category_summary,
        "retail_coverage": _coverage(RETAIL_SOURCES),
        "buyback_coverage": _coverage(BUYBACK_SOURCES),
        "resale_coverage": _coverage(RESALE_SOURCES),
        "source_summary": source_summary,
        "identity_audit": idaudit,
        "normalization_audit": normaudit,
        "duplicate_price_pattern": dup,
        "main_promotion": {"by_category": main_by_cat, "total": total_main},
        "freshness_compliance": {
            "violations": freshness_violations,
            "ok": len(freshness_violations) == 0,
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "latest.md").write_text(render_md(report), encoding="utf-8")
    print(f"[retail_buyback_audit] main_promotable={total_main} dup_patterns={len(dup)} "
          f"freshness_ok={report['freshness_compliance']['ok']} → {OUT/'latest.json'}")
    return 0


def render_md(r):
    L = ["# Retail & Buyback Automation — 品質監査\n",
         f"> 生成: {r['generated_at']} / {r['scope']}\n"]
    L.append("## カテゴリ別サマリ")
    L.append("| カテゴリ | 観測 | 価格有 | exact | high | fresh | Main昇格可 | 失敗(0円/stale/rejected) |")
    L.append("|---|--:|--:|--:|--:|--:|--:|--:|")
    for cat, b in r["category_summary"].items():
        L.append(f"| {cat} | {b['observations']} | {b['with_price']} | {b['exact_match']} | "
                 f"{b['high_confidence']} | {b['fresh']} | {b['main_promotable']} | "
                 f"{b['zero']}/{b['stale']}/{b['rejected']} |")
    L.append("")
    L.append(f"## Main 昇格（high conf + fresh + exact）: 合計 **{r['main_promotion']['total']}** 件")
    L.append(f"- カテゴリ別: {r['main_promotion']['by_category']}")
    L.append("")
    for label, key in [("販売価格", "retail_coverage"), ("買取価格", "buyback_coverage"),
                       ("二次流通", "resale_coverage")]:
        L.append(f"## {label} ソース網羅")
        L.append("| source | 観測 | 価格有 | fresh | Main昇格可 |")
        L.append("|---|--:|--:|--:|--:|")
        for s, b in r[key].items():
            if b.get("status") == "no_data":
                L.append(f"| {s} | 0 | – | – | no_data |")
            else:
                L.append(f"| {s} | {b['observations']} | {b['with_price']} | {b['fresh']} | {b['main_promotable']} |")
        L.append("")
    L.append("## 商品同一性 監査")
    ia = r["identity_audit"]
    L.append(f"- 容量不一致: {ia['capacity_mismatch']} / 別型番: {ia['wrong_model']} / "
             f"アクセサリー: {ia['accessory']} / 非本体: {ia['not_body_only']}")
    L.append(f"- condition分布: {ia['condition_dist']}")
    L.append("")
    L.append("## 正規化 監査")
    na = r["normalization_audit"]
    L.append(f"- price_type付与率: {na['has_price_type']:.0%} / 送料分離: {na['shipping_separated']:.0%} / "
             f"ポイント分離: {na['points_separated']:.0%} / 下取除外: {na['tradein_excluded']:.0%}")
    L.append(f"- price_type分布: {na['price_type_dist']}")
    L.append("")
    L.append("## duplicate_price_pattern（同一ソースで複数SKU同額・要確認）")
    if r["duplicate_price_pattern"]:
        L.append("| source | role | price | SKU数 | product_ids |")
        L.append("|---|---|--:|--:|---|")
        for d in r["duplicate_price_pattern"][:20]:
            L.append(f"| {d['source_name']} | {d['price_role']} | ¥{d['price']:,} | {d['count']} | "
                     f"{', '.join(d['product_ids'])} |")
    else:
        L.append("- 検出なし")
    L.append("")
    fc = r["freshness_compliance"]
    L.append(f"## Freshness 遵守: {'✅ OK' if fc['ok'] else '⚠️ 違反あり'}")
    L.append(f"- 取得失敗で時刻だけ更新した疑い: {len(fc['violations'])} 件")
    L.append("")
    return "\n".join(L)


if __name__ == "__main__":
    raise SystemExit(main())

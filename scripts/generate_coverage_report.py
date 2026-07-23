#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Market Coverage Engine — 監視対象カバレッジの分析と拡充提案。

利益判定ロジックは変更しない。既存 products.yaml は上書きせず、
拡充候補を exports/coverage/products_candidates.yaml として別生成する（非破壊・提案）。

出力:
  exports/coverage/latest.json / latest.md
  exports/coverage/products_candidates.yaml   （カテゴリ別・コメント付き・提案）
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
NOW = datetime.now(tz=JST)
OUT = ROOT / "coverage"  # coverage 出力（exports 配下に置く）
OUT = ROOT / "exports" / "coverage"
DB = ROOT / "data" / "premium_monitor.db"

# 利益が出やすいカテゴリ候補（ルールベース・調査）。
# expected_profit/competition/difficulty は 1-5（difficulty/competition は小さいほど良い）。
CATEGORY_CANDIDATES = [
    {"category": "Apple", "expected_profit": 4, "difficulty": 2, "api": True,
     "update_freq": "高", "competition": 4, "effort": "1時間",
     "note": "iPhone/iPad/Watch/MacBook。流動性最高・kakaku等で価格取得容易だが競合多"},
    {"category": "Nintendo", "expected_profit": 4, "difficulty": 2, "api": False,
     "update_freq": "高", "competition": 4, "effort": "1時間",
     "note": "Switch2 系。発売直後プレ値・買取活発"},
    {"category": "Sony Camera", "expected_profit": 5, "difficulty": 3, "api": False,
     "update_freq": "中", "competition": 3, "effort": "4時間",
     "note": "α7/α9/ZV。高単価・買取店網羅済みで拡張容易"},
    {"category": "Canon", "expected_profit": 5, "difficulty": 3, "api": False,
     "update_freq": "中", "competition": 3, "effort": "4時間",
     "note": "EOS R 系。高単価・供給不足でプレ値化しやすい"},
    {"category": "DJI", "expected_profit": 4, "difficulty": 3, "api": False,
     "update_freq": "中", "competition": 2, "effort": "4時間",
     "note": "Osmo/Mini/Air。競合少・海外差益大"},
    {"category": "Leica", "expected_profit": 5, "difficulty": 4, "api": False,
     "update_freq": "低", "competition": 2, "effort": "4時間",
     "note": "Q/M/SL。超高単価・玉数少だが利益絶対額大"},
    {"category": "GPU", "expected_profit": 4, "difficulty": 3, "api": True,
     "update_freq": "高", "competition": 4, "effort": "1日",
     "note": "RTX 50 系。発売直後プレ値・価格.com/PC店で取得可"},
    {"category": "Rolex", "expected_profit": 5, "difficulty": 5, "api": False,
     "update_freq": "低", "competition": 5, "effort": "3日",
     "note": "超高単価だが真贋・資金・在庫リスク大。要慎重（規約/本人確認）"},
    {"category": "Hermes", "expected_profit": 5, "difficulty": 5, "api": False,
     "update_freq": "低", "competition": 5, "effort": "3日",
     "note": "バッグ等。真贋・仕入れ困難。参考カテゴリ（優先度低）"},
    {"category": "Pokemon", "expected_profit": 4, "difficulty": 4, "api": False,
     "update_freq": "高", "competition": 5, "effort": "1日",
     "note": "TCG。ドメイン異質（型番/状態/PSA）。別スキーマ要"},
]

# カテゴリ別 対象商品候補 TOP（代表機種・参考。実価格は取得後に確定）
CANDIDATE_PRODUCTS = {
    "Apple": [
        ("iphone16", "iphone", "Apple", "iPhone 16", 124800), ("iphone16_plus", "iphone", "Apple", "iPhone 16 Plus", 139800),
        ("iphone16pro_max_1tb", "iphone", "Apple", "iPhone 16 Pro Max 1TB", 249800),
        ("ipad_pro_m4_11", "tablet", "Apple", "iPad Pro M4 11", 168800), ("ipad_pro_m4_13", "tablet", "Apple", "iPad Pro M4 13", 218800),
        ("ipad_air_m3_11", "tablet", "Apple", "iPad Air M3 11", 98800),
        ("macbook_pro_m4_16", "pc", "Apple", "MacBook Pro M4 16", 398000), ("mac_studio_m4", "pc", "Apple", "Mac Studio M4", 298000),
        ("apple_watch_ultra2", "wearable", "Apple", "Apple Watch Ultra 2", 128800),
        ("airpods_pro2", "audio", "Apple", "AirPods Pro 2", 39800), ("airpods_max_usbc", "audio", "Apple", "AirPods Max USB-C", 84800),
        ("vision_pro", "wearable", "Apple", "Apple Vision Pro", 599800),
    ],
    "Nintendo": [
        ("switch2_pokemon", "game_console", "Nintendo", "Nintendo Switch 2 ポケモン版", 53980),
        ("switch2_splatoon", "game_console", "Nintendo", "Nintendo Switch 2 スプラ版", 53980),
    ],
    "Sony Camera": [
        ("a7iv", "camera", "SONY", "SONY α7 IV", 330000), ("a7c2", "camera", "SONY", "SONY α7C II", 270000),
        ("a6700", "camera", "SONY", "SONY α6700", 190000), ("zve10m2", "camera", "SONY", "SONY ZV-E10 II", 130000),
        ("a9iii", "camera", "SONY", "SONY α9 III", 880000), ("a1", "camera", "SONY", "SONY α1", 900000),
    ],
    "Canon": [
        ("r6m3", "camera", "CANON", "Canon EOS R6 Mark III", 400000), ("r8", "camera", "CANON", "Canon EOS R8", 270000),
        ("r50", "camera", "CANON", "Canon EOS R50", 110000), ("r7", "camera", "CANON", "Canon EOS R7", 210000),
    ],
    "DJI": [
        ("dji_pocket3", "camera", "DJI", "DJI Osmo Pocket 3", 74800), ("dji_mini4pro", "camera", "DJI", "DJI Mini 4 Pro", 128700),
        ("dji_action5", "camera", "DJI", "DJI Osmo Action 5 Pro", 59400), ("dji_air3s", "camera", "DJI", "DJI Air 3S", 145200),
    ],
    "Leica": [
        ("leica_dlux8", "camera", "LEICA", "Leica D-Lux 8", 220000), ("leica_sl3", "camera", "LEICA", "Leica SL3", 1250000),
        ("leica_q3_43", "camera", "LEICA", "Leica Q3 43", 990000),
    ],
    "GPU": [
        ("rtx5090", "pc", "NVIDIA", "GeForce RTX 5090", 400000), ("rtx5080", "pc", "NVIDIA", "GeForce RTX 5080", 200000),
        ("rtx5070ti", "pc", "NVIDIA", "GeForce RTX 5070 Ti", 130000),
    ],
}


def _priority_score(c: dict) -> float:
    """追加優先度スコア: 期待利益×流動性 − 取得難易度 − 競合。APIありは加点。"""
    freq = {"高": 3, "中": 2, "低": 1}.get(c["update_freq"], 1)
    return round(c["expected_profit"] * 2 + freq * 1.5 + (2 if c["api"] else 0)
                 - c["difficulty"] * 1.2 - c["competition"] * 1.0, 1)


def main() -> int:
    print(f"[generate_coverage_report] 開始: {NOW.strftime('%Y-%m-%d %H:%M')} JST")
    con = sqlite3.connect(str(DB)); con.row_factory = sqlite3.Row
    genres = con.execute("SELECT genre, COUNT(*) n FROM products WHERE is_active=1 GROUP BY genre").fetchall()
    total_products = con.execute("SELECT COUNT(*) FROM products WHERE is_active=1").fetchone()[0]
    con.close()

    pr = json.loads((ROOT / "exports/profit_routes/latest.json").read_text(encoding="utf-8"))
    genre_of = {}
    try:
        con2 = sqlite3.connect(str(DB))
        for r in con2.execute("SELECT id, genre FROM products"):
            genre_of[r[0]] = r[1]
        con2.close()
    except Exception:
        pass
    main_by_cat = defaultdict(int); ref_by_cat = defaultdict(int)
    profit_by_cat = defaultdict(list); roi_by_cat = defaultdict(list)
    for r in pr.get("main_routes", []):
        g = genre_of.get(r["product_id"], "?")
        main_by_cat[g] += 1; profit_by_cat[g].append(r["net_profit"]); roi_by_cat[g].append(r["roi"])
    for r in pr.get("reference_routes", []):
        ref_by_cat[genre_of.get(r["product_id"], "?")] += 1

    coverage = []
    for row in genres:
        g = row["genre"]; n = row["n"]
        prof = profit_by_cat.get(g, []); rois = roi_by_cat.get(g, [])
        coverage.append({
            "category": g, "products": n,
            "main": main_by_cat.get(g, 0), "reference": ref_by_cat.get(g, 0),
            "avg_profit": (round(sum(prof) / len(prof)) if prof else 0),
            "avg_roi": (round(sum(rois) / len(rois), 4) if rois else 0),
        })
    coverage.sort(key=lambda x: x["products"], reverse=True)

    # カテゴリ候補ランキング
    cand = sorted(CATEGORY_CANDIDATES, key=_priority_score, reverse=True)
    for c in cand:
        c["priority_score"] = _priority_score(c)

    # Coverage Score(100): 幅(covered categories) + 深さ(products) + 収益性(main/ref) + 候補実装余地
    TARGET_CATS = 10
    covered = len(genres)
    breadth = min(30, round(covered / TARGET_CATS * 30))
    depth = min(30, round(total_products / 80 * 30))
    profitability = min(25, pr["summary"]["main_route_count"] * 10 + pr["summary"]["reference_route_count"] * 2)
    freshness = 15 if pr["summary"]["main_route_count"] > 0 else 5
    cov_score = min(100, breadth + depth + profitability + freshness)

    # 次に追加すべき商品 TOP50（候補カテゴリ優先度順に flatten）
    top50 = []
    for c in cand:
        for prod in CANDIDATE_PRODUCTS.get(c["category"], []):
            top50.append({"category": c["category"], "alias": prod[0], "genre": prod[1],
                          "brand": prod[2], "name": prod[3], "concept_retail": prod[4],
                          "priority_score": c["priority_score"]})
    top50.sort(key=lambda x: x["priority_score"], reverse=True)
    top50 = top50[:50]

    payload = {
        "generated_at": NOW.strftime("%Y-%m-%d %H:%M JST"),
        "total_products": total_products, "covered_categories": covered,
        "coverage_score": cov_score,
        "coverage_score_breakdown": {"breadth": breadth, "depth": depth,
                                     "profitability": profitability, "freshness": freshness},
        "current_coverage": coverage,
        "category_candidates_ranked": cand,
        "next_products_top50": top50,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "latest.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(payload)
    _write_candidates_yaml(cand)
    print(f"  Coverage Score {cov_score}/100 / カテゴリ {covered} / 商品 {total_products} / 候補TOP50 {len(top50)}")
    return 0


def _write_md(p):
    o = ["# Market Coverage Engine", "", f"生成: {p['generated_at']}",
         f"総商品 {p['total_products']} / カテゴリ {p['covered_categories']}", "",
         f"## Coverage Score: **{p['coverage_score']} / 100**",
         f"（幅 {p['coverage_score_breakdown']['breadth']}/30 ・ 深さ {p['coverage_score_breakdown']['depth']}/30 ・ "
         f"収益性 {p['coverage_score_breakdown']['profitability']}/25 ・ 鮮度 {p['coverage_score_breakdown']['freshness']}/15）", "",
         "## Task1: 現在のカテゴリ一覧", "",
         "| カテゴリ | 商品数 | main | reference | 平均利益 | 平均ROI |", "|---|---|---|---|---|---|"]
    for c in p["current_coverage"]:
        o.append(f"| {c['category']} | {c['products']} | {c['main']} | {c['reference']} | "
                 f"¥{c['avg_profit']:,} | {c['avg_roi']*100:.1f}% |")
    o += ["", "## Task2-4: 利益カテゴリ候補ランキング（優先度順）", "",
          "| 順位 | カテゴリ | 優先度 | 期待利益 | 取得難易度 | API | 更新頻度 | 競合 | 工数 | 備考 |",
          "|---|---|---|---|---|---|---|---|---|---|"]
    for i, c in enumerate(p["category_candidates_ranked"], 1):
        o.append(f"| {i} | {c['category']} | {c['priority_score']} | {c['expected_profit']}/5 | "
                 f"{c['difficulty']}/5 | {'○' if c['api'] else '×'} | {c['update_freq']} | {c['competition']}/5 | "
                 f"{c['effort']} | {c['note']} |")
    o += ["", "## Task9: 次に追加すべき商品 TOP50", "",
          "| # | カテゴリ | 商品 | brand | genre | 概算定価 |", "|---|---|---|---|---|---|"]
    for i, t in enumerate(p["next_products_top50"], 1):
        o.append(f"| {i} | {t['category']} | {t['name']} | {t['brand']} | {t['genre']} | ¥{t['concept_retail']:,} |")
    (OUT / "latest.md").write_text("\n".join(o) + "\n", encoding="utf-8")


def _write_candidates_yaml(cand):
    """カテゴリ別・コメント付きの候補 products.yaml（提案・非破壊。live には反映しない）。"""
    lines = ["# ==========================================================",
             "# Market Coverage — 監視対象拡充候補（提案・自動生成）",
             "# 注意: これは提案です。既存 config/products.yaml は上書きしません。",
             "#       採用時は各商品の retail_price・keywords を精査し手動でマージしてください。",
             f"# 生成: {NOW.strftime('%Y-%m-%d %H:%M JST')}",
             "# ==========================================================", "", "products:"]
    for c in cand:
        prods = CANDIDATE_PRODUCTS.get(c["category"], [])
        if not prods:
            continue
        lines.append(f"  # --- {c['category']}（優先度 {_priority_score(c)} / {c['effort']}）: {c['note']} ---")
        for alias, genre, brand, name, retail in prods:
            lines.append(f"  - id: prod_{alias}")
            lines.append(f"    genre: {genre}")
            lines.append(f"    brand: {brand}")
            lines.append(f"    name: \"{name}\"")
            lines.append(f"    retail_price: {retail}   # 概算定価（要確認）")
            lines.append(f"    keywords: \"{name}\"")
            lines.append(f"    memo: \"coverage候補（{c['category']}）\"")
        lines.append("")
    (OUT / "products_candidates.yaml").write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())

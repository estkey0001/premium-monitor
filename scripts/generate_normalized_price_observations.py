#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""正規化価格観測（normalized_price_observations）を生成・出力する。

正規化ロジックの本体は src/market/normalized_prices.py に一元化されており、
本スクリプトはそれを呼び出して JSON/Markdown の成果物を書き出すだけの薄いラッパ。
ranking / sedori / LP も同じ src/market/normalized_prices.py を唯一の入力源とする。

出力:
  - exports/normalized_price_observations/latest.json
  - exports/normalized_price_observations/latest.md
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.market.normalized_prices import (  # noqa: E402
    build_observations, STALE_DAYS, PRO_BUY_TYPES, PRO_SELL_TYPES, BEGINNER_TYPES,
)

JST = timezone(timedelta(hours=9))
DB_PATH = PROJECT_ROOT / "data" / "premium_monitor.db"
REPORT_DIR = PROJECT_ROOT / "exports" / "normalized_price_observations"


def _summarize(rows: list[dict]) -> dict:
    by_role = Counter(r["price_role"] for r in rows)
    by_type = Counter(r["price_type"] for r in rows)
    by_reject = Counter(r["rejection_reason"] for r in rows if r["rejection_reason"])
    return {
        "total": len(rows),
        "usable_for_beginner": sum(1 for r in rows if r["is_usable_for_beginner"]),
        "usable_for_pro": sum(1 for r in rows if r["is_usable_for_pro"]),
        "fresh": sum(1 for r in rows if r["is_fresh"]),
        "by_price_role": dict(by_role),
        "by_price_type": dict(by_type),
        "rejection_reasons": dict(by_reject),
    }


def _write_md(path: Path, now: datetime, summary: dict, rows: list[dict]) -> None:
    o = [f"# Normalized Price Observations", "",
         f"生成: {now.strftime('%Y-%m-%d %H:%M JST')}", "",
         "全価格（買取/販売/出品/落札/海外/下取/公式）を単一スキーマに正規化。",
         "`price_role`（buy/sell/official/trade_in）を必ず付与し、",
         "`is_usable_for_beginner` / `is_usable_for_pro` で main calculation 利用可否を判定。",
         "ranking / sedori / LP はこの定義（src/market/normalized_prices.py）を唯一の入力源とする。", "",
         "## サマリ", "",
         f"- 総観測数: **{summary['total']}**",
         f"- Beginner 利用可: {summary['usable_for_beginner']} / Pro 利用可: {summary['usable_for_pro']}",
         f"- fresh(≤{STALE_DAYS}日): {summary['fresh']}", "",
         "### price_role 別", "", "| role | 件数 |", "|---|---|"]
    for k, v in sorted(summary["by_price_role"].items()):
        o.append(f"| {k} | {v} |")
    o += ["", "### price_type 別", "", "| type | 件数 |", "|---|---|"]
    for k, v in sorted(summary["by_price_type"].items()):
        o.append(f"| {k} | {v} |")
    o += ["", "### rejection_reason 別（main calc 除外）", "", "| reason | 件数 |", "|---|---|"]
    for k, v in sorted(summary["rejection_reasons"].items()):
        o.append(f"| {k} | {v} |")
    o += ["", "## Beginner 利用可（official_price / buyback_price のみ）", "",
          "| product | role | type | price | conf | age | source |", "|---|---|---|---|---|---|---|"]
    for r in [x for x in rows if x["is_usable_for_beginner"]][:30]:
        o.append(f"| {r['product_name'][:22]} | {r['price_role']} | {r['price_type']} | "
                 f"¥{r['price']:,} | {r['confidence']} | {r['age_days']}d | {r['source_name'][:16]} |")
    o += ["", "## Pro 利用可（buy=販売/出品/落札/海外出品, sell=買取/海外落札）", "",
          "| product | role | type | price | cond | age | source |", "|---|---|---|---|---|---|---|"]
    for r in [x for x in rows if x["is_usable_for_pro"]][:30]:
        o.append(f"| {r['product_name'][:22]} | {r['price_role']} | {r['price_type']} | "
                 f"¥{r['price']:,} | {r['condition']} | {r['age_days']}d | {r['source_name'][:16]} |")
    path.write_text("\n".join(o) + "\n", encoding="utf-8")


def main() -> int:
    now = datetime.now(tz=JST)
    print(f"[generate_normalized_price_observations] 開始: {now.strftime('%Y-%m-%d %H:%M')} JST")
    if not DB_PATH.exists():
        print(f"[ERROR] DB が見つかりません: {DB_PATH}", file=sys.stderr)
        return 1
    con = sqlite3.connect(str(DB_PATH))
    rows = build_observations(con, now)
    con.close()
    summary = _summarize(rows)
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "schema_version": 1,
        "stale_days": STALE_DAYS,
        "pro_buy_types": sorted(PRO_BUY_TYPES),
        "pro_sell_types": sorted(PRO_SELL_TYPES),
        "beginner_types": sorted(BEGINNER_TYPES),
        "summary": summary,
        "observations": rows,
    }
    (REPORT_DIR / "latest.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_md(REPORT_DIR / "latest.md", now, summary, rows)
    print(f"  観測 {summary['total']} 件 / beginner利用可 {summary['usable_for_beginner']} "
          f"/ pro利用可 {summary['usable_for_pro']}")
    print(f"  → {REPORT_DIR / 'latest.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

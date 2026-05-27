#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""せどりルートレポートを生成して exports/sedori_routes_report/ に保存するスクリプト。

フィルタ条件:
  - buy_condition in ["new", "unused", "sealed", "未使用", "新品", "未開封"]
  - low_confidence / suspicious_price / product_not_listed / fetch_failed は除外

出力:
  - exports/sedori_routes_report/latest.json
  - exports/sedori_routes_report/latest.md
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

JST = timezone(timedelta(hours=9))
REPORT_DIR = PROJECT_ROOT / "exports" / "sedori_routes_report"

# 新品/未使用条件
_UNUSED_CONDITIONS = frozenset({"new", "unused", "sealed", "未使用", "新品", "未開封"})


def main() -> int:
    """メイン処理: せどりルートレポートを生成して保存する。"""
    now = datetime.now(tz=JST)
    print(f"[generate_sedori_routes_report] 開始: {now.strftime('%Y-%m-%d %H:%M')} JST")

    try:
        from src.db.repository import Repository
        repo = Repository()
        all_routes = repo.list_sedori_routes(min_net_profit=-9999999, limit=100)
    except Exception as e:
        print(f"[WARN] DB 読み込み失敗: {e}", file=sys.stderr)
        all_routes = []

    total = len(all_routes)

    # 新品・未使用のみフィルタ（中古・状態不明は除外）
    unused_routes = [
        r for r in all_routes
        if getattr(r, "buy_condition", "") in _UNUSED_CONDITIONS
    ]
    excluded_by_condition = total - len(unused_routes)

    # 利益あり/赤字で分類
    profitable = [r for r in unused_routes if getattr(r, "net_profit", 0) > 0]
    negative = [r for r in unused_routes if getattr(r, "net_profit", 0) <= 0]

    def _route_to_dict(r) -> dict:
        """SedoriRoute オブジェクトを辞書に変換する。"""
        return {
            "product_name": getattr(r, "product_name", ""),
            "buy_shop_name": getattr(r, "buy_shop_name", ""),
            "sell_shop_name": getattr(r, "sell_shop_name", ""),
            "buy_condition": getattr(r, "buy_condition", ""),
            "buy_price": getattr(r, "buy_price", 0),
            "sell_price": getattr(r, "sell_price", 0),
            "net_profit": getattr(r, "net_profit", 0),
            "profit_rate": round(float(getattr(r, "profit_rate", 0) or 0), 4),
            "needs_review": getattr(r, "needs_review", False),
        }

    report = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "routes_total": total,
        "routes_unused_only": len(unused_routes),
        "profitable_routes": len(profitable),
        "negative_routes": len(negative),
        "excluded_by_condition": excluded_by_condition,
        "top_profitable": [_route_to_dict(r) for r in
                           sorted(profitable, key=lambda r: getattr(r, "net_profit", 0), reverse=True)[:10]],
    }

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON レポート保存
    json_path = REPORT_DIR / "latest.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[INFO] sedori_routes_report/latest.json 保存完了 (profitable={len(profitable)})")

    # MD レポート保存
    lines = [
        f"# せどりルートレポート — {now.strftime('%Y-%m-%d %H:%M JST')}",
        "",
        f"- 全ルート: {total} / 新品・未使用のみ: {len(unused_routes)} (除外: {excluded_by_condition})",
        f"- 利益あり: {len(profitable)} / 赤字: {len(negative)}",
        "",
        "## Top利益ルート",
        "",
    ]
    for i, r in enumerate(report["top_profitable"], 1):
        lines.append(
            f"{i}. **{r['product_name']}** {r['buy_shop_name']} → {r['sell_shop_name']}: "
            f"+¥{r['net_profit']:,} ({r['profit_rate']*100:.1f}%) [{r['buy_condition']}]"
        )
    if not report["top_profitable"]:
        lines.append("データなし")

    md_path = REPORT_DIR / "latest.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[INFO] sedori_routes_report/latest.md 保存完了")

    return 0


if __name__ == "__main__":
    sys.exit(main())

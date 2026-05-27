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
        from src.db.database import Database
        from src.db.repository import Repository
        db = Database()
        repo = Repository(db)
        all_routes = repo.list_sedori_routes(min_net_profit=-9999999, limit=100)
    except Exception as e:
        print(f"[WARN] DB 読み込み失敗: {e}", file=sys.stderr)
        all_routes = []

    total = len(all_routes)

    # 除外フラグ付きルートをカウント・除外
    _EXCLUDE_FLAGS = frozenset({
        "suspicious_price", "product_not_listed", "fetch_failed",
        "low_confidence", "price_not_found",
    })
    confidence_excluded = [
        r for r in all_routes
        if any(getattr(r, f, False) for f in _EXCLUDE_FLAGS)
    ]
    excluded_by_confidence = len(confidence_excluded)
    valid_routes = [r for r in all_routes if r not in confidence_excluded]

    # 価格なし（buy_price or sell_price が 0 以下 or None）を除外
    price_missing = [
        r for r in valid_routes
        if not (getattr(r, "buy_price", 0) or 0) or not (getattr(r, "sell_price", 0) or 0)
    ]
    excluded_by_missing_price = len(price_missing)
    valid_routes = [r for r in valid_routes if r not in price_missing]

    # 新品・未使用のみフィルタ（中古・状態不明は除外）
    unused_routes = [
        r for r in valid_routes
        if getattr(r, "buy_condition", "") in _UNUSED_CONDITIONS
    ]
    excluded_by_condition = len(valid_routes) - len(unused_routes)

    # 利益あり/赤字で分類
    profitable = [r for r in unused_routes if getattr(r, "net_profit", 0) > 0]
    negative = [r for r in unused_routes if getattr(r, "net_profit", 0) <= 0]

    # reason_if_empty: データがない場合の理由を生成
    if len(profitable) == 0:
        if total == 0:
            reason_if_empty = "calculate-sedori-routes 未実行 or DBにルートデータなし"
        elif excluded_by_confidence > 0 and len(unused_routes) == 0:
            reason_if_empty = (
                f"全{total}件が低信頼度/価格未取得のため除外 "
                f"(confidence={excluded_by_confidence}, missing_price={excluded_by_missing_price})"
            )
        elif excluded_by_condition == len(valid_routes) and len(valid_routes) > 0:
            reason_if_empty = (
                f"全{len(valid_routes)}件が中古/状態不明のため除外 "
                f"(新品・未使用条件: {sorted(_UNUSED_CONDITIONS)})"
            )
        else:
            reason_if_empty = (
                f"全{len(unused_routes)}件が赤字ルートのみ "
                f"(total={total}, excl_cond={excluded_by_condition}, excl_conf={excluded_by_confidence})"
            )
    else:
        reason_if_empty = None

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

    report: dict = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "routes_total": total,
        "routes_unused_only": len(unused_routes),
        "profitable_routes": len(profitable),
        "negative_routes": len(negative),
        "excluded_by_condition": excluded_by_condition,
        "excluded_by_confidence": excluded_by_confidence,
        "excluded_by_missing_price": excluded_by_missing_price,
        "top_profitable": [_route_to_dict(r) for r in
                           sorted(profitable, key=lambda r: getattr(r, "net_profit", 0), reverse=True)[:10]],
    }
    if reason_if_empty:
        report["reason_if_empty"] = reason_if_empty

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON レポート保存
    json_path = REPORT_DIR / "latest.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[INFO] sedori_routes_report/latest.json 保存完了 (profitable={len(profitable)})")
    if reason_if_empty:
        print(f"[INFO] reason_if_empty: {reason_if_empty}")

    # MD レポート保存
    lines = [
        f"# せどりルートレポート — {now.strftime('%Y-%m-%d %H:%M JST')}",
        "",
        f"- 全ルート: {total} / 新品・未使用のみ: {len(unused_routes)} (除外: {excluded_by_condition})",
        f"- 低信頼度除外: {excluded_by_confidence} / 価格未取得除外: {excluded_by_missing_price}",
        f"- 利益あり: {len(profitable)} / 赤字: {len(negative)}",
        "",
        "## Top利益ルート",
        "",
    ]
    if reason_if_empty:
        lines.insert(3, f"- ⚠️ reason_if_empty: {reason_if_empty}")
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

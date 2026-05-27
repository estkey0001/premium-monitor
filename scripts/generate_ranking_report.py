#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ランキングレポートを生成して exports/ranking_report/ に保存するスクリプト。

出力:
  - exports/ranking_report/latest.json
  - exports/ranking_report/latest.md
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

JST = timezone(timedelta(hours=9))
REPORT_DIR = PROJECT_ROOT / "exports" / "ranking_report"

# 新品/未使用条件
_UNUSED_CONDITIONS = frozenset({"new", "unused", "sealed", "未使用", "新品", "未開封"})

# 除外フラグ
_EXCLUDE_FLAGS = frozenset({
    "suspicious_price", "product_not_listed", "fetch_failed",
    "low_confidence", "price_not_found",
})


def _fmt_price(v) -> str:
    """価格を日本円形式にフォーマットする。"""
    if v is None:
        return "—"
    try:
        return f"¥{int(v):,}"
    except Exception:
        return str(v)


def _fmt_profit(v) -> str:
    """利益を符号付き日本円形式にフォーマットする。"""
    if v is None:
        return "—"
    try:
        sign = "+" if int(v) >= 0 else ""
        return f"{sign}¥{int(v):,}"
    except Exception:
        return str(v)


def main() -> int:
    """メイン処理: ランキングレポートを生成して保存する。"""
    now = datetime.now(tz=JST)
    print(f"[generate_ranking_report] 開始: {now.strftime('%Y-%m-%d %H:%M')} JST")

    try:
        from src.db.database import Database
        from src.db.repository import Repository
        db = Database()
        repo = Repository(db)
        all_deals = repo.list_beginner_deals(min_profit=0, limit=50)
    except Exception as e:
        print(f"[WARN] DB 読み込み失敗: {e}", file=sys.stderr)
        all_deals = []

    # 初心者向け: 公式購入可能 / iPhone・ゲーム機 / 利益あり
    beginner_top = [
        d for d in all_deals
        if getattr(d, "user_level", "") in ("beginner_easy", "beginner_watch")
        and getattr(d, "category", "") in ("iphone", "game_console")
        and d.net_profit_jpy >= 0
    ][:10]

    # Pro向け: 全カテゴリ / 利益率高い順
    pro_top = sorted(
        [d for d in all_deals if d.net_profit_jpy >= 0],
        key=lambda d: getattr(d, "net_profit_rate", 0) or 0,
        reverse=True,
    )[:10]

    # 赤字案件
    excluded = [d for d in all_deals if d.net_profit_jpy < 0]

    def _deal_to_dict(d) -> dict:
        """BeginnerDeal オブジェクトを辞書に変換する。"""
        return {
            "product_name": getattr(d, "product_name", ""),
            "category": getattr(d, "category", ""),
            "user_level": getattr(d, "user_level", ""),
            "official_price_jpy": getattr(d, "official_price_jpy", None),
            "best_buyback_price": getattr(d, "best_buyback_price", None),
            "best_buyback_shop": getattr(d, "best_buyback_shop", ""),
            "net_profit_jpy": getattr(d, "net_profit_jpy", 0),
            "net_profit_rate": round(float(getattr(d, "net_profit_rate", 0) or 0), 4),
        }

    # reason_if_empty: データがない場合の理由を生成
    if len(all_deals) == 0:
        reason_if_empty = (
            "run-buyback-premium-check 未実行 or DBに beginner_deals データなし。"
            "import-buyback-csv / import-market-csv が先行して完了していることを確認してください。"
        )
    elif not beginner_top and not pro_top:
        reason_if_empty = (
            f"全{len(all_deals)}件が利益なし or カテゴリ/ユーザーレベル条件に該当なし "
            f"(iphone/game_console: {len([d for d in all_deals if getattr(d,'category','') in ('iphone','game_console')])}件)"
        )
    else:
        reason_if_empty = None

    report: dict = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "beginner_top10": [_deal_to_dict(d) for d in beginner_top],
        "pro_top10": [_deal_to_dict(d) for d in pro_top],
        "excluded_items": len(excluded),
        "total_deals": len(all_deals),
        "confidence_summary": {
            "total": len(all_deals),
            "profitable": len([d for d in all_deals if d.net_profit_jpy >= 0]),
            "negative": len([d for d in all_deals if d.net_profit_jpy < 0]),
        },
        "stale_data_count": 0,
    }
    if reason_if_empty:
        report["reason_if_empty"] = reason_if_empty

    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON レポート保存
    json_path = REPORT_DIR / "latest.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[INFO] ranking_report/latest.json 保存完了 (beginner={len(beginner_top)}, pro={len(pro_top)})")
    if reason_if_empty:
        print(f"[INFO] reason_if_empty: {reason_if_empty}")

    # MD レポート保存
    lines = [
        f"# ランキングレポート — {now.strftime('%Y-%m-%d %H:%M JST')}",
        "",
        f"- 総案件数: {len(all_deals)} / 利益あり: {report['confidence_summary']['profitable']}",
    ]
    if reason_if_empty:
        lines.append(f"- ⚠️ reason_if_empty: {reason_if_empty}")
    lines.extend([
        "",
        "## 👤 初心者ランキング Top10",
        "",
    ])
    for i, d in enumerate(report["beginner_top10"], 1):
        lines.append(
            f"{i}. **{d['product_name']}** — 実質{_fmt_profit(d['net_profit_jpy'])} "
            f"({d['best_buyback_shop']})"
        )
    if not report["beginner_top10"]:
        lines.append("データなし")

    lines.extend(["", "## 🎯 Pro ランキング Top10", ""])
    for i, d in enumerate(report["pro_top10"], 1):
        lines.append(
            f"{i}. **{d['product_name']}** — 実質{_fmt_profit(d['net_profit_jpy'])} "
            f"/ 利益率{d['net_profit_rate']*100:.1f}%"
        )
    if not report["pro_top10"]:
        lines.append("データなし")

    md_path = REPORT_DIR / "latest.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[INFO] ranking_report/latest.md 保存完了")

    return 0


if __name__ == "__main__":
    sys.exit(main())

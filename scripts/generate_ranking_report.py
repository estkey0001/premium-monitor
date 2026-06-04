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

    _stale_excluded = 0  # 14日超で利益判定から除外した件数（reason 用）
    try:
        from src.db.database import Database
        from src.db.repository import Repository
        from src.content.daily_lp_generator import DailyLPGenerator
        db = Database()
        repo = Repository(db)
        # LP と同じく「全レベル」を取得して enrich で昇格を反映（min_profit 制約なし）。
        _raw = repo.list_beginner_deals(min_profit=-9999999, limit=80)
        # 商品別買取行（bybp）を構築（中古・resale は enrich 側で除外）
        _bybp = {}
        for _p in repo.list_products():
            _rows = repo.list_buyback_prices_by_product(_p.id, limit=10)
            if _rows:
                _bybp[_p.id] = _rows
        _gen = DailyLPGenerator(repo)
        # LP と同一の補完（新品・未使用・非resale 価格のみ採用、中古/resale 除外）
        _enriched = [_gen._enrich_deal(d, _bybp.get(d.product_id, [])) for d in _raw]

        # 14日(336h)超の手動価格は利益判定から除外（observed_at 基準・有効データのみ採用）
        def _obs_age_h(d):
            newest = None
            for r in _bybp.get(getattr(d, "product_id", "") or "", []):
                if (r.get("buyback_price", 0) or 0) <= 0:
                    continue
                if r.get("data_source") in ("fetch_failed", "product_not_listed", "resale_market"):
                    continue
                o = r.get("observed_at", "")
                if not o:
                    continue
                try:
                    dt = datetime.fromisoformat(str(o))
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=JST)
                    dt = dt.astimezone(JST)
                    if newest is None or dt > newest:
                        newest = dt
                except Exception:
                    pass
            if newest is None:
                return 0.0
            return (datetime.now(tz=JST) - newest).total_seconds() / 3600

        all_deals = []
        for d in _enriched:
            if (d.net_profit_jpy or 0) > 0 and _obs_age_h(d) > 336.0:
                _stale_excluded += 1
                continue  # 14日超は利益ランキングから除外
            all_deals.append(d)
    except Exception as e:
        print(f"[WARN] DB 読み込み/enrich 失敗: {e}", file=sys.stderr)
        all_deals = []

    # 初心者向け: 一次流通仕入れ → 二次流通販売 / 全カテゴリ / 利益あり / 差益順
    # camera も「公式→新品/未使用買取」モデルが成立するため beginner に含める。
    _BEGINNER_CATEGORIES = ("iphone", "game_console", "tablet", "wearable", "audio", "pc", "camera")
    beginner_top = sorted(
        [
            d for d in all_deals
            if getattr(d, "user_level", "") in ("beginner_easy", "beginner_watch")
            and getattr(d, "category", "") in _BEGINNER_CATEGORIES
            and d.net_profit_jpy >= 0
        ],
        key=lambda d: d.net_profit_jpy,
        reverse=True,
    )[:10]

    # Pro向け: 二次流通仕入れ → 二次流通販売 / 全カテゴリ / 利益率高い順 / camera・pc優先
    _PRO_PRIORITY_CATEGORIES = ("camera", "pc")
    _pro_all = sorted(
        [d for d in all_deals if d.net_profit_jpy >= 0],
        key=lambda d: (
            getattr(d, "category", "") in _PRO_PRIORITY_CATEGORIES,
            getattr(d, "net_profit_rate", 0) or 0,
        ),
        reverse=True,
    )
    pro_top = _pro_all[:10]

    # 赤字案件
    excluded = [d for d in all_deals if d.net_profit_jpy < 0]

    # カテゴリ別の仕入れ先ラベル（初心者向け一次流通）
    _BEGINNER_SOURCE_LABELS: dict[str, str] = {
        "iphone": "Apple Store",
        "game_console": "任天堂公式 / PlayStation Direct / Xbox Store",
        "camera": "RICOH公式 / FUJIFILM公式 / キタムラ",
        "tablet": "Apple Store",
    }
    _BEGINNER_SOURCE_DEFAULT = "公式ストア / 正規一次販売店"
    _DEST_LABEL = "メルカリ / ラクマ / ヤフオク / 国内買取店"

    def _deal_to_dict(d, is_beginner: bool = True) -> dict:
        """BeginnerDeal オブジェクトを辞書に変換する。"""
        cat = getattr(d, "category", "")
        if is_beginner:
            route_type = "primary_to_secondary"
            source_label = _BEGINNER_SOURCE_LABELS.get(cat, _BEGINNER_SOURCE_DEFAULT)
        else:
            route_type = "secondary_to_secondary"
            source_label = "中古市場 / フリマ / 買取店"
        return {
            "product_name": getattr(d, "product_name", ""),
            "category": cat,
            "user_level": getattr(d, "user_level", ""),
            "official_price_jpy": getattr(d, "official_price_jpy", None),
            "best_buyback_price": getattr(d, "best_buyback_price", None),
            "best_buyback_shop": getattr(d, "best_buyback_shop", ""),
            "net_profit_jpy": getattr(d, "net_profit_jpy", 0),
            "net_profit_rate": round(float(getattr(d, "net_profit_rate", 0) or 0), 4),
            "route_type": route_type,
            "source_label": source_label,
            "dest_label": _DEST_LABEL,
        }

    # reason_if_empty: データがない場合の理由を生成
    _beginner_cat_count = len([
        d for d in all_deals
        if getattr(d, "category", "") in _BEGINNER_CATEGORIES
    ])
    if len(all_deals) == 0 and _stale_excluded == 0:
        reason_if_empty = (
            "run-buyback-premium-check 未実行 or DBに beginner_deals データなし。"
            "import-buyback-csv / import-market-csv が先行して完了していることを確認してください。"
        )
    elif not beginner_top:
        # beginner ランキングが0件のときは必ず理由を明示する（Task 1）
        reason_if_empty = (
            f"有効な初心者ランキング候補なし（公式価格→新品/未使用の最高買取・14日以内・"
            f"price>0・suspicious/low除外）。"
            f"全{len(all_deals)}件中 初心者対象カテゴリ{_beginner_cat_count}件 / "
            f"14日超で除外{_stale_excluded}件。新品・未使用の買取価格取得が増え次第ランキングに反映されます。"
        )
    else:
        reason_if_empty = None

    # カテゴリ別初心者ランキング（利益額順）
    _ALL_BEG_CATEGORIES = ("iphone", "game_console", "tablet", "wearable", "audio", "pc", "camera")
    beginner_by_category: dict[str, list] = {}
    for cat in _ALL_BEG_CATEGORIES:
        cat_deals = sorted(
            [
                d for d in all_deals
                if getattr(d, "user_level", "") in ("beginner_easy", "beginner_watch")
                and getattr(d, "category", "") == cat
                and d.net_profit_jpy >= 0
            ],
            key=lambda d: d.net_profit_jpy,
            reverse=True,
        )[:5]  # カテゴリ別5件まで
        if cat_deals:
            beginner_by_category[cat] = [_deal_to_dict(d, is_beginner=True) for d in cat_deals]

    # カテゴリ別プロランキング（利益率順）
    _ALL_PRO_CATEGORIES = ("camera", "pc", "iphone", "game_console", "tablet", "wearable", "audio")
    pro_by_category: dict[str, list] = {}
    for cat in _ALL_PRO_CATEGORIES:
        cat_deals = sorted(
            [
                d for d in all_deals
                if d.net_profit_jpy >= 0
                and getattr(d, "category", "") == cat
            ],
            key=lambda d: getattr(d, "net_profit_rate", 0) or 0,
            reverse=True,
        )[:5]  # カテゴリ別5件まで
        if cat_deals:
            pro_by_category[cat] = [_deal_to_dict(d, is_beginner=False) for d in cat_deals]

    # ── Top Camera Buyback Opportunities（auto_scraped / confidence=high / fresh<=7d のみ）──
    top_camera_buyback = []
    try:
        import sqlite3 as _sq
        from datetime import datetime as _dt
        _con = _sq.connect(str(PROJECT_ROOT / "data" / "premium_monitor.db"))
        _con.row_factory = _sq.Row
        _prices = _con.execute(
            "SELECT b.product_id, b.shop_name, b.buyback_price, b.observed_at, b.notes, "
            "       p.name AS product_name, p.official_price, p.retail_price "
            "FROM buyback_prices b LEFT JOIN products p ON p.id=b.product_id "
            "WHERE b.is_active=1 AND b.data_source='auto_scraped' AND b.confidence='high' "
            "AND b.buyback_price>0"
        ).fetchall()
        _con.close()
        for r in _prices:
            d = dict(r)
            o = d.get("observed_at", "")
            try:
                dt = _dt.fromisoformat(str(o))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=JST)
                age_d = (now - dt.astimezone(JST)).total_seconds() / 86400
            except Exception:
                age_d = 0.0
            if age_d > 7:  # fresh<=7d のみ
                continue
            official = d.get("official_price") or d.get("retail_price") or 0
            bp = d.get("buyback_price", 0) or 0
            top_camera_buyback.append({
                "product_id": d.get("product_id"), "product_name": d.get("product_name", ""),
                "shop_name": d.get("shop_name", ""), "buyback_price": bp,
                "official_price": official, "diff_vs_official": (bp - official) if official else None,
                "matched_item": d.get("notes", ""), "confidence": "high",
                "source": "auto_scraped", "age_days": round(age_d, 1),
            })
        top_camera_buyback.sort(key=lambda x: (x["diff_vs_official"] if x["diff_vs_official"] is not None else x["buyback_price"]), reverse=True)
        top_camera_buyback = top_camera_buyback[:20]
    except Exception as e:
        print(f"[WARN] top_camera_buyback 生成失敗: {e}", file=sys.stderr)

    report: dict = {
        "generated_at": now.strftime("%Y-%m-%d %H:%M JST"),
        "route_type_beginner": "primary_to_secondary",
        "top_camera_buyback_opportunities": top_camera_buyback,
        "route_type_pro": "secondary_to_secondary",
        "beginner_top10": [_deal_to_dict(d, is_beginner=True) for d in beginner_top],
        "pro_top10": [_deal_to_dict(d, is_beginner=False) for d in pro_top],
        "beginner_by_category": beginner_by_category,
        "pro_by_category": pro_by_category,
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
        "## 👤 初心者ランキング Top10（一次仕入れ → 二次流通販売）",
        "",
    ])
    for i, d in enumerate(report["beginner_top10"], 1):
        lines.append(
            f"{i}. **{d['product_name']}** — 実質{_fmt_profit(d['net_profit_jpy'])} "
            f"({d['best_buyback_shop']})"
        )
    if not report["beginner_top10"]:
        lines.append("データなし")

    lines.extend(["", "## 🎯 Pro ランキング Top10（二次流通仕入れ → 二次流通販売）", ""])
    for i, d in enumerate(report["pro_top10"], 1):
        lines.append(
            f"{i}. **{d['product_name']}** — 実質{_fmt_profit(d['net_profit_jpy'])} "
            f"/ 利益率{d['net_profit_rate']*100:.1f}%"
        )
    if not report["pro_top10"]:
        lines.append("データなし")

    # カテゴリ別初心者ランキング
    if report.get("beginner_by_category"):
        lines.extend(["", "## 👤 カテゴリ別初心者ランキング（利益額順）", ""])
        for cat, deals in sorted(report["beginner_by_category"].items()):
            lines.append(f"### {cat.upper()}")
            for i, d in enumerate(deals, 1):
                lines.append(
                    f"{i}. **{d['product_name']}** — 実質{_fmt_profit(d['net_profit_jpy'])} "
                    f"({d['best_buyback_shop']})"
                )
            lines.append("")

    # カテゴリ別プロランキング
    if report.get("pro_by_category"):
        lines.extend(["", "## 🎯 カテゴリ別プロランキング（利益率順）", ""])
        for cat, deals in sorted(report["pro_by_category"].items()):
            lines.append(f"### {cat.upper()}")
            for i, d in enumerate(deals, 1):
                lines.append(
                    f"{i}. **{d['product_name']}** — 実質{_fmt_profit(d['net_profit_jpy'])} "
                    f"/ 利益率{d['net_profit_rate']*100:.1f}%"
                )
            lines.append("")

    md_path = REPORT_DIR / "latest.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"[INFO] ranking_report/latest.md 保存完了")

    return 0


if __name__ == "__main__":
    sys.exit(main())

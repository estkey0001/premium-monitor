#!/usr/bin/env python3
"""取得成功率・有効データ量レポート生成スクリプト（Task 5）。

毎日の取得結果を集約し、以下を exports/data_quality_report/latest.{json,md} に出力する。
  - 全対象店舗数 / 成功店舗数 / 失敗店舗数
  - 失敗理由の内訳（理由→件数）
  - 商品別の有効買取データ数（新品・未使用・未開封 / 14日以内 / price>0）
  - ranking に使えたデータ数（beginner / pro）
  - sedori に使えたデータ数（routes 件数）
  - overseas の fresh / stale 件数

入力:
  exports/collector_report/latest.json    （買取取得の成功/失敗・理由）
  exports/ranking_report/latest.json       （ranking 件数・reason_if_empty）
  exports/sedori_routes_report/latest.json （sedori 件数・reason_if_empty）
  exports/overseas_prices/latest.json      （overseas stale 件数）
  DB buyback_prices                          （商品別の有効データ数）

実行:
  python scripts/generate_data_quality_report.py
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

JST = timezone(timedelta(hours=9))
ROOT = Path(__file__).parent.parent
OUT_DIR = ROOT / "exports" / "data_quality_report"

# 有効データ判定
VALID_NEW_CONDS = ("new", "new_unopened", "new_unopened_simfree", "unused", "sealed",
                   "新品", "未使用", "未開封", "新品未開封")
EXCLUDE_STALE_H = 336.0  # 14日


def _load_json(path: Path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _is_used(cond: str) -> bool:
    c = (cond or "").lower()
    return any(k in c for k in ("中古", "美品", "良品", "used", "b品", "c品", "ジャンク", "開封済"))


def _valid_buyback_counts(now):
    """商品別の有効買取データ数（新品・未使用 / 14日以内 / price>0）を返す。"""
    counts = {}
    try:
        import sqlite3
        con = sqlite3.connect(str(ROOT / "data" / "premium_monitor.db"))
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT product_id, condition, buyback_price, observed_at, data_source, "
            "COALESCE(confidence,'high') AS confidence "
            "FROM buyback_prices WHERE is_active=1"
        ).fetchall()
        con.close()
    except Exception as e:
        print(f"[WARN] DB読み込み失敗: {e}", file=sys.stderr)
        return counts
    for r in rows:
        d = dict(r)
        pid = d.get("product_id", "")
        if (d.get("buyback_price", 0) or 0) <= 0:
            continue
        if _is_used(d.get("condition", "")):
            continue
        if d.get("confidence", "high") == "low":
            continue
        if d.get("data_source") in ("fetch_failed", "product_not_listed", "resale_market"):
            continue
        # 14日以内
        o = d.get("observed_at", "")
        try:
            dt = datetime.fromisoformat(str(o))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=JST)
            age_h = (now - dt.astimezone(JST)).total_seconds() / 3600
            if age_h > EXCLUDE_STALE_H:
                continue
        except Exception:
            pass
        counts[pid] = counts.get(pid, 0) + 1
    return counts


def main() -> int:
    now = datetime.now(tz=JST)
    print(f"[generate_data_quality_report] 開始: {now.strftime('%Y-%m-%d %H:%M')} JST")

    collector = _load_json(ROOT / "exports/collector_report/latest.json") or {}
    ranking = _load_json(ROOT / "exports/ranking_report/latest.json") or {}
    sedori = _load_json(ROOT / "exports/sedori_routes_report/latest.json") or {}
    overseas = _load_json(ROOT / "exports/overseas_prices/latest.json") or {}

    summary = collector.get("summary", {}) or {}
    total_shops = len(collector.get("by_shop", {}) or {})
    ok_jobs = summary.get("ok", 0)
    failed_jobs = summary.get("failed", 0)
    skip_jobs = summary.get("skip", 0)
    total_jobs = summary.get("total", ok_jobs + failed_jobs + skip_jobs)

    # 店舗別 成功/失敗
    shops_with_success = sum(1 for v in (collector.get("by_shop", {}) or {}).values()
                             if (v.get("ok", 0) or 0) > 0)
    shops_all_failed = sum(1 for v in (collector.get("by_shop", {}) or {}).values()
                           if (v.get("ok", 0) or 0) == 0 and (v.get("failed", 0) or 0) > 0)

    failure_reasons = collector.get("failure_reason_ranking", []) or []

    valid_counts = _valid_buyback_counts(now)
    products_with_valid = sum(1 for v in valid_counts.values() if v > 0)

    # ranking / sedori 使用データ数
    beginner_n = len(ranking.get("beginner_top10", []) or [])
    pro_n = len(ranking.get("pro_top10", []) or [])
    ranking_reason = ranking.get("reason_if_empty")
    # sedori レポートは profitable_routes（int）/ pro_routes.count を持つ。
    if isinstance(sedori.get("profitable_routes"), int):
        sedori_routes_n = sedori["profitable_routes"]
    else:
        _sed_pro = sedori.get("pro_routes", {})
        if isinstance(_sed_pro, dict):
            sedori_routes_n = int(_sed_pro.get("count", 0) or 0)
        elif isinstance(_sed_pro, list):
            sedori_routes_n = len(_sed_pro)
        else:
            sedori_routes_n = len(sedori.get("routes", []) or [])
    sedori_reason = sedori.get("reason_if_empty")

    # overseas fresh / stale
    ovs_total = int(overseas.get("total_prices", 0) or 0)
    ovs_stale = int(overseas.get("stale_count", 0) or 0)
    ovs_fresh = max(0, ovs_total - ovs_stale)
    ovs_mode = overseas.get("source_mode", "unknown")
    ovs_ebay_configured = bool(overseas.get("ebay_app_id_configured", False))

    success_rate = round(100.0 * ok_jobs / total_jobs, 1) if total_jobs else 0.0

    # ── 前回との比較（Task 3）── 上書き前の latest.json を読む
    prev = _load_json(ROOT / "exports/data_quality_report/latest.json") or {}
    prev_rate = (prev.get("collection", {}) or {}).get("success_rate_pct")
    if isinstance(prev_rate, (int, float)):
        delta = round(success_rate - prev_rate, 1)
        trend = "改善" if delta > 0 else ("悪化" if delta < 0 else "横ばい")
    else:
        delta = None
        trend = "初回"
    top5_reasons = failure_reasons[:5]
    comparison = {
        "prev_success_rate_pct": prev_rate,
        "current_success_rate_pct": success_rate,
        "delta_pct": delta,
        "trend": trend,
        "top5_failure_reasons": top5_reasons,
    }

    report = {
        "generated_at": now.isoformat(timespec="seconds"),
        "collection": {
            "total_shops": total_shops,
            "shops_with_success": shops_with_success,
            "shops_all_failed": shops_all_failed,
            "total_jobs": total_jobs,
            "ok_jobs": ok_jobs,
            "failed_jobs": failed_jobs,
            "skip_jobs": skip_jobs,
            "success_rate_pct": success_rate,
        },
        "comparison": comparison,
        "failure_reasons": failure_reasons,
        "effective_data": {
            "products_with_valid_buyback": products_with_valid,
            "valid_buyback_by_product": valid_counts,
        },
        "ranking_usable": {
            "beginner": beginner_n,
            "pro": pro_n,
            "reason_if_empty": ranking_reason,
        },
        "sedori_usable": {
            "routes": sedori_routes_n,
            "reason_if_empty": sedori_reason,
        },
        "overseas": {
            "total": ovs_total,
            "fresh": ovs_fresh,
            "stale": ovs_stale,
            "source_mode": ovs_mode,
            "ebay_app_id_configured": ovs_ebay_configured,
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # 履歴に追記（成功率推移の追跡用）
    try:
        with open(OUT_DIR / "history.jsonl", "a", encoding="utf-8") as _hf:
            _hf.write(json.dumps({"at": now.isoformat(timespec="seconds"),
                                  "success_rate_pct": success_rate,
                                  "ok": ok_jobs, "failed": failed_jobs}, ensure_ascii=False) + "\n")
    except Exception:
        pass
    (OUT_DIR / "latest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # Markdown
    lines = [
        f"# データ取得品質レポート（{now.strftime('%Y-%m-%d %H:%M')} JST）",
        "",
        "## 取得成功率",
        f"- 全対象店舗数: {total_shops}",
        f"- 成功店舗数: {shops_with_success}",
        f"- 全失敗店舗数: {shops_all_failed}",
        f"- ジョブ成功率: {success_rate}%（OK {ok_jobs} / 失敗 {failed_jobs} / SKIP {skip_jobs} / 計 {total_jobs}）",
        "",
        "## 前回比較",
        f"- 前回成功率: {prev_rate if prev_rate is not None else '—'}%",
        f"- 今回成功率: {success_rate}%",
        f"- 変化: {('+' if (delta or 0) > 0 else '')}{delta if delta is not None else '—'}pt（{trend}）",
        "- 主要失敗理由 TOP5: "
        + (", ".join(f"{r.get('reason')} {r.get('count')}" for r in top5_reasons) or "なし"),
        "",
        "## 失敗理由（内訳）",
    ]
    if failure_reasons:
        for fr in failure_reasons:
            lines.append(f"- {fr.get('reason','?')}: {fr.get('count',0)}件")
    else:
        lines.append("- 失敗なし")
    lines += [
        "",
        "## 有効データ量（新品・未使用 / 14日以内 / price>0）",
        f"- 有効買取データを持つ商品数: {products_with_valid}",
    ]
    for pid, n in sorted(valid_counts.items(), key=lambda x: -x[1])[:15]:
        lines.append(f"  - {pid}: {n}店舗")
    lines += [
        "",
        "## ランキングに使えたデータ数",
        f"- Beginner: {beginner_n} 件",
        f"- Pro: {pro_n} 件",
    ]
    if ranking_reason:
        lines.append(f"- ⚠️ reason_if_empty: {ranking_reason}")
    lines += [
        "",
        "## せどりルートに使えたデータ数",
        f"- ルート: {sedori_routes_n} 件",
    ]
    if sedori_reason:
        lines.append(f"- ⚠️ reason_if_empty: {sedori_reason}")
    lines += [
        "",
        "## 海外価格の鮮度",
        f"- fresh: {ovs_fresh} / stale: {ovs_stale} / 計 {ovs_total}",
        f"- eBay取得モード: {ovs_mode}（EBAY_APP_ID設定: {'あり' if ovs_ebay_configured else '未設定→stale除外'}）",
    ]
    (OUT_DIR / "latest.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"[INFO] data_quality_report/latest.json 保存完了 "
          f"(成功率 {success_rate}% / 有効データ商品 {products_with_valid} / "
          f"ranking beginner={beginner_n} pro={pro_n} / sedori={sedori_routes_n})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

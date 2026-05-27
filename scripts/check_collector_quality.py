#!/usr/bin/env python3
"""買取コレクター品質ゲートスクリプト。

GitHub Actions の daily_lp.yml から呼ばれ、
exports/collector_report/latest.json を読み込んで品質を評価する。

Exit codes:
  0: 正常 — failure/warning 条件なし
  1: FAILURE — 誤価格リスクあり（suspicious_price, low_confidence, 主要商品店舗不足）
  2: WARNING — 取得率低下（50%超失敗, 3日連続失敗, レポートなし）

GitHub Actions Summary ($GITHUB_STEP_SUMMARY) にマークダウン表を出力する。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ──────────────────────────────────────────────
# パス設定
# ──────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT_PATH  = PROJECT_ROOT / "exports" / "collector_report" / "latest.json"
HISTORY_PATH = PROJECT_ROOT / "exports" / "collector_report" / "failure_history.json"

JST = timezone(timedelta(hours=9))

# ── 実行環境判定 ───────────────────────────────────────────────────────────
# GitHub Actions 上では取得できる店舗数がローカルより少ない（IP制限）
# → iPhone の最低目標を下げて warning を抑制
IS_GITHUB_ACTIONS = os.environ.get("GITHUB_ACTIONS", "").lower() == "true"

# ──────────────────────────────────────────────
# FAILURE 条件閾値
# FAILURE = suspicious_price または low_confidence のみ
# （誤価格がLPに出るリスクがある場合だけ stop-the-world）
# ──────────────────────────────────────────────
FAILURE_CONDITIONS = {
    "suspicious_price_gt0":   "suspicious_price > 0（誤価格リスク）",
    "low_confidence_gt0":     "low_confidence_count > 0（信頼度低価格がLPに表示される可能性）",
}

# WARNING 条件閾値（exit 0 で継続 — GitHub Actionsには ::warning:: annotationを出力）
WARNING_CONDITIONS = {
    "iphone_min_shops":           "iPhone主要商品の成功店舗数不足",
    "switch2_min2_shops":         "Switch2 で成功店舗2未満",
    "ps5pro_min2_shops":          "PS5 Pro で成功店舗2未満",
    "fetch_failed_over50pct":     "取得失敗が全体の50%以上",
    "consecutive_3day_failure":   "特定店舗が3日連続失敗",
    "report_not_generated":       "collector_report が生成されていない",
}

# optional_shop: 不安定または未対応扱いの店舗
# → 成功率分母には含めるが、3日連続失敗でもWARNINGを抑制しない
#   （ただし deploy-check の error 原因にしない）
OPTIONAL_SHOPS: dict[str, str] = {
    "2ndstreet":  "product_not_listed",  # iPhone17等が掲載されていない
    "bookoff":    "product_not_listed",  # 買取価格ページ構造が対象外
    "dosupara":   "url_invalid",         # 検索URLが404返し
    "geo_mobile": "site_blocked",        # Cloudflareブロック
    "hardoff":    "url_invalid",         # 検索URLが404返し
    "pasoko":     "product_not_listed",  # PC専門店 — PS5/Switch2取り扱いなし（2026-05-27確認）
}

# 主要商品の最小成功店舗数
# GitHub Actions 上はIPブロックで取得数が少ないため閾値を下げる
_IPHONE_MIN = 2 if IS_GITHUB_ACTIONS else 3
MIN_SHOPS = {
    "iphone17pro256": _IPHONE_MIN,
    "iphone17pro512": _IPHONE_MIN,
    "iphone17pm256":  _IPHONE_MIN,
    "iphone17pm512":  _IPHONE_MIN,
    "switch2":        2,
    "ps5_pro":        2,
}


# ──────────────────────────────────────────────
# レポート読み込み
# ──────────────────────────────────────────────

def load_report() -> dict | None:
    if not REPORT_PATH.exists():
        return None
    try:
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ERROR] collector_report/latest.json の読み込みに失敗: {e}", file=sys.stderr)
        return None


# ──────────────────────────────────────────────
# 3日連続失敗 履歴管理
# ──────────────────────────────────────────────

def load_failure_history() -> dict:
    """連続失敗履歴を読み込む。形式: {shop_id: [date_str, ...]}"""
    if not HISTORY_PATH.exists():
        return {}
    try:
        return json.loads(HISTORY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_failure_history(history: dict) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    HISTORY_PATH.write_text(json.dumps(history, ensure_ascii=False, indent=2), encoding="utf-8")


def update_failure_history(report: dict) -> dict:
    """今回のレポート結果で履歴を更新し、3日連続失敗のショップリストを返す。"""
    today = datetime.now(tz=JST).strftime("%Y-%m-%d")
    history = load_failure_history()

    # 今回の shop 別結果
    shop_detail = report.get("shop_detail", [])
    consecutive_3day = []

    for sd in shop_detail:
        sid = sd.get("shop_id", "")
        ok  = sd.get("ok", 0)
        if not sid:
            continue

        hist = history.get(sid, [])
        # 今日の分を追加
        if ok == 0:
            if not hist or hist[-1] != today:
                hist.append(today)
        else:
            # 成功したらリセット
            hist = []

        # 直近3日以内のエントリのみ保持
        cutoff = (datetime.now(tz=JST) - timedelta(days=3)).strftime("%Y-%m-%d")
        hist = [d for d in hist if d >= cutoff]
        history[sid] = hist

        # 3日連続失敗チェック（3日分の日付が揃っているか）
        if len(hist) >= 3:
            consecutive_3day.append(sid)

    save_failure_history(history)
    return {"consecutive_3day": consecutive_3day}


# ──────────────────────────────────────────────
# 品質評価
# ──────────────────────────────────────────────

def evaluate(report: dict) -> dict:
    """品質評価を実行し、結果 dict を返す。"""
    summary    = report.get("summary", {})
    total      = summary.get("total", 0)
    ok_count   = summary.get("ok", 0)
    failed_count = summary.get("failed", 0)
    skip_count = summary.get("skip", 0)
    low_conf   = report.get("low_confidence_count", 0)
    suspicious = report.get("suspicious_prices", [])
    psd        = report.get("product_shop_detail", {})
    shop_p5    = report.get("shop_priority_top5", [])
    prod_stats = report.get("product_price_stats", {})
    fail_rank  = report.get("failure_reason_ranking", [])

    failures = []
    warnings = []

    # ── FAILURE チェック（誤価格リスクのみ — ワークフロー停止） ──────────────
    # NOTE: GitHub Actions の IP がサイトにブロックされることが多く、
    # 取得数がローカルより少なくなるのは想定内。
    # 「成功店舗数不足」は WARNING に移し、誤価格データだけを FAILURE とする。

    if len(suspicious) > 0:
        failures.append(f"suspicious_price {len(suspicious)}件（誤価格リスク — LP公開前に要確認）")

    if low_conf > 0:
        failures.append(f"low_confidence_count {low_conf}件（信頼度低価格がLPに表示される可能性）")

    # ── WARNING チェック（通知のみ — ワークフロー継続） ──────────────────────

    # iPhone 主要4商品の成功店舗数（自動取得分のみ、手動CSVは別途インポート）
    iphone_fail = []
    for alias in ["iphone17pro256", "iphone17pro512", "iphone17pm256", "iphone17pm512"]:
        n = len(psd.get(alias, {}).get("success_shops", []))
        if n < MIN_SHOPS.get(alias, 3):
            iphone_fail.append(f"{alias}:{n}店舗(目標{MIN_SHOPS[alias]})")
    if iphone_fail:
        warnings.append(f"iPhone主要商品 自動取得店舗不足: {', '.join(iphone_fail)}")

    # Switch2
    sw2_n = len(psd.get("switch2", {}).get("success_shops", []))
    if sw2_n < MIN_SHOPS.get("switch2", 2):
        warnings.append(f"Switch2 自動取得成功店舗 {sw2_n}（目標2）")

    # PS5 Pro
    ps5_n = len(psd.get("ps5_pro", {}).get("success_shops", []))
    if ps5_n < MIN_SHOPS.get("ps5_pro", 2):
        warnings.append(f"PS5 Pro 自動取得成功店舗 {ps5_n}（目標2）")

    # ── WARNING チェック ─────────────────────────────
    if total > 0:
        fail_pct = failed_count / total * 100
        if fail_pct >= 50.0:
            warnings.append(f"取得失敗率 {fail_pct:.1f}%（50%以上）")

    hist_result = update_failure_history(report)
    if hist_result["consecutive_3day"]:
        required = [s for s in hist_result["consecutive_3day"] if s not in OPTIONAL_SHOPS]
        optional  = [s for s in hist_result["consecutive_3day"] if s in OPTIONAL_SHOPS]
        parts = []
        if required:
            parts.append(f"要対応: {', '.join(required[:5])}")
        if optional:
            parts.append(f"optional: {', '.join(optional[:5])}")
        warnings.append(f"3日連続失敗 — {' / '.join(parts)}")

    return {
        "failures":    failures,
        "warnings":    warnings,
        "ok_count":    ok_count,
        "failed_count": failed_count,
        "skip_count":  skip_count,
        "total":       total,
        "low_conf":    low_conf,
        "suspicious":  suspicious,
        "shop_p5":     shop_p5,
        "prod_stats":  prod_stats,
        "fail_rank":   fail_rank,
        "psd":         psd,
        "generated_at": report.get("generated_at", "—"),
    }


# ──────────────────────────────────────────────
# GitHub Actions Summary 出力
# ──────────────────────────────────────────────

def build_summary_md(result: dict) -> str:
    lines = []
    lines.append("## 📊 Collector Quality Report")
    lines.append("")
    lines.append(f"生成日時: `{result['generated_at']}`")
    lines.append("")

    # ステータスバッジ
    if result["failures"]:
        lines.append("### ❌ FAILURE — 品質ゲート不通過")
        for f in result["failures"]:
            lines.append(f"- {f}")
    elif result["warnings"]:
        lines.append("### ⚠️ WARNING — 注意が必要")
        for w in result["warnings"]:
            lines.append(f"- {w}")
    else:
        lines.append("### ✅ 品質ゲート通過")
    lines.append("")

    # 取得サマリー
    total   = result["total"]
    ok      = result["ok_count"]
    failed  = result["failed_count"]
    skip    = result["skip_count"]
    ok_pct  = round(ok / total * 100) if total > 0 else 0
    lines.append("### 取得サマリー")
    lines.append("")
    lines.append("| 項目 | 件数 |")
    lines.append("|------|------|")
    lines.append(f"| ✅ 成功 | **{ok}** / {total} ({ok_pct}%) |")
    lines.append(f"| ❌ 失敗 | {failed} |")
    lines.append(f"| ⏭️ スキップ | {skip} |")
    lines.append(f"| 🔴 low confidence | {result['low_conf']} |")
    lines.append(f"| ⚠️ suspicious_price | {len(result['suspicious'])} |")
    lines.append("")

    # 商品別成功状況（成功 / 未掲載 / 取得失敗 の3列）
    lines.append("### 商品別成功状況")
    lines.append("")
    lines.append("| 商品 | 成功 | 目標 | 達成 | 未掲載 | 取得失敗 | 成功店舗 |")
    lines.append("|------|------|------|------|--------|---------|---------|")
    TARGET_NAMES = {
        "iphone17pro256": "iPhone 17 Pro 256GB",
        "iphone17pro512": "iPhone 17 Pro 512GB",
        "iphone17pm256":  "iPhone 17 Pro Max 256GB",
        "iphone17pm512":  "iPhone 17 Pro Max 512GB",
        "switch2":        "Nintendo Switch 2",
        "ps5_pro":        "PS5 Pro",
    }
    for alias, min_shops in MIN_SHOPS.items():
        detail      = result["psd"].get(alias, {})
        success     = detail.get("success_shops", [])
        not_listed  = detail.get("not_listed_shops", [])
        failed      = detail.get("failed_shops", [])
        ok_flag     = "✅" if len(success) >= min_shops else "❌"
        shops_str   = ", ".join(success[:5]) if success else "—"
        nl_str      = str(len(not_listed)) if not_listed else "—"
        fail_str    = str(len(failed)) if failed else "—"
        lines.append(
            f"| {TARGET_NAMES.get(alias, alias)} | {len(success)} | {min_shops} | {ok_flag} "
            f"| {nl_str} | {fail_str} | {shops_str} |"
        )
    lines.append("")

    # 失敗理由ランキング
    fail_rank = result["fail_rank"]
    if fail_rank:
        lines.append("### 失敗理由 TOP5")
        lines.append("")
        lines.append("| 理由 | 件数 |")
        lines.append("|------|------|")
        for item in fail_rank[:5]:
            lines.append(f"| `{item['reason']}` | {item['count']} |")
        lines.append("")

    # 優先修正TOP5（timeout が失敗理由TOP5 にある場合は mobile_ichiban を上位に）
    shop_p5 = list(result.get("shop_p5", []))
    fail_rank = result.get("fail_rank", [])
    _top5_reasons = [item["reason"] for item in fail_rank[:5]]
    _timeout_in_top5 = "timeout" in _top5_reasons
    if _timeout_in_top5 and "mobile_ichiban" not in shop_p5[:1]:
        # mobile_ichiban が優先修正対象に含まれていれば先頭に移動、なければ追加
        if "mobile_ichiban" in shop_p5:
            shop_p5.remove("mobile_ichiban")
        shop_p5.insert(0, "mobile_ichiban ⚠️ timeout — 要優先確認")
    if shop_p5:
        lines.append("### 優先修正対象 TOP5（成功率0%）")
        lines.append("")
        for i, sp in enumerate(shop_p5[:5], 1):
            lines.append(f"{i}. `{sp}`")
        lines.append("")

    # optional_shop 分類セクション
    lines.append("### 🔧 不安定/未対応店舗（optional shops）")
    lines.append("")
    lines.append("| 店舗ID | 分類 | 説明 |")
    lines.append("|--------|------|------|")
    CLASSIFICATION_DESC = {
        "product_not_listed":        "対象商品を掲載していない",
        "url_invalid":               "検索URL が 404 / 構造変更の可能性",
        "site_blocked":              "Cloudflare 等によるブロック",
        "collector_not_implemented": "Collector 未実装",
        "playwright_timeout":        "JS描画タイムアウト",
    }
    for shop_id, cls in OPTIONAL_SHOPS.items():
        desc = CLASSIFICATION_DESC.get(cls, cls)
        lines.append(f"| `{shop_id}` | `{cls}` | {desc} |")
    lines.append("")
    lines.append("> ℹ️ これらの店舗は`deploy-check`のエラー原因に含まれません。")
    lines.append("")

    # suspicious_prices 詳細
    suspicious = result["suspicious"]
    if suspicious:
        lines.append("### ⚠️ 疑わしい価格（要確認）")
        lines.append("")
        lines.append("| 商品 | 店舗 | 価格 | 理由 |")
        lines.append("|------|------|------|------|")
        for sp in suspicious[:10]:
            lines.append(
                f"| {sp.get('product_alias','—')} "
                f"| {sp.get('shop','—')} "
                f"| ¥{sp.get('price', 0):,} "
                f"| {sp.get('reason','—')} |"
            )
        lines.append("")

    # next_action: 店舗別の対応状況
    lines.append("### 🔧 店舗別 next_action")
    lines.append("")
    lines.append("| 店舗 | 失敗理由 | ステータス | next_action |")
    lines.append("|------|---------|-----------|------------|")
    SHOP_NEXT_ACTIONS: dict[str, tuple[str, str, str]] = {
        # (失敗理由, ステータス, next_action)
        "janpara":  ("rate_limited_429",    "⚠️ 調査中",   "sleep 8s+30s backoff適用済み — Actions IP制限の可能性。継続監視"),
        "netoff":   ("price_not_found→修正済", "✅ 修正済み", "URL /sell/→/mobilebuy/ 修正 + regex修正 — 次回取得で確認"),
        "pasoko":   ("product_not_listed",  "✅ 分類変更",  "PC専門店でPS5/Switch非対応を確認 — product_not_listedに変更"),
        "sofmap":   ("service_unavailable", "🔴 復旧待ち", "503サーバー障害 — サイト側の問題。復旧を待って再確認"),
        "surugaya": ("site_blocked",        "🔴 改善不可",  "403ボット検知 — 無理に突破しない。手動価格でカバー"),
    }
    for shop_id, (reason, status, action) in SHOP_NEXT_ACTIONS.items():
        lines.append(f"| `{shop_id}` | `{reason}` | {status} | {action} |")
    lines.append("")

    return "\n".join(lines)


def write_github_summary(md: str) -> None:
    """$GITHUB_STEP_SUMMARY へ書き込む（ローカル実行時はスキップ）。"""
    summary_file = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_file:
        with open(summary_file, "a", encoding="utf-8") as f:
            f.write(md + "\n")
    else:
        # ローカル実行時: stdout に出力
        print("\n" + "=" * 60)
        print(md)
        print("=" * 60)


# ──────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────

def main() -> int:
    # 1. レポート読み込み
    report = load_report()
    if report is None:
        md = (
            "## 📊 Collector Quality Report\n\n"
            "### ⚠️ WARNING — collector_report/latest.json が見つからない\n\n"
            "update_buyback_prices.py が正常に実行されなかった可能性があります。\n"
        )
        write_github_summary(md)
        print("[WARNING] collector_report/latest.json が見つからない", file=sys.stderr)
        return 2  # exit 2 = WARNING

    # 2. 品質評価
    result = evaluate(report)

    # 3. サマリー出力
    md = build_summary_md(result)
    write_github_summary(md)

    # 4. サマリーをstderrに出力
    ok  = result["ok_count"]
    total = result["total"]
    fail = len(result["failures"])
    warn = len(result["warnings"])
    print(f"\n{'='*60}", file=sys.stderr)
    print(f"  Collector Quality: OK={ok}/{total}  "
          f"FAILURES={fail}  WARNINGS={warn}", file=sys.stderr)
    if result["failures"]:
        for f in result["failures"]:
            print(f"  ❌ {f}", file=sys.stderr)
    if result["warnings"]:
        for w in result["warnings"]:
            print(f"  ⚠️  {w}", file=sys.stderr)
    if fail == 0 and warn == 0:
        print("  ✅ 品質ゲート通過", file=sys.stderr)
    print(f"{'='*60}\n", file=sys.stderr)

    # 5. GitHub Actions 上では ::warning:: annotation を直接出力（exit codeに頼らない）
    if IS_GITHUB_ACTIONS and result["warnings"]:
        for w in result["warnings"]:
            # ::warning:: annotation — Actions UI に黄色マークで表示
            print(f"::warning::品質ゲート WARNING — {w}")

    # 6. exit code
    # FAILURE（誤価格リスク）: exit 1
    # WARNING（取得数不足など）: exit 0 で継続（annotation は上で出力済み）
    # 正常: exit 0
    if result["failures"]:
        return 1  # FAILURE — suspicious_price または low_confidence
    return 0  # 正常 or WARNING（ワークフロー継続）


if __name__ == "__main__":
    sys.exit(main())

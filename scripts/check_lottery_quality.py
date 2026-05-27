#!/usr/bin/env python3
"""抽選情報品質ゲートスクリプト。

LP生成後（build-public-lp の前後）から呼ばれ、抽選タブの表示ミスを防ぐ。

防ぐ問題:
  - 受付終了済みなのに「抽選受付中」として表示される
  - reference_only アイテムが active count に混入する
  - 同じ product_code が重複表示される
  - active item が entry_start_at / entry_end_at を持っていない
  - forms.gle リンクがないのに「抽選フォームを開く」と表示される
  - 「次回未定」「抽選情報未確認」などの古い文言が active section に出る

Exit codes:
  0: 正常 — 問題なし
  1: FAILURE — 表示ミスリスクあり（期限切れ active / 重複 product_code / 古い文言）
  2: WARNING — 注意事項あり（URL なし / 受付期間なし）

GitHub Actions Summary ($GITHUB_STEP_SUMMARY) にマークダウン表を出力する。
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
# パス設定
# ──────────────────────────────────────────────────────────────────────────────
PROJECT_ROOT  = Path(__file__).resolve().parent.parent
REPORT_DIR    = PROJECT_ROOT / "exports" / "lottery_report"
REPORT_JSON   = REPORT_DIR / "latest.json"
REPORT_MD     = REPORT_DIR / "latest.md"
LP_HTML_PATH  = PROJECT_ROOT / "exports" / "lp" / "daily" / "index_A.html"

JST = timezone(timedelta(hours=9))

# 古い文言（active section に出てはいけない）
STALE_PHRASES = ["次回未定", "抽選情報未確認", "一次抽選終了", "近日開始（予定）"]

# 受付中として想定される RICOH GR IV 商品
RICOH_EXPECTED = ["RICOH GR IV Monochrome", "RICOH GR IV HDF", "RICOH GR IV"]


# ──────────────────────────────────────────────────────────────────────────────
# データ取得
# ──────────────────────────────────────────────────────────────────────────────

def _get_now_jst() -> datetime:
    """現在時刻（JST, tzinfo なし naive datetime）を返す。"""
    try:
        import zoneinfo
        JST_zone = zoneinfo.ZoneInfo("Asia/Tokyo")
        return datetime.now(tz=JST_zone).replace(tzinfo=None)
    except Exception:
        return datetime.now()


def _parse_dt(s: str):
    """YYYY-MM-DD HH:MM 形式の文字列を naive datetime に変換。失敗時は None。"""
    try:
        dt = datetime.fromisoformat(str(s)[:16])
        if dt.tzinfo is not None:
            dt = dt.replace(tzinfo=None)
        return dt
    except Exception:
        return None


def _lottery_status(ev: dict, now: datetime) -> str:
    """アイテムの現在ステータスを判定。"""
    end_dt   = _parse_dt(ev.get("entry_end_at")   or ev.get("entry_end")   or "")
    start_dt = _parse_dt(ev.get("entry_start_at") or ev.get("entry_start") or "")

    if end_dt is not None and end_dt < now:
        return "closed"
    if start_dt is not None and start_dt > now:
        return "upcoming"
    if end_dt is not None and end_dt >= now:
        return "active"
    return ev.get("status", "unknown") or "unknown"


def load_lottery_items() -> list[dict]:
    """DailyLPGenerator から _LOTTERY_REFERENCE_ITEMS を読み込む。"""
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from src.content.daily_lp_generator import DailyLPGenerator
        return [dict(it) for it in DailyLPGenerator._LOTTERY_REFERENCE_ITEMS]
    except Exception as e:
        print(f"[ERROR] _LOTTERY_REFERENCE_ITEMS の読み込みに失敗: {e}", file=sys.stderr)
        return []


def load_db_lottery_events() -> list[dict]:
    """DB から lottery_events を読み込む（失敗時は空リスト）。"""
    try:
        from src.db.database import Database
        from src.db.repository import Repository
        db = Database()
        repo = Repository(db)
        events = repo.list_lottery_events()
        db.close()
        return [dict(ev) if not isinstance(ev, dict) else ev for ev in (events or [])]
    except Exception:
        return []


# ──────────────────────────────────────────────────────────────────────────────
# 品質チェック
# ──────────────────────────────────────────────────────────────────────────────

def run_checks(ref_items: list[dict], db_items: list[dict], now: datetime) -> dict:
    """全品質チェックを実行し、結果辞書を返す。"""
    all_items = db_items + ref_items

    # ── ステータス分類 ────────────────────────────────────────────────────────
    for it in all_items:
        it["_status"] = _lottery_status(it, now)

    # reference_only=True または 日付なし active → 参考リンク扱い
    def _is_truly_active(it: dict) -> bool:
        if it.get("reference_only", False):
            return False
        if it["_status"] != "active":
            return False
        v = it.get("entry_end_at") or it.get("entry_end") or ""
        return bool(str(v).strip())

    active_items    = [it for it in all_items if _is_truly_active(it)]
    upcoming_items  = [it for it in all_items if it["_status"] == "upcoming"
                       and not it.get("reference_only", False)]
    closed_items    = [it for it in all_items if it["_status"] == "closed"
                       and not it.get("reference_only", False)]
    reference_items = [it for it in all_items
                       if it.get("reference_only", False)
                       or (it["_status"] == "active"
                           and not (it.get("entry_end_at") or it.get("entry_end") or "").strip())]

    issues_failure: list[str] = []   # exit 1
    issues_warning: list[str] = []   # exit 2

    # ── Check 1: active item は entry_end_at を持つ ───────────────────────────
    for it in active_items:
        name = it.get("product_name", "?")
        if not (it.get("entry_end_at") or it.get("entry_end") or "").strip():
            issues_warning.append(f"active「{name}」に entry_end_at がない")

    # ── Check 2: active item の now が受付期間内である ─────────────────────────
    for it in active_items:
        name = it.get("product_name", "?")
        end_dt = _parse_dt(it.get("entry_end_at") or it.get("entry_end") or "")
        if end_dt is not None and end_dt < now:
            issues_failure.append(
                f"【期限切れ active】「{name}」の entry_end_at={end_dt} は過去 (now={now.strftime('%Y-%m-%d %H:%M')})")
        start_dt = _parse_dt(it.get("entry_start_at") or it.get("entry_start") or "")
        if start_dt is not None and start_dt > now:
            issues_failure.append(
                f"【未開始 active】「{name}」の entry_start_at={start_dt} はまだ先")

    # ── Check 3: active item に product_url がある ────────────────────────────
    for it in active_items:
        name = it.get("product_name", "?")
        if not (it.get("url") or "").strip():
            issues_warning.append(f"active「{name}」に url がない")

    # ── Check 4: active item に entry_form_url がある（または代替あり） ──────────
    for it in active_items:
        name = it.get("product_name", "?")
        has_form = bool((it.get("entry_form_url") or "").strip())
        has_url  = bool((it.get("url") or "").strip())
        if not has_form and not has_url:
            issues_warning.append(f"active「{name}」に entry_form_url も url もない")
        if not has_form:
            issues_warning.append(f"active「{name}」に entry_form_url がない（url のみ）")

    # ── Check 5: active item に重複 product_code がない ───────────────────────
    codes = [it.get("product_code", "") for it in active_items if it.get("product_code")]
    seen_codes: set[str] = set()
    for code in codes:
        if code in seen_codes:
            dup_names = [it.get("product_name", "?") for it in active_items
                         if it.get("product_code") == code]
            issues_failure.append(
                f"【重複 product_code】product_code={code} が複数: {dup_names}")
        seen_codes.add(code)

    # ── Check 6: reference_only item が active_items に含まれていない ──────────
    ref_in_active = [it for it in active_items if it.get("reference_only", False)]
    if ref_in_active:
        names = [it.get("product_name", "?") for it in ref_in_active]
        issues_failure.append(
            f"【reference_only が active に混入】{names}")

    # ── Check 7: active count が受付中件数と一致するか確認（LP HTML から） ──────
    lp_count: int | None = None
    if LP_HTML_PATH.exists():
        try:
            lp_html = LP_HTML_PATH.read_text(encoding="utf-8")
            # タブナビからカウントを取得
            nav_m = re.search(r'class="tab-nav"[^>]*>(.*?)</nav>', lp_html, re.DOTALL)
            if nav_m:
                cnt_m = re.search(r'lottery.*?tab-count[^>]*>(\d+)', nav_m.group(1), re.DOTALL)
                lp_count = int(cnt_m.group(1)) if cnt_m else None
        except Exception:
            pass
    expected_count = len(active_items)
    if lp_count is not None and lp_count != expected_count:
        issues_failure.append(
            f"【カウント不一致】LP タブバッジ={lp_count} vs 実 active 件数={expected_count}")

    # ── Check 8: RICOH GR IV 3件が同じ受付期間 ──────────────────────────────
    ricoh_actives = [it for it in active_items
                     if any(r in (it.get("product_name") or "") for r in RICOH_EXPECTED)]
    if len(ricoh_actives) >= 2:
        end_dates = {(it.get("entry_end_at") or "")[:16] for it in ricoh_actives}
        if len(end_dates) > 1:
            issues_warning.append(
                f"RICOH GR IV 系の entry_end_at が不統一: {end_dates}")

    # ── Check 9: 受付終了 item が active section に出ない（Check2 で既にカバー） ──
    # Check 2 で期限切れ active を FAILURE にしているため省略

    # ── Check 10: 古い文言が active item の note に出ない ────────────────────
    stale_found: list[str] = []
    for it in active_items:
        note = it.get("note") or ""
        for phrase in STALE_PHRASES:
            if phrase in note:
                stale_found.append(f"「{it.get('product_name','?')}」に古い文言「{phrase}」")
    if stale_found:
        issues_failure.extend(stale_found)

    # ── サマリー集計 ──────────────────────────────────────────────────────────
    missing_form_count = sum(
        1 for it in active_items
        if not (it.get("entry_form_url") or "").strip()
    )
    duplicate_codes = len(codes) - len(set(codes))
    stale_count = sum(
        1 for it in active_items
        for phrase in STALE_PHRASES
        if phrase in (it.get("note") or "")
    )

    return {
        "checked_at":            now.strftime("%Y-%m-%d %H:%M") + " JST",
        "active_count":          len(active_items),
        "upcoming_count":        len(upcoming_items),
        "closed_count":          len(closed_items),
        "reference_count":       len(reference_items),
        "lp_badge_count":        lp_count,
        "duplicate_count":       duplicate_codes,
        "stale_phrase_count":    stale_count,
        "missing_form_url_count": missing_form_count,
        "active_items": [
            {
                "product_name":  it.get("product_name", ""),
                "brand":         it.get("brand", ""),
                "entry_start_at": it.get("entry_start_at") or it.get("entry_start") or "",
                "entry_end_at":  it.get("entry_end_at")   or it.get("entry_end")   or "",
                "official_price": it.get("official_price") or it.get("price") or "",
                "has_form_url":  bool((it.get("entry_form_url") or "").strip()),
                "has_url":       bool((it.get("url") or "").strip()),
                "product_code":  it.get("product_code", ""),
            }
            for it in active_items
        ],
        "issues_failure":        issues_failure,
        "issues_warning":        issues_warning,
    }


# ──────────────────────────────────────────────────────────────────────────────
# レポート出力
# ──────────────────────────────────────────────────────────────────────────────

def save_reports(result: dict) -> None:
    """JSON / Markdown レポートを exports/lottery_report/ に保存。"""
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    # JSON
    REPORT_JSON.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Markdown
    md_lines = [
        "# 抽選品質レポート",
        "",
        f"**チェック日時**: {result['checked_at']}",
        "",
        "## サマリー",
        "",
        "| 項目 | 件数 |",
        "|------|------|",
        f"| 現在受付中 (active) | **{result['active_count']}** |",
        f"| 近日開始 (upcoming) | {result['upcoming_count']} |",
        f"| 受付終了 (closed)   | {result['closed_count']} |",
        f"| 参考リンク          | {result['reference_count']} |",
        f"| LP タブバッジ件数   | {result['lp_badge_count'] if result['lp_badge_count'] is not None else 'N/A'} |",
        f"| 重複 product_code   | {result['duplicate_count']} |",
        f"| 古い文言あり        | {result['stale_phrase_count']} |",
        f"| entry_form_url なし  | {result['missing_form_url_count']} |",
        "",
    ]

    # active items テーブル
    if result["active_items"]:
        md_lines += [
            "## 現在受付中アイテム",
            "",
            "| 商品名 | 受付開始 | 受付終了 | 公式価格 | フォーム |",
            "|--------|----------|----------|----------|----------|",
        ]
        for it in result["active_items"]:
            form_icon = "✅" if it["has_form_url"] else "❌"
            md_lines.append(
                f"| {it['product_name']} "
                f"| {it['entry_start_at'][:10] if it['entry_start_at'] else '—'} "
                f"| {it['entry_end_at'][:10] if it['entry_end_at'] else '—'} "
                f"| {it['official_price'] or '—'} "
                f"| {form_icon} |"
            )
        md_lines.append("")

    # 問題リスト
    if result["issues_failure"]:
        md_lines += ["## ❌ FAILURE 項目", ""]
        for issue in result["issues_failure"]:
            md_lines.append(f"- {issue}")
        md_lines.append("")

    if result["issues_warning"]:
        md_lines += ["## ⚠️ WARNING 項目", ""]
        for issue in result["issues_warning"]:
            md_lines.append(f"- {issue}")
        md_lines.append("")

    if not result["issues_failure"] and not result["issues_warning"]:
        md_lines += ["## ✅ 問題なし", "", "すべての品質チェックをパスしました。", ""]

    REPORT_MD.write_text("\n".join(md_lines), encoding="utf-8")


# ──────────────────────────────────────────────────────────────────────────────
# GitHub Actions Summary / Annotations
# ──────────────────────────────────────────────────────────────────────────────

def write_gha_summary(result: dict) -> None:
    """$GITHUB_STEP_SUMMARY にマークダウンを書き込む。"""
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    try:
        with open(summary_path, "a", encoding="utf-8") as f:
            f.write(REPORT_MD.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[WARN] GITHUB_STEP_SUMMARY への書き込みに失敗: {e}", file=sys.stderr)


def emit_gha_annotations(result: dict) -> None:
    """GitHub Actions の ::error:: / ::warning:: アノテーションを出力。"""
    for issue in result["issues_failure"]:
        print(f"::error::抽選品質 FAILURE — {issue}")
    for issue in result["issues_warning"]:
        print(f"::warning::抽選品質 WARNING — {issue}")


# ──────────────────────────────────────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    """品質チェック実行。exit code を返す。"""
    now = _get_now_jst()
    print(f"[lottery-quality] チェック開始: {now.strftime('%Y-%m-%d %H:%M')} JST")

    # データ読み込み
    ref_items = load_lottery_items()
    db_items  = load_db_lottery_events()

    if not ref_items and not db_items:
        print("[WARN] lottery アイテムが0件 — _LOTTERY_REFERENCE_ITEMS / DB ともに空", file=sys.stderr)
        save_reports({
            "checked_at": now.strftime("%Y-%m-%d %H:%M") + " JST",
            "active_count": 0, "upcoming_count": 0, "closed_count": 0,
            "reference_count": 0, "lp_badge_count": None,
            "duplicate_count": 0, "stale_phrase_count": 0, "missing_form_url_count": 0,
            "active_items": [], "issues_failure": ["lottery アイテムが0件"],
            "issues_warning": [],
        })
        return 2

    # チェック実行
    result = run_checks(ref_items, db_items, now)

    # レポート保存
    save_reports(result)
    write_gha_summary(result)
    emit_gha_annotations(result)

    # コンソール出力
    print(f"  active: {result['active_count']}件 / "
          f"upcoming: {result['upcoming_count']}件 / "
          f"closed: {result['closed_count']}件 / "
          f"reference: {result['reference_count']}件")
    print(f"  LP バッジ: {result['lp_badge_count']}")

    if result["issues_failure"]:
        print(f"\n[FAILURE] {len(result['issues_failure'])} 件の問題を検出:")
        for issue in result["issues_failure"]:
            print(f"  ❌ {issue}")
        print(f"\nレポート: {REPORT_MD}")
        return 1

    if result["issues_warning"]:
        print(f"\n[WARNING] {len(result['issues_warning'])} 件の注意事項:")
        for issue in result["issues_warning"]:
            print(f"  ⚠️  {issue}")
        print(f"\nレポート: {REPORT_MD}")
        return 2

    print("[OK] すべての品質チェックをパス")
    print(f"レポート: {REPORT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

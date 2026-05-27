#!/usr/bin/env python3
"""Daily LP Update ワークフロー結果を Discord / Telegram に通知するスクリプト。

読み込むファイル:
  - exports/collector_report/latest.json
  - exports/lottery_report/latest.json
  - exports/deploy_check_latest.txt
  - exports/prelaunch_check_latest.txt

環境変数:
  DISCORD_WEBHOOK_URL   … Discord webhook URL
  TELEGRAM_BOT_TOKEN    … Telegram Bot Token
  TELEGRAM_CHAT_ID      … Telegram Chat ID
  GITHUB_RUN_ID         … Actions Run ID (GHA で自動設定)
  GITHUB_REPOSITORY     … owner/repo (GHA で自動設定)
  GITHUB_SERVER_URL     … https://github.com (GHA で自動設定)

使い方:
  python scripts/notify_workflow_result.py           # 通知実行
  python scripts/notify_workflow_result.py --dry-run # メッセージ表示のみ
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

# ──────────────────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent.parent
COLLECTOR_REPORT = PROJECT_ROOT / "exports" / "collector_report" / "latest.json"
LOTTERY_REPORT   = PROJECT_ROOT / "exports" / "lottery_report"   / "latest.json"
DEPLOY_CHECK_TXT = PROJECT_ROOT / "exports" / "deploy_check_latest.txt"
PRELAUNCH_TXT    = PROJECT_ROOT / "exports" / "prelaunch_check_latest.txt"
LP_SETTINGS      = PROJECT_ROOT / "config" / "lp_settings.yaml"

JST = timezone(timedelta(hours=9))

# 主要 iPhone 商品の表示名
IPHONE_ALIASES = {
    "iphone17pro256": "Pro 256",
    "iphone17pro512": "Pro 512",
    "iphone17pm256":  "ProMax 256",
    "iphone17pm512":  "ProMax 512",
}


# ──────────────────────────────────────────────────────────────────────────────
# データ読み込み
# ──────────────────────────────────────────────────────────────────────────────

def _now_jst() -> str:
    return datetime.now(tz=JST).strftime("%Y-%m-%d %H:%M")


def _read_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _read_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _lp_url() -> str:
    """lp_settings.yaml から site_url を読む。"""
    try:
        text = LP_SETTINGS.read_text(encoding="utf-8")
        m = re.search(r'site_url:\s*["\']?([^\s"\']+)', text)
        return m.group(1).rstrip("/") if m else ""
    except Exception:
        return ""


def _actions_url() -> str:
    """GitHub Actions の実行 URL を組み立てる。"""
    run_id   = os.environ.get("GITHUB_RUN_ID", "")
    repo     = os.environ.get("GITHUB_REPOSITORY", "")
    server   = os.environ.get("GITHUB_SERVER_URL", "https://github.com").rstrip("/")
    if run_id and repo:
        return f"{server}/{repo}/actions/runs/{run_id}"
    return ""


# ──────────────────────────────────────────────────────────────────────────────
# メッセージ組み立て
# ──────────────────────────────────────────────────────────────────────────────

def build_report() -> dict:
    """各レポートを読み込んでサマリー dict を返す。"""
    cr = _read_json(COLLECTOR_REPORT)
    lr = _read_json(LOTTERY_REPORT)
    dc_text = _read_text(DEPLOY_CHECK_TXT)
    pl_text = _read_text(PRELAUNCH_TXT)

    # ── collector ──────────────────────────────────────────────────────────
    summary = cr.get("summary", {})
    total         = summary.get("total", 0)
    ok_count      = summary.get("ok", 0)
    failed_count  = summary.get("failed", 0)
    skip_count    = summary.get("skip", 0)
    low_conf      = cr.get("low_confidence_count", 0)
    suspicious    = len(cr.get("suspicious_prices", []))
    fail_pct      = round(failed_count / total * 100) if total else 0

    # iPhone 主要商品の成功店舗数
    detail = cr.get("product_shop_detail", {})
    iphone_shops: dict[str, int] = {}
    for alias, label in IPHONE_ALIASES.items():
        d = detail.get(alias, {})
        iphone_shops[label] = len(d.get("success_shops", []))

    # ── lottery ────────────────────────────────────────────────────────────
    l_active   = lr.get("active_count", 0)
    l_failures = len(lr.get("issues_failure", []))
    l_warnings = len(lr.get("issues_warning", []))

    # ── deploy-check ────────────────────────────────────────────────────────
    dc_errors   = len(re.findall(r"❌", dc_text))
    dc_warnings = len(re.findall(r"⚠️",  dc_text))
    dc_oks      = len(re.findall(r"✅",  dc_text))
    dc_passed   = "PASSED" in dc_text
    dc_failed   = "FAILED" in dc_text

    # ── prelaunch-check ─────────────────────────────────────────────────────
    pl_errors   = len(re.findall(r"❌", pl_text))
    pl_warnings = len(re.findall(r"⚠️",  pl_text))
    pl_passed   = "公開準備完了" in pl_text or "PASS" in pl_text

    return {
        "generated_at":    _now_jst(),
        "lp_url":          _lp_url(),
        "actions_url":     _actions_url(),
        # collector
        "total":           total,
        "ok_count":        ok_count,
        "failed_count":    failed_count,
        "skip_count":      skip_count,
        "fail_pct":        fail_pct,
        "low_conf":        low_conf,
        "suspicious":      suspicious,
        "iphone_shops":    iphone_shops,
        # lottery
        "l_active":        l_active,
        "l_failures":      l_failures,
        "l_warnings":      l_warnings,
        # deploy-check
        "dc_errors":       dc_errors,
        "dc_warnings":     dc_warnings,
        "dc_oks":          dc_oks,
        "dc_passed":       dc_passed,
        # prelaunch
        "pl_errors":       pl_errors,
        "pl_warnings":     pl_warnings,
        "pl_passed":       pl_passed,
    }


def _status_icon(has_error: bool, has_warning: bool = False) -> str:
    if has_error:
        return "🔴"
    if has_warning:
        return "🟡"
    return "🟢"


def build_discord_payload(r: dict) -> dict:
    """Discord embed ペイロードを返す。"""
    overall_ok = (r["dc_passed"] and r["pl_passed"]
                  and r["suspicious"] == 0 and r["l_failures"] == 0)
    color = 0x22C55E if overall_ok else (0xEF4444 if not r["dc_passed"] else 0xF59E0B)

    # iPhone 店舗数フィールド
    iphone_lines = "\n".join(
        f"  {label}: {cnt}店舗" for label, cnt in r["iphone_shops"].items()
    )

    fields = [
        {
            "name": "💰 価格取得",
            "value": (
                f"成功: **{r['ok_count']}/{r['total']}**  "
                f"失敗率: {r['fail_pct']}%\n"
                f"low_confidence: {r['low_conf']}  "
                f"suspicious: {r['suspicious']}"
            ),
            "inline": False,
        },
        {
            "name": "📱 iPhone 主要商品 成功店舗数",
            "value": iphone_lines or "データなし",
            "inline": False,
        },
        {
            "name": "🎰 抽選情報",
            "value": (
                f"受付中: **{r['l_active']}件**  "
                f"FAILURE: {r['l_failures']}  "
                f"WARNING: {r['l_warnings']}"
            ),
            "inline": False,
        },
        {
            "name": f"{_status_icon(r['dc_errors']>0, r['dc_warnings']>0)} deploy-check",
            "value": (
                f"✅ {r['dc_oks']}  ⚠️ {r['dc_warnings']}  ❌ {r['dc_errors']}  "
                f"→ **{'PASSED' if r['dc_passed'] else 'FAILED'}**"
            ),
            "inline": True,
        },
        {
            "name": f"{_status_icon(r['pl_errors']>0, r['pl_warnings']>0)} prelaunch-check",
            "value": (
                f"⚠️ {r['pl_warnings']}  ❌ {r['pl_errors']}  "
                f"→ **{'OK' if r['pl_passed'] else 'NG'}**"
            ),
            "inline": True,
        },
    ]

    # リンク
    links: list[str] = []
    if r["actions_url"]:
        links.append(f"[Actions Run]({r['actions_url']})")
    if r["lp_url"]:
        links.append(f"[LP]({r['lp_url']})")
    if links:
        fields.append({"name": "🔗 リンク", "value": "  |  ".join(links), "inline": False})

    return {
        "embeds": [
            {
                "title": f"Daily LP Update 結果 — {r['generated_at']} JST",
                "color": color,
                "fields": fields,
                "footer": {"text": "premium-monitor / auto-notify"},
            }
        ]
    }


def build_telegram_text(r: dict) -> str:
    """Telegram 送信用テキスト（HTML モード）を返す。"""
    overall_icon = _status_icon(
        has_error=(r["dc_errors"] > 0 or r["suspicious"] > 0 or r["l_failures"] > 0),
        has_warning=(r["dc_warnings"] > 0 or r["pl_warnings"] > 0),
    )

    iphone_lines = "\n".join(
        f"  {label}: {cnt}店舗" for label, cnt in r["iphone_shops"].items()
    )

    dc_status = "✅ PASSED" if r["dc_passed"] else "❌ FAILED"
    pl_status = "✅ OK" if r["pl_passed"] else "❌ NG"

    lines = [
        f"{overall_icon} <b>Daily LP Update 結果</b>",
        f"🕐 {r['generated_at']} JST",
        "",
        "💰 <b>価格取得</b>",
        f"  成功: {r['ok_count']}/{r['total']} ({100 - r['fail_pct']}%)",
        f"  失敗率: {r['fail_pct']}%",
        f"  low_confidence: {r['low_conf']}",
        f"  suspicious_price: {r['suspicious']}",
        "",
        "📱 <b>iPhone 主要商品 成功店舗数</b>",
        iphone_lines or "  データなし",
        "",
        "🎰 <b>抽選情報</b>",
        f"  受付中: {r['l_active']}件",
        f"  FAILURE: {r['l_failures']} / WARNING: {r['l_warnings']}",
        "",
        f"🔍 <b>deploy-check</b>: {dc_status}",
        f"  ✅{r['dc_oks']} ⚠️{r['dc_warnings']} ❌{r['dc_errors']}",
        f"🚀 <b>prelaunch-check</b>: {pl_status}",
        f"  ⚠️{r['pl_warnings']} ❌{r['pl_errors']}",
    ]

    if r["actions_url"]:
        lines += ["", f'🔗 <a href="{r["actions_url"]}">Actions Run</a>']
    if r["lp_url"]:
        lines += [f'🌐 <a href="{r["lp_url"]}">LP を開く</a>']

    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────────────────────
# 送信
# ──────────────────────────────────────────────────────────────────────────────

def send_discord(payload: dict) -> bool:
    """Discord webhook にメッセージを送信する。成功時 True。"""
    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL", "")
    if not webhook_url:
        print("[Discord] DISCORD_WEBHOOK_URL が未設定 — スキップ", file=sys.stderr)
        return False
    try:
        import urllib.request
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            webhook_url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = resp.status
            if status in (200, 204):
                print(f"[Discord] 送信成功 (HTTP {status})")
                return True
            print(f"[Discord] 送信失敗 (HTTP {status})", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[Discord] 送信エラー: {e}", file=sys.stderr)
        return False


def send_telegram(text: str) -> bool:
    """Telegram Bot API にメッセージを送信する。成功時 True。"""
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        missing = []
        if not token:   missing.append("TELEGRAM_BOT_TOKEN")
        if not chat_id: missing.append("TELEGRAM_CHAT_ID")
        print(f"[Telegram] {', '.join(missing)} が未設定 — スキップ", file=sys.stderr)
        return False
    try:
        import urllib.request
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {
            "chat_id":    chat_id,
            "text":       text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            if body.get("ok"):
                print("[Telegram] 送信成功")
                return True
            print(f"[Telegram] 送信失敗: {body.get('description')}", file=sys.stderr)
            return False
    except Exception as e:
        print(f"[Telegram] 送信エラー: {e}", file=sys.stderr)
        return False


# ──────────────────────────────────────────────────────────────────────────────
# メイン
# ──────────────────────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="Daily LP Update 結果を通知する")
    parser.add_argument("--dry-run", action="store_true", help="送信せずにメッセージ内容を表示する")
    args = parser.parse_args()

    report = build_report()

    discord_payload = build_discord_payload(report)
    telegram_text   = build_telegram_text(report)

    if args.dry_run:
        print("=" * 60)
        print("[DRY-RUN] Discord payload:")
        print(json.dumps(discord_payload, ensure_ascii=False, indent=2))
        print()
        print("[DRY-RUN] Telegram text:")
        print(telegram_text)
        print("=" * 60)
        return 0

    # 通知送信
    discord_ok  = send_discord(discord_payload)
    telegram_ok = send_telegram(telegram_text)

    if not discord_ok and not telegram_ok:
        has_discord_env  = bool(os.environ.get("DISCORD_WEBHOOK_URL"))
        has_telegram_env = bool(os.environ.get("TELEGRAM_BOT_TOKEN"))
        if not has_discord_env and not has_telegram_env:
            print("[notify] 通知先が設定されていないため送信をスキップ")
            return 0
        print("[notify] すべての通知先への送信に失敗", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())

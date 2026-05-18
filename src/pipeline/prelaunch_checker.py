"""本番前チェックリスト (Phase 13)。

LP公開前に15項目を自動検証し、不足項目を warning/error で報告する。
CLI / Streamlit の両方から呼べる共通ロジック。
"""

import re
import logging
from datetime import datetime
from pathlib import Path

import yaml

from src.content.safety import FORBIDDEN_PHRASES

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent


def _load_lp_settings() -> dict:
    path = PROJECT_ROOT / "config" / "lp_settings.yaml"
    try:
        with open(path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def run_prelaunch_check(repo=None) -> list[dict]:
    """本番前チェックを実行する。

    Args:
        repo: Repository（beginner_easy件数チェック用、Noneならスキップ）
    Returns:
        チェック結果リスト [{level, check, message}, ...]
    """
    results = []
    settings = _load_lp_settings()
    public_dir = PROJECT_ROOT / "docs"
    exports_dir = PROJECT_ROOT / "exports" / "lp" / "daily"
    index_path = public_dir / "index.html"

    # ===== 1. docs/index.html 存在 =====
    if index_path.exists():
        results.append({"level": "ok", "check": "public_index", "message": "docs/index.html 存在"})
        html = index_path.read_text(encoding="utf-8")
    else:
        results.append({"level": "error", "check": "public_index",
                        "message": "docs/index.html なし → build-public-lp を実行"})
        html = ""

    # ===== 2. deploy-check PASS（簡易版） =====
    if html:
        forbidden = [p for p in FORBIDDEN_PHRASES if p in html]
        if forbidden:
            results.append({"level": "error", "check": "forbidden", "message": f"禁止表現検出: {forbidden}"})
        else:
            results.append({"level": "ok", "check": "forbidden", "message": "禁止表現なし"})
    else:
        results.append({"level": "error", "check": "forbidden", "message": "HTML未生成のためチェック不可"})

    # ===== 3. GA ID 設定状態 =====
    ga_id = (settings.get("analytics", {}).get("google_analytics_id") or "").strip()
    if ga_id:
        results.append({"level": "ok", "check": "ga_id", "message": f"GA ID設定済み: {ga_id}"})
    else:
        results.append({"level": "warning", "check": "ga_id",
                        "message": "GA ID未設定 → 設定するとPV・CTR計測が可能"})

    # ===== 4. note_url 設定状態 =====
    note_url = (settings.get("note_url") or "").strip()
    if note_url and note_url != "#":
        results.append({"level": "ok", "check": "note_url", "message": f"note_url設定済み: {note_url}"})
    else:
        results.append({"level": "warning", "check": "note_url",
                        "message": "note_url未設定 → LP上は「準備中」表示。note記事公開後に設定"})

    # ===== 5. site_url 設定状態 =====
    site_url = (settings.get("site_url") or "").strip()
    if site_url:
        results.append({"level": "ok", "check": "site_url", "message": f"site_url設定済み: {site_url}"})
    else:
        results.append({"level": "warning", "check": "site_url",
                        "message": "site_url未設定 → GitHub Pages公開後に設定するとsitemap.xmlに反映"})

    # ===== 6. enable_note_cta = true =====
    if settings.get("enable_note_cta"):
        results.append({"level": "ok", "check": "note_cta", "message": "enable_note_cta: true"})
    else:
        results.append({"level": "warning", "check": "note_cta", "message": "enable_note_cta: false → note導線が非表示"})

    # ===== 7. enable_line_cta = false =====
    if not settings.get("enable_line_cta"):
        results.append({"level": "ok", "check": "line_cta", "message": "enable_line_cta: false（初期運用OFF）"})
    else:
        results.append({"level": "warning", "check": "line_cta", "message": "enable_line_cta: true → LINE準備が完了しているか確認"})

    # ===== 8. enable_telegram_cta = false =====
    if not settings.get("enable_telegram_cta"):
        results.append({"level": "ok", "check": "telegram_cta", "message": "enable_telegram_cta: false（初期運用OFF）"})
    else:
        results.append({"level": "warning", "check": "telegram_cta", "message": "enable_telegram_cta: true → Telegram準備が完了しているか確認"})

    # ===== 9. 空リンクなし =====
    if html:
        empty_tracked = re.findall(r'href=["\'](\s*#?\s*)["\'].*?data-track', html, re.DOTALL)
        if empty_tracked:
            results.append({"level": "error", "check": "empty_links", "message": f"data-track付き空リンク {len(empty_tracked)}件"})
        else:
            results.append({"level": "ok", "check": "empty_links", "message": "空リンクなし"})

    # ===== 10. 今日の日付 =====
    today = datetime.now().strftime("%Y-%m-%d")
    if html and today in html:
        results.append({"level": "ok", "check": "today_date", "message": f"今日の日付 {today} あり"})
    elif html:
        results.append({"level": "warning", "check": "today_date",
                        "message": f"今日の日付 {today} なし → generate-daily-lp + build-public-lp を実行"})

    # ===== 11. 価格表記 =====
    if html and "¥" in html:
        results.append({"level": "ok", "check": "price", "message": "価格表記あり"})
    elif html:
        results.append({"level": "error", "check": "price", "message": "価格表記なし"})

    # ===== 12. beginner_easy案件が1件以上 =====
    if repo:
        try:
            deals = repo.list_beginner_deals(user_level="beginner_easy", min_profit=0, limit=1)
            if deals:
                results.append({"level": "ok", "check": "beginner_easy", "message": f"beginner_easy案件あり"})
            else:
                results.append({"level": "warning", "check": "beginner_easy",
                                "message": "beginner_easy案件なし → scan-beginner-deals を実行"})
        except Exception:
            results.append({"level": "warning", "check": "beginner_easy", "message": "DB未接続（スキップ）"})

    # ===== 13. A/B/C LP生成済み =====
    variants_ok = []
    for v in ["A", "B", "C"]:
        vpath = exports_dir / f"index_{v}.html"
        if vpath.exists():
            variants_ok.append(v)
    if len(variants_ok) == 3:
        results.append({"level": "ok", "check": "ab_variants", "message": f"A/B/C全バリアント生成済み"})
    elif variants_ok:
        results.append({"level": "warning", "check": "ab_variants",
                        "message": f"生成済み: {variants_ok}。未生成: {[v for v in 'ABC' if v not in variants_ok]}"})
    else:
        results.append({"level": "warning", "check": "ab_variants",
                        "message": "A/B/C未生成 → generate-daily-lp --variant A/B/C を実行"})

    # ===== 14. sitemap.xml =====
    if (public_dir / "sitemap.xml").exists():
        results.append({"level": "ok", "check": "sitemap", "message": "sitemap.xml あり"})
    else:
        results.append({"level": "warning", "check": "sitemap", "message": "sitemap.xml なし → build-public-lp を実行"})

    # ===== 15. robots.txt =====
    if (public_dir / "robots.txt").exists():
        results.append({"level": "ok", "check": "robots", "message": "robots.txt あり"})
    else:
        results.append({"level": "warning", "check": "robots", "message": "robots.txt なし → build-public-lp を実行"})

    # ===== 16. 免責事項 =====
    if html and "購入を推奨するものではありません" in html:
        results.append({"level": "ok", "check": "disclaimer", "message": "免責事項あり"})
    elif html:
        results.append({"level": "error", "check": "disclaimer", "message": "免責事項なし"})

    return results


def summarize(results: list[dict]) -> dict:
    """結果をサマリにまとめる。"""
    errors = [r for r in results if r["level"] == "error"]
    warnings = [r for r in results if r["level"] == "warning"]
    oks = [r for r in results if r["level"] == "ok"]

    ready = len(errors) == 0
    next_steps = []
    if errors:
        for r in errors:
            next_steps.append(f"[修正必須] {r['message']}")
    for r in warnings:
        next_steps.append(f"[推奨] {r['message']}")

    return {
        "ready": ready,
        "total": len(results),
        "errors": len(errors),
        "warnings": len(warnings),
        "ok": len(oks),
        "results": results,
        "next_steps": next_steps,
    }

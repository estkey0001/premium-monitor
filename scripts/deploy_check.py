#!/usr/bin/env python3
"""LP公開前のデプロイチェック。

確認項目:
1. docs/index.html が存在する
2. 禁止表現が含まれていない
3. noteリンクが設定されている（enable_note_cta=true時）
4. LINE/Telegram CTAがOFFなら表示されていない
5. HTML内に今日の日付がある
6. 価格表記がある
7. 免責事項がある
8. data-track属性がある
"""

import sys
from datetime import datetime
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PUBLIC_DIR = PROJECT_ROOT / "docs"

# 禁止表現リスト
FORBIDDEN = [
    "確実に儲かる", "絶対利益", "誰でも稼げる", "今すぐ買え",
    "買えば勝ち", "ノーリスク", "必ず儲かる", "確実に利益",
    "リスクゼロ", "爆益確定",
]


def check() -> list[dict]:
    """デプロイチェックを実行する。結果リストを返す。"""
    results = []

    settings_path = PROJECT_ROOT / "config" / "lp_settings.yaml"
    with open(settings_path, "r", encoding="utf-8") as f:
        settings = yaml.safe_load(f) or {}

    index_path = PUBLIC_DIR / "index.html"

    # 1. index.html存在
    if index_path.exists():
        results.append({"level": "ok", "check": "index_exists", "message": "docs/index.html 存在"})
        html = index_path.read_text(encoding="utf-8")
    else:
        results.append({"level": "error", "check": "index_exists", "message": "docs/index.html が存在しない"})
        return results

    # 2. 禁止表現
    found_forbidden = [p for p in FORBIDDEN if p in html]
    if found_forbidden:
        results.append({"level": "error", "check": "forbidden_phrases", "message": f"禁止表現検出: {found_forbidden}"})
    else:
        results.append({"level": "ok", "check": "forbidden_phrases", "message": "禁止表現なし"})

    # 3. noteリンク
    if settings.get("enable_note_cta"):
        note_url = (settings.get("note_url") or "").strip()
        if note_url and note_url != "#":
            if note_url in html:
                results.append({"level": "ok", "check": "note_url", "message": f"noteリンク設定済み: {note_url}"})
            else:
                results.append({"level": "warning", "check": "note_url", "message": f"note_url設定済みだがHTML内に未反映（要再ビルド）"})
        else:
            # URL未設定 → 「準備中」表示が出ていればOK
            if "準備中" in html or "公開予定" in html:
                results.append({"level": "ok", "check": "note_url", "message": "note_url未設定 → 「準備中」表示（正常）"})
            else:
                results.append({"level": "warning", "check": "note_url", "message": "note_url未設定。設定後に再ビルドしてください"})

    # 3b. 空リンク（href="#"）が存在しないか
    import re
    empty_links = re.findall(r'href=["\'](#|)["\']', html)
    # フッターの # アンカー等は除外（data-track付きの空リンクが問題）
    empty_tracked = re.findall(r'href=["\'](#|)["\']\s*data-track', html)
    if empty_tracked:
        results.append({"level": "error", "check": "empty_links", "message": f"data-track付き空リンク検出 ({len(empty_tracked)}件)"})
    else:
        results.append({"level": "ok", "check": "empty_links", "message": "空リンクなし"})

    # 4. LINE/Telegram CTAがOFFなら非表示
    if not settings.get("enable_line_cta"):
        if "LINE登録" in html:
            results.append({"level": "error", "check": "line_cta_off", "message": "LINE CTA=OFFだがボタン表示あり"})
        else:
            results.append({"level": "ok", "check": "line_cta_off", "message": "LINE CTA非表示（正常）"})

    if not settings.get("enable_telegram_cta"):
        # フッターの「予定」言及は許容、ボタン表示はNG
        has_tg_button = 'data-track="telegram_click"' in html
        if has_tg_button:
            results.append({"level": "error", "check": "telegram_cta_off", "message": "Telegram CTA=OFFだがボタン表示あり"})
        else:
            results.append({"level": "ok", "check": "telegram_cta_off", "message": "Telegram CTA非表示（正常）"})

    # 4b. Analytics: 未設定ならGAスニペットが出ていないことを確認
    # 注: クリック計測JSの `typeof gtag==="function"` は安全ガード（GAなしでも動作しない）なので除外
    ga_id = (settings.get("analytics", {}).get("google_analytics_id") or "").strip()
    if not ga_id:
        has_ga_snippet = "googletagmanager.com/gtag" in html or "gtag(\"config\"" in html
        if has_ga_snippet:
            results.append({"level": "error", "check": "analytics_empty", "message": "GA ID未設定なのにGAスニペットが出力されている"})
        else:
            results.append({"level": "ok", "check": "analytics_empty", "message": "GA ID未設定 → GAスニペット非出力（正常）"})
    else:
        if ga_id in html:
            results.append({"level": "ok", "check": "analytics_set", "message": f"GA ID設定済み: {ga_id}"})
        else:
            results.append({"level": "warning", "check": "analytics_set", "message": "GA ID設定済みだがHTML内に未反映"})

    # 5. 今日の日付
    today = datetime.now().strftime("%Y-%m-%d")
    if today in html:
        results.append({"level": "ok", "check": "today_date", "message": f"今日の日付 {today} あり"})
    else:
        results.append({"level": "warning", "check": "today_date", "message": f"今日の日付 {today} が見つからない（前日の生成？）"})

    # 6. 価格表記
    if "¥" in html:
        results.append({"level": "ok", "check": "price_exists", "message": "価格表記あり"})
    else:
        results.append({"level": "error", "check": "price_exists", "message": "価格表記なし"})

    # 7. 免責事項
    if "購入を推奨するものではありません" in html:
        results.append({"level": "ok", "check": "disclaimer", "message": "免責事項あり"})
    else:
        results.append({"level": "error", "check": "disclaimer", "message": "免責事項が見つからない"})

    # 8. data-track属性
    if "data-track" in html:
        results.append({"level": "ok", "check": "data_track", "message": "data-track属性あり"})
    else:
        results.append({"level": "warning", "check": "data_track", "message": "data-track属性なし（リンクがない可能性）"})

    # 9. sitemap.xml
    sitemap = PUBLIC_DIR / "sitemap.xml"
    if sitemap.exists():
        results.append({"level": "ok", "check": "sitemap", "message": "sitemap.xml あり"})
    else:
        results.append({"level": "warning", "check": "sitemap", "message": "sitemap.xml なし"})

    # 10. robots.txt
    robots = PUBLIC_DIR / "robots.txt"
    if robots.exists():
        results.append({"level": "ok", "check": "robots", "message": "robots.txt あり"})
    else:
        results.append({"level": "warning", "check": "robots", "message": "robots.txt なし"})

    # 11. 買取価格更新日時の表示
    if "買取価格更新：" in html:
        results.append({"level": "ok", "check": "buyback_updated_ts", "message": "買取価格更新日時が表示されている"})
    else:
        results.append({"level": "error", "check": "buyback_updated_ts", "message": "買取価格更新日時が見つからない（data-buyback-updated が未出力）"})

    # 12. LP生成日時の表示
    if "LP生成：" in html:
        results.append({"level": "ok", "check": "lp_generated_ts", "message": "LP生成日時が表示されている"})
    else:
        results.append({"level": "error", "check": "lp_generated_ts", "message": "LP生成日時が見つからない"})

    # 13. 初級者向けタブの存在
    if 'id="tab-beginner"' in html:
        results.append({"level": "ok", "check": "tab_beginner", "message": "初級者向けタブが存在する"})
    else:
        results.append({"level": "error", "check": "tab_beginner", "message": "初級者向けタブ（id=tab-beginner）が見つからない"})

    # 14. 上級者向けタブの存在
    if 'id="tab-advanced"' in html:
        results.append({"level": "ok", "check": "tab_advanced", "message": "上級者向けタブが存在する"})
    else:
        results.append({"level": "error", "check": "tab_advanced", "message": "上級者向けタブ（id=tab-advanced）が見つからない"})

    # 15. 古いデータ警告ロジックの存在
    if "stale-warning-block" in html:
        results.append({"level": "ok", "check": "stale_warning", "message": "古いデータ警告ロジックが存在する"})
    else:
        results.append({"level": "error", "check": "stale_warning", "message": "古いデータ警告ロジック（stale-warning-block）が見つからない"})

    # 16. beginner_easy が初級者タブ内に存在するか
    if 'data-user-level="beginner_easy"' in html:
        results.append({"level": "ok", "check": "beginner_easy_in_tab", "message": "beginner_easy の案件が初級者タブ内にある"})
    else:
        results.append({"level": "warning", "check": "beginner_easy_in_tab", "message": "beginner_easy 案件なし（データ未生成の可能性）"})

    # 17. 上級者タブにコンテンツが存在するか（確定候補 or 監視候補のいずれか）
    has_advanced_confirmed = (
        'data-user-level="advanced_high_profit"' in html
        or 'data-user-level="expert_only"' in html
    )
    has_watch_candidates = 'watch-candidate-card' in html
    if has_advanced_confirmed:
        results.append({"level": "ok", "check": "advanced_in_tab", "message": "上級者向け確定案件が存在する"})
    elif has_watch_candidates:
        results.append({"level": "ok", "check": "advanced_in_tab", "message": "上級者向けタブに監視候補が表示されている（フォールバック正常）"})
    else:
        results.append({"level": "warning", "check": "advanced_in_tab", "message": "上級者向けタブにコンテンツなし（watch_candidates も空）"})

    # 18. 買取リンクが1つ以上存在するか
    has_buyback_link = bool(re.search(
        r'href=["\']https?://(?:www\.)?(?:janpara|iosys|sofmap|geo-online|kitamura|mapcamera|fujiyacamera|mobileno1|kaitori)[^"\']*["\']',
        html
    ))
    if has_buyback_link:
        results.append({"level": "ok", "check": "buyback_links_exist", "message": "買取リンクが存在する"})
    else:
        results.append({"level": "warning", "check": "buyback_links_exist", "message": "買取リンクが見つからない（リンク表示を確認してください）"})

    # 19. 複数店舗比較が表示されているか
    has_multi_shop = "買取店比較" in html or "shop-compare" in html or "buyback-compare" in html
    if has_multi_shop:
        results.append({"level": "ok", "check": "multi_shop_compare", "message": "複数店舗比較が表示されている"})
    else:
        results.append({"level": "warning", "check": "multi_shop_compare", "message": "複数店舗比較が見つからない"})

    # 20. 買取価格更新日時が表示されているか（既存チェックで対応済みのため確認のみ）
    # → buyback_updated_ts (check 11) で既に確認済み

    return results


def main():
    """CLIとして実行。"""
    results = check()
    errors = [r for r in results if r["level"] == "error"]
    warnings = [r for r in results if r["level"] == "warning"]
    oks = [r for r in results if r["level"] == "ok"]

    print(f"\n{'='*60}")
    print(f" Deploy Check ({len(results)} items)")
    print(f"{'='*60}")

    for r in results:
        icon = {"ok": "✅", "warning": "⚠️", "error": "❌"}[r["level"]]
        print(f"  {icon} [{r['check']}] {r['message']}")

    print(f"\n  Errors: {len(errors)} | Warnings: {len(warnings)} | OK: {len(oks)}")

    if errors:
        print(f"\n  ❌ Deploy check FAILED — fix errors before deploying")
        sys.exit(1)
    else:
        print(f"\n  ✅ Deploy check PASSED")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()

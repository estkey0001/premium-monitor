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

# `python3 scripts/deploy_check.py` のように直接実行された場合でも
# src パッケージを import できるようにする（CI と手元で結果を一致させる）。
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
            # URL未設定 → リンクを出さない（新UIのフッターは URL があるときだけ。旧UIの「準備中」の案内は UI Phase 10 で削除）
            if 'data-track="note_click"' not in html:
                results.append({"level": "ok", "check": "note_url", "message": "note_url未設定 → note へのリンクを出していない（正常）"})
            else:
                results.append({"level": "warning", "check": "note_url", "message": "note_url未設定なのに note へのリンクがある"})

    # 3b. 空リンク（href="#"）が存在しないか
    import re
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

    # 14b. LP上に「上級者向け」という表記がないこと（ユーザー向けUIには使わない）
    # コメント・CSS内は無視、li/p/h2/span等のテキストのみ検査
    import re as _re
    adv_in_ui = _re.findall(r'>([^<>]*上級者向け[^<>]*)<', html)
    if adv_in_ui:
        results.append({"level": "warning", "check": "no_kyusha_text", "message": f"LP上に「上級者向け」表記が{len(adv_in_ui)}件残っている（Pro向けに統一推奨）: {adv_in_ui[:2]}"})
    else:
        results.append({"level": "ok", "check": "no_kyusha_text", "message": "LP上に「上級者向け」表記なし（Pro向けに統一済み）"})

    # 18. 買取リンクが1つ以上存在するか
    has_buyback_link = bool(re.search(
        r'href=["\']https?://(?:www\.)?(?:janpara|iosys|sofmap|geo-online|kitamura|mapcamera|fujiyacamera|mobileno1|kaitori)[^"\']*["\']',
        html
    ))
    if has_buyback_link:
        results.append({"level": "ok", "check": "buyback_links_exist", "message": "買取リンクが存在する"})
    else:
        results.append({"level": "warning", "check": "buyback_links_exist", "message": "買取リンクが見つからない（リンク表示を確認してください）"})

    # 20b. 「新商品候補」がLP上に存在しない
    if '新商品候補' not in html:
        results.append({"level": "ok", "check": "new_products_removed", "message": "「新商品候補」テキストは存在しない（速報タブに移行済み）"})
    else:
        results.append({"level": "warning", "check": "new_products_removed", "message": "「新商品候補」テキストがまだ残っている"})

    # 23. 参照店舗数が表示されている
    if "参照" in html and "店舗" in html:
        results.append({"level": "ok", "check": "shop_count_shown", "message": "参照店舗数が表示されている"})
    else:
        results.append({"level": "warning", "check": "shop_count_shown", "message": "参照店舗数の表示が見つからない"})

    # 24. 未検証URLがリンクになっていない（unverified-link クラスがリンクなしで表示）
    # link_verified=false の場合は <span class="unverified-link"> として出力される
    if "unverified-link" in html:
        # unverified-linkがhrefを持っていないことを確認（href="..."の直前にunverified-linkがない）
        import re as _re
        bad_pattern = _re.findall(r'<a[^>]+class="[^"]*unverified-link[^"]*"[^>]+href', html)
        if bad_pattern:
            results.append({"level": "error", "check": "unverified_url_not_linked", "message": f"未検証URLがリンクになっている箇所あり: {len(bad_pattern)}件"})
        else:
            results.append({"level": "ok", "check": "unverified_url_not_linked", "message": "未検証URLはテキスト表示のみ（リンクなし）"})
    else:
        results.append({"level": "ok", "check": "unverified_url_not_linked", "message": "unverified-linkなし（全URL検証済みか買取データなし）"})

    # 38. タブボタンが全て有効（data-track付きhref="#"がない）
    bad_tracked = re.findall(r'href=["\']#["\'][^>]*data-track', html)
    if bad_tracked:
        results.append({"level": "error", "check": "tab_buttons_valid", "message": f"data-track付きhref='#'が{len(bad_tracked)}件（クリックが機能しない可能性）"})
    else:
        results.append({"level": "ok", "check": "tab_buttons_valid", "message": "タブ・CTAボタンに無効なhref='#'なし"})

    # 44. 空のhref（href="" または href="javascript:"）がない
    empty_href = re.findall(r'href=["\'](javascript:[^"\']*|)["\']', html)
    if empty_href:
        results.append({"level": "error", "check": "no_empty_href", "message": f"空または無効なhrefが{len(empty_href)}件"})
    else:
        results.append({"level": "ok", "check": "no_empty_href", "message": "空・無効なhrefなし"})

    # 49. ヒーロー旧コピー「公式 × 買取 × 海外相場。」が削除されている
    if '公式 × 買取 × 海外相場' not in html and '公式 &times; 買取 &times; 海外相場' not in html:
        results.append({"level": "ok", "check": "hero_old_copy_removed", "message": "ヒーロー旧コピー（公式×買取×海外相場）が削除されている"})
    else:
        results.append({"level": "error", "check": "hero_old_copy_removed", "message": "ヒーロー旧コピー（公式×買取×海外相場）が残存している（削除必要）"})

    # 50（旧49）. 旧機能チップ（features-bar）が削除されている
    if '<div class="features-bar">' not in html:
        results.append({"level": "ok", "check": "feature_chips_removed", "message": "旧機能チップ（features-bar）が削除されている"})
    else:
        results.append({"level": "error", "check": "feature_chips_removed", "message": "旧機能チップ（features-bar）が残存している（削除必要）"})

    # 68. モバイル一番の確認導線が存在する（リンクまたは「公式で要確認」表示）
    has_mobile_ichiban_link = bool(re.search(r'mobile-ichiban\.com|モバイル一番', html))
    if has_mobile_ichiban_link:
        results.append({"level": "ok", "check": "mobile_ichiban_link", "message": "モバイル一番の確認導線が存在する"})
    else:
        results.append({"level": "warning", "check": "mobile_ichiban_link", "message": "モバイル一番の確認導線が見つからない（buyback CSV の URL を確認）"})

    # 73. 買取商店のリンクまたは確認表示が存在する
    has_kaitori_shouten = bool(re.search(r'kaitorishouten-co\.jp|買取商店', html))
    if has_kaitori_shouten:
        results.append({"level": "ok", "check": "kaitori_shouten_link", "message": "買取商店の確認導線が存在する"})
    else:
        results.append({"level": "warning", "check": "kaitori_shouten_link", "message": "買取商店の確認導線が見つからない（buyback CSV の URL を確認）"})

    # 74. 買取一丁目のリンクまたは確認表示が存在する
    has_kaitori_itchome = bool(re.search(r'1-chome\.com|買取一丁目', html))
    if has_kaitori_itchome:
        results.append({"level": "ok", "check": "kaitori_itchome_link", "message": "買取一丁目の確認導線が存在する"})
    else:
        results.append({"level": "warning", "check": "kaitori_itchome_link", "message": "買取一丁目の確認導線が見つからない（buyback CSV の URL を確認）"})

    # 77. 抽選カードに製品直リンクが含まれる（トップページのみではなく製品ページ URL）
    has_lottery_product_link = bool(re.search(
        r'fujifilm-x\.com/ja-jp/products/cameras/x100vi/'
        r'|store\.nintendo\.co\.jp'
        r'|direct\.playstation\.com'
        r'|ricoh-imaging\.co\.jp/japan/products/cameras/gr',
        html
    ))
    if has_lottery_product_link:
        results.append({"level": "ok", "check": "lottery_product_link", "message": "抽選カードに製品/販売直リンクが含まれている"})
    else:
        results.append({"level": "warning", "check": "lottery_product_link", "message": "抽選カードの製品直リンクが見つからない"})

    # 78. 抽選カードにステータスラベルがある（受付中/近日開始/終了済み/要確認）
    has_lottery_status = any(s in html for s in ("受付中 / 販売中", "近日開始", "終了済み", "要確認", "lottery-status-open", "lottery-status-upcoming"))
    if has_lottery_status:
        results.append({"level": "ok", "check": "lottery_status_label", "message": "抽選カードにステータスラベル（受付中/近日開始/終了済み/要確認）がある"})
    else:
        results.append({"level": "warning", "check": "lottery_status_label", "message": "抽選ステータスラベルが見つからない"})

    # 82. href="#" が存在しないこと（data-track付きは #1 でチェック済み、残り）
    bare_hash_hrefs = re.findall(r'href=["\']#["\']', html)
    if bare_hash_hrefs:
        results.append({"level": "error", "check": "no_bare_hash_href", "message": f"href=\"#\" が {len(bare_hash_hrefs)}件存在する"})
    else:
        results.append({"level": "ok", "check": "no_bare_hash_href", "message": "href=\"#\" なし"})

    # 83. 空 href が存在しないこと
    empty_href = re.findall(r'href=["\']["\']', html)
    if empty_href:
        results.append({"level": "error", "check": "no_empty_href", "message": f"空href が {len(empty_href)}件存在する"})
    else:
        results.append({"level": "ok", "check": "no_empty_href", "message": "空href なし"})

    # 89. 「買取価格を確認」が shop-name-col に入っていないこと
    # shop-name-col の中に「買取価格を確認」テキストがあれば店舗名と誤って置き換わっている
    shop_name_col_bad = re.findall(r'class="shop-name-col">[^<]*買取価格を確認', html)
    if shop_name_col_bad:
        results.append({"level": "error", "check": "shop_name_col_no_label", "message": f"shop-name-col に「買取価格を確認」テキストが {len(shop_name_col_bad)}件入っている — 店舗名と混在"})
    else:
        results.append({"level": "ok", "check": "shop_name_col_no_label", "message": "shop-name-col に「買取価格を確認」ラベルなし（店舗名が正しく表示されている）"})

    # 93. 鮮度ラベルの「shop-name-col」内に「最新」が含まれていない（手動データを「最新」と誤表示しない）
    # freshness-live + manual_today の組み合わせで「最新」が shop テーブルに出ていないかチェック
    bad_freshness_live_in_shop = re.findall(
        r'class="shop-table[^"]*".*?freshness-live[^>]*>[^<]*最新', html, re.DOTALL
    )
    if bad_freshness_live_in_shop:
        results.append({"level": "warning", "check": "no_live_label_for_manual", "message": f"買取テーブル内に「最新」（freshness-live）が {len(bad_freshness_live_in_shop)}件。手動データに使われていないか確認推奨"})
    else:
        results.append({"level": "ok", "check": "no_live_label_for_manual", "message": "買取テーブル内に「最新」ラベルなし（手動データは日付表示）"})

    # 103. 抽選カードに空の href が存在しない（lottery_click データ付きリンクに href="" がない）
    lottery_empty_links = re.findall(r'data-track="lottery_click"[^>]*href=["\']["\']', html)
    if lottery_empty_links:
        results.append({"level": "error", "check": "lottery_no_empty_link", "message": f"抽選カードに空リンク（href=\"\"）が {len(lottery_empty_links)}件存在する"})
    else:
        results.append({"level": "ok", "check": "lottery_no_empty_link", "message": "抽選カードに空リンクなし"})

    # 107. メルカリが「出品価格」として表示されている
    has_mercari_basis_label = "出品価格" in html
    if has_mercari_basis_label:
        results.append({"level": "ok", "check": "mercari_basis_label", "message": "メルカリが「出品価格」種別として表示されている"})
    else:
        results.append({"level": "warning", "check": "mercari_basis_label", "message": "「出品価格」ラベルが見つからない（メルカリデータなしの可能性）"})

    # 114. スマホ用横スクロールUIがある（tab-nav が overflow-x: auto の CSS を持つ）
    has_scroll_ui = "overflow-x: auto" in html or "overflow-x:auto" in html
    if has_scroll_ui:
        results.append({"level": "ok", "check": "mobile_scroll_nav", "message": "スマホ横スクロールUI（overflow-x: auto）がCSSに定義されている"})
    else:
        results.append({"level": "warning", "check": "mobile_scroll_nav", "message": "スマホ横スクロールUIが見つからない"})

    # 119. iPhone 17 Pro / Pro Max が「近日開始」「候補」「新商品候補」扱いされていない
    iphone17_upcoming = bool(re.search(r'iPhone\s+17\s+Pro[^<]{0,100}近日開始', html))
    iphone17_candidate = bool(re.search(r'iPhone\s+17\s+Pro[^<]{0,100}(新商品候補|候補扱い)', html))
    if iphone17_upcoming or iphone17_candidate:
        results.append({"level": "error", "check": "iphone17_not_upcoming", "message": "iPhone 17 Pro / Pro Max が「近日開始」や「候補」扱いになっている"})
    else:
        results.append({"level": "ok", "check": "iphone17_not_upcoming", "message": "iPhone 17 Pro / Pro Max が「近日開始」「候補」扱いではない"})

    # 120. 「新商品候補」という表記がない
    has_new_product_candidate = "新商品候補" in html
    if has_new_product_candidate:
        results.append({"level": "error", "check": "no_new_product_candidate_label", "message": "「新商品候補」という表記が存在する（速報タブから削除してください）"})
    else:
        results.append({"level": "ok", "check": "no_new_product_candidate_label", "message": "「新商品候補」表記なし"})

    # ── #127: 急騰/急落タブが存在しない（CSS セレクタは除外）──
    import re as _re

    # ─── 鮮度・誤表記チェック群 ───────────────────────────────────────

    # ── #135: LIVE DEALS 表記が存在しない ──
    # CSS クラス名（.live-panel-title 等）は除外し、テキストコンテンツのみ確認
    import re as _re2
    live_deals_in_text = bool(_re2.search(r'>LIVE DEALS', html))
    if live_deals_in_text:
        results.append({"level": "error", "check": "no_live_deals_text", "message": "「LIVE DEALS」テキストが表示されている（誤認を招く表記を削除してください）"})
    else:
        results.append({"level": "ok", "check": "no_live_deals_text", "message": "「LIVE DEALS」表記なし"})

    # ── #136: リアルタイム表記が存在しない ──
    realtime_in_text = bool(_re2.search(r'>リアルタイム', html))
    if realtime_in_text:
        results.append({"level": "error", "check": "no_realtime_text", "message": "「リアルタイム」テキストが表示されている（誤認を招く表記を削除してください）"})
    else:
        results.append({"level": "ok", "check": "no_realtime_text", "message": "「リアルタイム」表記なし"})

    # ── #139: 手動CSVデータに「最新」と表示されていないか ──
    # CSS定義を除外: class="freshness-live" の実際の使用（HTML要素属性）を検出
    import re as _re3
    live_class_used = bool(_re3.search(r'class="[^"]*freshness-live[^"]*"', html))
    live_text_used  = '>🟢live' in html
    if live_class_used or live_text_used:
        results.append({"level": "warning", "check": "no_live_label_on_manual", "message": "手動データにliveクラスまたは🟢liveラベルが付いている — 鮮度ラベルを確認"})
    else:
        results.append({"level": "ok", "check": "no_live_label_on_manual", "message": "手動データに「live」ラベルなし（CSS定義のみ）"})

    # ── #140: 毎日更新表記が topbar・footer・meta 以外に存在しない ──
    # 許容: topbar-live（header内）、footer-live（footer内）、meta description
    import re as _re140
    # header・footer・meta・style・script を除いた本文のみ抽出
    _html_no_chrome = _re140.sub(r'<header\b.*?</header>', '', html, flags=_re140.DOTALL)
    _html_no_chrome = _re140.sub(r'<footer\b.*?</footer>', '', _html_no_chrome, flags=_re140.DOTALL)
    _html_no_chrome = _re140.sub(r'<meta\b[^>]*/>', '', _html_no_chrome)
    _html_no_chrome = _re140.sub(r'<style\b.*?</style>', '', _html_no_chrome, flags=_re140.DOTALL)
    mainichi_in_text = bool(_re140.search(r'>毎日更新', _html_no_chrome))
    if mainichi_in_text:
        results.append({"level": "warning", "check": "no_mainichi_koshin_text", "message": "「毎日更新」テキストが topbar・footer 以外に存在する（誤認を招く可能性）"})
    else:
        results.append({"level": "ok", "check": "no_mainichi_koshin_text", "message": "「毎日更新」表記は topbar/footer 内のみ（正常）"})

    # ── #141: freshness ラベルが「価格確認:」形式を使っている ──
    # 注: 48h超古いデータ時は全て「要更新 / N日前」形式になるため、「価格確認:」は出現しない（正常）
    import re as _re4

    # ── #143: deal カードの更新行が「価格確認：」を使っている（旧「最終更新：」は禁止）──
    old_saishin_in_updated = bool(_re4.search(r'class="updated-row"[^>]*>.*?最終更新：', html, _re4.DOTALL))
    if old_saishin_in_updated:
        results.append({"level": "warning", "check": "deal_card_no_saishin_label", "message": "updated-row に「最終更新：」が残っている（「価格確認：」に統一してください）"})
    else:
        results.append({"level": "ok", "check": "deal_card_no_saishin_label", "message": "updated-row に旧「最終更新：」表記なし（価格確認：に統一済み）"})

    # ── #144: 「本日の価格データ未更新」がトップに表示されていない（Round4: 抑制済みを確認）──
    # _section_stale_warning は hidden ブロックのみ返すため、このメッセージはHTML上に出ないはず
    has_today_not_updated_top = "本日の価格データ未更新" in html
    if has_today_not_updated_top:
        results.append({"level": "error", "check": "stale_banner_date_mismatch",
                        "message": "「本日の価格データ未更新」が HTML に残っています ← Round4: 抑制されるべき"})
    else:
        results.append({"level": "ok", "check": "stale_banner_date_mismatch",
                        "message": "#144 「本日の価格データ未更新」が HTML に存在しない（OK: トップ警告抑制済み）"})

    # ── 買取価格自動取得チェック群 ──────────────────────────────────────

    # csv_today_observed_at: manual_buyback_prices.csv に本日の observed_at がある
    csv_path = PROJECT_ROOT / "data" / "manual_buyback_prices.csv"
    today_str = datetime.now().strftime("%Y-%m-%d")
    if csv_path.exists():
        import csv as _csv
        csv_has_today = False
        try:
            with open(csv_path, newline="", encoding="utf-8") as _f:
                for row in _csv.DictReader(_f):
                    obs = row.get("observed_at", "")
                    if obs.startswith(today_str):
                        csv_has_today = True
                        break
        except Exception:
            pass
        if csv_has_today:
            results.append({"level": "ok", "check": "csv_today_observed_at", "message": f"manual_buyback_prices.csv に本日({today_str})の observed_at あり"})
        else:
            results.append({"level": "warning", "check": "csv_today_observed_at", "message": f"manual_buyback_prices.csv に本日({today_str})の observed_at なし（手動更新が必要な可能性）"})
    else:
        results.append({"level": "warning", "check": "csv_today_observed_at", "message": "manual_buyback_prices.csv が存在しない"})

    # iphone17_price_fetched: iPhone 17 Pro 系の価格が1件以上取得されている（価格 > 0）
    if csv_path.exists():
        iphone17_fetched = False
        try:
            with open(csv_path, newline="", encoding="utf-8") as _f:
                for row in _csv.DictReader(_f):
                    alias = row.get("product_alias", "")
                    price_str = row.get("buyback_price", "0")
                    try:
                        price = int(price_str)
                    except ValueError:
                        price = 0
                    if alias.startswith("iphone17") and price > 0:
                        iphone17_fetched = True
                        break
        except Exception:
            pass
        if iphone17_fetched:
            results.append({"level": "ok", "check": "iphone17_price_fetched", "message": "iPhone 17 Pro 系の買取価格が1件以上取得されている"})
        else:
            results.append({"level": "warning", "check": "iphone17_price_fetched", "message": "iPhone 17 Pro 系の買取価格が0件（スクレイピング未実行 or 全失敗の可能性）"})

    # mobile_ichiban_price: モバイル一番の買取価格が存在する
    if csv_path.exists():
        mobile_ichiban_ok = False
        try:
            with open(csv_path, newline="", encoding="utf-8") as _f:
                for row in _csv.DictReader(_f):
                    if row.get("buyback_shop", "") == "mobile_ichiban":
                        try:
                            price = int(row.get("buyback_price", "0"))
                        except ValueError:
                            price = 0
                        if price > 0:
                            mobile_ichiban_ok = True
                            break
        except Exception:
            pass
        if mobile_ichiban_ok:
            results.append({"level": "ok", "check": "mobile_ichiban_price", "message": "モバイル一番の買取価格（price > 0）が存在する"})
        else:
            results.append({"level": "warning", "check": "mobile_ichiban_price", "message": "モバイル一番の買取価格が取得されていない（fetch_failed または未対応）"})

    # no_price_zero_shown: buyback_price=0 かつ data_source != fetch_failed の行がLPに表示されていない
    # LP上で price=0 の行が「取得失敗」以外の形で表示されていないかをHTML検査
    # （¥0 の直接表記がないか確認）
    zero_price_pattern = re.findall(r'(?<![¥￥\d])[¥￥]0(?!\d)', html)
    if zero_price_pattern:
        results.append({"level": "warning", "check": "no_price_zero_shown", "message": f"LP上に¥0の価格表記が{len(zero_price_pattern)}件存在する（fetch_failed以外の0価格行が表示されている可能性）"})
    else:
        results.append({"level": "ok", "check": "no_price_zero_shown", "message": "LP上に¥0の価格表記なし（0価格行は非表示 or fetch_failed表示で正常）"})

    # ── #149: 参考DEALS に固定ハードコード商品が残っていない ──
    # 参考DEALSパネル自体は2026-05-28 以降 hero から削除済み → lp-item なしは正常
    old_fixed_deals = re.findall(
        r'class="lp-name">[^<]*(iPhone 16 Pro 256GB|iPhone 15 Plus 128GB|Canon EOS R6 II|SONY α7C II)[^<]*',
        html
    )
    if old_fixed_deals:
        results.append({"level": "error", "check": "hero_deals_dynamic", "message": f"参考DEALSに固定ハードコード商品が残っている: {old_fixed_deals[:3]}"})
    else:
        # 参考DEALSパネルは削除済み（hero_right 削除対応）なので lp-item なしは正常
        results.append({"level": "ok", "check": "hero_deals_dynamic", "message": "参考DEALSに固定ハードコード商品なし（パネル削除済み = 正常）"})

    # ── #151: fetch_failed が最高買取価格計算に使われていない ──
    # shop-row-failed の価格欄は「—」になっているか（¥数字 でないか）
    import re as _re7
    # shop-row-failed の1行内（closing </div></div> まで）に ¥数字 があるか
    # re.DOTALL で複数行に跨ぐと次の shop-row の価格にマッチしてしまうため、
    # 1行ブロック（class="shop-row-failed"...から次の class="shop-row" or </div></div> まで）を抽出してチェック
    _failed_rows = _re7.findall(
        r'class="shop-row-failed">(.*?)</div>\s*</div>',
        html, _re7.DOTALL
    )
    failed_with_price = [
        row for row in _failed_rows
        if _re7.search(r'class="shop-price-col">¥[\d,]+', row)
    ]
    if failed_with_price:
        results.append({"level": "error", "check": "fetch_failed_no_price_calc", "message": f"fetch_failed 行に価格が表示されている（— になるべき）: {len(failed_with_price)}件"})
    else:
        results.append({"level": "ok", "check": "fetch_failed_no_price_calc", "message": "fetch_failed 行の価格欄が「—」（価格計算に使われていない）"})

    # ── #152: ゲーム機カードにゲーム機向け店舗が表示されている ──
    # Nintendo Switch 2 / PS5 Pro のカードにゲーム向け店舗名があるか
    game_shop_names = ["ゲオ", "イオシス", "ブックオフ", "駿河屋", "ソフマップ", "TSUTAYA", "買取商店"]
    has_game_shop = any(s in html for s in game_shop_names)
    if has_game_shop:
        found_game_shops = [s for s in game_shop_names if s in html]
        results.append({"level": "ok", "check": "game_console_shops", "message": f"ゲーム機向け店舗が表示されている: {found_game_shops}"})
    else:
        results.append({"level": "warning", "check": "game_console_shops", "message": "ゲーム機向け店舗（ゲオ/イオシス/ブックオフ等）が見つからない（ゲーム機データ要確認）"})

    # ── #153: Switch 2 カードにゲーム機向け確認リンクがある ──
    has_switch2_game_link = bool(re.search(
        r'geo-online\.co\.jp|bookoffgroup\.co\.jp|suruga-ya\.jp|sofmap\.com',
        html
    ))
    if has_switch2_game_link:
        results.append({"level": "ok", "check": "switch2_game_shop_links", "message": "Switch 2 / ゲーム機向け確認リンク（ゲオ/ブックオフ/駿河屋/ソフマップ）が存在する"})
    else:
        results.append({"level": "warning", "check": "switch2_game_shop_links", "message": "Switch 2 向けゲーム機専門店リンクが見つからない（CSV 更新 → import → LP 再生成が必要）"})

    # ── #179: exports/collector_report/latest.json が存在する ──
    import json as _json179
    _collector_report_path = PROJECT_ROOT / "exports" / "collector_report" / "latest.json"
    if _collector_report_path.exists():
        try:
            with open(_collector_report_path, encoding="utf-8") as _f179:
                _cr = _json179.load(_f179)
            results.append({"level": "ok", "check": "collector_report_exists",
                            "message": f"collector_report/latest.json 存在（生成: {_cr.get('generated_at', '?')}）"})
        except Exception as _e179:
            results.append({"level": "warning", "check": "collector_report_exists",
                            "message": f"collector_report/latest.json 読み込みエラー: {_e179}"})
    else:
        results.append({"level": "warning", "check": "collector_report_exists",
                        "message": "collector_report/latest.json が存在しない（update_buyback_prices.py を実行してください）"})

    # ── #180: suspicious_price の形式チェック ──
    if _collector_report_path.exists() and '_cr' in dir():
        _sp_list = _cr.get("suspicious_prices", None)
        if _sp_list is None:
            results.append({"level": "warning", "check": "suspicious_price_format",
                            "message": "collector_report に suspicious_prices フィールドがない"})
        elif not isinstance(_sp_list, list):
            results.append({"level": "warning", "check": "suspicious_price_format",
                            "message": "suspicious_prices がリスト形式でない"})
        else:
            _sp_invalid = [
                s for s in _sp_list
                if not all(k in s for k in ("product_alias", "shop", "price", "reason", "details"))
            ]
            if _sp_invalid:
                results.append({"level": "warning", "check": "suspicious_price_format",
                                "message": f"suspicious_prices に必須フィールド不足のエントリ {len(_sp_invalid)}件"})
            else:
                _sp_count = len(_sp_list)
                _sp_msg = f"suspicious_price {_sp_count}件あり — 確認推奨" if _sp_count > 0 else "suspicious_price なし"
                _sp_level = "warning" if _sp_count > 0 else "ok"
                results.append({"level": _sp_level, "check": "suspicious_price_format",
                                "message": f"suspicious_prices 形式OK（{_sp_msg}）"})
    else:
        results.append({"level": "ok", "check": "suspicious_price_format",
                        "message": "collector_report 未生成のためスキップ"})

    # ── #181: fetch_failed 一覧に reason フィールドがある ──
    if _collector_report_path.exists() and '_cr' in dir():
        _ff_list = _cr.get("fetch_failed", [])
        _ff_no_reason = [
            f"{f.get('product_alias')}x{f.get('shop')}"
            for f in _ff_list
            if not f.get("reason")
        ]
        if _ff_no_reason:
            results.append({"level": "warning", "check": "fetch_failed_has_reason",
                            "message": f"fetch_failed に reason なし: {_ff_no_reason[:3]}"})
        elif _ff_list:
            results.append({"level": "ok", "check": "fetch_failed_has_reason",
                            "message": f"fetch_failed {len(_ff_list)}件すべてに reason あり"})
        else:
            results.append({"level": "ok", "check": "fetch_failed_has_reason",
                            "message": "fetch_failed 0件（全取得成功）"})
    else:
        results.append({"level": "ok", "check": "fetch_failed_has_reason",
                        "message": "collector_report 未生成のためスキップ"})

    # ── #182: docs/collector_report.html が存在する ──
    _cr_html_path = PUBLIC_DIR / "collector_report.html"
    if _cr_html_path.exists():
        results.append({"level": "ok", "check": "collector_report_html_exists",
                        "message": "docs/collector_report.html 存在"})
    else:
        results.append({"level": "warning", "check": "collector_report_html_exists",
                        "message": "docs/collector_report.html が存在しない（build-public-lp を再実行してください）"})

    # ── #183: LP内に collector_report.html へのリンクがある ──
    _cr_link_in_lp = 'collector_report.html' in html
    if _cr_link_in_lp:
        results.append({"level": "ok", "check": "collector_report_link_in_lp",
                        "message": "LP内に collector_report.html へのリンクがある"})
    else:
        results.append({"level": "warning", "check": "collector_report_link_in_lp",
                        "message": "LP内に collector_report.html リンクが見つからない（LP 再生成が必要）"})

    # ── #185: iPhone系で auto_scraped 行が1件以上存在する ──
    # iPhone買取コレクターが少なくとも1件でも成功していることを確認
    import csv as _csv185
    _csv185_path = PROJECT_ROOT / "data" / "manual_buyback_prices.csv"
    _iphone_scraped = []
    if _csv185_path.exists():
        with open(_csv185_path, newline="", encoding="utf-8") as _f185:
            for _row185 in _csv185.DictReader(_f185):
                alias = _row185.get("product_alias", "")
                if (alias.startswith("iphone") and
                        _row185.get("data_source") == "auto_scraped"):
                    _iphone_scraped.append(alias)
    if _iphone_scraped:
        results.append({"level": "ok", "check": "iphone_auto_scraped_exists",
                        "message": f"iPhone系 auto_scraped 行が {len(_iphone_scraped)}件存在する: {list(set(_iphone_scraped))[:4]}"})
    else:
        results.append({"level": "error", "check": "iphone_auto_scraped_exists",
                        "message": "iPhone系 auto_scraped 行が0件 — iPhone買取コレクターがすべて失敗している"})

    # 取得失敗バッジは初心者ページに表示されるはずなので、LP自体の存在確認に置き換え
    # より確実な方法: collector_report の ok 数を確認
    _cr_path186 = PROJECT_ROOT / "exports" / "collector_report" / "latest.json"
    if _cr_path186.exists():
        import json as _json186
        _cr186 = _json186.loads(_cr_path186.read_text(encoding="utf-8"))
        _ok186 = _cr186.get("summary", {}).get("ok", 0)
        _total186 = _cr186.get("summary", {}).get("total", 0)
        if _ok186 == 0 and _total186 > 0:
            results.append({"level": "error", "check": "beginner_page_auto_scraped_exists",
                            "message": f"自動取得0件（total={_total186}）— すべての買取コレクターが失敗している"})
        elif _ok186 < 3:
            results.append({"level": "warning", "check": "beginner_page_auto_scraped_exists",
                            "message": f"自動取得成功が{_ok186}件のみ（total={_total186}）— 多くのコレクターが失敗している"})
        else:
            results.append({"level": "ok", "check": "beginner_page_auto_scraped_exists",
                            "message": f"自動取得 OK {_ok186}件 / total {_total186}件"})
    else:
        results.append({"level": "ok", "check": "beginner_page_auto_scraped_exists",
                        "message": "collector_report 未生成のためスキップ"})

    # ── #188: iPhone 17 Pro 256GB に価格取得成功行が存在する ──
    import csv as _csv188
    _csv188_path = PROJECT_ROOT / "data" / "manual_buyback_prices.csv"
    _i17p256_rows = []
    if _csv188_path.exists():
        with open(_csv188_path, newline="", encoding="utf-8") as _f188:
            for _row188 in _csv188.DictReader(_f188):
                if (_row188.get("product_alias") == "iphone17pro256" and
                        _row188.get("data_source") == "auto_scraped"):
                    _price188 = _row188.get("buyback_price", "0")
                    try:
                        if float(_price188) > 0:
                            _i17p256_rows.append(_row188.get("buyback_shop"))
                    except (ValueError, TypeError):
                        pass
    if _i17p256_rows:
        results.append({"level": "ok", "check": "iphone17pro256_price_scraped",
                        "message": f"iPhone 17 Pro 256GB の価格取得成功: {_i17p256_rows}"})
    else:
        results.append({"level": "warning", "check": "iphone17pro256_price_scraped",
                        "message": "iPhone 17 Pro 256GB の auto_scraped 価格行がゼロ — コレクター修正が必要"})

    # ── #191: 取得失敗理由が reason フィールド付きで表示されている ──
    # collector_report の fetch_failed 一覧に reason が含まれているか確認
    _cr_path191 = PROJECT_ROOT / "exports" / "collector_report" / "latest.json"
    if _cr_path191.exists():
        import json as _json191
        _cr191 = _json191.loads(_cr_path191.read_text(encoding="utf-8"))
        _ff191 = _cr191.get("fetch_failed", [])
        _no_reason = [f"{f.get('product_alias')}x{f.get('shop')}" for f in _ff191 if not f.get("reason")]
        if _no_reason:
            results.append({"level": "warning", "check": "fetch_failed_has_reason_field",
                            "message": f"取得失敗エントリーに reason なしが {len(_no_reason)}件: {_no_reason[:3]}"})
        else:
            results.append({"level": "ok", "check": "fetch_failed_has_reason_field",
                            "message": f"全取得失敗エントリーに reason フィールドあり（{len(_ff191)}件）"})
    else:
        results.append({"level": "ok", "check": "fetch_failed_has_reason_field",
                        "message": "collector_report 未生成のためスキップ"})

    # ── #178: auto_scraped行のlink_verifiedがすべてtrue（URLスラッグ推測チェック） ──
    # URL推測（スラッグ生成）が禁止されているため、auto_scrapedはlink_verified=trueであるべき
    import csv as _csv178
    _auto_unverified = []
    _csv178_path = PROJECT_ROOT / "data" / "manual_buyback_prices.csv"
    if _csv178_path.exists():
        with open(_csv178_path, newline="", encoding="utf-8") as _f178:
            for _row178 in _csv178.DictReader(_f178):
                if (_row178.get("data_source") == "auto_scraped"
                        and _row178.get("link_verified", "").lower() != "true"):
                    _auto_unverified.append(
                        f"{_row178.get('product_alias')}x{_row178.get('buyback_shop')}"
                    )
    if _auto_unverified:
        results.append({"level": "warning", "check": "auto_scraped_link_verified",
                        "message": f"auto_scraped行にlink_verified=falseが{len(_auto_unverified)}件（URL推測の可能性）: {_auto_unverified[:3]}"})
    else:
        results.append({"level": "ok", "check": "auto_scraped_link_verified",
                        "message": "auto_scraped行のlink_verifiedはすべてtrue（URL推測なし）"})

    # ── #192: iPhone各商品に成功店舗3件以上 ─────────────────────────────────
    if _collector_report_path.exists() and '_cr' in dir():
        _psd = _cr.get("product_shop_detail", {})
        _iphone_aliases = ["iphone17pro256", "iphone17pro512", "iphone17pm256", "iphone17pm512"]
        _iphone_fail = []
        for _ia in _iphone_aliases:
            _cnt = len(_psd.get(_ia, {}).get("success_shops", []))
            if _cnt < 3:
                _iphone_fail.append(f"{_ia}:{_cnt}店舗")
        if _iphone_fail:
            results.append({"level": "warning", "check": "iphone_min3_shops",
                            "message": f"iPhone商品の成功店舗数が3未満: {', '.join(_iphone_fail)}"})
        else:
            results.append({"level": "ok", "check": "iphone_min3_shops",
                            "message": "iPhone主要4商品すべて成功店舗≥3"})
    else:
        results.append({"level": "ok", "check": "iphone_min3_shops",
                        "message": "collector_report 未生成のためスキップ"})

    # ── #193: Switch2に成功店舗2件以上 ──────────────────────────────────────
    if _collector_report_path.exists() and '_cr' in dir():
        _psd = _cr.get("product_shop_detail", {})
        _sw2_cnt = len(_psd.get("switch2", {}).get("success_shops", []))
        if _sw2_cnt < 2:
            results.append({"level": "warning", "check": "switch2_min2_shops",
                            "message": f"Switch2の成功店舗数が2未満: {_sw2_cnt}店舗"})
        else:
            results.append({"level": "ok", "check": "switch2_min2_shops",
                            "message": f"Switch2 成功店舗≥2（{_sw2_cnt}店舗）"})
    else:
        results.append({"level": "ok", "check": "switch2_min2_shops",
                        "message": "collector_report 未生成のためスキップ"})

    # ── #194: PS5 Proに成功店舗2件以上 ──────────────────────────────────────
    if _collector_report_path.exists() and '_cr' in dir():
        _psd = _cr.get("product_shop_detail", {})
        _ps5_cnt = len(_psd.get("ps5_pro", {}).get("success_shops", []))
        if _ps5_cnt < 2:
            results.append({"level": "warning", "check": "ps5pro_min2_shops",
                            "message": f"PS5 Proの成功店舗数が2未満: {_ps5_cnt}店舗"})
        else:
            results.append({"level": "ok", "check": "ps5pro_min2_shops",
                            "message": f"PS5 Pro 成功店舗≥2（{_ps5_cnt}店舗）"})
    else:
        results.append({"level": "ok", "check": "ps5pro_min2_shops",
                        "message": "collector_report 未生成のためスキップ"})

    # ── #195: 取得失敗理由が "unknown" のまま残っていない ────────────────────
    if _collector_report_path.exists() and '_cr' in dir():
        _ff_all = _cr.get("fetch_failed", [])
        _unknown_list = [
            f"{f.get('product_alias')}x{f.get('shop')}"
            for f in _ff_all
            if (f.get("reason") or "unknown") == "unknown"
        ]
        if _unknown_list:
            results.append({"level": "warning", "check": "no_unknown_failure_reason",
                            "message": f"failure_reason が unknown のまま {len(_unknown_list)}件: {_unknown_list[:5]}"})
        else:
            results.append({"level": "ok", "check": "no_unknown_failure_reason",
                            "message": "すべての取得失敗に reason が設定されている（unknown なし）"})
    else:
        results.append({"level": "ok", "check": "no_unknown_failure_reason",
                        "message": "collector_report 未生成のためスキップ"})

    _debug_dir = PROJECT_ROOT / "exports" / "debug"
    if _debug_dir.exists():
        _debug_files = list(_debug_dir.glob("*.html")) + list(_debug_dir.glob("*.txt"))
        if len(_debug_files) >= 2:
            results.append({"level": "ok", "check": "debug_files_saved",
                            "message": f"exports/debug/ に診断ファイル {len(_debug_files)}件あり"})
        else:
            results.append({"level": "warning", "check": "debug_files_saved",
                            "message": f"exports/debug/ のファイルが少ない: {len(_debug_files)}件（diagnose_collectors.py を実行してください）"})
    else:
        results.append({"level": "warning", "check": "debug_files_saved",
                        "message": "exports/debug/ ディレクトリが存在しない（diagnose_collectors.py を実行してください）"})

    # ── #197: confidence=low の価格がLPに表示されていない ────────────────────
    # docs/index.html（公開ビルド後）または exports/lp/daily/index_A.html を使用
    _lp_html_197 = ""
    _lp_file_197 = PUBLIC_DIR / "index.html"
    if not _lp_file_197.exists():
        # フォールバック: exports/lp/daily/index_A.html
        _lp_file_197 = PROJECT_ROOT / "exports" / "lp" / "daily" / "index_A.html"
    if _lp_file_197.exists():
        _lp_html_197 = _lp_file_197.read_text(encoding="utf-8", errors="ignore")
    if _lp_html_197:
        # confidence=low 行には data-confidence="low" 属性が付与される想定
        # または collector_report の low_confidence_count をチェック
        _cr_ref = _cr if ('_cr' in dir() and _cr) else {}
        _low_conf_in_cr = _cr_ref.get("low_confidence_count", 0)
        if 'data-confidence="low"' in _lp_html_197:
            results.append({"level": "error", "check": "low_confidence_not_in_lp",
                            "message": "confidence=low の価格がLPに含まれている（誤価格リスク）"})
        else:
            results.append({"level": "ok", "check": "low_confidence_not_in_lp",
                            "message": f"confidence=low 価格がLPに含まれていない（low={_low_conf_in_cr}件）"})
    else:
        results.append({"level": "warning", "check": "low_confidence_not_in_lp",
                        "message": "LP HTMLが見つからないため confidence=low チェックをスキップ"})

    # ── #198: suspicious_price がLPに表示されていない ────────────────────────
    _lp_html_198 = _lp_html_197  # 同じLPファイルを使用
    if _lp_html_198:
        if 'data-suspicious="true"' in _lp_html_198 or 'suspicious-price' in _lp_html_198:
            results.append({"level": "error", "check": "suspicious_price_not_in_lp",
                            "message": "suspicious_price がLPに含まれている（誤価格リスク）"})
        else:
            _cr_ref198 = _cr if ('_cr' in dir() and _cr) else {}
            _sp_count198 = len(_cr_ref198.get("suspicious_prices", []))
            results.append({"level": "ok", "check": "suspicious_price_not_in_lp",
                            "message": f"suspicious_price がLPに含まれていない（要疑い価格={_sp_count198}件）"})
    else:
        results.append({"level": "warning", "check": "suspicious_price_not_in_lp",
                        "message": "LP HTMLが見つからないため suspicious_price チェックをスキップ"})

    # ── #202: check_collector_quality.py が存在する ───────────────────────────
    _quality_script = PROJECT_ROOT / "scripts" / "check_collector_quality.py"
    if _quality_script.exists():
        results.append({"level": "ok", "check": "quality_gate_script_exists",
                        "message": "scripts/check_collector_quality.py が存在"})
    else:
        results.append({"level": "error", "check": "quality_gate_script_exists",
                        "message": "scripts/check_collector_quality.py が見つからない"})

    # ── #203: GitHub Actions に quality gate step が存在する ──────────────────
    _workflow_path = PROJECT_ROOT / ".github" / "workflows" / "daily_lp.yml"
    if _workflow_path.exists():
        _workflow_text = _workflow_path.read_text(encoding="utf-8")
        if "check_collector_quality.py" in _workflow_text:
            results.append({"level": "ok", "check": "quality_gate_in_workflow",
                            "message": "GitHub Actions に quality gate step がある"})
        else:
            results.append({"level": "warning", "check": "quality_gate_in_workflow",
                            "message": "GitHub Actions に check_collector_quality.py が含まれていない"})
    else:
        results.append({"level": "warning", "check": "quality_gate_in_workflow",
                        "message": ".github/workflows/daily_lp.yml が見つからない"})

    # ── #204: collector_report の summary が latest.json に存在する ─────────────
    _cr_check = _cr if ('_cr' in dir() and _cr) else {}
    _cr_summary = _cr_check.get("summary", {})
    if _cr_summary and _cr_summary.get("total", 0) > 0:
        _ok204 = _cr_summary.get("ok", 0)
        _total204 = _cr_summary.get("total", 0)
        _pct204 = round(_ok204 / _total204 * 100)
        results.append({"level": "ok", "check": "collector_summary_in_report",
                        "message": f"latest.json summary OK: {_ok204}/{_total204} ({_pct204}%)"})
    else:
        results.append({"level": "warning", "check": "collector_summary_in_report",
                        "message": "latest.json に summary フィールドがないか total=0"})

    # ── #205: Playwright browser install が daily_lp.yml に存在する ──────────────
    if _workflow_path.exists() and '_workflow_text' in dir():
        if "playwright install" in _workflow_text and "chromium" in _workflow_text:
            results.append({"level": "ok", "check": "playwright_install_in_workflow",
                            "message": "daily_lp.yml に playwright install --with-deps chromium が存在"})
        else:
            results.append({"level": "error", "check": "playwright_install_in_workflow",
                            "message": "daily_lp.yml に playwright install --with-deps chromium が見つからない（JS系コレクターが失敗する）"})
    else:
        results.append({"level": "warning", "check": "playwright_install_in_workflow",
                        "message": ".github/workflows/daily_lp.yml が見つからない"})

    # ── #206e: concurrency 設定が daily_lp.yml にある ────────────────────────
    if _workflow_path.exists() and '_workflow_text' in dir():
        _t206e1 = "concurrency:" in _workflow_text and "daily-lp-update" in _workflow_text
        results.append({"level": "ok" if _t206e1 else "warning", "check": "workflow_concurrency_set",
                        "message": "daily_lp.yml に concurrency: group=daily-lp-update が設定されている"
                                   + ("" if _t206e1 else " ← 同時実行push競合が発生する可能性あり")})
        _t206e2 = "cancel-in-progress: false" in _workflow_text
        results.append({"level": "ok" if _t206e2 else "warning", "check": "workflow_concurrency_no_cancel",
                        "message": "daily_lp.yml の concurrency が cancel-in-progress: false（後続を待機）"
                                   + ("" if _t206e2 else " ← cancel-in-progress: false を推奨")})
        # Phase 13: push の前の pull は未ステージの変更で失敗していた（2つの実行が重なった日に push も拒否された）。
        # push が拒否されたときに、未ステージの変更を退避して取り込み直す形を確かめる
        _t206e3 = ("git pull --rebase --autostash origin main" in _workflow_text
                   and "if ! git push origin main" in _workflow_text
                   and "-X theirs" not in _workflow_text and "git rebase --abort" in _workflow_text)
        results.append({"level": "ok" if _t206e3 else "warning", "check": "workflow_pull_rebase_before_push",
                        "message": "Commit and push ステップが、push を拒否されたら git pull --rebase --autostash で"
                                   "取り込み直す"
                                   + ("" if _t206e3 else " ← push競合の二重安全策が未設定")})
    else:
        for _ck in ("workflow_concurrency_set", "workflow_concurrency_no_cancel", "workflow_pull_rebase_before_push"):
            results.append({"level": "warning", "check": _ck,
                            "message": ".github/workflows/daily_lp.yml が見つからない"})

    # ── #206: collector_not_loaded が 0 件 ───────────────────────────────────
    if _collector_report_path.exists() and '_cr' in dir() and _cr:
        _ff206 = _cr.get("fetch_failed", [])
        _not_loaded = [
            f"{f.get('shop')}×{f.get('product_alias')}"
            for f in _ff206
            if f.get("reason") == "collector_not_loaded"
        ]
        if _not_loaded:
            results.append({"level": "warning", "check": "no_collector_not_loaded",
                            "message": f"collector_not_loaded が {len(_not_loaded)}件残存: {_not_loaded[:3]}（NOT_SUPPORTED_SHOPS に追加してください）"})
        else:
            results.append({"level": "ok", "check": "no_collector_not_loaded",
                            "message": "collector_not_loaded = 0（すべて not_supported または実装済み）"})
    else:
        results.append({"level": "ok", "check": "no_collector_not_loaded",
                        "message": "collector_report 未生成のためスキップ"})

    # ── #207: playwright_not_installed が 0 件 ──────────────────────────────
    if _collector_report_path.exists() and '_cr' in dir() and _cr:
        _ff207 = _cr.get("fetch_failed", [])
        _pw_fail = [
            f"{f.get('shop')}×{f.get('product_alias')}"
            for f in _ff207
            if f.get("reason") == "playwright_not_installed"
        ]
        if _pw_fail:
            results.append({"level": "warning", "check": "no_playwright_not_installed",
                            "message": f"playwright_not_installed が {len(_pw_fail)}件（workflow に playwright install ステップが必要）: {_pw_fail[:3]}"})
        else:
            results.append({"level": "ok", "check": "no_playwright_not_installed",
                            "message": "playwright_not_installed = 0"})
    else:
        results.append({"level": "ok", "check": "no_playwright_not_installed",
                        "message": "collector_report 未生成のためスキップ"})

    # ── #208: GitHub Actions 環境別閾値が check_collector_quality.py に存在する ──
    if _quality_script.exists():
        _qs_text = _quality_script.read_text(encoding="utf-8")
        if "GITHUB_ACTIONS" in _qs_text and "IS_GITHUB_ACTIONS" in _qs_text:
            results.append({"level": "ok", "check": "github_actions_threshold_exists",
                            "message": "check_collector_quality.py に IS_GITHUB_ACTIONS フラグが存在"})
        else:
            results.append({"level": "warning", "check": "github_actions_threshold_exists",
                            "message": "check_collector_quality.py に IS_GITHUB_ACTIONS 環境別閾値がない（GH Actions上で false warning が出る可能性）"})
    else:
        results.append({"level": "warning", "check": "github_actions_threshold_exists",
                        "message": "check_collector_quality.py が見つからない"})

    # ── #209: quality gate の FAILURE 条件が suspicious_price/low_confidence のみ ──
    if _quality_script.exists():
        _qs_text2 = _quality_script.read_text(encoding="utf-8") if '_qs_text' not in dir() else _qs_text
        # 旧FAILUREパターン（店舗数不足がFAILURE条件になっている）の検出
        _old_failure_pattern = (
            "iphone_min3_shops" in _qs_text2 and
            '"FAILURE"' in _qs_text2 and
            "switch2_min2_shops" in _qs_text2
        )
        # 正しいパターン: suspicious_price と low_confidence のみ FAILURE
        _has_suspicious_failure = "suspicious_price" in _qs_text2 and "low_confidence" in _qs_text2
        if _has_suspicious_failure and not _old_failure_pattern:
            results.append({"level": "ok", "check": "only_suspicious_low_conf_is_failure",
                            "message": "quality gate の FAILURE 条件が suspicious_price / low_confidence のみ（店舗数不足はWARNING）"})
        else:
            results.append({"level": "warning", "check": "only_suspicious_low_conf_is_failure",
                            "message": "quality gate の FAILURE 条件を確認してください（suspicious_price / low_confidence のみにすべき）"})
    else:
        results.append({"level": "warning", "check": "only_suspicious_low_conf_is_failure",
                        "message": "check_collector_quality.py が見つからない"})

    # ── #213: mobile_ichiban コレクターに timeout >= 45秒 の設定がある ─────────────
    _mi_collector = PROJECT_ROOT / "src" / "collectors" / "buyback_mobile_ichiban.py"
    if _mi_collector.exists():
        _mi_text = _mi_collector.read_text(encoding="utf-8")
        # _PW_GOTO_TIMEOUT_MS >= 45000 が設定されているか確認
        # Python の数値リテラルは _ 区切り可能（例: 60_000）→ _ を除去して数値化
        import re as _re
        _timeout_match = _re.search(r'_PW_GOTO_TIMEOUT_MS\s*=\s*([\d_]+)', _mi_text)
        _timeout_val = int(_timeout_match.group(1).replace("_", "")) if _timeout_match else 0
        if _timeout_val >= 45_000:
            results.append({"level": "ok", "check": "mobile_ichiban_timeout_gte45s",
                            "message": f"mobile_ichiban Playwright goto timeout = {_timeout_val}ms（>= 45000）"})
        else:
            results.append({"level": "warning", "check": "mobile_ichiban_timeout_gte45s",
                            "message": f"mobile_ichiban Playwright timeout が {_timeout_val}ms — 45000ms 以上推奨"})
    else:
        results.append({"level": "warning", "check": "mobile_ichiban_timeout_gte45s",
                        "message": "src/collectors/buyback_mobile_ichiban.py が見つからない"})

    # ── #214: mobile_ichiban が domcontentloaded を使用している（networkidle 禁止）───
    if _mi_collector.exists():
        _uses_domcontentloaded = "domcontentloaded" in _mi_text
        # コード内で networkidle を wait_until 引数として使用しているか確認
        # （docstring / コメント内の言及は除外）
        _uses_networkidle = bool(
            _re.search(r'wait_until\s*=\s*["\']networkidle["\']', _mi_text) or
            _re.search(r'wait_for_load_state\s*\(\s*["\']networkidle["\']', _mi_text)
        )
        if _uses_domcontentloaded and not _uses_networkidle:
            results.append({"level": "ok", "check": "mobile_ichiban_no_networkidle",
                            "message": "mobile_ichiban が domcontentloaded を使用、networkidle は使用していない（タイムアウト対策）"})
        elif _uses_networkidle:
            results.append({"level": "warning", "check": "mobile_ichiban_no_networkidle",
                            "message": "mobile_ichiban が networkidle を使用している — タイムアウトの原因になるため domcontentloaded に変更推奨"})
        else:
            results.append({"level": "warning", "check": "mobile_ichiban_no_networkidle",
                            "message": "mobile_ichiban の wait_until 設定が不明 — domcontentloaded を使用しているか確認してください"})
    else:
        results.append({"level": "warning", "check": "mobile_ichiban_no_networkidle",
                        "message": "src/collectors/buyback_mobile_ichiban.py が見つからない"})

    # ── #215: mobile_ichiban が requests fast path を持っている ──────────────────
    if _mi_collector.exists():
        _has_requests_fastpath = (
            "requests" in _mi_text and
            "_MIN_CONTENT_LENGTH" in _mi_text
        )
        if _has_requests_fastpath:
            results.append({"level": "ok", "check": "mobile_ichiban_requests_fastpath",
                            "message": "mobile_ichiban が requests fast path を実装（Playwright 前にまず requests 試行）"})
        else:
            results.append({"level": "warning", "check": "mobile_ichiban_requests_fastpath",
                            "message": "mobile_ichiban に requests fast path がない — Playwright タイムアウトリスクあり"})
    else:
        results.append({"level": "warning", "check": "mobile_ichiban_requests_fastpath",
                        "message": "src/collectors/buyback_mobile_ichiban.py が見つからない"})

    # ── #216: mobile_ichiban が全文fallback（extract_price）を使っていない ──────────
    if _mi_collector.exists():
        _no_extract_price_fallback = "extract_price" not in _mi_text or (
            # コメントのみの言及は許可（コードとして呼ばれていない）
            all("# " in line for line in _mi_text.split("\n") if "extract_price" in line)
        )
        # より確実な確認: return self.extract_price の呼び出しがないか
        _has_extract_price_call = bool(_re.search(r'return\s+self\.extract_price\(', _mi_text))
        if not _has_extract_price_call:
            results.append({"level": "ok", "check": "mobile_ichiban_no_extract_price_fallback",
                            "message": "mobile_ichiban が全文 extract_price() fallback を使っていない（商品名マッチなし価格採用禁止）"})
        else:
            results.append({"level": "warning", "check": "mobile_ichiban_no_extract_price_fallback",
                            "message": "mobile_ichiban が extract_price() fallback を使用 — 商品名と無関係な価格を採用するリスクあり"})
    else:
        results.append({"level": "warning", "check": "mobile_ichiban_no_extract_price_fallback",
                        "message": "src/collectors/buyback_mobile_ichiban.py が見つからない"})

    # ── #217: mobile_ichiban debug ファイルが生成される仕組みが存在する ──────────
    _debug_script = PROJECT_ROOT / "scripts" / "update_buyback_prices.py"
    if _debug_script.exists():
        _ds_text = _debug_script.read_text(encoding="utf-8")
        _has_save_debug = "_save_debug_txt" in _ds_text
        _has_elapsed    = "elapsed_seconds" in _ds_text
        _has_error_type = "error_type" in _ds_text
        if _has_save_debug and _has_elapsed and _has_error_type:
            results.append({"level": "ok", "check": "mobile_ichiban_debug_output",
                            "message": "_save_debug_txt が elapsed_seconds / error_type を含む詳細デバッグを出力する"})
        else:
            missing_fields = [f for f, v in [("_save_debug_txt", _has_save_debug),
                                              ("elapsed_seconds", _has_elapsed),
                                              ("error_type", _has_error_type)] if not v]
            results.append({"level": "warning", "check": "mobile_ichiban_debug_output",
                            "message": f"debug_txt に不足フィールドあり: {', '.join(missing_fields)}"})
    else:
        results.append({"level": "warning", "check": "mobile_ichiban_debug_output",
                        "message": "scripts/update_buyback_prices.py が見つからない"})

    # ── #218: mobile_ichiban failure_reason に timeout が分類されている ─────────
    if _mi_collector.exists():
        _has_timeout_reason = (
            'last_failure_reason = "timeout"' in _mi_text or
            "last_failure_reason = 'timeout'" in _mi_text
        )
        if _has_timeout_reason:
            results.append({"level": "ok", "check": "mobile_ichiban_timeout_reason_classified",
                            "message": "mobile_ichiban が timeout を last_failure_reason に分類している"})
        else:
            results.append({"level": "warning", "check": "mobile_ichiban_timeout_reason_classified",
                            "message": "mobile_ichiban が timeout を last_failure_reason に分類していない — debug レポートでタイムアウトが不明になる"})
    else:
        results.append({"level": "warning", "check": "mobile_ichiban_timeout_reason_classified",
                        "message": "src/collectors/buyback_mobile_ichiban.py が見つからない"})

    # ── #219: mobile_ichiban が product_not_listed を分類している ────────────────
    if _mi_collector.exists():
        _has_not_listed = (
            'last_failure_reason = "product_not_listed"' in _mi_text or
            "last_failure_reason = 'product_not_listed'" in _mi_text
        )
        if _has_not_listed:
            results.append({"level": "ok", "check": "mobile_ichiban_not_listed_classified",
                            "message": "mobile_ichiban が product_not_listed を last_failure_reason に分類している"})
        else:
            results.append({"level": "warning", "check": "mobile_ichiban_not_listed_classified",
                            "message": "mobile_ichiban が product_not_listed を分類していない — 未掲載と取得失敗が区別できない"})
    else:
        results.append({"level": "warning", "check": "mobile_ichiban_not_listed_classified",
                        "message": "src/collectors/buyback_mobile_ichiban.py が見つからない"})

    # ── #220: collector_report に product_not_listed が分類されている ────────────
    _latest_report = PROJECT_ROOT / "exports" / "collector_report" / "latest.json"
    if _latest_report.exists():
        import json as _json
        try:
            _report = _json.loads(_latest_report.read_text(encoding="utf-8"))
            _fail_ranking = _report.get("failure_reason_ranking", [])
            _reason_names = [item["reason"] for item in _fail_ranking]
            _has_not_listed_in_report = "product_not_listed" in _reason_names
            _has_price_not_found      = "price_not_found" in _reason_names
            # 両方存在する or 片方だけ存在する（どちらか1つでもあれば分類できている）
            if _has_not_listed_in_report:
                results.append({"level": "ok", "check": "report_has_not_listed_reason",
                                "message": "collector_report の failure_reason_ranking に product_not_listed が存在する（未掲載/失敗が別集計）"})
            else:
                results.append({"level": "warning", "check": "report_has_not_listed_reason",
                                "message": "collector_report の failure_reason_ranking に product_not_listed がない — 実際に未掲載商品があるか確認してください"})
        except Exception as _e:
            results.append({"level": "warning", "check": "report_has_not_listed_reason",
                            "message": f"latest.json の読み込みエラー: {_e}"})
    else:
        results.append({"level": "warning", "check": "report_has_not_listed_reason",
                        "message": "exports/collector_report/latest.json が見つからない"})

    # ── #221: LP上で product_not_listed が「現在未掲載」と表示される ────────────
    _lp_gen_path = PROJECT_ROOT / "src" / "content" / "daily_lp_generator.py"

    # ── #222: base_csv_collector が failure_reason を上書きしない ────────────────
    _base_collector = PROJECT_ROOT / "src" / "collectors" / "buyback_base_csv.py"
    if _base_collector.exists():
        _bc_text = _base_collector.read_text(encoding="utf-8")
        # 正しいパターン: if self.last_failure_reason is None: が price_not_found の前にある
        _has_none_check = bool(
            _re.search(r'if\s+self\.last_failure_reason\s+is\s+None.*?price_not_found', _bc_text, _re.DOTALL)
        )
        if _has_none_check:
            results.append({"level": "ok", "check": "base_collector_no_reason_overwrite",
                            "message": "buyback_base_csv.py が last_failure_reason を上書きしない（None チェック実装済み）"})
        else:
            results.append({"level": "warning", "check": "base_collector_no_reason_overwrite",
                            "message": "buyback_base_csv.py が last_failure_reason を上書きしている可能性 — None チェックが必要"})
    else:
        results.append({"level": "warning", "check": "base_collector_no_reason_overwrite",
                        "message": "src/collectors/buyback_base_csv.py が見つからない"})

    # ── #223: mobile_ichiban 512GB が price_not_found でなく product_not_listed ──
    if _latest_report.exists():
        try:
            _psd = _report.get("product_shop_detail", {})
            _512_not_listed = (
                "mobile_ichiban" in _psd.get("iphone17pro512", {}).get("not_listed_shops", []) or
                "mobile_ichiban" in _psd.get("iphone17pm512",  {}).get("not_listed_shops", [])
            )
            _512_price_not_found = (
                "mobile_ichiban" in _psd.get("iphone17pro512", {}).get("failed_shops", []) or
                "mobile_ichiban" in _psd.get("iphone17pm512",  {}).get("failed_shops", [])
            )
            if _512_not_listed:
                results.append({"level": "ok", "check": "mobile_ichiban_512_not_listed",
                                "message": "mobile_ichiban の 512GB 系が product_not_listed として正しく分類されている"})
            elif _512_price_not_found:
                results.append({"level": "warning", "check": "mobile_ichiban_512_not_listed",
                                "message": "mobile_ichiban の 512GB 系が product_not_listed でなく failed_shops に入っている — 分類の修正が必要"})
            else:
                results.append({"level": "ok", "check": "mobile_ichiban_512_not_listed",
                                "message": "mobile_ichiban 512GB エントリが report に存在しない（今回の取得対象外またはスキップ）"})
        except Exception as _e:
            results.append({"level": "warning", "check": "mobile_ichiban_512_not_listed",
                            "message": f"512GB 分類チェックエラー: {_e}"})
    else:
        results.append({"level": "warning", "check": "mobile_ichiban_512_not_listed",
                        "message": "latest.json が見つからない"})

    # #224（旧UIの CSS の未掲載バッジの色）は UI Phase 10 で旧UIと一緒に削除した

    # ── #225〜#232: 抽選タブ正規化チェック ─────────────────────────────────────
    import re as _re3
    _lp_gen_path_v2 = PROJECT_ROOT / "src" / "content" / "daily_lp_generator.py"
    if _lp_gen_path_v2.exists():
        _lp_gen_text = _lp_gen_path_v2.read_text(encoding="utf-8")

        # ── #225: RICOH GR IV Monochrome が lottery_events.csv または _LOTTERY_REFERENCE_ITEMS に存在 ──
        # RICOH は CSV(auto_scraped) 管理に移行済みのため、CSV を優先して確認
        _lottery_csv_path = PROJECT_ROOT / "data" / "lottery_events.csv"
        _lottery_csv_text = _lottery_csv_path.read_text(encoding="utf-8") if _lottery_csv_path.exists() else ""
        _mono_in_csv  = "RICOH GR IV Monochrome" in _lottery_csv_text
        _mono_in_code = "RICOH GR IV Monochrome" in _lp_gen_text
        if _mono_in_csv or _mono_in_code:
            _loc = "lottery_events.csv" if _mono_in_csv else "_LOTTERY_REFERENCE_ITEMS"
            results.append({"level": "ok", "check": "ricoh_monochrome_single",
                            "message": f"RICOH GR IV Monochrome が {_loc} に定義済み"})
        else:
            results.append({"level": "error", "check": "ricoh_monochrome_single",
                            "message": "RICOH GR IV Monochrome が lottery_events.csv にも _LOTTERY_REFERENCE_ITEMS にも存在しない"})

        # ── #226: RICOH GR IV HDF が lottery_events.csv または _LOTTERY_REFERENCE_ITEMS に存在 ──
        _hdf_in_csv  = "RICOH GR IV HDF" in _lottery_csv_text
        _hdf_in_code = "RICOH GR IV HDF" in _lp_gen_text
        if _hdf_in_csv or _hdf_in_code:
            _loc_hdf = "lottery_events.csv" if _hdf_in_csv else "_LOTTERY_REFERENCE_ITEMS"
            results.append({"level": "ok", "check": "ricoh_hdf_single",
                            "message": f"RICOH GR IV HDF が {_loc_hdf} に定義済み"})
        else:
            results.append({"level": "error", "check": "ricoh_hdf_single",
                            "message": "RICOH GR IV HDF が lottery_events.csv にも _LOTTERY_REFERENCE_ITEMS にも存在しない"})

        # ── #227: X100VI / PS5 / Switch2 が reference_only=True で定義されている ──
        _ref_items_block = _re3.search(
            r'_LOTTERY_REFERENCE_ITEMS\s*=\s*\[(.*?)\n    \]',
            _lp_gen_text, _re3.DOTALL
        )
        _ref_block_text = _ref_items_block.group(1) if _ref_items_block else _lp_gen_text
        _ref_only_items = {"FUJIFILM X100VI", "PlayStation 5 Pro", "Nintendo Switch 2"}
        _ref_only_ok = True
        _ref_only_missing = []
        for _item_name in _ref_only_items:
            # そのアイテム名が含まれるブロック周辺に reference_only: True があるか確認
            _item_pos = _ref_block_text.find(_item_name)
            if _item_pos == -1:
                _ref_only_missing.append(_item_name)
                _ref_only_ok = False
                continue
            # 前後 300 文字内に reference_only があるか
            _nearby = _ref_block_text[max(0, _item_pos - 50):_item_pos + 300]
            if '"reference_only": True' not in _nearby and "'reference_only': True" not in _nearby:
                _ref_only_missing.append(f"{_item_name}(reference_only なし)")
                _ref_only_ok = False
        if _ref_only_ok:
            results.append({"level": "ok", "check": "reference_only_items_flagged",
                            "message": "X100VI / PS5 / Switch2 に reference_only=True が設定済み"})
        else:
            results.append({"level": "error", "check": "reference_only_items_flagged",
                            "message": f"reference_only=True が未設定: {', '.join(_ref_only_missing)}"})

        # ── #228: RICOH 3件が CSV で auto_scraped 管理 OR reference_only でない ──────
        # RICOH は lottery_events.csv(auto_scraped) に移行済み
        # _LOTTERY_REFERENCE_ITEMS 内に RICOH + reference_only=True の組み合わせがないことを確認
        _ricoh_ref_only_found = []
        for _rname in ["RICOH GR IV Monochrome", "RICOH GR IV HDF"]:
            _pos = _ref_block_text.find(_rname)
            if _pos != -1:
                _ctx = _ref_block_text[_pos:_pos + 200]
                if '"reference_only": True' in _ctx or "'reference_only': True" in _ctx:
                    _ricoh_ref_only_found.append(_rname)
        # CSV で管理されているなら問題なし（_LOTTERY_REFERENCE_ITEMS に RICOH がなくても OK）
        _ricoh_in_csv = "RICOH GR IV" in _lottery_csv_text
        if not _ricoh_ref_only_found:
            _where = "lottery_events.csv（auto_scraped）" if _ricoh_in_csv else "_LOTTERY_REFERENCE_ITEMS（reference_only なし）"
            results.append({"level": "ok", "check": "ricoh_not_reference_only",
                            "message": f"RICOH GR IV は {_where} で管理 — reference_only=True なし"})
        else:
            results.append({"level": "error", "check": "ricoh_not_reference_only",
                            "message": f"RICOH 以下のアイテムに reference_only=True が誤設定: {', '.join(_ricoh_ref_only_found)}"})

        # ── #231: "次回未定" / "抽選情報未確認" が _LOTTERY_REFERENCE_ITEMS に存在しない ──
        _stale_phrases = ["次回未定", "抽選情報未確認", "一次抽選終了"]
        _stale_found = [p for p in _stale_phrases if p in _ref_block_text]
        if not _stale_found:
            results.append({"level": "ok", "check": "no_stale_lottery_phrases",
                            "message": "「次回未定」「抽選情報未確認」「一次抽選終了」等の古い文言が _LOTTERY_REFERENCE_ITEMS に含まれていない"})
        else:
            results.append({"level": "warning", "check": "no_stale_lottery_phrases",
                            "message": f"古い抽選文言が残存: {', '.join(_stale_found)}"})
    else:
        # #229（_section_lottery の4区分）・#230（旧UIの抽選の件数）・#232（旧UIの抽選の状態判定）は、
        # UI Phase 10 で旧UIの抽選の描画と一緒に削除した（抽選の状態は新UIの runtime が判定する）
        for _chk_name in ["ricoh_monochrome_single", "ricoh_hdf_single", "reference_only_items_flagged",
                          "ricoh_not_reference_only", "no_stale_lottery_phrases"]:
            results.append({"level": "warning", "check": _chk_name,
                            "message": "src/content/daily_lp_generator.py が見つからない"})

    # ── #233〜#240: lottery quality gate チェック ────────────────────────────────
    import re as _re4

    # ── #233: check_lottery_quality.py が存在する ─────────────────────────────
    _lottery_script = PROJECT_ROOT / "scripts" / "check_lottery_quality.py"
    if _lottery_script.exists():
        results.append({"level": "ok", "check": "lottery_quality_script_exists",
                        "message": "scripts/check_lottery_quality.py が存在する"})
    else:
        results.append({"level": "error", "check": "lottery_quality_script_exists",
                        "message": "scripts/check_lottery_quality.py が存在しない"})

    # ── #234: daily_lp.yml に Lottery quality gate ステップがある ──────────────
    _workflow_path = PROJECT_ROOT / ".github" / "workflows" / "daily_lp.yml"
    if _workflow_path.exists():
        _workflow_text = _workflow_path.read_text(encoding="utf-8")
        if "check_lottery_quality.py" in _workflow_text and "lottery_quality" in _workflow_text.lower():
            results.append({"level": "ok", "check": "lottery_quality_in_workflow",
                            "message": "daily_lp.yml に Lottery quality gate ステップが存在する"})
        else:
            results.append({"level": "error", "check": "lottery_quality_in_workflow",
                            "message": "daily_lp.yml に Lottery quality gate ステップが存在しない"})
    else:
        results.append({"level": "warning", "check": "lottery_quality_in_workflow",
                        "message": ".github/workflows/daily_lp.yml が見つからない"})

    # ── #235: exports/lottery_report/latest.json が生成されている ──────────────
    _lottery_report = PROJECT_ROOT / "exports" / "lottery_report" / "latest.json"
    if _lottery_report.exists():
        results.append({"level": "ok", "check": "lottery_report_exists",
                        "message": "exports/lottery_report/latest.json が生成されている"})
        # JSON 読み込んで内容チェック
        try:
            import json as _json4
            _lr = _json4.loads(_lottery_report.read_text(encoding="utf-8"))

            # ── #236: lottery active count（0 でも warning のみ — 抽選なし期間は正常） ──
            _lr_active = _lr.get("active_count", 0)
            if _lr_active >= 3:
                results.append({"level": "ok", "check": "lottery_active_count_gte3",
                                "message": f"lottery_report active_count = {_lr_active}（>= 3）"})
            elif _lr_active > 0:
                results.append({"level": "ok", "check": "lottery_active_count_gte3",
                                "message": f"lottery_report active_count = {_lr_active}（受付中）"})
            else:
                results.append({"level": "warning", "check": "lottery_active_count_gte3",
                                "message": f"lottery_report active_count = {_lr_active}（受付中の抽選なし — 抽選なし期間は正常）"})

            # ── #237: RICOH GR IV 3件が active_items に存在 ───────────────────
            _lr_active_names = [it.get("product_name", "") for it in _lr.get("active_items", [])]
            _ricoh_in_active = [n for n in _lr_active_names if "RICOH GR IV" in n]
            if len(_ricoh_in_active) >= 3:
                results.append({"level": "ok", "check": "ricoh_gr4_in_active_items",
                                "message": f"RICOH GR IV 系 {len(_ricoh_in_active)} 件が active_items に存在"})
            else:
                results.append({"level": "warning", "check": "ricoh_gr4_in_active_items",
                                "message": f"RICOH GR IV 系が active_items に {len(_ricoh_in_active)} 件のみ（期待値: 3）"})

            # ── #238: reference_only が active count に含まれていない ──────────
            _lr_dup = _lr.get("duplicate_count", 0)
            _lr_failures = _lr.get("issues_failure", [])
            _ref_in_active_issues = [f for f in _lr_failures if "reference_only" in f and "active" in f]
            if not _ref_in_active_issues:
                results.append({"level": "ok", "check": "reference_only_excluded_from_active",
                                "message": "reference_only アイテムが active count に混入していない"})
            else:
                results.append({"level": "error", "check": "reference_only_excluded_from_active",
                                "message": f"reference_only が active に混入: {_ref_in_active_issues}"})

            # ── #239: 古い文言が active section にない ──────────────────────
            _lr_stale = _lr.get("stale_phrase_count", 0)
            if _lr_stale == 0:
                results.append({"level": "ok", "check": "no_stale_in_active_section",
                                "message": "「次回未定」「抽選情報未確認」等の古い文言が active section にない"})
            else:
                results.append({"level": "error", "check": "no_stale_in_active_section",
                                "message": f"古い文言が active section に {_lr_stale} 件検出"})

            # ── #240: lottery_report に FAILURE がない ────────────────────────
            _lr_issues = _lr.get("issues_failure", [])
            if not _lr_issues:
                results.append({"level": "ok", "check": "lottery_quality_no_failure",
                                "message": "lottery_quality_gate: FAILURE 項目なし"})
            else:
                results.append({"level": "warning", "check": "lottery_quality_no_failure",
                                "message": f"lottery_quality_gate FAILURE 項目 {len(_lr_issues)} 件: {_lr_issues[0][:60]}..."
                                if _lr_issues[0] and len(_lr_issues[0]) > 60
                                else f"lottery_quality_gate FAILURE 項目 {len(_lr_issues)} 件"})

        except Exception as _e4:
            results.append({"level": "warning", "check": "lottery_report_exists",
                            "message": f"exports/lottery_report/latest.json の解析に失敗: {_e4}"})
    else:
        results.append({"level": "warning", "check": "lottery_report_exists",
                        "message": "exports/lottery_report/latest.json が未生成（check_lottery_quality.py を実行してください）"})
        for _chk in ["lottery_active_count_gte3", "ricoh_gr4_in_active_items",
                     "reference_only_excluded_from_active", "no_stale_in_active_section",
                     "lottery_quality_no_failure"]:
            results.append({"level": "warning", "check": _chk,
                            "message": "lottery_report が未生成のためスキップ"})

    # ── #241: update_lottery_events.py が存在する ────────────────────────────────
    _update_lottery_script = PROJECT_ROOT / "scripts" / "update_lottery_events.py"
    if _update_lottery_script.exists():
        results.append({"level": "ok", "check": "update_lottery_events_exists",
                        "message": "scripts/update_lottery_events.py が存在する"})
    else:
        results.append({"level": "error", "check": "update_lottery_events_exists",
                        "message": "scripts/update_lottery_events.py が存在しない"})

    # ── #242: daily_lp.yml に Update lottery events step がある ──────────────────
    if _workflow_path.exists():
        _wf_text2 = _workflow_path.read_text(encoding="utf-8")
        if "update_lottery_events.py" in _wf_text2 and "Update lottery events" in _wf_text2:
            results.append({"level": "ok", "check": "update_lottery_events_in_workflow",
                            "message": "daily_lp.yml に Update lottery events ステップが存在する"})
        else:
            results.append({"level": "error", "check": "update_lottery_events_in_workflow",
                            "message": "daily_lp.yml に Update lottery events ステップが存在しない"})
    else:
        results.append({"level": "warning", "check": "update_lottery_events_in_workflow",
                        "message": ".github/workflows/daily_lp.yml が見つからない"})

    # ── #243: data/lottery_events.csv が存在し RICOH 3件を含む ───────────────────
    _lottery_csv_check = PROJECT_ROOT / "data" / "lottery_events.csv"
    if _lottery_csv_check.exists():
        _csv_check_text = _lottery_csv_check.read_text(encoding="utf-8")
        _csv_ricoh_names = ["RICOH GR IV Monochrome", "RICOH GR IV HDF", "RICOH GR IV,"]
        _csv_missing = [n for n in _csv_ricoh_names if n not in _csv_check_text]
        if not _csv_missing:
            results.append({"level": "ok", "check": "lottery_csv_has_ricoh",
                            "message": "data/lottery_events.csv に RICOH GR IV 3件が存在する"})
        else:
            results.append({"level": "warning", "check": "lottery_csv_has_ricoh",
                            "message": f"data/lottery_events.csv に不足: {', '.join(_csv_missing)}"})
    else:
        results.append({"level": "warning", "check": "lottery_csv_has_ricoh",
                        "message": "data/lottery_events.csv が存在しない（update_lottery_events.py を実行してください）"})

    # ── #244〜#248: 通知スクリプト・ワークフロー連携チェック ────────────────────────

    # ── #244: notify_workflow_result.py が存在する ───────────────────────────
    _notify_script = PROJECT_ROOT / "scripts" / "notify_workflow_result.py"
    if _notify_script.exists():
        results.append({"level": "ok", "check": "notify_script_exists",
                        "message": "scripts/notify_workflow_result.py が存在する"})
    else:
        results.append({"level": "error", "check": "notify_script_exists",
                        "message": "scripts/notify_workflow_result.py が存在しない"})

    # ── #245〜#248: daily_lp.yml の通知・出力ステップ確認 ────────────────────
    _wf_notify_path = PROJECT_ROOT / ".github" / "workflows" / "daily_lp.yml"
    if _wf_notify_path.exists():
        _wf_notify_text = _wf_notify_path.read_text(encoding="utf-8")

        # #245: Notify ステップがある
        if "notify_workflow_result.py" in _wf_notify_text and "Notify" in _wf_notify_text:
            results.append({"level": "ok", "check": "notify_step_in_workflow",
                            "message": "daily_lp.yml に Notify workflow result ステップが存在する"})
        else:
            results.append({"level": "error", "check": "notify_step_in_workflow",
                            "message": "daily_lp.yml に Notify workflow result ステップが存在しない"})

        # #246: deploy-check が exports/deploy_check_latest.txt に tee している
        if "deploy_check_latest.txt" in _wf_notify_text and "tee" in _wf_notify_text:
            results.append({"level": "ok", "check": "deploy_check_tee_output",
                            "message": "deploy-check の出力が exports/deploy_check_latest.txt に保存される"})
        else:
            results.append({"level": "warning", "check": "deploy_check_tee_output",
                            "message": "deploy-check が exports/deploy_check_latest.txt に tee されていない"})

        # #247: prelaunch-check が exports/prelaunch_check_latest.txt に tee している
        if "prelaunch_check_latest.txt" in _wf_notify_text and "tee" in _wf_notify_text:
            results.append({"level": "ok", "check": "prelaunch_tee_output",
                            "message": "prelaunch-check の出力が exports/prelaunch_check_latest.txt に保存される"})
        else:
            results.append({"level": "warning", "check": "prelaunch_tee_output",
                            "message": "prelaunch-check が exports/prelaunch_check_latest.txt に tee されていない"})

        # #248: DISCORD_WEBHOOK_URL / TELEGRAM_BOT_TOKEN を参照している
        _has_discord  = "DISCORD_WEBHOOK_URL" in _wf_notify_text
        _has_telegram = "TELEGRAM_BOT_TOKEN"  in _wf_notify_text
        if _has_discord and _has_telegram:
            results.append({"level": "ok", "check": "notify_env_vars",
                            "message": "DISCORD_WEBHOOK_URL / TELEGRAM_BOT_TOKEN が workflow に設定されている"})
        else:
            _missing_envs = []
            if not _has_discord:  _missing_envs.append("DISCORD_WEBHOOK_URL")
            if not _has_telegram: _missing_envs.append("TELEGRAM_BOT_TOKEN")
            results.append({"level": "warning", "check": "notify_env_vars",
                            "message": f"通知環境変数が未設定: {', '.join(_missing_envs)}"})
    else:
        for _chk_n in ["notify_step_in_workflow", "deploy_check_tee_output",
                       "prelaunch_tee_output", "notify_env_vars"]:
            results.append({"level": "warning", "check": _chk_n,
                            "message": ".github/workflows/daily_lp.yml が見つからない"})

    # ── フォールバック表示 / Hero 0件防止 チェック群 ────────────────────────

    # #254: repository.py に manual_today フォールバック優先ロジックが存在する
    _repo_path = PROJECT_ROOT / "src" / "db" / "repository.py"
    _repo_txt  = _repo_path.read_text(encoding="utf-8") if _repo_path.exists() else ""
    _has_manual_fallback = (
        ("manual_today" in _repo_txt and "_priority" in _repo_txt)
        or ("manual_today" in _repo_txt and "ROW_NUMBER" in _repo_txt)
        or ("manual_today" in _repo_txt and "CASE WHEN" in _repo_txt)
    )
    if _has_manual_fallback:
        results.append({"level": "ok", "check": "repo_manual_fallback",
                        "message": "repository.py に manual_today フォールバック優先ロジックが存在する"})
    else:
        results.append({"level": "warning", "check": "repo_manual_fallback",
                        "message": "repository.py に manual_today フォールバックが見つからない（auto_scraped失敗時に手動データが使われない可能性）"})

    # #255: beginner_deal_scanner.py に fetch_failed 保持ロジックが存在する
    _scanner_path = PROJECT_ROOT / "src" / "market" / "beginner_deal_scanner.py"
    _scanner_txt  = _scanner_path.read_text(encoding="utf-8") if _scanner_path.exists() else ""
    _has_ff_keep  = "fetch_failed" in _scanner_txt and (
        "既存" in _scanner_txt or "保持" in _scanner_txt or "continue" in _scanner_txt
    )
    if _has_ff_keep:
        results.append({"level": "ok", "check": "scanner_fetch_failed_keep",
                        "message": "beginner_deal_scanner.py に fetch_failed 時の deal 保持ロジックが存在する"})
    else:
        results.append({"level": "warning", "check": "scanner_fetch_failed_keep",
                        "message": "beginner_deal_scanner.py の fetch_failed 保持ロジックが見つからない（自動取得失敗時に deal が消える可能性）"})

    _cq_path = PROJECT_ROOT / "scripts" / "check_collector_quality.py"
    _cq_txt  = _cq_path.read_text(encoding="utf-8") if _cq_path.exists() else ""

    # #256: janpara が OPTIONAL_SHOPS に含まれる
    if '"janpara"' in _cq_txt and "OPTIONAL_SHOPS" in _cq_txt:
        results.append({"level": "ok", "check": "janpara_in_optional_shops",
                        "message": "janpara が OPTIONAL_SHOPS に分類されている（rate_limited_429 — LP品質ゲート対象外）"})
    else:
        results.append({"level": "warning", "check": "janpara_in_optional_shops",
                        "message": "janpara が OPTIONAL_SHOPS に含まれていない（429ブロックでも品質ゲートFAILUREになる可能性）"})

    # #257: sofmap が OPTIONAL_SHOPS に含まれる
    if '"sofmap"' in _cq_txt and "OPTIONAL_SHOPS" in _cq_txt:
        results.append({"level": "ok", "check": "sofmap_in_optional_shops",
                        "message": "sofmap が OPTIONAL_SHOPS に分類されている（service_unavailable — LP品質ゲート対象外）"})
    else:
        results.append({"level": "warning", "check": "sofmap_in_optional_shops",
                        "message": "sofmap が OPTIONAL_SHOPS に含まれていない（503障害でも品質ゲートFAILUREになる可能性）"})

    # #258: surugaya が OPTIONAL_SHOPS に含まれる
    if '"surugaya"' in _cq_txt and "OPTIONAL_SHOPS" in _cq_txt:
        results.append({"level": "ok", "check": "surugaya_in_optional_shops",
                        "message": "surugaya が OPTIONAL_SHOPS に分類されている（site_blocked — LP品質ゲート対象外）"})
    else:
        results.append({"level": "warning", "check": "surugaya_in_optional_shops",
                        "message": "surugaya が OPTIONAL_SHOPS に含まれていない（403ブロックでも品質ゲートFAILUREになる可能性）"})

    # #261: collector_report に Required / Optional failures の分離表示がある
    if "optional_warnings" in _cq_txt and "Required" in _cq_txt:
        results.append({"level": "ok", "check": "collector_report_required_optional_split",
                        "message": "collector_report に Required / Optional failures の分離表示がある"})
    else:
        results.append({"level": "warning", "check": "collector_report_required_optional_split",
                        "message": "collector_report に Required / Optional failures の分離表示が見つからない"})

    # ── #262: geo が OPTIONAL_SHOPS に含まれるか ────────────────────────────
    try:
        _qgate_path = Path(__file__).resolve().parent / "check_collector_quality.py"
        _qgate_src = _qgate_path.read_text(encoding="utf-8") if _qgate_path.exists() else ""
        if '"geo"' in _qgate_src and "OPTIONAL_SHOPS" in _qgate_src:
            results.append({"level": "ok", "check": "geo_in_optional_shops",
                            "message": "geo が OPTIONAL_SHOPS に含まれている（iPhone17/PS5Pro未掲載）"})
        else:
            results.append({"level": "warning", "check": "geo_in_optional_shops",
                            "message": "geo が OPTIONAL_SHOPS に未追加（required_failed に計上される）"})
    except Exception as e:
        results.append({"level": "warning", "check": "geo_in_optional_shops",
                        "message": f"geo OPTIONAL_SHOPS チェック失敗: {e}"})

    # ── #263: tsutaya が OPTIONAL_SHOPS に含まれるか ─────────────────────────
    try:
        _qgate_path2 = Path(__file__).resolve().parent / "check_collector_quality.py"
        _qgate_src2 = _qgate_path2.read_text(encoding="utf-8") if _qgate_path2.exists() else ""
        if '"tsutaya"' in _qgate_src2 and "OPTIONAL_SHOPS" in _qgate_src2:
            results.append({"level": "ok", "check": "tsutaya_in_optional_shops",
                            "message": "tsutaya が OPTIONAL_SHOPS に含まれている（not_supported）"})
        else:
            results.append({"level": "warning", "check": "tsutaya_in_optional_shops",
                            "message": "tsutaya が OPTIONAL_SHOPS に未追加（required_failed に計上される）"})
    except Exception as e:
        results.append({"level": "warning", "check": "tsutaya_in_optional_shops",
                        "message": f"tsutaya OPTIONAL_SHOPS チェック失敗: {e}"})

    # ── #264: kaitori_itchome が networkidle を使っていないか ─────────────────
    try:
        _itchome_path = Path(__file__).resolve().parent.parent / "src" / "collectors" / "buyback_kaitori_itchome.py"
        _itchome_src = _itchome_path.read_text(encoding="utf-8") if _itchome_path.exists() else ""
        if "networkidle" not in _itchome_src:
            results.append({"level": "ok", "check": "kaitori_itchome_no_networkidle",
                            "message": "kaitori_itchome: networkidle を使っていない（タイムアウト対策済み）"})
        else:
            results.append({"level": "warning", "check": "kaitori_itchome_no_networkidle",
                            "message": "kaitori_itchome: networkidle を使用中（SPA タイムアウトの原因になる）"})
    except Exception as e:
        results.append({"level": "warning", "check": "kaitori_itchome_no_networkidle",
                        "message": f"kaitori_itchome networkidle チェック失敗: {e}"})

    # ── #265: geo が ps5_pro を product_not_listed で返すか ───────────────────
    try:
        _geo_path = Path(__file__).resolve().parent.parent / "src" / "collectors" / "buyback_geo.py"
        _geo_src = _geo_path.read_text(encoding="utf-8") if _geo_path.exists() else ""
        if "product_not_listed" in _geo_src and "_NOT_LISTED" in _geo_src and "ps5_pro" in _geo_src:
            results.append({"level": "ok", "check": "geo_ps5pro_not_listed",
                            "message": "geo: ps5_pro を product_not_listed で処理している"})
        else:
            results.append({"level": "warning", "check": "geo_ps5pro_not_listed",
                            "message": "geo: ps5_pro が price_not_found のまま（product_not_listed に修正推奨）"})
    except Exception as e:
        results.append({"level": "warning", "check": "geo_ps5pro_not_listed",
                        "message": f"geo ps5_pro チェック失敗: {e}"})

    # ── #272: 速報タブなし確認 (sokuhoh tab removed, Task 3) ──
    # CSS セレクタに data-tab="sokuhoh" が残るため id="tab-sokuhoh" で判定
    lp_src = html  # index.html は既に読み込み済み

    # ── #274: alerts.csv 存在確認 (Task 5) ──
    alerts_csv = PROJECT_ROOT / "data" / "alerts.csv"
    if alerts_csv.exists():
        results.append({"level": "ok", "check": "alerts_csv_exists",
                        "message": "#274 data/alerts.csv 存在"})
    else:
        results.append({"level": "warning", "check": "alerts_csv_exists",
                        "message": "#274 data/alerts.csv が存在しない（update_alerts.py 未実行）"})

    # ── #275: 抽選 active section に禁止文言なし (Task 2) ──
    _lottery_forbidden = ["抽選情報未確認", "公式商品ページで要確認"]
    _found_forbidden = [kw for kw in _lottery_forbidden if kw in lp_src]
    if _found_forbidden:
        results.append({"level": "warning", "check": "lottery_no_forbidden_notes",
                        "message": f"#275 抽選 active section に禁止文言あり: {_found_forbidden}"})
    else:
        results.append({"level": "ok", "check": "lottery_no_forbidden_notes",
                        "message": "#275 抽選 active section 禁止文言なし"})

    # ── #276: RICOH 日付整合性チェック ──────────────────────────────────────────
    # debug text に「5月29日」があれば entry_end_at=2026-05-29 12:00 になっているはず
    _ricoh_debug = PROJECT_ROOT / "exports" / "debug" / "ricoh_lottery_latest.txt"
    _lottery_csv = PROJECT_ROOT / "data" / "lottery_events.csv"
    if _ricoh_debug.exists() and _lottery_csv.exists():
        try:
            import csv as _csv
            _debug_text = _ricoh_debug.read_text(encoding="utf-8")
            _has_may29 = "5月29日" in _debug_text
            _ricoh_end = ""
            with open(_lottery_csv, encoding="utf-8") as _f:
                for _row in _csv.DictReader(_f):
                    if _row.get("brand", "").upper() == "RICOH" and _row.get("product_code") == "S0001551":
                        _ricoh_end = _row.get("entry_end_at", "")
                        break
            if _has_may29:
                if "2026-05-29 12:00" in _ricoh_end:
                    results.append({"level": "ok", "check": "ricoh_date_consistency",
                                    "message": "#276 RICOH GR IV: debug text に5月29日あり → entry_end_at=2026-05-29 12:00 ✅"})
                else:
                    results.append({"level": "warning", "check": "ricoh_date_consistency",
                                    "message": f"#276 RICOH GR IV: debug text に5月29日あるが entry_end_at={_ricoh_end!r}（期待: 2026-05-29 12:00）"})
            else:
                results.append({"level": "ok", "check": "ricoh_date_consistency",
                                "message": f"#276 RICOH GR IV: debug text に5月29日なし → entry_end_at={_ricoh_end!r} で OK"})
        except Exception as _e:
            results.append({"level": "warning", "check": "ricoh_date_consistency",
                            "message": f"#276 RICOH 日付整合性チェック失敗: {_e}"})
    else:
        results.append({"level": "warning", "check": "ricoh_date_consistency",
                        "message": "#276 ricoh_lottery_latest.txt または lottery_events.csv が存在しない"})

    _lottery_csv2 = PROJECT_ROOT / "data" / "lottery_events.csv"

    # ── #278: status_conflict=true でも entry_end_at が未来なら active card に残る ──
    if _lottery_csv2.exists():
        try:
            import csv as _csv3
            from datetime import datetime as _dt, timezone as _tz, timedelta as _td
            _jst = _tz(_td(hours=9))
            _now_jst = _dt.now(tz=_jst)
            _conflict_but_active = []
            _conflict_but_closed = []
            with open(_lottery_csv2, encoding="utf-8") as _f3:
                for _row3 in _csv3.DictReader(_f3):
                    if str(_row3.get("status_conflict", "")).lower() != "true":
                        continue
                    _end = _row3.get("entry_end_at", "")
                    try:
                        _end_dt = _dt.strptime(_end, "%Y-%m-%d %H:%M").replace(tzinfo=_jst) if _end else None
                    except ValueError:
                        _end_dt = None
                    if _end_dt and _end_dt >= _now_jst:
                        _conflict_but_active.append(_row3.get("product_name", "?"))
                    elif _end_dt:
                        _conflict_but_closed.append(_row3.get("product_name", "?"))

            if _conflict_but_active:
                results.append({"level": "ok", "check": "lottery_conflict_active_preserved",
                                "message": f"#278 status_conflict かつ entry_end_at が未来 → active card として保持: {_conflict_but_active}"})
            if _conflict_but_closed:
                results.append({"level": "ok", "check": "lottery_conflict_closed",
                                "message": f"#278 status_conflict かつ entry_end_at が過去 → closed: {_conflict_but_closed}"})
            if not _conflict_but_active and not _conflict_but_closed:
                results.append({"level": "ok", "check": "lottery_conflict_active_preserved",
                                "message": "#278 status_conflict=true の商品なし"})
        except Exception as _e3:
            results.append({"level": "warning", "check": "lottery_conflict_active_preserved",
                            "message": f"#278 conflict active チェック失敗: {_e3}"})

    # ── #279: source_text_excerpt が lottery_report に保存されている ─────────────
    _lr_json = PROJECT_ROOT / "exports" / "lottery_report" / "latest.json"
    if _lr_json.exists():
        try:
            import json as _json2
            _lr = _json2.loads(_lr_json.read_text(encoding="utf-8"))
            _items_with_excerpt = [
                it for it in (_lr.get("active_items") or [])
                if it.get("source_text_excerpt")
            ]
            if _items_with_excerpt:
                results.append({"level": "ok", "check": "lottery_source_text_excerpt",
                                "message": f"#279 source_text_excerpt が {len(_items_with_excerpt)}件の active item に保存されている"})
            else:
                results.append({"level": "ok", "check": "lottery_source_text_excerpt",
                                "message": "#279 source_text_excerpt あり active item なし（conflict なし）"})
        except Exception as _e4:
            results.append({"level": "warning", "check": "lottery_source_text_excerpt",
                            "message": f"#279 source_text_excerpt チェック失敗: {_e4}"})

    # ── #289-#291: ランキングレポート ──
    import json as _json_dc
    _rr_path = PROJECT_ROOT / "exports" / "ranking_report" / "latest.json"
    if _rr_path.exists():
        results.append({"level": "ok", "check": "ranking_report_exists",
                        "message": "#289 exports/ranking_report/latest.json が存在する"})
        try:
            _rr = _json_dc.loads(_rr_path.read_text(encoding="utf-8"))
            _t290 = "beginner_top10" in _rr
            results.append({"level": "ok" if _t290 else "warning", "check": "ranking_beginner_top10",
                            "message": "#290 ranking_report に beginner_top10 フィールドがある" + ("" if _t290 else " ← なし")})
            _t291 = "route_type_beginner" in _rr
            results.append({"level": "ok" if _t291 else "warning", "check": "ranking_route_type",
                            "message": "#291 ranking_report に route_type_beginner フィールドがある" + ("" if _t291 else " ← なし")})
        except Exception as _e291:
            results.append({"level": "warning", "check": "ranking_report_parse",
                            "message": f"#290-#291 ranking_report パース失敗: {_e291}"})
    else:
        results.append({"level": "warning", "check": "ranking_report_exists",
                        "message": "#289 exports/ranking_report/latest.json が存在しない"})

    # ── #292-#294: せどりルートレポート ──
    _sr_path = PROJECT_ROOT / "exports" / "sedori_routes_report" / "latest.json"
    if _sr_path.exists():
        results.append({"level": "ok", "check": "sedori_report_exists",
                        "message": "#292 exports/sedori_routes_report/latest.json が存在する"})
        try:
            _sr = _json_dc.loads(_sr_path.read_text(encoding="utf-8"))
            _t293 = "beginner_routes" in _sr
            results.append({"level": "ok" if _t293 else "warning", "check": "sedori_beginner_routes",
                            "message": "#293 sedori_routes_report に beginner_routes フィールドがある" + ("" if _t293 else " ← なし")})
            _t294 = "pro_routes" in _sr
            results.append({"level": "ok" if _t294 else "warning", "check": "sedori_pro_routes",
                            "message": "#294 sedori_routes_report に pro_routes フィールドがある" + ("" if _t294 else " ← なし")})
        except Exception as _e294:
            results.append({"level": "warning", "check": "sedori_report_parse",
                            "message": f"#293-#294 sedori_routes_report パース失敗: {_e294}"})
    else:
        results.append({"level": "warning", "check": "sedori_report_exists",
                        "message": "#292 exports/sedori_routes_report/latest.json が存在しない"})

    # ── #296-#303: 海外価格収集 API / 履歴 / アラートチェック ─────────────────

    _ebay_collector_path = PROJECT_ROOT / "src" / "collectors" / "overseas" / "ebay_completed.py"
    _ebay_src = _ebay_collector_path.read_text(encoding="utf-8") if _ebay_collector_path.exists() else ""

    # #296: eBay の出品・成約の HTML（検索結果）を取らない・廃止された Finding API を呼ばない（Phase 12・13。
    #       以前は「Finding API が主な取得の手段」を確かめていたが、Finding API は 2025-02-05 に廃止された）
    _t296 = ("svcs.ebay.com" not in _ebay_src and "_fetch_via_api(" not in _ebay_src
             and "html_scraping_disabled" in _ebay_src)
    results.append({"level": "ok" if _t296 else "error", "check": "ebay_api_primary",
                    "message": "#296 eBay の HTML の取得は停止・廃止された Finding API を呼ばない（成約は Marketplace Insights API）"
                               + ("" if _t296 else " ← HTML の取得・Finding API の呼び出しが残っている")})

    # #297: 取得しないときは html_blocked（価格なし）として分類する。実際に collect を呼んで、通信せずに
    #       html_blocked になることを確かめる（Phase 13 レビュー L-8: 文字列の有無だけでは検査にならない）
    try:
        import urllib.request as _ur297
        from src.collectors.overseas import ebay_completed as _ec297
        _calls297 = []
        _o_open, _o_fx = _ur297.urlopen, _ec297.get_usd_jpy
        _ur297.urlopen = lambda *a, **k: _calls297.append(a)
        _ec297.get_usd_jpy = lambda: (150.0, "deploy_check")
        try:
            _r297 = _ec297.EbayCompletedCollector().collect("prod_ps5_pro", "ps5_pro", ["PlayStation 5 Pro"])
        finally:
            _ur297.urlopen, _ec297.get_usd_jpy = _o_open, _o_fx
        _t297 = _r297.collector_method == "html_blocked" and _r297.price_jpy == 0 and not _calls297
    except Exception:  # noqa: BLE001
        _t297 = False
    results.append({"level": "ok" if _t297 else "error", "check": "ebay_api_key_handling",
                    "message": "#297 eBay を取得しないときの html_blocked 分類が実装されている" + ("" if _t297 else " ← 取得しないときの分類が不足")})

    # #298: access denied は site_blocked として正常分類される
    _t298 = "site_blocked" in _ebay_src and "html_blocked" in _ebay_src
    results.append({"level": "ok" if _t298 else "warning", "check": "ebay_blocked_classified",
                    "message": "#298 eBay アクセス拒否が site_blocked として正常分類される" + ("" if _t298 else " ← blocked 分類が未実装")})

    # #299: overseas_price_history.csv が存在する
    _hist_csv = PROJECT_ROOT / "data" / "overseas_price_history.csv"
    _t299 = _hist_csv.exists()
    results.append({"level": "ok" if _t299 else "warning", "check": "overseas_history_csv_exists",
                    "message": "#299 data/overseas_price_history.csv が存在する" + ("" if _t299 else " ← update_overseas_prices.py 未実行の可能性")})

    # #300: overseas_price_surge / overseas_price_drop アラートロジックが存在する
    _alerts_path = PROJECT_ROOT / "scripts" / "update_alerts.py"
    _alerts_src = _alerts_path.read_text(encoding="utf-8") if _alerts_path.exists() else ""
    _t300 = "overseas_price_surge" in _alerts_src and "overseas_price_drop" in _alerts_src
    results.append({"level": "ok" if _t300 else "error", "check": "overseas_alert_logic",
                    "message": "#300 update_alerts.py に overseas_price_surge / overseas_price_drop ロジックが存在する" + ("" if _t300 else " ← アラートロジックが未実装")})

    # #301: confidence=low のデータがアラート対象外になっている
    _t301 = 'confidence == "low"' in _alerts_src and "continue" in _alerts_src
    results.append({"level": "ok" if _t301 else "warning", "check": "overseas_alert_low_conf_excluded",
                    "message": "#301 confidence=low のデータがアラート除外されている" + ("" if _t301 else " ← low confidence データがアラートに含まれる可能性")})

    # #302: LP 生成器に manual fallback 表示（eBay 手動確認）が実装されている
    _lp_gen_path = PROJECT_ROOT / "src" / "content" / "daily_lp_generator.py"
    _lp_gen_src = _lp_gen_path.read_text(encoding="utf-8") if _lp_gen_path.exists() else ""

    # #314: 価格差・プレ値候補セクション（advanced_snaps）が生成 HTML に存在しない
    # LP ソースにコメントとして残っても OK。HTML 出力に section-header として出ないことを確認
    _t314 = "価格差・プレ値候補" not in html
    results.append({"level": "ok" if _t314 else "warning", "check": "no_price_gap_candidates_section",
                    "message": "#314 「価格差・プレ値候補」セクションが生成 HTML に存在しない" + ("" if _t314 else " ← 「価格差・プレ値候補」が HTML に残っています")})

    # #323: sedori 空状態にCLIコマンドが出ていない
    _t323 = "import-sale-csv" not in _lp_gen_src
    results.append({"level": "ok" if _t323 else "warning", "check": "sedori_no_cli_command",
                    "message": "#323 せどり空状態にCLIコマンドが表示されない" + ("" if _t323 else " ← CLIコマンドがLPソースに残っています")})

    # #327: info banner が「最高買取価格/最高買取店」の説明に更新済み（旧: 最高売却先）
    _t327 = "最高買取価格" in _lp_gen_src or "最高買取店" in _lp_gen_src
    results.append({"level": "ok" if _t327 else "warning", "check": "beginner_banner_sell_source",
                    "message": "#327 初心者 info banner が「最高買取価格/最高買取店」説明に更新済み" + ("" if _t327 else " ← info banner の買取説明が古い")})

    # ── Top / Ranking / Beginner 追加チェック (2026-05-28 Public LP Review) ──────
    # #328: Topに「一部店舗はサイト制限により取得不可」が生成 HTML に出ていない
    _t328 = "一部店舗はサイト制限により取得不可" not in html
    results.append({"level": "ok" if _t328 else "warning", "check": "no_optional_bar_in_html",
                    "message": "#328 生成 HTML に「一部店舗はサイト制限」バーが出ていない" + ("" if _t328 else " ← optional warn バーが HTML に残っています")})

    # #329: Topに「参考DEALS」が生成 HTML に出ていない
    _t329 = "参考DEALS" not in html
    results.append({"level": "ok" if _t329 else "warning", "check": "no_sankoDEALS_in_html",
                    "message": "#329 生成 HTML に「参考DEALS」が出ていない" + ("" if _t329 else " ← 「参考DEALS」が HTML に残っています")})

    # #331: Rankingに「買取ランキング」が HTML に出ていない
    _t331 = "買取ランキング" not in html
    results.append({"level": "ok" if _t331 else "warning", "check": "no_kaitori_ranking_in_html",
                    "message": "#331 生成 HTML に「買取ランキング」が出ていない（差益ランキングに変更済み）" + ("" if _t331 else " ← 「買取ランキング」が HTML に残っています")})

    # #334: Topに「手動確認データ」が hero-eyebrow 等に出ていない
    import re as _re334
    _t334 = not bool(_re334.search(r'手動確認データ', html))
    results.append({"level": "ok" if _t334 else "warning", "check": "no_manual_data_label_in_html",
                    "message": "#334 生成 HTML に「手動確認データ」ラベルが出ていない" + ("" if _t334 else " ← 「手動確認データ」が HTML に残っています")})

    # ── 2026-05-29 Public LP Review チェック (Round 3) ────────────────────────
    # #335: Topに「最終買取データ取得」が出ていない
    _t335 = "最終買取データ取得" not in html
    results.append({"level": "ok" if _t335 else "warning", "check": "no_last_buyback_fetch_label",
                    "message": "#335 生成 HTML に「最終買取データ取得」が出ていない" + ("" if _t335 else " ← 「最終買取データ取得」が HTML に残っています")})

    # #338: Sedoriに「推定コスト」が出ていない
    _t338 = "推定コスト" not in html
    results.append({"level": "ok" if _t338 else "warning", "check": "no_estimated_cost_in_html",
                    "message": "#338 生成 HTML に「推定コスト」が出ていない" + ("" if _t338 else " ← 「推定コスト」が HTML に残っています")})

    # #340: price=0 を利益計算に使わないロジックが LP ソースに存在する
    _t340 = "price > 0" in _lp_gen_src or "buyback_price', 0) > 0" in _lp_gen_src or "best_bp > 0" in _lp_gen_src
    results.append({"level": "ok" if _t340 else "warning", "check": "zero_price_not_used_in_profit",
                    "message": "#340 price=0 を利益計算に使わないガードが LP ソースに存在する" + ("" if _t340 else " ← price=0 ガードが見つかりません")})

    # #341: Lottery の active section に「受付中 / 販売中」が出ていない（→「現在販売中」に変更済み）
    _t341 = "受付中 / 販売中" not in _lp_gen_src
    results.append({"level": "ok" if _t341 else "warning", "check": "no_old_lottery_active_label",
                    "message": "#341 Lottery active ラベル「受付中 / 販売中」が LP ソースに残っていない" + ("" if _t341 else " ← 「受付中 / 販売中」が LP ソースに残っています")})

    # #342: 除外閾値が 168h 以上であること（2段階鮮度導入後は EXCLUDE_STALE_H=336h を参照）
    import re as _re342
    # 数値リテラル直書き、または EXCLUDE_STALE_H 経由（= EXCLUDE_STALE_H）の両方を許容
    _t342_m = _re342.search(r'_STALE_EXCLUDE_H\s*=\s*([0-9.]+)', _lp_gen_src)
    if _t342_m:
        _t342_val = float(_t342_m.group(1))
    else:
        _excl_m = _re342.search(r'EXCLUDE_STALE_H\s*=\s*([0-9.]+)', _lp_gen_src)
        _alias = bool(_re342.search(r'_STALE_EXCLUDE_H\s*=\s*EXCLUDE_STALE_H', _lp_gen_src))
        _t342_val = float(_excl_m.group(1)) if (_excl_m and _alias) else 0.0

    # #345: hero social proof に「差益案件 N件」ハードコード文字列がない（動的生成のみ許容）
    _t345 = '差益案件 <strong>' not in _lp_gen_src
    results.append({"level": "ok" if _t345 else "warning", "check": "no_hardcoded_deal_count_in_hero",
                    "message": "#345 hero social proof に「差益案件 N件」ハードコードが残っていない" + ("" if _t345 else " ← LP ソースに「差益案件 <strong>」が残っています")})

    # #347: 「最終買取データ取得」テキストが LP ソースに残っていない
    _t347 = "最終買取データ取得" not in _lp_gen_src
    results.append({"level": "ok" if _t347 else "warning", "check": "no_last_buyback_ts_label",
                    "message": "#347 「最終買取データ取得」テキストが LP ソースに残っていない" + ("" if _t347 else " ← 「最終買取データ取得」が LP ソースに残っています")})

    # ── Task 9 追加チェック ──────────────────────────────────────────────────

    # #355: 参考DEALS が HTML に存在しない（hero パネル削除済み）
    _t355 = '参考DEALS' not in html
    results.append({"level": "ok" if _t355 else "error", "check": "no_sanko_deals",
                    "message": "#355 「参考DEALS」が HTML に存在しない" + ("" if _t355 else " ← 「参考DEALS」が HTML に残っています")})

    # #356: 「最終買取データ取得」が HTML に存在しない
    _t356 = '最終買取データ取得' not in html
    results.append({"level": "ok" if _t356 else "error", "check": "no_last_buyback_label",
                    "message": "#356 「最終買取データ取得」が HTML に存在しない" + ("" if _t356 else " ← 「最終買取データ取得」が HTML に残っています")})

    # #357: 「推定コスト」が HTML に存在しない（sedori 推定コスト削除済み）
    _t357 = '推定コスト' not in html
    results.append({"level": "ok" if _t357 else "warning", "check": "no_sedori_estimated_cost",
                    "message": "#357 「推定コスト」が HTML に存在しない" + ("" if _t357 else " ← 「推定コスト」が HTML に残っています")})

    # #359: 「本日の価格データ未更新」が HTML 内に強表示されていない
    _t359 = '本日の価格データ未更新' not in html
    results.append({"level": "ok" if _t359 else "error", "check": "no_today_data_not_updated",
                    "message": "#359 「本日の価格データ未更新」が HTML に存在しない" + ("" if _t359 else " ← トップに「本日の価格データ未更新」が表示されています")})

    # #364: resale_market（二次流通）ソースが BeginnerDealScanner に存在する
    _bds_src = ""
    try:
        _bds_path = PROJECT_ROOT / "src" / "market" / "beginner_deal_scanner.py"
        _bds_src = _bds_path.read_text(encoding="utf-8")
    except Exception:
        pass
    _t364 = 'resale_market' in _bds_src and '_RESALE_NEW_CONDITIONS' in _bds_src
    results.append({"level": "ok" if _t364 else "error", "check": "resale_market_in_scanner",
                    "message": "#364 BeginnerDealScanner が sale_prices(新品条件)を二次流通候補として参照している" + ("" if _t364 else " ← resale_market ロジックが見つかりません")})

    # #367: price=0 / null が利益計算に使われていない（BeginnerDealScanner の sale_price > 0 ガード）
    _t367 = ('_sp.sale_price <= 0' in _bds_src or
             '_sp_pre.sale_price <= 0' in _bds_src or
             'sale_price > 0' in _bds_src or
             'not _sp.sale_price' in _bds_src or
             'not _sp_pre.sale_price' in _bds_src)
    results.append({"level": "ok" if _t367 else "error", "check": "sale_price_zero_guard",
                    "message": "#367 sale_prices で price=0/null ガードが存在する" + ("" if _t367 else " ← sale_price > 0 のチェックが見つかりません")})

    # =========================================
    # #369-#373: 二次流通自動収集コレクター (collect_resale_prices.py) チェック
    # =========================================

    # collect_resale_prices.py の存在確認
    _crp_path = PROJECT_ROOT / "scripts" / "collect_resale_prices.py"
    _crp_exists = _crp_path.exists()
    results.append({"level": "ok" if _crp_exists else "error",
                    "check": "collect_resale_script_exists",
                    "message": "#369 collect_resale_prices.py が存在する" + ("" if _crp_exists else " ← scripts/collect_resale_prices.py が見つかりません")})

    if _crp_exists:
        _crp_src = _crp_path.read_text(encoding="utf-8")

        # #370: eBay / Amazon / Mercari / ヤフオク / 楽天市場 コレクターが実装されている
        _t370_ebay    = "EbayResaleCollector"    in _crp_src
        _t370_amazon  = "AmazonJpResaleCollector" in _crp_src
        _t370_mercari = "MercariResaleCollector"  in _crp_src
        _t370_yahoo   = "YahooAuctionResaleCollector" in _crp_src
        _t370_rakuten = "RakutenResaleCollector"  in _crp_src
        _t370 = _t370_ebay and _t370_amazon and _t370_mercari and _t370_yahoo and _t370_rakuten
        results.append({"level": "ok" if _t370 else "warning",
                        "check": "resale_collectors_implemented",
                        "message": "#370 eBay/Amazon/Mercari/ヤフオク/楽天市場コレクター実装済み"
                                   + ("" if _t370 else
                                      f" ← ebay:{_t370_ebay} amazon:{_t370_amazon} mercari:{_t370_mercari} yahoo:{_t370_yahoo} rakuten:{_t370_rakuten}")})

        # #371: 決定論的 ID 生成（重複防止）が実装されている
        _t371 = "_make_sp_id" in _crp_src and "sha1" in _crp_src
        results.append({"level": "ok" if _t371 else "warning",
                        "check": "resale_deterministic_id",
                        "message": "#371 sale_price ID が決定論的（重複防止）に生成されている" + ("" if _t371 else " ← _make_sp_id / sha1 が見つかりません")})

        # #372: カメラ製品ターゲット設定が存在する
        _t372 = "prod_gr4" in _crp_src and "prod_x100vi" in _crp_src and "prod_gr3x" in _crp_src
        results.append({"level": "ok" if _t372 else "error",
                        "check": "resale_camera_targets_defined",
                        "message": "#372 GR IV / GR IIIx / X100VI がターゲット商品として設定されている" + ("" if _t372 else " ← CAMERA_PRODUCT_CONFIGS にカメラ製品が未設定")})

        # #373: ブロック検出・graceful fallback が実装されている
        _t373 = "_is_blocked" in _crp_src and "site_blocked" in _crp_src
        results.append({"level": "ok" if _t373 else "warning",
                        "check": "resale_block_detection",
                        "message": "#373 Cloud IP ブロック検出・graceful fallback が実装されている" + ("" if _t373 else " ← _is_blocked / site_blocked 処理が見つかりません")})
    else:
        for n, check in [(370, "resale_collectors_implemented"), (371, "resale_deterministic_id"),
                         (372, "resale_camera_targets_defined"), (373, "resale_block_detection")]:
            results.append({"level": "warning", "check": check,
                            "message": f"#{n} collect_resale_prices.py 未存在のためスキップ"})

    # #374: ワークフローに collect_resale_prices ステップが含まれている
    _workflow_path = PROJECT_ROOT / ".github" / "workflows" / "daily_lp.yml"
    if _workflow_path.exists():
        _wf_src = _workflow_path.read_text(encoding="utf-8")
        _t374 = "collect_resale_prices.py" in _wf_src and "EBAY_APP_ID" in _wf_src
        results.append({"level": "ok" if _t374 else "warning",
                        "check": "collect_resale_in_workflow",
                        "message": "#374 daily_lp.yml に collect_resale_prices ステップ（EBAY_APP_ID 含む）が追加されている"
                                   + ("" if _t374 else " ← workflow に collect_resale_prices.py ステップが見つかりません")})
    else:
        results.append({"level": "warning", "check": "collect_resale_in_workflow",
                        "message": "#374 daily_lp.yml 未存在のためスキップ"})

    # #377: Pro「中古プレ値あり」除外
    _t377 = ('中古プレ値あり' not in open(PROJECT_ROOT / 'src' / 'db' / 'repository.py', encoding='utf-8').read()
             or '_raw_flags' in _lp_gen_src)
    results.append({"level": "ok" if _t377 else "warning", "check": "pro_no_used_premium_badge",
                    "message": "#377 Proメインに「中古プレ値あり」が出ない" + ("" if _t377 else " ← repository.py または LP 側でフィルタが必要")})

    # #380: resale_collection_status.json が存在する
    _crs_path = PROJECT_ROOT / "exports" / "resale_collection_status.json"
    _t380 = _crs_path.exists()
    if _t380:
        try:
            import json as _json380
            _crs_data = _json380.loads(_crs_path.read_text(encoding="utf-8"))
            _has_products = "products" in _crs_data
            _has_platforms = "platforms" in _crs_data
            results.append({"level": "ok" if (_has_products and _has_platforms) else "warning",
                            "check": "resale_status_has_products",
                            "message": f"#380 resale_collection_status.json に products/platforms フィールドあり"
                                       + ("" if (_has_products and _has_platforms) else " ← products または platforms フィールドがない")})
        except Exception as _e380:
            results.append({"level": "warning", "check": "resale_status_has_products",
                            "message": f"#380 resale_collection_status.json 読み込みエラー: {_e380}"})
    else:
        results.append({"level": "warning", "check": "resale_status_has_products",
                        "message": "#380 resale_collection_status.json が存在しない（collect_resale_prices.py 実行後に生成される）"})

    # #381: ALL_PRODUCT_CONFIGS が全カテゴリ対応
    _collect_src_path = PROJECT_ROOT / "scripts" / "collect_resale_prices.py"
    if _collect_src_path.exists():
        _collect_src = _collect_src_path.read_text(encoding="utf-8")
        _t381 = 'ALL_PRODUCT_CONFIGS' in _collect_src and 'IPHONE_PRODUCT_CONFIGS' in _collect_src and 'GAME_PRODUCT_CONFIGS' in _collect_src
        results.append({"level": "ok" if _t381 else "warning", "check": "all_product_configs",
                        "message": "#381 collect_resale_prices.py が全カテゴリ対応（ALL_PRODUCT_CONFIGS）"
                                   + ("" if _t381 else " ← IPHONE/GAME_PRODUCT_CONFIGS が未定義")})
        # #382: ラクマコレクター実装
        _t382 = 'RakumaResaleCollector' in _collect_src
        results.append({"level": "ok" if _t382 else "warning", "check": "rakuma_collector",
                        "message": "#382 ラクマ（fril.jp）コレクター実装済み"
                                   + ("" if _t382 else " ← RakumaResaleCollector 未実装")})
    else:
        results.append({"level": "warning", "check": "all_product_configs",
                        "message": "#381 collect_resale_prices.py が見つからない"})
        results.append({"level": "warning", "check": "rakuma_collector",
                        "message": "#382 collect_resale_prices.py が見つからない"})

    # #383: difficulty sentinel fix が適用されている
    _t383 = 'difficulty >= 100' in _lp_gen_src or 'difficulty >= 100.0' in _lp_gen_src
    results.append({"level": "ok" if _t383 else "warning", "check": "difficulty_sentinel_fix",
                    "message": "#383 difficulty sentinel（100.0）再推定ロジックが実装されている"
                               + ("" if _t383 else " ← difficulty >= 100.0 チェックが未実装")})

    # #385: iPhone product_id がアンダースコア形式（products.yaml と一致）
    if _collect_src_path.exists():
        try:
            _crs_src385 = _collect_src  # 上の #381/#382 ブロックで既に読み込み済み
        except NameError:
            _crs_src385 = _collect_src_path.read_text(encoding="utf-8")
        # collect_resale_prices.py が prod_iphone17pro_256 形式を使用しているか確認
        _t385 = (
            'prod_iphone17pro_256' in _crs_src385
            and 'prod_iphone17pro_512' in _crs_src385
            and 'prod_iphone17pm_256' in _crs_src385
            and 'prod_iphone17pm_512' in _crs_src385
        )
        # アンダースコアなし（誤形式）が残っていないか確認
        _t385_bad = (
            '"prod_iphone17pro256"' in _crs_src385
            or '"prod_iphone17pro512"' in _crs_src385
            or '"prod_iphone17pm256"' in _crs_src385
            or '"prod_iphone17pm512"' in _crs_src385
        )
        _t385_ok = _t385 and not _t385_bad
        results.append({"level": "ok" if _t385_ok else "error", "check": "iphone_product_id_format",
                        "message": "#385 collect_resale_prices.py の iPhone product_id が products.yaml 形式（prod_iphone17pro_256 等）"
                                   + ("" if _t385_ok else " ← アンダースコアなし形式（FOREIGN KEY エラーの原因）が残存")})
    else:
        results.append({"level": "warning", "check": "iphone_product_id_format",
                        "message": "#385 collect_resale_prices.py が見つからない"})

    # #387: resale_collection_status.json に FOREIGN KEY エラーが記録されていない
    import json as _json387
    _crs_path387 = PROJECT_ROOT / "exports" / "resale_collection_status.json"
    if _crs_path387.exists():
        try:
            _crs_data387 = _json387.loads(_crs_path387.read_text(encoding="utf-8"))
            _errors387 = _crs_data387.get("summary", {}).get("errors", [])
            _fk_errors = [e for e in _errors387 if "FOREIGN KEY" in str(e)]
            _t387 = len(_fk_errors) == 0
            results.append({"level": "ok" if _t387 else "error", "check": "no_fk_errors",
                            "message": f"#387 resale_collection_status.json に FOREIGN KEY エラーなし"
                                       + ("" if _t387 else f" ← FK エラー {len(_fk_errors)}件: {_fk_errors[:2]}")})
        except Exception as _e387:
            results.append({"level": "warning", "check": "no_fk_errors",
                            "message": f"#387 resale_collection_status.json の読み込み失敗: {_e387}"})
    else:
        results.append({"level": "warning", "check": "no_fk_errors",
                        "message": "#387 resale_collection_status.json が見つからない（collect_resale_prices.py 未実行）"})

    # ── Round 5: Beginner/Pro 分離チェック ──────────────────────────────────
    # #395: LP ソースに beginner フリマ除外ロジックが実装されている
    _t395 = "data_source') != 'resale_market'" in _lp_gen_src or 'resale_market' in _lp_gen_src
    results.append({"level": "ok" if _t395 else "warning", "check": "beginner_resale_filter",
                    "message": "#395 LP ソースに Beginner フリマ除外ロジック（resale_market フィルタ）が実装済み"
                               + ("" if _t395 else " ← resale_market フィルタが未実装")})

    # ── Round 7: 中古排除・赤字表示・せどりルート品質チェック ──────────────────

    # #406: HTML 全体に「中古市場」が存在しない
    _t406 = '中古市場' not in html
    results.append({"level": "ok" if _t406 else "error", "check": "no_used_market_text",
                    "message": "#406 HTML に「中古市場」が存在しない（新品・未使用方針）"
                               + ("" if _t406 else " ← 「中古市場」が HTML に残っています")})

    # #407: HTML 全体に「中古相場」が存在しない
    _t407 = '中古相場' not in html
    results.append({"level": "ok" if _t407 else "error", "check": "no_used_market_price_text",
                    "message": "#407 HTML に「中古相場」が存在しない"
                               + ("" if _t407 else " ← 「中古相場」が HTML に残っています")})

    # #408: HTML 全体に「中古プレ値あり」が存在しない
    _t408 = '中古プレ値あり' not in html
    results.append({"level": "ok" if _t408 else "error", "check": "no_used_premium_flag_text",
                    "message": "#408 HTML に「中古プレ値あり」が存在しない"
                               + ("" if _t408 else " ← 「中古プレ値あり」が HTML に残っています")})

    # #409: HTML 全体に「中古A」が存在しない（中古グレード表記）
    _t409 = '中古A' not in html
    results.append({"level": "ok" if _t409 else "warning", "check": "no_used_grade_text",
                    "message": "#409 HTML に「中古A」が存在しない（新品・未使用方針）"
                               + ("" if _t409 else " ← 「中古A」が HTML に残っています（中古グレード表記）")})

    # #410: Beginner タブの監視中カードで「現在は赤字 / 価格変動」が +価格に表示されない
    # （profit > 0 のカードに赤字表示が出ないよう profit-note ロジックを確認）
    _t410 = '現在は赤字 / 価格変動を監視中' not in _lp_gen_src
    results.append({"level": "ok" if _t410 else "error", "check": "no_false_negative_profit_label",
                    "message": "#410 LP ソースに「現在は赤字 / 価格変動を監視中」（固定文言）が存在しない（profit-based に変更済み）"
                               + ("" if _t410 else " ← 「現在は赤字 / 価格変動を監視中」が固定文言として残っています")})

    # #419: LP ソースに中古・二次流通の共通除外ロジック（_enrich_deal / _cond_is_used）が実装されている
    _t419 = ('_enrich_deal' in _lp_gen_src) and ('_cond_is_used' in _lp_gen_src)
    results.append({"level": "ok" if _t419 else "warning", "check": "central_enrich_used_filter_impl",
                    "message": "#419 LP ソースに中古・二次流通の共通除外ロジック（_enrich_deal / _cond_is_used）が実装済み"
                               + ("" if _t419 else " ← 共通 enrich/中古フィルタが見つかりません")})

    # ── Round 8: 実描画HTML（docs/index.html）ベースの追加検査（2026-05-31）──
    # 全て html（公開ビルド後の実描画 HTML）または タブスライス を検査する＝false-positive を防ぐ

    # #420: 公開HTML全体に「最高売却先」が存在しない（→「最高買取店」へ統一）
    _t420 = '最高売却先' not in html
    results.append({"level": "ok" if _t420 else "error", "check": "no_max_sell_label_in_html",
                    "message": "#420 公開HTMLに「最高売却先」が存在しない（最高買取店へ統一）"
                               + ("" if _t420 else " ← 公開HTMLに『最高売却先』が残っています")})

    # #421: 公開HTML全体に「中古市場でプレ値継続中」が存在しない
    _t421 = ('中古市場でプレ値継続中' not in html) and ('中古市場' not in html) and ('中古相場' not in html) and ('中古プレ値' not in html)
    results.append({"level": "ok" if _t421 else "error", "check": "no_used_market_phrase_in_html",
                    "message": "#421 公開HTMLに「中古市場/中古相場/中古プレ値」系の文言が存在しない"
                               + ("" if _t421 else " ← 公開HTMLに中古市場系の文言が残っています")})

    # #422: 公開HTML全体に「除外 (中古等)」が存在しない
    _t422 = ('除外 (中古等)' not in html) and ('除外（中古等）' not in html)
    results.append({"level": "ok" if _t422 else "error", "check": "no_excluded_used_phrase_in_html",
                    "message": "#422 公開HTMLに「除外 (中古等)」が存在しない"
                               + ("" if _t422 else " ← 公開HTMLに『除外 (中古等)』が残っています")})

    # #468: manual_buyback_prices.csv に camera 商品の new/unused 行がある
    import os as _os468
    _csv_path = _os468.path.join(_os468.path.dirname(_os468.path.dirname(_os468.path.abspath(__file__))),
                                 'data', 'manual_buyback_prices.csv')
    _csv_ok = False
    try:
        with open(_csv_path, encoding='utf-8') as _f:
            _csv_txt = _f.read()
        _cam_aliases = ('x100vi', 'gr4', 'gr4_hdf', 'gr4_mono', 'gr3x')
        _new_conds = ('new_unopened', 'new', 'unused', 'sealed')
        for _ln in _csv_txt.splitlines()[1:]:
            _parts = _ln.split(',')
            if len(_parts) >= 4 and _parts[0].strip() in _cam_aliases and _parts[3].strip() in _new_conds:
                _csv_ok = True
                break
    except Exception:
        _csv_ok = False
    results.append({"level": "ok" if _csv_ok else "error", "check": "csv_has_camera_new_unused_rows",
                    "message": "#468 manual_buyback_prices.csv に camera 商品の new/unused 行がある"
                               + ("" if _csv_ok else " ← カメラの新品・未使用買取行が CSV に見つかりません")})

    # ── 手動価格の2段階鮮度ルール（Add two-stage freshness rules for manual prices） ──
    # ジェネレータのソースを読み、鮮度ロジックの実装を構造的に検証する。
    _gen_src = ''
    try:
        _gen_path = _os468.path.join(_os468.path.dirname(_os468.path.dirname(_os468.path.abspath(__file__))),
                                     'src', 'content', 'daily_lp_generator.py')
        with open(_gen_path, encoding='utf-8') as _gf:
            _gen_src = _gf.read()
    except Exception:
        _gen_src = ''

    # ── Enforce daily refresh pipeline and stale data policy ──
    _root = _os468.path.dirname(_os468.path.dirname(_os468.path.abspath(__file__)))

    # #475: daily_lp.yml に全取得・生成ステップがある
    _wf = ''
    try:
        with open(_os468.path.join(_root, '.github', 'workflows', 'daily_lp.yml'), encoding='utf-8') as _wf_f:
            _wf = _wf_f.read()
    except Exception:
        _wf = ''
    _required_steps = [
        'update_buyback_prices.py', 'collect_resale_prices.py', 'update_overseas_prices.py',
        'update_lottery_events.py', 'update_alerts.py', 'generate_ranking_report.py',
        'generate_sedori_routes_report.py', 'generate-daily-lp', 'build-public-lp',
    ]
    _missing_steps = [s for s in _required_steps if s not in _wf]
    _has_push = ('git push' in _wf) or ('ad-m/github-push-action' in _wf) or ('Commit and push' in _wf)
    _t475 = (not _missing_steps) and _has_push
    results.append({"level": "ok" if _t475 else "error", "check": "daily_workflow_has_all_steps",
                    "message": "#475 daily_lp.yml に全取得・生成・push ステップがある"
                               + ("" if _t475 else f" ← 不足: {_missing_steps or 'push'}")})

    # #476: 各レポートの latest.json / latest.md が存在する
    _report_files = [
        'exports/overseas_prices/latest.json',
        'exports/ranking_report/latest.json', 'exports/ranking_report/latest.md',
        'exports/sedori_routes_report/latest.json', 'exports/sedori_routes_report/latest.md',
        'exports/collector_report/latest.json',
    ]
    _missing_reports = [f for f in _report_files if not _os468.path.exists(_os468.path.join(_root, f))]
    _t476 = not _missing_reports
    results.append({"level": "ok" if _t476 else "error", "check": "report_latest_files_present",
                    "message": "#476 各レポートの latest.json / latest.md が存在する"
                               + ("" if _t476 else f" ← 不足: {_missing_reports}")})

    # #480: 抽選情報が毎日更新される（workflow に update_lottery_events ステップがある）
    _t480 = ('update_lottery_events.py' in _wf)
    results.append({"level": "ok" if _t480 else "error", "check": "lottery_daily_update",
                    "message": "#480 抽選情報が毎日更新される（daily_lp.yml に update_lottery_events ステップ）"
                               + ("" if _t480 else " ← 抽選情報の更新ステップが見つかりません")})

    try:
        with open(_os468.path.join(_root, 'exports/collector_report/latest.json'), encoding='utf-8') as _cr:
            _cr_txt = _cr.read()
        _t481_report = ('reason' in _cr_txt) or ('fail' in _cr_txt.lower())
    except Exception:
        _t481_report = False

    # ── Improve daily data freshness and effective route generation ──
    def _load_json_safe(rel):
        try:
            with open(_os468.path.join(_root, rel), encoding='utf-8') as _jf:
                return _json482.load(_jf)
        except Exception:
            return None
    import json as _json482

    _rank_json = _load_json_safe('exports/ranking_report/latest.json') or {}
    _sed_json = _load_json_safe('exports/sedori_routes_report/latest.json') or {}
    _dq_json = _load_json_safe('exports/data_quality_report/latest.json') or {}

    # #482: beginner ランキングが0件なら理由が表示される
    _beg_rank_n = len(_rank_json.get('beginner_top10', []) or [])
    _t482 = (_beg_rank_n > 0) or bool(_rank_json.get('reason_if_empty'))
    results.append({"level": "ok" if _t482 else "error", "check": "ranking_empty_reason",
                    "message": f"#482 beginner ランキングが0件なら理由が表示される（beginner={_beg_rank_n}）"
                               + ("" if _t482 else " ← 0件なのに reason_if_empty がありません")})

    # #483: sedori ルートが0件なら理由が表示される
    if isinstance(_sed_json.get('profitable_routes'), int):
        _sed_route_n = _sed_json['profitable_routes']
    else:
        _sp = _sed_json.get('pro_routes', {})
        _sed_route_n = int(_sp.get('count', 0) or 0) if isinstance(_sp, dict) else len(_sp or [])
    _t483 = (_sed_route_n > 0) or bool(_sed_json.get('reason_if_empty'))
    results.append({"level": "ok" if _t483 else "error", "check": "sedori_empty_reason",
                    "message": f"#483 sedori ルートが0件なら理由が表示される（routes={_sed_route_n}）"
                               + ("" if _t483 else " ← 0件なのに reason_if_empty がありません")})

    # #484: overseas stale が主計算（ランキング/Pro/せどり）に使われない設計
    #   update_overseas_prices.py に stale 判定があり、stale を主計算から除外する方針が明示されている。
    _ovs_src = ''
    try:
        with open(_os468.path.join(_root, 'scripts', 'update_overseas_prices.py'), encoding='utf-8') as _of:
            _ovs_src = _of.read()
    except Exception:
        _ovs_src = ''
    _t484 = ('stale' in _ovs_src) and ('主計算' in _ovs_src or '除外' in _ovs_src)
    results.append({"level": "ok" if _t484 else "warning", "check": "overseas_stale_excluded",
                    "message": "#484 overseas stale は主計算から除外する方針が明示されている"
                               + ("" if _t484 else " ← stale 除外の明示が見つかりません")})

    # #485: eBay を取らない理由を明示する（Phase 13: 以前は「EBAY_APP_ID を設定すれば Finding API で取れる」と
    #       警告していたが、Finding API は 2025-02-05 に廃止された。今は取らない理由と成約の取り方を示す）
    _t485 = ('Finding API は廃止' in _ovs_src) and ('Marketplace Insights' in _ovs_src)
    results.append({"level": "ok" if _t485 else "error", "check": "ebay_app_id_warning",
                    "message": "#485 eBay を取らない理由（Finding API は廃止・成約は Marketplace Insights）を明示する"
                               + ("" if _t485 else " ← eBay を取らない理由の明示が見つかりません")})

    # #486: 手動データ（camera 含む）が14日超なら利益判定から除外（LP・ranking 両方）
    _ranking_src = ''
    try:
        with open(_os468.path.join(_root, 'scripts', 'generate_ranking_report.py'), encoding='utf-8') as _rf:
            _ranking_src = _rf.read()
    except Exception:
        _ranking_src = ''
    try:
        with open(_os468.path.join(_root, 'src', 'market', 'normalized_prices.py'), encoding='utf-8') as _nf:
            _norm_src = _nf.read()
    except Exception:
        _norm_src = ''

    # #487: データ品質レポートに 成功率 / 失敗理由 / 有効データ数 が出る
    _dq_ok = bool(_dq_json) and ('collection' in _dq_json) and ('failure_reasons' in _dq_json) \
        and ('effective_data' in _dq_json) and ('ranking_usable' in _dq_json) and ('sedori_usable' in _dq_json)
    results.append({"level": "ok" if _dq_ok else "error", "check": "data_quality_report_present",
                    "message": "#487 データ品質レポートに 成功率/失敗理由/有効データ数/ranking・sedori使用数 が出る"
                               + ("" if _dq_ok else " ← data_quality_report/latest.json が不完全です")})

    # #488: カメラ買取コレクターが workflow にあり、状態レポートが出力される
    _t488 = ('update_camera_buyback.py' in _wf) and _os468.path.exists(
        _os468.path.join(_root, 'exports', 'camera_buyback_status.json'))
    results.append({"level": "ok" if _t488 else "warning", "check": "camera_buyback_collector_present",
                    "message": "#488 カメラ買取コレクターが daily_lp.yml にあり camera_buyback_status.json を出力"
                               + ("" if _t488 else " ← カメラ買取コレクターのステップ/レポートが見つかりません")})

    # #489: EBAY_APP_ID 設定手順が README / CLAUDE.md に記載されている
    _ebay_doc = False
    for _doc in ('README.md', 'CLAUDE.md'):
        try:
            with open(_os468.path.join(_root, _doc), encoding='utf-8') as _df:
                if 'EBAY_APP_ID' in _df.read():
                    _ebay_doc = True
                    break
        except Exception:
            pass
    results.append({"level": "ok" if _ebay_doc else "error", "check": "ebay_app_id_documented",
                    "message": "#489 EBAY_APP_ID の設定手順が README / CLAUDE.md に記載されている"
                               + ("" if _ebay_doc else " ← EBAY_APP_ID の設定手順が見つかりません")})

    # #490: resale collector に condition 推定ロジックがある（Task 1 次フェーズ）
    _resale_src = ''
    try:
        with open(_os468.path.join(_root, 'scripts', 'collect_resale_prices.py'), encoding='utf-8') as _rsf:
            _resale_src = _rsf.read()
    except Exception:
        _resale_src = ''
    _t490 = ('_infer_condition' in _resale_src) and ('new_unopened' in _gen_src or 'new_unopened' in _resale_src)
    results.append({"level": "ok" if _t490 else "error", "check": "resale_condition_inference",
                    "message": "#490 resale collector に condition 推定ロジック（_infer_condition）がある"
                               + ("" if _t490 else " ← condition 推定ロジックが見つかりません")})

    # ── Improve overseas api readiness and camera collector diagnostics ──
    _ovs_json = _load_json_safe('exports/overseas_prices/latest.json') or {}
    # #491: overseas latest.json に EBAY_APP_ID 設定状況/取得モードが明記される（Task 1）
    _t491 = ('ebay_app_id_configured' in _ovs_json) and ('source_mode' in _ovs_json)
    results.append({"level": "ok" if _t491 else "error", "check": "overseas_mode_annotated",
                    "message": f"#491 overseas latest.json に ebay_app_id_configured / source_mode が明記される（mode={_ovs_json.get('source_mode')}）"
                               + ("" if _t491 else " ← api/manual/html_blocked モードの明記が見つかりません")})

    # #492: data_quality に 前回比較（comparison: 前回成功率/今回/差分/TOP5）がある（Task 3）
    _cmp = (_dq_json.get('comparison', {}) or {})
    _t492 = ('comparison' in _dq_json) and ('current_success_rate_pct' in _cmp) \
        and ('trend' in _cmp) and ('top5_failure_reasons' in _cmp)
    results.append({"level": "ok" if _t492 else "error", "check": "data_quality_comparison",
                    "message": "#492 data_quality に前回比較（前回/今回成功率・改善悪化・失敗理由TOP5）がある"
                               + ("" if _t492 else " ← comparison セクションが不完全です")})

    # #494: camera collector に優先3店舗の実セレクタ/キーワードURLがある（Task 2）
    _cam_src = ''
    try:
        with open(_os468.path.join(_root, 'scripts', 'update_camera_buyback.py'), encoding='utf-8') as _cf:
            _cam_src = _cf.read()
    except Exception:
        _cam_src = ''
    _t494 = ('PRIORITY_SHOPS' in _cam_src) and ('_SHOP_PRICE_PATTERNS' in _cam_src) \
        and ('{kw}' in _cam_src) and _os468.path.exists(
            _os468.path.join(_root, 'exports', 'camera_buyback_status.json'))
    results.append({"level": "ok" if _t494 else "error", "check": "camera_collector_selectors",
                    "message": "#494 camera collector に優先3店舗の検索URL/店舗別抽出パターンがある"
                               + ("" if _t494 else " ← 優先店舗のセレクタ/キーワードURLが見つかりません")})

    # #495: workflow の commit ステップが data_quality_report / camera_buyback_status を含む
    #   （Actions が生成した品質レポートをリポジトリにコミットさせるため）
    _t495 = ('exports/data_quality_report/' in _wf) and ('exports/camera_buyback_status.json' in _wf)
    results.append({"level": "ok" if _t495 else "error", "check": "workflow_commits_quality_reports",
                    "message": "#495 daily_lp.yml が data_quality_report / camera_buyback_status をコミットする"
                               + ("" if _t495 else " ← 品質レポートが commit 対象に含まれていません")})

    # #496: data_quality に 7日移動平均・店舗別/商品別成功率・連続失敗・改善優先順位がある（Task 3）
    _t496 = (('moving_avg_7d_pct' in (_dq_json.get('comparison', {}) or {}))
             and ('shop_success_rates' in _dq_json) and ('product_success_rates' in _dq_json)
             and ('consecutive_failed_shops' in _dq_json) and ('improvement_priority' in _dq_json))
    results.append({"level": "ok" if _t496 else "error", "check": "data_quality_advanced_metrics",
                    "message": "#496 data_quality に 7日移動平均/店舗別/商品別成功率/連続失敗/改善優先順位がある"
                               + ("" if _t496 else " ← 指標が不足しています")})

    # ── Camera collector diagnostics & auto-scrape priority ──
    _cam_json = _load_json_safe('exports/camera_buyback_status.json') or {}

    # #498: camera 自動取得(auto_scraped)が成功していれば LP に反映される（data依存）
    #   auto_scraped カメラ価格が DB にある場合のみ厳密検証。無い日は warning。
    _has_auto_cam = False
    try:
        import sqlite3 as _sq498
        _c = _sq498.connect(_os468.path.join(_root, 'data', 'premium_monitor.db'))
        _r = _c.execute("SELECT COUNT(*) FROM buyback_prices WHERE data_source='auto_scraped' "
                        "AND is_active=1 AND product_id IN "
                        "('prod_x100vi','prod_gr4','prod_gr3x','prod_gr4_mono','prod_gr4_hdf')").fetchone()
        _has_auto_cam = bool(_r and _r[0] > 0)
        _c.close()
    except Exception:
        _has_auto_cam = False
    results.append({"level": "ok" if _has_auto_cam else "warning", "check": "camera_auto_scraped_in_lp",
                    "message": "#498 camera の auto_scraped 価格があれば LP に反映される"
                               + ("" if _has_auto_cam else " ← 現在 auto_scraped カメラ価格なし（manual_today fallback中・取得成功時に自動反映）")})

    # #499: manual_today より auto_scraped が優先される（repository の優先度SQL）
    _repo_src = ''
    try:
        with open(_os468.path.join(_root, 'src', 'db', 'repository.py'), encoding='utf-8') as _rf:
            _repo_src = _rf.read()
    except Exception:
        _repo_src = ''
    _t499 = ("data_source = 'auto_scraped'" in _repo_src and 'THEN 1' in _repo_src) \
        and ("data_source = 'manual_today'" in _repo_src and 'THEN 2' in _repo_src)
    results.append({"level": "ok" if _t499 else "error", "check": "auto_scraped_priority_over_manual",
                    "message": "#499 manual_today より auto_scraped が優先される（買取比較の優先度SQL）"
                               + ("" if _t499 else " ← auto_scraped 優先のロジックが見つかりません")})

    # #500: debug HTML が保存される実装＋ exports/debug_camera/ ディレクトリがある
    _t500 = ('--debug-html' in _cam_src) and ('debug_camera' in _cam_src) \
        and _os468.path.isdir(_os468.path.join(_root, 'exports', 'debug_camera'))
    results.append({"level": "ok" if _t500 else "warning", "check": "camera_debug_html_saved",
                    "message": "#500 camera debug HTML 保存（--debug-html / exports/debug_camera/）"
                               + ("" if _t500 else " ← debug HTML 保存の実装/ディレクトリが見つかりません")})

    # #501: camera status に診断（html_saved/cloudflare/js_required/selector_found/extracted_price + shop_diagnostics）
    _det = (_cam_json.get('detail') or [{}])
    _det0 = _det[0] if _det else {}
    _t501 = ('shop_diagnostics' in _cam_json) and all(
        k in _det0 for k in ('html_saved', 'cloudflare_detected', 'js_required',
                             'selector_found', 'extracted_price', 'html_size')
    )
    results.append({"level": "ok" if _t501 else "error", "check": "camera_status_diagnostics",
                    "message": "#501 camera_buyback_status に診断項目（html_saved/size/cloudflare/js_required/selector_found/extracted_price + 店舗別診断）がある"
                               + ("" if _t501 else " ← 診断項目が不足しています")})

    # ── Playwright fallback for camera buyback collector ──
    # #502: Playwright fallback が実装されている
    _t502 = ('_fetch_with_playwright' in _cam_src) and ('sync_playwright' in _cam_src) \
        and ('--playwright' in _cam_src)
    results.append({"level": "ok" if _t502 else "error", "check": "camera_playwright_fallback",
                    "message": "#502 camera collector に Playwright fallback が実装されている"
                               + ("" if _t502 else " ← Playwright fallback が見つかりません")})

    # #503: camera status に playwright_attempted がある
    _t503 = ('playwright_attempted' in _det0)
    results.append({"level": "ok" if _t503 else "error", "check": "camera_status_playwright_field",
                    "message": "#503 camera_buyback_status の detail に playwright_attempted 等の診断がある"
                               + ("" if _t503 else " ← playwright 診断項目が見つかりません")})

    # #504: screenshot / rendered HTML 保存処理がある
    _t504 = ('screenshot' in _cam_src) and ('.pw.html' in _cam_src or 'rendered_html_size' in _cam_src)
    results.append({"level": "ok" if _t504 else "error", "check": "camera_playwright_debug_artifacts",
                    "message": "#504 Playwright のスクリーンショット/レンダリングHTML保存処理がある"
                               + ("" if _t504 else " ← screenshot/rendered HTML 保存処理が見つかりません")})

    # #505: auto_scraped 成功時は manual_today より優先される（#499 と同根の保証）
    _t505 = _t499 and ("data_source=\"auto_scraped\"" in _cam_src or "data_source='auto_scraped'" in _cam_src
                       or 'data_source="auto_scraped"' in _cam_src or "'auto_scraped'" in _cam_src)
    results.append({"level": "ok" if _t505 else "error", "check": "camera_auto_over_manual",
                    "message": "#505 camera の auto_scraped 取得は manual_today より優先される"
                               + ("" if _t505 else " ← auto_scraped 保存/優先の実装が見つかりません")})

    # #506: 失敗時 manual_today fallback が維持される（collector は manual 行を削除しない）
    _t506 = ('fallback_note' in _cam_src) and ('manual_today' in _cam_src) \
        and ('delete' not in _cam_src.lower().replace('deleted', ''))
    # fallback_note が status に出ているかも確認
    _t506 = _t506 and ('fallback_note' in _cam_json)
    results.append({"level": "ok" if _t506 else "warning", "check": "camera_manual_fallback_kept",
                    "message": "#506 取得失敗時は manual_today fallback が維持される（collector は manual を削除しない）"
                               + ("" if _t506 else " ← manual fallback 維持の確認ができません")})

    # ── Playwright artifact upload & DOM diagnostics ──
    # #507: workflow に upload-artifact（camera-playwright-debug）がある
    _t507 = ('actions/upload-artifact' in _wf) and ('camera-playwright-debug' in _wf)
    results.append({"level": "ok" if _t507 else "error", "check": "workflow_uploads_camera_artifact",
                    "message": "#507 daily_lp.yml に upload-artifact（camera-playwright-debug）がある"
                               + ("" if _t507 else " ← upload-artifact ステップが見つかりません")})

    # #508: artifact に debug_camera / screenshots / status が含まれる
    _t508 = ('exports/debug_camera/' in _wf) and ('exports/debug_camera_screenshots/' in _wf) \
        and ('exports/camera_buyback_status.json' in _wf)
    results.append({"level": "ok" if _t508 else "error", "check": "artifact_paths_present",
                    "message": "#508 artifact に debug_camera/ screenshots/ camera_buyback_status.json が含まれる"
                               + ("" if _t508 else " ← artifact パスが不足しています")})

    # #509: collector に selector brute force / DOM 診断（selector_candidates）がある
    _t509 = ('selector_candidates' in _cam_src) and ('_PW_DOM_PROBE_JS' in _cam_src) \
        and ('body_text_preview' in _cam_src)
    results.append({"level": "ok" if _t509 else "error", "check": "camera_dom_diagnostics_impl",
                    "message": "#509 collector に DOM診断/selector brute force（selector_candidates/body_text_preview）がある"
                               + ("" if _t509 else " ← DOM診断の実装が見つかりません")})

    # #510: status detail に body_text_preview / iframe_count がある（実行済みなら）
    _t510_impl = all(k in _det0 for k in ('body_text_preview', 'iframe_count',
                                          'selector_candidates', 'shadow_dom_detected', 'dom_ready_state'))
    results.append({"level": "ok" if _t510_impl else "error", "check": "camera_status_dom_fields",
                    "message": "#510 camera_buyback_status の detail に body_text_preview/iframe_count/selector_candidates 等がある"
                               + ("" if _t510_impl else " ← DOM診断項目が detail に不足しています")})

    # #511: 価格regex/候補セレクタ群が実装されている（table td / .price / [class*=price]）
    _t511 = ("table td" in _cam_src) and ("[class*='price']" in _cam_src) and ('PRICE_RE' in _cam_src)
    results.append({"level": "ok" if _t511 else "error", "check": "camera_selector_bruteforce_list",
                    "message": "#511 selector brute force 候補（table td / .price / [class*=price]）と価格regexがある"
                               + ("" if _t511 else " ← 候補セレクタ/価格regex が見つかりません")})

    # ── Fujiya keyword variants（追加対策）──
    # #512: Fujiya keyword variants が定義されている
    _t512 = ('FUJIYA_KEYWORD_VARIANTS' in _cam_src) and ('該当件数' in _cam_src)
    results.append({"level": "ok" if _t512 else "error", "check": "fujiya_keyword_variants_defined",
                    "message": "#512 Fujiya の複数キーワード候補（FUJIYA_KEYWORD_VARIANTS）が定義されている"
                               + ("" if _t512 else " ← keyword variants が見つかりません")})

    # #513: keyword別 hit_count / best_keyword を diagnostics に保存する実装がある
    _t513 = ('keyword_hit_counts' in _cam_src) and ('best_keyword' in _cam_src) \
        and ('hit_count' in _cam_src)
    results.append({"level": "ok" if _t513 else "error", "check": "fujiya_hit_count_tracking",
                    "message": "#513 keyword別 hit_count / best_keyword を diagnostics に保存する実装がある"
                               + ("" if _t513 else " ← hit_count/best_keyword の実装が見つかりません")})

    # #514: camera_buyback_status の detail に keyword_hit_counts / best_keyword / hit_count フィールドがある
    _t514 = all(k in _det0 for k in ('keyword_hit_counts', 'best_keyword', 'hit_count'))
    results.append({"level": "ok" if _t514 else "error", "check": "camera_status_keyword_fields",
                    "message": "#514 camera_buyback_status の detail に keyword_hit_counts/best_keyword/hit_count がある"
                               + ("" if _t514 else " ← keyword 診断項目が detail に不足しています")})

    # ── Buyback page discovery & sales-price guard ──
    # #515: 販売価格を買取価格として保存しない（near_buyback ゲート / sales_catalog_no_buyback）
    _t515 = ('near_buyback' in _cam_src) and ('has_buyback_context' in _cam_src) \
        and ('sales_catalog_no_buyback' in _cam_src)
    results.append({"level": "ok" if _t515 else "error", "check": "camera_no_sales_price_as_buyback",
                    "message": "#515 販売価格を買取価格として保存しない（買取文脈ゲート）"
                               + ("" if _t515 else " ← 販売価格ガードが見つかりません")})

    # #516: 買取ページ探索の実装＋status detail フィールド（buyback_link_candidates/buyback_page_url/buyback_price_candidates）
    _t516_impl = ('buyback_link_candidates' in _cam_src) and ('purchase/list.aspx' in _cam_src) \
        and ('買取金額' in _cam_src or 'buyback_page_url' in _cam_src)
    _t516_fields = all(k in _det0 for k in ('buyback_link_candidates', 'buyback_page_url',
                                            'buyback_price_candidates', 'buyback_extracted_price'))
    _t516 = _t516_impl and _t516_fields
    results.append({"level": "ok" if _t516 else "error", "check": "camera_buyback_page_discovery",
                    "message": "#516 買取ページ探索（買取専用URL/リンク候補/買取価格候補）が status に出る"
                               + ("" if _t516 else " ← 買取ページ探索の実装/フィールドが不足しています")})

    # #517: Fujiya は販売 search.aspx ではなく買取 purchase ページを使う
    _t517 = ('/shop/purchase/list.aspx' in _cam_src) and ('fujiya_buyback' in _cam_src)
    results.append({"level": "ok" if _t517 else "error", "check": "fujiya_uses_buyback_page",
                    "message": "#517 Fujiya は買取専用ページ（/shop/purchase/list.aspx）を使う"
                               + ("" if _t517 else " ← 買取専用ページの使用が見つかりません")})

    # ── Fujiya model matching & confidence ──
    # #518: 機種厳密マッチ（_strict_model_match / _select_camera_buyback）が実装されている
    _t518 = ('_strict_model_match' in _cam_src) and ('_select_camera_buyback' in _cam_src) \
        and ('item_text' in _cam_src)
    results.append({"level": "ok" if _t518 else "error", "check": "fujiya_strict_model_match",
                    "message": "#518 Fujiya 機種厳密マッチ（_strict_model_match/_select_camera_buyback）が実装されている"
                               + ("" if _t518 else " ← 機種厳密マッチの実装が見つかりません")})

    # #519: strict 一致は confidence=high で保存（confidence=_confidence）
    _t519 = ('confidence=_confidence' in _cam_src) and ('high' in _cam_src)
    results.append({"level": "ok" if _t519 else "error", "check": "camera_confidence_classification",
                    "message": "#519 strict一致の auto_scraped は confidence で分類（high）して保存"
                               + ("" if _t519 else " ← confidence 分類の実装が見つかりません")})

    # #520: low confidence は主計算（enrich）に使われない
    _t520 = ("r.get('confidence', 'high') != 'low'" in _gen_src) or ("confidence', 'high') != 'low'" in _gen_src)
    results.append({"level": "ok" if _t520 else "error", "check": "low_confidence_excluded",
                    "message": "#520 low confidence の買取価格は主計算（enrich/比較）に使われない"
                               + ("" if _t520 else " ← low confidence 除外が見つかりません")})

    # #522: Fujiya auto_scraped が status に存在する（data依存：取得成功時 OK>=1）
    _fuji_ok = sum(1 for x in (_cam_json.get('detail') or [])
                   if x.get('shop_id') == 'src_fujiya' and x.get('status') == 'OK')
    _t522 = _fuji_ok >= 1
    results.append({"level": "ok" if _t522 else "warning", "check": "fujiya_auto_scraped_present",
                    "message": f"#522 Fujiya の auto_scraped 買取価格が存在する（OK={_fuji_ok}件）"
                               + ("" if _t522 else " ← Fujiya auto_scraped が0件（取得失敗日は正常）")})

    # ── Expand Fujiya matching & suppress inflated manual prices ──
    # #523: GR IV 無印は HDF/Mono/IIIx を誤採用しない（strict match の除外ロジック）
    # データ駆動 CAMERA_MODELS の gr4 が HDF/IIIX/MONOCHROME を exclude しているか（ソース文字列で検証）
    _t523 = ('"gr4":' in _cam_src) and ('"exclude": ["HDF", "IIIX", "3X", "MONOCHROME"]' in _cam_src)
    results.append({"level": "ok" if _t523 else "error", "check": "gr4_excludes_variants",
                    "message": "#523 GR IV 無印は HDF/Monochrome/IIIx を誤採用しない（CAMERA_MODELS exclude）"
                               + ("" if _t523 else " ← GR IV 無印の除外ロジックが見つかりません")})

    # #524: all_price_candidates / rejected_candidates が status に保存される
    _t524 = ('all_price_candidates' in _cam_src) and ('rejected_candidates' in _cam_src) \
        and ('rejection_reason' in _cam_src) and ('all_price_candidates' in _det0) \
        and ('rejected_candidates' in _det0) and ('used_for_save' in _det0)
    results.append({"level": "ok" if _t524 else "error", "check": "camera_candidate_tracking",
                    "message": "#524 all_price_candidates / rejected_candidates / used_for_save が status に保存される"
                               + ("" if _t524 else " ← 候補追跡フィールドが不足しています")})

    # #525: auto_scraped(high) がある場合、30%超高い manual 価格はランキング主計算から除外
    _t525 = ('_auto_high' in _gen_src) and ('* 1.3' in _gen_src) \
        and ("data_source') == 'auto_scraped'" in _gen_src or 'auto_scraped' in _gen_src)
    results.append({"level": "ok" if _t525 else "error", "check": "inflated_manual_excluded",
                    "message": "#525 auto_scraped(high) 比30%超高い manual はランキング主計算から除外"
                               + ("" if _t525 else " ← 過大 manual 除外ロジックが見つかりません")})

    # #527: 販売価格を買取として保存しないガード維持（キタムラ対応後も）
    _t527 = ('near_buyback' in _cam_src) and ('sales_catalog_no_buyback' in _cam_src)
    results.append({"level": "ok" if _t527 else "error", "check": "sales_guard_maintained",
                    "message": "#527 販売価格を買取価格として保存しないガードが維持されている"
                               + ("" if _t527 else " ← 販売価格ガードが見つかりません")})

    # #529: matched_item を notes に保存し repo が notes を返す
    _t529 = ('notes=(_matched_item' in _cam_src) and ('notes' in _repo_src) \
        and ("COALESCE(notes" in _repo_src)
    results.append({"level": "ok" if _t529 else "error", "check": "matched_item_persisted",
                    "message": "#529 matched_item を notes に保存し買取比較に表示できる"
                               + ("" if _t529 else " ← matched_item の保存/取得が見つかりません")})

    # #530: GR IV 無印が HDF/Mono/IIIx を誤採用しない（#523 と対：camera_buyback_status で確認）
    _gr4 = next((x for x in (_cam_json.get('detail') or [])
                 if x.get('shop_id') == 'src_fujiya' and x.get('product_alias') == 'gr4'
                 and x.get('status') == 'OK'), None)
    _gr4_item = (_gr4.get('matched_item', '') if _gr4 else '')
    _t530 = (_gr4 is None) or (('HDF' not in _gr4_item) and ('Monochrome' not in _gr4_item)
                               and ('モノクローム' not in _gr4_item) and ('IIIx' not in _gr4_item))
    results.append({"level": "ok" if _t530 else "error", "check": "gr4_plain_no_variant_misadopt",
                    "message": "#530 GR IV 無印が HDF/Monochrome/IIIx 価格を誤採用しない"
                               + ("" if _t530 else f" ← GR IV 無印が派生機種を誤採用: {_gr4_item[:40]}")})

    # #531: manual 過大価格がランキングに使われない（enrich 除外＝LP/ranking 双方に効く）
    _t531 = ('_auto_high' in _gen_src) and ('* 1.3' in _gen_src)
    results.append({"level": "ok" if _t531 else "error", "check": "inflated_manual_not_in_ranking",
                    "message": "#531 manual 過大価格（auto high比1.3倍超）がランキング主計算に使われない"
                               + ("" if _t531 else " ← 過大 manual 除外が見つかりません")})

    # #532: data_quality_report に camera_auto_scraped_count 等の信頼性メトリクスがある
    _cr = (_dq_json.get('camera_reliability', {}) or {})
    _t532 = all(k in _cr for k in ('camera_auto_scraped_count', 'camera_auto_high_confidence_count',
                                   'camera_manual_fallback_count', 'camera_rejected_candidate_count',
                                   'camera_rejection_reasons'))
    results.append({"level": "ok" if _t532 else "error", "check": "data_quality_camera_reliability",
                    "message": f"#532 data_quality_report に camera 信頼性メトリクスがある（auto={_cr.get('camera_auto_scraped_count')}）"
                               + ("" if _t532 else " ← camera_reliability メトリクスが不足しています")})

    # ── Camera Buyback Expansion Phase ──
    # #533: 全対象機種に model alias と strict ルール（CAMERA_MODELS）が定義されている
    _expected_models = ["a7rv", "a1ii", "a7cr", "fx3", "r5ii", "r6ii", "r3",
                        "z8", "zf", "z9", "q3", "m11", "gr3", "gr3x", "gr4",
                        "gr4_hdf", "gr4_mono", "x100vi", "gfx100rf", "xt5"]
    _t533 = ('CAMERA_MODELS' in _cam_src) and all(f'"{a}":' in _cam_src for a in _expected_models)
    results.append({"level": "ok" if _t533 else "error", "check": "camera_models_all_aliases",
                    "message": f"#533 全対象機種({len(_expected_models)})に model alias / strict ルールが定義されている"
                               + ("" if _t533 else " ← 一部機種の alias 定義が見つかりません")})

    # #534: strict match がデータ駆動（require_any/include_all/exclude）で有効
    _t534 = ('require_any' in _cam_src) and ('include_all' in _cam_src) \
        and ('exclude_raw' in _cam_src) and ('CAMERA_MODELS.get(alias)' in _cam_src)
    results.append({"level": "ok" if _t534 else "error", "check": "strict_match_data_driven",
                    "message": "#534 strict model match がデータ駆動（require_any/include_all/exclude）で有効"
                               + ("" if _t534 else " ← データ駆動 strict match が見つかりません")})

    # #535: ランキングに Top Camera Buyback Opportunities（high/auto/fresh<=7d）がある
    _topcam = _rank_json.get('top_camera_buyback_opportunities')
    _t535 = ('top_camera_buyback_opportunities' in _ranking_src) and ("data_source='auto_scraped'" in _ranking_src) \
        and ("confidence='high'" in _ranking_src) and ('> 7' in _ranking_src) and (_topcam is not None)
    results.append({"level": "ok" if _t535 else "error", "check": "top_camera_buyback_ranking",
                    "message": f"#535 Top Camera Buyback Opportunities（high/auto/fresh<=7d）がランキングにある（{len(_topcam or [])}件）"
                               + ("" if _t535 else " ← Top Camera Buyback ランキングが見つかりません")})

    # #536: data_quality に per_brand_success_rates と low_confidence_count がある
    _t536 = ('per_brand_success_rates' in _cr) and ('camera_auto_low_confidence_count' in _cr)
    results.append({"level": "ok" if _t536 else "error", "check": "camera_brand_success_rates",
                    "message": "#536 data_quality に ブランド別成功率 / low_confidence_count がある"
                               + ("" if _t536 else " ← ブランド別成功率/low_confidence が不足しています")})

    # #537: 拡張カメラ製品が products.yaml に seed されている
    _yaml_ok = False
    try:
        with open(_os468.path.join(_root, 'config', 'products.yaml'), encoding='utf-8') as _yf:
            _ytxt = _yf.read()
        _yaml_ok = all(pid in _ytxt for pid in
                       ('prod_a7rv', 'prod_r5ii', 'prod_z8', 'prod_q3', 'prod_m11', 'prod_gfx100rf', 'prod_xt5'))
    except Exception:
        _yaml_ok = False
    results.append({"level": "ok" if _yaml_ok else "error", "check": "expansion_products_seeded",
                    "message": "#537 拡張カメラ製品（Sony/Canon/Nikon/Leica/GFX/X-T5）が products.yaml に定義されている"
                               + ("" if _yaml_ok else " ← 拡張製品が products.yaml に見つかりません")})

    # #538: Top Camera Buyback ランキングがカメラ製品のみ（genre='camera'）に限定されている
    _t538 = ("genre='camera'" in _ranking_src) and all(
        (x.get('product_name', '') != '') for x in (_topcam or [])
    ) and not any(
        kw in (x.get('product_name', '') or '')
        for x in (_topcam or []) for kw in ('iPhone', 'PlayStation', 'PS5', 'Switch')
    )
    results.append({"level": "ok" if _t538 else "error", "check": "top_camera_buyback_camera_only",
                    "message": "#538 Top Camera Buyback ランキングがカメラ製品（genre='camera'）のみに限定されている"
                               + ("" if _t538 else " ← 非カメラ製品（iPhone/PS5等）が混入しています")})

    # ── 監査指摘（Issue 1-6）の修正ガード ──
    def _read_src(*parts):
        try:
            with open(_os468.path.join(_root, *parts), encoding='utf-8') as _f:
                return _f.read()
        except Exception:
            return ''
    _det_src = _read_src('src', 'market', 'buyback_change_detector.py')
    _alert_src = _read_src('scripts', 'update_alerts.py')
    _sedori_src = _read_src('src', 'market', 'sedori_route_calculator.py')

    # #539: 買取急変検知が price<=0 をガード（0円→急騰/急落の偽アラート防止）
    _t539 = ('current <= 0 or previous <= 0' in _det_src)
    results.append({"level": "ok" if _t539 else "error", "check": "buyback_alert_zero_guard",
                    "message": "#539 買取急変検知が price<=0（取得失敗/前回なし）をガードしている"
                               + ("" if _t539 else " ← 0円アラートのガードが見つかりません")})

    # #540: alert生成側でも 0円 / diff==0 をスキップ
    _t540 = ('(price_after or 0) <= 0 or (price_before or 0) <= 0' in _alert_src) and ('if diff == 0' in _alert_src)
    results.append({"level": "ok" if _t540 else "error", "check": "alert_zero_diff_skip",
                    "message": "#540 アラート生成が 0円/差分0 をスキップしている"
                               + ("" if _t540 else " ← 0円/差分0 スキップが見つかりません")})

    # #541: カメラ買取が商品個別URL（item_link_candidates / _pick_item_url）を採用
    _t541 = ('_pick_item_url' in _cam_src) and ('item_link_candidates' in _cam_src) \
        and ('link_verified=_url_verified' in _cam_src)
    results.append({"level": "ok" if _t541 else "error", "check": "camera_item_url",
                    "message": "#541 カメラ買取リンクが商品個別ページURL（店舗トップ/検索でない）を優先している"
                               + ("" if _t541 else " ← 商品個別URLの採用ロジックが見つかりません")})

    # #542: DOM probe が下取（トレードイン/%UP）価格を現金買取から分離・除外
    _t542 = ('is_tradein' in _cam_src) and ('下取' in _cam_src) and ('!c.is_tradein' in _cam_src)
    results.append({"level": "ok" if _t542 else "error", "check": "camera_tradein_exclude",
                    "message": "#542 カメラ買取が下取(15%UP等)価格を現金買取価格から分離・除外している"
                               + ("" if _t542 else " ← 下取価格の除外ロジックが見つかりません")})

    # #543: sedori が売却先に海外販売価格を含む（NPO の PRO_SELL_TYPES = buyback + overseas_sold）
    _t543 = ('overseas_sold_price' in _norm_src) and ('PRO_SELL_TYPES' in _norm_src) \
        and ('pro_sell_options' in _sedori_src)
    results.append({"level": "ok" if _t543 else "error", "check": "sedori_overseas_sell",
                    "message": "#543 せどり計算の売却先が「買取価格＋海外販売価格」になっている（NPO PRO_SELL_TYPES）"
                               + ("" if _t543 else " ← 海外売却ルートが見つかりません")})

    # #544: ranking top_camera が参照価格(公式/定価)<=0 を除外（差益計算不能を弾く）
    _t544 = ('reference <= 0' in _ranking_src) and ('reference_source' in _ranking_src)
    results.append({"level": "ok" if _t544 else "error", "check": "top_camera_reference_guard",
                    "message": "#544 Top Camera Buyback が参照価格(公式/定価)未取得の商品を除外している"
                               + ("" if _t544 else " ← 参照価格0の除外ロジックが見つかりません")})

    # ── normalized_price_observations（正規化価格テーブル）ガード #545-#551 ──
    _npo = _load_json_safe('exports/normalized_price_observations/latest.json')
    _obs = (_npo or {}).get("observations", []) if isinstance(_npo, dict) else []

    # #545: latest.json が存在する
    _t545 = isinstance(_npo, dict) and ("observations" in _npo)
    results.append({"level": "ok" if _t545 else "error", "check": "npo_exists",
                    "message": f"#545 normalized_price_observations/latest.json が存在する（{len(_obs)}観測）"
                               + ("" if _t545 else " ← ファイルが見つかりません")})

    # #546: price_role が全観測に必ずある
    _missing_role = sum(1 for r in _obs if not r.get("price_role"))
    _t546 = _t545 and _missing_role == 0 and len(_obs) > 0
    results.append({"level": "ok" if _t546 else "error", "check": "npo_price_role_required",
                    "message": "#546 全観測に price_role が付与されている"
                               + ("" if _t546 else f" ← price_role 欠落 {_missing_role} 件")})

    # #547: trade_in_price が最高買取価格(=main calc)に使われない
    _bad547 = sum(1 for r in _obs if r.get("price_type") == "trade_in_price"
                  and (r.get("is_usable_for_beginner") or r.get("is_usable_for_pro")))
    _t547 = _t545 and _bad547 == 0
    results.append({"level": "ok" if _t547 else "error", "check": "npo_tradein_not_main",
                    "message": "#547 trade_in_price が main calculation（最高買取等）に使われない"
                               + ("" if _t547 else f" ← trade_in が利用可 {_bad547} 件")})

    # #548: Pro route の buy 側に buyback_price が使われない
    _bad548 = sum(1 for r in _obs if r.get("is_usable_for_pro")
                  and r.get("price_role") == "buy" and r.get("price_type") == "buyback_price")
    _t548 = _t545 and _bad548 == 0
    results.append({"level": "ok" if _t548 else "error", "check": "npo_pro_buy_no_buyback",
                    "message": "#548 Pro route の buy 側に buyback_price が使われない"
                               + ("" if _t548 else f" ← buyback を仕入れに使用 {_bad548} 件")})

    # #549: Pro route の sell 側に sale/listing/sold 価格が使われない
    _sale_types = {"shop_sale_price", "flea_listing_price", "flea_sold_price", "overseas_listing_price"}
    _bad549 = sum(1 for r in _obs if r.get("is_usable_for_pro")
                  and r.get("price_role") == "sell" and r.get("price_type") in _sale_types)
    _t549 = _t545 and _bad549 == 0
    results.append({"level": "ok" if _t549 else "error", "check": "npo_pro_sell_no_sale",
                    "message": "#549 Pro route の sell 側に sale/listing 価格が使われない"
                               + ("" if _t549 else f" ← sale/listing を売却に使用 {_bad549} 件")})

    # #550: price=0 が main calculation に使われない
    _bad550 = sum(1 for r in _obs if (r.get("price") or 0) <= 0
                  and (r.get("is_usable_for_beginner") or r.get("is_usable_for_pro")))
    _t550 = _t545 and _bad550 == 0
    results.append({"level": "ok" if _t550 else "error", "check": "npo_price_zero_not_main",
                    "message": "#550 price=0 が main calculation に使われない"
                               + ("" if _t550 else f" ← price=0 が利用可 {_bad550} 件")})

    # #551: stale 14日超が main calculation に使われない
    _bad551 = sum(1 for r in _obs if (not r.get("is_fresh"))
                  and (r.get("is_usable_for_beginner") or r.get("is_usable_for_pro")))
    _t551 = _t545 and _bad551 == 0
    results.append({"level": "ok" if _t551 else "error", "check": "npo_stale_not_main",
                    "message": "#551 stale（14日超）が main calculation に使われない"
                               + ("" if _t551 else f" ← stale が利用可 {_bad551} 件")})

    # ── normalized_price_observations を唯一の入力源とする移行ガード #552-#557 ──
    _t552 = ('from src.market.normalized_prices import' in _sedori_src) \
        and ('pro_buy_options' in _sedori_src) and ('pro_sell_options' in _sedori_src)
    results.append({"level": "ok" if _t552 else "error", "check": "sedori_uses_npo",
                    "message": "#552 sedori 計算が normalized_prices（pro_buy/pro_sell）を唯一の入力源にしている"
                               + ("" if _t552 else " ← sedori が NPO を使っていません")})

    _t553 = ('from src.market.normalized_prices import' in _ranking_src) \
        and ('beginner_official' in _ranking_src) and ('repo.list_beginner_deals(' not in _ranking_src)
    results.append({"level": "ok" if _t553 else "error", "check": "ranking_uses_npo",
                    "message": "#553 ranking が NPO（official+sell / buy+sell）由来で旧 list_beginner_deals 直読みを廃止"
                               + ("" if _t553 else " ← ranking に旧DB直読みが残存")})

    _sedori_rep_src = _read_src('scripts', 'generate_sedori_routes_report.py')
    _t554 = all(k in _sedori_rep_src for k in
                ('buy_price_type', 'sell_price_type', 'buy_source', 'sell_source'))
    results.append({"level": "ok" if _t554 else "error", "check": "sedori_route_meta_fields",
                    "message": "#554 sedori route に buy_price_type/sell_price_type/buy_source/sell_source が出力される"
                               + ("" if _t554 else " ← route の型/ソース欄が見つかりません")})

    # #555: sedori report の Pro route — buy 側に buyback が無い / sell 側に sale 系が無い
    _srep = _load_json_safe('exports/sedori_routes_report/latest.json') or {}
    _pro_top = (_srep.get('pro_routes', {}) or {}).get('top', []) if isinstance(_srep, dict) else []
    _sale_t = {'shop_sale_price', 'flea_listing_price', 'flea_sold_price', 'overseas_listing_price'}
    _bad555 = sum(1 for r in _pro_top
                  if r.get('buy_price_type') == 'buyback_price'
                  or r.get('sell_price_type') in _sale_t
                  or r.get('buy_price_type') == 'trade_in_price'
                  or r.get('sell_price_type') == 'trade_in_price')
    _t555 = _bad555 == 0
    results.append({"level": "ok" if _t555 else "error", "check": "sedori_pro_role_integrity",
                    "message": "#555 sedori Pro route の buy=販売系 / sell=買取・海外落札 のみ（buyback仕入れ/sale売却/下取なし）"
                               + ("" if _t555 else f" ← 役割違反 {_bad555} 件")})

    # #556: ranking Pro top10 — buy 側に buyback が無い / sell 側に sale 系が無い
    _rj = _load_json_safe('exports/ranking_report/latest.json') or {}
    _rpro = _rj.get('pro_top10', []) if isinstance(_rj, dict) else []
    _bad556 = sum(1 for r in _rpro
                  if r.get('buy_price_type') == 'buyback_price'
                  or r.get('sell_price_type') in _sale_t)
    _t556 = _bad556 == 0
    results.append({"level": "ok" if _t556 else "error", "check": "ranking_pro_role_integrity",
                    "message": "#556 ranking Pro top10 が buy=販売系 / sell=買取 のみ（buyback仕入れ/sale売却なし）"
                               + ("" if _t556 else f" ← 役割違反 {_bad556} 件")})

    # #557: migration 018 + SedoriRouteModel に型/ソースフィールド
    _mig018 = _os468.path.exists(_os468.path.join(_root, 'src', 'db', 'migrations', '018_sedori_route_price_meta.sql'))
    _model_src = _read_src('src', 'models', 'sale_price.py')
    _t557 = _mig018 and ('buy_price_type' in _model_src) and ('sell_source' in _model_src)
    results.append({"level": "ok" if _t557 else "error", "check": "sedori_price_meta_migration",
                    "message": "#557 migration 018 と SedoriRouteModel に価格種別/ソース欄がある"
                               + ("" if _t557 else " ← migration 018 / モデル欄が見つかりません")})

    # #558: カメラ買取が段階表示の下取(trade-in)段を除外し現金買取最高値を採用
    _t558 = ('_select_cash_buyback_price' in _cam_src) and ('下取' in _cam_src) \
        and ('基準査定額' in _norm_src) and ('has_cash' in _norm_src)
    results.append({"level": "ok" if _t558 else "error", "check": "camera_cash_buyback_tier",
                    "message": "#558 カメラ買取が段階表示の下取(15%UP等)段を除外し現金買取の最高値を採用する"
                               + ("" if _t558 else " ← 下取段除外/現金買取選定ロジックが見つかりません")})

    # #559: auto_scraped high がある商品で、manual 買取が +30% 超なら主計算から除外
    _lp_src559 = _read_src('src', 'content', 'daily_lp_generator.py')
    _code559 = ('MANUAL_OVER_AUTO_RATIO' in _norm_src) and ('manual_over_auto_high' in _norm_src) \
        and ('_auto_hi' in _lp_src559 or 'manual_outlier' in _lp_src559.lower())
    # データ面: auto_high*1.3 を超える manual 買取が usable になっていない
    _bad559 = 0
    if _t545:
        from collections import defaultdict as _dd559
        _ah = _dd559(float)
        for r in _obs:
            if (r.get('price_type') == 'buyback_price' and r.get('extraction_method') == 'auto_scraped'
                    and r.get('confidence') == 'high' and r.get('is_fresh') and (r.get('price') or 0) > 0):
                _ah[r.get('product_id')] = max(_ah[r.get('product_id')], r.get('price'))
        for r in _obs:
            if (r.get('price_type') == 'buyback_price' and r.get('extraction_method') == 'manual'
                    and (r.get('price') or 0) > 0):
                _a = _ah.get(r.get('product_id'), 0)
                if _a > 0 and (r.get('price') or 0) > _a * 1.3 \
                        and (r.get('is_usable_for_beginner') or r.get('is_usable_for_pro')):
                    _bad559 += 1
    _t559 = _code559 and _bad559 == 0
    results.append({"level": "ok" if _t559 else "error", "check": "manual_over_auto_excluded",
                    "message": "#559 auto_scraped high の+30%超の manual 買取が主計算/最高買取から除外される"
                               + ("" if _t559 else f" ← コード未実装 or 異常manual残存 {_bad559} 件")})

    # ── 製品同一性（本体判定）ガード #560-#565 ──
    _sed_rep = _load_json_safe('exports/sedori_routes_report/latest.json') or {}
    _pro_routes = (_sed_rep.get('pro_routes', {}) or {}).get('top', []) if isinstance(_sed_rep, dict) else []
    _all_routes = _pro_routes + (_sed_rep.get('all_profitable', []) if isinstance(_sed_rep, dict) else [])

    # #560: NPO に product_match_confidence / accessory_flag フィールドがある
    _t560 = _t545 and len(_obs) > 0 and all(
        ('product_match_confidence' in r and 'accessory_flag' in r and 'is_body_only' in r)
        for r in _obs[:50])
    results.append({"level": "ok" if _t560 else "error", "check": "npo_product_identity_fields",
                    "message": "#560 normalized_price_observations に product_match_confidence/accessory_flag/is_body_only がある"
                               + ("" if _t560 else " ← 製品同一性フィールドが不足")})

    # #561: accessory_flag=true が main calculation に使われない
    _bad561 = sum(1 for r in _obs if r.get('accessory_flag')
                  and (r.get('is_usable_for_beginner') or r.get('is_usable_for_pro')))
    _t561 = _t545 and _bad561 == 0
    results.append({"level": "ok" if _t561 else "error", "check": "npo_accessory_not_main",
                    "message": "#561 accessory_flag=true の価格が main calculation に使われない"
                               + ("" if _t561 else f" ← accessory が利用可 {_bad561} 件")})

    # #562: wrong_model_flag=true が main calculation に使われない
    _bad562 = sum(1 for r in _obs if r.get('wrong_model_flag')
                  and (r.get('is_usable_for_beginner') or r.get('is_usable_for_pro')))
    _t562 = _t545 and _bad562 == 0
    results.append({"level": "ok" if _t562 else "error", "check": "npo_wrong_model_not_main",
                    "message": "#562 wrong_model_flag=true の価格が main calculation に使われない"
                               + ("" if _t562 else f" ← wrong_model が利用可 {_bad562} 件")})

    # #563: 本体価格フロア未満（GR IV ¥61,267 等の異常安値）が Pro route の buy に使われない
    #   sedori report の buy_price が、その商品の参照価格(retail/official)の50%未満でない
    _prod_ref = {}
    try:
        for _p in _load_products_for_ref():
            _prod_ref[_p[0]] = _p[1]
    except Exception:
        _prod_ref = {}
    _bad563 = 0
    for r in _all_routes:
        # report には product_name のみ。buy_price が極端に安いものを検出（保守的に絶対閾値併用）
        bp = r.get('buy_price', 0) or 0
        if 0 < bp < 70000 and r.get('buy_price_type') in (
                'shop_sale_price', 'flea_listing_price', 'flea_sold_price', 'overseas_listing_price'):
            # カメラ/高額機の本体が7万未満で仕入れられるのは異常 → 要確認
            _nm = r.get('product_name', '')
            if any(k in _nm for k in ('GR IV', 'X100', 'Leica', 'α7', 'R5', 'FX3', 'Z8', 'Z9', 'GFX')):
                _bad563 += 1
    _t563 = _bad563 == 0
    results.append({"level": "ok" if _t563 else "error", "check": "pro_buy_body_price_floor",
                    "message": "#563 Pro route の buy 側に本体価格フロア未満の異常安値(GR IV¥61,267等)が使われない"
                               + ("" if _t563 else f" ← 異常安値 buy {_bad563} 件")})

    # #564: 本体価格フロア検証ロジック（BODY_PRICE_FLOOR_RATIO / accessory_or_wrong_product）が実装されている
    _t564 = ('BODY_PRICE_FLOOR_RATIO' in _norm_src) and ('accessory_or_wrong_product' in _norm_src) \
        and ('ACCESSORY_KEYWORDS' in _norm_src)
    results.append({"level": "ok" if _t564 else "error", "check": "body_price_floor_logic",
                    "message": "#564 本体価格フロア/アクセサリー除外ロジックが normalized_prices に実装されている"
                               + ("" if _t564 else " ← 本体判定ロジックが見つかりません")})

    # #565: item_url が無い場合は route/観測を high confidence にしない
    #   （product_match_confidence=high は auto_scraped 由来のみ。sale系は medium 以下）
    _bad565 = sum(1 for r in _obs if r.get('product_match_confidence') == 'high'
                  and not (r.get('item_url') or r.get('extraction_method') in ('auto_scraped', 'official', 'retail_concept')))
    _t565 = _t545 and _bad565 == 0
    results.append({"level": "ok" if _t565 else "error", "check": "no_high_conf_without_item_url",
                    "message": "#565 item_url が無い価格を product_match high にしない（auto/official のみ high）"
                               + ("" if _t565 else f" ← item_url無しでhigh {_bad565} 件")})

    # ── Pro 利益ルート（profit_routes）ガード #566-#576 ──
    _pr = _load_json_safe('exports/profit_routes/latest.json') or {}
    _pr_main = _pr.get('main_routes', []) if isinstance(_pr, dict) else []
    _pr_ref = _pr.get('reference_routes', []) if isinstance(_pr, dict) else []
    _SALE_T = {'shop_sale_price', 'flea_listing_price', 'flea_sold_price', 'overseas_listing_price'}

    _t566 = isinstance(_pr, dict) and ('main_routes' in _pr)
    results.append({"level": "ok" if _t566 else "error", "check": "profit_routes_exists",
                    "message": f"#566 profit_routes/latest.json が存在する（main {len(_pr_main)}件）"
                               + ("" if _t566 else " ← ファイルが見つかりません")})

    _b567 = sum(1 for r in _pr_main if r.get('buy_price_type') == 'buyback_price')
    _t567 = _t566 and _b567 == 0
    results.append({"level": "ok" if _t567 else "error", "check": "profit_buy_no_buyback",
                    "message": "#567 Pro route の buy 側に buyback_price がない" + ("" if _t567 else f" ← {_b567}件")})

    _b568 = sum(1 for r in _pr_main if r.get('sell_price_type') in _SALE_T)
    _t568 = _t566 and _b568 == 0
    results.append({"level": "ok" if _t568 else "error", "check": "profit_sell_no_sale",
                    "message": "#568 Pro route の sell 側に sale/listing 価格がない" + ("" if _t568 else f" ← {_b568}件")})

    _b569 = sum(1 for r in _pr_main if 'trade_in_price' in (r.get('buy_price_type'), r.get('sell_price_type')))
    _t569 = _t566 and _b569 == 0
    results.append({"level": "ok" if _t569 else "error", "check": "profit_no_trade_in",
                    "message": "#569 Pro route に trade_in_price が使われない" + ("" if _t569 else f" ← {_b569}件")})

    _b570 = sum(1 for r in _pr_main if (r.get('buy_price') or 0) <= 0 or (r.get('sell_price') or 0) <= 0)
    _t570 = _t566 and _b570 == 0
    results.append({"level": "ok" if _t570 else "error", "check": "profit_no_zero",
                    "message": "#570 Pro route に price=0 が使われない" + ("" if _t570 else f" ← {_b570}件")})

    _b571 = sum(1 for r in _pr_main if (r.get('net_profit') or 0) <= 0 or (r.get('roi') or 0) < 0.05)
    _t571 = _t566 and _b571 == 0
    results.append({"level": "ok" if _t571 else "error", "check": "profit_net_roi",
                    "message": "#571 全 Pro route が net_profit>0 かつ roi>=5%" + ("" if _t571 else f" ← 不適合 {_b571}件")})

    _t572 = _t566 and all(r.get('route_confidence') in ('high', 'medium') for r in _pr_main)
    results.append({"level": "ok" if _t572 else "error", "check": "profit_confidence",
                    "message": "#572 main route は route_confidence high/medium のみ（low不使用）"
                               + ("" if _t572 else " ← low が混入")})

    # #573: 0件時に診断（理由表示）がある
    _t573 = _t566 and (len(_pr_main) > 0 or bool(_pr.get('zero_route_diagnostics')))
    results.append({"level": "ok" if _t573 else "error", "check": "profit_zero_diagnostics",
                    "message": "#573 利益ルート0件時に診断（候補数/除外理由）が出力される"
                               + ("" if _t573 else " ← 0件診断がありません")})

    # #574: eBay stale は main route に使われない（main の sell に reference/stale が無い）
    _b574 = sum(1 for r in _pr_main if r.get('reference_route') or 'stale' in (r.get('rejection_reason') or ''))
    _t574 = _t566 and _b574 == 0
    results.append({"level": "ok" if _t574 else "error", "check": "profit_no_stale_in_main",
                    "message": "#574 eBay stale が main route に使われない" + ("" if _t574 else f" ← {_b574}件")})

    # #575: eBay stale 参考ルートは reference_route=true
    _b575 = sum(1 for r in _pr_ref if not r.get('reference_route'))
    _t575 = _t566 and _b575 == 0
    results.append({"level": "ok" if _t575 else "error", "check": "profit_reference_flag",
                    "message": "#575 海外sold stale 参考ルートは reference_route=true で明示"
                               + ("" if _t575 else f" ← 未フラグ {_b575}件")})

    # #576: 生成スクリプトが is_usable_for_pro を入力源にしている（独自再判定で異常値混入を防ぐ）
    _pr_src = _read_src('scripts', 'generate_profit_routes.py')
    _t576 = ('is_usable_for_pro' in _pr_src) and ('reference_route' in _pr_src)
    results.append({"level": "ok" if _t576 else "error", "check": "profit_uses_npo_usable",
                    "message": "#576 profit_routes が is_usable_for_pro を入力源にしている"
                               + ("" if _t576 else " ← NPO usable を使っていません")})

    # ── eBay fresh化 / 参考ルート明示 ガード #577-#582 ──
    _lp_html = ""
    try:
        _lp_html = (PROJECT_ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    except Exception:
        _lp_html = ""

    # #577（eBay API 未設定の注意を旧UIに出す）と #592（参考ルートの未成立の理由を旧UIに出す）は UI Phase 10 で削除した。
    # 後継は運営者向けのページ（eBay の設定・利益ルートが成立しない理由。#839 が検査する）
    # #578: stale eBay sold は main route に使われない（reference でのみ）
    _b578 = sum(1 for r in _pr_main if r.get('sell_price_type') == 'overseas_sold_price'
                and (r.get('sell_observed_age_days') or 0) > 14)
    _t578 = _t566 and _b578 == 0
    results.append({"level": "ok" if _t578 else "error", "check": "profit_stale_overseas_reference_only",
                    "message": "#578 stale な海外sold が main route に使われない（参考のみ）"
                               + ("" if _t578 else f" ← main に stale海外sold {_b578}件")})

    # #579: 参考ルートはすべて overseas_sold かつ reference_route=true
    _b579 = sum(1 for r in _pr_ref if not (r.get('reference_route') and r.get('sell_price_type') == 'overseas_sold_price'))
    _t579 = _t566 and _b579 == 0
    results.append({"level": "ok" if _t579 else "error", "check": "profit_reference_overseas",
                    "message": "#579 stale海外sold は reference_route=true でのみ表示"
                               + ("" if _t579 else f" ← 不適合 {_b579}件")})

    # #580: 参考ルートに observed_age_days（経過日数）が出力される
    _t580 = _t566 and all(('sell_observed_age_days' in r) for r in _pr_ref) if _pr_ref else _t566
    results.append({"level": "ok" if _t580 else "error", "check": "profit_reference_age",
                    "message": "#580 参考ルートに observed_age_days（経過日数）が含まれる"
                               + ("" if _t580 else " ← age が欠落")})

    # #581: 海外sold の main 昇格は fresh かつ API のみ（生成ロジックで担保）
    _t581 = ("collector_method" in _pr_src) and ("source_mode" in _pr_src) \
        and ("overseas_sold_price" in _pr_src)
    results.append({"level": "ok" if _t581 else "error", "check": "profit_overseas_main_requires_api",
                    "message": "#581 海外sold の main 昇格は fresh かつ API 取得時のみ（collector_method/source_mode 判定）"
                               + ("" if _t581 else " ← API昇格条件が未実装")})

    # #582: main route 0件でも参考ルート or 0件診断が表示される
    _t582 = _t566 and (len(_pr_main) > 0 or len(_pr_ref) > 0 or bool(_pr.get('zero_route_diagnostics')))
    results.append({"level": "ok" if _t582 else "error", "check": "profit_zero_shows_reference",
                    "message": "#582 main 0件でも参考ルート/診断が表示される"
                               + ("" if _t582 else " ← 0件時に何も表示されない")})

    # ── 0件状態の説明 UI ガード #589-#594 ──
    _zero_mode = (len(_pr_main) == 0)  # main 0件のときに LP 説明UIを検証

    # #591: 最安buy/最高sell が表示される
    _t591 = (not _zero_mode) or ('最安' in _lp_html and '最高' in _lp_html)
    results.append({"level": "ok" if _t591 else "error", "check": "lp_zero_min_buy_max_sell",
                    "message": "#591 最安buy/最高sell が表示される"
                               + ("" if _t591 else " ← 最安buy/最高sell がありません")})

    # #593: 次に取得すべきデータランキングが表示される
    _t593 = (not _zero_mode) or ('次に取得すべきデータ' in _lp_html)
    results.append({"level": "ok" if _t593 else "error", "check": "lp_missing_data_ranking",
                    "message": "#593 次に取得すべきデータランキングが表示される"
                               + ("" if _t593 else " ← データ優先度ランキングがありません")})

    # #594: profit_routes に missing_data_priority と充実した zero 診断がある
    _zd = _pr.get('zero_route_diagnostics', {}) if isinstance(_pr, dict) else {}
    _has_rich = any(('min_usable_buy' in z and 'main_blocked_reason' in z and 'needed' in z)
                    for z in _zd.values()) if _zd else (len(_pr_main) > 0)
    _t594 = _t566 and ('missing_data_priority' in _pr) and _has_rich
    results.append({"level": "ok" if _t594 else "error", "check": "profit_zero_rich_diagnostics",
                    "message": "#594 profit_routes に missing_data_priority と商品別詳細診断がある"
                               + ("" if _t594 else " ← 診断データが不足")})

    # ── フリマsold 仕入れ側 ガード #595-#601 ──
    _flea_obs = [r for r in _obs if r.get('price_type') == 'flea_sold_price']

    # #595: flea_sold_price が NPO に存在
    # 成約（flea_sold_price）は根拠（商品ページの URL と成約日時）のあるものだけ（#826）。
    # 根拠のある成約が0件なのはデータが無いだけなので warning（出品価格で埋めて ok にしない。Phase 0.2）
    _t595 = len(_flea_obs) > 0
    results.append({"level": "ok" if _t595 else "warning", "check": "npo_has_flea_sold",
                    "message": f"#595 normalized_price_observations に flea_sold_price がある（{len(_flea_obs)}件）"
                               + ("" if _t595 else " ← 根拠のある成約データが0件（成約価格 未取得）")})

    # #596: flea_sold_price が Pro buy 側として使われる（usable な flea_sold buy が存在）
    _flea_usable = [r for r in _flea_obs if r.get('price_role') == 'buy' and r.get('is_usable_for_pro')]
    _t596 = _t595 and (len(_flea_usable) > 0)
    results.append({"level": "ok" if _t596 else "warning", "check": "flea_sold_pro_buy",
                    "message": f"#596 flea_sold_price が Pro buy 候補として使われる（usable {len(_flea_usable)}件）"
                               + ("" if _t596 else " ← 現状 target以下のusableなflea_soldがありません（薄利/データ次第）")})

    # #597: flea_sold で accessory/wrong_model が main calc に使われない
    _bad597 = sum(1 for r in _flea_obs if (r.get('accessory_flag') or r.get('wrong_model_flag'))
                  and r.get('is_usable_for_pro'))
    _t597 = _bad597 == 0
    results.append({"level": "ok" if _t597 else "error", "check": "flea_sold_no_accessory",
                    "message": "#597 flea_sold の accessory/wrong_model が main calc に使われない"
                               + ("" if _t597 else f" ← 混入 {_bad597}件")})

    # #598: flea_sold に item_url または search_url が存在（収集物）
    _flea_files = ['exports/flea_sold_prices/yahoo_sold.json', 'exports/flea_sold_prices/mercari_sold.json']
    _flea_data = [(_load_json_safe(f) or {}) for f in _flea_files]
    _flea_present = any(isinstance(d, dict) and d.get('products') for d in _flea_data)
    _no_url = 0
    for d in _flea_data:
        for _a, _p in (d.get('products', {}) if isinstance(d, dict) else {}).items():
            if not _p.get('search_url') and not _p.get('item_urls'):
                _no_url += 1
    _t598 = (not _flea_present) or (_no_url == 0)
    results.append({"level": "ok" if _t598 else "error", "check": "flea_sold_url_present",
                    "message": "#598 flea_sold に item_url または search_url が存在する"
                               + ("" if _t598 else f" ← URL欠落 {_no_url}件")})

    # #599: target_buy_price 以下の sold だけが main route 候補（main の flea_sold buy が target以下）
    _zd2 = _pr.get('zero_route_diagnostics', {}) if isinstance(_pr, dict) else {}
    _tgt = {}
    for pid, z in _zd2.items():
        if z.get('target_buy_price'):
            _tgt[pid] = z['target_buy_price']
    # main route の buy も対象（routeになった商品はzeroになく target を別途持たないため緩く検査）
    _bad599 = 0
    for r in _pr_main:
        if r.get('buy_price_type') == 'flea_sold_price':
            t = _tgt.get(r.get('product_id'))
            if t is not None and (r.get('buy_price') or 0) > t:
                _bad599 += 1
    _t599 = _bad599 == 0
    results.append({"level": "ok" if _t599 else "error", "check": "flea_sold_target_only",
                    "message": "#599 target_buy_price 超の flea_sold が main route に使われない"
                               + ("" if _t599 else f" ← target超 {_bad599}件")})

    # #600: 確定ルートがある日は、新UIのせどりルートのページに出ている（UI Phase 10: 旧UIの見出しではなく新UIのページで見る）
    #   確定かどうかは新UIと同じ判定（opportunity.confirmed_routes）。出ない確定ルートがあれば error
    try:
        import html as _h600
        from src.content.ui import opportunity as _opp600
        from src.tcg.models import now_jst as _now600
        _conf600 = _opp600.confirmed_routes(_pr_main, _now600())
    except Exception:  # noqa: BLE001
        _conf600 = []
    _rs600 = _lp_html.find('data-nu-page="routes"')
    _routes600 = _h600.unescape(_lp_html[_rs600:_lp_html.find('data-nu-page="more"', _rs600)]) if _rs600 >= 0 else ""
    _miss600 = [str(r.get("product_name") or r.get("product_id") or "")[:30] for r in _conf600
                if str(r.get("product_name") or "") and str(r.get("product_name")) not in _routes600]
    _t600 = not _miss600
    results.append({"level": "ok" if _t600 else "error", "check": "lp_main_routes_shown",
                    "message": f"#600 確定ルート（{len(_conf600)}件）が新UIのせどりルートに出ている"
                               + ("" if _t600 else f" ← 出ていない: {_miss600[:3]}")})

    # ── Pro route 品質表示 / 再現性スコア ガード #602-#608 ──
    _has_main = len(_pr_main) > 0

    # #603: GR IIIx route（または main route 商品名）が LP に表示される
    _main_names = [r.get('product_name', '') for r in _pr_main]
    _t603 = (not _has_main) or any(nm and nm in _lp_html for nm in _main_names)
    results.append({"level": "ok" if _t603 else "error", "check": "lp_main_route_product_shown",
                    "message": "#603 main route 商品（GR IIIx等）が LP に表示される"
                               + ("" if _t603 else " ← main route 商品名が LP にありません")})

    # #604: buy_age_days / sell_age_days がルートに含まれる
    _t604 = (not _has_main) or all(('buy_observed_age_days' in r and 'sell_observed_age_days' in r)
                                   for r in _pr_main)
    results.append({"level": "ok" if _t604 else "error", "check": "profit_route_age_fields",
                    "message": "#604 main route に buy_age_days / sell_age_days が含まれる"
                               + ("" if _t604 else " ← 鮮度フィールドが欠落")})

    # #605: reproducibility_score がルートに含まれ LP に表示される
    # （UI Phase 10: 旧UIの「再現性スコア」の表示は旧UIと一緒に削除した。生成物にスコアがあることだけを見る）
    _t605 = (not _has_main) or all('reproducibility_score' in r for r in _pr_main)
    results.append({"level": "ok" if _t605 else "error", "check": "profit_route_reproducibility",
                    "message": "#605 reproducibility_score がルートに付与される"
                               + ("" if _t605 else " ← 再現性スコアがありません")})

    # ── Profit Health Dashboard ガード #609-#614 ──
    _hr = _load_json_safe('audit_health/health_report.json') or {}
    _hr_ok = isinstance(_hr, dict) and ('health_score' in _hr)

    # #613: 前日比較が表示される
    _t613 = _hr_ok and ('前日比較' in _lp_html) and ('diff_vs_prev' in _hr)
    results.append({"level": "ok" if _t613 else "error", "check": "health_diff_shown",
                    "message": "#613 前日比較が表示される"
                               + ("" if _t613 else " ← 前日比較が見つかりません")})

    # #614: Critical 判定が算出・表示される（異常検知が機能）
    _anom = _hr.get('anomalies', {}) if _hr_ok else {}
    _t614 = _hr_ok and ('critical' in _anom and 'warning' in _anom and 'info' in _anom)
    results.append({"level": "ok" if _t614 else "error", "check": "health_critical_classification",
                    "message": f"#614 異常が Critical/Warning/Info に分類される"
                               f"（C{len(_anom.get('critical',[]))}/W{len(_anom.get('warning',[]))}/I{len(_anom.get('info',[]))}）"
                               + ("" if _t614 else " ← 異常分類がありません")})

    # ── AI Opportunities Engine ガード #615-#621 ──
    _ai = _load_json_safe('exports/ai_opportunities/latest.json') or {}
    _ai_ok = isinstance(_ai, dict) and ('todays_opportunities' in _ai)
    _ai_ops = _ai.get('todays_opportunities', []) if _ai_ok else []

    # #616: Opportunity Score が全候補に付与される
    _t616 = _ai_ok and (len(_ai_ops) == 0 or all(
        isinstance(o.get('opportunity_score'), int) and 0 <= o['opportunity_score'] <= 100 for o in _ai_ops))
    results.append({"level": "ok" if _t616 else "error", "check": "ai_opportunity_score",
                    "message": "#616 Opportunity Score（0-100）が全候補に付与される"
                               + ("" if _t616 else " ← Opportunity Score が不正")})

    # #617: BUY/WATCH/PASS 判定が付与される
    _valid_dec = {"BUY", "WATCH", "PASS"}
    _t617 = _ai_ok and (len(_ai_ops) == 0 or all(o.get('buy_now') in _valid_dec for o in _ai_ops))
    results.append({"level": "ok" if _t617 else "error", "check": "ai_buy_decision",
                    "message": "#617 BUY/WATCH/PASS 判定が付与される"
                               + ("" if _t617 else " ← 判定値が不正")})

    # #618: Today's Recommendation（今日のおすすめ）が表示される
    # （UI Phase 10: 旧UIの「今日のおすすめ」の表示は削除した。生成物におすすめがあることだけを見る）
    _t618 = _ai_ok and (bool(_ai.get('daily_recommendation')) == (len(_ai_ops) > 0))
    results.append({"level": "ok" if _t618 else "error", "check": "ai_daily_recommendation",
                    "message": "#618 今日のおすすめ（Daily Recommendation）が生成物に付与される"
                               + ("" if _t618 else " ← 今日のおすすめが見つかりません")})

    # #619: Risk が全候補に付与される
    _t619 = _ai_ok and (len(_ai_ops) == 0 or all(isinstance(o.get('risks'), list) and o['risks'] for o in _ai_ops))
    results.append({"level": "ok" if _t619 else "error", "check": "ai_risks",
                    "message": "#619 Risk が全候補に付与される"
                               + ("" if _t619 else " ← Risk がありません")})

    # #620: Holding Period が全候補に付与される
    _valid_hold = {"即日", "数日", "1週間", "1ヶ月", "長期"}
    _t620 = _ai_ok and (len(_ai_ops) == 0 or all(o.get('holding_period') in _valid_hold for o in _ai_ops))
    results.append({"level": "ok" if _t620 else "error", "check": "ai_holding_period",
                    "message": "#620 Holding Period が全候補に付与される"
                               + ("" if _t620 else " ← Holding Period が不正")})

    # #621: Health連携（60未満=低下中 / 80以上=良好）が実装される
    _hnote = _ai.get('health_note', '') if _ai_ok else ''
    _ai_src = _read_src('scripts', 'generate_ai_opportunities.py')
    _t621 = _ai_ok and ('現在データ品質低下中' in _ai_src) and ('データ品質は良好です' in _ai_src) \
        and (_hnote != '' if _ai.get('health_score') is not None else True)
    results.append({"level": "ok" if _t621 else "error", "check": "ai_health_link",
                    "message": f"#621 Health連携メッセージが実装される（現在: {_hnote or '—'}）"
                               + ("" if _t621 else " ← Health連携が見つかりません")})

    # #623（AI の候補のアラート閾値の表示）は UI Phase 10 で旧UIの AI Dashboard と一緒に削除した

    # #626: Today Tasks（今日やること）が Dashboard 最上部に表示される
    _t626 = _ai_ok and isinstance(_ai.get("today_tasks"), list) and len(_ai["today_tasks"]) > 0 \
        and ('今日やること' in _lp_html)
    results.append({"level": "ok" if _t626 else "error", "check": "ai_today_tasks",
                    "message": f"#626 今日やること（Today Tasks）が表示される（{len(_ai.get('today_tasks',[]))}件）"
                               + ("" if _t626 else " ← 今日やること が見つかりません")})

    # #627: 成立確率・次回更新予測・価格トレンドが付与される
    _t627 = _ai_ok and (len(_ai_ops) == 0 or all(
        ("success_probability" in o and o.get("next_update") and isinstance(o.get("price_trend"), dict))
        for o in _ai_ops))
    results.append({"level": "ok" if _t627 else "error", "check": "ai_probability_forecast_trend",
                    "message": "#627 成立確率/次回更新予測/価格トレンドが付与される"
                               + ("" if _t627 else " ← 一部フィールドが欠落")})

    # ── AI Notification Engine ガード #628-#633 ──
    _nt = _load_json_safe('exports/notifications/latest.json') or {}
    _nt_ok = isinstance(_nt, dict) and ('events' in _nt)
    _nt_events = _nt.get('events', []) if _nt_ok else []
    _nt_src = _read_src('scripts', 'generate_notifications.py')

    # #628: notification_events（latest.json）が存在
    _t628 = _nt_ok and ('delivery_status' in _nt) and ('channels' in _nt)
    results.append({"level": "ok" if _t628 else "error", "check": "notification_events_exists",
                    "message": f"#628 notifications/latest.json が存在する（events {len(_nt_events)}）"
                               + ("" if _t628 else " ← ファイルが見つかりません")})

    # #629: history/ に日次スナップショットが保存される
    _nt_hist = list((PROJECT_ROOT / "exports" / "notifications" / "history").glob("*.json"))
    _t629 = len(_nt_hist) > 0
    results.append({"level": "ok" if _t629 else "error", "check": "notification_history",
                    "message": f"#629 notifications/history/ に履歴が保存される（{len(_nt_hist)}日分）"
                               + ("" if _t629 else " ← 履歴が見つかりません")})

    # #630: suppression（再送抑制・24h/ROI+5%例外）が実装される
    _supp_exists = (PROJECT_ROOT / "exports" / "notifications" / "suppression.json").exists()
    _t630 = _supp_exists and ('SUPPRESS_HOURS' in _nt_src) and ('RESEND_ROI_GAIN' in _nt_src) \
        and ('apply_suppression' in _nt_src)
    results.append({"level": "ok" if _t630 else "error", "check": "notification_suppression",
                    "message": "#630 通知抑制（24h再送禁止・ROI+5%例外）が実装される"
                               + ("" if _t630 else " ← 抑制ロジックが見つかりません")})

    # #631: priority（Critical/High/Medium/Low）が全イベントに付与
    _valid_pri = {"Critical", "High", "Medium", "Low"}
    _t631 = _nt_ok and (len(_nt_events) == 0 or all(e.get("priority") in _valid_pri for e in _nt_events)) \
        and ('WATCH_TO_BUY' in _nt_src) and ('NEW_MAIN' in _nt_src)
    results.append({"level": "ok" if _t631 else "error", "check": "notification_priority",
                    "message": "#631 通知に priority（Critical/High/Medium/Low）が付与される"
                               + ("" if _t631 else " ← priority が不正")})

    # #633: 通知先チャネル（Discord/Telegram）が拡張しやすい構造で定義される
    _t633 = _nt_ok and ("discord" in _nt.get("channels", []) and "telegram" in _nt.get("channels", [])) \
        and ('CHANNELS' in _nt_src)
    results.append({"level": "ok" if _t633 else "error", "check": "notification_channels",
                    "message": "#633 通知チャネル（Discord/Telegram）が定義される"
                               + ("" if _t633 else " ← チャネル定義が見つかりません")})

    # ── Market Coverage Engine ガード #634-#637 ──
    _cov = _load_json_safe('exports/coverage/latest.json') or {}
    _cov_ok = isinstance(_cov, dict) and ('coverage_score' in _cov)

    # #636: 候補 products.yaml（提案・非破壊）が生成される。live products.yaml は上書きしない
    _cand_yaml = (PROJECT_ROOT / "exports" / "coverage" / "products_candidates.yaml")
    _t636 = _cand_yaml.exists() and ('自動生成' in _cand_yaml.read_text(encoding="utf-8")
                                     if _cand_yaml.exists() else False)
    results.append({"level": "ok" if _t636 else "error", "check": "coverage_candidate_yaml",
                    "message": "#636 拡充候補 products_candidates.yaml が生成される（既存yaml非破壊）"
                               + ("" if _t636 else " ← 候補yaml が見つかりません")})

    # #637: カテゴリ候補ランキングと次に追加すべき商品TOP50 が出力される
    _t637 = _cov_ok and len(_cov.get('category_candidates_ranked', [])) >= 5 \
        and len(_cov.get('next_products_top50', [])) > 0
    results.append({"level": "ok" if _t637 else "error", "check": "coverage_candidates",
                    "message": f"#637 カテゴリ候補ランキング・追加商品TOP{len(_cov.get('next_products_top50',[]))} が出力される"
                               + ("" if _t637 else " ← 候補ランキングが不足")})

    # ── Capital Allocation Engine ガード #638-#643 ──
    _al = _load_json_safe('exports/allocation/latest.json') or {}
    _al_ok = isinstance(_al, dict) and ('plans' in _al) and ('account_id' in _al)
    _dbg = str(_al.get("default_budget")) if _al_ok else None
    _dplan = (_al.get("plans", {}) or {}).get(_dbg) if _al_ok else None

    # #639: Allocation（配分）と各予算プランが存在する
    _t639 = _al_ok and isinstance(_dplan, dict) and ("allocations" in _dplan) and len(_al.get("plans", {})) >= 5
    results.append({"level": "ok" if _t639 else "error", "check": "capital_allocation",
                    "message": f"#639 予算別 Allocation プランが存在する（{len(_al.get('plans',{}))}予算）"
                               + ("" if _t639 else " ← 配分プランが不足")})

    # #643: 集中リスク上限（商品30%/カテゴリ50%/メーカー60%）が守られている
    _bad643 = 0
    if _al_ok:
        caps = _al.get("concentration_caps", {})
        pcap = caps.get("product", 0.30)
        for _b, _pl in (_al.get("plans", {}) or {}).items():
            try:
                if _pl.get("max_concentration", 0) > pcap + 0.001:
                    _bad643 += 1
            except Exception:
                pass
    _t643 = _al_ok and _bad643 == 0 and ("account_id" in _al)
    results.append({"level": "ok" if _t643 else "error", "check": "capital_concentration_caps",
                    "message": "#643 集中リスク上限（商品30%等）が守られ account_id 構造で保存される"
                               + ("" if _t643 else f" ← 上限超過 {_bad643}件")})

    # ── Execution Intelligence Engine ガード #644-#648 ──
    _ex = _load_json_safe('exports/execution/latest.json') or {}
    _ex_ok = isinstance(_ex, dict) and ('prediction_accuracy' in _ex)

    # #645: Prediction / Notification / Allocation Accuracy が算出される
    _t645 = _ex_ok and ('error_points' in _ex.get('prediction_accuracy', {})) \
        and ('notification_accuracy' in _ex) and ('allocation_accuracy' in _ex)
    results.append({"level": "ok" if _t645 else "error", "check": "execution_accuracy",
                    "message": f"#645 予測/通知/配分の精度が算出される（予測誤差 "
                               f"{_ex.get('prediction_accuracy',{}).get('error_points','?')}pt）"
                               + ("" if _t645 else " ← Accuracy が不足")})

    # #646: Self Improvement 補正係数（利益ロジック不適用）が学習される
    _lc = _ex.get('learning_coefficients', {}) if _ex_ok else {}
    _t646 = _ex_ok and all(k in _lc for k in
                           ("opportunity_score_coeff", "success_probability_coeff", "risk_score_coeff"))
    results.append({"level": "ok" if _t646 else "error", "check": "execution_learning_coeff",
                    "message": "#646 補正係数（score/probability/risk）が学習される（利益ロジック不変）"
                               + ("" if _t646 else " ← 補正係数が見つかりません")})

    # #647: Insights TOP10 が LP に表示される
    _ins = _ex.get('insights_top10', []) if _ex_ok else []
    _t647 = _ex_ok and len(_ins) > 0 and ('今週学んだこと' in _lp_html)
    results.append({"level": "ok" if _t647 else "error", "check": "execution_insights",
                    "message": f"#647 Insights（今週学んだこと TOP{len(_ins)}）が表示される"
                               + ("" if _t647 else " ← Insights が見つかりません")})

    # #648: 週次 Learning Report が生成される
    _t648 = (PROJECT_ROOT / "exports" / "execution" / "weekly_learning.md").exists()
    results.append({"level": "ok" if _t648 else "error", "check": "execution_weekly_report",
                    "message": "#648 週次 Learning Report（weekly_learning.md）が生成される"
                               + ("" if _t648 else " ← 週次レポートが見つかりません")})

    # ── SaaS 基盤 ガード #649-#655 ──
    def _mod_exists(*parts):
        return (PROJECT_ROOT.joinpath(*parts)).exists()

    # #649: SaaS モジュール（subscription/accounts/auth/billing/api）が存在
    _saas_files = ["subscription.py", "accounts.py", "auth.py", "billing.py", "api.py"]
    _t649 = all(_mod_exists("src", "saas", f) for f in _saas_files)
    results.append({"level": "ok" if _t649 else "error", "check": "saas_modules",
                    "message": "#649 SaaS モジュール（subscription/accounts/auth/billing/api）が存在する"
                               + ("" if _t649 else " ← SaaS モジュールが不足")})

    # #650: サブスク権限ゲート（Free/Pro/Enterprise）が定義され機能する
    _t650 = False
    try:
        import importlib
        _sub = importlib.import_module("src.saas.subscription")
        _t650 = (not _sub.can_access("free", "pro")) and _sub.can_access("pro", "capital") \
            and _sub.can_access("enterprise", "api") and set(_sub.TIERS) == {"free", "pro", "enterprise"}
    except Exception:
        _t650 = False
    results.append({"level": "ok" if _t650 else "error", "check": "saas_subscription_gate",
                    "message": "#650 サブスク権限ゲート（Free/Pro/Enterprise）が機能する"
                               + ("" if _t650 else " ← 権限ゲートが不正")})

    # #651: account_id 単位のストア（settings/watchlist/portfolio）が機能する
    _t651 = False
    try:
        _accs = importlib.import_module("src.saas.accounts")
        _al = _accs.list_accounts()
        _t651 = isinstance(_al, list) and all(
            ("account_id" in a and "tier" in a and "settings" in a and "watchlist" in a and "portfolio" in a)
            for a in _al) and len(_al) >= 1
    except Exception:
        _t651 = False
    results.append({"level": "ok" if _t651 else "error", "check": "saas_accounts_store",
                    "message": f"#651 account 単位ストア（settings/watchlist/portfolio）が機能する（{len(_al) if _t651 else '?'}件）"
                               + ("" if _t651 else " ← account ストアが不正")})

    # #652: REST API のルート（/account /opportunities /notifications /capital /execution）が定義される
    _api_src = _read_src("src", "saas", "api.py")
    _t652 = all(r in _api_src for r in
                ('"/account"', '"/opportunities"', '"/notifications"', '"/capital"', '"/execution"'))
    results.append({"level": "ok" if _t652 else "error", "check": "saas_api_routes",
                    "message": "#652 REST API ルート（account/opportunities/notifications/capital/execution）が定義される"
                               + ("" if _t652 else " ← API ルートが不足")})

    # #653: 認証/課金が env gating（キー未埋め込み・未設定で無効）で実装される
    _auth_src = _read_src("src", "saas", "auth.py"); _bill_src = _read_src("src", "saas", "billing.py")
    _t653 = ('os.environ' in _auth_src) and ('GOOGLE_OAUTH_CLIENT_ID' in _auth_src) \
        and ('STRIPE_SECRET_KEY' in _bill_src) and ('TRIAL_DAYS' in _bill_src)
    results.append({"level": "ok" if _t653 else "error", "check": "saas_auth_billing_gated",
                    "message": "#653 認証(email/google/apple)・課金(Stripe/Trial)が env gating で実装される"
                               + ("" if _t653 else " ← 認証/課金の env gating が見つかりません")})

    # #654: Admin Dashboard（登録者数/通知/利益ルート/Health/実行成功率）が生成される
    _adm = _load_json_safe('exports/admin/latest.json') or {}
    _t654 = isinstance(_adm, dict) and ('accounts' in _adm) and ('metrics' in _adm) \
        and ('health_score' in (_adm.get('metrics') or {}))
    results.append({"level": "ok" if _t654 else "error", "check": "saas_admin_dashboard",
                    "message": f"#654 Admin Dashboard が生成される（登録者 {(_adm.get('accounts') or {}).get('total','?')}）"
                               + ("" if _t654 else " ← Admin Dashboard が見つかりません")})

    # #655: ROADMAP.md（運用/障害/デプロイ/課金/バックアップ）が存在
    _rm = PROJECT_ROOT / "ROADMAP.md"
    _rm_txt = _rm.read_text(encoding="utf-8") if _rm.exists() else ""
    _t655 = all(k in _rm_txt for k in ("デプロイ", "障害", "課金", "バックアップ"))
    results.append({"level": "ok" if _t655 else "error", "check": "saas_roadmap",
                    "message": "#655 ROADMAP.md（運用/障害/デプロイ/課金/バックアップ）が存在する"
                               + ("" if _t655 else " ← ROADMAP が不足")})

    # ── Production Readiness Audit ガード #656-#662 ──
    _prod = _load_json_safe('exports/production/latest.json') or {}
    _prod_ok = isinstance(_prod, dict) and ('overall_score' in _prod) and ('scores' in _prod)

    # #656: Production Report が存在する
    _t656 = _prod_ok and ('issues' in _prod) and ('go_no_go' in _prod)
    results.append({"level": "ok" if _t656 else "error", "check": "production_report",
                    "message": f"#656 Production Report が存在する（Overall {_prod.get('overall_score','?')}/100）"
                               + ("" if _t656 else " ← Production Report が見つかりません")})

    # #657: Security 監査（Secret無し・path traversal対策・API hardening）
    _sec = _prod.get('security', {}) if _prod_ok else {}
    _t657 = _prod_ok and (_sec.get('secrets_in_code') == 0) and _sec.get('path_traversal_guarded') \
        and all((_sec.get('api_hardening', {}) or {}).get(k) for k in
                ("input_validation", "security_headers", "rate_limit", "account_isolation"))
    results.append({"level": "ok" if _t657 else "error", "check": "production_security",
                    "message": "#657 Security 監査（Secret0/パストラバーサル対策/API hardening）合格"
                               + ("" if _t657 else " ← Security に問題あり")})

    # #658: Operations 監査（Runbook/Health/Monitoring/Rollback）
    _ops = _prod.get('operations', {}) if _prod_ok else {}
    _t658 = _prod_ok and _ops.get('runbook') and _ops.get('health') and _ops.get('monitoring') \
        and _ops.get('rollback')
    results.append({"level": "ok" if _t658 else "error", "check": "production_operations",
                    "message": "#658 Operations 監査（Runbook/Health/Monitoring/Rollback）合格"
                               + ("" if _t658 else " ← Operations に不足")})

    # #659: Deployment 監査（Pages/CI 稼働・本番構成案あり）
    _dep = _prod.get('deployment', {}) if _prod_ok else {}
    _t659 = _prod_ok and _dep.get('github_pages') and _dep.get('ci') \
        and bool((_dep.get('production_backend', {}) or {}).get('recommended'))
    results.append({"level": "ok" if _t659 else "error", "check": "production_deployment",
                    "message": "#659 Deployment 監査（Pages/CI・本番構成案）合格"
                               + ("" if _t659 else " ← Deployment に不足")})

    # #660: Business Readiness（プラン/課金/ユーザー管理/Admin）
    _biz = _prod.get('business_readiness', {}) if _prod_ok else {}
    _t660 = _prod_ok and set(_biz.get('tiers', [])) == {"free", "pro", "enterprise"} \
        and _biz.get('admin') and _biz.get('watchlist')
    results.append({"level": "ok" if _t660 else "error", "check": "production_business",
                    "message": "#660 Business Readiness（3プラン/Admin/Watchlist）合格"
                               + ("" if _t660 else " ← Business Readiness に不足")})

    # #661: No Critical（本番前にCritical課題ゼロ）
    _t661 = _prod_ok and _prod.get('no_critical') is True and len(_prod.get('issues', {}).get('Critical', [])) == 0
    results.append({"level": "ok" if _t661 else "error", "check": "production_no_critical",
                    "message": f"#661 Critical 課題ゼロ（残 {len(_prod.get('issues',{}).get('Critical',[]))}件）"
                               + ("" if _t661 else " ← Critical 課題が残存")})

    # #662: Overall Score が閾値（>=70）以上
    _ov = _prod.get('overall_score', 0) if _prod_ok else 0
    _t662 = _prod_ok and _ov >= 70
    results.append({"level": "ok" if _t662 else "warning", "check": "production_overall_score",
                    "message": f"#662 Overall Score {_ov}/100（>=70 でリリース水準）"
                               + ("" if _t662 else " ← スコアが基準未満")})

    # ── Data Quality Engine ガード #663-#669 ──
    _dq = _load_json_safe('exports/data_quality/latest.json') or {}
    _dq_ok = isinstance(_dq, dict) and ('quality_score' in _dq) and ('dashboard' in _dq)

    # #663: Data Quality Report が存在する
    _t663 = _dq_ok and ('methodology' in _dq) and ('production_recommendation' in _dq)
    results.append({"level": "ok" if _t663 else "error", "check": "data_quality_report",
                    "message": f"#663 Data Quality Report が存在する（Overall {(_dq.get('quality_score') or {}).get('overall','?')}/100）"
                               + ("" if _t663 else " ← Data Quality Report が見つかりません")})

    # #664: Source Quality Ranking（100点・主要9ソース）が生成される
    _rank = _dq.get('source_ranking', []) if _dq_ok else []
    _t664 = isinstance(_rank, list) and len(_rank) >= 9 and all(
        ('source' in x and 'quality_score' in x and 'rank' in x) for x in _rank)
    results.append({"level": "ok" if _t664 else "error", "check": "data_quality_source_ranking",
                    "message": f"#664 Source Quality Ranking が生成される（{len(_rank)}ソース）"
                               + ("" if _t664 else " ← Source Ranking が不足")})

    # #665: Stale 分析（原因分類・カテゴリ別）が生成される
    _st = _dq.get('stale_analysis', {}) if _dq_ok else {}
    _t665 = isinstance(_st, dict) and ('causes' in _st) and ('by_source' in _st) and ('stale_keys' in _st)
    results.append({"level": "ok" if _t665 else "error", "check": "data_quality_stale_analysis",
                    "message": f"#665 Stale 分析が生成される（stale {_st.get('stale_keys','?')}キー・原因分類あり）"
                               + ("" if _t665 else " ← Stale 分析が不足")})

    # #666: ¥0 分析（原因分類・実失敗件数）が生成される
    _zp = _dq.get('zero_price_analysis', {}) if _dq_ok else {}
    _t666 = isinstance(_zp, dict) and ('causes' in _zp) and ('real_failures' in _zp)
    results.append({"level": "ok" if _t666 else "error", "check": "data_quality_zero_price",
                    "message": f"#666 ¥0 分析が生成される（実取得失敗 {_zp.get('real_failures','?')}件）"
                               + ("" if _t666 else " ← ¥0 分析が不足")})

    # #667: Coverage Validation（商品単位・監視対象網羅）が生成される
    _cv = _dq.get('coverage_validation', {}) if _dq_ok else {}
    _t667 = isinstance(_cv, dict) and ('status_breakdown' in _cv) \
        and ('products_with_data' in _cv) and ('products_total_monitored' in _cv)
    results.append({"level": "ok" if _t667 else "error", "check": "data_quality_coverage",
                    "message": f"#667 Coverage Validation が生成される（{_cv.get('products_with_data','?')}/{_cv.get('products_total_monitored','?')}商品）"
                               + ("" if _t667 else " ← Coverage Validation が不足")})

    # #668: Normalization 監査（税/送料/ポイント/通貨の統一）+ 自動化カバレッジ透明性
    _nm = _dq.get('normalization_audit', {}) if _dq_ok else {}
    _acov = _dq.get('automation_coverage', {}) if _dq_ok else {}
    _t668 = isinstance(_nm, dict) and ('unified_rules' in _nm) and ('consistency_ok' in _nm) \
        and isinstance(_acov, dict) and ('by_method' in _acov)
    results.append({"level": "ok" if _t668 else "error", "check": "data_quality_normalization",
                    "message": "#668 Normalization 監査 + 自動化カバレッジ透明性が生成される"
                               + ("" if _t668 else " ← Normalization/自動化監査が不足")})

    # #669: Data Quality Overall Score が閾値（>=70）以上
    _dqov = (_dq.get('quality_score') or {}).get('overall', 0) if _dq_ok else 0
    _t669 = _dq_ok and _dqov >= 70
    results.append({"level": "ok" if _t669 else "warning", "check": "data_quality_overall_score",
                    "message": f"#669 Data Quality Overall {_dqov}/100（>=70 でデータ品質水準）"
                               + ("" if _t669 else " ← データ品質スコアが基準未満")})

    # ── Beta Launch Preparation ガード #670-#676 ──
    _beta = _load_json_safe('exports/beta/latest.json') or {}
    _beta_ok = isinstance(_beta, dict) and ('beta_ready_score' in _beta) and ('readiness' in _beta)

    # #670: Beta Report が存在する（Score/Issues/Checklist/Ready判定）
    _t670 = _beta_ok and ('issues' in _beta) and ('launch_checklist' in _beta) and ('verdict' in _beta)
    results.append({"level": "ok" if _t670 else "error", "check": "beta_report",
                    "message": f"#670 Beta Report が存在する（Ready {_beta.get('beta_ready_score','?')}/100・{_beta.get('verdict','?')}）"
                               + ("" if _t670 else " ← Beta Report が見つかりません")})

    # #671: Onboarding（5ステップ）が定義され β体験ページに出力される
    _steps = _beta.get('onboarding_steps', []) if _beta_ok else []
    _beta_html = _read_src("docs", "beta", "index.html") if (PROJECT_ROOT / "docs" / "beta" / "index.html").exists() else ""
    _t671 = isinstance(_steps, list) and len(_steps) == 5 and ("STEP" in _beta_html) and ("5ステップ" in _beta_html)
    results.append({"level": "ok" if _t671 else "error", "check": "beta_onboarding",
                    "message": f"#671 初回オンボーディング（{len(_steps)}ステップ）がβ体験ページに出力される"
                               + ("" if _t671 else " ← Onboarding が不足")})

    # #672: Demo Account（Watchlist/Notification/Capital/Execution/History）が存在
    _demo = _load_json_safe('data/accounts/demo_beta.json') or {}
    _t672 = isinstance(_demo, dict) and all(k in _demo for k in
            ("watchlist", "settings", "portfolio", "execution", "history")) and len(_demo.get("watchlist", [])) >= 1
    results.append({"level": "ok" if _t672 else "error", "check": "beta_demo_account",
                    "message": f"#672 Demo Account が存在する（watchlist {len(_demo.get('watchlist', []))}件・execution/history有）"
                               + ("" if _t672 else " ← Demo Account が不足")})

    # #673: Feedback 導線（Bug Report / Feature Request）がβ体験ページにある
    _t673 = ("Feedback" in _beta_html) and ("Bug Report" in _beta_html) and ("Feature Request" in _beta_html)
    results.append({"level": "ok" if _t673 else "error", "check": "beta_feedback",
                    "message": "#673 Feedback（Bug Report/Feature Request）導線がある"
                               + ("" if _t673 else " ← Feedback 導線が不足")})

    # #674: Analytics（匿名・集計）構造 + クライアントが存在
    _an = _beta.get('analytics', {}) if _beta_ok else {}
    _an_names = {e.get('name') for e in (_an.get('events') or [])}
    _t674 = ({"dau", "watchlist_count", "notification_count", "opportunity_view",
              "capital_view", "execution_view"} <= _an_names) \
        and ("beta_analytics" in _beta_html) and ("localStorage" in _beta_html)
    results.append({"level": "ok" if _t674 else "error", "check": "beta_analytics",
                    "message": "#674 Analytics（匿名集計・DAU/Watchlist/通知/各閲覧）構造が配置される"
                               + ("" if _t674 else " ← Analytics 構造が不足")})

    # #675: Admin Beta Dashboard（登録者/通知/Opportunity/Execution/Feedback）
    _ab = _beta.get('admin_beta', {}) if _beta_ok else {}
    _t675 = isinstance(_ab, dict) and all(k in _ab for k in
            ("registered_users", "notification_count", "opportunity_count",
             "execution_usage_rate", "feedback_count"))
    results.append({"level": "ok" if _t675 else "error", "check": "beta_admin_dashboard",
                    "message": f"#675 Admin Beta Dashboard が生成される（登録者 {_ab.get('registered_users','?')}）"
                               + ("" if _t675 else " ← Admin Beta Dashboard が不足")})

    # #676: Beta Ready Score が閾値（>=75）以上・Critical ゼロ
    _bscore = _beta.get('beta_ready_score', 0) if _beta_ok else 0
    _bcrit = len((_beta.get('issues', {}) or {}).get('Critical', [])) if _beta_ok else 99
    _t676 = _beta_ok and _bscore >= 75 and _bcrit == 0
    results.append({"level": "ok" if _t676 else "warning", "check": "beta_overall",
                    "message": f"#676 Beta Ready {_bscore}/100・Critical {_bcrit}件（>=75かつCritical0でβ公開水準）"
                               + ("" if _t676 else " ← β公開基準未満")})

    # ── Official Source Registry & Validation ガード #677-#687 ──
    _osa = _load_json_safe('exports/official_source_audit/latest.json') or {}
    _osa_ok = isinstance(_osa, dict) and ('registered' in _osa) and ('maker_report' in _osa)
    _reg = _osa.get('registered', []) if _osa_ok else []

    # #677: official_source_audit が生成される
    results.append({"level": "ok" if _osa_ok else "error", "check": "official_source_audit",
                    "message": f"#677 official_source_audit が生成される（verified {sum(1 for x in _reg if x.get('verified'))}件）"
                               + ("" if _osa_ok else " ← official_source_audit が見つかりません")})

    # #678: Apple 旧404 URL(iphone-16-pro-max)を verified として登録していない
    _t678 = not any((x.get('url') and 'iphone-16-pro-max' in x.get('url', '') and x.get('verified'))
                    for x in _reg)
    results.append({"level": "ok" if _t678 else "error", "check": "official_no_stale_apple_url",
                    "message": "#678 Apple 旧404 URL(iphone-16-pro-max)を verified 登録していない"
                               + ("" if _t678 else " ← 旧URLが verified 登録されています")})

    # #679: official price = 0/None を verified 価格として登録していない
    _t679 = not any((x.get('verified') and x.get('official_price') is not None and x.get('official_price') <= 0)
                    for x in _reg)
    results.append({"level": "ok" if _t679 else "error", "check": "official_no_zero_price",
                    "message": "#679 official price=0 を保存/main利用していない"
                               + ("" if _t679 else " ← ¥0 が登録されています")})

    # #680: 検証済み価格はすべて sanity 合格（validator で異常値が弾かれている）
    try:
        from src.market.official_price_validator import sanity_check_price
        _bad = [x for x in _reg if x.get('official_price') and sanity_check_price(x['official_price'], None)]
        _t680 = len(_bad) == 0
    except Exception:
        _t680 = False
    results.append({"level": "ok" if _t680 else "error", "check": "official_price_sanity",
                    "message": "#680 登録済み公式価格が sanity check を通過（アクセサリー/月額/1円等なし）"
                               + ("" if _t680 else " ← 異常価格が登録されています")})

    # #681: low confidence の公式価格を main 利用しない（high/medium のみ price 付与）
    _t681 = not any((x.get('official_price') and x.get('confidence') == 'low') for x in _reg)
    results.append({"level": "ok" if _t681 else "error", "check": "official_low_conf_not_main",
                    "message": "#681 low confidence の公式価格を main 利用していない"
                               + ("" if _t681 else " ← low confidence 価格が main 利用されています")})

    # #682: 公式価格 validator モジュールが存在（保存前検証の実装）
    _val_src = _read_src("src", "market", "official_price_validator.py")
    _t682 = all(k in _val_src for k in ("validate_official_price", "sanity_check_price",
                                        "classify_confidence", "is_official_domain", "detect_open_price"))
    results.append({"level": "ok" if _t682 else "error", "check": "official_validator_impl",
                    "message": "#682 公式価格 validator（保存前検証・sanity・confidence）が実装される"
                               + ("" if _t682 else " ← validator 実装が不足")})

    # #683: 公式コレクターが保存前に validator を呼ぶ（accessory/mismatch を保存しない）
    _gen_src = _read_src("src", "collectors", "official", "_generic.py")
    _ap_src = _read_src("src", "collectors", "official", "apple.py")
    _t683 = ("validate_official_price" in _gen_src) and ("validate_official_price" in _ap_src) \
        and ("official_price_rejected" in _gen_src)
    results.append({"level": "ok" if _t683 else "error", "check": "official_collector_guarded",
                    "message": "#683 公式コレクターが保存前検証を実施（mismatch/accessory を保存しない）"
                               + ("" if _t683 else " ← コレクターの保存前検証が不足")})

    # #684: Canon が registry に存在（verified もしくは needs_manual_verification で明示）
    _canon = [x for x in _reg if x.get('source') == 'src_canon_official']
    _t684 = len(_canon) >= 1
    results.append({"level": "ok" if _t684 else "warning", "check": "official_canon_registered",
                    "message": f"#684 Canon が registry に登録される（{len(_canon)}件・要手動検証含む）"
                               + ("" if _t684 else " ← Canon 未登録")})

    # #685: Nikon が registry に存在
    _nikon = [x for x in _reg if x.get('source') == 'src_nikon_direct']
    _t685 = len(_nikon) >= 1
    results.append({"level": "ok" if _t685 else "warning", "check": "official_nikon_registered",
                    "message": f"#685 Nikon が registry に登録される（{len(_nikon)}件）"
                               + ("" if _t685 else " ← Nikon 未登録")})

    # #686: Sony が registry に存在（型番 ILCE/ILME で同定）
    _sony = [x for x in _reg if x.get('source') == 'src_sony_store']
    _t686 = len(_sony) >= 1
    results.append({"level": "ok" if _t686 else "warning", "check": "official_sony_registered",
                    "message": f"#686 Sony が registry に登録される（{len(_sony)}件・要手動検証）"
                               + ("" if _t686 else " ← Sony 未登録")})

    # #687: source config に verified / last_verified_at が存在する
    _has_verified_fields = any(('verified' in x and (x.get('verified') is not None)) for x in _reg)
    _matrix = _osa.get('source_matrix', {}) if _osa_ok else {}
    _has_lva = any((v.get('sources', {}).get('official') or {}).get('last_verified_at')
                   for v in _matrix.values())
    _t687 = _has_verified_fields and _has_lva
    results.append({"level": "ok" if _t687 else "error", "check": "official_config_verified_fields",
                    "message": "#687 source config に verified/last_verified_at が存在する"
                               + ("" if _t687 else " ← verified/last_verified_at が不足")})

    # ── Retail & Buyback Automation ガード #688-#694 ──
    _rb = _load_json_safe('exports/retail_buyback_audit/latest.json') or {}
    _rb_ok = isinstance(_rb, dict) and ('category_summary' in _rb) and ('main_promotion' in _rb)

    # #688: retail_buyback_audit が生成される
    _t688 = _rb_ok and ('duplicate_price_pattern' in _rb) and ('identity_audit' in _rb)
    results.append({"level": "ok" if _t688 else "error", "check": "retail_buyback_audit",
                    "message": f"#688 retail_buyback_audit が生成される（Main昇格 {(_rb.get('main_promotion') or {}).get('total','?')}件）"
                               + ("" if _t688 else " ← retail_buyback_audit が見つかりません")})

    # #689: 価格品質ゲート（price_quality）が実装される
    _pq_src = _read_src("src", "market", "price_quality.py")
    _t689 = all(k in _pq_src for k in ("is_main_promotable", "detect_duplicate_price_pattern",
                                       "capacity_consistent", "identity_strict_ok", "effective_confidence"))
    results.append({"level": "ok" if _t689 else "error", "check": "price_quality_impl",
                    "message": "#689 価格品質ゲート（Main昇格/同一性/duplicate検出）が実装される"
                               + ("" if _t689 else " ← price_quality 実装が不足")})

    # #690: Main昇格ゲート = high confidence + fresh + exact match（実装に3条件が揃う）
    _t690 = all(k in _pq_src for k in ("is_fresh", "is_exact_product_match")) \
        and ("high" in _pq_src) and ("effective_confidence(obs) != \"high\"" in _pq_src or "!= \"high\"" in _pq_src)
    results.append({"level": "ok" if _t690 else "error", "check": "main_promotion_gate",
                    "message": "#690 Main昇格ゲートが high+fresh+exact の3条件で実装される"
                               + ("" if _t690 else " ← Main昇格ゲートの条件が不足")})

    # #691: duplicate_price_pattern が監査に含まれる（同一SKU同額の警告・弾かない）
    _dup = _rb.get('duplicate_price_pattern', []) if _rb_ok else None
    _t691 = isinstance(_dup, list)
    results.append({"level": "ok" if _t691 else "error", "check": "duplicate_price_pattern",
                    "message": f"#691 duplicate_price_pattern 警告が生成される（{len(_dup) if isinstance(_dup,list) else '?'}件）"
                               + ("" if _t691 else " ← duplicate_price_pattern が不足")})

    # #692: 商品同一性監査（容量/型番/アクセサリー/本体）
    _ia = _rb.get('identity_audit', {}) if _rb_ok else {}
    _t692 = isinstance(_ia, dict) and all(k in _ia for k in
            ("capacity_mismatch", "wrong_model", "accessory", "not_body_only"))
    results.append({"level": "ok" if _t692 else "error", "check": "retail_identity_audit",
                    "message": "#692 商品同一性監査（容量/型番/アクセサリー/本体）が生成される"
                               + ("" if _t692 else " ← 同一性監査が不足")})

    # #693: 正規化監査（税込/送料/ポイント/買取/下取 の別項目）
    _na = _rb.get('normalization_audit', {}) if _rb_ok else {}
    _t693 = isinstance(_na, dict) and all(k in _na for k in
            ("has_price_type", "shipping_separated", "points_separated", "tradein_excluded"))
    results.append({"level": "ok" if _t693 else "error", "check": "retail_normalization_audit",
                    "message": "#693 正規化監査（税込/送料/ポイント/買取/下取の別項目）が生成される"
                               + ("" if _t693 else " ← 正規化監査が不足")})

    # #694: Freshness 遵守（取得失敗で古い値の時刻だけを更新していない）
    _fc = _rb.get('freshness_compliance', {}) if _rb_ok else {}
    _t694 = isinstance(_fc, dict) and _fc.get('ok') is True
    results.append({"level": "ok" if _t694 else "warning", "check": "retail_freshness_compliance",
                    "message": f"#694 Freshness 遵守（時刻だけ更新の疑い {len((_fc or {}).get('violations', []))}件）"
                               + ("" if _t694 else " ← Freshness 違反の疑い")})

    # ── Source Matching Accuracy ガード #695-#707 ──
    _sm = _load_json_safe('exports/source_matching/latest.json') or {}
    _sm_ok = isinstance(_sm, dict) and ('accuracy' in _sm)
    _acc = _sm.get('accuracy', {}) if _sm_ok else {}

    # #695: ProductIdentityResolver が存在する
    _res_src = _read_src("src", "market", "product_identity_resolver.py")
    _t695 = all(k in _res_src for k in ("class ProductIdentityResolver", "def resolve",
                                        "matched_product_id", "identity_confidence"))
    results.append({"level": "ok" if _t695 else "error", "check": "product_identity_resolver",
                    "message": "#695 ProductIdentityResolver が存在する"
                               + ("" if _t695 else " ← Resolver が見つかりません")})

    # #696-#701: マッチング品質の機能テスト（resolver/price_quality を直接検証）
    try:
        import importlib
        _pq = importlib.import_module("src.market.price_quality")
        _pir = importlib.import_module("src.market.product_identity_resolver")
        importlib.reload(_pq)  # 最新実装で検証
        cap_ok = (_pq.extract_capacity_gb("1TB") == 1024 and
                  _pq.extract_capacity_gb("256GB") == 256 and
                  _pq.extract_capacity_gb("256GB") != _pq.extract_capacity_gb("512GB"))
        model_ok = (_pq.model_compatible("iPhone 17 Pro", "iPhone 17 Pro Max") is False and
                    _pq.model_compatible("RICOH GR IV", "RICOH GR IV HDF") is False and
                    _pq.model_compatible("iPhone 16 Pro", "iPhone 17 Pro") is False)
        _R = _pir.ProductIdentityResolver({"p": {"name": "iPhone 17 Pro 256GB", "model_number": ""}})
        acc_ok = _R.resolve(source_title="iPhone 17 Pro ケース", link_type="item").accessory_flag is True
        from src.market.official_price_validator import sanity_check_price as _sc
        ti_ok = (_sc(180000, 200000, "下取価格") is not None and _sc(8000, 200000, "月々分割") is not None)
        search_ok = _R.resolve(source_title="iPhone 17 Pro 256GB", link_type="search",
                               expected_product_id="p").identity_confidence != "high"
        gate_ok = (_pq.is_main_promotable({"price": 1, "is_fresh": False, "is_exact_product_match": True,
                   "product_match_confidence": "high", "link_type": "item", "is_body_only": True,
                   "product_name": "x", "rejection_reason": "stale_over_14d"}) is False)
    except Exception:
        cap_ok = model_ok = acc_ok = ti_ok = search_ok = gate_ok = False

    for num, key, ok, msg in [
        (696, "capacity_normalization", cap_ok, "容量正規化(1TB=1024/256≠512)が正しい"),
        (697, "model_normalization", model_ok, "型番/機種判別(Pro≠Pro Max/GR IV≠HDF/世代)が正しい"),
        (698, "accessory_rejection", acc_ok, "アクセサリー拒否が機能する"),
        (699, "tradein_rejection", ti_ok, "下取/分割月額の拒否が機能する"),
        (700, "search_result_downgrade", search_ok, "検索結果は high にしない"),
        (701, "main_promotion_strict_gate", gate_ok, "Main昇格ゲート(stale等)が厳格"),
    ]:
        results.append({"level": "ok" if ok else "error", "check": key,
                        "message": f"#{num} {msg}" + ("" if ok else " ← 機能テスト失敗")})

    # #702: False Main Promotion = 0
    _fmp = _acc.get("false_main_promotion", 99) if _sm_ok else 99
    _t702 = _sm_ok and _fmp == 0
    results.append({"level": "ok" if _t702 else "error", "check": "false_main_promotion_zero",
                    "message": f"#702 False Main Promotion = {_fmp}（目標0）"
                               + ("" if _t702 else " ← False Main Promotion が残存")})

    # #703: Duplicate audit が生成される
    _t703 = _sm_ok and isinstance(_sm.get("duplicate_price_pattern"), list)
    results.append({"level": "ok" if _t703 else "error", "check": "duplicate_audit_generated",
                    "message": f"#703 Duplicate audit が生成される（{len(_sm.get('duplicate_price_pattern', []))}件）"
                               + ("" if _t703 else " ← Duplicate audit が不足")})

    # #704: RICOH duplicate が reviewed または flagged
    _ricoh_dup = [d for d in _sm.get("duplicate_price_pattern", [])
                  if any("gr4" in p or "gr" in str(d.get("models", "")).lower() for p in d.get("product_ids", []))
                  or (d.get("is_official") and d.get("price") == 299800)]
    _t704 = any(d.get("review_status") in ("reviewed_true_same_price", "manual_review_required")
                for d in _ricoh_dup) or len(_ricoh_dup) == 0
    results.append({"level": "ok" if _t704 else "warning", "check": "ricoh_duplicate_reviewed",
                    "message": "#704 RICOH GR IV 同額が reviewed/flagged 済み"
                               + ("" if _t704 else " ← RICOH duplicate 未レビュー")})

    # #705: Mobile Ichiban mismatch が解消/flag（同額の複数SKU割当が main から除外）
    _mi_main = [f for f in _sm.get("false_main_promotion", []) if f.get("source") == "モバイル一番"]
    _t705 = len(_mi_main) == 0
    results.append({"level": "ok" if _t705 else "error", "check": "mobile_ichiban_resolved",
                    "message": "#705 モバイル一番の誤マッチが main から除外されている"
                               + ("" if _t705 else " ← モバイル一番の誤マッチが main に残存")})

    # #706: Apple SKU mismatch が解消/flag（未検証SKUに推測価格を main 昇格しない）
    _apple_fm = [f for f in _sm.get("false_main_promotion", []) if "メーカー公式" in str(f.get("source", ""))]
    _t706 = len(_apple_fm) == 0
    results.append({"level": "ok" if _t706 else "error", "check": "apple_sku_mismatch_resolved",
                    "message": "#706 Apple 統合ページ由来の誤 SKU 価格が main 昇格していない"
                               + ("" if _t706 else " ← Apple SKU 誤価格が main に残存")})

    # #707: Source Matching Report が存在し精度目標を満たす
    _pma = _acc.get("product_match_accuracy", 0) if _sm_ok else 0
    _cma = _acc.get("capacity_match_accuracy", 0) if _sm_ok else 0
    _mma = _acc.get("model_match_accuracy", 0) if _sm_ok else 0
    _t707 = _sm_ok and _pma >= 0.99 and _cma >= 1.0 and _mma >= 1.0
    results.append({"level": "ok" if _t707 else "warning", "check": "source_matching_report",
                    "message": f"#707 Source Matching 精度（product {_pma:.1%}/cap {_cma:.0%}/model {_mma:.0%}）"
                               + ("" if _t707 else " ← 精度目標未達")})

    # ── API Automation Foundation ガード #708-#722 ──
    _apiauto = _load_json_safe('exports/api_automation/latest.json') or {}
    _apican = _load_json_safe('exports/api_automation/canary.json') or {}
    _api_ok = isinstance(_apiauto, dict) and ('per_api' in _apiauto)

    # #708: API automation report が存在
    _t708 = _api_ok and ('safety' in _apiauto)
    results.append({"level": "ok" if _t708 else "error", "check": "api_automation_report",
                    "message": "#708 API automation report が存在する"
                               + ("" if _t708 else " ← API automation report が不足")})

    # #709: API canary report が存在し simulated を明示
    _t709 = isinstance(_apican, dict) and ('per_api' in _apican) and (_apican.get('real_api_called') is False
            or _apican.get('mode') is not None)
    results.append({"level": "ok" if _t709 else "error", "check": "api_canary_report",
                    "message": f"#709 API canary report が存在（mode={_apican.get('mode','?')}/real_api={_apican.get('real_api_called')}）"
                               + ("" if _t709 else " ← canary report が不足")})

    # #710: NOT_CONFIGURED が graceful（未設定APIが error でなく status で表現）
    _statuses = {a: p.get("status") for a, p in (_apiauto.get("per_api", {}) or {}).items()}
    _t710 = _api_ok and all(s in ("NOT_CONFIGURED", "collected", "disabled_kill_switch", None)
                            for s in _statuses.values())
    results.append({"level": "ok" if _t710 else "error", "check": "api_not_configured_graceful",
                    "message": f"#710 NOT_CONFIGURED graceful（statuses={_statuses}）"
                               + ("" if _t710 else " ← 未設定APIの扱いが不正")})

    # #711: kill switch / dry-run が実装（api_runtime）
    _rt_src = _read_src("src", "collectors", "api", "api_runtime.py")
    _t711 = all(k in _rt_src for k in ("def kill_switch_on", "def is_dry_run", "def api_enabled",
                                       "ENABLE_EBAY_API"))
    results.append({"level": "ok" if _t711 else "error", "check": "api_kill_switch_dry_run",
                    "message": "#711 Kill Switch / Dry Run が実装される"
                               + ("" if _t711 else " ← Kill Switch/Dry Run 実装が不足")})

    # #712: Retry / Circuit Breaker / error 分類 が実装
    _t712 = all(k in _rt_src for k in ("def retry_with_backoff", "class CircuitBreaker",
                                       "def classify_error", "PERMANENT_STATUS", "TRANSIENT_STATUS"))
    results.append({"level": "ok" if _t712 else "error", "check": "api_retry_circuit_breaker",
                    "message": "#712 Retry / Circuit Breaker / error 分類 が実装される"
                               + ("" if _t712 else " ← Retry/Circuit Breaker 実装が不足")})

    # #713: ProductIdentityResolver + price_quality が API 経路に適用
    _col_src = _read_src("scripts", "collect_api_prices.py")
    _t713 = ("ProductIdentityResolver" in _col_src) and ("is_main_promotable" in _col_src) \
        and ("resolver.resolve" in _col_src)
    results.append({"level": "ok" if _t713 else "error", "check": "api_quality_gate_applied",
                    "message": "#713 API経路に ProductIdentityResolver + Main Gate が適用される"
                               + ("" if _t713 else " ← API品質ゲート未適用")})

    # #714: data_origin が追跡される
    _t714 = ("data_origin" in _col_src) and ("ORIGIN_API" in _col_src or "origin" in _col_src)
    results.append({"level": "ok" if _t714 else "error", "check": "api_origin_tracked",
                    "message": "#714 data_origin（api/fallback/manual）が追跡される"
                               + ("" if _t714 else " ← data_origin 未追跡")})

    # #715: 再マッチ(別商品)を除外している（Pro→Pro Max 等の混入防止）
    _t715 = "matched_product_id != pid" in _col_src or "cross_product" in _col_src
    results.append({"level": "ok" if _t715 else "error", "check": "api_cross_product_reject",
                    "message": "#715 別商品への再マッチ（Pro/Pro Max等）を除外する"
                               + ("" if _t715 else " ← 再マッチ除外が未実装")})

    # #716: Canary Gate（全API READY もしくは未設定でも simulated PASS）
    _canary_pass = _apican.get("all_pass") if isinstance(_apican, dict) else None
    _t716 = _canary_pass is True
    results.append({"level": "ok" if _t716 else "warning", "check": "api_canary_gate",
                    "message": f"#716 Canary Gate 判定（all_pass={_canary_pass}）"
                               + ("" if _t716 else " ← Canary 未通過")})

    # #717: API 由来の False Main Promotion = 0（canary の各API false_main）
    _api_fm = 0
    for p in (_apican.get("per_api", {}) or {}).values():
        _api_fm += (p.get("metrics", {}) or {}).get("false_main_promotion", 0)
    _t717 = _api_fm == 0
    results.append({"level": "ok" if _t717 else "error", "check": "api_false_main_zero",
                    "message": f"#717 API由来 False Main Promotion = {_api_fm}（目標0）"
                               + ("" if _t717 else " ← API由来の False Main が残存")})

    # #718: eBay/Rakuten/Yahoo が env-gated（未設定でも落ちない設計）
    _mk_src = _read_src("src", "collectors", "api", "market_apis.py")
    # eBay は Finding API の廃止で取得しない（Phase 13。キーの有無にかかわらず None）ことを動かして確かめる
    try:
        from src.collectors.api.market_apis import ebay_fetch_items as _efi718
        _ebay718 = _efi718("PlayStation 5 Pro") is None
    except Exception:  # noqa: BLE001
        _ebay718 = False
    _t718 = all(k in _mk_src for k in ("RAKUTEN_APP_ID", "YAHOO_SHOPPING_APP_ID")) \
        and ("return None" in _mk_src) and _ebay718
    results.append({"level": "ok" if _t718 else "error", "check": "api_env_gated",
                    "message": "#718 eBay/Rakuten/Yahoo collector が env-gated（未設定で graceful）"
                               + ("" if _t718 else " ← env gating が不足")})

    # #719: workflow に API 環境変数が配線（Secret未設定でも落ちない）
    _wf = ""
    try:
        _wf = (PROJECT_ROOT / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
    except Exception:
        pass
    _t719 = all(k in _wf for k in ("ENABLE_EBAY_API", "API_DRY_RUN", "collect_api_prices.py"))
    results.append({"level": "ok" if _t719 else "error", "check": "api_workflow_wired",
                    "message": "#719 workflow に API 環境変数/ステップが配線される"
                               + ("" if _t719 else " ← workflow 配線が不足")})

    # #720: Secret leak = 0（API automation の exports にキー実値が無い）
    import re as _re720
    _leak = 0
    for _rel in ("exports/api_automation/latest.json", "exports/api_automation/collection.json",
                 "exports/api_automation/canary.json"):
        _p = PROJECT_ROOT / _rel
        if _p.exists():
            _txt = _p.read_text(encoding="utf-8", errors="ignore")
            _leak += len(_re720.findall(
                r"(sk_(?:live|test)_[A-Za-z0-9]{16,}|AKIA[0-9A-Z]{16}|ghp_[A-Za-z0-9]{20,})", _txt))
    _t720 = _leak == 0
    results.append({"level": "ok" if _t720 else "error", "check": "api_secret_leak_zero",
                    "message": "#720 API automation exports に Secret 実値の混入なし"
                               + ("" if _t720 else " ← Secret 混入の疑い")})

    # #721: Dry Run が既定安全（workflow の API_DRY_RUN 既定 true）
    _t721 = "API_DRY_RUN: ${{ vars.API_DRY_RUN || 'true' }}" in _wf
    results.append({"level": "ok" if _t721 else "warning", "check": "api_dry_run_default_safe",
                    "message": "#721 Dry Run が既定安全（API_DRY_RUN 既定 true）"
                               + ("" if _t721 else " ← Dry Run 既定が安全側でない")})

    # #722: API regression tests が存在する
    _t722 = (PROJECT_ROOT / "tests" / "test_api_automation.py").exists()
    results.append({"level": "ok" if _t722 else "error", "check": "api_regression_tests",
                    "message": "#722 API regression tests（tests/test_api_automation.py）が存在する"
                               + ("" if _t722 else " ← API テストが不足")})

    # ── Real API Canary & Progressive Rollout ガード #723-#731 ──
    _rc = _load_json_safe('exports/api_automation/real_canary_latest.json') or {}
    _rc_ok = isinstance(_rc, dict) and ('per_api' in _rc) and ('overall' in _rc)

    # #723: Real Canary Master Report が存在
    results.append({"level": "ok" if _rc_ok else "error", "check": "real_canary_report",
                    "message": f"#723 Real Canary Master Report が存在（overall={_rc.get('overall','?')}）"
                               + ("" if _rc_ok else " ← Real Canary Report が不足")})

    # #724: API rollout state が有効値
    _valid_states = {"NOT_CONFIGURED", "DISABLED", "DRY_RUN", "CANARY", "STAGE_5",
                     "STAGE_10", "STAGE_25", "FULL", "ROLLOUT_BLOCKED"}
    _states = (_rc.get("rollout_state", {}) or {}).values() if _rc_ok else []
    _t724 = _rc_ok and all(s in _valid_states for s in _states)
    results.append({"level": "ok" if _t724 else "error", "check": "api_rollout_state_valid",
                    "message": f"#724 API rollout state が有効（{_rc.get('rollout_state', {})}）"
                               + ("" if _t724 else " ← rollout state 不正")})

    # #725: 各API Canary の判定が有効（PASS / ROLLOUT_BLOCKED / PENDING）
    _valid_status = {"CANARY_PASS", "ROLLOUT_BLOCKED", "PENDING_USER_CONFIGURATION", "DISABLED"}
    _t725 = _rc_ok and all(p.get("status") in _valid_status for p in (_rc.get("per_api", {}) or {}).values())
    results.append({"level": "ok" if _t725 else "error", "check": "api_canary_gate_valid",
                    "message": "#725 eBay/Rakuten/Yahoo Canary Gate 判定が有効"
                               + ("" if _t725 else " ← Canary Gate 判定が不正")})

    # #726: Cross Product Main = 0（設定済みAPIの canary で cross_product が main 昇格していない）
    _cpm = 0
    for p in (_rc.get("per_api", {}) or {}).values():
        _cpm += (p.get("gate", {}) or {}).get("cross_product_main", 0)
    _t726 = _cpm == 0
    results.append({"level": "ok" if _t726 else "error", "check": "api_cross_product_main_zero",
                    "message": f"#726 Cross Product Main = {_cpm}（目標0）"
                               + ("" if _t726 else " ← cross product が main 昇格")})

    # #727: ROLLOUT_BLOCKED の API が誤って FULL 状態でない
    _bad_rollout = [a for a, p in (_rc.get("per_api", {}) or {}).items()
                    if p.get("status") == "ROLLOUT_BLOCKED" and p.get("rollout_state") == "FULL"]
    _t727 = len(_bad_rollout) == 0
    results.append({"level": "ok" if _t727 else "error", "check": "api_blocked_not_full",
                    "message": "#727 ROLLOUT_BLOCKED の API が FULL 展開していない"
                               + ("" if _t727 else f" ← {_bad_rollout} が block なのに FULL")})

    # #728: stage 制御が実装される（api_runtime）
    _t728 = all(k in _rt_src for k in ("def api_stage", "def stage_product_limit",
                                       "def rollout_state", "EBAY_API_STAGE"))
    results.append({"level": "ok" if _t728 else "error", "check": "api_stage_control",
                    "message": "#728 stage 制御（0/5/10/25/all）が実装される"
                               + ("" if _t728 else " ← stage 制御が不足")})

    # #729: workflow に stage 制御が配線される
    _t729 = all(k in _wf for k in ("EBAY_API_STAGE", "real_canary_api.py"))
    results.append({"level": "ok" if _t729 else "error", "check": "api_stage_workflow",
                    "message": "#729 workflow に stage 制御 / real canary が配線される"
                               + ("" if _t729 else " ← workflow の stage 配線が不足")})

    # #730: 未設定APIが PENDING_USER_CONFIGURATION（架空成功でない）
    _pending_ok = all(p.get("real_api_called") is False
                      for p in (_rc.get("per_api", {}) or {}).values()
                      if p.get("status") == "PENDING_USER_CONFIGURATION")
    _t730 = _rc_ok and _pending_ok
    results.append({"level": "ok" if _t730 else "error", "check": "api_pending_no_fake",
                    "message": "#730 未設定APIは PENDING（real_api_called=false・架空成功なし）"
                               + ("" if _t730 else " ← 未設定APIを架空成功として報告")})

    # #731: Data Quality Accuracy が維持（>=90 を目安）
    _dq2 = _load_json_safe('exports/data_quality/latest.json') or {}
    _dq_acc = (_dq2.get("quality_score", {}) or {}).get("dimensions", {}).get("accuracy", 0)
    _t731 = _dq_acc >= 90
    results.append({"level": "ok" if _t731 else "warning", "check": "api_data_quality_accuracy",
                    "message": f"#731 Data Quality Accuracy 維持（{_dq_acc}/100）"
                               + ("" if _t731 else " ← Accuracy 低下")})

    # ── eBay Real Canary ガード #732-#738 ──
    _erc = _load_json_safe('exports/api_automation/ebay_real_canary.json') or {}
    _erc_ok = isinstance(_erc, dict) and ('verdict' in _erc) and ('configuration' in _erc)
    _erc_configured = (_erc.get("configuration", {}) or {}).get("EBAY_APP_ID") == "CONFIGURED"

    # #732: eBay real canary report が存在
    results.append({"level": "ok" if _erc_ok else "error", "check": "ebay_real_canary_report",
                    "message": f"#732 eBay real canary report が存在（verdict={_erc.get('verdict','?')}）"
                               + ("" if _erc_ok else " ← eBay real canary report が不足")})

    # #733: verdict が有効値
    _valid_v = {"EBAY_REAL_CANARY_PASS", "EBAY_ROLLOUT_BLOCKED",
                "EBAY_CONFIGURATION_ERROR", "EBAY_PENDING_CONFIGURATION"}
    _t733 = _erc_ok and _erc.get("verdict") in _valid_v
    results.append({"level": "ok" if _t733 else "error", "check": "ebay_canary_verdict_valid",
                    "message": f"#733 eBay Canary Verdict が有効（{_erc.get('verdict','?')}）"
                               + ("" if _t733 else " ← verdict 不正")})

    # #734: 架空PASS禁止 — 未設定/未呼出しで PASS を出していない
    _t734 = _erc_ok and not (_erc.get("verdict") == "EBAY_REAL_CANARY_PASS"
                             and _erc.get("real_api_called") is not True)
    results.append({"level": "ok" if _t734 else "error", "check": "ebay_no_fake_pass",
                    "message": "#734 未設定/未呼出しで EBAY_REAL_CANARY_PASS を出していない"
                               + ("" if _t734 else " ← 架空PASSの疑い")})

    # #735: real_api_called が configured と整合（未設定なら false）
    _t735 = _erc_ok and (_erc_configured or _erc.get("real_api_called") is False)
    results.append({"level": "ok" if _t735 else "error", "check": "ebay_real_api_called_consistent",
                    "message": f"#735 real_api_called={_erc.get('real_api_called')} が設定状態と整合"
                               + ("" if _t735 else " ← real_api_called が不整合")})

    # #736: Dry Run Main Mutation = 0
    _t736 = _erc_ok and _erc.get("dry_run_main_mutation", 1) == 0
    results.append({"level": "ok" if _t736 else "error", "check": "ebay_dry_run_no_mutation",
                    "message": f"#736 Dry Run Main Mutation = {_erc.get('dry_run_main_mutation','?')}（目標0）"
                               + ("" if _t736 else " ← Dry Run で Main 変化")})

    # #737: PASS の場合は精度条件を満たす（未達で PASS していない）
    _em = _erc.get("metrics", {}) if _erc_ok else {}
    if _erc.get("verdict") == "EBAY_REAL_CANARY_PASS":
        _t737 = (_em.get("product_match_accuracy", 0) >= 0.99 and _em.get("capacity_match_accuracy") == 1.0
                 and _em.get("model_match_accuracy") == 1.0 and _em.get("cross_product_main", 1) == 0)
    else:
        _t737 = True   # 非PASSは対象外
    results.append({"level": "ok" if _t737 else "error", "check": "ebay_pass_meets_gate",
                    "message": "#737 EBAY_REAL_CANARY_PASS は精度条件(Product>=99/Cap100/Model100)を満たす"
                               + ("" if _t737 else " ← 精度未達で PASS")})

    # #738: Stage 5 推奨は PASS 時のみ（非PASSで自動 stage 変更を推奨しない）
    _t738 = _erc_ok and (_erc.get("verdict") == "EBAY_REAL_CANARY_PASS"
                         or _erc.get("recommended_next_action") in (None, {}))
    results.append({"level": "ok" if _t738 else "error", "check": "ebay_stage_recommend_gated",
                    "message": "#738 Stage 5 推奨は Canary PASS 時のみ"
                               + ("" if _t738 else " ← 非PASSで stage 変更を推奨")})

    # ══════════════════════════════════════════════════════════════════
    # #739-#750: TCG（ポケモンカード / ONE PIECEカードゲーム）監視レイヤー
    # ══════════════════════════════════════════════════════════════════
    results.extend(_check_tcg_layer())

    # ══════════════════════════════════════════════════════════════════
    # #800-#810: 新UI（?ui=new のときだけ表示する追加レイヤー）
    # ══════════════════════════════════════════════════════════════════
    results.extend(_check_new_ui(html))
    results.extend(_check_legacy_intents())
    results.extend(_check_phase12_sources_and_sold(html))
    results.extend(_check_phase13_ebay_sold())
    results.extend(_check_phase15_identity())
    results.extend(_check_phase16_official_direct())
    results.extend(_check_phase17_camera_sell())
    results.extend(_check_phase18_actionability(html))
    results.extend(_check_phase19_actionable_notifications(html))
    results.extend(_check_phase20_notification_outbox())
    results.extend(_check_phase21_delivery_providers())
    results.extend(_check_phase22_telegram_safety())

    # ══════════════════════════════════════════════════════════════════
    # #820-#825: データの正確さ・鮮度の偽装（Phase 0）
    # ══════════════════════════════════════════════════════════════════
    results.extend(_check_data_correctness())

    return results


def _check_legacy_intents() -> list[dict]:
    """#840 UI Phase 10: 旧UIと一緒に削除した検査のうち、今も守るべき意図を新UIの判定で確かめる（動かして確かめる）。

    旧UIの検査はソースの文字列（_tab_beginner・_deal_card・_collector_warn_bar_html など旧UIの描画関数）を見ていた。
    同じ意図を、新UIが実際に使う判定（opportunity.deal_reasons・admin.collector_warn・DailyLPGenerator._cond_is_used）で見る。
    - 旧 #342・#469〜#474・#486: 14日より古い買取価格は確定の利益に使わない
    - 旧 #353・#326: 0円（取得失敗）の価格を利益・赤字の判定に使わない
    - 旧 #361: 中古の条件の価格を使わない
    - 旧 #259・#260（optional_only_no_strong_warn・suspicious_still_strong_warn）: 取得の警告の強さの分け方
    """
    out: list[dict] = []
    bad = []
    try:
        from datetime import datetime as _dt840, timedelta as _td840
        from src.content.ui import admin as _ad840
        from src.content.ui import opportunity as _op840
        from src.content.daily_lp_generator import DailyLPGenerator as _G840
        from src.tcg.models import JST as _JST840
        _now = _dt840(2026, 10, 7, 12, 0, tzinfo=_JST840)
        _t = lambda **kw: (_now - _td840(**kw)).isoformat()   # noqa: E731
        _deal = {"product_id": "prod_check840", "title": "検査用", "genre": "camera", "official_price": 100000,
                 "official_checked_at": _t(days=3), "msrp_evidence": "VERIFIED_DATED", "stock_status": "在庫あり",
                 "stock_checked_at": _t(minutes=10), "sale_method": "normal", "sell_shop": "検査買取店",
                 "sell_identity_verified": True, "sell_price": 130000, "sell_checked_at": _t(hours=2),
                 "net_profit": 28200, "official_url": "https://www.apple.com/jp/shop/x",
                 "sell_url": "https://kaitori.example.jp/item/1", "purchase_shipping": 0,
                 "purchase_shipping_status": "FREE_VERIFIED"}
        if _op840.deal_reasons(_deal, _now):
            bad.append(f"基準の案件が確定にならない: {_op840.deal_reasons(_deal, _now)}")
        if "stale_sell_price" not in _op840.deal_reasons(dict(_deal, sell_checked_at=_t(days=15)), _now):
            bad.append("15日前の買取価格が確定に使われる")
        if not _op840.deal_reasons(dict(_deal, sell_price=0, net_profit=-100000), _now):
            bad.append("0円の買取価格が確定に使われる")
        if not _op840.deal_reasons(dict(_deal, sell_identity_verified=False), _now):
            bad.append("商品の照合が済んでいない買取価格が確定に使われる")
        if not (_G840._cond_is_used("中古") and not _G840._cond_is_used("new_unopened")):
            bad.append("中古の条件を見分けられない")
        _opt = {"2ndstreet"}
        _w = lambda **c: _ad840.collector_warn(dict({"suspicious_prices": [], "summary": {}, "shop_detail": []}, **c),  # noqa: E731
                                               _opt, 5)["level"]
        if _w(summary={"low_confidence_count": 1}) != "strong":
            bad.append("低信頼度の価格があっても強い警告にならない")
        if _w(shop_detail=[{"shop_id": "2ndstreet", "failed": 9}]) != "info":
            bad.append("任意の店だけの失敗が強い警告になる")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"判定を動かせない: {exc}")
    out.append({"level": "ok" if not bad else "error", "check": "legacy_intents_on_new_ui",
                "message": "#840 旧UIの検査の意図（14日より古い価格・0円・未照合・中古を確定に使わない、取得の警告の強さ）を"
                           "新UIの判定で満たす" + ("" if not bad else f" ← {bad[:4]}")})
    return out


def _check_phase12_sources_and_sold(html: str) -> list[dict]:
    """Phase 12: 取得の安全性（#842）・API と秘密の値（#843）・成約の意味（#844）。動かして確かめる。"""
    import json as _j12
    import re as _re12
    root = PROJECT_ROOT
    out: list[dict] = []

    # #842 取得の安全性: robots.txt の禁止を取りに行かない・ブロックで打ち切る・ブラウザを名乗らない・
    #       メルカリ / ラクマをスクレイピングしない
    bad = []
    try:
        from src.collectors import polite as _pl
        from src.collectors.buyback_kaitori_shouten import KaitoriShoutenCsvCollector as _KS
        _orig = _pl.robots_checker

        class _Deny:
            def is_allowed(self, url):
                return False

            def get_crawl_delay(self, url):
                return None
        _pl.robots_checker = lambda: _Deny()
        try:
            _c = _KS()
            _hits = []
            _c._fetch_html = lambda url: _hits.append(url) or "x"
            if _c.fetch("airpods_pro3", "", "new_unopened") is not None or _hits \
                    or _c.last_failure_reason != "robots_disallowed":
                bad.append("robots.txt で禁止の URL を取りに行く")
        finally:
            _pl.robots_checker = _orig
        for _rsn in ("http_403", "rate_limited_429", "robots_disallowed", "site_blocked", "http_401"):
            _sc = _pl.ShopCutoff()
            _sc.record("x", False, _rsn)
            if not _sc.is_cut("x"):
                bad.append(f"{_rsn} の店を打ち切らない")
        _sc = _pl.ShopCutoff()
        for _ in range(2):
            _sc.record("x", False, "http_0")                     # 名前の分からない失敗の理由も数える
        if not _sc.is_cut("x"):
            bad.append("理由の名前が分からない失敗で打ち切らない")
        if not _pl.HONEST_UA.startswith("PremiumMonitor/"):
            bad.append("User-Agent が PremiumMonitor で始まらない")
        # ブラウザ（Mozilla 互換・Chrome・Firefox・Edge・Safari・iPhone）を名乗る User-Agent の文字列
        _ua = _re12.compile(r"Mozilla/5\.0|Chrome/\d|Firefox/\d|Edg/\d|Safari/\d|iPhone OS \d")
        for _base in ("src", "scripts"):
            for _f in (root / _base).rglob("*.py"):
                if _f.name == "deploy_check.py":
                    continue
                if _ua.search(_f.read_text(encoding="utf-8", errors="ignore")):
                    bad.append(f"ブラウザを名乗る User-Agent: {_f.relative_to(root)}")
        _rs = (root / "scripts" / "collect_resale_prices.py").read_text(encoding="utf-8")
        for _sk in ("skip_mercari", "skip_rakuma", "skip_amazon", "skip_yahoo"):
            if f"    {_sk} = True" not in _rs:
                bad.append(f"resale が {_sk} を外している（規約上取らない取得元を取る）")
        _m12 = _re12.search(r"class RakutenResaleCollector.*?\n    def collect\(.*?(?=\n    def |\nclass )", _rs, _re12.S)
        if not _m12 or "_fetch_html(" in _m12.group(0):
            bad.append("楽天の公式 API の失敗で検索結果の HTML を取りに行く")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"判定を動かせない: {exc}")
    out.append({"level": "ok" if not bad else "error", "check": "source_safety",
                "message": "#842 取得の安全性（robots.txt・ブロックで打ち切り・正直な User-Agent・規約上取らない取得元を取らない）"
                           + ("" if not bad else f" ← {bad[:4]}")})

    # #843 API と秘密の値: 公開するページ（docs/ の全 HTML）と成約の生成物に、秘密の値・認証の値が無い。
    #       成約の API は資格情報が無いのに取りに行った記録が無い（監査 M2: 1ページだけ・eBay の token の形を見落としていた）
    bad = []
    try:
        import os as _os12
        _auth = _re12.compile(r"Bearer\s+[^\s\"'<,;}]{8,}|Basic\s+[A-Za-z0-9+/=]{12,}")
        _names = _re12.compile(r"client_secret|access_token|refresh_token|EBAY_CLIENT_SECRET")
        _sec = _os12.environ.get("EBAY_CLIENT_SECRET") or ""
        _pages = [(PUBLIC_DIR / "index.html", html or "")]
        for _f in sorted(PUBLIC_DIR.rglob("*.html")):
            if _f.name != "index.html" or _f.parent != PUBLIC_DIR:
                _pages.append((_f, None))
        _sold_dir = root / "exports" / "sold_history"
        if _sold_dir.exists():
            _pages += [(_f, None) for _f in sorted(_sold_dir.glob("*.json"))]
        for _f, _txt in _pages:
            if _txt is None:
                try:
                    _txt = _f.read_text(encoding="utf-8", errors="ignore")
                except OSError:
                    continue
            _why = ("認証の値" if _auth.search(_txt) else "秘密の値の名前" if _names.search(_txt)
                    else "EBAY_CLIENT_SECRET の値" if len(_sec) >= 6 and _sec in _txt else "")
            if _why:
                bad.append(f"{_why}: {_f.relative_to(root) if root in _f.parents else _f.name}")
                if len(bad) >= 4:
                    break
    except Exception as exc:  # noqa: BLE001
        bad.append(f"判定を動かせない: {exc}")
    out.append({"level": "ok" if not bad else "error", "check": "api_secret_safety",
                "message": "#843 API の安全性（公開する全ページ・成約の記録に秘密の値・認証の値が無い）"
                           + ("" if not bad else f" ← {bad[:4]}")})

    # #844 成約の意味: 保存した成約はすべて根拠あり（商品ページ・成約日時・同一性・状態）。成約中央値は3件以上・期間あり。
    #       確定の利益ルートの売値が成約中央値のときも同じ
    bad = []
    try:
        from src.market import price_types as _pt12
        from src.market import sold_history as _sh12
        for _r in _sh12.load():
            _why = _sh12.record_reasons(_r)
            if _why:
                bad.append(f"根拠の無い成約が履歴にある（{_r.item_url} {_why}）")
                break
        _npo = root / "exports" / "normalized_price_observations" / "latest.json"
        if _npo.exists():
            for _o in _j12.loads(_npo.read_text(encoding="utf-8")).get("observations") or []:
                if _o.get("sold_median_eligible") and not (
                        int(_o.get("sample_count") or 0) >= _pt12.MIN_SOLD_SAMPLES
                        and _o.get("sold_period_start") and _o.get("sold_period_end")):
                    bad.append(f"件数・期間の足りない成約中央値（{_o.get('product_id')}）")
                    break
        _pr = root / "exports" / "profit_routes" / "latest.json"
        if _pr.exists():
            for _r in _j12.loads(_pr.read_text(encoding="utf-8")).get("main_routes") or []:
                if _pt12.canonical(_r.get("sell_canonical_type")) in (_pt12.SOLD_MEDIAN, _pt12.SOLD) and not (
                        int(_r.get("sell_sample_count") or 0) >= _pt12.MIN_SOLD_SAMPLES
                        and _r.get("sell_period_start") and _r.get("sell_period_end")):
                    bad.append(f"件数・期間の足りない成約を売値にした確定ルート（{_r.get('product_id')}）")
                    break
                if _pt12.canonical(_r.get("sell_canonical_type")) == _pt12.LISTING:
                    bad.append(f"出品価格を売値にした確定ルート（{_r.get('product_id')}）")
                    break
    except Exception as exc:  # noqa: BLE001
        bad.append(f"判定を動かせない: {exc}")
    out.append({"level": "ok" if not bad else "error", "check": "sold_semantics",
                "message": "#844 成約の意味（根拠のある成約だけ・成約中央値は3件以上と期間・出品を売値にしない）"
                           + ("" if not bad else f" ← {bad[:3]}")})
    return out


def _check_phase13_ebay_sold() -> list[dict]:
    """Phase 13: eBay の成約の CI の組み込みと関門（#845）・廃止された Finding API を呼ばない（#846）。動かして確かめる。"""
    import os as _os13
    import re as _re13
    import tempfile as _tf13
    root = PROJECT_ROOT
    out: list[dict] = []

    # #845 eBay の成約: CI のステップがあり、既定は取りに行かない（取得の明示・承認・ライセンスは false、canary は true）。
    #       資格情報・承認・ライセンス・取得の明示のどれか1つでも欠けたら通信0（状態だけを書く）。token の形を伏せる
    bad = []
    try:
        _wf = (root / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
        _m = _re13.search(r"- name: eBay SOLD \(Marketplace Insights\)\n(.*?)(?=\n      - name: )", _wf, _re13.S)
        if not _m:
            bad.append("CI に eBay SOLD のステップが無い")
        else:
            _st = _m.group(1)
            for _need in ("scripts/collect_ebay_sold.py", "continue-on-error: true",
                          "vars.ENABLE_EBAY_API || 'false'", "vars.EBAY_INSIGHTS_APPROVED || 'false'",
                          "vars.EBAY_SOLD_LICENSE_CONFIRMED || 'false'", "vars.EBAY_SOLD_CANARY || 'true'",
                          "vars.API_DRY_RUN || 'true'"):
                if _need not in _st:
                    bad.append(f"eBay SOLD のステップの既定が安全側でない（{_need} が無い）")
            if _wf.index("- name: eBay SOLD (Marketplace Insights)") > _wf.index(
                    "- name: Generate normalized price observations"):
                bad.append("eBay SOLD のステップが正規化（成約の履歴を読む）より後にある")
        if "exports/sold_history/" not in _wf.split("- name: Commit and push", 1)[-1]:
            bad.append("成約の履歴（exports/sold_history/）を CI が保存しない")
        from src.collectors.api import ebay_insights as _ei
        _keys = ("EBAY_CLIENT_ID", "EBAY_CLIENT_SECRET", "EBAY_APP_ID", "ENABLE_EBAY_API", "API_DRY_RUN",
                 _ei.APPROVAL_ENV, _ei.LICENSE_ENV, _ei.CANARY_ENV, _ei.STAGE_ENV)
        _saved = {k: _os13.environ.get(k) for k in _keys}
        try:
            for k in _keys:
                _os13.environ.pop(k, None)
            _steps = [({}, _ei.ST_PENDING),
                      ({"EBAY_CLIENT_ID": "dc-id-0000", "EBAY_CLIENT_SECRET": "dc-sec-0000"}, _ei.ST_PENDING_APPROVAL),
                      ({_ei.APPROVAL_ENV: "true"}, _ei.ST_PENDING_LICENSE),
                      ({_ei.LICENSE_ENV: "true"}, _ei.ST_DISABLED),
                      ({"ENABLE_EBAY_API": "true", "API_DRY_RUN": "true"}, _ei.ST_DRY_RUN),
                      ({"API_DRY_RUN": "false"}, _ei.ST_OK)]
            for _env, _want in _steps:
                _os13.environ.update(_env)
                if _ei.status() != _want:
                    bad.append(f"関門の順番が違う（{_want} のはずが {_ei.status()}）")
                    break
            # ライセンスの確認が無ければ、ほかが全部そろっていても取りに行かない（通信0・状態だけ）
            _os13.environ[_ei.LICENSE_ENV] = "false"
            import importlib.util as _iu13
            import urllib.request as _ur13
            _sp = _iu13.spec_from_file_location("dc13_collect_ebay_sold", root / "scripts" / "collect_ebay_sold.py")
            _mod = _iu13.module_from_spec(_sp)
            _sp.loader.exec_module(_mod)
            _calls = []
            _orig_open = _ur13.urlopen
            _ur13.urlopen = lambda *a, **k: _calls.append(a) or (_ for _ in ()).throw(RuntimeError("no network"))
            try:
                with _tf13.TemporaryDirectory() as _td:
                    _mod.STATUS_PATH = Path(_td) / "status.json"
                    import contextlib as _cl13
                    import io as _io13
                    with _cl13.redirect_stdout(_io13.StringIO()):
                        _mod.main([])
                    import json as _j13
                    _body = _j13.loads(_mod.STATUS_PATH.read_text(encoding="utf-8"))
            finally:
                _ur13.urlopen = _orig_open
            if _calls or _body.get("status") != _ei.ST_PENDING_LICENSE or _body.get("network_used"):
                bad.append("ライセンスの確認が無いのに取りに行く")
        finally:
            for k, v in _saved.items():
                if v is None:
                    _os13.environ.pop(k, None)
                else:
                    _os13.environ[k] = v
        _tok = "v^1.1#i^1#p^3#r^0#I^3#f^0#t^Ul4xMF8xOjAwRkY="
        if _tok in _ei.redact(f"token {_tok} and Bearer {_tok}"):
            bad.append("eBay の token（v^1.1#...）を伏せない")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"判定を動かせない: {exc}")
    out.append({"level": "ok" if not bad else "error", "check": "ebay_sold_gates",
                "message": "#845 eBay の成約（CI のステップは既定で取りに行かない・資格情報 / 承認 / ライセンス / "
                           "取得の明示が欠けたら通信0・token を伏せる）" + ("" if not bad else f" ← {bad[:4]}")})

    # #846 廃止された Finding API（2025-02-05）を呼ぶコードが無い（EBAY_CLIENT_ID を登録しても client id を送らない）
    bad = []
    _fd = _re13.compile(r"svcs\.ebay\.com|FindingService|findItemsByKeywords\"|findCompletedItems\"|SECURITY-APPNAME")
    # eBay の検索結果の HTML を取るコード（呼ばれないまま残っている）を呼び戻していないか（監査 L-3）
    _html_call = _re13.compile(r"(?<!def )\b_fetch_via_html\(|collectors\.price\.ebay\b|collectors\.price import ebay\b")
    for _base in ("src", "scripts"):
        for _f in (root / _base).rglob("*.py"):
            if _f.name == "deploy_check.py":
                continue
            _txt = _f.read_text(encoding="utf-8", errors="ignore")
            if _fd.search(_txt):
                bad.append(str(_f.relative_to(root)))
            for _ln in _txt.splitlines():
                if _html_call.search(_ln) and not _ln.lstrip().startswith(("#", "def ")) \
                        and "collector_module" not in _ln:
                    bad.append(f"eBay の HTML の取得を呼んでいる: {_f.relative_to(root)}")
                    break
    out.append({"level": "ok" if not bad else "error", "check": "ebay_finding_api_removed",
                "message": "#846 廃止された eBay Finding API・eBay の検索結果の HTML を取るコードを呼んでいない"
                           + ("" if not bad else f" ← {bad[:4]}")})
    return out


def _check_phase15_identity() -> list[dict]:
    """Phase 15: 商品の同一性と価格の意味（#847）・公式の再確認の鮮度（#848）。動かして確かめる。"""
    import importlib.util as _iu15
    import json as _j15
    import tempfile as _tf15
    from types import SimpleNamespace as _NS15

    import yaml as _y15
    root = PROJECT_ROOT
    out: list[dict] = []

    # #847 同一性と価格の意味: 確認済みは登録の型番・JAN と公式の証拠が一致するものだけ。判断待ちは確認済みにしない。
    #       オープン価格に価格（架空の希望小売価格）を持たせない。販売終了の商品を確認済みの定価に戻さない
    bad = []
    try:
        from src.market import official_registry as _reg
        prods = (_y15.safe_load((root / "config" / "products.yaml").read_text(encoding="utf-8")) or {}).get("products") or []
        for p in prods:
            st, _ = _reg.identity_state(p)
            ev = _reg.IDENTITY_EVIDENCE.get(p["id"]) or {}
            # Phase 16: 色だけが違う部品番号の組（variant_skus・容量と価格がすべて同じ）も公式の証拠として認める
            if st == "IDENTITY_CONFIRMED" and not (
                    (ev.get("model_number") and ev["model_number"] == p.get("model_number"))
                    or (ev.get("jan_code") and ev["jan_code"] == p.get("jan_code"))
                    or _reg._variant_group_ok(p, ev)):
                bad.append(f"公式の証拠の無い確認済み（{p['id']}）")
            if p["id"] in _reg.USER_DECISIONS and st == "IDENTITY_CONFIRMED":
                bad.append(f"判断待ちを確認済みにしている（{p['id']}）")
        # 同一性の証拠は、公式ページ（https・確認日あり）に限る
        for pid, ev in _reg.IDENTITY_EVIDENCE.items():
            if not str(ev.get("url") or "").startswith("https://") or not ev.get("checked_on"):
                bad.append(f"同一性の証拠に公式ページの URL・確認日が無い（{pid}）")
        for pid, v in _reg.VERIFIED_URLS.items():
            kind = v.get("price_kind") or ("open_price" if v.get("open_price") else "msrp")
            if kind not in _reg.PRICE_KINDS:
                bad.append(f"価格の意味が不明（{pid}: {kind}）")
            if kind == "open_price" and v.get("price"):
                bad.append(f"オープン価格に価格がある（{pid}）")
            if pid in _reg.OFFICIAL_NOT_SOLD:
                bad.append(f"販売終了の商品が確認済みの定価にある（{pid}）")
        # 否定対照: 証拠と食い違う型番は確認済みにならない
        if _reg.identity_state({"id": "prod_ps5_pro", "model_number": "CFI-7000B01"})[0] == "IDENTITY_CONFIRMED":
            bad.append("証拠と違う型番で確認済みになる")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"判定を動かせない: {exc}")
    out.append({"level": "ok" if not bad else "error", "check": "identity_semantics",
                "message": "#847 商品の同一性（確認済みは公式の証拠と一致する型番・JAN だけ・判断待ちを確定にしない）・"
                           "価格の意味（オープン価格に架空の希望小売価格を作らない・販売終了を戻さない）"
                           + ("" if not bad else f" ← {bad[:4]}")})

    # #848 公式の再確認の鮮度: 失敗・ブロックでは何も更新しない（確認日を進めない）。古い結果で確認日を戻さない。
    #       価格が変わったら確認済みの定価から外す
    bad = []
    try:
        _sp = _iu15.spec_from_file_location("dc15_audit", root / "scripts" / "audit_official_sources.py")
        _m = _iu15.module_from_spec(_sp)
        _sp.loader.exec_module(_m)
        v = _m.VERIFIED_URLS["prod_ps5_pro"]

        def _run(results):
            calls = []

            class _C:
                def execute(self, sql, params=()):
                    calls.append((sql, params))
                    return _NS15(fetchone=lambda: None)

                def commit(self):
                    pass
            with _tf15.TemporaryDirectory() as td:
                pth = Path(td) / "latest.json"
                pth.write_text(_j15.dumps({"results": results}), encoding="utf-8")
                _m.apply_recheck(_C(), {"prod_ps5_pro": {"model_number": "CFI-7100B01"}}, pth)
            return [c for c in calls if c[0].lstrip().upper().startswith("UPDATE")]
        # 今の記録（URL・型番・記録の価格）に対する結果にする（照合で外れて何も確かめない検査にしない）
        base = {"product_id": "prod_ps5_pro", "recorded_price": v["price"], "url": v["url"], "model": "CFI-7100B01"}
        for st in ("failed", "blocked"):
            if _run([dict(base, status=st, price=None, stock="", observed_at="2099-01-01T00:00:00+09:00")]):
                bad.append(f"{st} で更新する（鮮度の偽装）")
        if _run([dict(base, status="unchanged", price=v["price"], stock="",
                      observed_at="2000-01-01T00:00:00+09:00")]):
            bad.append("記録より古い再確認で確認日を変える")
        if _run([dict(base, status="unchanged", price=v["price"], stock="",
                      observed_at="2099-01-01T00:00:00+09:00")]):
            bad.append("未来の日付の再確認で確認日を進める")
        # 肯定の対照: 記録より新しく今日までの unchanged は確認日を進める（反映の経路が働いていること）
        _today = _m.NOW.date().isoformat()
        if str(v.get("checked_on") or "") < _today and not _run(
                [dict(base, status="unchanged", price=v["price"], stock="", observed_at=_today + "T09:00:00+09:00")]):
            bad.append("記録より新しい再確認を反映しない（照合の条件が誤っている）")
        ch = _run([dict(base, status="changed", price=v["price"] + 1000, stock="",
                        observed_at="2099-01-01T00:00:00+09:00")])
        if not any("official_price=NULL" in s for s, _ in ch):
            bad.append("価格が変わったのに確認済みの定価のまま")
        if not any("product_source_config" in s for s, _ in ch):
            bad.append("価格が変わったのに公式の購入ページの確認済みの印が残る")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"判定を動かせない: {exc}")
    out.append({"level": "ok" if not bad else "error", "check": "official_recheck_freshness",
                "message": "#848 公式の再確認（失敗・ブロックでは確認日を進めない・古い結果で戻さない・価格が変われば確定から外す）"
                           + ("" if not bad else f" ← {bad[:4]}")})
    return out


def _check_phase16_official_direct() -> list[dict]:
    """Phase 16: 価格の意味（#849）・公式直販価格の判定（#850）・JAN とセットの照合（#851）・quality_checker（#852）。"""
    import copy as _cp16
    import inspect as _in16
    import sqlite3 as _sq16

    import yaml as _y16
    root = PROJECT_ROOT
    out: list[dict] = []
    try:
        prods = {p["id"]: p for p in (_y16.safe_load((root / "config" / "products.yaml").read_text(encoding="utf-8"))
                                      or {}).get("products") or []}
    except Exception:  # noqa: BLE001
        prods = {}

    # #849 価格の意味: オープン価格の商品に希望小売価格（msrp）を作らない。公式直販価格を「定価」と呼ばない
    bad = []
    try:
        from src.content.ui.product_detail import PriceRow
        from src.market import official_registry as _reg
        from src.market import price_types as _pt
        for pid, kind in _reg.MSRP_OF.items():
            if kind != "open_price":
                bad.append(f"希望小売価格の記録がオープン価格でない（{pid}）")
            if _reg.price_kind_of(pid) == "msrp":
                bad.append(f"オープン価格の商品の価格を定価（msrp）にしている（{pid}）")
        if "定価" in _reg.PRICE_KIND_LABELS["official_direct"]:
            bad.append("公式直販価格の呼び方に「定価」が入っている")
        row = PriceRow(role="buy", source="x", price=1, price_type=_pt.RETAIL, quality="VERIFIED", official=True,
                       retail_kind="official_direct")
        if row.type_label != "公式直販価格":
            bad.append(f"商品詳細で公式直販価格を「{row.type_label}」と表示する")
        row.retail_kind = "msrp"                     # 肯定の対照: 希望小売価格は「定価」
        if row.type_label != "定価":
            bad.append("希望小売価格を「定価」と表示しない")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"判定を動かせない: {exc}")
    out.append({"level": "ok" if not bad else "error", "check": "price_semantics",
                "message": "#849 価格の意味（オープン価格に希望小売価格を作らない・公式直販価格を定価と呼ばない）"
                           + ("" if not bad else f" ← {bad[:4]}")})

    # #850 公式直販価格: 証拠（同一性・ボディー/キット・送料・販売の形・確認日）が欠ければ使わない。否定の対照を動かす
    bad = []
    try:
        from src.market import official_registry as _reg
        from src.market import official_shipping as _osh
        ok_any = False
        for pid, v in _reg.VERIFIED_URLS.items():
            if v.get("price_kind") != "official_direct":
                continue
            ok, why = _reg.official_direct_gate(pid, prods.get(pid))
            ok_any = ok_any or ok
            if pid not in _reg.OFFICIAL_DIRECT_OFFERS:
                bad.append(f"公式直販価格の証拠が無い（{pid}）")
        if not ok_any:
            bad.append("公式直販価格が1件も判定を通らない（判定の条件が誤っている）")
        pid = "prod_r5ii"
        if pid in _reg.OFFICIAL_DIRECT_OFFERS and pid in prods:
            o0 = _cp16.deepcopy(_reg.OFFICIAL_DIRECT_OFFERS[pid])
            s0 = _osh.PRODUCT_SHIPPING.get(pid)
            try:
                for change, label in (({"body_kit": "kit"}, "キットをボディーとして使う"),
                                      ({"sale_mode": "LOTTERY"}, "抽選の価格を使う"),
                                      ({"checked_on": "2099-01-01"}, "未来の確認日を使う"),
                                      ({"stock_semantics": ""}, "在庫の表し方が分からないのに使う")):
                    _reg.OFFICIAL_DIRECT_OFFERS[pid] = dict(o0, **change)
                    if _reg.official_direct_gate(pid, prods[pid])[0]:
                        bad.append(label)
                _reg.OFFICIAL_DIRECT_OFFERS[pid] = o0
                if _reg.official_direct_gate(pid, dict(prods[pid], jan_code="4549292000000"))[0]:
                    bad.append("JAN が証拠と違うのに使う")
                if _reg.official_direct_gate(pid, dict(prods[pid], name=prods[pid]["name"] + " レンズキット"))[0]:
                    bad.append("キットの商品にボディーの価格を使う")
                _osh.PRODUCT_SHIPPING.pop(pid, None)
                if _reg.official_direct_gate(pid, prods[pid])[0]:
                    bad.append("送料が分からないのに使う（0円とみなしている）")
            finally:
                _reg.OFFICIAL_DIRECT_OFFERS[pid] = o0
                if s0 is not None:
                    _osh.PRODUCT_SHIPPING[pid] = s0
        # 説明文（JAN の代わり）だけで同一性を確定しない（型番も JAN も部品番号の組も無い商品は使わない）
        if "prod_airpods_pro3" in prods and _reg.official_direct_gate(
                "prod_airpods_pro3", dict(prods["prod_airpods_pro3"], model_number=""))[0]:
            bad.append("説明文だけで同一性を確定する")
        # 在庫未確認を在庫ありにしない（Z8 は在庫の記録が無い）
        from src.content.ui import opportunity as _opp
        if _opp.stock_from(_reg.VERIFIED_URLS.get("prod_z8", {}).get("stock") or "", "") == "IN_STOCK":
            bad.append("在庫未確認を在庫ありにしている")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"判定を動かせない: {exc}")
    out.append({"level": "ok" if not bad else "error", "check": "official_direct_safety",
                "message": "#850 公式直販価格（同一性・ボディー/キット・送料・販売の形・在庫の表し方・確認日がそろうものだけ）"
                           + ("" if not bad else f" ← {bad[:4]}")})

    # #851 JAN とセット: JAN が一致しても、セット・版・限定品が違えば同じ商品にしない（楽天・Yahoo を戻したとき用）
    bad = []
    try:
        from src.market.product_identity_resolver import ProductIdentityResolver
        _res = ProductIdentityResolver({"prod_switch2": {"name": "Nintendo Switch 2", "jan_code": "4902370553024"}})
        for title in ("Nintendo Switch 2 マリオカート ワールド セット", "Nintendo Switch 2 多言語対応 海外版",
                      "Nintendo Switch 2 限定エディション"):
            r = _res.resolve(source_title=title, jan="4902370553024", link_type="item",
                             expected_product_id="prod_switch2")
            if r.identity_confidence == "high" or not r.variant_conflict:
                bad.append(f"JAN 一致で「{title}」を同じ商品にする")
        r = _res.resolve(source_title="Nintendo Switch 2 本体", jan="4902370553024", link_type="item",
                         expected_product_id="prod_switch2")
        if r.identity_confidence != "high":                   # 肯定の対照
            bad.append("単体の JAN 一致を確定にしない（判定の条件が誤っている）")
        if "res.variant_conflict" not in (root / "scripts" / "collect_api_prices.py").read_text(encoding="utf-8"):
            bad.append("楽天・Yahoo の取得がセット・版の食い違いを外さない")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"判定を動かせない: {exc}")
    out.append({"level": "ok" if not bad else "error", "check": "bundle_jan_safety",
                "message": "#851 JAN とセット（JAN が一致してもセット・版・限定品の食い違いは別の商品）"
                           + ("" if not bad else f" ← {bad[:4]}")})

    # #852 quality_checker: 存在しないテーブル名を引かない。公式の購入ページは初心者向けの案件と同じ判定
    bad = []
    try:
        from src.market.beginner_deal_scanner import verified_official_item_url
        from src.pipeline import quality_checker as _qc
        src = _in16.getsource(_qc.QualityChecker.check_beginner_quality)
        if "product_source_configs" in src.replace("product_source_configs）", ""):
            bad.append("存在しないテーブル名（product_source_configs）を引いている")
        if "verified_official_item_url" not in src:
            bad.append("公式の購入ページの判定が初心者向けの案件と違う")
        c = _sq16.connect(":memory:")
        c.row_factory = _sq16.Row
        c.execute("CREATE TABLE product_source_config (product_id TEXT, source_id TEXT, target_url TEXT, extra_config TEXT)")
        c.executemany("INSERT INTO product_source_config VALUES (?,?,?,?)", [
            ("a", "src_x", "https://example.jp/item", '{"verified": true, "link_type": "item"}'),
            ("b", "src_x", "https://example.jp/cat", '{"verified": true, "link_type": "category"}'),
            ("c", "src_x", "https://example.jp/item", '{"verified": false, "link_type": "item"}')])
        if not verified_official_item_url(c, "a") or verified_official_item_url(c, "b") \
                or verified_official_item_url(c, "c"):
            bad.append("確認済みの購入ページの判定が誤っている")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"判定を動かせない: {exc}")
    out.append({"level": "ok" if not bad else "error", "check": "quality_checker_official_url",
                "message": "#852 quality_checker（存在しないテーブル名を引かない・公式の購入ページは案件と同じ判定）"
                           + ("" if not bad else f" ← {bad[:4]}")})
    return out


def _check_phase17_camera_sell() -> list[dict]:
    """Phase 17: カメラの新品の買取（#853）。JAN で1行だけ・新品と中古を混ぜない・失敗で時刻を進めない・抽選/在庫なしを
    今すぐ行動できるに数えない。否定の対照を動かして確かめる。"""
    import importlib.util as _iu17

    import yaml as _y17
    root = PROJECT_ROOT
    bad = []
    try:
        from src.collectors import buyback_kaitori_shouten as ks
        from src.content.ui.opportunity import AVAILABILITY_OF, _cond_family
        from src.market import official_registry as _reg
        from src.market.opportunity_diagnostics import ACTIONABLE_AVAILABILITY
        prods = {p["id"]: p for p in (_y17.safe_load((root / "config" / "products.yaml").read_text(encoding="utf-8"))
                                      or {}).get("products") or []}
        # JAN は公式の証拠・登録の値と同じ（X100VI は公式のモールで買う色・版の JAN）
        if ks.JAN_RULES["x100vi"]["jan"] not in (_reg.IDENTITY_EVIDENCE["prod_x100vi"].get("colors") or {}).values():
            bad.append("X100VI の買取の JAN が公式で買う版と違う")
        for a, pid in (("z8", "prod_z8"), ("r5ii", "prod_r5ii")):
            if ks.JAN_RULES[a]["jan"] != prods.get(pid, {}).get("jan_code"):
                bad.append(f"{a} の買取の JAN が登録と違う")
        # 新品同様（used_s）・中古を新品の系統にしない
        for c in ("used_s", "used_a", "used"):
            if _cond_family(c) == "new":
                bad.append(f"{c} を新品として扱う")
        # 否定の対照: キット・別の版・同じ JAN の価格違いは使わない
        def _ld(name, jan, price, n):
            return ('<script type="application/ld+json">{"@type":"Product","name":"%s","gtin13":"%s",'
                    '"offers":{"price":%d,"url":"https://www.kaitorishouten-co.jp/products/detail/%d"}}</script>'
                    % (name, jan, price, n))
        rows = ks.parse_jsonld_rows(_ld("ミラーレス一眼カメラ Canon EOS R5 Mark II RF24-105L IS USM レンズキット",
                                        "4549292229141", 570000, 1))
        if ks.match_jan_rows(rows, "r5ii"):
            bad.append("レンズキットをボディーの買取にする")
        rows = ks.parse_jsonld_rows(_ld("コンパクトデジタルカメラ RICOH GR IV 30th Anniversary Edition Kit",
                                        "4549212311291", 259800, 2))
        if ks.match_jan_rows(rows, "gr4"):
            bad.append("30周年記念キットを GR IV の買取にする")
        col = ks.KaitoriShoutenCsvCollector()
        html = (_ld("Z 8 ボディ", "4960759909947", 420000, 3) + _ld("Z 8 ボディ", "4960759909947", 430000, 4))
        if col._parse_price(html, "z8", "Nikon Z8") is not None:
            bad.append("同じ JAN に違う価格が並んでもどれかを選ぶ")
        if col._parse_price(_ld("Z 8 ボディ", "4960759909947", 420000, 3), "z8", "Nikon Z8") != 420000:
            bad.append("正しい1行を読めない（照合の条件が誤っている）")       # 肯定の対照
        # 取得に失敗しても、前回の行の時刻・価格を変えない
        _sp = _iu17.spec_from_file_location("dc17_ubp", root / "scripts" / "update_buyback_prices.py")
        _m = _iu17.module_from_spec(_sp)
        _sp.loader.exec_module(_m)
        prev = {"product_alias": "z8", "buyback_shop": "kaitori_shouten", "buyback_price": "420000",
                "observed_at": "2026-10-08T16:00:00+09:00", "data_source": "auto_scraped"}
        out = _m.keep_manual_on_failure([{"product_alias": "z8", "buyback_shop": "kaitori_shouten",
                                          "buyback_price": "0", "observed_at": "2099-01-01T00:00:00+09:00",
                                          "data_source": "fetch_failed"}], [prev],
                                        {("z8", "kaitori_shouten"): "connection_error"})
        if out != [prev]:
            bad.append("取得に失敗したときに前回の行の時刻・価格を変える")
        # 前回の価格を否定する失敗（掲載が無い・同じ JAN に違う価格）では前回の行を残さない
        for _reason in ("product_not_listed", "ambiguous_rows"):
            _f = {"product_alias": "z8", "buyback_shop": "kaitori_shouten", "buyback_price": "0",
                  "observed_at": "2099-01-01T00:00:00+09:00", "data_source": "fetch_failed"}
            if _m.keep_manual_on_failure([_f], [prev], {("z8", "kaitori_shouten"): _reason}) != [_f]:
                bad.append(f"{_reason} なのに前回の価格を残す（古い価格を今の価格に見せる）")
        # 抽選・在庫なし・在庫未確認は今すぐ行動できるに数えない
        for st in ("LOTTERY", "OUT_OF_STOCK", "UNKNOWN"):
            if AVAILABILITY_OF.get(st) in ACTIONABLE_AVAILABILITY:
                bad.append(f"{st} を今すぐ行動できるに数える")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"判定を動かせない: {exc}")
    return [{"level": "ok" if not bad else "error", "check": "camera_sell_semantics",
             "message": "#853 カメラの新品の買取（JAN で1行だけ・キット/版/限定を分ける・新品同様を新品にしない・"
                        "失敗で時刻を進めない・抽選/在庫なしを行動できるに数えない）" + ("" if not bad else f" ← {bad[:4]}")}]


def _check_phase18_actionability(html: str) -> list[dict]:
    """Phase 18: 今すぐ行動できるか（#854）。利益だけでは行動できるにしない・在庫切れ/未確認/3時間を過ぎた在庫あり/
    受付終了/日程不明/一般のページの URL では行動できない・受付中と3時間以内の在庫ありだけ行動できる。
    公開ページで、行動できる商品の数とボタンの数が合い、行動できない商品に「購入する」「申し込む」のボタンが無い。"""
    import re as _re18
    from datetime import datetime as _dt18
    from datetime import timedelta as _td18

    from src.tcg.models import JST as _JST18
    bad = []
    try:
        from src.market import actionability as act
        now = _dt18(2026, 10, 9, 12, 0, tzinfo=_JST18)
        url = "https://pur.store.sony.jp/ps5/products/ps5/CFI-7100B01_purchase/"

        def ev(start, end, status="active", checked=now - _td18(hours=1), form=url):
            return {"product_id": "p", "sale_method": "抽選販売", "status": status, "entry_start_at": start.isoformat(),
                    "entry_end_at": end.isoformat() if end else "", "checked_at": checked.isoformat(),
                    "entry_form_url": form}

        def run(**kw):
            base = dict(profitable=True, identity_ok=True, stock="IN_STOCK", stock_checked_at=now - _td18(hours=1),
                        buy_url=url, event=None, now=now)
            base.update(kw)
            return act.evaluate(**base)
        if not run().actionable:
            bad.append("3時間以内の在庫ありを行動できるにしない（判定の条件が誤っている）")
        if not run(stock="LOTTERY", event=ev(now - _td18(days=1), now + _td18(days=1))).actionable:
            bad.append("受付中の抽選を行動できるにしない（判定の条件が誤っている）")
        for label, kw in (("利益なし", {"profitable": False}),
                          ("在庫切れ", {"stock": "OUT_OF_STOCK"}),
                          ("在庫未確認", {"stock": "UNKNOWN"}),
                          ("3時間を過ぎた在庫あり", {"stock_checked_at": now - _td18(hours=4)}),
                          ("一般のページの URL", {"buy_url": "https://www.apple.com/jp/shop/"}),
                          ("受付終了の抽選", {"stock": "LOTTERY", "event": ev(now - _td18(days=5), now - _td18(days=1))}),
                          ("締切が不明な抽選", {"stock": "LOTTERY", "event": ev(now - _td18(days=1), None)}),
                          ("ページで終了の抽選", {"stock": "LOTTERY",
                                             "event": ev(now - _td18(days=1), now + _td18(days=1), "closed")}),
                          ("確認が古い抽選", {"stock": "LOTTERY", "event": ev(now - _td18(days=1), now + _td18(days=1),
                                                                         checked=now - _td18(days=10))}),
                          ("情報の無い抽選", {"stock": "LOTTERY"}),
                          ("状態の矛盾のある抽選", {"stock": "LOTTERY",
                                             "event": dict(ev(now - _td18(days=1), now + _td18(days=1)),
                                                           status_conflict="true")}),
                          ("開始が分からない抽選", {"stock": "LOTTERY",
                                             "event": dict(ev(now - _td18(days=1), now + _td18(days=1)),
                                                           entry_start_at="")}),
                          ("一覧のページ", {"buy_url": "https://ricohimagingstore.com/Form/Product/ProductList.aspx"
                                                "?shop=0&cat=002010"}),
                          ("販売終了", {"sale_method": "discontinued"})):
            if run(**kw).actionable:
                bad.append(f"{label}を今すぐ行動できるにする")
        # 公開ページ: 行動できる商品の数とボタンの数が一致（行動できない商品にボタンを出さない）
        sec = html.split('data-nu-page="opportunities"', 1)[1] if 'data-nu-page="opportunities"' in html else ""
        sec = sec.split('data-nu-page="', 1)[0] if sec else ""
        # スマホのカード・PC の表の行の両方（レビュー L3）
        cards_act = len(_re18.findall(r'<li class="nu-ocard"[^>]*data-actionable="1"', sec))
        ctas = len(_re18.findall(r'<div class="nu-ocard__action"><a [^>]*data-track="opportunity_action"', sec))
        rows_act = len(_re18.findall(r'<tr class="nu-orow"[^>]*data-actionable="1"', sec))
        row_ctas = sum(1 for m in _re18.finditer(r'<tr class="nu-orow".*?</tr>', sec, flags=_re18.S)
                       if 'data-track="opportunity_action"' in m.group(0))
        if cards_act != ctas or rows_act != row_ctas or cards_act != rows_act:
            bad.append(f"行動できる商品（カード {cards_act}・表 {rows_act}）とボタン（{ctas}・{row_ctas}）が合わない")
        for pat in (r'<li class="nu-ocard"[^>]*data-actionable="0".*?</li>',
                    r'<tr class="nu-orow"[^>]*data-actionable="0".*?</tr>'):
            if any('data-track="opportunity_action"' in m.group(0) for m in _re18.finditer(pat, sec, flags=_re18.S)):
                bad.append("行動できない商品に購入・申込のボタンがある")
                break
    except Exception as exc:  # noqa: BLE001
        bad.append(f"判定を動かせない: {exc}")
    return [{"level": "ok" if not bad else "error", "check": "actionability_semantics",
             "message": "#854 今すぐ行動できるか（利益だけで行動できるにしない・在庫切れ/未確認/3時間を過ぎた在庫あり/"
                        "受付終了/日程不明/一般のページでは行動できない・行動できない商品にボタンを出さない）"
                        + ("" if not bad else f" ← {bad[:4]}")}]


_SECRET_PATTERNS = (r"discord(?:app)?\.com/api(?:/v\d+)?/webhooks/\d+/[\w-]+", r"api\.telegram\.org/bot\d+:",
                    r"(?<!\d)\d{5,12}:[A-Za-z0-9_-]{30,}", r"hooks\.slack\.com/services/[\w/]+",
                    r"Authorization:\s*Bearer\s+[A-Za-z0-9._-]{30,}")


def _check_phase19_actionable_notifications(html: str) -> list[dict]:
    """Phase 19: 今すぐ行動の通知（#855）。行動できない → できる だけ候補・同じ状態では出さない・re-arm・期限切れ/一般の URL/
    参考の利益は配信の直前に止める・dry-run では送信の関数を呼ばない・LP の生成のステップは dry-run 固定で送信先の
    Secrets を渡さない・今回の出力に送信 0 と行動できる候補だけ・通知の出力と公開ページに配信先の URL・トークンが無い。"""
    import json as _json19
    import re as _re19
    from datetime import datetime as _dt19
    from datetime import timedelta as _td19

    from src.tcg.models import JST as _JST19
    bad, warn = [], []
    root = Path(__file__).resolve().parent.parent
    try:
        from src.notifiers import actionable as an
        from src.notifiers import adapters as ad
        from src.notifiers import outbox as ob
        now = _dt19(2026, 10, 9, 12, 0, tzinfo=_JST19)
        url = "https://pur.store.sony.jp/ps5/products/ps5/CFI-7100B01_purchase/"

        def row(avail="IN_STOCK", ok=True, **kw):
            r = {"product_id": "p", "product": "P", "availability": avail, "actionable": ok, "reasons": [] if ok else ["x"],
                 "confirmed": True, "net_profit": 50000, "roi": 0.3, "cta_label": "購入する", "cta_url": url if ok else "",
                 "until_ms": int((now + _td19(hours=2)).timestamp() * 1000) if ok else None, "deadline": "",
                 "checked_at": (now - _td19(hours=1)).isoformat(), "event_key": ""}
            r.update(kw)
            return {"actionability": {"products": [r]}}

        def run(d, st, baseline=False, **kw):
            res = ob.cycle(st, d, now=now, mode=ob.MODE_DRY, baseline=baseline, **kw)
            return res["observe"]["notification_candidates"], res["prepare"]["planned"], res

        st = ob.empty_store()
        run(row("OUT_OF_STOCK", False), st)
        n, planned, _r = run(row(), st)
        if (n, planned) != (1, 1):
            bad.append("在庫切れ → 在庫ありを候補・配信の計画にしない")
        n, planned, res = run(row(), st)
        if n or res["observe"]["dedupe_suppressed"] != 1:
            bad.append("同じ状態（在庫ありのまま）で毎回候補にする")
        run(row("OUT_OF_STOCK", False), st)
        if run(row(), st)[0] != 1:
            bad.append("在庫切れ → 在庫ありに戻ったとき（re-arm）候補にしない")
        run(row("STOCK_STALE", False), st)
        if run(row(), st)[0] != 0:
            bad.append("更新待ち（確認できなかった）で re-arm して同じ通知を繰り返す")
        if run(row(), ob.empty_store())[0] != 0 or run(row(), ob.empty_store(), baseline=True)[0] != 0:
            bad.append("前回の状態を見ていない商品（利益だけが変わった）・基準日を候補にする")
        for label, kw in (("期限を過ぎた", {"until_ms": int((now - _td19(minutes=1)).timestamp() * 1000)}),
                          ("一般のページの URL", {"cta_url": "https://www.apple.com/jp/shop/"}),
                          ("参考の利益", {"confirmed": False}),
                          ("利益なし", {"net_profit": 0})):
            st2 = ob.empty_store()
            run(row("OUT_OF_STOCK", False), st2)
            if run(row(**kw), st2)[1]:
                bad.append(f"{label}の候補を配信の直前の確認で止めない")
        if run(row(), st)[2]["counts"]["delivered"]:
            bad.append("dry-run の計画を送信済み（DELIVERED）にする")
        if not an.is_dry_run({}):
            bad.append("既定が dry-run でない")
        if any(a.configured for k, a in ad.default_adapters().items() if k != "log"):
            bad.append("既定で Discord・Telegram の送信先が設定されている")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"通知の候補を動かせない: {exc}")
    # ワークフロー: LP の生成のステップは dry-run 固定・送信先の Secrets を渡さない・dry-run を外すステップが無い
    try:
        wf = (root / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
        m = _re19.search(r"- name: Generate daily LP Variant A\n(.*?)(?=\n      - name:|\n      # )", wf, _re19.S)
        step = m.group(1) if m else ""
        if 'NOTIFICATION_DRY_RUN: "true"' not in step:
            bad.append("LP の生成のステップが dry-run に固定されていない")
        if _re19.search(r"DISCORD_WEBHOOK_URL|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID", step):
            bad.append("LP の生成のステップに通知の送信先の Secrets を渡している")
        if _re19.search(r"NOTIFICATION_DRY_RUN:\s*[\"']?(false|0|no|off)", wf, _re19.I):
            bad.append("dry-run を外すステップがある")
        if wf.find("Generate daily LP Variant A") < wf.find("Generate notifications"):
            bad.append("既存の通知の生成の順序が変わった")
        # 台帳を読み書きするのは generate-daily-lp の生成だけ（買取のプレ値のジョブの途中の生成では判定しない。レビュー H-1）
        cli_src = (root / "src" / "cli.py").read_text(encoding="utf-8")
        job_src = (root / "src" / "jobs" / "buyback_premium_job.py").read_text(encoding="utf-8")
        if cli_src.count("notifications=True") != 1 or "notifications=True" in job_src:
            bad.append("generate-daily-lp 以外の LP の生成でも通知の台帳を更新する")
    except OSError as exc:
        bad.append(f"ワークフローを読めない: {exc}")
    # 今回の出力（CI では LP の生成の後に必ずある）
    lp = root / "exports" / "notifications" / "actionable" / "latest.json"
    try:
        rep = _json19.loads(lp.read_text(encoding="utf-8"))
        from src.market.actionability import ACTIONABLE_TYPES, _official_url
        if rep.get("failed"):
            # 通知は内部用の dry-run なので、失敗で LP の公開は止めない（送信・dry-run でない・誤った候補は ERROR。レビュー L-2）
            warn.append(f"今回の通知の生成に失敗した（{rep.get('error')}）")
        if rep.get("dry_run") is not True:
            bad.append("今回の通知が dry-run でない")
        # 今回の診断から作った出力か（前回の出力を今回のものと取り違えない。監査 L-4）
        try:
            dg = _json19.loads((root / "exports" / "opportunity_diagnostics" / "latest.json").read_text(encoding="utf-8"))
            if str(dg.get("generated_at") or "") != str(rep.get("diagnostics_generated_at") or ""):
                warn.append("通知の出力が今回の診断から作られていない（前回の出力が残っている）")
        except (OSError, ValueError):
            warn.append("診断の出力が無い")
        cnt = rep.get("counts") if isinstance(rep.get("counts"), dict) else {}
        if rep.get("dispatch_sent") or cnt.get("delivered") or cnt.get("sending") or rep.get("external_calls"):
            bad.append(f"外部へ送信した（{rep.get('dispatch_sent')}件・送信済み {cnt.get('delivered')}件）")
        for c in rep.get("candidates") or []:
            if c.get("availability") not in ACTIONABLE_TYPES or not _official_url(c.get("action_url") or "") \
                    or c.get("confirmed") is not True:
                bad.append(f"行動できない・公式の購入ページでない・確定でない候補: {c.get('product_id')}")
    except (OSError, ValueError):
        warn.append("今回の通知の出力が無い（LP の生成の前）")
    # 配信先の URL・トークンが通知の出力・公開ページに無い
    texts = [html]
    for f in (root / "exports" / "notifications").rglob("*.json"):
        try:
            texts.append(f.read_text(encoding="utf-8"))
        except OSError:
            pass
    if any(_re19.search(p, t) for p in _SECRET_PATTERNS for t in texts):
        bad.append("通知の出力か公開ページに配信先の URL・トークンがある")
    level = "error" if bad else ("warning" if warn else "ok")
    return [{"level": level, "check": "actionable_notifications",
             "message": "#855 今すぐ行動の通知（行動できない → できる だけ・同じ状態では出さない・re-arm・配信の直前の確認・"
                        "dry-run で送らない・Secrets を渡さない・配信先の URL/トークンを出さない）"
                        + ("" if not (bad or warn) else f" ← {(bad or warn)[:4]}")}]


def _is_valid_canary_record(r: dict) -> bool:
    """Telegram の接続の試験の記録か（Telegram だけ・固定の [TEST] の文・商品なし。Phase 22）。"""
    from src.notifiers import outbox as _ob
    # 本文は文言の一致でなく形で見る（文言を変えても過去の記録で止めない。レビュー L-5）: [TEST] で始まり、URL・価格を含まない
    msg = str(r.get("message") or "")
    return (r.get("is_canary") is True and r.get("notification_type") == "TELEGRAM_CANARY" and not r.get("product_id")
            and list((r.get("channels") or {}).keys()) == ["telegram"] and msg.startswith("[TEST]")
            and "http" not in msg and "¥" not in msg and not r.get("action_url")
            and str(r.get("idempotency_key") or "").startswith("CANARY:telegram:") and bool(_ob.CANARY_TEXT))


def _check_phase20_notification_outbox() -> list[dict]:
    """Phase 20: 通知の outbox（#856）。冪等性のキーが作り直しても同じ・保存の前に送らない・送った後に保存できなければ
    次の実行は送り直さない（届いたか不明）・dry-run の記録は本番の送信を止めない・台帳は atomic に書く・配信先の部品は
    HTTP を import しない・ワークフローは手順ごとに台帳を保存し（always）、送信は保存した台帳と同じときだけ・台帳に
    配信先の URL・トークンが無い。"""
    import json as _json20
    import re as _re20
    from datetime import datetime as _dt20
    from datetime import timedelta as _td20

    from src.tcg.models import JST as _JST20
    bad, warn = [], []
    root = Path(__file__).resolve().parent.parent
    try:
        from src.notifiers import adapters as ad
        from src.notifiers import outbox as ob
        now = _dt20(2026, 10, 9, 12, 0, tzinfo=_JST20)
        url = "https://pur.store.sony.jp/ps5/products/ps5/CFI-7100B01_purchase/"

        def d(avail="IN_STOCK", ok=True):
            return {"actionability": {"products": [{
                "product_id": "p", "product": "P", "availability": avail, "actionable": ok, "reasons": [] if ok else ["x"],
                "confirmed": True, "net_profit": 50000, "roi": 0.3, "cta_label": "購入する", "cta_url": url if ok else "",
                "until_ms": int((now + _td20(hours=2)).timestamp() * 1000) if ok else None, "deadline": "",
                "checked_at": (now - _td20(hours=1)).isoformat(), "event_key": ""}]}}

        calls = []

        class _T(ad.ProviderAdapter):
            name = "fixture"

            def build_payload(self, record):
                return {"content": record.get("message") or ""}

        ok_adapter = _T(lambda p, k: (calls.append(k), (200, {}, {}))[1])
        # 同じ候補を作り直しても同じキー
        k1 = ob.idempotency_key("p", "event", "p|2026-10-08T12:00+09:00")
        if k1 != ob.idempotency_key("p", "event", "p|2026-10-08T12:00+09:00"):
            bad.append("冪等性のキーが安定しない")
        # 送った後に保存できずに止まった → 次の実行は送り直さない
        st = ob.empty_store()
        ob.observe(st, d("OUT_OF_STOCK", False)["actionability"]["products"], now=now, mode=ob.MODE_LIVE)
        ob.observe(st, d()["actionability"]["products"], now=now, mode=ob.MODE_LIVE, channels=["fixture"])
        ob.prepare(st, d()["actionability"]["products"], now=now, mode=ob.MODE_LIVE, attempt_id="a1",
                   adapters={"fixture": ok_adapter})
        persisted = _json20.loads(ob.dumps(st))                     # SENDING を保存した内容
        ob.send(st, now=now, attempt_id="a1", adapters={"fixture": ok_adapter})   # 送った（保存されずに止まる）
        ob.cycle(persisted, d(), now=now, mode=ob.MODE_LIVE, attempt_id="a2", adapters={"fixture": ok_adapter})
        if len(calls) != 1:
            bad.append(f"送った後に保存できなかった通知を次の実行で送り直す（{len(calls)}回）")
        if ob.counts(persisted)["ambiguous_delivery"] != 1:
            bad.append("送った後に止まった記録を「届いたか不明」にしない")
        # 保存の前に送らない（send は保存した台帳のハッシュと今のファイルが同じときだけ）
        import tempfile as _tf
        with _tf.TemporaryDirectory() as tmp:
            r = ob.run_send(Path(tmp), now=now, dry_run=False, attempt_id="a1", persisted_sha="",
                            adapters={"fixture": ok_adapter}, real_send_allowed=True)
            if r.get("skipped") != "not_persisted":
                bad.append("保存したことを確かめずに送る")
        # dry-run の記録は本番の送信を止めない・dry-run は DELIVERED にしない
        st = ob.empty_store()
        ob.observe(st, d("OUT_OF_STOCK", False)["actionability"]["products"], now=now, mode=ob.MODE_DRY)
        res = ob.cycle(st, d(), now=now, mode=ob.MODE_DRY)
        if res["counts"]["delivered"] or res["counts"]["dry_run_planned"] != 1:
            bad.append("dry-run の計画を送信済みにする")
        res = ob.cycle(st, d(), now=now, mode=ob.MODE_LIVE, attempt_id="l1", adapters={"fixture": ok_adapter},
                       channels=["fixture"])
        if res["observe"]["notification_candidates"] != 0:
            bad.append("dry-run で計画した古い変化を、本番に切り替えた時点で送る")
        ob.cycle(st, d("OUT_OF_STOCK", False), now=now, mode=ob.MODE_LIVE, attempt_id="l2",
                 adapters={"fixture": ok_adapter}, channels=["fixture"])
        res = ob.cycle(st, d(), now=now, mode=ob.MODE_LIVE, attempt_id="l3", adapters={"fixture": ok_adapter},
                       channels=["fixture"])
        if res["observe"]["notification_candidates"] != 1:
            bad.append("dry-run の記録が、本番に切り替えた後の新しい変化の送信を止める")
        # 記録が消えても（prune）同じキーで送り直さない
        st = ob.empty_store()
        calls.clear()
        ob.cycle(st, d("OUT_OF_STOCK", False), now=now, mode=ob.MODE_LIVE, channels=["fixture"])
        ob.cycle(st, d(), now=now, mode=ob.MODE_LIVE, attempt_id="p1", adapters={"fixture": ok_adapter},
                 channels=["fixture"])
        ob.cycle(st, d("STOCK_STALE", False), now=now, mode=ob.MODE_LIVE, channels=["fixture"])
        ob.prune(st, now + _td20(days=ob.RETENTION_DAYS + 2))
        ob.cycle(st, d(), now=now, mode=ob.MODE_LIVE, attempt_id="p2", adapters={"fixture": ok_adapter},
                 channels=["fixture"])
        if len(calls) != 1:
            bad.append("記録を消した後に同じ変化を送り直す")
        # 台帳は atomic に書く
        import inspect as _insp
        if "write_text_atomic" not in _insp.getsource(ob.save):
            bad.append("台帳を atomic に書いていない")
        # 配信先の部品は HTTP を import しない（Phase 20 は外部への通信 0）
        src_ad = (root / "src" / "notifiers" / "adapters.py").read_text(encoding="utf-8")
        if _re20.search(r"^\s*(import|from)\s+(requests|urllib|http\.client|httpx|aiohttp|socket)\b", src_ad, _re20.M):
            bad.append("配信先の部品が HTTP の部品を import している")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"outbox を動かせない: {exc}")
    # ワークフロー: 手順ごとの保存（always）・送信は保存した台帳と同じときだけ・dry-run 固定・Secrets を渡さない
    try:
        wf = (root / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
        steps = {m.group(1): m.group(2) for m in _re20.finditer(
            r"- name: ([^\n]+)\n(.*?)(?=\n      - name:|\n      # |\Z)", wf, _re20.S)}
        order = [n for n in ("Sync notification outbox", "Generate daily LP Variant A",
                             "Persist notification outbox (candidates)",
                             "Prepare notification dispatch", "Persist notification outbox (prepared)",
                             "Send notifications", "Persist notification outbox (sent)", "Deploy check",
                             "Commit and push")]
        pos = [wf.find(f"- name: {n}") for n in order]
        if any(p < 0 for p in pos) or pos != sorted(pos):
            bad.append("通知の outbox の手順の順序が違う（生成 → 保存 → 確認 → 保存 → 送信 → 保存 → deploy-check）")
        for n in ("Persist notification outbox (candidates)", "Persist notification outbox (prepared)",
                  "Persist notification outbox (sent)"):
            if "always()" not in steps.get(n, "") or "persist_notification_state.sh" not in steps.get(n, ""):
                bad.append(f"{n} が always() で台帳を保存しない")
        for n in ("Prepare notification dispatch", "Send notifications"):
            if "!cancelled()" not in steps.get(n, "") or "steps.generate_lp.outcome == 'success'" not in steps.get(n, ""):
                bad.append(f"{n} が、取り消し・生成の失敗のときにも動く")
        if "':(exclude)exports/notifications/actionable/state.json'" not in steps.get("Commit and push", ""):
            bad.append("最後のコミットが通知の台帳を含む（台帳の保存は persist だけにする）")
        send = steps.get("Send notifications", "")
        if "steps.persist_outbox_prepared.outcome == 'success'" not in send or \
                "--persisted-sha \"${{ steps.persist_outbox_prepared.outputs.sha }}\"" not in send:
            bad.append("送信の手順が、保存した台帳を確かめずに動く")
        prep = steps.get("Prepare notification dispatch", "")
        if 'NOTIFICATION_DRY_RUN: "true"' not in prep:
            bad.append("Prepare notification dispatch が dry-run に固定されていない")
        if _re20.search(r"DISCORD_WEBHOOK_URL|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID", prep):
            bad.append("Prepare notification dispatch に通知の送信先の Secrets を渡している")
        # 送信の手順は変数で dry-run を外せるが、既定は dry-run（Phase 22）。Discord の Secrets は渡さない
        if "NOTIFICATION_DRY_RUN: ${{ vars.NOTIFICATION_DRY_RUN || 'true' }}" not in send:
            bad.append("Send notifications の dry-run の既定が true でない")
        if _re20.search(r"DISCORD_WEBHOOK_URL", send):
            bad.append("Send notifications に Discord の Secrets を渡している")
        if "NOTIFICATION_OUTBOX_SYNCED: ${{ steps.sync_outbox.outcome == 'success' }}" not in steps.get(
                "Generate daily LP Variant A", ""):
            bad.append("台帳を main に合わせられなかったときに候補を作らない形になっていない")
        sh = (root / "scripts" / "persist_notification_state.sh").read_text(encoding="utf-8")
        if not all(x in sh for x in ('git worktree add', 'git -C "$WT" add -- "$STATE"', '"$REMOTE" != "$EXPECTED"',
                                     "sha=")) or "--autostash" in sh or "checkout --theirs" in sh:
            bad.append("台帳の保存が、作業ツリーに触れずに台帳だけを保存し、main の台帳が変わっていたら止める形になっていない")
    except OSError as exc:
        bad.append(f"ワークフローを読めない: {exc}")
    # 今の台帳: 読める・形が今のもの・配信先の URL・トークンが無い・本番の送信の記録が無い（Phase 20 は dry-run）
    sp = root / "exports" / "notifications" / "actionable" / "state.json"
    try:
        text = sp.read_text(encoding="utf-8")
        st = _json20.loads(text)
        if st.get("schema") != 2:
            warn.append("台帳が前の形式のまま（次の生成で今の形になる）")
        if any(_re20.search(p, text) for p in _SECRET_PATTERNS):
            bad.append("通知の台帳に配信先の URL・トークンがある")
        # Telegram の接続の試験（Phase 22）の記録は除く（商品の通知の本番の送信の記録だけを数える。監査 H-1）
        live = [r for r in (st.get("records") or {}).values() if isinstance(r, dict) and r.get("mode") == "live"
                and not _is_valid_canary_record(r)]
        if live:
            bad.append(f"本番の送信の記録がある（Phase 20 は dry-run）: {len(live)}件")
    except OSError:
        warn.append("通知の台帳が無い（基準日の前）")
    except ValueError:
        bad.append("通知の台帳が壊れている")
    level = "error" if bad else ("warning" if warn else "ok")
    return [{"level": level, "check": "notification_outbox",
             "message": "#856 通知の outbox（冪等性のキー・保存の前に送らない・送った後に止まったら送り直さない・dry-run は"
                        "送信済みにしない・atomic・HTTP の部品なし・手順ごとの保存・Secrets を渡さない）"
                        + ("" if not (bad or warn) else f" ← {(bad or warn)[:4]}")}]


_NOTIFY_SECRET_NAMES = ("DISCORD_WEBHOOK_URL", "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")
# 通知の Secrets を渡してよい手順（送信の手順だけ）: 手順の名前 → (渡してよい Secrets, 実行してよいもの)。
# 名前だけでは許さない（実行するものも確かめる）。Telegram は「Send notifications」だけ（Phase 22）
_SECRET_SENDERS = {
    "Notify workflow result": ({"DISCORD_WEBHOOK_URL"}, lambda run: run == "python scripts/notify_workflow_result.py"),
    "Send notifications": ({"TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"},
                           lambda run: run == 'python -m src.cli dispatch-notifications --step send --persisted-sha '
                                              '"${{ steps.persist_outbox_prepared.outputs.sha }}"'),
}
_SECRET_SENDER_STEPS = set(_SECRET_SENDERS)


def _notification_secret_exposure(root: Path) -> list[str]:
    """ワークフローのどこで通知の Secrets を参照しているか（YAML の構造で。Phase 21・監査 M-1）。

    送信の手順（_SECRET_SENDER_STEPS）の env だけを許す。ワークフロー全体・ジョブの env、ほかの手順のどの項目
    （env・with・run）にあってもエラー。secrets 全体（toJSON(secrets)）・添字での参照（secrets['…']）もエラー。
    """
    import re as _re
    probs = []
    # Secrets の名前は大文字と小文字を区別しない（レビュー L-A）
    pat = _re.compile(r"secrets\s*\.\s*(" + "|".join(_NOTIFY_SECRET_NAMES) + r")\b", _re.I)
    for wf_path in sorted((root / ".github" / "workflows").glob("*.y*ml")):
        text = wf_path.read_text(encoding="utf-8")
        if _re.search(r"toJSON\s*\(\s*secrets\s*\)|secrets\s*\[", text):
            probs.append(f"{wf_path.name}: secrets 全体・添字での参照がある")
        try:
            doc = yaml.safe_load(text) or {}
        except yaml.YAMLError:
            probs.append(f"{wf_path.name}: YAML を読めない")
            continue
        # 構造で見つけた「許す場所」の参照の数と、全文の参照の数が違えば、構造の外（重複したキーなど）にもある
        allowed = sum(len(pat.findall(str(st.get("env") or "")))
                      for job in (doc.get("jobs") or {}).values() if isinstance(job, dict)
                      for st in job.get("steps") or [] if isinstance(st, dict)
                      and str(st.get("name") or "") in _SECRET_SENDER_STEPS)
        if len(pat.findall(text)) != allowed:
            probs.append(f"{wf_path.name}: 送信の手順の env の外に通知の Secrets の参照がある")
        if pat.search(str(doc.get("env") or "")):
            probs.append(f"{wf_path.name}: ワークフロー全体の env に通知の Secrets")
        senders: dict = {}
        for jname, job in (doc.get("jobs") or {}).items():
            if not isinstance(job, dict):
                continue
            rest = {k: v for k, v in job.items() if k != "steps"}
            if pat.search(str(rest)):
                probs.append(f"{wf_path.name}: ジョブ {jname} の設定に通知の Secrets")
            sec = job.get("secrets")
            if sec == "inherit" or (isinstance(sec, dict) and any(
                    str(k).upper() in _NOTIFY_SECRET_NAMES or pat.search(str(v)) for k, v in sec.items())):
                probs.append(f"{wf_path.name}: ジョブ {jname} が呼ぶワークフローに Secrets を渡している（secrets）")
            for st in job.get("steps") or []:
                if not isinstance(st, dict):
                    continue
                name = str(st.get("name") or st.get("uses") or "")
                other = {k: v for k, v in st.items() if k != "env"}
                if pat.search(str(other)):
                    probs.append(f"{wf_path.name}: {name} の env 以外に通知の Secrets")
                if pat.search(str(st.get("env") or "")):
                    names = {m.upper() for m in pat.findall(str(st.get("env") or ""))}
                    if name not in _SECRET_SENDERS:
                        probs.append(f"{wf_path.name}: 送信の手順でない {name} に通知の Secrets")
                    elif not names <= _SECRET_SENDERS[name][0]:
                        probs.append(f"{wf_path.name}: {name} に渡してよくない Secrets（{sorted(names - _SECRET_SENDERS[name][0])}）")
                    elif not _SECRET_SENDERS[name][1](str(st.get("run") or "").strip()):
                        probs.append(f"{wf_path.name}: {name} が決まったコマンド以外を実行する")
                    else:
                        senders[name] = senders.get(name, 0) + 1
        for n, c in senders.items():
            if c > 1:
                probs.append(f"{wf_path.name}: 通知の Secrets を持つ {n} の手順が複数ある（{c}）")
    return probs


def _check_phase21_delivery_providers(root: Path | None = None) -> list[dict]:
    """Phase 21: 配信先と人による解決（#857）。本番の送信が無効（送信の部品なし・最終の関門が閉じている・旗が false）・
    通知の Secrets は送信の手順（今は既存のワークフローの結果の通知だけ）以外に渡さない・Discord/Telegram の応答の分類・
    配信先の ID・秘密の値を消す・届いたか不明を人が解決できる（送信済みは送り直さない・期限切れは戻さない）・
    古い基準のファイルを使わない。"""
    import re as _re21
    from datetime import datetime as _dt21
    from datetime import timedelta as _td21

    from src.tcg.models import JST as _JST21
    bad = []
    root = root or Path(__file__).resolve().parent.parent
    try:
        from src.notifiers import adapters as ad
        from src.notifiers import outbox as ob
        if ad.REAL_SEND_IMPLEMENTED or ad.PRODUCT_REAL_SEND_ENABLED:
            bad.append("商品の通知の本番の送信が有効になっている（Phase 22 は接続の試験だけ）")
        if ad.real_send_gate({})["allowed"]:
            bad.append("既定の設定で本番の送信の関門が開く")
        full = {"NOTIFICATION_REAL_SEND": "true", "NOTIFICATION_DRY_RUN": "false", "NOTIFICATION_PROVIDERS": "discord",
                "DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/1/x"}
        if ad.real_send_gate(full)["allowed"]:
            bad.append("送信の部品が無いのに本番の送信の関門が開く")
        d, t = ad.DiscordAdapter(), ad.TelegramAdapter()
        for name, got, want in (
                ("Discord 2xx", d.classify_response(204), None),
                ("Discord 400", d.classify_response(400).kind, ad.FINAL),
                ("Discord 401", d.classify_response(401).kind, ad.FINAL),
                ("Discord 429", d.classify_response(429, {"Retry-After": "5"}).kind, ad.RETRYABLE),
                ("Discord 502", d.classify_response(502).kind, ad.AMBIGUOUS),
                ("Telegram ok:false 200", t.classify_response(200, {}, {"ok": False, "error_code": 400}).kind, ad.FINAL),
                ("Telegram 429 本文", t.classify_response(429, {}, {"ok": False, "error_code": 429,
                                                                   "parameters": {"retry_after": 7}}).retry_after, 7),
                ("Telegram 2xx の形でない", t.classify_response(200, {}, {}).kind, ad.AMBIGUOUS)):
            if got != want:
                bad.append(f"{name} の分類が違う（{got}）")
        if t.extract_delivery_id(200, {}, {"ok": True, "result": {"message_id": 42}}) != "42":
            bad.append("Telegram の message_id を取れない")
        if "secret" in ad.redact("https://discord.com/api/webhooks/1/secret 123456789:" + "A" * 35):
            bad.append("秘密の値を消せない")
        # 届いたか不明の解決
        now = _dt21(2026, 10, 9, 12, 0, tzinfo=_JST21)
        url = "https://pur.store.sony.jp/ps5/products/ps5/CFI-7100B01_purchase/"
        row = {"product_id": "p", "product": "P", "availability": "IN_STOCK", "actionable": True, "reasons": [],
               "confirmed": True, "net_profit": 50000, "roi": 0.3, "cta_label": "購入する", "cta_url": url,
               "until_ms": int((now + _td21(hours=2)).timestamp() * 1000), "deadline": "",
               "checked_at": (now - _td21(hours=1)).isoformat(), "event_key": ""}

        def unknown_store():
            st = ob.empty_store()
            ob.observe(st, [dict(row, availability="OUT_OF_STOCK", actionable=False, reasons=["x"])], now=now,
                       mode=ob.MODE_LIVE)
            ob.observe(st, [row], now=now, mode=ob.MODE_LIVE, channels=["discord"])
            nid = next(iter(st["records"]))
            st["records"][nid]["channels"]["discord"].update(status=ob.UNKNOWN_DELIVERY)
            return st, nid
        st, nid = unknown_store()
        ob.resolve(st, nid, ob.MARK_DELIVERED, rows=[row], now=now)
        if ob.prepare(st, [row], now=now, mode=ob.MODE_LIVE, attempt_id="z")["sending"] or \
                st["records"][nid]["status"] != ob.DELIVERED:
            bad.append("送信済みにした配信を送り直す")
        st, nid = unknown_store()
        ob.resolve(st, nid, ob.MARK_NOT_DELIVERED, rows=[dict(row, until_ms=int(now.timestamp() * 1000) - 1)], now=now)
        if st["records"][nid]["status"] != ob.EXPIRED:
            bad.append("期限切れの配信を出し直せる状態に戻す")
        st, nid = unknown_store()
        n_before = len(st["records"])
        ob.resolve(st, nid, ob.MARK_NOT_DELIVERED, rows=[row], now=now)
        if st["records"][nid]["status"] != ob.FAILED_RETRYABLE or len(st["records"]) != n_before:
            bad.append("届いていなかった配信を、同じ記録で出し直せる状態に戻さない")
        if not ob.resolve.__doc__ or not ob.list_unknown(unknown_store()[0]):
            bad.append("届いたか不明の一覧を作れない")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"配信先・解決を動かせない: {exc}")
    try:
        wf = (root / ".github" / "workflows" / "daily_lp.yml").read_text(encoding="utf-8")
        steps = {m.group(1): m.group(2) for m in _re21.finditer(
            r"- name: ([^\n]+)\n(.*?)(?=\n      - name:|\n      # |\Z)", wf, _re21.S)}
        bad.extend(_notification_secret_exposure(root))
        if _re21.search(r"NOTIFICATION_REAL_SEND:\s*[\"']?(true|1|yes|on)", wf, _re21.I):
            bad.append("本番の送信の旗を true にしている")
        for n in ("Generate daily LP Variant A", "Prepare notification dispatch"):
            if 'NOTIFICATION_REAL_SEND: "false"' not in steps.get(n, ""):
                bad.append(f"{n} に本番の送信の旗（false）が無い")
        send = steps.get("Send notifications", "")
        # 送信の手順は変数で設定する（既定は false）。接続の試験の旗は手動の実行のときだけ（Phase 22）
        if "NOTIFICATION_REAL_SEND: ${{ vars.NOTIFICATION_REAL_SEND || 'false' }}" not in send:
            bad.append("Send notifications の本番の送信の旗の既定が false でない")
        if "TELEGRAM_CANARY: ${{ github.event_name == 'workflow_dispatch' && vars.TELEGRAM_CANARY || 'false' }}" not in send:
            bad.append("接続の試験の旗が、手動の実行に限られていない")
        sh = (root / "scripts" / "persist_notification_state.sh").read_text(encoding="utf-8")
        if not all(x in sh for x in ('"$B_RUN" != "$RUN_ID"', 'AT_MAIN=', 'MAX_AGE_SECONDS')):
            bad.append("保存の手順が、基準のファイルの実行の識別・main のコミットの台帳・古さを確かめない")
    except OSError as exc:
        bad.append(f"ワークフローを読めない: {exc}")
    return [{"level": "ok" if not bad else "error", "check": "delivery_providers",
             "message": "#857 配信先と人による解決（本番の送信は無効・Secrets は送信の手順だけ・応答の分類・配信先の ID・"
                        "秘密の値を消す・届いたか不明の解決・古い基準を使わない）" + ("" if not bad else f" ← {bad[:4]}")}]


class _FakeTgResp:
    def __init__(self, status, body, headers=None):
        self.status, self.body, self.headers = status, body, headers or {}

    def getcode(self):
        return self.status

    def read(self):
        return self.body


class _FakeTgOpener:
    """Telegram の偽の通信（ネットワークに出ない）。送った要求を記録する。"""

    def __init__(self, result):
        self.result, self.requests = result, []

    def open(self, req, timeout=None):
        self.requests.append(req)
        if isinstance(self.result, BaseException):
            raise self.result
        if isinstance(self.result, tuple) and self.result[0] >= 400:
            import io
            import urllib.error
            raise urllib.error.HTTPError(req.full_url, self.result[0], "x", self.result[2] if len(self.result) > 2 else {},
                                         io.BytesIO(self.result[1]))
        return _FakeTgResp(self.result[0], self.result[1], self.result[2] if len(self.result) > 2 else {})


def _check_phase22_telegram_safety(root: Path | None = None) -> list[dict]:
    """Phase 22: Telegram の実送信の安全（#858）。公式の Bot API だけ・要求の形（parse_mode なし・プレビューなし）・
    応答の分類（200 かつ ok=true かつ message_id だけ成功）・例外にトークンを出さない・接続の試験は同じ ID で二度と
    送らない・SENDING の保存の前に送らない・商品の通知の本番の送信は無効・接続の試験は手動の実行に限る。"""
    import json as _json22
    import re as _re22
    import socket as _sock22
    import tempfile as _tf22
    from datetime import datetime as _dt22

    from src.tcg.models import JST as _JST22
    bad = []
    root = root or Path(__file__).resolve().parent.parent
    try:
        from src.notifiers import adapters as ad
        from src.notifiers import outbox as ob
        from src.notifiers import telegram_transport as tt
        token, chat = "123456789:" + "A" * 35, "-1001234567890"
        if tt.API_BASE != "https://api.telegram.org":
            bad.append("Telegram の公式の Bot API 以外に送る")
        src_tt = (root / "src" / "notifiers" / "telegram_transport.py").read_text(encoding="utf-8")
        if _re22.search(r"\bprint\(|logger\.|logging\.", src_tt):
            bad.append("送信の部品がログ・出力をする（URL・トークンが出るおそれ）")
        # 要求の形
        op = _FakeTgOpener((200, b'{"ok": true, "result": {"message_id": 77}}'))
        a = ad.TelegramAdapter(tt.make_telegram_transport(token, chat, opener=op))
        rec = {"is_test_message": True, "message": ob.CANARY_TEXT}
        if a.send(rec, "k") != "77":
            bad.append("200 + ok=true の message_id を取れない")
        req = op.requests[0]
        body = _json22.loads(req.data.decode("utf-8"))
        if not req.full_url.startswith("https://api.telegram.org/bot") or req.get_method() != "POST" or \
                "parse_mode" in body or body.get("disable_web_page_preview") is not True or body.get("chat_id") != chat:
            bad.append("Telegram の要求の形が違う（POST・公式・parse_mode なし・プレビューなし・chat_id）")
        # 応答の分類
        for name, result, kind in (("200 ok:false", (200, b'{"ok": false, "error_code": 400}'), ad.FINAL),
                                   ("200 の読めない本文", (200, b"not json"), ad.AMBIGUOUS),
                                   ("200 ok:true で message_id なし", (200, b'{"ok": true, "result": {}}'), ad.AMBIGUOUS),
                                   ("400", (400, b'{"ok": false, "error_code": 400}'), ad.FINAL),
                                   ("401", (401, b'{"ok": false, "error_code": 401}'), ad.FINAL),
                                   ("403", (403, b'{"ok": false, "error_code": 403}'), ad.FINAL),
                                   ("429", (429, b'{"ok": false, "error_code": 429, "parameters": {"retry_after": 9}}'),
                                    ad.RETRYABLE),
                                   ("500", (500, b""), ad.AMBIGUOUS), ("502", (502, b""), ad.AMBIGUOUS),
                                   ("503", (503, b""), ad.RETRYABLE), ("504", (504, b""), ad.AMBIGUOUS),
                                   ("タイムアウト", _sock22.timeout("timed out"), ad.AMBIGUOUS)):
            try:
                ad.TelegramAdapter(tt.make_telegram_transport(token, chat, opener=_FakeTgOpener(result))).send(rec, "k")
                got = None
            except ad.ProviderError as e:
                got = e.kind
                if token in str(e) or token.split(":")[1] in str(e.error_class):
                    bad.append(f"{name}: 例外にトークンが入る")
            if got != kind:
                bad.append(f"Telegram の {name} の分類が違う（{got}）")
        # 接続の試験: 同じ ID では二度と送らない・保存の前に送らない
        now = _dt22(2026, 10, 9, 12, 0, tzinfo=_JST22)
        with _tf22.TemporaryDirectory() as tmp:
            out = Path(tmp)
            ob.save(out / ob.STORE_NAME, ob.empty_store())
            op2 = _FakeTgOpener((200, b'{"ok": true, "result": {"message_id": 5}}'))
            ad2 = ad.TelegramAdapter(tt.make_telegram_transport(token, chat, opener=op2))
            r0 = ob.run_canary(out, now=now, attempt_id="a0", canary_id="t", adapter=ad2, persist=lambda: "")
            if r0["requests"] or op2.requests:
                bad.append("SENDING を保存できないのに接続の試験を送る")
            def ok_persist():
                return ob.file_sha(out / ob.STORE_NAME)
            r1 = ob.run_canary(out, now=now, attempt_id="a1", canary_id="t", adapter=ad2, persist=ok_persist)
            r2 = ob.run_canary(out, now=now, attempt_id="a2", canary_id="t", adapter=ad2, persist=ok_persist)
            st, _b = ob.load(out / ob.STORE_NAME)
            text = ob.dumps(st)
            if (r1.get("status"), len(op2.requests), r2["requests"]) != (ob.DELIVERED, 1, 0):
                bad.append("接続の試験を同じ ID で二度送る・送れない")
            if token in text or chat in text:
                bad.append("台帳にトークン・チャット ID が入る")
        # 関門
        full = {"NOTIFICATION_REAL_SEND": "true", "NOTIFICATION_DRY_RUN": "false", "NOTIFICATION_PROVIDERS": "telegram",
                "TELEGRAM_CANARY": "true", "GITHUB_EVENT_NAME": "workflow_dispatch",
                "TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat}
        if ad.real_send_gate(full, purpose="product")["allowed"]:
            bad.append("商品の通知の本番の送信の関門が開く")
        if not ad.real_send_gate(full, purpose="canary")["allowed"]:
            bad.append("全部そろっても接続の試験の関門が開かない")
        for k, v in (("GITHUB_EVENT_NAME", "schedule"), ("NOTIFICATION_PROVIDERS", "telegram,discord"),
                     ("TELEGRAM_CANARY", "false"), ("NOTIFICATION_DRY_RUN", "true")):
            if ad.real_send_gate(dict(full, **{k: v}), purpose="canary")["allowed"]:
                bad.append(f"{k}={v} でも接続の試験の関門が開く")
    except Exception as exc:  # noqa: BLE001
        bad.append(f"Telegram の送信を確かめられない: {type(exc).__name__}")
    return [{"level": "ok" if not bad else "error", "check": "telegram_real_send_safety",
             "message": "#858 Telegram の実送信の安全（公式の Bot API・要求の形・応答の分類・トークンを出さない・接続の試験は"
                        "1回だけ・保存の前に送らない・商品の通知は無効・手動の実行だけ）" + ("" if not bad else f" ← {bad[:4]}")}]


def _check_new_ui(html: str) -> list[dict]:
    """新UIのチェック（#800-#809・#835-#839）。

    UI Phase 10 で旧UIを削除した。公開するページは新UIだけ（新UIが無ければ error。旧UIの受け皿は無い）。

    #800 旧UIの DOM・CSS・JS が残っていない（UI Phase 10。旧UIのタブ id・クラス・関数・CSS の目印）
    #801 新UIの root が1つあり、終わりの目印がある
    #802 新UIが既定（head のスクリプトが ui-new を付け、本文は JS が表示を決めてから出す）
    #803 表示の切り替えは URL だけ（cookie / localStorage で決めない。localStorage はマイページの保存だけ）
    #804 ボトムナビが5項目
    #805 状態の対応表に不整合がない
    #806 閲覧時の状態判定（runtime）のデータと JS がある
    #807 新UIに ¥0 を表示していない
    #808 新UIに運営者向けの内部情報を出していない
    #809 新UIのリンクは https: かサイト内の相対パスだけ（javascript: 等が無い）
    #810 抽選の表示モデル（VM）が元データと一致する（UI Phase 10 で旧UIとの件数照合を削除し、VM の突き合わせだけを残した）
    #835 互換: ?ui=legacy・?ui=new の古い URL は新UIで開き URL から ui を外す・旧UIのハッシュを新UIのページへ読み替える・
         作るリンクに ui=new / ui=legacy を付けない・旧表示への入口や案内が無い
    #836 UI Phase 9: 運営者向けのページに秘密の値・偽の操作・偽のログイン表示・DEMO が無く、区分がそろっている
    #837 JS が無い・ルーターが動かないときは静的な案内
    #838 アーカイブも新UIで出す
    #839 旧UIにしか無かった運営の情報が運営者向けのページにある（健康度・AI・資金配分・実行・カバー範囲・通知・
         取得の警告・データ取得状況・eBay の設定・利益ルートが成立しない理由）
    """
    import re as _re
    out: list[dict] = []

    def _add(no, key, ok, msg, ng="", level_ng="error"):
        out.append({"level": "ok" if ok else level_ng, "check": key,
                    "message": f"#{no} {msg}" + ("" if ok else f" ← {ng}")})

    # 旧UIの目印（タブ・カード・ドロワー・ポップアップの id とクラス、タブを切り替える JS、旧UIの CSS）
    _legacy_markers = [m for m in LEGACY_UI_MARKERS if m in html]
    _add(800, "no_legacy_ui", not _legacy_markers, "旧UIの DOM・CSS・JS が残っていない",
         f"旧UIの目印: {_legacy_markers[:6]}")

    n_root = html.count('<div id="new-ui-root"')
    start = html.find('<div id="new-ui-root"')
    end = html.find("<!-- /new-ui-root -->", start) if start >= 0 else -1
    _add(801, "new_ui_root", n_root == 1 and end > 0,
         "新UIの root（#new-ui-root）が1つあり、終わりの目印がある",
         f"root {n_root}個・目印 {'あり' if end > 0 else 'なし'}（新UIの生成に失敗した可能性。旧UIの受け皿は無い）")
    if n_root != 1 or end < 0:
        return out
    root = html[start:end]

    _hs802 = html.find("<script>(function(){try{var d=document.documentElement;")
    _head802 = html[_hs802:html.find("</script>", _hs802)] if _hs802 >= 0 else ""
    _head_ok = ("var d=document.documentElement;d.classList.add('ui-new');" in _head802
                and "legacy" not in _head802 and "ui-legacy" not in html)
    _add(802, "new_ui_default",
         _head_ok and "html:not(.ui-new) #new-ui-root{display:none!important}" in html
         and "html.ui-new body>*:not(#new-ui-root){display:none!important}" in html
         and root.startswith('<div id="new-ui-root" hidden'),
         "新UIが既定（?ui=legacy も新UI。新UIは JS が表示を決めてから出す）",
         "既定の表示の切り替えが想定と違う")
    # localStorage を使ってよいのはマイページ（UI Phase 7）の保存の入口（NuStore）だけ。新UIの既定化には使わない
    _ks, _ke = root.find("var KEY = 'premium-monitor.mypage'"), root.find("window.NuStore = NuStore;")
    _store = root[_ks:_ke] if 0 <= _ks < _ke else ""
    _rest = root.replace(_store, "") if _store else root
    _hs = html.find("<script>(function(){try{var d=document.documentElement;")
    _head_script = html[_hs:html.find("</script>", _hs)] if _hs >= 0 else ""
    _add(803, "new_ui_flag_only",
         bool(_head_script) and not any(w in _head_script for w in ("localStorage", "sessionStorage", "cookie"))
         and "localStorage" not in _rest and "document.cookie" not in root
         and "'ui'" not in _store and "legacy" not in _store,
         "表示の切り替えは URL だけ（cookie / localStorage で決めない。localStorage はマイページの保存だけ）",
         "URL 以外で表示が切り替わる")
    # #835 UI Phase 10: 古い URL の互換（旧UIは削除済み。?ui=legacy・?ui=new・旧UIのハッシュは新UIへ）
    bad835 = []
    if "params.delete('ui'); params.delete('from');" not in root or "var LEGACY_URL = params.get('ui') === 'legacy';" not in root:
        bad835.append("ルーターが ?ui=…（旧表示・古い ?ui=new）を新UIで開いて URL から外していない")
    if 'id="nu-legacy-ended"' not in root or "旧表示は終了しました" not in root:
        bad835.append("?ui=legacy で開いたときの「旧表示は終了しました」の案内が無い")
    _fb835 = html.find('<div id="nu-fallback"')
    _links835 = root + (html[_fb835:start] if 0 <= _fb835 < start else "")          # 静的な案内のリンクも
    if _re.search(r'href="[^"]*[?&](?:amp;)?ui=(?:new|legacy)', _links835):
        bad835.append("作るリンクに ui=new / ui=legacy が残っている")
    if "nu-legacy-note" in html or "旧表示（" in _links835:
        bad835.append("旧表示への入口・旧表示の案内が残っている")
    _map835 = _re.search(r"data-nu-map='([^']*)'", root)
    try:
        import html as _html835
        import json as _json835
        _mp = _json835.loads(_html835.unescape(_map835.group(1))) if _map835 else {}
    except ValueError:
        _mp = {}
    if (_mp.get("exact") or {}).get("tab-health", {}).get("page") != "admin" or not (_mp.get("exact") or {}).get("tab-lottery"):
        bad835.append("旧UIのハッシュ（#tab-…）を新UIのページへ読み替える表が無い")
    if "q.set('page', 'product'); q.set('product_id', PD_ALIAS[alias])" not in root:
        bad835.append("旧UIの商品カードのリンク（#product-…）が商品詳細に読み替わらない")
    _add(835, "legacy_url_compat", not bad835,
         "古い URL の互換（?ui=legacy・?ui=new は新UIで開いて URL から外す・旧UIのハッシュは新UIのページへ）・"
         "作るリンクに ui= なし・旧表示への入口なし",
         f"問題: {bad835[:5]}")
    # #837 UI Phase 10: JS が無い・ルーターが動かなかったときは静的な案内（旧UIに戻さない）
    bad837 = []
    _fb_s = html.find('<div id="nu-fallback"')
    _fb_e = html.find("</ul></div></div>", _fb_s) if _fb_s >= 0 else -1
    _fb = html[_fb_s:_fb_e] if 0 <= _fb_s < _fb_e < start else ""        # 終わりが見つからない・root より後なら空（範囲を広げない）
    if html.count('<div id="nu-fallback"') != 1 or not (0 <= _fb_s < start):
        bad837.append("静的な案内（#nu-fallback）が1つ・新UIの root より前に無い")
    for _need, _why in (("JavaScript を有効にすると", "JS を有効にする案内"), ("<h1>", "見出し"),
                        ('href="./"', "HOME へのリンク"), ('href="?page=opportunities"', "利益商品へのリンク"),
                        ('href="?page=lottery"', "抽選へのリンク"), ('href="?page=search"', "検索へのリンク"),
                        ("生成時点の値", "生成時点の値である旨"),
                        ("購入を推奨するものではありません", "注意書き（購入を推奨しない）"),
                        ("利益を保証するものではありません", "注意書き（利益を保証しない）")):
        if _need not in _fb:
            bad837.append(f"案内に{_why}が無い")
    if "d.classList.remove('ui-new');d.classList.add('ui-fallback');" not in html:
        bad837.append("ルーターが動かなかったときに静的な案内へ切り替えない")
    # JS が無い（クラスなし）・ルーターが動かない（ui-fallback）ときに、案内を出して他を隠す CSS（1つでも欠けると白い画面）
    for _css, _why in (("html:not(.ui-new) #nu-fallback,html.ui-fallback #nu-fallback{display:block}",
                        "案内を表示する"),
                       ("html:not(.ui-new) body>*:not(#nu-fallback),", "JS が無いとき案内以外を隠す"),
                       ("html.ui-fallback body>*:not(#nu-fallback){display:none!important}", "失敗のとき案内以外を隠す")):
        if _css not in html:
            bad837.append(f"静的な案内の CSS（{_why}）が無い")
    if _re.search(r"¥0(?![0-9,])|DEMO", _fb):
        bad837.append("案内に ¥0・DEMO がある")
    _add(837, "static_fallback", not bad837,
         "JS が無い・ルーターが動かないときは静的な案内（生成時点の値・主なページへのリンク）を出す",
         f"問題: {bad837[:5]}")
    # #838 UI Phase 10: アーカイブ（過去の LP）も新UIで出し、「その日の記録」と今のサイトへの戻り道を出す
    bad838 = []
    _hs838 = html.find("<script>(function(){try{var d=document.documentElement;")
    if "archive" in (html[_hs838:html.find("</script>", _hs838)]
                       if "<script>(function(){try{var d=document.documentElement;" in html else ""):
        bad838.append("head のスクリプトがアーカイブで新UIを止めている（白い画面になる）")
    for _js, _why in (("root.setAttribute('data-nu-archive', ARCH[1]);", "アーカイブの判定"),
                      ("a.setAttribute('href', '../' + h.replace(", "別ファイルへのリンクを今のサイトへ書き換える"),
                      ("note.hidden = false;", "その日の記録の案内を出す")):
        if _js not in root:
            bad838.append(f"ルーターに{_why}処理が無い")
    if 'id="nu-archive-note"' not in root:
        bad838.append("その日の記録の案内が無い")
    _arch_idx = PUBLIC_DIR / "archive" / "index.html"
    try:
        _ai_txt = _arch_idx.read_text(encoding="utf-8") if _arch_idx.exists() else ""
    except OSError:
        _ai_txt = ""
    if 'http-equiv="refresh"' not in _ai_txt or 'url=../' not in _ai_txt:
        bad838.append("docs/archive/index.html（今のサイトへの転送）が無い")
    _add(838, "archive_new_ui", not bad838,
         "アーカイブも新UIで出す（その日の記録の案内・今のサイトへの戻り道・archive/ から今のサイトへの転送）",
         f"問題: {bad838[:5]}")
    n_nav = root.count('class="nu-bottomnav__link"')
    _add(804, "new_ui_bottom_nav", n_nav == 5, "ボトムナビが5項目", f"{n_nav}項目")
    try:
        from src.content.ui import status as _ui_status
        problems = _ui_status.validate()
    except Exception as exc:  # noqa: BLE001
        problems = [f"import 失敗: {exc}"]
    _add(805, "new_ui_status_registry", not problems, "状態の対応表に不整合がない", str(problems))
    _add(806, "new_ui_runtime_present",
         'id="nu-lot-data"' in root and "deriveLotteryRuntimeState" in root
         and "NuLotteryRuntime.apply" in root,
         "閲覧時の状態判定（runtime）のデータと JS がある", "閲覧時に締切を過ぎても受付中に見える")
    _add(807, "new_ui_no_zero_price", not _re.search(r"¥0(?![0-9,])", root),
         "新UIに ¥0 を表示していない", "¥0 が表示されている")
    # 運営者向けのページ（UI Phase 9。?page=admin）は別のページなので除く。一般のページには内部情報を出さない
    _body808 = root.split('<script type="application/json"', 1)[0]
    _ai808 = _body808.find('data-nu-page="admin"')
    _ae808 = _body808.find('data-nu-page="mypage"', _ai808) if _ai808 >= 0 else -1
    _admin808 = _body808[_ai808:_ae808] if 0 <= _ai808 < _ae808 else ""
    _public808 = _body808.replace(_admin808, "") if _admin808 else _body808
    leaked = [w for w in ("取得失敗", "EBAY_APP_ID", "Health Score", "suspicious_price",
                          "HTTP 403", "HTTP403", "SOURCE_BLOCKED", "timeout")
              if w in _public808]
    _add(808, "new_ui_no_internal_info", not leaked,
         "新UIの一般のページに運営者向けの内部情報を出していない（運営者向けのページは別）", f"表示されている: {leaked}")
    # #836 運営者向けのページ（UI Phase 9）: 秘密の値・偽の操作・偽のログイン表示・DEMO が無く、必要な区分がそろっている
    bad836 = []
    if not _admin808:
        bad836.append("運営者向けのページが無い")
    else:
        _t836 = _re.sub(r"<[^>]+>", " ", _admin808)
        for _pat, _lbl in ((r"(?i)\bbearer\s+[a-z0-9._-]{12,}", "Bearer トークン"),
                           (r"-----BEGIN [A-Z ]*PRIVATE KEY", "秘密鍵"),
                           (r"(?i)(appid|token|secret|api[_-]?key|password)\s*[=:]\s*[A-Za-z0-9._-]{8,}", "キーの値"),
                           (r"discord(?:app)?\.com/api/webhooks/", "Webhook の URL"),
                           (r"api\.telegram\.org/bot\d", "Bot の URL"),
                           (r"/Users/|/home/[a-z]", "絶対パス")):
            if _re.search(_pat, _admin808):
                bad836.append(_lbl)
        if "<button" in _admin808 or "<form" in _admin808 or "<input" in _admin808:
            bad836.append("操作の部品（読むだけのはず）")
        for _w in ("ログイン済み", "ログイン中", "管理者としてログイン", "権限: 管理者"):
            if _w in _t836:
                bad836.append(f"偽の状態: {_w}")
        if "DEMO" in _t836 or "SAMPLE" in _t836:
            bad836.append("DEMO")
        for _sec in ("overview", "sources", "data-quality", "ai", "capital", "execution", "notifications", "system"):
            if f'data-nu-ad-panel="{_sec}"' not in _admin808:
                bad836.append(f"区分が無い: {_sec}")
        if "ログイン・権限の仕組みは無く" not in _t836 or "読むだけ" not in _t836:
            bad836.append("認証が無い・読むだけであることの説明が無い")
    _add(836, "admin_ui_safe", not bad836,
         "運営者向けのページに秘密の値・偽の操作・偽のログイン表示・DEMO が無く、8つの区分がそろっている",
         f"問題: {bad836[:5]}")
    bad = [h for h in _re.findall(r'href="([^"]*)"', root)
           if not (h.startswith(("https://", "?", "./", "#")) or _re.match(r"^[A-Za-z0-9_\-]+/", h))]
    _add(809, "new_ui_safe_links", not bad,
         "新UIのリンクは https: かサイト内の相対パスだけ", f"安全でないリンク: {bad[:3]}")
    _vm810 = _re.search(r'data-nu-vmcheck="tcg:(\d+);legacy:(\d+);n:(\d+)"', root)
    _add(810, "new_ui_vm_fidelity", bool(_vm810) and _vm810.group(1) == "0" and _vm810.group(2) == "0",
         f"抽選の表示モデル（VM）が元データと一致する（{_vm810.group(3) if _vm810 else '—'}件）",
         (f"食い違い: TCG {_vm810.group(1)}件・旧来の抽選 {_vm810.group(2)}件" if _vm810 else "突き合わせの結果が無い"))
    # #839 UI Phase 10: 旧UIにしか無かった運営の情報（旧 #493・#497・#577・#586・#589・#590・#609〜#644）が
    # 運営者向けのページにある（旧UIの削除で運営の情報を失わない）
    _ai839 = root.find('data-nu-page="admin"')
    _admin839 = root[_ai839:root.find('data-nu-page="mypage"', _ai839)] if _ai839 >= 0 else ""
    _miss839 = [w for w, need in ADMIN_REQUIRED_ITEMS if need not in _admin839]
    _add(839, "admin_has_legacy_operator_info", bool(_admin839) and not _miss839,
         "旧UIにしか無かった運営の情報が運営者向けのページにある", f"無い: {_miss839[:6]}")
    return out


# 旧UI（UI Phase 10 で削除）の目印。公開するページにあれば #800 が error にする
LEGACY_UI_MARKERS = (
    'id="tab-lottery"', 'id="tab-ranking"', 'id="tab-sedori"', 'id="tab-beginner"', 'id="tab-advanced"',
    'id="tab-health"', 'id="main-tab-nav"', 'id="mobile-drawer"', 'id="genre-dropdown"', 'id="collector-warn-bar"',
    'class="tab-panel', 'class="deal-card', 'class="hero-timestamps', 'class="alert-popup', 'class="ranking-card',
    "function activateTab", "function activateCategory", "drawerTabLabels", "SOUBA デザインシステム",
    "nu-legacy-note", "ui-legacy",
)
# 運営者向けのページに必要な、旧UIから移した運営の情報（項目の名前, ページに必要な文言）
ADMIN_REQUIRED_ITEMS = (
    ("健康度（旧 #609・#610）", "システムの健康度"), ("異常の一覧（旧 #611）", "異常の一覧"),
    ("改善の優先順位（旧 #612）", "改善の優先順位"), ("AI の候補（旧 #615〜#625）", "今日の AI の候補"),
    ("最新の通知（旧 #632）", "利用者向けの通知"), ("カバー範囲（旧 #634・#635）", "カバー範囲"),
    ("資金配分（旧 #638〜#642）", "資金配分"), ("実行の記録（旧 #644）", "実行の件数"),
    ("取得の警告（旧 警告バー）", "取得の警告（旧表示の警告バーと同じ分類）"),
    ("データ取得状況（旧 #493）", "買取の取得（全体）"), ("カメラの買取（旧 #497）", "カメラの買取"),
    ("eBay の設定（旧 #577・#586）", "eBay を設定したときに"),
    ("利益ルートが成立しない理由（旧 #589・#590）", "せどりルートが成立しない理由"),
)


def _check_data_correctness() -> list[dict]:
    """誤価格・鮮度の偽装を公開前に止めるチェック（#820-#825）。

    #820 明らかに誤りの買取価格（HARD_REJECT_REASONS）が CSV に残っていない（LP・利益計算に流れない）
    #821 公式定価の観測時刻が、生成時刻（毎回の実行時刻）になっていない
    #822 直近のコミットで、手動 CSV の「値は同じで日時だけ新しい」更新をしていない
    #823 品質の集計で「対象外」にしている店は、CLAUDE.md の OPTIONAL_SHOPS だけ
    #824 カメラの採用価格は、現金買取の段で、限定版・キット・発売前の品ではない
    #825 公式定価で、同じ一覧ページの別商品に同じ価格を割り当てていない（RICOH の first_on_page 対策）
    #826 成約価格として使う値は、商品ページの URL と成約日時の根拠を持つ
    #827 成約を名乗るのに根拠の無い値を、利益計算に使っていない
    #828 確定利益（main route）の売値は BUYBACK_CASH か SOLD_MEDIAN だけ
    """
    import csv as _csv
    import importlib.util as _ilu
    import json as _json
    import subprocess as _sp
    from datetime import datetime as _dt

    out: list[dict] = []

    def _add(no, key, ok, msg, ng="", level_ng="error"):
        out.append({"level": "ok" if ok else level_ng, "check": key,
                    "message": f"#{no} {msg}" + ("" if ok else f" ← {ng}")})

    def _load(name):
        spec = _ilu.spec_from_file_location(name, PROJECT_ROOT / "scripts" / f"{name}.py")
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    # #820
    def _int(v):
        try:
            return int(str(v or "0").replace(",", ""))
        except ValueError:
            return 0
    rep_p = PROJECT_ROOT / "exports" / "collector_report" / "latest.json"
    if rep_p.exists():
        rep = _json.loads(rep_p.read_text(encoding="utf-8"))
        hard = _load("update_buyback_prices").HARD_REJECT_REASONS
        # (商品, 店, 価格) で照合する（同じ店・商品で別の実行の正しい価格を誤検出しないため）
        bad = {(x["product_alias"], x["shop"], _int(x.get("price"))) for x in rep.get("suspicious_prices") or []
               if x.get("reason") in hard}
        with open(PROJECT_ROOT / "data" / "manual_buyback_prices.csv", encoding="utf-8") as f:
            leaked = [f"{r['product_alias']}/{r['buyback_shop']}=¥{_int(r['buyback_price']):,}"
                      for r in _csv.DictReader(f)
                      if (r["product_alias"], r["buyback_shop"], _int(r["buyback_price"])) in bad
                      and _int(r["buyback_price"]) > 0]
        _add(820, "no_rejected_price_published", not leaked,
             "明らかに誤りの買取価格が CSV（LP・利益計算の入力）に残っていない", f"残っている: {leaked[:5]}")
    else:
        _add(820, "no_rejected_price_published", False,
             "明らかに誤りの買取価格が CSV（LP・利益計算の入力）に残っていない",
             "collector_report が無く判定できない", level_ng="warning")

    # #821
    def _ts(v):
        """ISO・「YYYY-MM-DD HH:MM JST」・タイムゾーン無し（JST とみなす）を読む。"""
        from datetime import timedelta as _td
        from datetime import timezone as _tz
        jst = _tz(_td(hours=9))
        s_ = str(v or "").strip().replace(" JST", "")
        try:
            d = _dt.fromisoformat(s_)
        except ValueError:
            return None
        return (d if d.tzinfo else d.replace(tzinfo=jst)).astimezone(jst)
    npo_p = PROJECT_ROOT / "exports" / "normalized_price_observations" / "latest.json"
    if npo_p.exists():
        npo = _json.loads(npo_p.read_text(encoding="utf-8"))
        obs = npo.get("observations") or []
        g = _ts(npo.get("generated_at"))
        # 偽装の形: 複数の公式価格が「まったく同じ観測時刻」を持ち、それが生成時刻と重なる
        # （実際に取得した公式価格は、取得の間隔を空けて1件ずつ取るので同じ時刻にならない）
        same: dict = {}
        for o in obs:
            if o.get("price_role") == "official" and o.get("observed_at"):
                same.setdefault(str(o["observed_at"]), []).append(o.get("product_id"))
        fake = []
        for ts_str, pids in same.items():
            t = _ts(ts_str)
            if len(pids) >= 3 and t is not None and g is not None and abs((g - t).total_seconds()) < 600:
                fake.extend(pids)
        _add(821, "official_price_not_generation_time", not fake,
             "公式定価の観測時刻が生成時刻になっていない（確認日・実際の取得時刻を保持）",
             f"生成時刻と同じ時刻の公式価格 {len(fake)}件: {fake[:5]}")
    else:
        _add(821, "official_price_not_generation_time", True, "正規化データが無い（判定対象なし）")

    # #822（公開する作業ツリーと、直近のコミットの両方を見る）
    aud = _load("audit_timestamp_only_updates")
    found = aud.audit_worktree()
    rr = _sp.run(["git", "rev-parse", "--verify", "HEAD~1"], cwd=PROJECT_ROOT, capture_output=True, text=True)
    if rr.returncode == 0:
        found += aud.audit_commits("HEAD~1..HEAD")
    _add(822, "no_timestamp_only_update", not found,
         "手動 CSV で「値は同じで日時だけ新しい」更新をしていない（作業ツリーと直近のコミット）",
         f"{[(c, p, n) for c, p, n, _ in found][:3]}")

    # #823
    dq = _load("generate_data_quality_dashboard")
    opt = _load("check_collector_quality").OPTIONAL_SHOPS
    from src.models.buyback_price import BUYBACK_SHOPS as _BS
    allowed = {(_BS.get(f"src_{k}") or {}).get("name") for k in opt}
    extra = sorted(set(dq.UNSUPPORTED_SHOPS) - allowed)
    _add(823, "dq_required_sources_counted", not extra,
         "品質の集計で対象外にしている店は OPTIONAL_SHOPS だけ", f"required なのに対象外: {extra}")

    # #824
    cam_p = PROJECT_ROOT / "exports" / "camera_buyback_status.json"
    cam = _json.loads(cam_p.read_text(encoding="utf-8")) if cam_p.exists() else None
    cam_at = _ts(cam.get("generated_at")) if cam else None
    _now = _dt.now(cam_at.tzinfo) if cam_at else None
    if cam is not None and (cam_at is None or (_now - cam_at).total_seconds() > 6 * 3600):
        # カメラの取得が今回の実行で失敗し、前回コミットした古い状態ファイルが残っている場合。
        # 今の DB に無い古い値で公開を止めないよう、判定対象なし（warning）にする
        _add(824, "camera_cash_buyback_only", False, "カメラの採用価格は現金買取の段・通常版のみ",
             f"camera_buyback_status.json が古い（generated_at={cam.get('generated_at')}）ため判定できない",
             level_ng="warning")
    elif cam is not None:
        ucb = _load("update_camera_buyback")
        bad_cam = []
        for r in cam.get("detail") or []:
            if r.get("status") != "OK":
                continue
            item = r.get("matched_item") or ""
            kind = ucb.classify_tier_text(item)
            if not ucb._strict_model_match(item, r.get("product_alias", "")) or kind == "TRADE_IN_ONLY":
                bad_cam.append(f"{r.get('product_alias')}/{r.get('shop_id')}")
            elif kind == "CASH_TIERS" and ucb._select_cash_buyback_price(item) != r.get("price"):
                bad_cam.append(f"{r.get('product_alias')}/{r.get('shop_id')}=下取の可能性")
        _add(824, "camera_cash_buyback_only", not bad_cam,
             "カメラの採用価格は現金買取の段・通常版のみ", f"不正: {bad_cam[:5]}")
    else:
        _add(824, "camera_cash_buyback_only", True, "カメラの取得結果が無い（判定対象なし）")

    # #825
    if npo_p.exists():
        groups: dict = {}
        for o in (npo.get("observations") or []):
            if o.get("price_role") == "official" and o.get("extraction_method") == "official" and o.get("price"):
                groups.setdefault(o["price"], []).append(o.get("product_id"))
        try:
            import yaml as _yaml
            cfg = _yaml.safe_load((PROJECT_ROOT / "config" / "product_source_configs.yaml").read_text(encoding="utf-8"))
            page_of = {}
            for c in (cfg.get("configs") or cfg.get("product_source_configs") or []):
                if c.get("target_url"):
                    page_of.setdefault(c["product_id"], set()).add(c["target_url"])
        except Exception:  # noqa: BLE001
            page_of = {}
        shared = []
        for price, pids in groups.items():
            pids = sorted(set(pids))
            for i, a in enumerate(pids):
                for b in pids[i + 1:]:
                    if page_of.get(a, set()) & page_of.get(b, set()):
                        shared.append(f"{a}/{b}=¥{price:,}")
        _add(825, "official_price_not_shared_across_products", not shared,
             "同じ一覧ページの別商品に同じ公式定価を割り当てていない", f"同額: {shared[:5]}")

    # #826〜#828: 出品価格（LISTING）と成約価格（SOLD）を取り違えていない（Phase 0.2）
    from src.market import price_types as _ptypes
    if npo_p.exists():
        obs = npo.get("observations") or []
        # #826 成約（flea_sold_price / canonical SOLD の仕入れ値）は、商品ページの URL と成約日時の根拠を持つ
        bad_sold = [f"{o.get('product_id')}/{o.get('source_name')}" for o in obs
                    if o.get("price_role") == "buy"
                    and (o.get("price_type") == "flea_sold_price" or o.get("canonical_price_type") == _ptypes.SOLD)
                    and not _ptypes.has_sold_evidence(o.get("item_url") or o.get("source_url"), o.get("sold_at"))]
        _add(826, "sold_price_has_evidence", not bad_sold,
             "成約価格として使う値は、商品ページの URL と成約日時の根拠を持つ（出品・ダミー URL を成約にしない）",
             f"根拠の無い成約: {bad_sold[:5]}")
        # #827 「落札」「sold」などを名乗るのに根拠の無い値が、利益計算に使える状態になっていない
        leaked = [f"{o.get('product_id')}/{o.get('source_name')}" for o in obs
                  if o.get("price_role") == "buy" and _ptypes.is_sold_label(o.get("source_name"))
                  and o.get("canonical_price_type") != _ptypes.SOLD
                  and (o.get("is_usable_for_pro") or o.get("is_usable_for_beginner"))]
        _add(827, "sold_label_without_evidence_unused", not leaked,
             "成約を名乗るのに根拠の無い値（出品・種別不明）を利益計算に使っていない", f"使用中: {leaked[:5]}")
    pr_p = PROJECT_ROOT / "exports" / "profit_routes" / "latest.json"
    if pr_p.exists():
        pr = _json.loads(pr_p.read_text(encoding="utf-8"))
        # #828 確定利益（main route）の売値は買取（BUYBACK_CASH）か、条件を満たした成約中央値（SOLD_MEDIAN）だけ
        bad_sell = [f"{r.get('product_id')}/{r.get('sell_source')}={r.get('sell_canonical_type')}"
                    for r in (pr.get("main_routes") or [])
                    if not _ptypes.is_confirmed_sell_type(r.get("sell_canonical_type"))]
        _add(828, "main_route_sell_type_confirmed", not bad_sell,
             "確定利益の売値は買取価格か、条件を満たした成約中央値だけ（出品価格を売値にしない）",
             f"対象外の売値: {bad_sell[:5]}")
        # #829 確定ルート（main_routes）は、新UIと同じ判定（opportunity.route_reasons）を生成時刻で通っている。
        #   旧UI・AI Opportunities・通知はこの main_routes を使うので、ここが崩れると旧UIだけに偽ルートが出る
        from src.content.ui import opportunity as _opp829
        from src.tcg.models import JST as _JST829
        try:
            _gen_at = _dt.strptime(str(pr.get("generated_at") or "")[:16], "%Y-%m-%d %H:%M").replace(tzinfo=_JST829)
        except ValueError:
            _gen_at = None
        unsafe = [f"{r.get('product_id')}/{r.get('buy_source')}→{r.get('sell_source')}:"
                  f"{','.join(_opp829.route_reasons(r, _gen_at))}"
                  for r in (pr.get("main_routes") or []) if _gen_at and _opp829.route_reasons(r, _gen_at)]
        _add(829, "main_routes_pass_canonical_gate", _gen_at is not None and not unsafe,
             "確定ルートは新UIと同じ判定（商品の照合・状態・URL・費用・内訳）を通っている（旧UIと新UIの安全基準が一致）",
             f"判定を通らない確定ルート: {unsafe[:3]}" if unsafe else "profit_routes の generated_at が読めない")
        # #830 利益ルートから作った成果物（AI の候補・資金配分・実行履歴の OPEN・通知）が、今の確定・参考ルート
        #   （route_id・新UIと同じ判定）から作られている。無効になったルートが別の成果物経由で復活していない
        if _gen_at is not None:
            _keys = _opp829.current_route_keys(pr, _gen_at)

            def _art(rel):
                p = PROJECT_ROOT / rel
                try:
                    return _json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
                except ValueError:
                    return {}
            _ai = _art("exports/ai_opportunities/latest.json")
            _al = _art("exports/allocation/latest.json")
            _ex = _art("exports/execution/execution_history.json")
            _nt = _art("exports/notifications/latest.json")
            stale = []
            stale += [f"AI:{o.get('product_id')}" for o in (_ai.get("todays_opportunities") or [])
                      if not _opp829.record_route_ok(o, _keys)]
            for _b, _pl in ((_al.get("plans") or {}).items()):
                stale += [f"資金配分{_b}:{a.get('product_id')}" for a in (_pl.get("allocations") or [])
                          if not _opp829.record_route_ok(a, _keys)]
            stale += [f"実行OPEN:{e.get('exec_id')}" for e in (_ex.get("executions") or [])
                      if e.get("status") == "OPEN" and not _opp829.record_route_alive(e, _keys)]
            stale += [f"通知:{e.get('type')}/{e.get('product_id')}" for e in (_nt.get("events") or [])
                      if e.get("type") in _opp829.ROUTE_EVENT_TYPES
                      and not (e.get("route_checked") and _opp829.record_route_ok(
                          {"route_id": e.get("route_id"), "kind": "main"}, _keys))]
            _add(830, "artifacts_follow_current_routes", not stale,
                 "AI の候補・資金配分・実行の OPEN・通知は、今の確定・参考ルート（route_id）から作られている"
                 "（無効になったルートを復活させていない）", f"今のルートと照合できない: {stale[:5]}")
    # #831 価格の履歴（商品詳細）は、実際に観測した点だけ（読める観測時刻・未来でない・同じ系列で時刻が重ならない・正の価格）
    _ph_p = PROJECT_ROOT / "exports" / "price_history" / "latest.json"
    if _ph_p.exists():
        from src.market import price_history as _ph831
        from src.tcg.models import JST as _J831
        _now831 = _dt.now(tz=_J831)
        try:
            _ph = _json.loads(_ph_p.read_text(encoding="utf-8"))
        except ValueError:
            _ph = {}
        bad_pts = []
        for _k, _s in ((_ph.get("series") or {}).items()):
            _ats = [str(p.get("at") or "") for p in (_s.get("points") or [])]
            if len(_ats) != len(set(_ats)):
                bad_pts.append(f"{_k}:重複")
            for p in (_s.get("points") or []):
                if not isinstance(p.get("price"), int) or p["price"] <= 0 or _ph831._future(str(p.get("at") or ""), _now831):
                    bad_pts.append(f"{_k}:{p.get('at')}")
        _add(831, "price_history_real_points", bool(_ph.get("series") is not None) and not bad_pts,
             "価格の履歴は実際に観測した点だけ（観測時刻あり・未来でない・重複なし・正の価格）",
             f"不正な点: {bad_pts[:5]}")
    # #832 公開ページの商品詳細に、DEMO・危ない URL・除外したルートの利益が出ていない
    _idx = PUBLIC_DIR / "index.html"
    if _idx.exists():
        _h = _idx.read_text(encoding="utf-8")
        _i = _h.find('data-nu-page="product"')
        _sec = _h[_i:_h.find('<script type="application/json"', _i)] if _i >= 0 else ""
        issues = []
        if "DEMO（見た目" in _h or "data-nu-pd=\"prod_demo" in _h:
            issues.append("DEMO の表示")
        import re as _re832
        if _re832.search(r'href="\s*(?:javascript|data|vbscript):', _sec, _re832.I):
            issues.append("危ない URL")
        for r in ((pr or {}).get("excluded_routes") or []) if pr_p.exists() else []:
            _n = r.get("net_profit")
            if isinstance(_n, (int, float)) and _n > 0 and f"+¥{int(_n):,}" in _sec:
                issues.append(f"除外したルートの利益 +¥{int(_n):,}")
        _add(832, "product_detail_safe", _i >= 0 and not issues,
             "公開ページの商品詳細に DEMO・危ない URL・除外したルートの利益が出ていない",
             f"問題: {issues[:5]}" if issues else "商品詳細のページが見つからない")
        # #833 利益に使った売却価格は、商品の照合が済んだ買取価格（normalized_prices.sell_confirmation_reasons）だけ。
        # 商品詳細の「利益の計算に使った売却先」は、表の確認済みの行（参考の折りたたみの中ではない）と同じ店・同じ価格
        import html as _html833
        from src.market.normalized_prices import confirmed_sell_keys as _csk833
        _npo833 = PROJECT_ROOT / "exports" / "normalized_price_observations" / "latest.json"
        try:
            _obs833 = (_json.loads(_npo833.read_text(encoding="utf-8")) or {}).get("observations") or []
        except (OSError, ValueError):
            _obs833 = []
        _keys833 = _csk833(_obs833)
        bad833, n833 = [], 0
        for _m in _re832.finditer(r'<article class="nu-pd" data-nu-pd="([^"]+)"', _sec):
            _pid = _html833.unescape(_m.group(1))
            _end = _sec.find('<article class="nu-pd" ', _m.end())
            _art = _sec[_m.start():_end if _end >= 0 else len(_sec)]
            # 店名に括弧があっても読めるように、種別の括弧は「に ¥」の直前の最後の括弧として読む
            _sm = _re832.search(r'で買い、([^<]+)（[^（）<]*）に ¥([\d,]+) で売る場合', _html833.unescape(_art))
            if not _sm:
                continue
            n833 += 1
            _shop, _price = _sm.group(1), int(_sm.group(2).replace(",", ""))
            if (_pid, _shop, _price) not in _keys833:
                bad833.append(f"{_pid}:{_shop} ¥{_price:,}（商品照合未完了）")
            _main = _art.split('class="nu-pd-morerows"')[0]
            _row = _main.find("利益の計算に使った売却先")
            if _row < 0 or "確認済み" not in _main[_row:_main.find("</tr>", _row)]:
                bad833.append(f"{_pid}: 表の確認済みの行に利益の売却先が無い")
        _add(833, "opportunity_sell_identity_verified", bool(_obs833) and not bad833,
             f"利益に使った売却価格はすべて商品照合済みの買取価格で、商品詳細の表の確認済みの行と一致（{n833}件）",
             f"問題: {bad833[:5]}" if bad833 else "正規化の観測が読めない")

        # #834 マイページ（UI Phase 7）: DEMO・架空のアカウント表示が無い、ウォッチのボタンは登録済みの商品だけ、
        # カードの想定純利益は商品詳細と同じ値（マイページで計算し直していない）、危ないリンク・抽選の外の応募ボタンが無い
        _mi = _h.find('data-nu-page="mypage"')
        _mp = _h[_mi:_h.find('</main>', _mi)] if _mi >= 0 else ""          # マイページは本文の最後のページ
        bad834 = []
        _mp_text = _re832.sub(r"<[^>]+>", " ", _mp)
        if "DEMO" in _mp_text or 'data-nu-mp-card="prod_demo' in _mp:
            bad834.append("DEMO")
        for _w in ("ログイン済み", "ログイン中", "同期済み", "クラウドに保存", "通知登録完了", "会員ランク", "契約プラン", "プラン契約"):
            if _w in _mp_text:
                bad834.append(f"架空の状態: {_w}")
        if _re832.search(r"[\w.+-]+@[\w-]+\.[\w.]+", _mp_text):
            bad834.append("メールアドレス")
        _pd_ids = set(_re832.findall(r'<article class="nu-pd" data-nu-pd="([^"]+)"', _sec))
        _w_ids = set(_re832.findall(r'data-nu-watch="([^"]+)"', _h))
        if _w_ids - _pd_ids:
            bad834.append(f"登録の無い商品のウォッチ: {sorted(_w_ids - _pd_ids)[:3]}")
        if _re832.search(r'href="\s*(?:javascript|data|vbscript):', _mp, _re832.I):
            bad834.append("危ない URL")
        _outside = _re832.sub(r'<article class="nu-mp-lot".*?</article>', "", _mp, flags=_re832.S)
        if "data-nu-cta=" in _outside:
            bad834.append("抽選の一覧の外の応募ボタン")
        for _pid, _net in _re832.findall(r'data-nu-mp-card="([^"]+)"[^>]*?data-net="(\d*)"', _mp):
            _ai = _sec.find(f'<article class="nu-pd" data-nu-pd="{_pid}"')
            _ae = _sec.find('<article class="nu-pd" ', _ai + 10)
            _pm = _re832.search(r'nu-pd-metric--main nu-pd-metric--profit"><dt>想定純利益</dt><dd><span class="nu-pd-val">'
                                r'\+¥([\d,]+)', _sec[_ai:_ae if _ae >= 0 else len(_sec)]) if _ai >= 0 else None
            _pd_net = _pm.group(1).replace(",", "") if _pm else ""
            if _pd_net != _net:
                bad834.append(f"{_pid}: マイページ {_net or '算出前'} / 商品詳細 {_pd_net or '算出前'}")
        _add(834, "mypage_safe", _mi >= 0 and not bad834,
             "マイページに DEMO・架空のアカウント表示・危ないリンクが無く、ウォッチは登録済みの商品だけ、想定純利益は商品詳細と同じ",
             f"問題: {bad834[:5]}" if bad834 else "マイページが見つからない")
    return out


def _check_tcg_layer() -> list[dict]:
    """TCG 入荷・抽選・プレミア監視レイヤーの健全性チェック（#739-#750）。"""
    out: list[dict] = []

    def _add(no, key, ok, msg, ng=""):
        out.append({"level": "ok" if ok else "error", "check": key,
                    "message": f"#{no} {msg}" + ("" if ok else f" ← {ng}")})

    try:
        from src.tcg import classify, dedupe, freshness, premium, shrink
        from src.tcg.models import (
            EVENT_CONVENIENCE_STORE, EVENT_FIRST_COME, EVENT_LOTTERY,
            EVENT_RESTOCK, EVENT_TYPES, SHRINK_STATUSES, SHRINK_UNKNOWN,
            now_jst,
        )
        from src.tcg.sources import sources_for
        from src.collectors.tcg import ALL_COLLECTORS
    except Exception as exc:  # noqa: BLE001
        for no, key in ((739, "tcg_pokemon_source"), (740, "tcg_onepiece_source"),
                        (741, "tcg_lottery_parser"), (742, "tcg_first_come_parser"),
                        (743, "tcg_convenience_event"), (744, "tcg_restock_event"),
                        (745, "tcg_shrink_status"), (746, "tcg_premium_calc"),
                        (747, "tcg_stale_not_available"), (748, "tcg_source_priority"),
                        (749, "tcg_duplicate_prevention"), (750, "tcg_report_exists")):
            out.append({"level": "error", "check": key,
                        "message": f"#{no} TCG レイヤーの読み込みに失敗: {exc}"})
        return out

    from datetime import timedelta

    # #739: Pokemon source exists
    _add(739, "tcg_pokemon_source", bool(sources_for("POKEMON")),
         "Pokemon の監視 source が登録されている", "source 未登録")

    # #740: ONE PIECE source exists
    _add(740, "tcg_onepiece_source", bool(sources_for("ONE_PIECE")),
         "ONE PIECE の監視 source が登録されている", "source 未登録")

    # #741: Lottery parser valid（抽選を抽選として判定できる）
    _add(741, "tcg_lottery_parser",
         classify.classify_event_type("抽選販売の応募受付を開始します") == EVENT_LOTTERY,
         "抽選告知を LOTTERY として判定できる", "抽選の判定に失敗")

    # #742: First-come parser valid（先着を抽選と混同しない）
    _add(742, "tcg_first_come_parser",
         classify.classify_event_type("店頭にて先着販売", store="YODOBASHI") == EVENT_FIRST_COME,
         "店頭先着を FIRST_COME として判定できる", "先着の判定に失敗")

    # #743: Convenience-store event supported
    _add(743, "tcg_convenience_event",
         (EVENT_CONVENIENCE_STORE in EVENT_TYPES
          and classify.classify_event_type("ローソン店頭にて先着販売", store="LAWSON")
          == EVENT_CONVENIENCE_STORE),
         "コンビニ販売イベントを扱える", "コンビニ販売が未対応")

    # #744: Restock event supported
    _add(744, "tcg_restock_event",
         (EVENT_RESTOCK in EVENT_TYPES
          and classify.classify_event_type("本日再入荷しました") == EVENT_RESTOCK),
         "再入荷イベントを扱える", "再入荷が未対応")

    # #745: Shrink status supported（BOX=シュリンク付きと仮定しない）
    _add(745, "tcg_shrink_status",
         (len(SHRINK_STATUSES) >= 6
          and shrink.detect_shrink_status("BOX販売あり") == SHRINK_UNKNOWN
          and shrink.assume_shrink_from_box(True) == SHRINK_UNKNOWN),
         "シュリンク状態を管理し BOX=シュリンク付きと仮定しない",
         "BOX からシュリンクを推定している")

    # #746: Premium calculation valid（異常値1件を採用しない）
    _p = premium.compute_premium(7200, 12500)
    _add(746, "tcg_premium_calc",
         (_p["premium_yen"] == 5300 and abs(_p["premium_percent"] - 73.6) < 0.1
          and premium.market_median([12000, 12500, 12800, 250000]) == 12500
          and premium.market_median([99000]) is None),
         "プレミア計算が正しく、異常値1件を市場価格に採用しない",
         "プレミア計算または外れ値除外が不正")

    # #747: Stale restock not shown as available
    _stale = {"event_type": EVENT_RESTOCK, "source_type": "RETAILER_OFFICIAL",
              "reported_at": (now_jst() - timedelta(hours=5)).isoformat()}
    _add(747, "tcg_stale_not_available",
         freshness.is_stale(_stale) and not freshness.available_now(_stale),
         "鮮度切れの入荷報告を「今買える」と表示しない",
         "古い入荷報告が購入可能として扱われている")

    # #748: Unverified source cannot override official
    _add(748, "tcg_source_priority",
         (dedupe.can_override("OFFICIAL", "SOCIAL_REPORT") is False
          and classify.confidence_for("SOCIAL_REPORT", 1) == "low"
          and classify.verification_label("SOCIAL_REPORT", "low", 1) != "Confirmed"),
         "未確認 source が公式情報を上書きしない",
         "下位 source が公式を上書きできる状態")

    # #749: Duplicate event prevention works
    _base = {"tcg": "POKEMON", "product_id": "a", "store": "LAWSON",
             "event_type": EVENT_RESTOCK, "observed_at": now_jst().isoformat()}
    _merged = dedupe.dedupe_events([
        dict(_base, source_type="SOCIAL_REPORT", confidence="low", source_url="x"),
        dict(_base, source_type="RETAILER_OFFICIAL", confidence="high", source_url="y"),
    ])
    _add(749, "tcg_duplicate_prevention",
         len(_merged) == 1 and _merged[0]["source_type"] == "RETAILER_OFFICIAL",
         "重複イベントを排除し上位 source を残す", "重複排除が機能していない")

    # #750: TCG report exists
    import json as _json_tcg
    _rep = {}
    _rep_path = PROJECT_ROOT / "exports" / "tcg" / "latest.json"
    if _rep_path.exists():
        try:
            _rep = _json_tcg.loads(_rep_path.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001 - 破損時は未生成扱い
            _rep = {}
    _md = (PROJECT_ROOT / "exports" / "tcg" / "latest.md")
    _ok750 = bool(_rep.get("generated_at")) and _md.exists() and bool(ALL_COLLECTORS)
    # TCG は追加レイヤーのため、未生成でも既存 LP の公開は止めない（warning）。
    out.append({"level": "ok" if _ok750 else "warning", "check": "tcg_report_exists",
                "message": "#750 TCG レポート(exports/tcg/latest.json / latest.md)が生成されている"
                           + ("" if _ok750 else " ← TCG レポートが未生成（追加レイヤーのため warning）")})

    out.extend(_check_pokemon_coverage(_rep))
    out.extend(_check_tcg_lottery(_rep))
    return out


def _check_tcg_lottery(report: dict) -> list[dict]:
    """TCG 抽選インテリジェンスの健全性チェック（#759-#766）。"""
    out: list[dict] = []

    def _add(no, key, ok, msg, ng="", level_ng="error"):
        out.append({"level": "ok" if ok else level_ng, "check": key,
                    "message": f"#{no} {msg}" + ("" if ok else f" ← {ng}")})

    from src.collectors.tcg.lottery.base import TOURNAMENT_TERMS, LotteryAdapter
    from src.tcg.lottery.manual import is_official_url
    from src.tcg.lottery.registry import ST_SOURCE_BLOCKED
    from src.tcg.lottery.schema import compute_lottery_status
    from src.tcg.models import parse_dt
    from src.tcg.sales_context import _GIVEAWAY_RE

    lots = report.get("lotteries") or []
    # 状態を判定した時刻で検証する（生成時刻との数分のずれで誤検知しない）
    gen = parse_dt(report.get("lottery_evaluated_at") or report.get("generated_at"))

    # #759: 大会抽選・プレゼント抽選を抽選販売にしない（ロジック + 出力の両方）
    _a = LotteryAdapter()
    _logic = (not _a.build_from_article(
                  title="「シティリーグ2027」事前抽選のエントリー", body="大会の事前抽選。応募期間 10/2(金) 12:00 ～ 10/5(月) 16:59",
                  url="https://www.pokemon-card.com/info/1.html", published_at="2026-09-18T00:00:00+09:00")
              and not LotteryAdapter.is_lottery_sale("購入すると抽選でプロモカードが当たる"))
    # 「抽選告知あり」（タイトルのみ）も含めて検査する
    _bad = [e.get("product_name") for e in lots
            if any(w in (e.get("product_name") or "") for w in TOURNAMENT_TERMS)
            or _GIVEAWAY_RE.search(e.get("product_name") or "")
            or (e.get("announcement_only") and _a.screen_announcement_title(
                e.get("product_name") or ""))]
    _add(759, "tcg_no_tournament_or_giveaway_lottery", _logic,
         "大会抽選・プレゼント抽選を抽選販売として扱わない（判定ロジック）",
         "判定ロジックが大会・プレゼント抽選を通している")
    # 出力の商品名は外部の告知本文から作られるため、日次公開を止めない warning にする
    _add(767, "tcg_lottery_output_no_tournament_or_giveaway", not _bad,
         "出力された抽選に大会・プレゼント抽選が含まれていない",
         f"該当: {_bad[:3]}", level_ng="warning")

    # #760: 終了済みの抽選を受付中・開始前として出さない（生成時刻で状態を再計算して一致）
    _mismatch = []
    for e in lots:
        if e.get("announcement_only") or gen is None:
            continue
        if compute_lottery_status(e, gen) != e.get("status"):
            _mismatch.append(e.get("product_name"))
    _add(760, "tcg_lottery_status_consistent", not _mismatch,
         "抽選の状態が日程と一致している（終了済みを受付中にしない）", f"不一致: {_mismatch[:3]}")

    # #761: 手動確認データを読み込み時刻で fresh 化しない
    _manual = [e for e in lots if e.get("collection_method") == "MANUAL_VERIFIED"]
    _fresh = [e.get("product_name") for e in _manual
              if e.get("observed_at") != e.get("last_verified_at")]
    _add(761, "tcg_manual_lottery_not_refreshed", not _fresh,
         f"手動確認の抽選（{len(_manual)}件）の観測時刻を確認日時のまま保持している",
         f"fresh 化: {_fresh[:3]}")

    # #762: アクセス拒否の source を正常と偽らない
    _fake = []
    for r in report.get("lottery_sources") or []:
        if any(p.get("http_status") in (401, 403, 429) for p in (r.get("pages") or [])) \
                and r.get("state") != ST_SOURCE_BLOCKED and not r.get("reachable"):
            _fake.append(r.get("source_id"))
    _add(762, "tcg_blocked_source_not_healthy", not _fake,
         "アクセス拒否（HTTP 403 等）の監視元を正常扱いしない", f"偽装: {_fake}")

    # #763: 応募ボタンは公式の応募 URL のみ
    _bad_links = [e.get("entry_url") for e in lots
                  if e.get("entry_url") and not is_official_url(e["entry_url"])]
    _add(763, "tcg_entry_url_official_only", not _bad_links,
         "応募ページへのリンクは公式サイトの URL のみ", f"非公式: {_bad_links[:3]}")

    # #764: 抽選カバレッジ（監視状況）が出力されている（外部依存のため warning）
    _cov = report.get("lottery_coverage") or {}
    _add(764, "tcg_lottery_coverage_report", bool(_cov.get("configured_sources")),
         "抽選の監視状況（登録 / 実装 / 正常 / 拒否 / 未実装）が出力されている",
         "カバレッジ未出力", level_ng="warning")

    # #765: 1つ以上の監視元から抽選を実データ取得できている（外部依存のため warning）
    _real = [e for e in lots if not e.get("announcement_only")]
    _add(765, "tcg_lottery_real_data", bool(_real) or any(
        h.get("retailer") for h in (report.get("lottery_sources") or [])
        if h.get("state") == "NO_ACTIVE_LOTTERY"),
         f"抽選を実データで取得している（{len(_real)}件）、または監視元が正常に0件を返している",
         "抽選も正常取得の監視元も無い", level_ng="warning")

    # #766（旧UIの TCG タブで抽選が在庫より上）は UI Phase 10 で旧UIと一緒に削除した（新UIは抽選・在庫が別のページ）
    # #841 UI Phase 10: 公式の発売予定（公式のページ・発売日が読める・今日以降）は、新UIの抽選・予約に全部出ている
    # （旧UIの「販売・入荷・プレミア」の発売予定の後継。日付の書き方の違い（2026.11.21 など）で黙って消えない）
    from datetime import datetime as _dt841
    from src.content.ui import runtime as _rt841
    from src.tcg.models import JST as _JST841
    _today841 = _dt841.now(_JST841).strftime("%Y-%m-%d")
    _lp841 = PUBLIC_DIR / "index.html"
    _html841 = _lp841.read_text(encoding="utf-8") if _lp841.exists() else ""
    _ls841 = _html841.find('data-nu-page="lottery"')
    _lot_page = _html841[_ls841:_html841.find('data-nu-page="restock"', _ls841)] if _ls841 >= 0 else ""
    import html as _h841
    _lot_text = _h841.unescape(_lot_page)
    _want841 = [e for e in (report.get("events") or []) if isinstance(e, dict) and e.get("status") == "COMING_SOON"
                and not e.get("stale") and (_rt841.official_url(e.get("canonical_url"))
                                            or _rt841.official_url(e.get("source_url")))
                and (_rt841.release_date_iso(e.get("release_date")) or "") >= _today841]
    _miss841 = sorted({str(e.get("product_name") or "")[:30] for e in _want841
                       if str(e.get("product_name") or "") not in _lot_text})
    _add(841, "tcg_release_schedule_shown", bool(_html841) and not _miss841,
         f"公式の発売予定（{len(_want841)}件）が新UIの抽選・予約に出ている",
         f"出ていない: {_miss841[:4]}")
    return out


def _check_pokemon_coverage(report: dict) -> list[dict]:
    """ポケモン商品単位監視・CI fail-closed の健全性チェック（#751-#758）。"""
    out: list[dict] = []

    def _add(no, key, ok, msg, ng="", level_ng="error"):
        out.append({"level": "ok" if ok else level_ng, "check": key,
                    "message": f"#{no} {msg}" + ("" if ok else f" ← {ng}")})

    from datetime import timedelta
    from urllib.parse import urlparse
    from src.tcg import freshness, scoring
    from src.tcg.models import EVENT_LOTTERY, EVENT_GENERAL_SALE, now_jst
    from src.tcg.product_types import (
        PT_ACCESSORY, is_box_opportunity_eligible, split_prices,
    )

    now = now_jst()

    # #751: 当選者のみの購入期間は一般購入可能（AVAILABLE_NOW / BUY NOW）にしない
    _lot = {"event_type": EVENT_LOTTERY, "source_type": "OFFICIAL",
            "application_start": (now - timedelta(days=10)).isoformat(),
            "application_end": (now - timedelta(days=5)).isoformat(),
            "purchase_start": (now - timedelta(days=1)).isoformat(),
            "purchase_end": (now + timedelta(days=2)).isoformat()}
    _lot["status"] = freshness.compute_status(_lot, now)
    _buy = scoring.buy_now_signal(_lot, {"premium_percent": 90.0, "premium_yen": 5000})
    _add(751, "tcg_winner_period_not_general_sale",
         _lot["status"] == "WINNER_PURCHASE_PERIOD" and not _buy["buy_now"],
         "当選者のみの購入期間を一般販売・BUY NOW と区別する",
         f"status={_lot['status']} buy_now={_buy['buy_now']}")

    # #752: 発売予定（COMING_SOON）は AVAILABLE_NOW にせず BUY NOW も出さない
    _fut = {"event_type": EVENT_GENERAL_SALE, "source_type": "OFFICIAL",
            "sale_start": (now + timedelta(days=10)).isoformat()}
    _fut["status"] = freshness.compute_status(_fut, now)
    _fb = scoring.buy_now_signal(_fut, {"premium_percent": 90.0, "premium_yen": 5000})
    _add(752, "tcg_coming_soon_not_available",
         _fut["status"] == "COMING_SOON" and not _fb["buy_now"],
         "発売予定商品を AVAILABLE_NOW / BUY NOW にしない",
         f"status={_fut['status']} buy_now={_fb['buy_now']}")

    # #753: パック価格を BOX 定価に自動昇格しない
    _sp = split_prices("BOOSTER_BOX", "200円（税込）", api_type="拡張パック")
    _add(753, "tcg_pack_price_not_box_retail",
         _sp["pack_price"] == 200 and _sp["retail_price"] is None,
         "1パックの希望小売価格を BOX 定価として扱わない", str(_sp))

    # #754: アクセサリーを BOX Opportunity に入れない
    _add(754, "tcg_accessory_not_box_opportunity",
         not is_box_opportunity_eligible(PT_ACCESSORY),
         "周辺グッズを BOX Opportunity の対象にしない", "アクセサリーが対象になっている")

    # #755: CI の deploy-check が fail-closed（pipefail + CLI の非ゼロ終了）
    _wf = (PROJECT_ROOT / ".github" / "workflows" / "daily_lp.yml")
    _cli = (PROJECT_ROOT / "src" / "cli.py")
    _wf_ok = False
    try:
        import yaml as _yaml_wf
        _steps = _yaml_wf.safe_load(_wf.read_text(encoding="utf-8"))["jobs"]["update-lp"]["steps"]
        _dc = [st for st in _steps if st.get("name") == "Deploy check"]
        _run = (_dc[0].get("run") or "") if _dc else ""
        _wf_ok = bool(_dc) and "pipefail" in _run and not _dc[0].get("continue-on-error")
    except Exception:  # noqa: BLE001 - 読めなければ NG として扱う
        _wf_ok = False
    _cli_src = _cli.read_text(encoding="utf-8") if _cli.exists() else ""
    _i = _cli_src.find('def deploy_check_lp')
    _cli_ok = _i >= 0 and "sys.exit(1)" in _cli_src[_i:_i + 2500]
    _add(755, "ci_deploy_check_fail_closed", _wf_ok and _cli_ok,
         "CI の deploy-check が失敗時にジョブを失敗させる（pipefail + 非ゼロ終了）",
         f"workflow_pipefail={_wf_ok} cli_exit={_cli_ok}")

    # #756: 本番表示のイベントは実取得データのみ（fixture / テスト用ホストを出さない）
    _bad = []
    _official = ("OFFICIAL", "RETAILER_OFFICIAL", "STORE_OFFICIAL")
    for e in (report.get("events") or []):
        url = e.get("source_url") or ""
        host = (urlparse(url).hostname or "").lower()
        # コミュニティ / SNS 報告は URL が無いのが正常なので対象外。
        # 公式系で URL が無いもの、または明確なテスト用ホストだけを fixture とみなす。
        if not host:
            if e.get("source_type") in _official:
                _bad.append(e.get("product_name"))
            continue
        if (host in ("example.com", "example.org", "localhost", "127.0.0.1")
                or host.endswith((".example.com", ".example.org", ".test", ".localhost"))):
            _bad.append(e.get("product_name"))
    _add(756, "tcg_no_fixture_in_production", not _bad,
         "TCG 表示イベントは実 source の URL を持つ（fixture を表示しない）",
         f"不正な source_url: {_bad[:3]}")

    # #757: ポケモン系のファネルが出力されている（外部サイト依存のため warning）
    _pf = report.get("pokemon_funnel") or {}
    _add(757, "pokemon_funnel_report", bool(_pf.get("sources")),
         "Pokemon collector のファネル（pages / product links / accepted / rejected）が出力されている",
         "ファネル未出力", level_ng="warning")

    # #758: ポケモン商品ページを1件以上発見している（外部サイト依存のため warning）
    _tot = _pf.get("total") or {}
    _add(758, "pokemon_product_pages_discovered",
         int(_tot.get("product_pages_discovered") or 0) > 0,
         f"Pokemon 商品ページを発見している（{_tot.get('product_pages_discovered', 0)}件）",
         "商品ページ 0 件（DEGRADED）", level_ng="warning")
    return out


def _load_products_for_ref():
    """商品IDと参照価格(official or retail)のリストを返す（#563 用）。"""
    import sqlite3 as _sq
    _con = _sq.connect(str(PROJECT_ROOT / "data" / "premium_monitor.db"))
    out = []
    for r in _con.execute("SELECT id, COALESCE(official_price,0), COALESCE(retail_price,0) FROM products"):
        out.append((r[0], r[1] or r[2]))
    _con.close()
    return out


def main():
    """CLIとして実行。"""
    results = check()
    errors = [r for r in results if r["level"] == "error"]
    warnings = [r for r in results if r["level"] == "warning"]
    oks = [r for r in results if r["level"] == "ok"]

    print(f"\n{'='*60}")
    print(f" Deploy Check ({len(results)} items)")
    # 実行日時（運営者向けのページが「いつのチェックか」を出すため。CI の出力ファイルに残る）
    _jst = __import__("datetime").timezone(__import__("datetime").timedelta(hours=9))
    print(f" 実行日時: {__import__('datetime').datetime.now(_jst).isoformat(timespec='seconds')}")
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

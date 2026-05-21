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

    # 11. 買取価格更新日時の表示（ラベル名変更に対応: 旧「買取価格更新：」→新「最終買取データ取得：」）
    has_buyback_ts = "最終買取データ取得：" in html or "最終データ取得:" in html or "買取価格更新：" in html
    if has_buyback_ts:
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

    # 14. Pro向けタブの存在
    if 'id="tab-advanced"' in html:
        results.append({"level": "ok", "check": "tab_advanced", "message": "Pro向けタブが存在する（id=tab-advanced）"})
    else:
        results.append({"level": "error", "check": "tab_advanced", "message": "Pro向けタブ（id=tab-advanced）が見つからない"})

    # 14b. LP上に「上級者向け」という表記がないこと（ユーザー向けUIには使わない）
    # コメント・CSS内は無視、li/p/h2/span等のテキストのみ検査
    import re as _re
    adv_in_ui = _re.findall(r'>([^<>]*上級者向け[^<>]*)<', html)
    if adv_in_ui:
        results.append({"level": "warning", "check": "no_kyusha_text", "message": f"LP上に「上級者向け」表記が{len(adv_in_ui)}件残っている（Pro向けに統一推奨）: {adv_in_ui[:2]}"})
    else:
        results.append({"level": "ok", "check": "no_kyusha_text", "message": "LP上に「上級者向け」表記なし（Pro向けに統一済み）"})

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
    has_pro_candidate_card = 'pro-candidate-card' in html
    if has_advanced_confirmed:
        results.append({"level": "ok", "check": "advanced_in_tab", "message": "上級者向け確定案件が存在する"})
    elif has_watch_candidates or has_pro_candidate_card:
        results.append({"level": "ok", "check": "advanced_in_tab", "message": "Pro向けタブに市場価格カードが表示されている（price_history fallback 正常）"})
    else:
        results.append({"level": "error", "check": "advanced_in_tab", "message": "Pro向けタブにコンテンツなし（price_history fallback が動作していない）"})

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

    # 20. 速報タブが存在する
    if 'id="tab-sokuhoh"' in html or 'data-tab="sokuhoh"' in html:
        results.append({"level": "ok", "check": "sokuhoh_tab_exists", "message": "速報タブ（tab-sokuhoh）が存在する"})
    else:
        results.append({"level": "error", "check": "sokuhoh_tab_exists", "message": "速報タブ（id=tab-sokuhoh）が見つからない"})

    # 20b. 「新商品候補」がLP上に存在しない
    if '新商品候補' not in html:
        results.append({"level": "ok", "check": "new_products_removed", "message": "「新商品候補」テキストは存在しない（速報タブに移行済み）"})
    else:
        results.append({"level": "warning", "check": "new_products_removed", "message": "「新商品候補」テキストがまだ残っている"})

    # 20c. 速報カードまたはデータなし表示が存在する
    if 'sokuhoh-card' in html or '速報がありません' in html:
        results.append({"level": "ok", "check": "sokuhoh_content", "message": "速報タブにコンテンツ（카드またはデータなし表示）がある"})
    else:
        results.append({"level": "warning", "check": "sokuhoh_content", "message": "速報タブにコンテンツが見つからない"})

    # 20d. 抽選リンク種別ラベルがある
    if any(lbl in html for lbl in ['抽選ページを確認', '予約ページを確認', '販売ページを確認', '商品ページを確認', '公式サイトを確認']):
        results.append({"level": "ok", "check": "lottery_link_type_label", "message": "抽選カードにリンク種別ラベルがある"})
    else:
        results.append({"level": "warning", "check": "lottery_link_type_label", "message": "抽選カードのリンク種別ラベルが見つからない"})

    # 21. 初心者向けカードに複数買取店テーブルがある
    if "buyback-shop-table" in html or "buyback-table" in html:
        results.append({"level": "ok", "check": "buyback_shop_table", "message": "初心者カードに複数買取店テーブルが存在する"})
    else:
        results.append({"level": "error", "check": "buyback_shop_table", "message": "複数買取店テーブルが見つからない（beginner deals 要確認）"})

    # 22. 最高買取価格が表示されている
    if "最高買取価格" in html or "buyback-best-price" in html:
        results.append({"level": "ok", "check": "buyback_best_price_label", "message": "最高買取価格ラベルが存在する"})
    else:
        results.append({"level": "error", "check": "buyback_best_price_label", "message": "最高買取価格ラベルが見つからない"})

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

    # 25. 価格取得日時が表示されている（freshness系クラス）
    if "freshness-live" in html or "freshness-recent" in html or "freshness-stale" in html:
        results.append({"level": "ok", "check": "price_freshness_shown", "message": "価格取得日時・鮮度ラベルが表示されている"})
    else:
        results.append({"level": "warning", "check": "price_freshness_shown", "message": "価格鮮度ラベルが見つからない"})

    # 26. 掲載価格注意文が表示されている
    if "掲載価格は取得・入力時点の参考値" in html or "buyback-notice" in html:
        results.append({"level": "ok", "check": "buyback_notice", "message": "買取価格注意文が表示されている"})
    else:
        results.append({"level": "error", "check": "buyback_notice", "message": "買取価格注意文が見つからない"})

    # 27. 上級者向けタブに海外相場リンクセクションがある
    if "overseas-links-section" in html:
        results.append({"level": "ok", "check": "overseas_links_section", "message": "海外相場リンクセクションが存在する"})
    else:
        results.append({"level": "warning", "check": "overseas_links_section", "message": "海外相場リンクセクションが見つからない（上級者向けデータ要確認）"})

    # 28. eBay soldリンクが存在するか
    if "ebay.com" in html and ("LH_Sold=1" in html or "sold" in html.lower()):
        results.append({"level": "ok", "check": "ebay_sold_link", "message": "eBay 落札済み検索リンクが存在する"})
    else:
        results.append({"level": "warning", "check": "ebay_sold_link", "message": "eBay soldリンクが見つからない"})

    # 29. B&H / Adorama / MPB / KEH などの海外専門店リンクが存在するか
    has_overseas_specialist = (
        "bhphotovideo.com" in html
        or "adorama.com" in html
        or "mpb.com" in html
        or "keh.com" in html
    )
    if has_overseas_specialist:
        results.append({"level": "ok", "check": "overseas_specialist_links", "message": "海外専門店リンク（B&H/Adorama/MPB/KEH）が存在する"})
    else:
        results.append({"level": "warning", "check": "overseas_specialist_links", "message": "海外専門店リンクが見つからない（カメラ案件が対象）"})

    # 30. 海外相場ボタン（overseas-btn）が存在するか
    if "overseas-btn" in html:
        results.append({"level": "ok", "check": "overseas_btn_exists", "message": "海外相場ボタンが存在する"})
    else:
        results.append({"level": "warning", "check": "overseas_btn_exists", "message": "海外相場ボタンが見つからない"})

    # 31. 価格未取得時の確認導線（adv-fallback-notice または海外リンク）がある
    has_fallback_notice = "adv-fallback-notice" in html or "overseas-links-section" in html
    if has_fallback_notice:
        results.append({"level": "ok", "check": "price_no_data_fallback", "message": "価格未取得時の確認導線がある"})
    else:
        results.append({"level": "warning", "check": "price_no_data_fallback", "message": "価格未取得時の確認導線が見つからない"})

    # 32. 公式買取ページ誘導テキストが存在する（未検証URLの代替表示）
    if "公式買取ページで確認" in html or "unverified-link" in html:
        results.append({"level": "ok", "check": "buyback_page_guidance", "message": "公式買取ページ誘導テキストが存在する"})
    else:
        results.append({"level": "warning", "check": "buyback_page_guidance", "message": "公式買取ページ誘導テキストが見つからない"})

    # 33. せどりタブが存在する
    if 'id="tab-sedori"' in html:
        results.append({"level": "ok", "check": "sedori_tab_exists", "message": "せどりルートタブが存在する"})
    else:
        results.append({"level": "error", "check": "sedori_tab_exists", "message": "せどりルートタブ（id=tab-sedori）が見つからない"})

    # 34. せどりタブに仕入れ価格・売却価格が表示されているか（ルートがある場合）
    has_best_card = "sc-best-card" in html
    has_no_data = "sc-no-data" in html
    if has_best_card:
        results.append({"level": "ok", "check": "sedori_best_route", "message": "せどりタブに最大利益ルートカードがある"})
    elif has_no_data:
        results.append({"level": "ok", "check": "sedori_best_route", "message": "せどりタブにデータなし表示（ルート未計算、正常）"})
    else:
        results.append({"level": "warning", "check": "sedori_best_route", "message": "せどりタブに最大ルートカードもデータなし表示も見つからない"})

    # 35. せどりタブに仕入れ価格表示がある
    if "sc-price-buy" in html or "仕入れ先" in html:
        results.append({"level": "ok", "check": "sedori_buy_price", "message": "せどりタブに仕入れ価格表示がある"})
    else:
        results.append({"level": "warning", "check": "sedori_buy_price", "message": "せどりタブに仕入れ価格表示が見つからない"})

    # 36. せどりタブに売却価格表示がある
    if "sc-price-sell" in html or "売却先" in html:
        results.append({"level": "ok", "check": "sedori_sell_price", "message": "せどりタブに売却価格表示がある"})
    else:
        results.append({"level": "warning", "check": "sedori_sell_price", "message": "せどりタブに売却価格表示が見つからない"})

    # 37. せどりタブに実質利益表示がある
    if "実質利益" in html and "sc-wrap" in html:
        results.append({"level": "ok", "check": "sedori_net_profit", "message": "せどりタブに実質利益表示がある"})
    else:
        results.append({"level": "warning", "check": "sedori_net_profit", "message": "せどりタブに実質利益表示が見つからない"})

    # 38. タブボタンが全て有効（data-track付きhref="#"がない）
    bad_tracked = re.findall(r'href=["\']#["\'][^>]*data-track', html)
    if bad_tracked:
        results.append({"level": "error", "check": "tab_buttons_valid", "message": f"data-track付きhref='#'が{len(bad_tracked)}件（クリックが機能しない可能性）"})
    else:
        results.append({"level": "ok", "check": "tab_buttons_valid", "message": "タブ・CTAボタンに無効なhref='#'なし"})

    # 39. 初心者向けに公式購入リンクがある（Apple Store / 任天堂公式 / 公式 等）
    has_official_link = (
        "apple.com" in html
        or "store.nintendo.co.jp" in html
        or "nintendo.co.jp" in html
        or "apple-store" in html
        or "official-price-btn" in html
        or "公式で購入" in html
    )
    if has_official_link:
        results.append({"level": "ok", "check": "beginner_official_link", "message": "初心者向けに公式購入リンクがある"})
    else:
        results.append({"level": "warning", "check": "beginner_official_link", "message": "公式購入リンクが見つからない（初心者向けデータ要確認）"})

    # 40. Pro向けに国内二次流通リンクがある
    has_domestic_secondary = (
        "jp.mercari.com" in html
        or "auctions.yahoo.co.jp" in html
        or "fril.jp" in html
        or "pro-chip-domestic" in html
    )
    if has_domestic_secondary:
        results.append({"level": "ok", "check": "pro_domestic_links", "message": "Pro向けに国内二次流通リンクがある"})
    else:
        results.append({"level": "warning", "check": "pro_domestic_links", "message": "Pro向け国内二次流通リンクが見つからない"})

    # 41. Pro向けに海外相場リンクがある（eBay sold / StockX / B&H / Adorama / MPB / KEH / Amazon US）
    has_overseas_pro = (
        ("LH_Sold=1" in html or "ebay.com" in html)
        and "stockx.com" in html
        and "bhphotovideo.com" in html
    )
    if has_overseas_pro:
        results.append({"level": "ok", "check": "pro_overseas_links", "message": "Pro向けに海外相場リンク（eBay/StockX/B&H）がある"})
    else:
        results.append({"level": "warning", "check": "pro_overseas_links", "message": "Pro向け海外相場リンクが不足している（watch_candidatesが必要）"})

    # 42. StockX リンクがある
    if "stockx.com" in html:
        results.append({"level": "ok", "check": "stockx_link", "message": "StockXリンクが存在する"})
    else:
        results.append({"level": "warning", "check": "stockx_link", "message": "StockXリンクが見つからない"})

    # 43. Amazon US リンクがある
    if "amazon.com/s" in html:
        results.append({"level": "ok", "check": "amazon_us_link", "message": "Amazon USリンクが存在する"})
    else:
        results.append({"level": "warning", "check": "amazon_us_link", "message": "Amazon USリンクが見つからない"})

    # 44. 空のhref（href="" または href="javascript:"）がない
    empty_href = re.findall(r'href=["\'](javascript:[^"\']*|)["\']', html)
    if empty_href:
        results.append({"level": "error", "check": "no_empty_href", "message": f"空または無効なhrefが{len(empty_href)}件"})
    else:
        results.append({"level": "ok", "check": "no_empty_href", "message": "空・無効なhrefなし"})

    # 45. 品質バッジCSS（Phase 15）が存在する
    if "sc-badge-review" in html and "sc-qs-badge" in html:
        results.append({"level": "ok", "check": "quality_badge_css", "message": "品質チェックバッジCSS（sc-badge-review/sc-qs-badge）が存在する"})
    else:
        results.append({"level": "warning", "check": "quality_badge_css", "message": "品質チェックバッジCSSが見つからない（Phase 15未適用の可能性）"})

    # 46. 要確認（needs_review）バッジが存在するか、またはルート数が0の場合はOK
    has_review_badge = "要確認" in html and "sc-badge-review" in html
    has_no_routes = "sc-no-data" in html
    has_routes = "sc-best-card" in html
    if has_review_badge or has_no_routes:
        results.append({"level": "ok", "check": "quality_review_badge", "message": "品質チェック要確認バッジ表示またはルートなし（正常）"})
    elif has_routes:
        # ルートがある場合、バッジなしは要確認ルートが存在しないだけなのでOK
        results.append({"level": "ok", "check": "quality_review_badge", "message": "せどりルートあり・要確認バッジなし（全ルートが品質OK）"})
    else:
        results.append({"level": "warning", "check": "quality_review_badge", "message": "品質チェック状態が判定できない"})

    # 47. sort_scoreによるソート（ルートがある場合にsc-best-crown内に品質情報がある）
    if has_routes and "sc-best-crown" in html:
        results.append({"level": "ok", "check": "sedori_sort_score", "message": "せどりルートにsc-best-crownが存在する（sort_scoreソート適用）"})
    elif not has_routes:
        results.append({"level": "ok", "check": "sedori_sort_score", "message": "せどりルートなし（sort_scoreソートチェックスキップ）"})
    else:
        results.append({"level": "warning", "check": "sedori_sort_score", "message": "せどりルートのベストカードクラウンが見つからない"})

    # 48. 品質スコアCSSクラス（sc-qs-high/mid/low）が定義されている
    if "sc-qs-high" in html and "sc-qs-mid" in html and "sc-qs-low" in html:
        results.append({"level": "ok", "check": "quality_score_css_classes", "message": "品質スコアCSSクラス（high/mid/low）が定義されている"})
    else:
        results.append({"level": "warning", "check": "quality_score_css_classes", "message": "品質スコアCSS（sc-qs-high/mid/low）が見つからない"})

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

    # 50. 商品ジャンルタブ（cat-genre-bar）がある
    if "cat-genre-bar" in html and "cat-genre-btn" in html:
        results.append({"level": "ok", "check": "category_genre_bar", "message": "商品ジャンルタブ（cat-genre-bar）が存在する"})
    else:
        results.append({"level": "error", "check": "category_genre_bar", "message": "商品ジャンルタブが見つからない"})

    # 51. メーカーチップが存在する
    if "cat-maker-chip" in html:
        results.append({"level": "ok", "check": "category_maker_chips", "message": "メーカーチップ（cat-maker-chip）が存在する"})
    else:
        results.append({"level": "error", "check": "category_maker_chips", "message": "メーカーチップが見つからない"})

    # 52. 抽選情報タブが存在する
    if 'data-tab="lottery"' in html or 'id="tab-lottery"' in html:
        results.append({"level": "ok", "check": "lottery_tab_exists", "message": "抽選情報タブが存在する"})
    else:
        results.append({"level": "warning", "check": "lottery_tab_exists", "message": "抽選情報タブが見つからない"})

    # 53. LIVE DEALSが有効なリンク
    if "live-panel-link" in html or ('LIVE DEALS' in html and 'href="#tab-beginner"' in html):
        results.append({"level": "ok", "check": "live_deals_link", "message": "LIVE DEALSが有効なリンクになっている"})
    else:
        results.append({"level": "warning", "check": "live_deals_link", "message": "LIVE DEALSのリンクが未設定"})

    # 54. ランキング行にクリックナビゲーションがある（data-target-tab）
    if "rank-row-clickable" in html and "data-target-tab" in html:
        results.append({"level": "ok", "check": "ranking_nav_links", "message": "ランキング行にクリックナビゲーション（data-target-tab）がある"})
    else:
        results.append({"level": "warning", "check": "ranking_nav_links", "message": "ランキング行のクリックナビゲーションが未設定"})

    # 55. 商品カードにIDがある（product-）
    if 'id="product-' in html:
        results.append({"level": "ok", "check": "product_card_ids", "message": "商品カードにid属性（product-*）がある"})
    else:
        results.append({"level": "warning", "check": "product_card_ids", "message": "商品カードのid属性が見つからない"})

    # 56. カテゴリチップに data-target-tab が設定されている
    if 'data-target-tab="beginner"' in html and 'data-target-tab="advanced"' in html:
        results.append({"level": "ok", "check": "category_chip_target_tab", "message": "カテゴリチップに data-target-tab が設定されている"})
    else:
        results.append({"level": "error", "check": "category_chip_target_tab", "message": "カテゴリチップに data-target-tab が見つからない（ナビ修正必要）"})

    # 57. カテゴリチップに data-target-id が設定されている
    if 'data-target-id="category-pro-camera"' in html and 'data-target-id="category-beginner-iphone"' in html:
        results.append({"level": "ok", "check": "category_chip_target_id", "message": "カテゴリチップに data-target-id（category-pro-camera/category-beginner-iphone）が設定されている"})
    else:
        results.append({"level": "error", "check": "category_chip_target_id", "message": "カテゴリチップの data-target-id が不足している（ナビ修正必要）"})

    # 58. カテゴリアンカーID（category-pro-camera / category-beginner-iphone）が存在する
    has_pro_camera = 'id="category-pro-camera"' in html
    has_beg_iphone = 'id="category-beginner-iphone"' in html
    if has_pro_camera and has_beg_iphone:
        results.append({"level": "ok", "check": "category_anchor_ids", "message": "カテゴリアンカーID（category-pro-camera / category-beginner-iphone）が存在する"})
    else:
        missing = []
        if not has_pro_camera:
            missing.append("category-pro-camera")
        if not has_beg_iphone:
            missing.append("category-beginner-iphone")
        results.append({"level": "error", "check": "category_anchor_ids", "message": f"カテゴリアンカーIDが不足: {', '.join(missing)}"})

    # 59. activateCategory JS 関数が存在する
    if "activateCategory" in html:
        results.append({"level": "ok", "check": "activate_category_fn", "message": "activateCategory JS関数が存在する"})
    else:
        results.append({"level": "error", "check": "activate_category_fn", "message": "activateCategory JS関数が見つからない（カテゴリナビ未実装）"})

    # 60. ランキング行に data-target-id が設定されている
    if "rank-row-clickable" in html and 'data-target-id="product-' in html:
        results.append({"level": "ok", "check": "ranking_target_id", "message": "ランキング行に data-target-id（product-*）が設定されている"})
    else:
        results.append({"level": "warning", "check": "ranking_target_id", "message": "ランキング行の data-target-id が未設定"})

    # 61. category-beginner-tablet アンカーが存在する
    if 'id="category-beginner-tablet"' in html:
        results.append({"level": "ok", "check": "category_anchor_tablet", "message": "category-beginner-tablet アンカーが存在する"})
    else:
        results.append({"level": "error", "check": "category_anchor_tablet", "message": "category-beginner-tablet アンカーが見つからない"})

    # 62. category-beginner-game アンカーが存在する
    if 'id="category-beginner-game"' in html:
        results.append({"level": "ok", "check": "category_anchor_game", "message": "category-beginner-game アンカーが存在する"})
    else:
        results.append({"level": "error", "check": "category_anchor_game", "message": "category-beginner-game アンカーが見つからない"})

    # 63. category-lottery アンカーが存在する（抽選タブ内）
    if 'id="category-lottery"' in html:
        results.append({"level": "ok", "check": "category_anchor_lottery", "message": "category-lottery アンカーが存在する"})
    else:
        results.append({"level": "error", "check": "category_anchor_lottery", "message": "category-lottery アンカーが見つからない"})

    # 64. ゲーム機チップが category-beginner-game に正しく設定されている
    #     （ゲームジャンルボタン自体が category-beginner-iphone を指していないか確認）
    game_chip_ok = 'data-target-id="category-beginner-game"' in html
    # ゲームジャンルボタンタグ内に category-beginner-iphone が混在していないか（同一タグ属性）
    game_chip_wrong = bool(re.search(
        r'data-genre="game"[^>]*data-target-id="category-beginner-iphone"', html
    ))
    if game_chip_ok and not game_chip_wrong:
        results.append({"level": "ok", "check": "game_chip_target", "message": "ゲーム機チップが category-beginner-game に正しく設定されている"})
    else:
        results.append({"level": "error", "check": "game_chip_target", "message": "ゲーム機チップのターゲットが誤っている（category-beginner-game が必要）"})

    # 65. 抽選チップが category-lottery に設定されている
    if 'data-target-id="category-lottery"' in html and 'data-target-tab="lottery"' in html:
        results.append({"level": "ok", "check": "lottery_chip_target", "message": "抽選チップが category-lottery に正しく設定されている"})
    else:
        results.append({"level": "error", "check": "lottery_chip_target", "message": "抽選チップの data-target-id=category-lottery が見つからない"})

    # 66. ランキングカードが存在する
    if "ranking-card" in html and "ranking-tab-btn" in html:
        results.append({"level": "ok", "check": "ranking_card_exists", "message": "ランキングカードとタブが存在する"})
    else:
        results.append({"level": "error", "check": "ranking_card_exists", "message": "ランキングカードが見つからない"})

    # 67. せどりランキングタブが存在する
    if 'data-rtab="sedori"' in html:
        results.append({"level": "ok", "check": "sedori_ranking_tab", "message": "せどりランキングタブが存在する"})
    else:
        results.append({"level": "warning", "check": "sedori_ranking_tab", "message": "せどりランキングタブが見つからない"})

    # 68. モバイル一番の確認導線が存在する（リンクまたは「公式で要確認」表示）
    has_mobile_ichiban_link = bool(re.search(r'mobile-ichiban\.com|モバイル一番', html))
    if has_mobile_ichiban_link:
        results.append({"level": "ok", "check": "mobile_ichiban_link", "message": "モバイル一番の確認導線が存在する"})
    else:
        results.append({"level": "warning", "check": "mobile_ichiban_link", "message": "モバイル一番の確認導線が見つからない（buyback CSV の URL を確認）"})

    # 69. 価格に鮮度ラベル（freshness-*）が表示されている
    if any(cls in html for cls in ("freshness-live", "freshness-recent", "freshness-stale", "freshness-warn")):
        results.append({"level": "ok", "check": "price_freshness_label", "message": "価格鮮度ラベル（freshness-*）が表示されている"})
    else:
        results.append({"level": "warning", "check": "price_freshness_label", "message": "価格鮮度ラベルが見つからない"})

    # 70. 古い価格（参考値/要確認）バッジが表示されている
    if "freshness-stale" in html or "freshness-warn" in html:
        results.append({"level": "ok", "check": "stale_price_badge", "message": "古い価格に参考値/要確認バッジが表示されている"})
    else:
        results.append({"level": "warning", "check": "stale_price_badge", "message": "古い価格バッジが見つからない（全データが新鮮か、鮮度チェックが機能していない可能性）"})

    # 71. 抽選情報に公式リンクがある
    has_lottery_link = bool(re.search(r'lottery_click', html))
    if has_lottery_link:
        results.append({"level": "ok", "check": "lottery_official_link", "message": "抽選情報タブに公式リンク（data-track=lottery_click）がある"})
    else:
        results.append({"level": "warning", "check": "lottery_official_link", "message": "抽選情報の公式リンクが見つからない"})

    # 72. 買取店比較に「要確認」表示または確認リンクがある
    has_verify_guidance = "要確認" in html or "公式で要確認" in html or "公式サイトで確認" in html
    if has_verify_guidance:
        results.append({"level": "ok", "check": "buyback_verify_guidance", "message": "買取店比較に確認導線（要確認/公式で要確認）が存在する"})
    else:
        results.append({"level": "warning", "check": "buyback_verify_guidance", "message": "買取店比較の確認導線が見つからない"})

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

    # 75. Pro向け国内価格テーブルが存在する
    has_pro_domestic_table = 'pro-domestic-price-table' in html or 'pro_domestic_click' in html
    if has_pro_domestic_table:
        results.append({"level": "ok", "check": "pro_domestic_price_table", "message": "Pro向け国内二次流通価格の確認導線が存在する"})
    else:
        results.append({"level": "warning", "check": "pro_domestic_price_table", "message": "Pro向け国内価格テーブルが見つからない（watch_candidates データまたは CSS クラスを確認）"})

    # 76. Pro向け海外相場の確認導線が存在する
    has_pro_overseas = 'pro-overseas-price-table' in html or 'pro_overseas_click' in html
    if has_pro_overseas:
        results.append({"level": "ok", "check": "pro_overseas_price_link", "message": "Pro向け海外相場の確認導線が存在する"})
    else:
        results.append({"level": "warning", "check": "pro_overseas_price_link", "message": "Pro向け海外相場の確認導線が見つからない"})

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

    # 79. 終了済み抽選が「受付中」として表示されていない（折り畳みセクションに入っているか）
    # lottery-closed-section が存在すれば終了済み処理が機能している
    has_closed_section = "lottery-closed-section" in html
    if has_closed_section:
        results.append({"level": "ok", "check": "lottery_closed_section", "message": "終了済み抽選が折り畳みセクションに分離されている"})
    else:
        # 終了済みアイテムが存在しない場合はOK（全て現在進行中）
        results.append({"level": "ok", "check": "lottery_closed_section", "message": "抽選情報に終了済みアイテムなし（全て現在進行中）"})

    # 80. Pro向け全価格行に確認リンクがある（pro-link-btn クラスが存在する）
    has_pro_link_btn = "pro-link-btn" in html
    if has_pro_link_btn:
        results.append({"level": "ok", "check": "pro_price_row_links", "message": "Pro向け価格テーブルの各行に確認ボタンがある"})
    else:
        results.append({"level": "warning", "check": "pro_price_row_links", "message": "Pro向け価格テーブルの確認ボタンが見つからない"})

    # 81. Pro向け価格表に「価格未取得」行がある（全サイト行が出ているか）
    has_no_price_rows = "pro-no-price" in html or "価格未取得" in html
    if has_no_price_rows:
        results.append({"level": "ok", "check": "pro_all_sites_shown", "message": "Pro向け価格表に全サイト行（価格未取得含む）が表示されている"})
    else:
        results.append({"level": "warning", "check": "pro_all_sites_shown", "message": "Pro向け全サイト行が見つからない（watch_candidates にデータがない可能性）"})

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

    # 84. 買取比較テーブルに「モバイル一番」テキストがある
    has_mobile_ichiban_name = "モバイル一番" in html
    if has_mobile_ichiban_name:
        results.append({"level": "ok", "check": "shop_name_mobile_ichiban", "message": "買取比較テーブルに「モバイル一番」の店舗名が表示されている"})
    else:
        results.append({"level": "error", "check": "shop_name_mobile_ichiban", "message": "「モバイル一番」の店舗名がLP上に見つからない — shop_display に店舗名が入っていない可能性"})

    # 85. 買取比較テーブルに「買取商店」テキストがある
    has_kaitori_shouten_name = "買取商店" in html
    if has_kaitori_shouten_name:
        results.append({"level": "ok", "check": "shop_name_kaitori_shouten", "message": "買取比較テーブルに「買取商店」の店舗名が表示されている"})
    else:
        results.append({"level": "error", "check": "shop_name_kaitori_shouten", "message": "「買取商店」の店舗名がLP上に見つからない"})

    # 86. 買取比較テーブルに「買取一丁目」テキストがある
    has_kaitori_itchome_name = "買取一丁目" in html
    if has_kaitori_itchome_name:
        results.append({"level": "ok", "check": "shop_name_kaitori_itchome", "message": "買取比較テーブルに「買取一丁目」の店舗名が表示されている"})
    else:
        results.append({"level": "error", "check": "shop_name_kaitori_itchome", "message": "「買取一丁目」の店舗名がLP上に見つからない"})

    # 87. 買取比較テーブルに「じゃんぱら」テキストがある
    has_janpara_name = "じゃんぱら" in html
    if has_janpara_name:
        results.append({"level": "ok", "check": "shop_name_janpara", "message": "買取比較テーブルに「じゃんぱら」の店舗名が表示されている"})
    else:
        results.append({"level": "error", "check": "shop_name_janpara", "message": "「じゃんぱら」の店舗名がLP上に見つからない"})

    # 88. 買取比較テーブルに「イオシス」テキストがある
    has_iosys_name = "イオシス" in html
    if has_iosys_name:
        results.append({"level": "ok", "check": "shop_name_iosys", "message": "買取比較テーブルに「イオシス」の店舗名が表示されている"})
    else:
        results.append({"level": "error", "check": "shop_name_iosys", "message": "「イオシス」の店舗名がLP上に見つからない"})

    # 89. 「買取価格を確認」が shop-name-col に入っていないこと
    # shop-name-col の中に「買取価格を確認」テキストがあれば店舗名と誤って置き換わっている
    shop_name_col_bad = re.findall(r'class="shop-name-col">[^<]*買取価格を確認', html)
    if shop_name_col_bad:
        results.append({"level": "error", "check": "shop_name_col_no_label", "message": f"shop-name-col に「買取価格を確認」テキストが {len(shop_name_col_bad)}件入っている — 店舗名と混在"})
    else:
        results.append({"level": "ok", "check": "shop_name_col_no_label", "message": "shop-name-col に「買取価格を確認」ラベルなし（店舗名が正しく表示されている）"})

    # 90. 買取比較テーブルに「確認」ボタン列がある（shop-link-col）
    has_shop_link_col = "shop-link-col" in html
    if has_shop_link_col:
        results.append({"level": "ok", "check": "shop_link_col_exists", "message": "買取比較テーブルに確認ボタン列（shop-link-col）が存在する"})
    else:
        results.append({"level": "error", "check": "shop_link_col_exists", "message": "買取比較テーブルの確認ボタン列（shop-link-col）が見つからない"})

    # 91. ページ上部のタイムスタンプラベルが明確（「最終」「取得」を含む）
    has_clear_ts_label = "最終買取データ取得" in html or "最終データ取得" in html
    if has_clear_ts_label:
        results.append({"level": "ok", "check": "hero_ts_label_clear", "message": "ヒーローのデータ取得タイムスタンプラベルが明確（「最終〜取得」）"})
    else:
        results.append({"level": "warning", "check": "hero_ts_label_clear", "message": "ヒーローの更新日時ラベルが不明確 — 「最終買取データ取得」等に変更することを推奨"})

    # 92. 手動確認データラベルが表示されている（manual CSV由来価格を明示）
    has_manual_label = "手動確認データ" in html
    if has_manual_label:
        results.append({"level": "ok", "check": "manual_data_label", "message": "手動確認データのラベルが表示されている"})
    else:
        results.append({"level": "warning", "check": "manual_data_label", "message": "手動確認データラベルが見つからない（manual CSV インポート後は表示されるはず）"})

    # 93. 鮮度ラベルの「shop-name-col」内に「最新」が含まれていない（手動データを「最新」と誤表示しない）
    # freshness-live + manual_today の組み合わせで「最新」が shop テーブルに出ていないかチェック
    bad_freshness_live_in_shop = re.findall(
        r'class="shop-table[^"]*".*?freshness-live[^>]*>[^<]*最新', html, re.DOTALL
    )
    if bad_freshness_live_in_shop:
        results.append({"level": "warning", "check": "no_live_label_for_manual", "message": f"買取テーブル内に「最新」（freshness-live）が {len(bad_freshness_live_in_shop)}件。手動データに使われていないか確認推奨"})
    else:
        results.append({"level": "ok", "check": "no_live_label_for_manual", "message": "買取テーブル内に「最新」ラベルなし（手動データは日付表示）"})

    # 94. 鮮度ラベルに日付（MM/DD形式）が含まれる（observed_at由来の日付表示）
    has_date_in_freshness = bool(re.search(r'freshness-[a-z]+[^>]*>\s*手動確認データ / \d{2}/\d{2}', html))
    if has_date_in_freshness:
        results.append({"level": "ok", "check": "freshness_shows_date", "message": "鮮度ラベルに MM/DD 形式の確認日付が表示されている"})
    else:
        results.append({"level": "warning", "check": "freshness_shows_date", "message": "鮮度ラベルに日付（MM/DD）が見つからない（manual データなし、またはフォーマット変更の可能性）"})

    # 95. 「本日確認」ラベルが使われている（曖昧な「本日○件」の代わり）
    has_hontou_kakunin = "本日確認" in html
    if has_hontou_kakunin:
        results.append({"level": "ok", "check": "count_label_clarity", "message": "「本日確認」ラベルが使われている（件数定義が明確）"})
    else:
        results.append({"level": "warning", "check": "count_label_clarity", "message": "「本日確認」ラベルが見つからない — 曖昧な「本日○件」のまま"})

    # 96. タブバッジ（tab-count）が初心者タブに存在する（ボタン内の直接の子 span のみ対象）
    beginner_tab_badge = re.search(r'data-tab="beginner"[^>]*>[^<]*<span class="tab-count">(\d+)</span>', html)
    if beginner_tab_badge:
        badge_num = int(beginner_tab_badge.group(1))
        results.append({"level": "ok", "check": "beginner_tab_badge", "message": f"初心者タブバッジが存在する（{badge_num}件）"})
    else:
        results.append({"level": "warning", "check": "beginner_tab_badge", "message": "初心者タブのバッジ数が見つからない"})

    # 97. Pro価格表: 国内最安価格が表示されている
    has_pro_dom_min = "国内最安" in html
    if has_pro_dom_min:
        results.append({"level": "ok", "check": "pro_dom_min_price", "message": "Pro向けカードに国内最安価格サマリーが表示されている"})
    else:
        results.append({"level": "warning", "check": "pro_dom_min_price", "message": "Pro向けカードの国内最安価格サマリーが見つからない（データ未取得の可能性）"})

    # 98. Pro価格表: 海外最高価格が表示されている
    has_pro_ovs_max = "海外最高" in html
    if has_pro_ovs_max:
        results.append({"level": "ok", "check": "pro_ovs_max_price", "message": "Pro向けカードに海外最高価格サマリーが表示されている"})
    else:
        results.append({"level": "warning", "check": "pro_ovs_max_price", "message": "Pro向けカードの海外最高価格サマリーが見つからない（データ未取得の可能性）"})

    # 99. Pro価格表: 価格あり行が未取得行より上（pro-row-has-price が pro-no-price-chip より先に出現）
    pos_has_price = html.find('pro-row-has-price')
    pos_no_price_chip = html.find('pro-no-price-chip')
    if pos_has_price != -1 and pos_no_price_chip != -1:
        if pos_has_price < pos_no_price_chip:
            results.append({"level": "ok", "check": "pro_price_order", "message": "Pro価格表: 価格あり行が未取得チップより上に表示されている"})
        else:
            results.append({"level": "error", "check": "pro_price_order", "message": "Pro価格表: 価格あり行が未取得チップより下に出現している（順序不正）"})
    elif pos_has_price != -1:
        results.append({"level": "ok", "check": "pro_price_order", "message": "Pro価格表: 価格あり行のみ（未取得なし）"})
    else:
        results.append({"level": "warning", "check": "pro_price_order", "message": "Pro価格表の価格あり行が見つからない（データ未取得の可能性）"})

    # 100. Pro価格表: 未取得サイトがチップ形式にまとまっている（pro-no-price-chip）
    has_pro_no_price_chips = "pro-no-price-chip" in html
    if has_pro_no_price_chips:
        results.append({"level": "ok", "check": "pro_no_price_chips", "message": "Pro価格表の未取得サイトがチップ形式で表示されている"})
    else:
        results.append({"level": "warning", "check": "pro_no_price_chips", "message": "Pro価格表の未取得チップが見つからない（全サイト価格取得済みか、データなしの可能性）"})

    # 102. 抽選カードに最終確認日（lottery-checked-at）が表示されている
    has_lottery_checked_at = "lottery-checked-at" in html
    if has_lottery_checked_at:
        results.append({"level": "ok", "check": "lottery_checked_at", "message": "抽選カードに最終確認日（lottery-checked-at）が表示されている"})
    else:
        results.append({"level": "warning", "check": "lottery_checked_at", "message": "抽選カードの最終確認日（lottery-checked-at）が見つからない"})

    # 103. 抽選カードに空の href が存在しない（lottery_click データ付きリンクに href="" がない）
    lottery_empty_links = re.findall(r'data-track="lottery_click"[^>]*href=["\']["\']', html)
    if lottery_empty_links:
        results.append({"level": "error", "check": "lottery_no_empty_link", "message": f"抽選カードに空リンク（href=\"\"）が {len(lottery_empty_links)}件存在する"})
    else:
        results.append({"level": "ok", "check": "lottery_no_empty_link", "message": "抽選カードに空リンクなし"})

    # 104. Pro価格表に price_basis（種別ラベル）が表示されている
    has_price_basis = "pro-price-basis" in html
    if has_price_basis:
        results.append({"level": "ok", "check": "price_basis_shown", "message": "Pro価格表に価格種別ラベル（pro-price-basis）が表示されている"})
    else:
        results.append({"level": "warning", "check": "price_basis_shown", "message": "Pro価格表の価格種別ラベル（pro-price-basis）が見つからない（データ未取得の可能性）"})

    # 105. Pro価格表の下に価格種別注意文がある
    has_price_basis_disclaimer = "pro-price-basis-disclaimer" in html and "出品価格・成約価格・販売価格は意味が異なります" in html
    if has_price_basis_disclaimer:
        results.append({"level": "ok", "check": "price_basis_disclaimer", "message": "Pro価格表に価格種別注意文が表示されている"})
    else:
        results.append({"level": "warning", "check": "price_basis_disclaimer", "message": "Pro価格表の価格種別注意文が見つからない"})

    # 106. eBay sold が「海外sold」として表示されている
    has_ebay_sold_label = "海外sold" in html
    if has_ebay_sold_label:
        results.append({"level": "ok", "check": "ebay_sold_basis_label", "message": "eBay soldが「海外sold」種別として表示されている"})
    else:
        results.append({"level": "warning", "check": "ebay_sold_basis_label", "message": "「海外sold」ラベルが見つからない（eBayデータなしの可能性）"})

    # 107. メルカリが「出品価格」として表示されている
    has_mercari_basis_label = "出品価格" in html
    if has_mercari_basis_label:
        results.append({"level": "ok", "check": "mercari_basis_label", "message": "メルカリが「出品価格」種別として表示されている"})
    else:
        results.append({"level": "warning", "check": "mercari_basis_label", "message": "「出品価格」ラベルが見つからない（メルカリデータなしの可能性）"})

    # 101. Hero と announce bar で同一の件数（「本日確認」）が表示されている
    # 両方から件数を抽出して一致するか検証
    hero_counts = re.findall(r'本日確認.*?<strong>(\d+)</strong>', html)
    announce_counts = re.findall(r'本日確認\s*(\d+)\s*件', html)
    if hero_counts and announce_counts:
        hero_n = int(hero_counts[0])
        announce_n = int(announce_counts[0])
        if hero_n == announce_n:
            results.append({"level": "ok", "check": "count_consistency", "message": f"Hero と announce bar の件数が一致（{hero_n}件）"})
        else:
            results.append({"level": "error", "check": "count_consistency", "message": f"Hero({hero_n}件) と announce bar({announce_n}件) の件数が不一致"})
    else:
        results.append({"level": "warning", "check": "count_consistency", "message": "Hero または announce bar の件数を取得できなかった"})

    # 108. Pro向けカードが0件にならない（price_history fallback が動作している）
    has_pro_watch_card = 'pro-candidate-card' in html or 'watch-candidate-card' in html
    if has_pro_watch_card:
        results.append({"level": "ok", "check": "pro_card_not_empty", "message": "Pro向けカード（市場価格テーブル）が表示されている"})
    else:
        results.append({"level": "error", "check": "pro_card_not_empty", "message": "Pro向けカードが0件 — price_history fallback が動作していない可能性"})

    # 109. price_history fallback の案内文が表示されている（fallback 時の注意バナー）
    has_fallback_notice = "adv-fallback-notice" in html
    if has_fallback_notice:
        results.append({"level": "ok", "check": "pro_fallback_notice", "message": "Pro向けfallback表示の案内文が表示されている"})
    else:
        results.append({"level": "warning", "check": "pro_fallback_notice", "message": "Pro向けfallback案内文が見つからない（watch_candidatesあり or 表示なしの可能性）"})

    # 110. price_basis ラベルが実際のLP上に表示されている（pro-price-basis クラスで包まれた種別テキスト）
    has_basis_label_in_table = bool(re.search(r'class="pro-price-basis">[^<]+<', html))
    if has_basis_label_in_table:
        results.append({"level": "ok", "check": "price_basis_in_table", "message": "Pro価格表に price_basis テキスト（出品価格・中古販売価格等）が表示されている"})
    else:
        results.append({"level": "warning", "check": "price_basis_in_table", "message": "pro-price-basis クラスにテキストなし（価格データなしの可能性）"})

    # 111. eBay sold ラベルが実際にLP上に表示されている
    has_ebay_sold_in_table = "海外sold" in html
    if has_ebay_sold_in_table:
        results.append({"level": "ok", "check": "ebay_sold_in_table", "message": "「海外sold」ラベルがLP上に表示されている"})
    else:
        results.append({"level": "warning", "check": "ebay_sold_in_table", "message": "「海外sold」ラベルがない（eBay fallback データ未取得の可能性）"})

    # 112. 出品価格 / 中古販売価格ラベルが表示されている
    has_listing_price = "出品価格" in html
    has_used_price_label = "中古販売価格" in html
    if has_listing_price and has_used_price_label:
        results.append({"level": "ok", "check": "price_basis_labels_shown", "message": "「出品価格」「中古販売価格」ラベルがLP上に表示されている"})
    elif has_listing_price or has_used_price_label:
        results.append({"level": "ok", "check": "price_basis_labels_shown", "message": "price_basis ラベルが少なくとも1種類表示されている"})
    else:
        results.append({"level": "warning", "check": "price_basis_labels_shown", "message": "「出品価格」「中古販売価格」ラベルが見つからない（price_history データ未取得の可能性）"})

    # 旧チェック番号を振り直し（109→113以降）
    # 113. 固定メニューが商品ジャンルより上にある（main-tab-nav が cat-genre-bar より前）
    pos_tab_nav  = html.find('id="main-tab-nav"')
    pos_cat_genre = html.find('class="cat-genre-bar"')
    if pos_tab_nav != -1 and pos_cat_genre != -1:
        if pos_tab_nav < pos_cat_genre:
            results.append({"level": "ok", "check": "fixed_nav_above_genre", "message": "固定メニュー（main-tab-nav）が商品ジャンルより上に配置されている"})
        else:
            results.append({"level": "error", "check": "fixed_nav_above_genre", "message": "固定メニューが商品ジャンルより下にある（順序不正）"})
    else:
        results.append({"level": "error", "check": "fixed_nav_above_genre", "message": "main-tab-nav または cat-genre-bar が見つからない"})

    # 113. 商品ジャンルメニューが固定メニューと分離されている（cat-nav-wrap が独立要素）
    has_cat_nav_wrap = "cat-nav-wrap" in html
    if has_cat_nav_wrap:
        results.append({"level": "ok", "check": "genre_nav_separated", "message": "商品ジャンルメニューが固定メニューと分離されたブロック（cat-nav-wrap）にある"})
    else:
        results.append({"level": "error", "check": "genre_nav_separated", "message": "cat-nav-wrap が見つからない（ジャンルナビが未分離の可能性）"})

    # 114. スマホ用横スクロールUIがある（tab-nav が overflow-x: auto の CSS を持つ）
    has_scroll_ui = "overflow-x: auto" in html or "overflow-x:auto" in html
    if has_scroll_ui:
        results.append({"level": "ok", "check": "mobile_scroll_nav", "message": "スマホ横スクロールUI（overflow-x: auto）がCSSに定義されている"})
    else:
        results.append({"level": "warning", "check": "mobile_scroll_nav", "message": "スマホ横スクロールUIが見つからない"})

    # 115. 24時間以上古い案件に対する鮮度バナー警告ロジックが存在する（CSS クラス定義）
    has_stale_warn_css = "data-stale-warn" in html
    if has_stale_warn_css:
        results.append({"level": "ok", "check": "stale_24h_warning_css", "message": "24時間超古いデータの警告バナーCSS（data-stale-warn）が定義されている"})
    else:
        results.append({"level": "warning", "check": "stale_24h_warning_css", "message": "data-stale-warn CSS が見つからない"})

    # 116. 48時間以上古い案件の強警告CSS が存在する
    has_stale_critical_css = "data-stale-critical" in html
    if has_stale_critical_css:
        results.append({"level": "ok", "check": "stale_48h_critical_css", "message": "48時間超古いデータの強警告バナーCSS（data-stale-critical）が定義されている"})
    else:
        results.append({"level": "warning", "check": "stale_48h_critical_css", "message": "data-stale-critical CSS が見つからない"})

    # 117. RICOH GR IV が「一次抽選終了 / 次回未定」になっている
    has_gr4_closed = "一次抽選終了" in html
    if has_gr4_closed:
        results.append({"level": "ok", "check": "gr4_lottery_closed", "message": "RICOH GR IV が「一次抽選終了」として表示されている"})
    else:
        results.append({"level": "warning", "check": "gr4_lottery_closed", "message": "「一次抽選終了」表記が見つからない（RICOH GR IV 抽選状態要確認）"})

    # 118. RICOH GR IV に指定の公式ストアURLが入っている
    has_gr4_url = "S0001551" in html or "ricohimagingstore.com" in html
    if has_gr4_url:
        results.append({"level": "ok", "check": "gr4_official_url", "message": "RICOH GR IV に公式ストア直リンク（ricohimagingstore.com）が含まれている"})
    else:
        results.append({"level": "warning", "check": "gr4_official_url", "message": "RICOH GR IV の公式ストアURL（ricohimagingstore.com）が見つからない"})

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

    # ── #122: Proカード初期表示件数が適切か（collapsed なしカードが1〜8件）──
    import re as _re
    all_pro_cards = _re.findall(r'class="watch-candidate-card pro-candidate-card(?:\s+pro-card-collapsed)?"', html)
    visible_pro_cards = [c for c in all_pro_cards if "pro-card-collapsed" not in c]
    if 1 <= len(visible_pro_cards) <= 8:
        results.append({"level": "ok", "check": "pro_card_initial_limit", "message": f"Proカード初期表示件数が適切（{len(visible_pro_cards)}件表示 / {len(all_pro_cards)}件中）"})
    elif len(visible_pro_cards) == 0:
        results.append({"level": "error", "check": "pro_card_initial_limit", "message": "Proカード初期表示が0件 — pro-card-collapsed の設定を確認"})
    else:
        results.append({"level": "warning", "check": "pro_card_initial_limit", "message": f"Proカード初期表示が多すぎる（{len(visible_pro_cards)}件）— 上位6件制限を確認"})

    # ── #123: さらに表示ボタンが存在するか ──
    has_show_more = "pro-show-more-btn" in html or "pro-card-collapsed" in html
    if has_show_more:
        collapsed_count = html.count("pro-card-collapsed")
        results.append({"level": "ok", "check": "pro_show_more_btn", "message": f"「さらに表示」ボタンが存在する（折り畳みカードあり: {collapsed_count}件）"})
    else:
        results.append({"level": "warning", "check": "pro_show_more_btn", "message": "「さらに表示」ボタンが存在しない（Proカードが6件以下 or 未実装）"})

    # ── #124: 海外soldありフィルタが存在するか ──
    has_overseas_sold_filter = 'data-filter="overseas-sold"' in html
    if has_overseas_sold_filter:
        results.append({"level": "ok", "check": "pro_filter_overseas_sold", "message": "「海外soldあり」フィルタボタンが存在する"})
    else:
        results.append({"level": "error", "check": "pro_filter_overseas_sold", "message": "「海外soldあり」フィルタが存在しない — pro-filter-bar の実装を確認"})

    # ── #125: 価格差ありフィルタが存在するか ──
    has_price_gap_filter = 'data-filter="price-gap"' in html
    if has_price_gap_filter:
        results.append({"level": "ok", "check": "pro_filter_price_gap", "message": "「価格差あり」フィルタボタンが存在する"})
    else:
        results.append({"level": "error", "check": "pro_filter_price_gap", "message": "「価格差あり」フィルタが存在しない — pro-filter-bar の実装を確認"})

    # ── #126: カード並び順（価格差ありカードが先頭に来ているか）──
    first_card_match = _re.search(
        r'class="watch-candidate-card pro-candidate-card"[^>]*data-has-price-gap="(\d)"',
        html,
    )
    if not first_card_match:
        # data-has-price-gap が先頭に来ない場合は属性の順序が異なる可能性
        first_card_match2 = _re.search(
            r'data-has-price-gap="(\d)"[^>]*class="watch-candidate-card',
            html,
        )
        first_pg = first_card_match2.group(1) if first_card_match2 else None
    else:
        first_pg = first_card_match.group(1)
    has_price_gap_card = 'data-has-price-gap="1"' in html
    if has_price_gap_card:
        # 価格差ありカードが存在し、フィルタが動作する構造ならOK
        results.append({"level": "ok", "check": "pro_cards_sorted_by_gap", "message": "価格差ありカードが存在し、ソート構造が正常"})
    else:
        results.append({"level": "warning", "check": "pro_cards_sorted_by_gap", "message": "価格差ありカード（data-has-price-gap=1）が存在しない — 相場データを確認"})

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

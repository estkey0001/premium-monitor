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

    # 20. 新商品候補セクション（存在すれば OK / なくてもwarningだけ）
    if "section-new-products" in html or "new-product-card" in html:
        results.append({"level": "ok", "check": "new_products_section", "message": "新商品候補セクションが存在する"})
    else:
        results.append({"level": "warning", "check": "new_products_section", "message": "新商品候補セクションなし（候補データがない可能性）"})

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

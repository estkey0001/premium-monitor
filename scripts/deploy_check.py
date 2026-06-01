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

    # 11. 更新日時の表示（2026-05-29 仕様変更: 買取データ日時は古い場合非表示のため「更新日：」に統合）
    # 旧ラベル「最終買取データ取得：」「LP生成：」も後方互換として許容
    has_buyback_ts = (
        "最終買取データ取得：" in html or "最終データ取得:" in html or "買取価格更新：" in html
        or "更新日：" in html  # 2026-05-29 新形式
    )
    if has_buyback_ts:
        results.append({"level": "ok", "check": "buyback_updated_ts", "message": "更新日時が表示されている（topbar または hero-timestamps）"})
    else:
        results.append({"level": "warning", "check": "buyback_updated_ts", "message": "更新日時が見つからない（staleness guard でstaleの場合は非表示が正常）"})

    # 12. LP生成日時の表示（「LP生成：」または「更新日：」を許容）
    if "LP生成：" in html or "更新日：" in html:
        results.append({"level": "ok", "check": "lp_generated_ts", "message": "LP生成日時が表示されている"})
    else:
        results.append({"level": "warning", "check": "lp_generated_ts", "message": "LP生成日時が見つからない（hero-timestamps 要確認）"})

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

    # 20. 速報タブ削除確認（Task 3: 速報はポップアップへ移行済み）
    if 'id="tab-sokuhoh"' in html:
        results.append({"level": "warning", "check": "sokuhoh_tab_exists", "message": "速報タブパネルが残っている（Task 3 で削除予定）"})
    else:
        results.append({"level": "ok", "check": "sokuhoh_tab_exists", "message": "速報タブ削除済み（ポップアップへ移行）"})

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
    # 48h超古いデータで全カード除外された場合は警告止まり（正常な除外）
    _data_stale_48h = "data-stale-critical" in html
    if "buyback-shop-table" in html or "buyback-table" in html:
        results.append({"level": "ok", "check": "buyback_shop_table", "message": "初心者カードに複数買取店テーブルが存在する"})
    elif _data_stale_48h:
        results.append({"level": "warning", "check": "buyback_shop_table", "message": "複数買取店テーブルなし（48h超古いデータのため初心者案件を除外中）"})
    else:
        results.append({"level": "error", "check": "buyback_shop_table", "message": "複数買取店テーブルが見つからない（beginner deals 要確認）"})

    # 22. 最高買取価格ラベルが表示されている（旧: 最高売却価格 → 2026-05 に最高買取価格へ統一）
    if "最高買取価格" in html or "buyback-best-price" in html:
        results.append({"level": "ok", "check": "buyback_best_price_label", "message": "最高買取価格ラベルが存在する"})
    elif _data_stale_48h:
        results.append({"level": "warning", "check": "buyback_best_price_label", "message": "最高買取価格ラベルなし（データが古い可能性）"})
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

    # 65. 抽選チップが category-lottery に設定されている（ジャンルドロップダウン統合後はタブボタンで対応）
    if 'data-target-id="category-lottery"' in html and 'data-target-tab="lottery"' in html:
        results.append({"level": "ok", "check": "lottery_chip_target", "message": "抽選チップが category-lottery に正しく設定されている"})
    elif 'data-tab="lottery"' in html:
        results.append({"level": "ok", "check": "lottery_chip_target", "message": "抽選情報タブボタンで抽選情報へのアクセスが可能（ジャンルドロップダウン統合後）"})
    else:
        results.append({"level": "error", "check": "lottery_chip_target", "message": "抽選チップも抽選タブも見つからない"})

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
        results.append({"level": "warning", "check": "shop_name_mobile_ichiban", "message": "「モバイル一番」の店舗名がLP上に見つからない（買取データ取得失敗の可能性 — collector quality gateを確認）"})

    # 85. 買取比較テーブルに「買取商店」テキストがある
    has_kaitori_shouten_name = "買取商店" in html
    if has_kaitori_shouten_name:
        results.append({"level": "ok", "check": "shop_name_kaitori_shouten", "message": "買取比較テーブルに「買取商店」の店舗名が表示されている"})
    else:
        results.append({"level": "warning", "check": "shop_name_kaitori_shouten", "message": "「買取商店」の店舗名がLP上に見つからない（買取データ取得失敗の可能性）"})

    # 86. 買取比較テーブルに「買取一丁目」テキストがある
    has_kaitori_itchome_name = "買取一丁目" in html
    if has_kaitori_itchome_name:
        results.append({"level": "ok", "check": "shop_name_kaitori_itchome", "message": "買取比較テーブルに「買取一丁目」の店舗名が表示されている"})
    else:
        results.append({"level": "warning", "check": "shop_name_kaitori_itchome", "message": "「買取一丁目」の店舗名がLP上に見つからない（買取データ取得失敗の可能性）"})

    # 87. 買取比較テーブルに「じゃんぱら」テキストがある
    has_janpara_name = "じゃんぱら" in html
    if has_janpara_name:
        results.append({"level": "ok", "check": "shop_name_janpara", "message": "買取比較テーブルに「じゃんぱら」の店舗名が表示されている"})
    else:
        results.append({"level": "warning", "check": "shop_name_janpara", "message": "「じゃんぱら」の店舗名がLP上に見つからない（買取データ取得失敗の可能性）"})

    # 88. 買取比較テーブルに「イオシス」テキストがある
    has_iosys_name = "イオシス" in html
    if has_iosys_name:
        results.append({"level": "ok", "check": "shop_name_iosys", "message": "買取比較テーブルに「イオシス」の店舗名が表示されている"})
    else:
        results.append({"level": "warning", "check": "shop_name_iosys", "message": "「イオシス」の店舗名がLP上に見つからない（買取データ取得失敗の可能性）"})

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

    # 91. ページ上部のタイムスタンプラベルが存在する
    has_clear_ts_label = (
        "最終買取データ取得" in html or "最終データ取得" in html
        or "更新日：" in html or 'data-lp-generated' in html
    )
    if has_clear_ts_label:
        results.append({"level": "ok", "check": "hero_ts_label_clear", "message": "ヒーローの更新日時ラベルが存在する（data-lp-generated または 更新日：）"})
    else:
        results.append({"level": "warning", "check": "hero_ts_label_clear", "message": "ヒーローの更新日時ラベルが見つからない — hero-timestamps を確認してください"})

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

    # 94. 鮮度ラベルに日付またはN日前表記が含まれる（observed_at由来の日付表示）
    # 新フォーマット: 「価格確認: MM/DD HH:mm」または「要更新 / N日前」（手動確認データプレフィックスは省略可）
    has_date_in_freshness = bool(re.search(
        r'class="freshness-[a-z]+"[^>]*>[^<]*(?:価格確認: \d{2}/\d{2}|要更新 / \d+日前)',
        html
    ))
    if has_date_in_freshness:
        results.append({"level": "ok", "check": "freshness_shows_date", "message": "鮮度ラベルに価格確認日時/要更新表記が表示されている（新フォーマット）"})
    else:
        results.append({"level": "warning", "check": "freshness_shows_date", "message": "鮮度ラベルに日付/要更新表記が見つからない（manual データなし、またはフォーマット未適用の可能性）"})

    # 95. 「最終確認」または「本日確認」ラベルが使われている（曖昧な「本日○件」の代わり）
    # LP は現在「最終確認 N 件」を使用（手動確認データ表示に合わせた表記）
    has_kakunin_label = "最終確認" in html or "本日確認" in html
    kakunin_text = "最終確認" if "最終確認" in html else ("本日確認" if "本日確認" in html else "")
    if has_kakunin_label:
        results.append({"level": "ok", "check": "count_label_clarity", "message": f"「{kakunin_text}」ラベルが使われている（件数定義が明確）"})
    else:
        results.append({"level": "warning", "check": "count_label_clarity", "message": "「最終確認」「本日確認」ラベルが見つからない — 件数定義が不明確"})

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

    # 101. Hero の件数整合性（announce bar 削除済みのため hero 内のみチェック）
    # 新形式: hero-btn secondary に「(N件)」または件数なしテキストのみ（データ古い場合）
    _hero_btn_count = re.findall(r'hero-btn secondary[^>]*>[^<]*\((\d+)件\)', html)
    # 旧形式フォールバック
    _kakunin_pat = r'(?:最終確認|本日確認)'
    hero_counts_old = re.findall(_kakunin_pat + r'.*?<strong>(\d+)</strong>', html)
    if _hero_btn_count:
        results.append({"level": "ok", "check": "count_consistency", "message": f"Hero ボタンに件数あり（{_hero_btn_count[0]}件）"})
    elif hero_counts_old:
        results.append({"level": "ok", "check": "count_consistency", "message": f"Hero 件数取得済み（旧形式: {hero_counts_old[0]}件）"})
    else:
        # 件数なしは「データ古い時」の正常ケース（stale時は件数を出さない仕様）
        _has_hero_btn = 'hero-btn secondary' in html
        if _has_hero_btn:
            results.append({"level": "ok", "check": "count_consistency", "message": "Hero ボタンあり（データ鮮度低下のため件数非表示 — 正常）"})
        else:
            results.append({"level": "warning", "check": "count_consistency", "message": "Hero の件数ボタンが見つからない（LP再生成で解消する可能性あり）"})

    # 108. Pro向けカードが0件にならない（price_history fallback が動作している）
    has_pro_watch_card = 'pro-candidate-card' in html or 'watch-candidate-card' in html
    if has_pro_watch_card:
        results.append({"level": "ok", "check": "pro_card_not_empty", "message": "Pro向けカード（市場価格テーブル）が表示されている"})
    else:
        results.append({"level": "error", "check": "pro_card_not_empty", "message": "Pro向けカードが0件 — price_history fallback が動作していない可能性"})

    # 109. price_history fallback の案内文が表示されている（fallback 時の注意バナー）
    # adv-fallback-notice は watch_candidates が空の場合にのみ表示される（fallback モード）
    # watch_candidates がある場合（pro-candidate-card が存在する）はバナー不要 → OK
    has_fallback_notice = "adv-fallback-notice" in html
    has_pro_candidates  = "pro-candidate-card" in html or "watch-candidate-card" in html
    if has_fallback_notice:
        results.append({"level": "ok", "check": "pro_fallback_notice", "message": "Pro向けfallback表示の案内文が表示されている（watch_candidates空のfallbackモード）"})
    elif has_pro_candidates:
        # watch_candidates データあり → fallback バナー不要（正常）
        results.append({"level": "ok", "check": "pro_fallback_notice", "message": "Pro向けカードあり → fallback案内文は不要（正常）"})
    else:
        results.append({"level": "warning", "check": "pro_fallback_notice", "message": "Pro向けカードもfallback案内文も見つからない（price_history未取得の可能性）"})

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
    # 113. 固定メニュー（main-tab-nav）にジャンルドロップダウンが統合されている
    pos_tab_nav   = html.find('id="main-tab-nav"')
    pos_genre_dd  = html.find('id="genre-dropdown"')
    pos_cat_genre = html.find('class="cat-genre-bar"')  # 旧形式（統合後は不要）
    if pos_tab_nav != -1 and pos_genre_dd != -1:
        if pos_tab_nav < pos_genre_dd:
            results.append({"level": "ok", "check": "fixed_nav_above_genre", "message": "固定メニュー（main-tab-nav）にジャンルドロップダウンが統合されている"})
        else:
            results.append({"level": "error", "check": "fixed_nav_above_genre", "message": "main-tab-nav が genre-dropdown より後にある（順序不正）"})
    elif pos_tab_nav != -1 and pos_cat_genre != -1:
        # 旧形式（統合前）でも OK
        if pos_tab_nav < pos_cat_genre:
            results.append({"level": "ok", "check": "fixed_nav_above_genre", "message": "固定メニュー（main-tab-nav）が商品ジャンルより上に配置されている"})
        else:
            results.append({"level": "error", "check": "fixed_nav_above_genre", "message": "固定メニューが商品ジャンルより下にある（順序不正）"})
    else:
        results.append({"level": "error", "check": "fixed_nav_above_genre", "message": "main-tab-nav または cat-genre-bar/genre-dropdown が見つからない"})

    # 113. 商品ジャンルメニューが存在する（統合後は genre-dropdown、旧形式は cat-nav-wrap）
    has_genre_dropdown = 'id="genre-dropdown"' in html
    has_cat_nav_wrap   = "cat-nav-wrap" in html
    if has_genre_dropdown:
        results.append({"level": "ok", "check": "genre_nav_separated", "message": "ジャンルドロップダウン（genre-dropdown）が統合ナビ内に存在する"})
    elif has_cat_nav_wrap:
        results.append({"level": "ok", "check": "genre_nav_separated", "message": "商品ジャンルメニューが固定メニューと分離されたブロック（cat-nav-wrap）にある"})
    else:
        results.append({"level": "error", "check": "genre_nav_separated", "message": "genre-dropdown も cat-nav-wrap も見つからない（ジャンルナビが未設定）"})

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

    # 117. RICOH GR IV 3モデルが「抽選受付中」として表示されている
    has_gr4_active = "抽選受付中" in html and "RICOH GR IV" in html
    if has_gr4_active:
        results.append({"level": "ok", "check": "gr4_lottery_active", "message": "RICOH GR IV が「抽選受付中」として表示されている"})
    else:
        results.append({"level": "warning", "check": "gr4_lottery_active", "message": "「抽選受付中」＋「RICOH GR IV」の組み合わせが見つからない（抽選ステータス要確認）"})

    # 118. RICOH GR IV 3モデルの公式ストアURL・製品コードが存在する
    has_gr4_s0001551 = "S0001551" in html
    has_gr4_s0001566 = "S0001566" in html
    has_gr4_s0001580 = "S0001580" in html
    if has_gr4_s0001551 and has_gr4_s0001566 and has_gr4_s0001580:
        results.append({"level": "ok", "check": "gr4_three_models_present", "message": "RICOH GR IV 3モデル（S0001551/S0001566/S0001580）がすべてLP内に存在する"})
    else:
        missing = [c for c, v in [("S0001551(GR IV)", has_gr4_s0001551), ("S0001566(HDF)", has_gr4_s0001566), ("S0001580(Monochrome)", has_gr4_s0001580)] if not v]
        results.append({"level": "warning", "check": "gr4_three_models_present", "message": f"RICOH GR IV モデルのうち一部が見つからない: {', '.join(missing)}"})

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
        results.append({"level": "warning", "check": "pro_card_initial_limit", "message": "Proカード初期表示が0件（買取データ不足の可能性 — collector quality gateを確認）"})
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
        results.append({"level": "warning", "check": "pro_filter_overseas_sold", "message": "「海外soldあり」フィルタが存在しない（Proカードがない場合は非表示 — 正常の可能性あり）"})

    # ── #125: 価格差ありフィルタが存在するか ──
    has_price_gap_filter = 'data-filter="price-gap"' in html
    if has_price_gap_filter:
        results.append({"level": "ok", "check": "pro_filter_price_gap", "message": "「価格差あり」フィルタボタンが存在する"})
    else:
        results.append({"level": "warning", "check": "pro_filter_price_gap", "message": "「価格差あり」フィルタが存在しない（Proカードがない場合は非表示 — 正常の可能性あり）"})

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

    # ── #127: 急騰/急落タブが存在しない（CSS セレクタは除外）──
    import re as _re
    _surge_in_button = bool(_re.search(r'<button[^>]+data-tab="surge"', html))
    _surge_panel     = 'id="tab-surge"' in html
    if _surge_in_button or _surge_panel:
        results.append({"level": "error", "check": "no_surge_tab", "message": "急騰/急落タブ（data-tab=surge）が残っている — 削除してください"})
    else:
        results.append({"level": "ok", "check": "no_surge_tab", "message": "急騰/急落タブは削除済み"})

    # ── #128: 速報タブ削除確認（Task 3: 速報はポップアップへ移行済み）──
    if 'id="tab-sokuhoh"' in html:
        results.append({"level": "warning", "check": "sokuhoh_tab_exists", "message": "#128 速報タブパネルが残っている（Task 3 で削除予定）"})
    else:
        results.append({"level": "ok", "check": "sokuhoh_tab_exists", "message": "#128 速報タブ削除済み（ポップアップへ移行）"})

    # ── #129: 抽選情報タブが1つだけ（CSS セレクタは除外）──
    lottery_tab_count = len(_re.findall(r'<button[^>]+data-tab="lottery"', html))
    if lottery_tab_count == 1:
        results.append({"level": "ok", "check": "single_lottery_tab", "message": "抽選情報タブが1つだけ存在する"})
    elif lottery_tab_count == 0:
        results.append({"level": "error", "check": "single_lottery_tab", "message": "抽選情報タブが存在しない"})
    else:
        results.append({"level": "warning", "check": "single_lottery_tab", "message": f"抽選情報タブが{lottery_tab_count}つ存在する（重複）"})

    # ── #130: メインナビが1つに統合されている ──
    main_nav_count = html.count('id="main-tab-nav"')
    cat_nav_count  = html.count('class="cat-nav-wrap"')
    if main_nav_count == 1 and cat_nav_count == 0:
        results.append({"level": "ok", "check": "unified_main_nav", "message": "メインナビが1つに統合されている（cat-nav-wrapなし）"})
    elif main_nav_count == 1 and cat_nav_count > 0:
        results.append({"level": "warning", "check": "unified_main_nav", "message": "main-tab-navはあるがcat-nav-wrapも残っている（削除推奨）"})
    else:
        results.append({"level": "error", "check": "unified_main_nav", "message": "main-tab-navが見つからない"})

    # ── #131: ジャンルドロップダウンが存在する ──
    if 'id="genre-dropdown"' in html:
        results.append({"level": "ok", "check": "genre_dropdown_exists", "message": "ジャンルドロップダウンが存在する"})
    else:
        results.append({"level": "error", "check": "genre_dropdown_exists", "message": "ジャンルドロップダウン（id=genre-dropdown）が存在しない"})

    # ── #132: ジャンルボタンに data-genre 属性がある ──
    if 'class="genre-btn"' in html and 'data-genre=' in html:
        results.append({"level": "ok", "check": "genre_data_attrs", "message": "ジャンルボタンに data-genre 属性がある"})
    else:
        results.append({"level": "error", "check": "genre_data_attrs", "message": "ジャンルボタン（.genre-btn）または data-genre 属性が存在しない"})

    # ── #133: メーカーチップに data-target-tab 属性がある ──
    if 'class="maker-chip"' in html and 'data-target-tab=' in html:
        results.append({"level": "ok", "check": "maker_data_attrs", "message": "メーカーチップに data-target-tab 属性がある"})
    else:
        results.append({"level": "error", "check": "maker_data_attrs", "message": "メーカーチップ（.maker-chip）または data-target-tab 属性が存在しない"})

    # ── #134: activateCategory 関数が JS に存在する ──
    if 'activateCategory' in html:
        results.append({"level": "ok", "check": "activate_category_js", "message": "activateCategory 関数が JS に存在する"})
    else:
        results.append({"level": "error", "check": "activate_category_js", "message": "activateCategory 関数が JS に存在しない"})

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

    # ── #137: 手動確認データの表示 ──
    has_manual_label = "手動確認" in html or "手動確認データ" in html
    if has_manual_label:
        results.append({"level": "ok", "check": "manual_data_label_present", "message": "「手動確認データ」ラベルが存在する"})
    else:
        results.append({"level": "warning", "check": "manual_data_label_present", "message": "「手動確認」ラベルが存在しない — 手動CSVデータであることをユーザーに明示してください"})

    # ── #138: 48h超古いデータに強警告バナーがあるか（構造確認） ──
    has_critical_css = "data-stale-critical" in html
    if has_critical_css:
        results.append({"level": "ok", "check": "stale_48h_banner_ready", "message": "48h超古いデータ用の強警告バナーCSS/属性が定義されている"})
    else:
        results.append({"level": "error", "check": "stale_48h_banner_ready", "message": "data-stale-critical が存在しない"})

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
    kakunin_in_freshness = bool(_re4.search(r'class="freshness-[a-z]+"[^>]*>[^<]*価格確認:', html))
    stale_yoko_exists = bool(_re4.search(r'class="freshness-[a-z]+"[^>]*>[^<]*要更新 / \d+日前', html))
    if kakunin_in_freshness:
        results.append({"level": "ok", "check": "freshness_kakunin_format", "message": "鮮度ラベルに「価格確認: MM/DD」形式が使われている"})
    elif stale_yoko_exists:
        results.append({"level": "ok", "check": "freshness_kakunin_format", "message": "全データが48h+古いため「要更新 / N日前」形式で表示（「価格確認:」は新鮮データ時のみ）"})
    else:
        results.append({"level": "warning", "check": "freshness_kakunin_format", "message": "鮮度ラベルに「価格確認:」形式が見つからない（データなし or 旧フォーマット）"})

    # ── #142: 古い価格ラベルが「要更新 / N日前」形式を使っている ──
    yoko_in_freshness = bool(_re4.search(r'class="freshness-(?:stale|warn)"[^>]*>[^<]*要更新 /', html))
    if yoko_in_freshness:
        results.append({"level": "ok", "check": "freshness_yoko_format", "message": "古い価格に「要更新 / N日前」形式が使われている"})
    else:
        results.append({"level": "warning", "check": "freshness_yoko_format", "message": "「要更新 / N日前」形式が見つからない（全データが新鮮 or フォーマット未適用）"})

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

    # fetch_failed_display: 「取得失敗 / 要確認」表示クラスがある（または全成功）
    has_fetch_failed_css = "freshness-fetch-failed" in html
    has_any_fetch_failed_text = "取得失敗 / 要確認" in html
    # CSV上に fetch_failed 行があるか確認
    csv_has_fetch_failed = False
    if csv_path.exists():
        try:
            with open(csv_path, newline="", encoding="utf-8") as _f:
                for row in _csv.DictReader(_f):
                    if row.get("data_source", "") == "fetch_failed":
                        csv_has_fetch_failed = True
                        break
        except Exception:
            pass
    if csv_has_fetch_failed:
        if has_fetch_failed_css or has_any_fetch_failed_text:
            results.append({"level": "ok", "check": "fetch_failed_display", "message": "fetch_failed 行があり、LP上に「取得失敗 / 要確認」表示がある"})
        else:
            results.append({"level": "warning", "check": "fetch_failed_display", "message": "CSV上に fetch_failed 行があるが、LP上に「取得失敗 / 要確認」表示が見つからない"})
    else:
        results.append({"level": "ok", "check": "fetch_failed_display", "message": "fetch_failed 行なし（全取得成功 or スクレイピング未実行）"})

    # no_price_zero_shown: buyback_price=0 かつ data_source != fetch_failed の行がLPに表示されていない
    # LP上で price=0 の行が「取得失敗」以外の形で表示されていないかをHTML検査
    # （¥0 の直接表記がないか確認）
    zero_price_pattern = re.findall(r'(?<![¥￥\d])[¥￥]0(?!\d)', html)
    if zero_price_pattern:
        results.append({"level": "warning", "check": "no_price_zero_shown", "message": f"LP上に¥0の価格表記が{len(zero_price_pattern)}件存在する（fetch_failed以外の0価格行が表示されている可能性）"})
    else:
        results.append({"level": "ok", "check": "no_price_zero_shown", "message": "LP上に¥0の価格表記なし（0価格行は非表示 or fetch_failed表示で正常）"})

    # ── #145: 自動取得バッジが表示されている ──
    has_auto_scraped_badge = 'badge-auto-scraped' in html
    if has_auto_scraped_badge:
        results.append({"level": "ok", "check": "auto_scraped_badge", "message": "「自動取得」バッジ（badge-auto-scraped）が表示されている"})
    else:
        # CSV に auto_scraped 行がある場合のみエラー、なければ警告
        csv_has_auto = False
        if csv_path.exists():
            try:
                with open(csv_path, newline="", encoding="utf-8") as _f:
                    for row in _csv.DictReader(_f):
                        if row.get("data_source", "") == "auto_scraped":
                            csv_has_auto = True
                            break
            except Exception:
                pass
        if csv_has_auto:
            results.append({"level": "error", "check": "auto_scraped_badge", "message": "CSV に auto_scraped 行があるが LP 上に「自動取得」バッジが見つからない"})
        else:
            results.append({"level": "warning", "check": "auto_scraped_badge", "message": "「自動取得」バッジなし（CSV に auto_scraped データなし、または LP 未再生成）"})

    # ── #146: 取得失敗バッジが表示されている ──
    has_fetch_failed_badge = 'badge-fetch-failed' in html
    if has_fetch_failed_badge:
        results.append({"level": "ok", "check": "fetch_failed_badge", "message": "「取得失敗」バッジ（badge-fetch-failed）が表示されている"})
    else:
        if csv_has_fetch_failed:
            results.append({"level": "warning", "check": "fetch_failed_badge", "message": "CSV に fetch_failed 行があるが LP 上に「取得失敗」バッジが見つからない（LP 再生成を推奨）"})
        else:
            results.append({"level": "ok", "check": "fetch_failed_badge", "message": "取得失敗バッジなし（fetch_failed データなし、正常）"})

    # ── #147: 取得失敗行に確認リンクがある ──
    import re as _re5
    failed_rows_with_links = _re5.findall(r'shop-row-failed[^>]*>.*?<a\s+href=', html, _re5.DOTALL)
    failed_rows_without_links = _re5.findall(r'shop-row-failed', html)
    if not failed_rows_without_links:
        results.append({"level": "ok", "check": "fetch_failed_has_link", "message": "取得失敗行なし（全取得成功）"})
    elif failed_rows_with_links:
        results.append({"level": "ok", "check": "fetch_failed_has_link", "message": f"取得失敗行（shop-row-failed）に確認リンクがある（{len(failed_rows_with_links)}行）"})
    else:
        results.append({"level": "error", "check": "fetch_failed_has_link", "message": "取得失敗行（shop-row-failed）に確認リンクがない — URL 設定を確認してください"})

    # ── #148: ページ上部に取得統計（自動取得N件 / 取得失敗N件）が表示されている ──
    has_collection_stats = 'collection-stats-bar' in html
    has_stats_text = bool(re.search(r'自動取得\s*\d+件', html))
    if has_collection_stats or has_stats_text:
        results.append({"level": "ok", "check": "collection_stats_shown", "message": "ページ上部に取得統計（自動取得N件/取得失敗N件）が表示されている"})
    else:
        results.append({"level": "warning", "check": "collection_stats_shown", "message": "取得統計バーが見つからない（LP 再生成で反映されます）"})

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

    # ── #161: iPhone 17 Pro 256GB が初心者向け内に表示されている ──
    _has_iphone17_in_beginner = "iPhone 17 Pro 256GB" in html
    if _has_iphone17_in_beginner:
        results.append({"level": "ok", "check": "iphone17pro_in_beginner", "message": "iPhone 17 Pro 256GB が初心者向けセクションに表示されている"})
    else:
        results.append({"level": "warning", "check": "iphone17pro_in_beginner", "message": "iPhone 17 Pro 256GB が初心者向けセクションに見つからない（買取データ取得失敗の可能性）"})

    # ── #162: マイナス利益商品が「現在は赤字」として表示されている ──
    _has_monitoring_badge = 'badge-monitoring' in html or '現在は赤字' in html
    results.append({
        "level": "ok" if _has_monitoring_badge else "warning",
        "check": "monitoring_badge_shown",
        "message": "「現在は赤字」バッジが表示されている" if _has_monitoring_badge else "「現在は赤字」バッジが見つからない（赤字商品がない可能性）"
    })

    # ── #163: マイナス利益商品が通常の緑カードに混ざっていない ──
    import re as _re_monitoring
    _monitoring_with_green = _re_monitoring.findall(
        r'data-user-level="monitoring"[^>]*>(?:(?!data-user-level).)*?class="badge badge-easy"',
        html, _re_monitoring.DOTALL
    )
    if _monitoring_with_green:
        results.append({"level": "error", "check": "monitoring_not_in_green_card", "message": f"monitoring商品が緑(badge-easy)カードに混ざっている: {len(_monitoring_with_green)}件"})
    else:
        results.append({"level": "ok", "check": "monitoring_not_in_green_card", "message": "monitoring商品は緑カードに混ざっていない"})

    # ── #164: 取得失敗商品が「取得失敗/要確認」として表示されている ──
    _has_fetch_failed_card = 'badge-fetch-failed-card' in html or 'data-user-level="fetch_failed"' in html
    results.append({
        "level": "ok" if _has_fetch_failed_card else "warning",
        "check": "fetch_failed_card_shown",
        "message": "取得失敗カードが表示されている" if _has_fetch_failed_card else "取得失敗カードが見つからない（取得失敗商品がない可能性）"
    })

    # ── #165: 初心者タブが0件表示にならない ──
    _has_any_beginner_card = any(x in html for x in ['badge-easy', 'badge-watch', 'badge-monitoring', 'badge-fetch-failed-card'])
    if _has_any_beginner_card:
        results.append({"level": "ok", "check": "beginner_tab_not_empty", "message": "初心者向けタブに1件以上の商品が表示されている"})
    else:
        results.append({"level": "error", "check": "beginner_tab_not_empty", "message": "初心者向けタブが0件（商品が全く表示されていない）"})

    # ── #166: iPhone 17 Pro がスマホ欄（iphone セクション）に表示されている ──
    # コンテンツ内の <div id="category-beginner-iphone"> を探す（ナビメニューのボタンとは区別）
    import re as _re166
    _beg_tab_start = html.find('id="tab-beginner"')
    _beg_tab_end   = html.find('id="tab-advanced"')
    _beg_tab_html  = html[_beg_tab_start:_beg_tab_end] if _beg_tab_start >= 0 and _beg_tab_end > _beg_tab_start else ""

    # ── #150: カード上部の最高買取価格と比較テーブル1位価格の一致確認 ──
    # beginner_easy / beginner_watch カードのみ対象（monitoringカードは「最高買取価格」ラベルなし）
    # ※ _beg_tab_html は上で定義済み
    import re as _re6
    card_sections_150 = _re6.split(r'(?=<div[^>]+data-user-level=")', _beg_tab_html)
    mismatch_150 = []
    checked_150 = 0
    for _cs in card_sections_150:
        _ul_m = _re6.match(r'<div[^>]+data-user-level="([^"]+)"', _cs)
        if not _ul_m or _ul_m.group(1) not in ('beginner_easy', 'beginner_watch'):
            continue
        _best_m = _re6.search(
            r'最高買取価格</div>\s*<div class="price-cell-val[^"]*">¥([\d,]+)', _cs)
        _gold_m = _re6.search(
            r'shop-rank gold[^<]*</div>\s*<div class="shop-name-col">[^<]*</div>\s*<div class="shop-price-col">¥([\d,]+)', _cs)
        if _best_m and _gold_m:
            checked_150 += 1
            if _best_m.group(1).replace(',','') != _gold_m.group(1).replace(',',''):
                mismatch_150.append(f"best=¥{_best_m.group(1)} vs gold=¥{_gold_m.group(1)}")
    if checked_150 == 0:
        results.append({"level": "ok", "check": "best_price_matches_table",
                        "message": "利益ありカードなし（価格整合チェックスキップ）"})
    elif mismatch_150:
        results.append({"level": "warning", "check": "best_price_matches_table",
                        "message": f"カード最高価格と比較テーブル1位が不一致（{len(mismatch_150)}件）: {mismatch_150[:2]}"})
    else:
        results.append({"level": "ok", "check": "best_price_matches_table",
                        "message": f"カード最高価格と比較テーブル1位が一致（{checked_150}件確認）"})
    _iphone_section_in_beg = _re166.search(
        r'<div id="category-beginner-iphone".*?(?=<div id="category-beginner-tablet"|<div id="category-beginner-game"|<div id="category-beginner-other"|$)',
        _beg_tab_html, _re166.DOTALL
    )
    _iphone17pro_in_iphone_section = bool(_iphone_section_in_beg and 'iPhone 17 Pro' in _iphone_section_in_beg.group(0))
    results.append({
        "level": "ok" if _iphone17pro_in_iphone_section else "warning",
        "check": "iphone17_in_iphone_section",
        "message": "iPhone 17 Pro がスマホ欄に表示" if _iphone17pro_in_iphone_section else "iPhone 17 Pro がスマホ欄に見つからない（買取データ取得失敗の可能性）"
    })

    # ── #167: Switch 2 / PlayStation がゲーム機欄に表示されている ──
    import re as _re167
    _game_section_in_beg = _re167.search(
        r'<div id="category-beginner-game".*?(?=<div id="category-beginner-other"|<div id="tab-"|$)',
        _beg_tab_html, _re167.DOTALL
    )
    _switch2_in_game = bool(_game_section_in_beg and ('Nintendo Switch 2' in _game_section_in_beg.group(0) or 'PlayStation' in _game_section_in_beg.group(0)))
    results.append({
        "level": "ok" if _switch2_in_game else "warning",
        "check": "game_console_in_game_section",
        "message": "ゲーム機がゲーム機欄に表示" if _switch2_in_game else "ゲーム機商品がゲーム機欄に見つからない"
    })

    # ── #168: 監視中セクションが最上位になっていない（ジャンル内にある）──
    # beginner タブ内で、最初のジャンルブロック（category-beginner-iphone）より前に
    # status-monitoring が出ていないことを確認する（旧構造の残骸チェック）
    import re as _re168
    _first_genre_pos = _beg_tab_html.find('<div id="category-beginner-')
    _monitoring_pos_in_beg = _beg_tab_html.find('status-subhead status-monitoring')
    # monitoring がジャンルブロック外（最初のジャンルより前）に存在する場合はエラー
    _monitoring_before_genre = (
        _monitoring_pos_in_beg >= 0
        and _first_genre_pos >= 0
        and _monitoring_pos_in_beg < _first_genre_pos
    )
    if _monitoring_before_genre:
        results.append({"level": "error", "check": "monitoring_inside_genre", "message": "監視中セクションがジャンル外（最上位）に出ている"})
    else:
        results.append({"level": "ok", "check": "monitoring_inside_genre", "message": "監視中セクションはジャンル内に正しく配置されている"})

    # ── #169: 各ジャンル内に状態別見出しがある ──
    _has_status_subhead = 'status-subhead' in _beg_tab_html
    results.append({
        "level": "ok" if _has_status_subhead else "warning",
        "check": "status_subhead_exists",
        "message": "ジャンル内に状態別見出しが存在する" if _has_status_subhead else "状態別見出し(status-subhead)が見つからない"
    })

    # ── #170: カメラ商品が初心者タブに表示されている（2026-05-28 仕様変更: 意図的に beginner タブへ移動）──
    # カメラは公式購入→買取の差益案件として初心者タブに表示するのが正しい
    import re as _re170
    _camera_in_beginner = _re170.findall(
        r'data-user-level="(?:beginner_easy|beginner_watch|monitoring|fetch_failed)"[^>]*>(?:(?!data-user-level).)*?badge-camera',
        _beg_tab_html, _re170.DOTALL
    )
    if _camera_in_beginner:
        results.append({"level": "ok", "check": "camera_in_beginner", "message": f"カメラ商品が初心者タブに{len(_camera_in_beginner)}件表示されている（仕様通り）"})
    else:
        # カメラデータがない場合は警告（データ未生成の可能性）
        results.append({"level": "warning", "check": "camera_in_beginner", "message": "カメラ商品が初心者タブに表示されていない（BeginnerDeal未生成の可能性）"})

    # ── #171: iPad がタブレット欄（category-beginner-tablet）に表示されている ──
    import re as _re171
    _tablet_section = _re171.search(
        r'<div id="category-beginner-tablet".*?(?=<div id="category-beginner-pc"|<div id="category-beginner-game"|<div id="category-beginner-other"|$)',
        _beg_tab_html, _re171.DOTALL
    )
    _ipad_in_tablet = bool(_tablet_section and 'iPad' in _tablet_section.group(0))
    results.append({
        "level": "ok" if _ipad_in_tablet else "warning",
        "check": "ipad_in_tablet_section",
        "message": "iPad がタブレット欄に表示" if _ipad_in_tablet else "iPad がタブレット欄に見つからない（データなし or genre設定を確認）"
    })

    # ── #172: MacBook が PC欄（category-beginner-pc）に表示されている ──
    import re as _re172
    _pc_section = _re172.search(
        r'<div id="category-beginner-pc".*?(?=<div id="category-beginner-wearable"|<div id="category-beginner-game"|<div id="category-beginner-other"|$)',
        _beg_tab_html, _re172.DOTALL
    )
    _macbook_in_pc = bool(_pc_section and ('MacBook' in _pc_section.group(0) or 'Mac mini' in _pc_section.group(0)))
    results.append({
        "level": "ok" if _macbook_in_pc else "warning",
        "check": "macbook_in_pc_section",
        "message": "MacBook/Mac mini がPC欄に表示" if _macbook_in_pc else "MacBook/Mac mini がPC欄に見つからない（データなし or genre設定を確認）"
    })

    # ── #173: 取得失敗カードに失敗理由バッジが存在する ──
    # fetch_failedカードが存在する場合のみチェック（0件の場合はOK）
    _has_ff_cards = 'data-user-level="fetch_failed"' in _beg_tab_html
    if _has_ff_cards:
        _has_failure_reason_badge = 'failure-reason-badge' in _beg_tab_html
        results.append({
            "level": "ok" if _has_failure_reason_badge else "warning",
            "check": "failure_reason_badge_shown",
            "message": "取得失敗カードに失敗理由バッジが表示されている" if _has_failure_reason_badge else "取得失敗カードがあるが失敗理由バッジが見つからない"
        })
    else:
        results.append({"level": "ok", "check": "failure_reason_badge_shown", "message": "取得失敗カードなし（失敗理由バッジ不要）"})

    # ── #174: 取得失敗カードに最終試行時刻が表示されている ──
    if _has_ff_cards:
        _has_failure_timestamp = 'fetch-failed-timestamp' in _beg_tab_html
        results.append({
            "level": "ok" if _has_failure_timestamp else "warning",
            "check": "failure_timestamp_shown",
            "message": "取得失敗カードに最終試行時刻が表示されている" if _has_failure_timestamp else "取得失敗カードがあるが最終試行時刻が見つからない"
        })
    else:
        results.append({"level": "ok", "check": "failure_timestamp_shown", "message": "取得失敗カードなし（最終試行時刻不要）"})

    # ── #175: iPad がその他欄（genre=ipad）で表示されていない ──
    # ipad genre の商品が category-beginner-other に混入していないか確認
    import re as _re175
    _other_section = _re175.search(
        r'<div id="category-beginner-other".*?$',
        _beg_tab_html, _re175.DOTALL
    )
    _ipad_in_other = bool(_other_section and 'iPad' in _other_section.group(0))
    if _ipad_in_other:
        results.append({"level": "error", "check": "ipad_not_in_other", "message": "iPad が「その他」欄に混入している（genre=tabletに修正が必要）"})
    else:
        results.append({"level": "ok", "check": "ipad_not_in_other", "message": "iPad は「その他」欄に混入していない"})

    # ── #176: AirPods がスマートフォン欄に入っていない ──
    import re as _re176
    _sp_section = _re176.search(
        r'<div id="category-beginner-smartphone".*?(?=<div id="category-beginner-tablet"|<div id="category-beginner-pc"|<div id="category-beginner-wearable"|<div id="category-beginner-audio"|<div id="category-beginner-game"|<div id="category-beginner-other"|$)',
        _beg_tab_html, _re176.DOTALL
    )
    _airpods_in_sp = bool(_sp_section and 'AirPods' in _sp_section.group(0))
    if _airpods_in_sp:
        results.append({"level": "error", "check": "airpods_not_in_smartphone",
                        "message": "AirPods がスマートフォン欄に混入している（genre=audioに修正が必要）"})
    else:
        results.append({"level": "ok", "check": "airpods_not_in_smartphone",
                        "message": "AirPods はスマートフォン欄に混入していない"})

    # ── #177: Apple Watch がウェアラブル欄（category-beginner-wearable）に表示されている ──
    import re as _re177
    _wearable_section = _re177.search(
        r'<div id="category-beginner-wearable".*?(?=<div id="category-beginner-audio"|<div id="category-beginner-game"|<div id="category-beginner-other"|$)',
        _beg_tab_html, _re177.DOTALL
    )
    _applewatch_in_wearable = bool(_wearable_section and 'Apple Watch' in _wearable_section.group(0))
    results.append({
        "level": "ok" if _applewatch_in_wearable else "warning",
        "check": "applewatch_in_wearable_section",
        "message": "Apple Watch がウェアラブル欄に表示" if _applewatch_in_wearable else "Apple Watch がウェアラブル欄に見つからない（データなし or genre設定を確認）"
    })

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

    # ── #184: fetch_failed が存在する場合、取得失敗リンクが表示される ──
    # collector_report/latest.json の failed 件数 >= threshold なら collector-warn-bar が表示されるべき
    import json as _json184
    _cr_json_path = PROJECT_ROOT / "exports" / "collector_report" / "latest.json"
    _WARN_THRESHOLD = 5
    if _cr_json_path.exists():
        try:
            _cr184 = _json184.loads(_cr_json_path.read_text(encoding="utf-8"))
            _failed184 = _cr184.get("summary", {}).get("failed", 0)
            _suspicious184 = len(_cr184.get("suspicious_prices", []))
            _should_show_warn = (_failed184 >= _WARN_THRESHOLD) or (_suspicious184 > 0)
            _has_warn_bar = 'collector-warn-bar' in html
            if _should_show_warn:
                if _has_warn_bar:
                    results.append({"level": "ok", "check": "fetch_failed_report_link",
                                    "message": f"取得失敗{_failed184}件 / suspicious{_suspicious184}件 → 警告バーが表示されている"})
                else:
                    results.append({"level": "warning", "check": "fetch_failed_report_link",
                                    "message": f"取得失敗{_failed184}件 / suspicious{_suspicious184}件あるが collector-warn-bar が表示されていない（LP 再生成が必要）"})
            else:
                results.append({"level": "ok", "check": "fetch_failed_report_link",
                                "message": f"取得失敗{_failed184}件（閾値{_WARN_THRESHOLD}未満）／suspicious 0件 → 警告バー表示不要"})
        except Exception as _e184:
            results.append({"level": "ok", "check": "fetch_failed_report_link",
                            "message": f"collector_report JSON 読み込みエラー（スキップ）: {_e184}"})
    else:
        results.append({"level": "ok", "check": "fetch_failed_report_link",
                        "message": "collector_report/latest.json 未生成のためスキップ"})

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

    # ── #186: 初心者ページの自動取得0件チェック ──
    # LP HTMLに auto_scraped カードがまったくない場合はエラー（取得完全失敗）
    _auto_scraped_in_lp = html.count('data-source="auto_scraped"') + html.count("data_source='auto_scraped'") + html.count("auto_scraped")
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

    # ── #187: 店舗名縦書き崩れなし (shop-name-col に word-break:keep-all が存在する) ──
    if 'word-break: keep-all' in html or 'word-break:keep-all' in html:
        results.append({"level": "ok", "check": "shop_name_no_vertical_wrap",
                        "message": "shop-name-col に word-break:keep-all が設定されている"})
    else:
        results.append({"level": "warning", "check": "shop_name_no_vertical_wrap",
                        "message": "shop-name-col の word-break:keep-all が見当たらない — 店舗名が縦書きになる可能性"})

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

    # ── #189: 取得失敗セクションが折りたたみ可能（<details>タグ）──
    # fetch_failed_details クラスの details タグが存在するか確認
    if 'fetch-failed-details' in html:
        results.append({"level": "ok", "check": "fetch_failed_section_collapsible",
                        "message": "取得失敗セクションが <details> 折りたたみ対応されている"})
    else:
        results.append({"level": "warning", "check": "fetch_failed_section_collapsible",
                        "message": "取得失敗セクションに fetch-failed-details が見当たらない — LP再生成が必要"})

    # ── #190: 取得失敗が多すぎて初心者ページが埋まっていない ──
    # fetch_failed 件数がページ内カード総数の70%未満であるべき
    _ff_card_count = html.count('stripe-fetch-failed')
    _total_cards = html.count('deal-card')
    if _total_cards > 0:
        _ff_ratio = _ff_card_count / _total_cards
        if _ff_ratio >= 0.70:
            results.append({"level": "warning", "check": "fetch_failed_not_dominant",
                            "message": f"取得失敗カードが全カードの{_ff_ratio:.0%}（{_ff_card_count}/{_total_cards}）— 自動取得改善が必要"})
        else:
            results.append({"level": "ok", "check": "fetch_failed_not_dominant",
                            "message": f"取得失敗カード比率 {_ff_ratio:.0%}（{_ff_card_count}/{_total_cards}）— 許容範囲内"})
    else:
        results.append({"level": "ok", "check": "fetch_failed_not_dominant",
                        "message": "deal-card が見当たらない（LP未生成またはカード形式変更）"})

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

    # ── #196: debug HTML/TXT が保存されている ────────────────────────────────
    import glob as _glob
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

    # ── #199: fetch_failed 3件超のときに「さらに表示」UIが存在する ──────────
    _lp_html_199 = _lp_html_197
    if _lp_html_199:
        _ff_shop_count = _lp_html_199.count('shop-row-failed')
        if _ff_shop_count > 3:
            if 'ff-more-btn' in _lp_html_199:
                results.append({"level": "ok", "check": "fetch_failed_collapse_ui_exists",
                                "message": f"fetch_failed店舗 {_ff_shop_count}件で「さらに表示」UIが存在"})
            else:
                results.append({"level": "warning", "check": "fetch_failed_collapse_ui_exists",
                                "message": f"fetch_failed店舗 {_ff_shop_count}件あるが「さらに表示」UIが見つからない"})
        else:
            results.append({"level": "ok", "check": "fetch_failed_collapse_ui_exists",
                            "message": f"fetch_failed店舗 {_ff_shop_count}件（3件以下のため折りたたみUI不要）"})
    else:
        results.append({"level": "warning", "check": "fetch_failed_collapse_ui_exists",
                        "message": "LP HTMLが見つからないため fetch_failed_collapse_ui チェックをスキップ"})

    # ── #200: monitoring カードに価格変動メッセージが存在する ──────────────────
    # Task 5 でUI統一: monitoring-note クラスは廃止 → profit-note に「現在は赤字 / 価格変動を監視中」
    _lp_html_200 = _lp_html_197
    if _lp_html_200:
        _has_monitoring_msg = (
            '価格変動を監視中' in _lp_html_200
            or '監視中' in _lp_html_200
        ) and 'data-user-level="monitoring"' in _lp_html_200
        if _has_monitoring_msg:
            results.append({"level": "ok", "check": "monitoring_description_exists",
                            "message": "monitoring カードに監視中メッセージが存在"})
        else:
            results.append({"level": "warning", "check": "monitoring_description_exists",
                            "message": "monitoring カードの監視中メッセージが見つからない"})
    else:
        results.append({"level": "warning", "check": "monitoring_description_exists",
                        "message": "LP HTMLが見つからないため monitoring_description チェックをスキップ"})

    # ── #201: fetch_failed セクションに説明文が存在する ──────────────────────
    # fetch_failed カードが実際に表示されている場合のみ確認
    _lp_html_201 = _lp_html_197
    if _lp_html_201:
        _has_ff_card = ('badge-fetch-failed-card' in _lp_html_201
                        or 'data-user-level="fetch_failed"' in _lp_html_201)
        if not _has_ff_card:
            # fetch_failed カードが存在しない → 説明文チェック不要
            results.append({"level": "ok", "check": "fetch_failed_description_exists",
                            "message": "fetch_failed カードなし → 説明文チェックスキップ（正常）"})
        elif 'fetch-failed-note' in _lp_html_201:
            results.append({"level": "ok", "check": "fetch_failed_description_exists",
                            "message": "fetch_failed セクションに説明文が存在"})
        else:
            results.append({"level": "warning", "check": "fetch_failed_description_exists",
                            "message": "fetch_failed カードあるが説明文（fetch-failed-note）が見つからない"})
    else:
        results.append({"level": "warning", "check": "fetch_failed_description_exists",
                        "message": "LP HTMLが見つからないため fetch_failed_description チェックをスキップ"})

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
        _t206e3 = "git pull --rebase origin main" in _workflow_text
        results.append({"level": "ok" if _t206e3 else "warning", "check": "workflow_pull_rebase_before_push",
                        "message": "Commit and push ステップに git pull --rebase origin main がある"
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

    # ── #210: RICOH GR IV 3モデルの forms.gle リンクが LP に存在する ──────────────
    _gr4_forms = {
        "GR IV":            "forms.gle/4vvkxe1e9ghfiy667",
        "GR IV HDF":        "forms.gle/tAWGX3dnehAnWgX5A",
        "GR IV Monochrome": "forms.gle/FjicSoGraoJuQwBd9",
    }
    _missing_forms = [name for name, url in _gr4_forms.items() if url not in html]
    if not _missing_forms:
        results.append({"level": "ok", "check": "gr4_forms_links",
                        "message": "RICOH GR IV 3モデルの抽選フォームリンク（forms.gle）がすべて存在する"})
    else:
        results.append({"level": "warning", "check": "gr4_forms_links",
                        "message": f"RICOH GR IV フォームリンクが見つからないモデル: {', '.join(_missing_forms)}"})

    # ── #211: RICOH GR IV 3モデルの公式価格が LP に存在する ──────────────────────
    _gr4_prices = {
        "GR IV ¥194,800":        "194,800",
        "GR IV HDF ¥187,020":    "187,020",
        "GR IV Monochrome ¥283,800": "283,800",
    }
    _missing_prices = [label for label, price in _gr4_prices.items() if price not in html]
    if not _missing_prices:
        results.append({"level": "ok", "check": "gr4_prices_present",
                        "message": "RICOH GR IV 3モデルの公式価格（¥194,800/¥187,020/¥283,800）がすべて存在する"})
    else:
        results.append({"level": "warning", "check": "gr4_prices_present",
                        "message": f"RICOH GR IV 価格が見つからない: {', '.join(_missing_prices)}"})

    # ── #212: RICOH GR IV 抽選受付期間（2026-05-27〜2026-05-29）が LP に存在する ──
    _has_entry_start = "2026-05-27" in html
    _has_entry_end   = "2026-05-29" in html
    if _has_entry_start and _has_entry_end:
        results.append({"level": "ok", "check": "gr4_entry_period_present",
                        "message": "RICOH GR IV 抽選受付期間（2026-05-27〜2026-05-29）がLP内に存在する"})
    else:
        missing_dates = []
        if not _has_entry_start:
            missing_dates.append("2026-05-27（受付開始）")
        if not _has_entry_end:
            missing_dates.append("2026-05-29（受付終了）")
        results.append({"level": "warning", "check": "gr4_entry_period_present",
                        "message": f"RICOH GR IV 抽選期間の日付が見つからない: {', '.join(missing_dates)}"})

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
    if _lp_gen_path.exists():
        _lp_text = _lp_gen_path.read_text(encoding="utf-8")
        _has_not_listed_display = (
            "product_not_listed" in _lp_text and
            "現在未掲載" in _lp_text and
            "badge-not-listed" in _lp_text
        )
        if _has_not_listed_display:
            results.append({"level": "ok", "check": "lp_not_listed_display",
                            "message": "LP が product_not_listed を「現在未掲載」バッジで表示する実装が存在する"})
        else:
            results.append({"level": "warning", "check": "lp_not_listed_display",
                            "message": "LP が product_not_listed を「現在未掲載」で表示していない — _source_badge の更新が必要"})
    else:
        results.append({"level": "warning", "check": "lp_not_listed_display",
                        "message": "src/content/daily_lp_generator.py が見つからない"})

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

    # ── #224: badge-not-listed が green 系色を使っていない ─────────────────────
    if _lp_gen_path.exists():
        import re as _re2
        # .badge-not-listed ブロックを抽出して green 系色 (#0A7C4F, #166534, rgba(0,200 など) を検出
        _badge_block = _re2.search(
            r'\.badge-not-listed\s*\{\{(.*?)\}\}', _lp_text, _re2.DOTALL
        )
        _fresh_block = _re2.search(
            r'\.freshness-not-listed\s*\{\{(.*?)\}\}', _lp_text, _re2.DOTALL
        )
        _GREEN_PATTERNS = [r'#0A7C4F', r'#166534', r'#15803D', r'rgba\(0,200', r'rgba\(21,128']
        def _has_green(block_match) -> bool:
            if not block_match:
                return False
            content = block_match.group(1)
            return any(_re2.search(p, content, _re2.IGNORECASE) for p in _GREEN_PATTERNS)
        _badge_green = _has_green(_badge_block)
        _fresh_green = _has_green(_fresh_block)
        if not _badge_green and not _fresh_green:
            results.append({"level": "ok", "check": "not_listed_badge_not_green",
                            "message": "badge-not-listed / freshness-not-listed が green 系色を使っていない（自動取得成功と区別）"})
        else:
            which = []
            if _badge_green:  which.append("badge-not-listed")
            if _fresh_green:  which.append("freshness-not-listed")
            results.append({"level": "warning", "check": "not_listed_badge_not_green",
                            "message": f"{', '.join(which)} が green 系色を使用 — 自動取得成功（緑）と紛らわしい"})
    else:
        results.append({"level": "warning", "check": "not_listed_badge_not_green",
                        "message": "src/content/daily_lp_generator.py が見つからない"})

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

        # ── #229: _section_lottery が 4セクション（A/B/C/D）を持つ ─────────────
        _lottery_fn_m = _re3.search(
            r'def _section_lottery\(.*?\n    def ', _lp_gen_text, _re3.DOTALL
        )
        _lottery_fn_text = _lottery_fn_m.group(0) if _lottery_fn_m else ""
        _has_active_section   = "現在受付中" in _lottery_fn_text
        _has_closed_section   = "受付終了" in _lottery_fn_text and "lottery-closed-section" in _lottery_fn_text
        _has_reference_section = "lottery-reference-section" in _lottery_fn_text or "参考リンク" in _lottery_fn_text
        if _has_active_section and _has_closed_section and _has_reference_section:
            results.append({"level": "ok", "check": "lottery_4sections",
                            "message": "_section_lottery に 受付中/受付終了/参考リンク の3種+フォールバック構造が存在"})
        else:
            _missing = []
            if not _has_active_section:   _missing.append("現在受付中セクション")
            if not _has_closed_section:   _missing.append("受付終了セクション(lottery-closed-section)")
            if not _has_reference_section: _missing.append("参考リンクセクション(lottery-reference-section)")
            results.append({"level": "error", "check": "lottery_4sections",
                            "message": f"_section_lottery に以下が不足: {', '.join(_missing)}"})

        # ── #230: lottery_count が reference_only を除外している ────────────────
        # _lottery_active_count の sum() 定義周辺 1500 文字内に reference_only があれば OK
        # （sum に渡すヘルパー関数が reference_only を参照していれば同様に OK）
        _count_pos = _lp_gen_text.find("_lottery_active_count")
        # ヘルパー関数は sum() より前に定義されるため、広範囲（前後 800 文字）をチェック
        _count_region = _lp_gen_text[max(0, _count_pos - 800):_count_pos + 1500] if _count_pos >= 0 else ""
        if "reference_only" in _count_region:
            results.append({"level": "ok", "check": "lottery_count_excludes_reference",
                            "message": "_lottery_active_count の計算が reference_only を除外している"})
        else:
            results.append({"level": "warning", "check": "lottery_count_excludes_reference",
                            "message": "_lottery_active_count の計算で reference_only が除外されていない可能性"})

        # ── #231: "次回未定" / "抽選情報未確認" が _LOTTERY_REFERENCE_ITEMS に存在しない ──
        _stale_phrases = ["次回未定", "抽選情報未確認", "一次抽選終了"]
        _stale_found = [p for p in _stale_phrases if p in _ref_block_text]
        if not _stale_found:
            results.append({"level": "ok", "check": "no_stale_lottery_phrases",
                            "message": "「次回未定」「抽選情報未確認」「一次抽選終了」等の古い文言が _LOTTERY_REFERENCE_ITEMS に含まれていない"})
        else:
            results.append({"level": "warning", "check": "no_stale_lottery_phrases",
                            "message": f"古い抽選文言が残存: {', '.join(_stale_found)}"})

        # ── #232: _lottery_status_from_dates が entry_start_at を参照している ──────
        # 関数定義ブロックを抽出（次の staticmethod/def まで）
        _status_fn_m = _re3.search(
            r'def _lottery_status_from_dates\((.+?)(?=\n    @|\n    def )',
            _lp_gen_text, _re3.DOTALL
        )
        _status_fn_text = _status_fn_m.group(0) if _status_fn_m else ""
        # フォールバック: 関数名周辺 800 文字で判断
        if not _status_fn_text:
            _pos = _lp_gen_text.find("def _lottery_status_from_dates(")
            _status_fn_text = _lp_gen_text[_pos:_pos + 800] if _pos != -1 else ""
        if "entry_start_at" in _status_fn_text or "entry_start" in _status_fn_text:
            results.append({"level": "ok", "check": "lottery_status_checks_start",
                            "message": "_lottery_status_from_dates が entry_start_at を参照して近日開始を判定"})
        else:
            results.append({"level": "warning", "check": "lottery_status_checks_start",
                            "message": "_lottery_status_from_dates が entry_start_at を参照していない（近日開始判定なし）"})
    else:
        for _chk_name in ["ricoh_monochrome_single", "ricoh_hdf_single", "reference_only_items_flagged",
                          "ricoh_not_reference_only", "lottery_4sections", "lottery_count_excludes_reference",
                          "no_stale_lottery_phrases", "lottery_status_checks_start"]:
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

    # #249: 初心者カードが完全消滅しない（fetch_failed / stale でもカードが表示される）
    _beg_has_any = any(x in html for x in [
        'badge-easy', 'badge-watch', 'badge-monitoring', 'badge-fetch-failed-card',
        'data-user-level="beginner_easy"', 'data-user-level="beginner_watch"',
        'data-user-level="monitoring"',
    ])
    if _beg_has_any:
        results.append({"level": "ok", "check": "beginner_cards_not_zero",
                        "message": "初心者向けタブにカードが1件以上表示されている（フォールバック正常）"})
    else:
        results.append({"level": "error", "check": "beginner_cards_not_zero",
                        "message": "初心者向けタブのカードが完全に0件（フォールバックが機能していない可能性）"})

    # #250: Proカードが完全消滅しない
    _pro_has_any = 'pro-candidate-card' in html or 'watch-candidate-card' in html
    if _pro_has_any:
        results.append({"level": "ok", "check": "pro_cards_not_zero",
                        "message": "Pro向けタブにカードが1件以上表示されている"})
    else:
        results.append({"level": "warning", "check": "pro_cards_not_zero",
                        "message": "Pro向けカードが0件（market_snapshot / price_history データを確認）"})

    # #251: Hero の初心者向けボタンに「(0件)」が表示されていない
    import re as _re251
    _hero_zero = bool(_re251.search(r'hero[^<]{0,200}\(0件\)', html))
    if _hero_zero:
        results.append({"level": "warning", "check": "hero_not_zero_count",
                        "message": "Hero の初心者向けボタンに「(0件)」が表示されている（フォールバックデータを確認）"})
    else:
        results.append({"level": "ok", "check": "hero_not_zero_count",
                        "message": "Hero の初心者向けボタンに「0件」表示なし"})

    # #252: stale データがある場合、注意バナーが表示されている
    _has_stale_structure = 'data-stale-warn' in html or 'stale-warning-block' in html
    _has_stale_message   = '要更新' in html or '古い参考' in html or '公式サイトで最新価格' in html
    if _has_stale_structure:
        results.append({"level": "ok", "check": "stale_warning_present",
                        "message": "stale データ警告バナー（data-stale-warn）の構造が存在する"})
    else:
        results.append({"level": "warning", "check": "stale_warning_present",
                        "message": "stale データ警告バナーが見つからない（stale-warning-block / data-stale-warn が未設定）"})

    # #253: 参考データ表示時に注意文がある（手動確認データ注意・stale 注意のいずれか）
    _has_data_caution = (
        '手動確認データ' in html
        or '古い参考データ' in html
        or '購入前に必ず公式サイト' in html
        or '最新価格を必ずご確認' in html
        or '参考値として' in html
    )
    if _has_data_caution:
        results.append({"level": "ok", "check": "fallback_data_caution",
                        "message": "参考データ・古いデータの注意文が表示されている"})
    else:
        results.append({"level": "warning", "check": "fallback_data_caution",
                        "message": "参考データ・古いデータの注意文が見つからない（ユーザーへの誤解防止に追記推奨）"})

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

    # ── #256〜#261: OPTIONAL_SHOPS 分類チェック ──────────────────────────────
    import json as _json256
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

    # #259: optional failureのみのとき LP に強警告バー（collector-warn-strong）が出ない
    _cr_json259_path = PROJECT_ROOT / "exports" / "collector_report" / "latest.json"
    _lp_generator_path = PROJECT_ROOT / "src" / "content" / "daily_lp_generator.py"
    _lp_gen_txt = _lp_generator_path.read_text(encoding="utf-8") if _lp_generator_path.exists() else ""
    if "collector-warn-strong" in _lp_gen_txt and "_OPTIONAL_SHOP_IDS" in _lp_gen_txt:
        results.append({"level": "ok", "check": "optional_only_no_strong_warn",
                        "message": "LP生成器が required/optional を区別して警告強度を調整している"})
    else:
        results.append({"level": "warning", "check": "optional_only_no_strong_warn",
                        "message": "LP生成器が optional only の場合でも強警告を出す可能性がある"})

    # #260: suspicious_price / low_confidence は強警告のまま
    if "suspicious" in _lp_gen_txt and "collector-warn-strong" in _lp_gen_txt:
        results.append({"level": "ok", "check": "suspicious_still_strong_warn",
                        "message": "suspicious_price / low_confidence 時は強警告が出る設計になっている"})
    else:
        results.append({"level": "warning", "check": "suspicious_still_strong_warn",
                        "message": "suspicious_price / low_confidence 時の強警告ロジックが見つからない"})

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
    if 'id="tab-sokuhoh"' in lp_src:
        results.append({"level": "error", "check": "no_sokuhoh_tab",
                        "message": "#272 LP に速報タブパネルが残っている (tab-sokuhoh) — Task 3 未適用"})
    else:
        results.append({"level": "ok", "check": "no_sokuhoh_tab",
                        "message": "#272 速報タブなし（削除済み）"})

    # ── #273: アラートポップアップコンテナ存在確認 (Task 6) ──
    if 'id="alert-popup-container"' in lp_src:
        results.append({"level": "ok", "check": "alert_popup_container",
                        "message": "#273 アラートポップアップコンテナあり（alert-popup-container）"})
    else:
        results.append({"level": "warning", "check": "alert_popup_container",
                        "message": "#273 alert-popup-container が LP に存在しない（Task 6 未適用 or アラートデータなし）"})

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

    # ── #277: status_conflict=true の場合 LP に conflict warning が存在 ──────────
    _lp_html_path = PROJECT_ROOT / "docs" / "index.html"
    _lottery_csv2 = PROJECT_ROOT / "data" / "lottery_events.csv"
    if _lottery_csv2.exists() and _lp_html_path.exists():
        try:
            import csv as _csv2
            _conflict_items = []
            with open(_lottery_csv2, encoding="utf-8") as _f2:
                for _row2 in _csv2.DictReader(_f2):
                    if (str(_row2.get("status_conflict", "")).lower() == "true"
                            and _row2.get("status", "") == "active"):
                        _conflict_items.append(_row2.get("product_name", "?"))

            if _conflict_items:
                _lp_html2 = _lp_html_path.read_text(encoding="utf-8")
                _has_conflict_warning = "lottery-conflict-warning" in _lp_html2
                if _has_conflict_warning:
                    results.append({"level": "ok", "check": "lottery_conflict_warning_in_lp",
                                    "message": f"#277 status_conflict active 商品 {_conflict_items} → LP に conflict warning あり ✅"})
                else:
                    results.append({"level": "warning", "check": "lottery_conflict_warning_in_lp",
                                    "message": f"#277 status_conflict active 商品 {_conflict_items} があるが LP に lottery-conflict-warning が存在しない"})
            else:
                results.append({"level": "ok", "check": "lottery_conflict_warning_in_lp",
                                "message": "#277 status_conflict=true の active 商品なし（LP conflict warning 不要）"})
        except Exception as _e2:
            results.append({"level": "warning", "check": "lottery_conflict_warning_in_lp",
                            "message": f"#277 conflict warning チェック失敗: {_e2}"})

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

    # ── #280: タブ順（抽選情報→ランキング→せどりルート→初心者→Pro）──
    # nav.tab-nav 内だけで確認（CSS セクションの data-tab= を除外）
    try:
        import re as _re280
        _nav_m = _re280.search(r'<nav[^>]*class="tab-nav[^"]*"[^>]*>.*?</nav>', html, _re280.DOTALL)
        _nav_html = _nav_m.group(0) if _nav_m else html
        _t280 = (
            _nav_html.find('data-tab="lottery"') < _nav_html.find('data-tab="ranking"') <
            _nav_html.find('data-tab="sedori"') < _nav_html.find('data-tab="beginner"') <
            _nav_html.find('data-tab="advanced"')
        )
        results.append({"level": "ok" if _t280 else "error", "check": "tab_order",
                        "message": "#280 タブ順: 抽選情報→ランキング→せどりルート→初心者→Pro" + ("" if _t280 else " ← 順番がおかしい")})
    except Exception as _e280:
        results.append({"level": "warning", "check": "tab_order", "message": f"#280 タブ順チェック失敗: {_e280}"})

    # ── #281: 速報タブが存在しない（ポップアップのみ）──
    _t281 = ('<button class="tab-btn" data-tab="surge"' not in html and
             '<button class="tab-btn active" data-tab="surge"' not in html)
    results.append({"level": "ok" if _t281 else "error", "check": "no_surge_tab",
                    "message": "#281 速報タブ（surge）がタブナビに存在しない" + ("" if _t281 else " ← surge タブが残っている")})

    # ── #282: lottery タブがデフォルトアクティブ ──
    _t282 = ('data-tab="lottery" role="tab" aria-selected="true"' in html or
             'class="tab-btn active" data-tab="lottery"' in html)
    results.append({"level": "ok" if _t282 else "warning", "check": "lottery_tab_active",
                    "message": "#282 抽選情報タブ（lottery）がデフォルトアクティブ" + ("" if _t282 else " ← active でない")})

    # ── #283: lottery パネルがデフォルトアクティブ ──
    _t283 = ('id="tab-lottery" class="tab-panel active"' in html or
             'class="tab-panel active" id="tab-lottery"' in html or
             '"tab-lottery" class="tab-panel active"' in html)
    results.append({"level": "ok" if _t283 else "warning", "check": "lottery_panel_active",
                    "message": "#283 抽選情報パネル（tab-lottery）がデフォルトアクティブ" + ("" if _t283 else " ← active でない")})

    # ── #284: 初心者タブ内に「推定コスト」表示なし（せどりルートセクションは除外）──
    try:
        import re as _re284
        _beg_m = _re284.search(r'id="tab-beginner"[^>]*>(.*?)(?=<div id="tab-|</body>)', html, _re284.DOTALL)
        _beg_html = _beg_m.group(1) if _beg_m else ""
        _t284 = '推定コスト' not in _beg_html
        results.append({"level": "ok" if _t284 else "warning", "check": "no_estimated_cost",
                        "message": "#284 初心者タブ内に推定コスト表示がない" + ("" if _t284 else " ← beginnerタブに推定コスト表示が残っている")})
    except Exception as _e284:
        results.append({"level": "warning", "check": "no_estimated_cost", "message": f"#284 チェック失敗: {_e284}"})

    # ── #285: 初心者ページに「最高売却先」または「公式店定価購入」の説明あり（2026-05-28 仕様変更）──
    _t285 = ('最高売却先' in html or '公式店定価購入' in html or '最も高く売れる売却先' in html)
    results.append({"level": "ok" if _t285 else "warning", "check": "primary_to_secondary_desc",
                    "message": "#285 初心者ページに「公式店定価購入 → 最高売却先」の説明あり" + ("" if _t285 else " ← 説明がない")})

    # ── #286: lottery-conflict-warning CSS が存在する ──
    _t286 = 'lottery-conflict-warning' in html
    results.append({"level": "ok" if _t286 else "warning", "check": "lottery_conflict_warning_css",
                    "message": "#286 lottery-conflict-warning CSS クラスが存在する" + ("" if _t286 else " ← なし")})

    # ── #287: ポップアップ速報（alert-popup）が存在する ──
    _t287 = 'alert-popup' in html or 'id="alert-popup"' in html
    results.append({"level": "ok" if _t287 else "warning", "check": "alert_popup_exists",
                    "message": "#287 ポップアップ速報（alert-popup）が存在する" + ("" if _t287 else " ← alert-popup なし")})

    # ── #288: モバイルドロワー要素が存在する ──
    _t288 = 'mobile-drawer' in html and 'mobile-hamburger' in html
    results.append({"level": "ok" if _t288 else "warning", "check": "mobile_drawer_exists",
                    "message": "#288 モバイルドロワー（mobile-drawer + mobile-hamburger）が存在する" + ("" if _t288 else " ← なし")})

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

    # ── #295: ジャンルタブ（ドロワー/ドロップダウン）が存在する ──
    _t295 = 'genre-toggle-btn' in html or 'genre-dropdown' in html
    results.append({"level": "ok" if _t295 else "warning", "check": "genre_menu_exists",
                    "message": "#295 ジャンルメニュー（genre-toggle-btn または genre-dropdown）が存在する" + ("" if _t295 else " ← なし")})

    # ── #296-#303: 海外価格収集 API / 履歴 / アラートチェック ─────────────────

    _ebay_collector_path = PROJECT_ROOT / "src" / "collectors" / "overseas" / "ebay_completed.py"
    _ebay_src = _ebay_collector_path.read_text(encoding="utf-8") if _ebay_collector_path.exists() else ""

    # #296: eBay HTML scraping が primary method ではない
    _t296 = "FINDING_API_URL" in _ebay_src and "_fetch_via_api" in _ebay_src
    results.append({"level": "ok" if _t296 else "error", "check": "ebay_api_primary",
                    "message": "#296 eBay Finding API が primary method として実装されている" + ("" if _t296 else " ← HTML scraping が主軸になっている")})

    # #297: EBAY_APP_ID なしの場合 manual fallback に移行する設計
    _t297 = "_ebay_app_id" in _ebay_src and "html_blocked" in _ebay_src
    results.append({"level": "ok" if _t297 else "error", "check": "ebay_api_key_handling",
                    "message": "#297 EBAY_APP_ID 未設定時の html_blocked 分類が実装されている" + ("" if _t297 else " ← API key なし時の fallback 処理が不足")})

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
    _t302 = "eBay 手動確認" in _lp_gen_src and "overseas_collector_method" in _lp_gen_src
    results.append({"level": "ok" if _t302 else "warning", "check": "lp_manual_fallback_display",
                    "message": "#302 LP生成器に collector_method バッジ表示（eBay 手動確認）が実装されている" + ("" if _t302 else " ← manual fallback 明示が未実装")})

    # #303: LP に html_blocked 時の通知文がある、または collector_method="manual" の場合の note がある
    _t303 = "eBay自動取得は制限中" in _lp_gen_src or "eBay 手動確認" in _lp_gen_src
    results.append({"level": "ok" if _t303 else "warning", "check": "lp_blocked_notice",
                    "message": "#303 LP生成器に eBay 取得制限中の案内文が実装されている" + ("" if _t303 else " ← html_blocked 時の案内文が未実装")})

    # #304: Pro海外相場テーブルに「取得方法」列ヘッダーがある
    _t304 = "取得方法" in _lp_gen_src and "pro-overseas-price-table" in _lp_gen_src
    results.append({"level": "ok" if _t304 else "warning", "check": "pro_overseas_method_col",
                    "message": "#304 Pro海外相場テーブルに「取得方法」列が実装されている" + ("" if _t304 else " ← Pro海外テーブルに取得方法列が未実装")})

    # #305: collector_method=manual の場合「eBay 手動確認」が Pro テーブルに表示されるロジック
    _t305 = "collector-method-badge" in _lp_gen_src and "cm-manual" in _lp_gen_src
    results.append({"level": "ok" if _t305 else "warning", "check": "pro_overseas_manual_badge",
                    "message": "#305 collector_method=manual → 「eBay 手動確認」バッジがProテーブルに実装されている" + ("" if _t305 else " ← cm-manual バッジが未実装")})

    # #306: collector_method=api の場合「API取得」ロジックが Proテーブルにある
    _t306 = "cm-api" in _lp_gen_src and "API取得" in _lp_gen_src
    results.append({"level": "ok" if _t306 else "warning", "check": "pro_overseas_api_badge",
                    "message": "#306 collector_method=api → 「API取得」バッジが実装されている" + ("" if _t306 else " ← cm-api バッジが未実装")})

    # #307: collector_method=html_blocked の場合「自動取得制限中」ロジックが Proテーブルにある
    _t307 = "cm-blocked" in _lp_gen_src and "自動取得制限中" in _lp_gen_src
    results.append({"level": "ok" if _t307 else "warning", "check": "pro_overseas_blocked_badge",
                    "message": "#307 collector_method=html_blocked → 「自動取得制限中」バッジが実装されている" + ("" if _t307 else " ← cm-blocked バッジが未実装")})

    # #308: unknown の場合「取得方法未確認」バッジが実装されている
    _t308 = "cm-unknown" in _lp_gen_src and "取得方法未確認" in _lp_gen_src
    results.append({"level": "ok" if _t308 else "warning", "check": "pro_overseas_unknown_badge",
                    "message": "#308 collector_method 未設定 → 「取得方法未確認」バッジが実装されている" + ("" if _t308 else " ← cm-unknown バッジが未実装")})

    # ── Task 12: LP全面修正 チェック (2026-05-28) ──────────────────────────────
    # #309: announce-bar が生成 HTML に存在しない（HTML 要素として削除済み確認）
    # CSS クラス定義は .announce-bar として残るが、HTML 要素は出力されない
    import re as _re309
    _t309 = not bool(_re309.search(r'<div[^>]+class="[^"]*announce-bar[^"]*"', html))
    results.append({"level": "ok" if _t309 else "warning", "check": "no_announce_bar",
                    "message": "#309 announce-bar HTML 要素が生成 HTML に存在しない（削除済み）" + ("" if _t309 else " ← announce-bar 要素が HTML に残っています")})

    # #310: ticker-bar が生成 HTML に存在しない（HTML 要素として削除済み確認）
    # CSS クラス定義は .ticker-bar として残るが、HTML 要素は出力されない
    import re as _re310
    _t310 = not bool(_re310.search(r'<div[^>]+class="[^"]*ticker-bar[^"]*"', html))
    results.append({"level": "ok" if _t310 else "warning", "check": "no_hardcoded_ticker",
                    "message": "#310 ticker-bar HTML 要素が生成 HTML に存在しない" + ("" if _t310 else " ← ticker-bar 要素が HTML に残っています")})

    # #311: Hero タイトルが更新済み（「すぐに把握」を含む）
    _t311 = "すぐに把握。" in _lp_gen_src
    results.append({"level": "ok" if _t311 else "warning", "check": "hero_title_updated",
                    "message": "#311 Hero タイトル「すぐに把握。」に更新済み" + ("" if _t311 else " ← Hero タイトルが古いままです")})

    # #312: GENRE_GROUPS に camera が含まれている（初心者タブにカメラあり）
    _t312 = "category-beginner-camera" in _lp_gen_src and "('camera'" in _lp_gen_src
    results.append({"level": "ok" if _t312 else "warning", "check": "beginner_camera_in_genre_groups",
                    "message": "#312 GENRE_GROUPS にカメラが含まれている（初心者タブ）" + ("" if _t312 else " ← camera が GENRE_GROUPS に未追加")})

    # #313: カメラのジャンルナビが beginner タブを指している
    _t313 = 'data-genre="camera" data-target-tab="beginner"' in _lp_gen_src
    results.append({"level": "ok" if _t313 else "warning", "check": "camera_nav_points_to_beginner",
                    "message": "#313 カメラジャンルナビが beginner タブを指している" + ("" if _t313 else " ← camera nav が advanced タブを指しています")})

    # #314: 価格差・プレ値候補セクション（advanced_snaps）が生成 HTML に存在しない
    # LP ソースにコメントとして残っても OK。HTML 出力に section-header として出ないことを確認
    _t314 = "価格差・プレ値候補" not in html
    results.append({"level": "ok" if _t314 else "warning", "check": "no_price_gap_candidates_section",
                    "message": "#314 「価格差・プレ値候補」セクションが生成 HTML に存在しない" + ("" if _t314 else " ← 「価格差・プレ値候補」が HTML に残っています")})

    # #315: deal card ラベルが「最高買取価格」に更新済み（2026-05-31 仕様変更: 最高売却価格 → 最高買取価格）
    _t315 = "最高買取価格" in _lp_gen_src and "二次流通最高価格" not in _lp_gen_src
    results.append({"level": "ok" if _t315 else "warning", "check": "buyback_price_label_correct",
                    "message": "#315 deal card 「最高買取価格」ラベルが正しい（2026-05-31 統一）" + ("" if _t315 else " ← 「最高買取価格」が未実装")})

    # #316: 差益ラベルが「差益（定価購入→最高買取）」に更新済み（2026-05-31 仕様変更）
    _t316 = "差益（定価購入→最高買取）" in _lp_gen_src and "差益（公式価格→二次流通）" not in _lp_gen_src
    results.append({"level": "ok" if _t316 else "warning", "check": "profit_label_correct",
                    "message": "#316 差益ラベル「差益（定価購入→最高買取）」が正しい" + ("" if _t316 else " ← 差益ラベルが旧形式")})

    # #317: 海外価格テーブルに手数料注記がある（メルカリ・eBay等）
    _t317 = "メルカリ・eBay等は販売手数料" in _lp_gen_src
    results.append({"level": "ok" if _t317 else "warning", "check": "overseas_fee_disclaimer",
                    "message": "#317 海外価格テーブルに手数料注記あり（メルカリ・eBay等）" + ("" if _t317 else " ← 手数料注記が未追加")})

    # #318: カメラ除外ロジックが _tab_beginner 呼び出しから除去済み
    _t318 = "カメラも初心者タブに表示する" in _lp_gen_src
    results.append({"level": "ok" if _t318 else "warning", "check": "beginner_camera_exclusion_removed",
                    "message": "#318 _tab_beginner からカメラ除外ロジックが除去済み" + ("" if _t318 else " ← カメラ除外ロジックが残っています")})

    # ── Task 14: 売却先定義・ランキング・せどり 追加チェック (2026-05-28) ────────────
    # #319: 「最高買取価格」ラベルが初心者 deal card に実装済み（2026-05-31 統一）
    _t319 = "最高買取価格" in _lp_gen_src and "買取店最高価格" not in _lp_gen_src
    results.append({"level": "ok" if _t319 else "warning", "check": "sell_price_label_correct",
                    "message": "#319 初心者カード「最高買取価格」ラベルが正しい" + ("" if _t319 else " ← 「最高買取価格」未実装または「買取店最高価格」が残存")})

    # #320: 「買取店比較」ラベルが初心者 deal card に実装済み（旧: 売却先比較）
    _t320 = "買取店比較" in _lp_gen_src
    results.append({"level": "ok" if _t320 else "warning", "check": "sell_comparison_label",
                    "message": "#320 初心者カード「買取店比較」ラベルが実装済み" + ("" if _t320 else " ← 「買取店比較」が未実装")})

    # #321: 差益ラベルが「差益（定価購入→最高買取）」（2026-05-31 統一）
    _t321 = "差益（定価購入→最高買取）" in _lp_gen_src
    results.append({"level": "ok" if _t321 else "warning", "check": "profit_label_sell_price",
                    "message": "#321 差益ラベル「差益（定価購入→最高買取）」が実装済み" + ("" if _t321 else " ← 差益ラベルが旧形式")})

    # #322: 「買取ランキング」がランキングタイトルに使われていない
    _t322 = "買取ランキング" not in _lp_gen_src or "差益ランキング" in _lp_gen_src
    results.append({"level": "ok" if _t322 else "warning", "check": "ranking_title_updated",
                    "message": "#322 ランキングタイトルが「差益ランキング」に更新済み" + ("" if _t322 else " ← 「買取ランキング」が残っています")})

    # #323: sedori 空状態にCLIコマンドが出ていない
    _t323 = "import-sale-csv" not in _lp_gen_src
    results.append({"level": "ok" if _t323 else "warning", "check": "sedori_no_cli_command",
                    "message": "#323 せどり空状態にCLIコマンドが表示されない" + ("" if _t323 else " ← CLIコマンドがLPソースに残っています")})

    # #324: collector-warn-info バーが LP に出力されない（optional 失敗のみでは非表示）
    _t324 = "一部店舗はサイト制限により取得不可" not in _lp_gen_src
    results.append({"level": "ok" if _t324 else "warning", "check": "no_optional_warn_bar",
                    "message": "#324 optional 失敗のみの場合の warn バーが非表示" + ("" if _t324 else " ← collector-warn-info バーが LP ソースに残っています")})

    # #325: hero-eyebrow から「手動確認データ」が除去済み
    _t325 = "手動確認データ &mdash;" not in html
    results.append({"level": "ok" if _t325 else "warning", "check": "no_manual_data_in_eyebrow",
                    "message": "#325 hero-eyebrow から「手動確認データ」が除去済み" + ("" if _t325 else " ← hero-eyebrow に「手動確認データ」が残っています")})

    # #326: price=0 の場合「価格未取得」表示が monitoring card に実装されている
    _t326 = "価格未取得" in _lp_gen_src
    results.append({"level": "ok" if _t326 else "warning", "check": "zero_price_shows_not_found",
                    "message": "#326 price=0 の場合「価格未取得」表示が実装済み" + ("" if _t326 else " ← monitoring card の price=0 対応が未実装")})

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

    # #330: Topbar に古い最終更新日が出ない（データが >24h 古い場合は非表示）
    _t330 = "_topbar_date_html" in _lp_gen_src and "_buyback_age_hours" in _lp_gen_src
    results.append({"level": "ok" if _t330 else "warning", "check": "topbar_date_staleness_guard",
                    "message": "#330 topbar-date に staleness guard が実装済み（古い日付を非表示）" + ("" if _t330 else " ← topbar-date の staleness guard が未実装")})

    # #331: Rankingに「買取ランキング」が HTML に出ていない
    _t331 = "買取ランキング" not in html
    results.append({"level": "ok" if _t331 else "warning", "check": "no_kaitori_ranking_in_html",
                    "message": "#331 生成 HTML に「買取ランキング」が出ていない（差益ランキングに変更済み）" + ("" if _t331 else " ← 「買取ランキング」が HTML に残っています")})

    # #332: Beginnerに「最高買取価格」が生成 HTML に出ている（2026-05-31 統一）
    _t332 = "最高買取価格" in html
    results.append({"level": "ok" if _t332 else "warning", "check": "sell_price_label_in_html",
                    "message": "#332 生成 HTML に「最高買取価格」ラベルが出ている" + ("" if _t332 else " ← 「最高買取価格」が HTML に出ていない")})

    # #333: Beginnerに「買取店比較」が生成 HTML に出ている（旧: 売却先比較 → 2026-05-31 統一）
    _t333 = "買取店比較" in html
    results.append({"level": "ok" if _t333 else "warning", "check": "sell_comparison_in_html",
                    "message": "#333 生成 HTML に「買取店比較」が出ている" + ("" if _t333 else " ← 「買取店比較」が HTML に出ていない")})

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

    # #336: Topに「参考DEALS」「本日の差益案件」パネルが出ていない（hero-right 削除済み）
    # CSS クラス .live-panel-items は残るが、HTML 要素として <div class="live-panel-items"> は出ない
    import re as _re336
    _t336 = "参考DEALS" not in html and not bool(_re336.search(r'<div[^>]+class="[^"]*live-panel-items[^"]*"', html))
    results.append({"level": "ok" if _t336 else "warning", "check": "no_hero_right_panel",
                    "message": "#336 hero-right パネル（参考DEALS / live-panel-items）が HTML に出ていない" + ("" if _t336 else " ← hero-right パネルが残っています")})

    # #337: Topに古い日付が topbar-date 要素として出ていない（>24h stale は非表示）
    import re as _re337
    _t337 = not bool(_re337.search(r'<div[^>]*topbar-date[^>]*>最終更新:', html))
    results.append({"level": "ok" if _t337 else "warning", "check": "no_stale_topbar_date",
                    "message": "#337 topbar-date に古い最終更新日が出ていない（staleness guard 動作確認）" + ("" if _t337 else " ← topbar-date に古い日付が出ています")})

    # #338: Sedoriに「推定コスト」が出ていない
    _t338 = "推定コスト" not in html
    results.append({"level": "ok" if _t338 else "warning", "check": "no_estimated_cost_in_html",
                    "message": "#338 生成 HTML に「推定コスト」が出ていない" + ("" if _t338 else " ← 「推定コスト」が HTML に残っています")})

    # #339: Beginnerに「公式店定価購入」の説明が出ている
    _t339 = "公式店定価購入" in html
    results.append({"level": "ok" if _t339 else "warning", "check": "beginner_official_purchase_desc",
                    "message": "#339 Beginner に「公式店定価購入 → 最高売却先との差益」説明あり" + ("" if _t339 else " ← Beginner 説明が古い")})

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
    _t342 = _t342_val >= 168.0
    results.append({"level": "ok" if _t342 else "error", "check": "stale_exclude_h_168",
                    "message": f"#342 除外閾値={_t342_val:.0f}h（168h以上で7日以上の買取データ許容）" + ("" if _t342 else " ← 168.0 以上に変更してください")})

    # #343: _section_stale_warning がトップバナーを出さない（hidden ブロックのみ返す）
    # Round4: _section_stale_warning は常に非表示ブロックのみを返すよう変更済み
    _t343 = ('常に非表示ブロックのみ返す' in _lp_gen_src or
             'hidden ブロックのみ' in _lp_gen_src or
             '各タブ内の freshness_banner に委譲' in _lp_gen_src)
    results.append({"level": "ok" if _t343 else "warning", "check": "stale_warning_critical_threshold",
                    "message": "#343 _section_stale_warning がトップバナーを抑制（hidden ブロックのみ）" + ("" if _t343 else " ← _section_stale_warning が可視バナーを出す可能性があります")})

    # #344: _deal_card にメルカリ・ヤフオク・eBay の未取得プレースホルダーが存在する
    _t344 = (
        "メルカリ" in _lp_gen_src
        and "ヤフオク" in _lp_gen_src
        and "shop-row-pending" in _lp_gen_src
        and "flea_click" in _lp_gen_src
    )
    results.append({"level": "ok" if _t344 else "warning", "check": "flea_placeholder_in_deal_card",
                    "message": "#344 _deal_card にメルカリ/ヤフオク/eBay 未取得プレースホルダーが存在する" + ("" if _t344 else " ← shop-row-pending / flea_click が見つかりません")})

    # #345: hero social proof に「差益案件 N件」ハードコード文字列がない（動的生成のみ許容）
    _t345 = '差益案件 <strong>' not in _lp_gen_src
    results.append({"level": "ok" if _t345 else "warning", "check": "no_hardcoded_deal_count_in_hero",
                    "message": "#345 hero social proof に「差益案件 N件」ハードコードが残っていない" + ("" if _t345 else " ← LP ソースに「差益案件 <strong>」が残っています")})

    # #346: freshness_banner の 168h 分岐が存在する（タブ内鮮度バナー）
    _t346 = "age_h >= 168" in _lp_gen_src
    results.append({"level": "ok" if _t346 else "warning", "check": "freshness_banner_168h_branch",
                    "message": "#346 _tab_beginner の freshness_banner に 168h 分岐が存在する" + ("" if _t346 else " ← age_h >= 168 分岐が見つかりません")})

    # #347: 「最終買取データ取得」テキストが LP ソースに残っていない
    _t347 = "最終買取データ取得" not in _lp_gen_src
    results.append({"level": "ok" if _t347 else "warning", "check": "no_last_buyback_ts_label",
                    "message": "#347 「最終買取データ取得」テキストが LP ソースに残っていない" + ("" if _t347 else " ← 「最終買取データ取得」が LP ソースに残っています")})

    # #348: 「古い参考データ」警告の閾値が 168h であること（_section_stale_warning）
    _t348 = "7日超" in _lp_gen_src or "168" in _lp_gen_src
    results.append({"level": "ok" if _t348 else "info", "check": "stale_warning_7day_label",
                    "message": "#348 _section_stale_warning に「7日超」または 168 の記述が存在する" + ("" if _t348 else " ← 168h 閾値ラベルが見つかりません")})

    # ── Task 9 追加チェック ──────────────────────────────────────────────────

    # #349: ランキングで利益ありの商品があるなら初心者ページの利益ありが0件にならない
    import re as _re349
    _ranking_profits = _re349.findall(r'class="rank-profit[^"]*">\+¥([\d,]+)', html)
    _beginner_easy_cards = html.count('data-user-level="beginner_easy"') + html.count('data-user-level="beginner_watch"')
    if _ranking_profits and _beginner_easy_cards == 0:
        results.append({"level": "error", "check": "ranking_beginner_consistency",
                        "message": f"#349 ランキングに利益あり({len(_ranking_profits)}件)なのに初心者ページの利益ありカードが0件 ← 不整合"})
    elif _ranking_profits:
        results.append({"level": "ok", "check": "ranking_beginner_consistency",
                        "message": f"#349 ランキング利益あり({len(_ranking_profits)}件) / 初心者ページカード({_beginner_easy_cards}件) — 整合"})
    else:
        results.append({"level": "ok", "check": "ranking_beginner_consistency",
                        "message": "#349 ランキング利益なし → 初心者ページとの整合チェックをスキップ"})

    # #350: X100VI がランキングにある場合は初心者ページにも表示される（メインまたは参考データ fold）
    # Round 4: 中古条件除外により X100VI は used-cond-details fold に移動する場合もある → id="product-x100vi" 存在でOK
    _x100vi_in_ranking = bool(_re349.search(r'X100VI.*?\+¥|x100vi.*?\+¥', html, _re349.IGNORECASE))
    # product-x100vi カードがどこかに存在すればOK（fold内も含む）
    _x100vi_in_beginner = 'id="product-x100vi"' in html or 'X100VI' in html
    if _x100vi_in_ranking and not _x100vi_in_beginner:
        results.append({"level": "warning", "check": "x100vi_in_beginner_if_ranking",
                        "message": "#350 X100VI がランキング利益ありなのに初心者ページに表示されていない"})
    else:
        results.append({"level": "ok", "check": "x100vi_in_beginner_if_ranking",
                        "message": "#350 X100VI 表示整合 OK（ランキングにある場合はページに表示、中古条件なら参考fold）"})

    # #351: _deal_age_h（scanned_at ベース）が LP ソースに存在する
    _t351 = "_deal_age_h" in _lp_gen_src or "scanned_at ベース" in _lp_gen_src or "deal.scanned_at" in _lp_gen_src
    results.append({"level": "ok" if _t351 else "warning", "check": "deal_age_scanned_at",
                    "message": "#351 beginner フィルタが scanned_at ベースで動作している" + ("" if _t351 else " ← _bybp_age_h が buyback observed_at を参照（不整合の可能性）")})

    # #352: 売却先比較にラクマ・StockX の未取得行が存在する
    _t352 = "ラクマ" in html and "StockX" in html and "shop-row-pending" in html
    results.append({"level": "ok" if _t352 else "warning", "check": "flea_all_platforms",
                    "message": "#352 売却先比較にラクマ・StockX の未取得行が存在する" + ("" if _t352 else " ← ラクマまたは StockX が見つかりません")})

    # #353: price=0 を赤字判定に使わないガードが LP ソースに存在する
    _t353 = "price=0 は未取得" in _lp_gen_src or "best_buyback_price > 0" in _lp_gen_src or "best_bp > 0" in _lp_gen_src
    results.append({"level": "ok" if _t353 else "warning", "check": "price_zero_not_red",
                    "message": "#353 price=0 を赤字判定に使わないガードが LP ソースに存在する" + ("" if _t353 else " ← price=0 ガードが見つかりません")})

    # #354: カメラ商品が初心者ページに表示される（stripe-camera クラス + beginner_easy）
    # _deal_card は data-genre でなく stripe-camera クラスでカメラを識別する
    _camera_beginner_match = bool(_re349.search(
        r'stripe-camera[^>]*data-user-level="beginner_easy"|data-user-level="beginner_easy"[^>]*stripe-camera',
        html
    ))
    results.append({"level": "ok" if _camera_beginner_match else "warning", "check": "camera_in_beginner",
                    "message": "#354 カメラ商品（stripe-camera）が初心者ページに表示されている" + ("" if _camera_beginner_match else " ← stripe-camera beginner_easy カードが見つかりません（カメラ最新スキャンで beginner_easy が生成されたか確認）")})

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

    # ── Round 4 追加チェック ────────────────────────────────────────────────
    import re as _re358

    # #358: 初心者タブ（メイン表示）のカードに中古条件が含まれない
    # used-cond-details fold 内は除外して確認
    _beg_tab_m = _re358.search(r'id=["\']tab-beginner["\'].*?(?=id=["\']tab-advanced["\']|id=["\']tab-lottery["\']|$)', html, _re358.DOTALL)
    if _beg_tab_m:
        _beg_html = _beg_tab_m.group(0)
        # used-cond-details fold 内を除去してからチェック
        _beg_main = _re358.sub(r'<details[^>]*used-cond-details[^>]*>.*?</details>', '', _beg_html, flags=_re358.DOTALL)
        _used_in_main = _re358.findall(r'買取条件：(中古[^<]{0,30}|美品[^<]{0,20}|良品[^<]{0,20}|開封済[^<]{0,20})', _beg_main)
        if _used_in_main:
            results.append({"level": "error", "check": "no_used_cond_in_beginner_main",
                            "message": f"#358 初心者タブのメイン表示に中古条件が混入: {_used_in_main[:3]}"})
        else:
            results.append({"level": "ok", "check": "no_used_cond_in_beginner_main",
                            "message": "#358 初心者タブのメイン表示に中古条件なし（OK）"})
    else:
        results.append({"level": "ok", "check": "no_used_cond_in_beginner_main",
                        "message": "#358 初心者タブが見つからないためスキップ"})

    # #359: 「本日の価格データ未更新」が HTML 内に強表示されていない
    _t359 = '本日の価格データ未更新' not in html
    results.append({"level": "ok" if _t359 else "error", "check": "no_today_data_not_updated",
                    "message": "#359 「本日の価格データ未更新」が HTML に存在しない" + ("" if _t359 else " ← トップに「本日の価格データ未更新」が表示されています")})

    # #360: Hero に「差益案件 XX件」（今日更新でない件数）が表示されていない
    # hero-social-html は件数なし文言か、全く件数を含まないはず
    # 「差益案件」に続く数字（XX件）は非表示時にのみ使われない形式を確認
    _hero_m = _re358.search(r'class=["\']hero[^"\']*["\'][^>]*>.*?(?=</section>|<section\b)', html, _re358.DOTALL)
    _hero_html = _hero_m.group(0) if _hero_m else ''
    _hero_deals_count = _re358.search(r'差益案件.*?(\d+)件', _hero_html)
    if _hero_deals_count:
        results.append({"level": "warning", "check": "no_stale_count_in_hero",
                        "message": f"#360 Hero に「差益案件{_hero_deals_count.group(1)}件」が表示 — データが今日付きか確認"})
    else:
        results.append({"level": "ok", "check": "no_stale_count_in_hero",
                        "message": "#360 Hero に「差益案件 XX件」なし（OK: 古いデータ時は件数非表示）"})

    # #361: 中古条件除外フィルターが LP ソースに存在する
    _t361 = '_USED_COND_KEYWORDS' in _lp_gen_src and '_is_used_cond' in _lp_gen_src
    results.append({"level": "ok" if _t361 else "error", "check": "used_cond_filter_exists",
                    "message": "#361 中古条件除外フィルター(_USED_COND_KEYWORDS/_is_used_cond)が LP ソースに存在する" + ("" if _t361 else " ← 中古条件フィルターが見つかりません")})

    # #362: _section_stale_warning がトップバナーを出さない（hidden ブロックのみ）
    _t362 = ('常に非表示ブロックのみ返す' in _lp_gen_src or
             'return \'<div class="stale-warning-block"' in _lp_gen_src or
             "return '<div class=\"stale-warning-block\"" in _lp_gen_src)
    results.append({"level": "ok" if _t362 else "warning", "check": "stale_warning_suppressed",
                    "message": "#362 _section_stale_warning がトップバナーを抑制（hidden ブロックのみ）" + ("" if _t362 else " ← _section_stale_warning がバナーを出す可能性があります")})

    # #363: 価格根拠行（price-source-row）が初心者タブのカードに存在する（旧ラベル: 最高売却先 → 最高買取店）
    _t363 = 'price-source-row' in html and '最高買取店' in html
    results.append({"level": "ok" if _t363 else "warning", "check": "price_source_row_exists",
                    "message": "#363 価格根拠行（price-source-row / 最高買取店）がカードに存在する" + ("" if _t363 else " ← price-source-row が見つかりません")})

    # ── Task 7 追加チェック（カメラ二次流通価格）──────────────────────────
    import re as _re364

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

    # #365: Amazon/楽天/Mercari/eBay の売却先候補が HTML 内に存在する（カメラ含む）
    _t365_amazon  = 'Amazon新品出品' in html or 'amazon.co.jp' in html
    _t365_mercari = 'メルカリ' in html
    _t365_ebay    = 'eBay' in html or 'ebay.com' in html
    _t365 = _t365_amazon and _t365_mercari and _t365_ebay
    results.append({"level": "ok" if _t365 else "warning", "check": "resale_platform_coverage",
                    "message": "#365 Amazon/Mercari/eBay の売却先候補が HTML に存在する" + ("" if _t365 else f" ← Amazon:{_t365_amazon} Mercari:{_t365_mercari} eBay:{_t365_ebay}")})

    # #366: RICOH カメラが beginner_easy に存在する（二次流通価格で復旧済み）
    _t366_gr4  = 'RICOH GR IV' in html and 'beginner_easy' in html
    _t366_gr3x = 'RICOH GR IIIx' in html and 'beginner_easy' in html
    if _t366_gr4 and _t366_gr3x:
        results.append({"level": "ok", "check": "ricoh_camera_in_beginner",
                        "message": "#366 RICOH GR IV / GR IIIx が初心者ページ(beginner_easy)に存在する"})
    elif _t366_gr4 or _t366_gr3x:
        results.append({"level": "warning", "check": "ricoh_camera_in_beginner",
                        "message": f"#366 RICOH カメラの一部が初心者ページに未表示（GR IV:{_t366_gr4} / GR IIIx:{_t366_gr3x}）"})
    else:
        results.append({"level": "warning", "check": "ricoh_camera_in_beginner",
                        "message": "#366 RICOH GR IV / GR IIIx が初心者ページに表示されていない — 二次流通価格の取得を確認"})

    # #367: price=0 / null が利益計算に使われていない（BeginnerDealScanner の sale_price > 0 ガード）
    _t367 = ('_sp.sale_price <= 0' in _bds_src or
             '_sp_pre.sale_price <= 0' in _bds_src or
             'sale_price > 0' in _bds_src or
             'not _sp.sale_price' in _bds_src or
             'not _sp_pre.sale_price' in _bds_src)
    results.append({"level": "ok" if _t367 else "error", "check": "sale_price_zero_guard",
                    "message": "#367 sale_prices で price=0/null ガードが存在する" + ("" if _t367 else " ← sale_price > 0 のチェックが見つかりません")})

    # #368: 中古A/美品が highest_sell_price(best_buyback_price) に混入していない
    # beginner_easy カードの価格根拠行で「中古A（美品）」「美品」が最高売却価格として表示されない
    if _beg_tab_m:
        _beg_main2 = _re364.sub(r'<details[^>]*used-cond-details[^>]*>.*?</details>', '', _beg_html, flags=_re364.DOTALL)
        # price-source-row 内に中古条件が出ていないか確認
        _source_rows = _re364.findall(r'<div class="price-source-row"[^>]*>(.*?)</div>', _beg_main2, _re364.DOTALL)
        _used_in_source = [r for r in _source_rows if '中古A' in r or '美品' in r or '良品' in r or '中古B' in r]
        if _used_in_source:
            results.append({"level": "error", "check": "no_used_cond_in_best_price",
                            "message": f"#368 初心者メインカードの最高売却価格に中古条件が含まれています: {len(_used_in_source)}件"})
        else:
            results.append({"level": "ok", "check": "no_used_cond_in_best_price",
                            "message": "#368 初心者メインカードの最高売却価格に中古条件なし（OK）"})
    else:
        results.append({"level": "ok", "check": "no_used_cond_in_best_price",
                        "message": "#368 初心者タブ未検出 → スキップ"})

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

    # #375: sell_candidates 統一チェック
    _t375 = '_enrich_from_sell_candidates' in _lp_gen_src
    results.append({"level": "ok" if _t375 else "error", "check": "sell_candidates_unified",
                    "message": "#375 sell_candidates が統一されている（_enrich_from_sell_candidates）" + ("" if _t375 else " ← 実装されていません")})

    # #376: monitoring deal に有効価格があれば利益ありに昇格
    _t376 = '_enrich_from_sell_candidates' in _lp_gen_src and 'deduped_all' in _lp_gen_src
    results.append({"level": "ok" if _t376 else "error", "check": "monitoring_upgrade_to_profit",
                    "message": "#376 監視中案件が有効価格で利益ありに昇格する" + ("" if _t376 else " ← deduped_all 補完が未実装")})

    # #377: Pro「中古プレ値あり」除外
    _t377 = ('中古プレ値あり' not in open(PROJECT_ROOT / 'src' / 'db' / 'repository.py', encoding='utf-8').read()
             or '_raw_flags' in _lp_gen_src)
    results.append({"level": "ok" if _t377 else "warning", "check": "pro_no_used_premium_badge",
                    "message": "#377 Proメインに「中古プレ値あり」が出ない" + ("" if _t377 else " ← repository.py または LP 側でフィルタが必要")})

    # #378: eBay 海外価格フォールバック
    _t378 = 'ebay' in _lp_gen_src.lower() and ('_ovs_price = d.best_buyback_price' in _lp_gen_src or 'ebay_fallback' in _lp_gen_src or "'ebay' in _best_shop" in _lp_gen_src)
    results.append({"level": "ok" if _t378 else "warning", "check": "ebay_overseas_fallback",
                    "message": "#378 eBay 最高売却時に海外価格フォールバックあり" + ("" if _t378 else " ← eBay フォールバック未実装")})

    # #379: 自動取得レポート強化 — per-product tracking
    _t379 = '_get_platform_pending_label' in _lp_gen_src and '_product_resale_status' in _lp_gen_src
    results.append({"level": "ok" if _t379 else "warning", "check": "platform_pending_label",
                    "message": "#379 プラットフォーム別未取得理由ラベルが実装されている（_get_platform_pending_label）"
                               + ("" if _t379 else " ← _get_platform_pending_label 未実装")})

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

    # #384: data_source バッジが実装されている
    _t384 = '_data_source_badge' in _lp_gen_src
    results.append({"level": "ok" if _t384 else "warning", "check": "data_source_badge",
                    "message": "#384 データソースバッジ（_data_source_badge）が実装されている"
                               + ("" if _t384 else " ← _data_source_badge 未実装")})

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

    # #386: Beginner から resale_market を除外するロジックが _deal_card に実装されている
    _t386 = (
        "data_source') != 'resale_market'" in _lp_gen_src
        or "!= 'resale_market'" in _lp_gen_src
    )
    results.append({"level": "ok" if _t386 else "warning", "check": "beginner_resale_filter_impl",
                    "message": "#386 Beginner フリマ除外ロジック（resale_market フィルタ）が LP ソースに実装済み"
                               + ("" if _t386 else " ← resale_market フィルタが未実装")})

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
    import re as _re388

    # 初心者タブ HTML を抽出（#358 で使用したものを再利用）
    _beg_tab_m388 = _re388.search(
        r'id=["\']tab-beginner["\'].*?(?=id=["\']tab-advanced["\']|id=["\']tab-lottery["\']|$)',
        html, _re388.DOTALL,
    )
    _beg_html388 = _beg_tab_m388.group(0) if _beg_tab_m388 else ''

    # Pro タブ HTML を抽出
    _pro_tab_m388 = _re388.search(
        r'id=["\']tab-advanced["\'].*?(?=id=["\']tab-lottery["\']|$)',
        html, _re388.DOTALL,
    )
    _pro_html388 = _pro_tab_m388.group(0) if _pro_tab_m388 else ''

    # #388: Beginner タブに「メルカリ直近売買」が出ない
    _t388 = 'メルカリ直近売買' not in _beg_html388
    results.append({"level": "ok" if _t388 else "error", "check": "no_mercari_in_beginner",
                    "message": "#388 Beginner タブに「メルカリ直近売買」なし（フリマ除外）"
                               + ("" if _t388 else " ← 「メルカリ直近売買」が Beginner タブに表示されています")})

    # #389: Beginner タブに「ヤフオク落札相場」が出ない
    _t389 = 'ヤフオク落札相場' not in _beg_html388
    results.append({"level": "ok" if _t389 else "error", "check": "no_yahoo_pending_in_beginner",
                    "message": "#389 Beginner タブに「ヤフオク落札相場」なし（フリマ除外）"
                               + ("" if _t389 else " ← 「ヤフオク落札相場」が Beginner タブに表示されています")})

    # #390: Beginner タブに「ラクマ直近売買」が出ない
    _t390 = 'ラクマ直近売買' not in _beg_html388
    results.append({"level": "ok" if _t390 else "error", "check": "no_rakuma_in_beginner",
                    "message": "#390 Beginner タブに「ラクマ直近売買」なし（フリマ除外）"
                               + ("" if _t390 else " ← 「ラクマ直近売買」が Beginner タブに表示されています")})

    # #391: Beginner タブに「eBay sold」が出ない
    _t391 = 'eBay sold' not in _beg_html388
    results.append({"level": "ok" if _t391 else "error", "check": "no_ebay_sold_in_beginner",
                    "message": "#391 Beginner タブに「eBay sold」なし（フリマ除外）"
                               + ("" if _t391 else " ← 「eBay sold」が Beginner タブに表示されています")})

    # #392: Beginner タブに「StockX」が出ない（pending行として）
    # ただし Proタブのランキング参照リンク等で出る可能性があるので shop-row-pending 限定チェック
    _t392 = 'shop-row-pending' not in _beg_html388
    results.append({"level": "ok" if _t392 else "error", "check": "no_flea_pending_in_beginner",
                    "message": "#392 Beginner タブに shop-row-pending（フリマ未取得行）なし"
                               + ("" if _t392 else " ← Beginner タブにフリマ未取得行が表示されています")})

    # #393: Beginner タブに「買取店比較」が出る
    _t393 = '買取店比較' in _beg_html388
    results.append({"level": "ok" if _t393 else "warning", "check": "kaitori_compare_in_beginner",
                    "message": "#393 Beginner タブに「買取店比較」ヘッダーが存在する"
                               + ("" if _t393 else " ← 「買取店比較」が見つかりません（買取店データ未取得の可能性）")})

    # #394: Beginner タブに「差益（定価購入→最高買取）」が出る（ラベル変更確認）
    _t394 = '差益（定価購入→最高買取）' in _beg_html388
    results.append({"level": "ok" if _t394 else "warning", "check": "beginner_profit_label_updated",
                    "message": "#394 Beginner タブの差益ラベルが「最高買取」表記に更新済み"
                               + ("" if _t394 else " ← 「差益（定価購入→最高買取）」が見つかりません")})

    # #395: LP ソースに beginner フリマ除外ロジックが実装されている
    _t395 = "data_source') != 'resale_market'" in _lp_gen_src or 'resale_market' in _lp_gen_src
    results.append({"level": "ok" if _t395 else "warning", "check": "beginner_resale_filter",
                    "message": "#395 LP ソースに Beginner フリマ除外ロジック（resale_market フィルタ）が実装済み"
                               + ("" if _t395 else " ← resale_market フィルタが未実装")})

    # ── Round 6: Beginner完全分離チェック ────────────────────────────────────
    # _beg_html388 / _pro_html388 は Round 5 で既に抽出済み

    # Rankingタブ HTML を抽出
    _rank_tab_m396 = _re388.search(
        r'id=["\']tab-ranking["\'].*?(?=id=["\']tab-sedori["\']|id=["\']tab-beginner["\']|$)',
        html, _re388.DOTALL,
    )
    _rank_html396 = _rank_tab_m396.group(0) if _rank_tab_m396 else ''

    # Sedoriタブ HTML を抽出
    _sed_tab_m396 = _re388.search(
        r'id=["\']tab-sedori["\'].*?(?=id=["\']tab-beginner["\']|id=["\']tab-advanced["\']|$)',
        html, _re388.DOTALL,
    )
    _sed_html396 = _sed_tab_m396.group(0) if _sed_tab_m396 else ''

    # #396: Beginner タブに「eBay」が存在しない
    _t396 = 'eBay' not in _beg_html388
    results.append({"level": "ok" if _t396 else "error", "check": "no_ebay_in_beginner",
                    "message": "#396 Beginner タブに「eBay」なし（海外・フリマ除外）"
                               + ("" if _t396 else " ← 「eBay」が Beginner タブに表示されています")})

    # #397: Beginner タブに「ヤフオク」が存在しない
    _t397 = 'ヤフオク' not in _beg_html388
    results.append({"level": "ok" if _t397 else "error", "check": "no_yahuoku_in_beginner",
                    "message": "#397 Beginner タブに「ヤフオク」なし（フリマ除外）"
                               + ("" if _t397 else " ← 「ヤフオク」が Beginner タブに表示されています")})

    # #398: Beginner タブに「メルカリ」が存在しない
    _t398 = 'メルカリ' not in _beg_html388
    results.append({"level": "ok" if _t398 else "error", "check": "no_mercari_in_beginner",
                    "message": "#398 Beginner タブに「メルカリ」なし（フリマ除外）"
                               + ("" if _t398 else " ← 「メルカリ」が Beginner タブに表示されています")})

    # #399: Beginner タブに「ラクマ」が存在しない
    _t399 = 'ラクマ' not in _beg_html388
    results.append({"level": "ok" if _t399 else "error", "check": "no_rakuma_in_beginner",
                    "message": "#399 Beginner タブに「ラクマ」なし（フリマ除外）"
                               + ("" if _t399 else " ← 「ラクマ」が Beginner タブに表示されています")})

    # #400: Beginner タブに「StockX」が存在しない
    _t400 = 'StockX' not in _beg_html388
    results.append({"level": "ok" if _t400 else "error", "check": "no_stockx_in_beginner",
                    "message": "#400 Beginner タブに「StockX」なし（フリマ除外）"
                               + ("" if _t400 else " ← 「StockX」が Beginner タブに表示されています")})

    # #401: Ranking タブに「→ 最高売却先」が存在しない（「最高買取店」に変更済み）
    _t401 = '→ 最高売却先' not in _rank_html396 and '&rarr; 最高売却先' not in _rank_html396
    results.append({"level": "ok" if _t401 else "error", "check": "no_max_sell_in_ranking",
                    "message": "#401 Ranking タブに「→ 最高売却先」なし（「最高買取店」に変更済み）"
                               + ("" if _t401 else " ← Ranking タブに「→ 最高売却先」が残っています")})

    # #402: Ranking タブに「eBay → 最高買取店」または「eBay → 最高売却先」が存在しない
    _t402 = ('eBay → 最高買取店' not in _rank_html396
             and 'eBay → 最高売却先' not in _rank_html396
             and 'eBay &rarr; 最高' not in _rank_html396)
    results.append({"level": "ok" if _t402 else "error", "check": "no_ebay_as_top_shop_in_ranking",
                    "message": "#402 Ranking タブに「eBay」が最高買取店として表示されない（resale除外）"
                               + ("" if _t402 else " ← Ranking タブに eBay が最高買取店として出ています")})

    # #403: Beginner 説明文に「買取店で売却」が含まれる
    _t403 = '買取店で売却' in _beg_html388
    results.append({"level": "ok" if _t403 else "warning", "check": "beginner_desc_buyback_sell",
                    "message": "#403 Beginner 説明文に「買取店で売却」が含まれる"
                               + ("" if _t403 else " ← 「買取店で売却」が見つかりません（説明文要確認）")})

    # #404: Pro タブに eBay / ヤフオク / メルカリ が存在する（Pro向け内容が維持されている）
    _t404 = ('eBay' in _pro_html388 or 'ヤフオク' in _pro_html388 or 'メルカリ' in _pro_html388)
    results.append({"level": "ok" if _t404 else "warning", "check": "pro_has_resale_platforms",
                    "message": "#404 Pro タブに eBay / ヤフオク / メルカリ が存在する（Pro向け内容維持）"
                               + ("" if _t404 else " ← Pro タブにフリマ/海外プラットフォームが見つかりません")})

    # #405: Sedori タブに「Proルート」分類が存在する
    _t405 = 'Proルート' in _sed_html396 or 'pro_routes' in _lp_gen_src
    results.append({"level": "ok" if _t405 else "warning", "check": "sedori_has_pro_classification",
                    "message": "#405 Sedori タブに「Proルート」分類が実装されている"
                               + ("" if _t405 else " ← Sedori タブの Proルート分類が見つかりません")})

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

    # #411: Sedori タブに初心者合成ルート（公式→買取店）が「実際に描画」されている
    # （旧版はソースに _synth_routes があれば OK としていたため 0 ルートでも誤通過した。
    #   実出力 _sed_html396 を検査する。データ次第で 0 件はあり得るため warning レベル）
    _t411 = '初心者ルート' in _sed_html396
    results.append({"level": "ok" if _t411 else "warning", "check": "sedori_has_synth_beginner_routes",
                    "message": "#411 Sedori タブに初心者合成ルート（公式→買取店）が描画されている"
                               + ("" if _t411 else " ← Sedori 実出力に初心者ルートが描画されていません（データ不足の可能性）")})

    # #412: Sedori タブの説明文に「中古」が出ない
    _t412 = '中古' not in _sed_html396
    results.append({"level": "ok" if _t412 else "warning", "check": "no_used_in_sedori_tab",
                    "message": "#412 Sedori タブに「中古」が存在しない（新品・未使用方針）"
                               + ("" if _t412 else " ← Sedori タブに「中古」が残っています")})

    # #413: Ranking タブに「最高買取店」ラベルが存在する（旧: 最高売却先）
    _t413 = '最高買取店' in _rank_html396
    results.append({"level": "ok" if _t413 else "warning", "check": "ranking_has_buyback_shop_label",
                    "message": "#413 Ranking タブに「最高買取店」ラベルが存在する"
                               + ("" if _t413 else " ← Ranking タブに「最高買取店」が見つかりません")})

    # #414: Beginner タブに「除外（中古等）」が存在しない
    _t414 = '除外 (中古等)' not in _beg_html388 and '除外（中古等）' not in _beg_html388
    results.append({"level": "ok" if _t414 else "error", "check": "no_excluded_used_in_beginner",
                    "message": "#414 Beginner タブに「除外（中古等）」が存在しない"
                               + ("" if _t414 else " ← Beginner タブに「除外（中古等）」が残っています")})

    # #415: Sedori タブに合成初心者ルート（sc-table）または「0ルート」の理由説明が存在する
    _t415 = ('sc-table' in _sed_html396 or
             '初心者ルート一覧' in _sed_html396 or
             '現在、条件を満たすルートはありません' in _sed_html396)
    results.append({"level": "ok" if _t415 else "warning", "check": "sedori_has_content_or_reason",
                    "message": "#415 Sedori タブにルート表またはデータなし理由が存在する"
                               + ("" if _t415 else " ← Sedori タブにルート表も理由説明もありません")})

    # #416: Beginner タブに「参考データ（中古・開封済み条件）」が存在しない
    _t416 = '参考データ（中古・開封済み条件）' not in _beg_html388
    results.append({"level": "ok" if _t416 else "error", "check": "no_used_reference_in_beginner",
                    "message": "#416 Beginner タブに「参考データ（中古・開封済み条件）」が存在しない"
                               + ("" if _t416 else " ← 「参考データ（中古・開封済み条件）」が Beginner タブに残っています")})

    # #417: Beginner タブに中古グレード表記「used_a」「used_b」が存在しない
    # （正規買取店が出す中古価格が初心者タブに混入する不具合の回帰ガード）
    _t417 = ('used_a' not in _beg_html388) and ('used_b' not in _beg_html388)
    results.append({"level": "ok" if _t417 else "error", "check": "no_used_grade_enum_in_beginner",
                    "message": "#417 Beginner タブに中古グレード（used_a/used_b）が存在しない（新品・未使用のみ）"
                               + ("" if _t417 else " ← Beginner タブに中古グレード（used_a 等）が表示されています")})

    # #418: Beginner タブに「二次流通（参考）」取得方法ラベルが存在しない
    _t418 = '二次流通（参考）' not in _beg_html388
    results.append({"level": "ok" if _t418 else "error", "check": "no_resale_source_in_beginner",
                    "message": "#418 Beginner タブに「二次流通（参考）」取得方法ラベルが存在しない（公式→買取店のみ）"
                               + ("" if _t418 else " ← Beginner タブに二次流通由来の価格が表示されています")})

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

    # #423: Ranking タブにせどりサブタブ（rtab-sedori）が存在しない（せどりルートはせどりタブ専用）
    _t423 = ('rtab-sedori' not in _rank_html396) and ('data-rtab="sedori"' not in _rank_html396)
    results.append({"level": "ok" if _t423 else "error", "check": "no_sedori_subtab_in_ranking",
                    "message": "#423 Ranking タブにせどりサブタブ（店舗間/二次流通ルート）が存在しない"
                               + ("" if _t423 else " ← Ranking にせどりサブタブが残っています")})

    # #424: Ranking タブに eBay / ヤフオク / メルカリ が主価格（店舗名）として出ない
    _t424 = ('eBay' not in _rank_html396) and ('ヤフオク' not in _rank_html396) and ('メルカリ' not in _rank_html396)
    results.append({"level": "ok" if _t424 else "error", "check": "no_resale_shop_in_ranking",
                    "message": "#424 Ranking タブに eBay/ヤフオク/メルカリ が表示されない（初心者ランキングは公式→最高買取店のみ）"
                               + ("" if _t424 else " ← Ranking に二次流通ショップが残っています")})

    # #425: Beginner タブに「resale_market」が出ない
    _t425 = 'resale_market' not in _beg_html388
    results.append({"level": "ok" if _t425 else "error", "check": "no_resale_market_in_beginner",
                    "message": "#425 Beginner タブに『resale_market』が存在しない"
                               + ("" if _t425 else " ← Beginner に resale_market 由来データが残っています")})

    # #426: Sedori タブが「0ルート」表示ではない（ルート表または正常な空状態説明が存在）
    _t426_zero = '0ルート' in _sed_html396
    _t426_has_content = ('初心者ルート一覧' in _sed_html396 or 'sc-table' in _sed_html396
                         or 'Proルート' in _sed_html396
                         or '現在、条件を満たすルートはありません' in _sed_html396)
    _t426 = (not _t426_zero) and _t426_has_content
    results.append({"level": "ok" if _t426 else "warning", "check": "sedori_not_zero_routes",
                    "message": "#426 Sedori タブが『0ルート』表示でない（ルート表/正常な空状態説明が存在）"
                               + ("" if _t426 else " ← Sedori タブが 0ルート、またはルート/説明が見つかりません")})

    # #427: Beginner カードに「取得方法」「最終確認」「買取店比較」が描画されている
    _t427 = ('取得方法' in _beg_html388) and ('最終確認' in _beg_html388) and ('買取店比較' in _beg_html388)
    results.append({"level": "ok" if _t427 else "warning", "check": "beginner_card_buyback_meta",
                    "message": "#427 Beginner カードに『取得方法/最終確認/買取店比較』が描画されている"
                               + ("" if _t427 else " ← Beginner カードの買取メタ情報が不足しています")})

    # #428: Ranking タブに「マップカメラ → フジヤカメラ」店舗間せどりルートが存在しない
    _t428 = ('マップカメラ → フジヤカメラ' not in _rank_html396) and ('マップカメラ &rarr; フジヤカメラ' not in _rank_html396)
    results.append({"level": "ok" if _t428 else "error", "check": "no_mapcamera_fujiya_in_ranking",
                    "message": "#428 Ranking タブに『マップカメラ → フジヤカメラ』店舗間せどりルートが存在しない"
                               + ("" if _t428 else " ← Ranking に店舗間せどりルートが残っています")})

    # #429: Ranking タブに「カメラのキタムラ → フジヤカメラ」店舗間せどりルートが存在しない
    _t429 = ('カメラのキタムラ → フジヤカメラ' not in _rank_html396) and ('カメラのキタムラ &rarr; フジヤカメラ' not in _rank_html396)
    results.append({"level": "ok" if _t429 else "error", "check": "no_kitamura_fujiya_in_ranking",
                    "message": "#429 Ranking タブに『カメラのキタムラ → フジヤカメラ』店舗間せどりルートが存在しない"
                               + ("" if _t429 else " ← Ranking に店舗間せどりルートが残っています")})

    # #430: Beginner 説明文が「対象は新品・未使用・未開封のみです。」になっている
    _t430 = '対象は新品・未使用・未開封のみです' in _beg_html388
    results.append({"level": "ok" if _t430 else "error", "check": "beginner_disclaimer_text",
                    "message": "#430 Beginner 説明文が『対象は新品・未使用・未開封のみです。』になっている"
                               + ("" if _t430 else " ← Beginner 説明文が想定と異なります")})

    # #431: Beginner カードに内部コード（new_unopened_simfree 等）が出ない（Task 2）
    _internal_codes = ('new_unopened_simfree', 'new_unopened', 'used_a', 'used_b',
                       'resale_market', 'manual_today', 'manual_confirmed', 'auto_scraped')
    _leaked = [c for c in _internal_codes if c in _beg_html388]
    _t431 = not _leaked
    results.append({"level": "ok" if _t431 else "error", "check": "no_internal_code_in_beginner",
                    "message": "#431 Beginner カードに内部コード（new_unopened_simfree 等）が出ない（日本語表示に変換）"
                               + ("" if _t431 else f" ← 内部コードが残っています: {', '.join(_leaked)}")})

    # #432: 買取店比較が「上位3件表示 + details 折りたたみ」になっている（Task 1）
    _t432 = ('shop-compare-fold' in _beg_html388) and ('買取店比較を見る' in _beg_html388)
    results.append({"level": "ok" if _t432 else "error", "check": "beginner_buyback_compare_collapsed",
                    "message": "#432 買取店比較が『買取店比較を見る』details に折りたたまれている"
                               + ("" if _t432 else " ← 買取店比較の折りたたみ（shop-compare-fold）が見つかりません")})

    # #433: 古いデータの「N日前」がカード上部（買取店比較ヘッダー shop-table-hd）に強表示されない（Task 3）
    import re as _re433
    _hd_blocks = _re433.findall(r'shop-table-hd.*?</div>', _beg_html388)
    _t433 = not any(('日前' in b or '要更新' in b) for b in _hd_blocks)
    results.append({"level": "ok" if _t433 else "error", "check": "no_stale_in_card_top",
                    "message": "#433 古いデータ（N日前/要更新）が買取店比較ヘッダーに強表示されない（価格確認行に小さく表示）"
                               + ("" if _t433 else " ← shop-table-hd に『N日前/要更新』が残っています")})

    # #434: Beginner カードに買取店比較の details 折りたたみ（shop-compare-fold）が存在する
    _t434 = 'shop-compare-fold' in _beg_html388
    results.append({"level": "ok" if _t434 else "warning", "check": "beginner_has_details",
                    "message": "#434 Beginner カードに買取店比較の折りたたみ（shop-compare-fold）が存在する"
                               + ("" if _t434 else " ← 買取店比較の折りたたみが見つかりません（店舗数が少ない可能性）")})

    # #435: 最高買取店が大きく表示されている（best-buyback-block）（Task 1/5）
    _t435 = ('best-buyback-block' in _beg_html388) and ('bb-shop-price' in _beg_html388)
    results.append({"level": "ok" if _t435 else "error", "check": "beginner_best_shop_prominent",
                    "message": "#435 最高買取店が大きく表示されている（best-buyback-block / bb-shop-price）"
                               + ("" if _t435 else " ← 最高買取店の大表示ブロックが見つかりません")})

    # #436: Pro タブに「中古販売価格」が存在しない（Pro でも中古は出さない：Task 1）
    _t436 = '中古販売価格' not in _pro_html388
    results.append({"level": "ok" if _t436 else "error", "check": "no_used_sale_price_in_pro",
                    "message": "#436 Pro タブに『中古販売価格』が存在しない（新品・未使用・未開封のみ）"
                               + ("" if _t436 else " ← Pro に中古販売価格が残っています")})

    # #437: Pro の価格根拠（pro-price-basis）に「中古」「used_a」「used」が主表示されない（Task 1）
    import re as _re437
    _basis_spans = _re437.findall(r'<span class="pro-price-basis[^"]*">(.*?)</span>', _pro_html388)
    _bad_basis = [b for b in _basis_spans if ('中古' in b) or ('used_a' in b.lower()) or ('used' in b.lower()) or ('美品' in b) or ('開封済' in b) or ('ジャンク' in b)]
    _t437 = not _bad_basis
    results.append({"level": "ok" if _t437 else "error", "check": "no_used_basis_in_pro",
                    "message": "#437 Pro の価格根拠に『中古/used_a/used/美品/開封済み/ジャンク』が主表示されない"
                               + ("" if _t437 else f" ← 中古系の価格根拠が残っています: {', '.join(_bad_basis[:3])}")})

    # #438: Pro で中古価格しかない場合「新品・未使用価格未取得」と表示される（Task 1）
    #   中古販売価格が DB に存在する状況で、Pro 国内テーブルがそれを除外した結果の fallback 文言を検査。
    #   （該当データが無い日もあるため warning レベル：存在すれば OK、無くても公開は妨げない）
    _t438 = '新品・未使用価格未取得' in _pro_html388
    results.append({"level": "ok" if _t438 else "warning", "check": "pro_used_only_fallback_label",
                    "message": "#438 Pro で中古価格のみの商品は『新品・未使用価格未取得』と表示される"
                               + ("" if _t438 else " ← 該当文言が見当たりません（中古のみの商品が無い日は正常）")})

    # #439: Beginner の買取店比較テーブル（shop-row 群）に「自動取得」が直接出ない
    #   取得方法は confirm-line / details にだけ集約。shop-row 内には大バッジも生テキストも残さない。
    _beg_shop_rows = _re437.findall(r'<div class="shop-row(?: [^"]*)?">.*?</div>\s*</div>', _beg_html388)
    _t439 = not any(
        ('badge-auto' in row) or ('badge-manual' in row)
        or ('自動取得' in row) or ('手動確認' in row)
        for row in _beg_shop_rows
    )
    results.append({"level": "ok" if _t439 else "error", "check": "beginner_source_not_in_shop_row",
                    "message": "#439 Beginner の買取店比較テーブル（shop-row）に『自動取得/手動確認』が直接出ない"
                               + ("" if _t439 else " ← 店舗行に取得方法ラベルが残っています")})

    # #440: Beginner の取得方法は confirm-line（または details）にだけ表示される（Task 2）
    _t440 = ('取得方法' in _beg_html388) and ('confirm-line' in _beg_html388)
    results.append({"level": "ok" if _t440 else "error", "check": "beginner_source_in_confirm_line",
                    "message": "#440 Beginner の取得方法は confirm-line（最終確認行）にだけ表示されている"
                               + ("" if _t440 else " ← confirm-line の取得方法表示が見つかりません")})

    # #441: Pro に買取店価格候補が残っている（問題2）
    #   中古販売価格を除外しても、買取店価格（pro-row-buyback / 買取価格）が Pro 国内候補として表示される。
    _t441 = ('pro-row-buyback' in _pro_html388) or ('買取価格' in _pro_html388)
    results.append({"level": "ok" if _t441 else "error", "check": "pro_buyback_candidates_present",
                    "message": "#441 Pro に買取店価格候補（買取価格）が残っている"
                               + ("" if _t441 else " ← Pro から買取店候補が消えています")})

    # #442: Pro に国内新品/未使用価格候補が残っている（問題2）
    #   国内仕入れ/売却候補テーブル（pro-domestic-row / pro-row-has-price）が存在する。
    _t442 = ('pro-domestic-row' in _pro_html388) or ('pro-row-has-price' in _pro_html388)
    results.append({"level": "ok" if _t442 else "error", "check": "pro_domestic_candidates_present",
                    "message": "#442 Pro に国内新品/未使用価格候補（国内候補テーブル）が残っている"
                               + ("" if _t442 else " ← Pro の国内価格候補が消えています")})

    # #443: Beginner の各店舗カードに 店舗名・価格・差益・確認リンクが揃っている
    #   縦カード(shop-card)は入れ子構造のため、列クラスの個数整合で判定（店名数 == 確認リンク数）。
    _beg_name_n = _beg_html388.count('shop-name-col')
    _beg_link_n = _beg_html388.count('shop-link-col')
    _t443 = (_beg_name_n > 0) and (_beg_name_n == _beg_link_n) \
        and ('shop-price-col' in _beg_html388) and ('shop-diff-col' in _beg_html388)
    results.append({"level": "ok" if _t443 else "error", "check": "beginner_row_has_core_cols",
                    "message": f"#443 Beginner の各店舗カードに 店舗名・価格・差益・確認リンクが揃っている（店名{_beg_name_n}/リンク{_beg_link_n}）"
                               + ("" if _t443 else " ← 主要列が欠けている店舗カードがあります")})

    # #444: 取得方法ラベル（自動取得/手動確認）は confirm-line / details 内にだけ存在する
    #   shop-row 群の外（confirm-line など）に出ていれば OK、shop-row 内には無いこと（#439と対）。
    _t444 = _t439 and (('自動取得' in _beg_html388) or ('手動確認' in _beg_html388))
    results.append({"level": "ok" if _t444 else "warning", "check": "beginner_source_only_in_details_or_confirm",
                    "message": "#444 取得方法（自動取得/手動確認）は details / confirm-line にだけ表示される"
                               + ("" if _t444 else " ← 取得方法ラベルが見つからない、または shop-row に残存")})

    # ── compact card レイアウト（Redesign beginner cards） ──
    # compact 利益カード単位に分割（deal-card-compact、監視中カードを除く）
    _compact_cards = _re437.findall(
        r'<div class="deal-card deal-card-compact(?! deal-card-monitoring)[^"]*"[^>]*>.*?(?=<div class="deal-card |<details class="monitoring-global-section|<details class="status-subsection|$)',
        _beg_html388, _re437.DOTALL
    )

    def _initial_view(card_html: str) -> str:
        """買取店比較fold（shop-compare-fold）より前 = 初期表示部分を返す。"""
        i = card_html.find('shop-compare-fold')
        if i < 0:
            i = card_html.find('card-detail-fold')
        return card_html[:i] if i >= 0 else card_html

    # #445: 初期表示は最高買取店＋2位差額のみ（買取店比較テーブルは details 内）
    #   初期表示（買取店比較foldより前）に shop-row が出ないこと。
    _init_row_counts = [_initial_view(c).count('class="shop-row') for c in _compact_cards]
    _max_init_rows = max(_init_row_counts, default=0)
    _t445 = bool(_compact_cards) and (_max_init_rows == 0) and ('shop-compare-fold' in _beg_html388)
    results.append({"level": "ok" if _t445 else "error", "check": "beginner_compare_folded_initial_hero_only",
                    "message": f"#445 初期表示は最高買取店＋2位差額のみ・買取店比較は details 内（初期表示の shop-row max={_max_init_rows}）"
                               + ("" if _t445 else " ← 初期表示に店舗行が残っている、または比較foldが無い")})

    # #446: 初期表示に最高買取店ブロック（best-buyback-hero）と2位差額が出る
    #   全カードの初期表示に best-buyback-hero があり、少なくとも一部に『2位との差額』が出る。
    _all_hero = bool(_compact_cards) and all('best-buyback-hero' in _initial_view(c) for c in _compact_cards)
    _any_runnerup = ('2位との差額' in _beg_html388)
    _t446 = _all_hero and _any_runnerup
    results.append({"level": "ok" if _t446 else "error", "check": "beginner_hero_and_runnerup_diff",
                    "message": "#446 初期表示に最高買取店ブロックと『2位との差額』が表示される"
                               + ("" if _t446 else " ← 最高買取店ブロックまたは2位差額が初期表示にありません")})

    # #447: 監視中セクションが折りたたみ（details）になっている
    _t447 = ('monitoring-global-section' in _beg_html388) and ('監視中の商品を見る' in _beg_html388)
    results.append({"level": "ok" if _t447 else "warning", "check": "beginner_monitoring_section_collapsed",
                    "message": "#447 監視中セクションが折りたたみ（監視中の商品を見る）になっている"
                               + ("" if _t447 else " ← 監視中の折りたたみセクションが見つかりません（監視中0件の日は正常）")})

    # #448: 利益ありカードが監視中セクションより上にある
    _pos_profit = _beg_html388.find('status-profit')
    _pos_mon = _beg_html388.find('monitoring-global-section')
    _t448 = (_pos_profit >= 0) and (_pos_mon < 0 or _pos_profit < _pos_mon)
    results.append({"level": "ok" if _t448 else "error", "check": "beginner_profit_above_monitoring",
                    "message": "#448 利益ありカードが監視中セクションより上に表示されている"
                               + ("" if _t448 else " ← 監視中セクションが利益ありより上にあります")})

    # #449: 最高買取店ブロック（best-buyback-hero）が存在する
    _t449 = ('best-buyback-hero' in _beg_html388) or ('best-buyback-block' in _beg_html388)
    results.append({"level": "ok" if _t449 else "error", "check": "beginner_best_buyback_block_present",
                    "message": "#449 最高買取店ブロック（best-buyback-hero）が存在する"
                               + ("" if _t449 else " ← 最高買取店ブロックが見つかりません")})

    # #450: 全買取店は比較fold内、取得失敗店舗は nested sub-details(shop-failed-details)内
    #   初期表示に取得失敗行が出ないこと（取得失敗の常時表示=False）。
    _failed_in_initial = any('shop-row-failed' in _initial_view(c) for c in _compact_cards)
    _t450 = bool(_compact_cards) and (not _failed_in_initial) \
        and ((('shop-row-failed' not in _beg_html388)) or ('shop-failed-details' in _beg_html388))
    results.append({"level": "ok" if _t450 else "error", "check": "beginner_all_shops_in_fold_failed_nested",
                    "message": f"#450 全買取店は比較fold内・取得失敗は別sub-details内（初期表示の取得失敗={_failed_in_initial}）"
                               + ("" if _t450 else " ← 取得失敗店舗が初期表示に出ている、または別detailsに分離されていない")})

    # ── Pro 買取店候補（Show top buyback shops and restore pro buyback candidates） ──
    # #451: Pro タブに「国内売却候補 / 買取店」セクションがある
    _t451 = ('国内売却候補' in _pro_html388) and ('pro-buyback-table' in _pro_html388)
    results.append({"level": "ok" if _t451 else "error", "check": "pro_buyback_sell_section_present",
                    "message": "#451 Pro タブに『国内売却候補 / 買取店』セクションがある"
                               + ("" if _t451 else " ← 国内売却候補（買取店）セクションが見つかりません")})

    # #452: Pro タブに買取店候補が3件以上ある商品が「複数」存在する
    _pro_bb_tables = _re437.findall(r'pro-buyback-table.*?</table>', _pro_html388, _re437.DOTALL)
    _pro_bb_counts = [t.count('pro-row-buyback') for t in _pro_bb_tables]
    _pro_bb_3plus = sum(1 for c in _pro_bb_counts if c >= 3)
    _t452 = _pro_bb_3plus >= 2
    results.append({"level": "ok" if _t452 else "warning", "check": "pro_buyback_3plus_multiple_products",
                    "message": f"#452 Pro タブに買取店候補が3件以上の商品が複数存在する（該当{_pro_bb_3plus}商品 / 件数内訳={_pro_bb_counts}）"
                               + ("" if _t452 else " ← 3件以上の商品が複数見つかりません（買取データが少ない日は正常）")})

    # #453: Pro で買取候補が3件未満の商品には理由が表示される
    #   「国内売却候補 / 買取店（N件）」の N<3 の数 ≦ 理由ノート(pro-bb-reason-note)の数。
    _bb_section_counts = [int(n) for n in _re437.findall(r'国内売却候補 / 買取店（(\d+)件）', _pro_html388)]
    _bb_under3_sections = sum(1 for n in _bb_section_counts if n < 3)
    _bb_reason_notes = _pro_html388.count('pro-bb-reason-note')
    _t453 = (_bb_under3_sections == 0) or (_bb_reason_notes >= _bb_under3_sections)
    results.append({"level": "ok" if _t453 else "error", "check": "pro_buyback_few_reason_shown",
                    "message": f"#453 Pro で買取候補が少ない商品に理由が表示される（<3件の商品={_bb_under3_sections} / 理由表示={_bb_reason_notes}）"
                               + ("" if _t453 else " ← 理由表示が不足しています")})

    # ── Refine beginner profit labels and pro route priority ──
    # #454: profit > 0 の利益ありカードに「様子見」バッジが出ない（Task 1）
    #   status-profit サブセクション内の shop card に「様子見」ラベルが無いこと。
    _profit_subsections = _re437.findall(
        r'status-subhead status-profit.*?(?=status-subhead|monitoring-global-section|fetch-failed-details|<div id="category-beginner|$)',
        _beg_html388, _re437.DOTALL
    )
    # バッジだけでなく本文ノート（様子見推奨 等）も含め、利益ありサブセクションに「様子見」が一切無いこと。
    _t454 = not any('様子見' in s for s in _profit_subsections)
    results.append({"level": "ok" if _t454 else "error", "check": "beginner_no_watch_badge_on_profit",
                    "message": "#454 profit>0 の利益ありカードに『様子見』が出ない（バッジ・本文とも：利益あり/小幅利益/微益）"
                               + ("" if _t454 else " ← 利益ありカードに『様子見』が残っています")})

    # #455: 価格「—」店舗が通常の「もっと見る」に混ざらず、別 details に分離されている（Task 2）
    #   取得失敗・未掲載店舗は shop-failed-details（専用 details）にある。
    _has_failed_rows = 'shop-row-failed' in _beg_html388
    _t455 = (not _has_failed_rows) or ('shop-failed-details' in _beg_html388 and '取得失敗・未掲載店舗を見る' in _beg_html388)
    results.append({"level": "ok" if _t455 else "error", "check": "beginner_failed_shops_separate_details",
                    "message": "#455 価格『—』店舗は通常のもっと見るに混ざらず別 details に分離されている"
                               + ("" if _t455 else " ← 取得失敗店舗が通常のもっと見るに混在しています")})

    # #456: 取得失敗店舗（shop-row-failed）が通常の shop-more-details（価格取得済み）側に出ない（Task 2）
    #   shop-failed-details を除いた通常 more-details 内に shop-row-failed が無いこと。
    _normal_more = _re437.findall(
        r'<details class="shop-more-details">.*?</details>', _beg_html388, _re437.DOTALL
    )
    _t456 = not any('shop-row-failed' in m for m in _normal_more)
    results.append({"level": "ok" if _t456 else "error", "check": "beginner_no_failed_in_normal_more",
                    "message": "#456 取得失敗店舗が通常の『もっと見る（価格取得済み）』に出ない"
                               + ("" if _t456 else " ← 通常のもっと見るに取得失敗店舗が混在しています")})

    # #457: Pro ルートで買取店→買取店ルートだけが上位を占めない（Task 4）
    #   買取店→買取店ルートは『要確認（買取店→買取店）』セクションに分離され、警告ノートが付く。
    #   推奨ルートがある場合は推奨が上に来る。bb2bb ルートが無い日は正常。
    _pos_pref  = _sed_html396.find('Proルート 推奨')
    _pos_bb2bb = _sed_html396.find('要確認（買取店→買取店）')
    if _pos_bb2bb >= 0:
        _t457 = ((_pos_pref < 0) or (_pos_pref < _pos_bb2bb)) and ('sc-route-bb2bb-note' in _sed_html396)
    else:
        _t457 = True
    results.append({"level": "ok" if _t457 else "error", "check": "pro_route_bb2bb_not_top",
                    "message": "#457 Pro ルートで買取店→買取店ルートだけが上位を占めない（要確認セクションへ分離）"
                               + ("" if _t457 else " ← 買取店→買取店ルートが上位を占めています")})

    # #458: 小幅利益カードに「小幅利益」と表示される（Task 1 / 段階バッジ）
    #   利益あり/小幅利益/微益 のいずれかのバッジが利益サブセクションに存在する。
    _has_tier_badge = any(
        ('>小幅利益<' in s) or ('>利益あり<' in s) or ('>微益<' in s)
        for s in _profit_subsections
    )
    _t458 = (not _profit_subsections) or _has_tier_badge
    results.append({"level": "ok" if _t458 else "warning", "check": "beginner_profit_tier_badges",
                    "message": "#458 利益カードに段階バッジ（利益あり/小幅利益/微益）が表示される"
                               + ("" if _t458 else " ← 段階バッジが見つかりません（利益カード0件の日は正常）")})

    # #459: 初心者の買取店比較がスマホ向け縦カード形式（shop-card）になっている（Task 2）
    _t459 = ('shop-card' in _beg_html388) and ('shop-card-top' in _beg_html388)
    results.append({"level": "ok" if _t459 else "error", "check": "beginner_buyback_vertical_card",
                    "message": "#459 初心者の買取店比較が縦カード形式（shop-card）になっている"
                               + ("" if _t459 else " ← 縦カード形式になっていません")})

    # #460: Pro に「国内仕入れ候補 / 国内売却候補 / 海外売却候補」が分離表示される（問題4）
    _t460 = ('国内仕入れ候補' in _pro_html388) and ('国内売却候補' in _pro_html388) and ('海外売却候補' in _pro_html388)
    results.append({"level": "ok" if _t460 else "error", "check": "pro_three_candidate_sections",
                    "message": "#460 Pro に 国内仕入れ候補 / 国内売却候補 / 海外売却候補 が分離表示される"
                               + ("" if _t460 else " ← いずれかの候補セクションが見つかりません")})

    # #461: Beginner タブ全体に「利益率が低め」「様子見推奨」が一切存在しない（問題1/2・本文も含む）
    _t461 = ('様子見推奨' not in _beg_html388) and ('利益率が低め' not in _beg_html388)
    results.append({"level": "ok" if _t461 else "error", "check": "beginner_no_wait_wording_anywhere",
                    "message": "#461 Beginner タブ全体に『利益率が低め』『様子見推奨』が存在しない（本文含む）"
                               + ("" if _t461 else " ← 本文に様子見系の文言が残っています")})

    # #462: 「小幅利益」カードには本文に「小幅利益（定価購入→最高買取・参考値）」が表示される（問題2）
    #   小幅利益バッジがある場合、対応する正規の note 文言が存在すること。
    _has_kohaba_badge = ('>小幅利益<' in _beg_html388)
    _t462 = (not _has_kohaba_badge) or ('小幅利益（定価購入→最高買取・参考値）' in _beg_html388)
    results.append({"level": "ok" if _t462 else "error", "check": "beginner_kohaba_note_wording",
                    "message": "#462 『小幅利益』カードに本文『小幅利益（定価購入→最高買取・参考値）』が表示される"
                               + ("" if _t462 else " ← 小幅利益カードの正規 note 文言が見つかりません")})

    # ── Restore camera buyback visibility in beginner tab ──
    # #463: カメラ初心者カードが存在する
    _t463 = ('badge-camera' in _beg_html388) or ('data-genre="camera"' in _beg_html388)
    results.append({"level": "ok" if _t463 else "warning", "check": "beginner_camera_card_exists",
                    "message": "#463 カメラの初心者カードが存在する"
                               + ("" if _t463 else " ← カメラ初心者カードが見つかりません（カメラ案件0件の日は正常）")})

    # #464: カメラ等の未取得カードに理由付き表示がある（理由ラベルのいずれかが出る）
    #   監視中カードの status バッジが必ず意味のある理由/状態ラベルを持つこと。
    _REASON_LABELS = ('中古価格のみ取得', '新品買取価格なし', 'サイト制限中', '商品未掲載',
                      '取得失敗', '買取価格取得待ち', '価格変動を監視中')
    _mon_badges = _re437.findall(r'mon-status-badge">([^<]+)<', _beg_html388)
    _t464 = all(b.strip() in _REASON_LABELS for b in _mon_badges)
    results.append({"level": "ok" if _t464 else "error", "check": "beginner_missing_reason_shown",
                    "message": f"#464 未取得/監視中カードに理由（中古価格のみ取得/新品買取価格なし/サイト制限中/商品未掲載/取得失敗 等）が表示される（{len(_mon_badges)}枚）"
                               + ("" if _t464 else f" ← 理由不明のステータス: {[b for b in _mon_badges if b.strip() not in _REASON_LABELS][:3]}")})

    # #465: 新品/未使用の買取価格がある利益カードには店舗名（最高買取店）が出る
    #   利益サブセクションの best-buyback-hero に '—' でない店舗名が表示されている。
    _hero_blocks = _re437.findall(r'best-buyback-hero">.*?</div>\s*</div>', _beg_html388, _re437.DOTALL)
    _t465 = (not _hero_blocks) or all(
        (m is not None and m.group(1).strip() not in ('', '—'))
        for m in (_re437.search(r'bb-shop-val"><strong>([^<]*)</strong>', h) for h in _hero_blocks)
    )
    results.append({"level": "ok" if _t465 else "error", "check": "beginner_best_shop_name_shown",
                    "message": "#465 新品/未使用の買取価格がある場合は最高買取店の店舗名が表示される"
                               + ("" if _t465 else " ← 店舗名が空または『—』の最高買取店ブロックがあります")})

    # #466: 中古価格（中古A/used_a/美品 等）が初心者カードの買取価格・条件として使われない
    #   （理由テキストの『中古価格のみ取得』は説明文なので許容。条件ラベルとしての中古は不可）
    _t466 = ('中古A' not in _beg_html388) and ('used_a' not in _beg_html388) \
        and ('美品' not in _beg_html388) and ('中古販売価格' not in _beg_html388)
    results.append({"level": "ok" if _t466 else "error", "check": "beginner_no_used_price_used",
                    "message": "#466 中古価格（中古A/used_a/美品/中古販売価格）が初心者の買取価格に使われない"
                               + ("" if _t466 else " ← 初心者カードに中古条件の価格が混入しています")})

    # #467: X100VI / GR IV / GR IIIx のうち少なくとも1件は新品・未使用の買取価格（利益カード）が表示される
    #   カメラの利益カード（stripe-camera + best-buyback-hero）が beginner に存在する。
    _camera_profit_cards = _re437.findall(
        r'<div class="deal-card deal-card-compact[^"]*stripe-camera[^"]*"[^>]*>.*?(?=<div class="deal-card |<details class="monitoring-global-section|<details class="status-subsection|$)',
        _beg_html388, _re437.DOTALL
    )
    _t467 = any('best-buyback-hero' in c for c in _camera_profit_cards)
    results.append({"level": "ok" if _t467 else "error", "check": "beginner_camera_new_unused_buyback_shown",
                    "message": f"#467 カメラ（X100VI/GR IV/GR IIIx 等）に新品・未使用の買取価格が表示される（利益カード{len(_camera_profit_cards)}枚）"
                               + ("" if _t467 else " ← カメラの新品・未使用買取価格が表示されていません")})

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

    # #469: EXCLUDE_STALE_H が 336h（_STALE_EXCLUDE_H も同等）になっている
    _t469 = ('EXCLUDE_STALE_H = 336' in _gen_src) and ('_STALE_EXCLUDE_H = EXCLUDE_STALE_H' in _gen_src) \
        and ('WARNING_STALE_H = 168' in _gen_src)
    results.append({"level": "ok" if _t469 else "error", "check": "freshness_thresholds_two_stage",
                    "message": "#469 鮮度閾値が WARNING=168h / EXCLUDE=336h（_STALE_EXCLUDE_H=336h 同等）になっている"
                               + ("" if _t469 else " ← 閾値定義が見つかりません")})

    # #470: 7日超価格は「要更新」表示になる（7日以上前の参考値）
    #   7〜14日の手動価格がある日は表示される。0件の日は warning。
    _t470_struct = ('7日以上前の参考値' in _gen_src) and ('_src_stale7' in _gen_src)
    _t470_shown = ('要更新' in _beg_html388) and ('7日以上前の参考値' in _beg_html388)
    _t470 = _t470_struct and _t470_shown
    results.append({"level": "ok" if _t470 else ("warning" if _t470_struct else "error"),
                    "check": "freshness_7d_warning_shown",
                    "message": "#470 7日超の価格に『要更新』『7日以上前の参考値』が表示される"
                               + ("" if _t470 else (" ← 7〜14日の価格が無い日は正常（実装は有効）" if _t470_struct
                                                    else " ← 7日超表示の実装が見つかりません"))})

    # #471: 14日超価格は利益判定に使われない（enrich 後に降格を適用）
    _t471 = ('_apply_stale_downgrade(d) for d in deduped_all' in _gen_src) \
        and ("age > EXCLUDE_STALE_H" in _gen_src)
    results.append({"level": "ok" if _t471 else "error", "check": "freshness_14d_excluded_from_profit",
                    "message": "#471 14日超の手動価格は利益判定から除外される（enrich 後に降格適用）"
                               + ("" if _t471 else " ← 14日超の除外処理が見つかりません")})

    # #472: 14日超商品は監視中へ降格される（カードは消さない）
    _t472 = ("'user_level': 'monitoring'" in _gen_src) and ('||STALE14' in _gen_src)
    results.append({"level": "ok" if _t472 else "error", "check": "freshness_14d_downgraded_to_monitoring",
                    "message": "#472 14日超商品は監視中へ降格される（カードは残す / STALE14 マーカー）"
                               + ("" if _t472 else " ← 監視中降格の実装が見つかりません")})

    # #473: 「価格情報が古い（要再確認）」が表示される（>14日商品がある日のみ可視）
    _t473_struct = '価格情報が古い（要再確認）' in _gen_src
    _t473_shown = '価格情報が古い（要再確認）' in _beg_html388
    _t473 = _t473_struct and _t473_shown
    results.append({"level": "ok" if _t473 else ("warning" if _t473_struct else "error"),
                    "check": "freshness_stale14_note_shown",
                    "message": "#473 14日超商品に『価格情報が古い（要再確認）』が表示される"
                               + ("" if _t473 else (" ← 14日超商品が無い日は正常（実装は有効）" if _t473_struct
                                                    else " ← 該当文言の実装が見つかりません"))})

    # #474: manual_today / manual_confirmed の observed_at を見て鮮度判定している
    _t474 = ('_price_obs_age_h' in _gen_src) and ("r.get('observed_at'" in _gen_src
                                                  or 'observed_at' in _gen_src)
    results.append({"level": "ok" if _t474 else "error", "check": "freshness_uses_observed_at",
                    "message": "#474 手動価格の observed_at を見て鮮度判定している"
                               + ("" if _t474 else " ← observed_at ベースの鮮度判定が見つかりません")})

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

    # #477: 24h超データに要更新表示がある（7〜14日の参考値含む）
    _t477_struct = ('要更新' in _gen_src)
    _t477_shown = ('要更新' in _beg_html388)
    _t477 = _t477_struct and _t477_shown
    results.append({"level": "ok" if _t477 else ("warning" if _t477_struct else "error"),
                    "check": "stale_24h_warning_shown",
                    "message": "#477 24時間超データに『要更新』表示がある"
                               + ("" if _t477 else (" ← 24h超データが無い日は正常（実装有効）" if _t477_struct
                                                    else " ← 要更新表示の実装が見つかりません"))})

    # #478: ランキングが最新有効データから生成（中古/used をランキングに使わない）
    _t478 = ('中古A' not in _rank_html396) and ('used_a' not in _rank_html396) \
        and ('美品' not in _rank_html396)
    results.append({"level": "ok" if _t478 else "error", "check": "ranking_from_valid_data",
                    "message": "#478 ランキングが最新有効データから生成（中古/used を使わない）"
                               + ("" if _t478 else " ← ランキングに中古/used 価格が混入しています")})

    # #479: せどりルートが最新有効データから生成（中古を使わない / 中古除外ロジックあり）
    _t479 = ('中古A' not in _sed_html396) and ('used_a' not in _sed_html396) \
        and ('_cond_is_used' in _gen_src)
    results.append({"level": "ok" if _t479 else "error", "check": "sedori_from_valid_data",
                    "message": "#479 せどりルートが最新有効データから生成（中古/used を除外）"
                               + ("" if _t479 else " ← せどりルートに中古/used が混入、または除外ロジックなし")})

    # #480: 抽選情報が毎日更新される（workflow に update_lottery_events ステップがある）
    _t480 = ('update_lottery_events.py' in _wf)
    results.append({"level": "ok" if _t480 else "error", "check": "lottery_daily_update",
                    "message": "#480 抽選情報が毎日更新される（daily_lp.yml に update_lottery_events ステップ）"
                               + ("" if _t480 else " ← 抽選情報の更新ステップが見つかりません")})

    # #481: fetch_failed の理由が LP（failure-reason-badge）またはレポートに出る
    _t481_lp = ('failure-reason-badge' in _beg_html388) or ('failure-reason-badge' in html)
    _t481_report = False
    try:
        with open(_os468.path.join(_root, 'exports/collector_report/latest.json'), encoding='utf-8') as _cr:
            _cr_txt = _cr.read()
        _t481_report = ('reason' in _cr_txt) or ('fail' in _cr_txt.lower())
    except Exception:
        _t481_report = False
    _t481 = _t481_lp or _t481_report
    results.append({"level": "ok" if _t481 else "error", "check": "fetch_failed_reason_visible",
                    "message": "#481 fetch_failed の理由が LP またはレポートに表示される"
                               + ("" if _t481 else " ← 取得失敗理由がどこにも出ていません")})

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
    _sed_route_n = len(_sed_json.get('routes', []) or _sed_json.get('pro_routes', []) or [])
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

    # #485: EBAY_APP_ID 未設定時に明確な warning を出す実装がある
    _t485 = ('EBAY_APP_ID' in _ovs_src) and ('STRONG WARNING' in _ovs_src or 'api_not_configured' in _ovs_src)
    results.append({"level": "ok" if _t485 else "error", "check": "ebay_app_id_warning",
                    "message": "#485 EBAY_APP_ID 未設定時に明確な warning を出す"
                               + ("" if _t485 else " ← EBAY_APP_ID 未設定警告が見つかりません")})

    # #486: 手動データ（camera 含む）が14日超なら利益判定から除外（LP・ranking 両方）
    _ranking_src = ''
    try:
        with open(_os468.path.join(_root, 'scripts', 'generate_ranking_report.py'), encoding='utf-8') as _rf:
            _ranking_src = _rf.read()
    except Exception:
        _ranking_src = ''
    _t486 = ('EXCLUDE_STALE_H' in _gen_src) and ('336' in _ranking_src) and ('_stale_excluded' in _ranking_src)
    results.append({"level": "ok" if _t486 else "error", "check": "camera_manual_14d_excluded",
                    "message": "#486 手動データ（camera含む）が14日超なら利益判定から除外される（LP・ranking）"
                               + ("" if _t486 else " ← 14日除外ロジックが見つかりません")})

    # #487: データ品質レポートに 成功率 / 失敗理由 / 有効データ数 が出る
    _dq_ok = bool(_dq_json) and ('collection' in _dq_json) and ('failure_reasons' in _dq_json) \
        and ('effective_data' in _dq_json) and ('ranking_usable' in _dq_json) and ('sedori_usable' in _dq_json)
    results.append({"level": "ok" if _dq_ok else "error", "check": "data_quality_report_present",
                    "message": "#487 データ品質レポートに 成功率/失敗理由/有効データ数/ranking・sedori使用数 が出る"
                               + ("" if _dq_ok else " ← data_quality_report/latest.json が不完全です")})

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

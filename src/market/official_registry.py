"""公式の確認の記録の正本（Phase 15。以前は scripts/audit_official_sources.py にあった表をそのまま移した）。

ここだけを読めば、商品ごとの公式の確認（公式 URL・確認の種類・価格・確認日・販売の状態・在庫・同一性の証拠）が分かる。
scripts/audit_official_sources.py は、ここの表を import して DB（products・product_source_config）に書く。

価格の意味（price_kind。Phase 15）:
- "msrp": メーカーが「希望小売価格」「定価」と明示している価格
- "official_direct": メーカーの公式ストアの販売価格（希望小売価格とは呼ばない。Apple Store など）
- "open_price": メーカーの希望小売価格はオープン価格（架空の希望小売価格を作らない）

Phase 16: 公式直販価格（official_direct）は、OFFICIAL_DIRECT_OFFERS の証拠がそろい official_direct_gate を通ったときだけ
確定の仕入れ値（products.official_price）に使う。1つでも欠ければ参考（価格を DB に書かない）。公式ストアに価格が
あるだけでは確定にしない。希望小売価格（msrp）とは呼ばない（カメラの希望小売価格はオープン価格のまま: MSRP_OF）。
"""

from __future__ import annotations

# ─────────────────────────────────────────────────────────────
# 実検証済み公式URL（WebFetch またはブラウザで公式ページを表示し、公式ドメイン + 商品一致を確認。
# extraction_method の値は以前からの名前 webfetch_verified のまま。どちらで確認したかは各行のコメントに書く）
# 確認日は VERIFIED_URLS_CHECKED_ON（実行日の TODAY ではない）。price は検証時に確認できた本体価格（税込）。
# link_type: item=個別商品/購入ページ, category=カテゴリ購入ページ（個別URLなし）
# confidence: high/medium/low（official_price_validator の基準）
# ─────────────────────────────────────────────────────────────
# VERIFIED_URLS の価格・URL を人（WebFetch）が実際に確認した日。
# この辞書は固定値なので、スクリプトを毎日実行しても「今日確認した」ことにはならない。
# 価格を公式ページで再確認したときだけ、確認した証拠（URL・価格）と一緒にこの日付を更新する。
# 値を確認していないのに日付だけ新しくしてはいけない（鮮度の偽装になる）。
# 2026-08-23: git の記録上、VERIFIED_URLS を最後に確認・更新した日
VERIFIED_URLS_CHECKED_ON = "2026-08-23"

VERIFIED_URLS = {
    # ---- Apple（公式直販・価格実在）----
    # 2026-10-03: 公式の購入ページ（ブラウザで表示）で「256GB 159,800円から」を確認（08/23 の 142,800円から改定）
    # 2026-10-08（Phase 16）: 同じ購入ページで「256GB 159,800円から」を再確認（ブラウザ）。5色・2容量の SKU が並び、
    # 256GB はどの色も同じ価格（OFFICIAL_DIRECT_OFFERS に証拠）
    "prod_iphone17_256":    {"source": "src_apple_jp", "url": "https://www.apple.com/jp/shop/buy-iphone/iphone-17",         "link_type": "item",     "price": 159800, "conf": "high", "checked_on": "2026-10-08", "price_kind": "official_direct"},
    # 2026-10-03: 公式の購入ページで「AirPods Pro 3 42,800円」を再確認
    # 2026-10-08（Phase 14）: 同じ購入ページで 42,800円 を再確認（ブラウザ）。在庫・お届けの表示は、選択を進める前の
    # ページには出ない（明示の証拠が無いので在庫は記録しない＝在庫未確認のまま）
    "prod_airpods_pro3":    {"source": "src_apple_jp", "url": "https://www.apple.com/jp/shop/buy-airpods/airpods-pro-3",   "link_type": "item",     "price": 42800,  "conf": "high", "checked_on": "2026-10-08", "price_kind": "official_direct"},
    # ---- ゲーム機（公式ストア・公式ラインナップ）----
    # 2026-10-03: Sony Store の購入ページで「PlayStation®5 Pro CFI-7100B01 入荷待ち 137,980 円(税込)」を確認
    # （2026-04-02 の価格改定後の価格。設定値の 119,980円 は改定前）。
    # 在庫の表示（入荷待ち）も同じページで確認した時刻つきで記録する（7日を過ぎれば在庫未確認に戻る）
    # 2026-10-08 02:34（Phase 14）: 同じ購入ページで「選択済み CFI-7100B01 入荷待ち 137,980円(税込)」を再確認（ブラウザ）。
    # PlayStation 公式の本体ラインナップ（https://www.playstation.com/ja-jp/ps5/buy-now/）でも
    # 「PS5 Pro 希望小売価格：137,980円（税込）」。「カートに入れる」のボタンはあるが「入荷待ち」なので在庫切れの扱い
    "prod_ps5_pro": {"source": "src_sony_store", "url": "https://pur.store.sony.jp/ps5/products/ps5/CFI-7100B01_purchase/",
                     "link_type": "item", "price": 137980, "conf": "high", "checked_on": "2026-10-08", "price_kind": "msrp",
                     "stock": "入荷待ち", "stock_checked_at": "2026-10-08T02:34:48+09:00"},
    # 2026-10-03: 任天堂公式の商品ラインナップで「Nintendo Switch 2 本体 日本語・国内専用 希望小売価格： 59,980 円（税込）」
    # を確認（2026-05-25 の価格改定後。設定値の 49,980円 は改定前）
    # 2026-10-08 02:32（Phase 14）: My Nintendo Store の商品ページ（Nintendo Switch 2（日本語・国内専用））で
    # 「59,980 円 税込」「お届け予定日：通常2～6日後にお届け」「カートに入れる」（押せる状態）を確認（ブラウザ）。
    # 購入できることの明示の表示なので、確認した時刻つきで在庫ありとして記録する（7日を過ぎれば在庫未確認に戻る）。
    # ページの「品切れ」の表示は、おすすめに出ていた別の周辺機器（microSD Express カード）のもの
    "prod_switch2": {"source": "src_nintendo_store", "url": "https://store-jp.nintendo.com/item/hardware-accessory/VM_BEE_S_KB6CA",
                     "link_type": "item", "price": 59980, "conf": "high", "checked_on": "2026-10-08", "price_kind": "msrp",
                     "stock": "カートに入れる（お届け予定日：通常2～6日後）", "stock_checked_at": "2026-10-08T02:32:13+09:00"},
    # ---- カメラ（Phase 16。希望小売価格はオープン価格（MSRP_OF）。価格はメーカー直販の販売価格 = 公式直販価格）----
    # 公式直販価格は official_direct_gate を通ったときだけ products.official_price に書く（OFFICIAL_DIRECT_OFFERS に証拠）。
    # Phase 15 までは製品ページ（category）・価格なしで載せていた
    # 2026-10-08: ニコンダイレクトの購入ページ「Z8 … ニコンダイレクト販売価格 575,300円 … JANコード： 4960759909947」
    # 「こちらの商品はボディーのみの販売となります」。在庫の欄（spec_stock_msg）は空（在庫は記録しない）
    "prod_z8": {"source": "src_nikon_direct", "url": "https://nij.nikon.com/shop/g/g4960759909947/", "link_type": "item",
                "price": 575300, "conf": "high", "checked_on": "2026-10-08", "price_kind": "official_direct"},
    # 2026-10-08 14:31: フジフイルムモールの購入ページ（シルバー）「X100VI 315,700円（税込）」「送料：無料」
    # 「カラーを選択 シルバー 在庫なし ブラック 在庫なし」。ブラック（g16941816）も同じ 315,700円
    "prod_x100vi": {"source": "src_fujifilm_official", "url": "https://mall-jp.fujifilm.com/shop/g/g16941878/",
                    "link_type": "item", "price": 315700, "conf": "high", "checked_on": "2026-10-08",
                    "price_kind": "official_direct",
                    "stock": "在庫なし（シルバー・ブラックとも）", "stock_checked_at": "2026-10-08T14:31:45+09:00"},
    # 2026-10-08: キヤノンオンラインショップの購入ページ「EOS R5 Mark II・ボディー（レンズは付きません）」
    # 「価格 654,500円(税込) … 送料無料 … カートに入れる」（押せるボタン。構造化データの offers も price 654500）。
    # 製品ページ（personal.canon.jp）に「JANコード 4549292-229141 商品コード 6536C001」。
    # 在庫の確認は 14:15〜14:24 の間（古いほうの時刻で記録する）
    "prod_r5ii": {"source": "src_canon_official", "url": "https://store.canon.jp/online/g/g6536C001/", "link_type": "item",
                  "price": 654500, "conf": "high", "checked_on": "2026-10-08", "price_kind": "official_direct",
                  "stock": "カートに入れる（送料無料）", "stock_checked_at": "2026-10-08T14:15:00+09:00"},
}

# 検証できなかった/公式定価が存在しないメーカー（推測URLで verified 扱いしない）
# 実際の型番（同一性確認用）
UNVERIFIED = {
    "prod_r6ii":  {"source": "src_canon_official", "model": "EOS R6 Mark II",  "reason": "canon.jp が当環境からDNS解決不可（要手動検証）"},
    "prod_r3":    {"source": "src_canon_official", "model": "EOS R3",          "reason": "canon.jp が当環境からDNS解決不可（要手動検証）"},
    "prod_z9":    {"source": "src_nikon_direct",   "model": "Z9",              "reason": "オープン価格の可能性・個別URL未検証"},
    "prod_zf":    {"source": "src_nikon_direct",   "model": "Zf",              "reason": "オープン価格の可能性・個別URL未検証"},
    "prod_a1ii":  {"source": "src_sony_store",     "model": "ILCE-1M2",        "reason": "store.sony.jp が当環境からDNS解決不可（要手動検証）"},
    "prod_a7rv":  {"source": "src_sony_store",     "model": "ILCE-7RM5",       "reason": "store.sony.jp が当環境からDNS解決不可（要手動検証）"},
    "prod_a7cr":  {"source": "src_sony_store",     "model": "ILCE-7CR",        "reason": "store.sony.jp が当環境からDNS解決不可（要手動検証）"},
    "prod_fx3":   {"source": "src_sony_store",     "model": "ILME-FX3",        "reason": "store.sony.jp が当環境からDNS解決不可（要手動検証）"},
}

# 公式ストアで今は売っていない（販売終了・後継機に交代）と確認した商品。
# 過去に確認した定価は「今その値段で公式から買える」根拠にならないので、確認済みの定価として使わない
# （products.official_price を消し、設定値の参考価格に戻す。確定利益には使わない）。
OFFICIAL_NOT_SOLD = {
    "prod_iphone17pro_256": {"source": "src_apple_jp", "checked_on": "2026-10-03",
                             "reason": "iPhone 17 Pro の購入ページが /buy-iphone へ移動。公式は iPhone 18 Pro を販売中"},
    "prod_iphone17pro_512": {"source": "src_apple_jp", "checked_on": "2026-10-03",
                             "reason": "iPhone 17 Pro の購入ページが /buy-iphone へ移動。公式は iPhone 18 Pro を販売中"},
    "prod_iphone17pm_256":  {"source": "src_apple_jp", "checked_on": "2026-10-03",
                             "reason": "iPhone 17 Pro Max の購入ページが /buy-iphone へ移動。公式は iPhone 18 Pro Max を販売中"},
    "prod_iphone17pm_512":  {"source": "src_apple_jp", "checked_on": "2026-10-03",
                             "reason": "iPhone 17 Pro Max の購入ページが /buy-iphone へ移動。公式は iPhone 18 Pro Max を販売中"},
    "prod_ipad_pro_m4_11":  {"source": "src_apple_jp", "checked_on": "2026-10-03",
                             "reason": "公式の iPad Pro は M5 チップ（M4 は販売していない）"},
    "prod_ipad_pro_m4_13":  {"source": "src_apple_jp", "checked_on": "2026-10-03",
                             "reason": "公式の iPad Pro は M5 チップ（M4 は販売していない）"},
    "prod_ipad_air_m3":     {"source": "src_apple_jp", "checked_on": "2026-10-03",
                             "reason": "公式の iPad Air は M4 チップ（M3 は販売していない）"},
    "prod_apple_watch_s11": {"source": "src_apple_jp", "checked_on": "2026-10-03",
                             "reason": "公式は Apple Watch Series 12 を販売中（Series 11 は販売していない）"},
    "prod_apple_watch_ultra3": {"source": "src_apple_jp", "checked_on": "2026-10-03",
                                "reason": "公式は Apple Watch Ultra 4 を販売中（Ultra 3 は販売していない）"},
    "prod_switch2_mk":      {"source": "src_nintendo_store", "checked_on": "2026-10-03",
                             "reason": "任天堂公式のラインナップでマリオカート ワールド セットは「生産終了」"},
    # 2026-10-07（Phase 11）: 公式の購入ページで確認
    # - iPhone 16 Pro の購入ページ /shop/buy-iphone/iphone-16-pro は /jp/iphone へ移動（301）。
    #   /jp/iphone の現行は iPhone 18 Pro・17・17e・16
    # - AirPods Max の購入ページ /shop/buy-airpods/airpods-max は airpods-max-2 へ移動（301）
    # - Mac の購入ページ: mac-mini は M6・M5 Pro、macbook-air は M5、macbook-pro は M5・M5 Pro・M5 Max のみ
    #   （以前は VERIFIED_URLS に「現行はM5世代」の注記つき・価格なしで載せていた MacBook 3件もここへ移した）
    "prod_iphone16pro_256": {"source": "src_apple_jp", "checked_on": "2026-10-07",
                             "reason": "iPhone 16 Pro の購入ページが /jp/iphone へ移動。公式は iPhone 18 Pro を販売中"},
    "prod_iphone16pm_256":  {"source": "src_apple_jp", "checked_on": "2026-10-07",
                             "reason": "iPhone 16 Pro Max は公式で販売していない（公式は iPhone 18 Pro Max を販売中）"},
    "prod_iphone16pm_512":  {"source": "src_apple_jp", "checked_on": "2026-10-07",
                             "reason": "iPhone 16 Pro Max は公式で販売していない（公式は iPhone 18 Pro Max を販売中）"},
    "prod_airpods_max":     {"source": "src_apple_jp", "checked_on": "2026-10-07",
                             "reason": "AirPods Max の購入ページが AirPods Max 2 へ移動（初代は販売していない）"},
    "prod_mac_mini_m4":     {"source": "src_apple_jp", "checked_on": "2026-10-07",
                             "reason": "公式の Mac mini は M6・M5 Pro チップ（M4 は販売していない）"},
    "prod_macbook_air_m4_13": {"source": "src_apple_jp", "checked_on": "2026-10-07",
                               "reason": "公式の MacBook Air は M5 チップ（M4 は販売していない）"},
    "prod_macbook_air_m4_15": {"source": "src_apple_jp", "checked_on": "2026-10-07",
                               "reason": "公式の MacBook Air は M5 チップ（M4 は販売していない）"},
    "prod_macbook_pro_m4_14": {"source": "src_apple_jp", "checked_on": "2026-10-07",
                               "reason": "公式の MacBook Pro は M5・M5 Pro・M5 Max チップ（M4 は販売していない）"},
    # 2026-10-08（Phase 14）: ブラウザで公式ページを確認
    # - PlayStation 公式の本体ラインナップ（https://www.playstation.com/ja-jp/ps5/buy-now/）で売っているデジタル・
    #   エディションは「日本語専用」（希望小売価格 55,000円）だけ。この商品（型番の登録なし・設定の参考価格 72,980円。
    #   多言語の版に当たる）はラインナップに無い。型番が無いので日本語専用の版と同じ商品とはみなさない
    # - RICOH の製品ページ（https://www.ricoh-imaging.co.jp/japan/products/gr-3/）に「RICOH GRIII 生産終了」
    # source は公式の取得元として読まれる src_sony_store（_official_meta は OFFICIAL_DOMAINS の source だけを読む）。
    # 証拠のページは PlayStation 公式（playstation.com）の本体ラインナップ
    "prod_ps5_de":          {"source": "src_sony_store", "checked_on": "2026-10-08",
                             "reason": "公式の本体ラインナップのデジタル・エディションは日本語専用（55,000円）だけ。この商品の版は無い"},
    "prod_gr3":             {"source": "src_ricoh_imaging", "checked_on": "2026-10-08",
                             "reason": "RICOH の製品ページに「RICOH GRIII 生産終了」"},
}

# 旧世代/404 として検出・要注意（Task1）。実際に 404 を確認したもの。
KNOWN_STALE = {
    "iphone-16-pro-max": "iPhone 16 世代の購入ページ。iphone-17-pro ページに統合/404",
}


# 価格の意味（price_kind）の根拠（Phase 15。ブラウザで公式ページを表示して確認）
# - Apple: 公式の購入ページは価格だけを示し「希望小売価格」とは書かない → official_direct（Apple Store の販売価格）。
#   Apple の購入ページの価格は Phase 2.1 から確定の仕入れ値に使っている（購入できるのが公式ストアなので、
#   その販売価格が仕入れ値になる）。Phase 16 からは official_direct_gate も通す
# - Sony（PS5 Pro）: PlayStation 公式の本体ラインナップに「希望小売価格：137,980円（税込）」→ msrp
# - Nintendo（Switch 2）: 任天堂公式の商品ラインナップに「希望小売価格： 59,980 円（税込）」→ msrp
# - Nikon（Z8）・Fujifilm（X100VI）・Canon（R5 II）: 希望小売価格はオープン価格（MSRP_OF）。Phase 16 から、メーカー直販の
#   販売価格を official_direct として持つ（希望小売価格とは呼ばない）
# - RICOH（GR IV 系。collector が取る）: リコーイメージングストアが「定価」と明記 → msrp（SOURCE_PRICE_KINDS）
PRICE_KINDS = ("msrp", "official_direct", "open_price")
PRICE_KIND_LABELS = {"msrp": "定価（希望小売価格）", "official_direct": "公式直販価格", "open_price": "オープン価格"}

# 価格の種類の対応（Phase 16。手順2）。種別の正本は src/market/price_types.py（RETAIL・BUYBACK_CASH・LISTING・SOLD・
# SOLD_MEDIAN・CONFIGURED_REFERENCE）。MSRP と OFFICIAL_DIRECT は、仕入れの RETAIL を price_kind で分けたもの
# （観測の種別は RETAIL のまま。新しい種別を増やさない）
PRICE_SEMANTICS = {
    "MSRP": ("RETAIL", "msrp", "メーカーが「希望小売価格」「定価」と明示した価格"),
    "OFFICIAL_DIRECT": ("RETAIL", "official_direct", "メーカーの公式ストアが実際に売っている価格（定価と呼ばない）"),
    "RETAIL": ("RETAIL", "", "販売店の販売価格（公式ではない）"),
    "BUYBACK_CASH": ("BUYBACK_CASH", "", "買取店の現金買取価格"),
    "LISTING": ("LISTING", "", "出品中の価格（売れた価格ではない）"),
    "SOLD": ("SOLD", "", "1件の成約価格"),
    "SOLD_MEDIAN": ("SOLD_MEDIAN", "", "成約価格の中央値（件数・期間つき）"),
    "REFERENCE": ("CONFIGURED_REFERENCE", "", "設定値の参考価格（確認日不明）"),
}

# collector が公式ストアから取る価格の意味（VERIFIED_URLS に無い商品。取得元ごと）
# 2026-10-08: リコーイメージングストアの一覧・商品ページに「定価 ¥211,800 税込」（GR IV）。抽選販売・SOLD OUT
SOURCE_PRICE_KINDS = {"src_ricoh_imaging": "msrp"}

# メーカーの希望小売価格（Phase 16。手順3・4）。オープン価格の商品に架空の希望小売価格を作らない（値は持たない）
MSRP_OF = {"prod_z8": "open_price", "prod_x100vi": "open_price", "prod_r5ii": "open_price"}


def price_kind_of(product_id: str, source: str = "") -> str:
    """その商品の公式の価格の意味（msrp / official_direct / open_price / 空 = 分からない）。"""
    v = VERIFIED_URLS.get(str(product_id or ""))
    if v:
        return v.get("price_kind") or ("open_price" if v.get("open_price") else "msrp")
    return SOURCE_PRICE_KINDS.get(str(source or ""), "")


def official_price_label(product_id: str, price=None, source: str = "") -> str:
    """公式の価格の呼び方。文面・表で定価と公式直販価格を呼び分ける。

    公式直販価格の商品は、記録（VERIFIED_URLS）と同じ価格のときだけ「公式直販価格」。違う値（再確認で外れた後の
    設定値の参考価格など）は「参考価格」と呼ぶ（確認していない値を公式の価格に見せない。Phase 16 監査 M-1）。
    """
    if price_kind_of(product_id, source) != "official_direct":
        return "定価"
    rec = (VERIFIED_URLS.get(str(product_id or "")) or {}).get("price")
    try:
        same = price is not None and rec is not None and int(price) == int(rec)     # 価格が無ければ参考
    except (TypeError, ValueError):
        same = False
    return "公式直販価格" if same else "参考価格"


# カメラのメーカー直販の監査（Phase 15。2026-10-08 にブラウザで確認。手順21）
# 希望小売価格（オープン価格）と、公式ストアの販売価格は別のもの。Phase 16 から、直販の販売価格は
# OFFICIAL_DIRECT_OFFERS の証拠がそろい official_direct_gate を通ったものだけ確定の仕入れ値に使う
CAMERA_DIRECT_SALE_AUDIT = {
    "src_fujifilm_official": {"shop": "フジフイルムモール", "msrp": "オープン価格",
                              "example": "X100VI シルバー 315,700円（税込）・在庫なし・5,000円以上送料無料",
                              "url": "https://mall-jp.fujifilm.com/shop/g/g16941878/", "checked_on": "2026-10-08"},
    "src_nikon_direct": {"shop": "ニコンダイレクト", "msrp": "オープンプライス（製品ページ）",
                         "example": "Z8 ニコンダイレクト販売価格 575,300円（税込）",
                         "url": "https://nij.nikon.com/shop/g/g4960759909947/", "checked_on": "2026-10-08"},
    "src_canon_official": {"shop": "キヤノンオンラインショップ", "msrp": "オープン価格",
                           "example": "EOS R5 Mark II・ボディー キヤノンオンラインショップ価格 654,500円（税込）",
                           "url": "https://store.canon.jp/online/g/g6536C001/", "checked_on": "2026-10-08"},
    "src_ricoh_imaging": {"shop": "リコーイメージングストア", "msrp": "公式ストアが「定価」と表記",
                          "example": "GR IV 定価 211,800円・HDF 222,000円・Monochrome 299,800円（いずれも抽選販売・SOLD OUT）",
                          "url": "https://ricohimagingstore.com/Form/Product/ProductList.aspx?shop=0&cat=002010",
                          "checked_on": "2026-10-08"},
}

# 同一性の公式の証拠（Phase 15）: 型番・JAN を、公式ページに出ている値で確かめた記録。
# config/products.yaml の model_number・jan_code と一致し、ここに証拠があるものだけ「同一性を確認済み」とする
# （商品名だけ・価格の一致だけ・発売年だけで同一性を決めない）
IDENTITY_EVIDENCE = {
    # Sony Store の購入ページの商品データに「PlayStation®5 Pro,CFI-7100B01,…,137980,…,4948872417075」
    # （レビューの ID も 4948872417075・型番 CFI-7100B01）
    "prod_ps5_pro": {"model_number": "CFI-7100B01", "jan_code": "4948872417075", "edition": "日本向け（2025年版）",
                     "bundle": "本体のみ", "url": "https://pur.store.sony.jp/ps5/products/ps5/CFI-7100B01_purchase/",
                     "checked_on": "2026-10-08"},
    # My Nintendo Store の商品ページ（Nintendo Switch 2（日本語・国内専用））の HTML に JAN 4902370553024 だけが出る
    "prod_switch2": {"jan_code": "4902370553024", "edition": "日本語・国内専用", "bundle": "本体のみ",
                     "url": "https://store-jp.nintendo.com/item/hardware-accessory/VM_BEE_S_KB6CA",
                     "checked_on": "2026-10-08"},
    # Apple の購入ページの構造化データ（Offer）に「price 42800・sku MFHP4J/A」
    "prod_airpods_pro3": {"model_number": "MFHP4J/A", "edition": "日本向け", "bundle": "本体（充電ケース付き）",
                          "url": "https://www.apple.com/jp/shop/buy-airpods/airpods-pro-3", "checked_on": "2026-10-08"},
    # ---- Phase 16（2026-10-08 にブラウザで確認）----
    # Apple の購入ページの商品データ（partNumber・price.fullPrice・name）に、256GB の5色の部品番号がどれも 159,800円で並ぶ
    # （512GB は 194,800円で別）。この商品は色を区別しないので、型番1つではなく「同じ容量の色違いの部品番号の組」で確認する
    "prod_iphone17_256": {"model_name": "iPhone 17", "variant_skus": {"MG674J/A": ("256GB", "Black", 159800), "MG684J/A": ("256GB", "White", 159800),
                                           "MG694J/A": ("256GB", "Mist Blue", 159800),
                                           "MG6A4J/A": ("256GB", "Lavender", 159800),
                                           "MG6C4J/A": ("256GB", "Sage", 159800)},
                          "edition": "日本向け（SIM フリー）", "bundle": "本体",
                          "url": "https://www.apple.com/jp/shop/buy-iphone/iphone-17", "checked_on": "2026-10-08"},
    # ニコンの製品ページ「Z8 … オープンプライス JANコード：4960759909947」・ニコンダイレクトの購入ページも同じ JAN・
    # 「こちらの商品はボディーのみの販売となります」
    "prod_z8": {"model_number": "Z8", "jan_code": "4960759909947", "edition": "日本向け", "bundle": "ボディーのみ",
                "url": "https://nij.nikon.com/shop/g/g4960759909947/", "checked_on": "2026-10-08"},
    # キヤノンの製品ページ「EOS R5 Mark II JANコード 4549292-229141 商品コード 6536C001」。購入ページ（6536C001）は
    # 「EOS R5 Mark II・ボディー（レンズは付きません）」。レンズキット（RF24-105L）は別の商品（808,500円）
    "prod_r5ii": {"model_number": "EOS R5 Mark II", "jan_code": "4549292229141", "edition": "日本向け",
                  "bundle": "ボディーのみ（商品コード 6536C001）",
                  "url": "https://personal.canon.jp/product/camera/eos/r5mk2", "checked_on": "2026-10-08"},
    # フジフイルムモールの購入ページ（シルバー）の keywords に「X100VI,X100VIS,X100VI-S,…,4547410554281」。
    # 色ごとに JAN が別（この商品は色を区別しないので JAN は登録しない。型番で確認）。レンズ一体型（キットの区別なし）
    "prod_x100vi": {"model_number": "X100VI", "edition": "日本向け", "bundle": "本体（レンズ一体型）",
                    "colors": {"シルバー": "4547410554281"},
                    "url": "https://mall-jp.fujifilm.com/shop/g/g16941878/", "checked_on": "2026-10-08"},
    # リコーイメージングストアの一覧・商品ページの「商品コード」（GR IV HDF・Monochrome は Phase 15 以前から
    # 型番の欄にこのコードを登録している）。30周年記念キット（S0001522）は別の商品（混ぜない）
    "prod_gr4": {"model_number": "S0001551", "edition": "日本向け", "bundle": "本体（RICOH GR IV【1年保証】）",
                 "url": "https://ricohimagingstore.com/Form/Product/ProductDetail.aspx?shop=0&pid=S0001551",
                 "checked_on": "2026-10-08"},
    "prod_gr4_hdf": {"model_number": "S0001566", "edition": "日本向け", "bundle": "本体（RICOH GR IV HDF【1年保証】）",
                     "url": "https://ricohimagingstore.com/Form/Product/ProductList.aspx?shop=0&cat=002010",
                     "checked_on": "2026-10-08"},
    "prod_gr4_mono": {"model_number": "S0001580", "edition": "日本向け",
                      "bundle": "本体（RICOH GR IV Monochrome【1年保証】）",
                      "url": "https://ricohimagingstore.com/Form/Product/ProductList.aspx?shop=0&cat=002010",
                      "checked_on": "2026-10-08"},
}

# 公式直販価格（OFFICIAL_DIRECT）の証拠（Phase 16。手順6）。official_direct_gate が全部を確かめる。
# - identity_equivalent: JAN の代わりになる強い証拠（色違いが同じ価格・メーカーの部品番号など）。無ければ JAN が要る
# - capacity / body_kit / edition: 公式ストアの商品の容量・ボディーかキットか・版（商品名と食い違えば参考）
# - sale_mode: NORMAL（通常販売）/ MEMBERS_ONLY（無料の会員登録が要る）なら購入できる。LOTTERY・ENDED・PREORDER は参考
# - stock / stock_semantics: 在庫の状態（IN_STOCK / OUT_OF_STOCK / UNKNOWN）と、ページの在庫の表し方。
#   UNKNOWN でも価格は使えるが「今すぐ行動できる」には数えない（在庫ありの明示が要る。opportunity の actionable）
# - rejected: 使えない理由（あれば参考）
OFFICIAL_DIRECT_OFFERS = {
    "prod_iphone17_256": {
        "shop": "Apple Store（オンライン）", "url": "https://www.apple.com/jp/shop/buy-iphone/iphone-17",
        "price": 159800, "checked_on": "2026-10-08", "capacity": "256GB", "body_kit": "not_applicable",
        "edition": "日本向け（SIM フリー）",
        "identity_equivalent": "JAN の代わりに、購入ページの商品データの 256GB の5色の部品番号（IDENTITY_EVIDENCE の "
                               "variant_skus。どの色も 159,800円）",
        "sale_mode": "NORMAL", "stock": "UNKNOWN",
        "stock_semantics": "在庫・お届けの表示は色・容量を選んだ後に出る（ページの初期表示に在庫の情報が無い）",
        "rejected": []},
    "prod_airpods_pro3": {
        "shop": "Apple Store（オンライン）", "url": "https://www.apple.com/jp/shop/buy-airpods/airpods-pro-3",
        "price": 42800, "checked_on": "2026-10-08", "capacity": "", "body_kit": "not_applicable", "edition": "日本向け",
        "identity_equivalent": "Apple の部品番号 MFHP4J/A が購入ページの構造化データの sku と一致（JAN の代わり）",
        "sale_mode": "NORMAL", "stock": "UNKNOWN",
        "stock_semantics": "在庫・お届けの表示は選択を進めた後に出る（ページの初期表示に在庫の情報が無い）",
        "rejected": []},
    "prod_z8": {
        "shop": "ニコンダイレクト", "url": "https://nij.nikon.com/shop/g/g4960759909947/",
        "price": 575300, "checked_on": "2026-10-08", "capacity": "", "body_kit": "body", "edition": "日本向け",
        "identity_equivalent": "", "sale_mode": "NORMAL", "stock": "UNKNOWN",
        "stock_semantics": "購入ページの在庫の欄（spec_stock_msg）が空。「買い物かごに入れる」だけでは在庫ありにしない"
                           "（ログインなしでも買える。送料は会員のログイン時だけ無料）",
        "rejected": []},
    "prod_x100vi": {
        "shop": "フジフイルムモール", "url": "https://mall-jp.fujifilm.com/shop/g/g16941878/",
        "price": 315700, "checked_on": "2026-10-08", "capacity": "", "body_kit": "fixed_lens", "edition": "日本向け",
        "identity_equivalent": "型番 X100VI が一致。シルバー（JAN 4547410554281）とブラックの2色で、どちらも 315,700円"
                               "（色で価格が変わらない。この商品は色を区別しない）",
        "sale_mode": "MEMBERS_ONLY", "stock": "OUT_OF_STOCK",
        "stock_semantics": "「カラーを選択」の欄に色ごとの在庫（2026-10-08 14:31 はシルバー・ブラックとも在庫なし）。"
                           "購入にはフジフイルムメンバーズの登録と本人確認が要る・お一人様1台",
        "rejected": []},
    "prod_r5ii": {
        "shop": "キヤノンオンラインショップ", "url": "https://store.canon.jp/online/g/g6536C001/",
        "price": 654500, "checked_on": "2026-10-08", "capacity": "", "body_kit": "body", "edition": "日本向け",
        "identity_equivalent": "", "sale_mode": "NORMAL", "stock": "IN_STOCK",
        "stock_semantics": "購入ページの「カートに入れる」が押せる状態（在庫切れのときは押せない・在庫の表示が出る）",
        "rejected": []},
}

def _today_jst() -> str:
    from datetime import datetime, timedelta, timezone
    return datetime.now(timezone(timedelta(hours=9))).date().isoformat()


_SALE_MODES_OK = ("NORMAL", "MEMBERS_ONLY")
_STOCKS = ("IN_STOCK", "OUT_OF_STOCK", "UNKNOWN")
_KIT_MARK = ("キット", "kit", "レンズ付", "セット")


def _capacity_of(text: str):
    import re as _re
    m = _re.search(r"(\d+)\s*(GB|TB)", str(text or ""), _re.I)
    if not m:
        return None
    return int(m.group(1)) * (1024 if m.group(2).upper() == "TB" else 1)


def official_direct_gate(product_id: str, product: dict | None, today: str | None = None) -> tuple[bool, tuple[str, ...]]:
    """公式直販価格を確定の仕入れ値に使ってよいか（Phase 16。手順6・7）。使えない理由を全部返す。

    product は config/products.yaml の1件（name・model_number・jan_code）。1つでも欠ければ参考（False）。
    公式ストアに価格があるだけでは通さない。送料は official_shipping の記録（金額・確認日・根拠）が要る。
    """
    from datetime import date

    from src.market import official_shipping as osh
    from src.market.official_price_validator import is_official_domain
    pid = str(product_id or "")
    p = dict(product or {}, id=pid)          # 同一性は判定する商品の ID で見る（渡された行に id が無くても）
    o = OFFICIAL_DIRECT_OFFERS.get(pid)
    v = VERIFIED_URLS.get(pid) or {}
    if not o:
        return False, ("no_official_direct_evidence",)
    reasons: list[str] = []
    if v.get("price_kind") != "official_direct":
        reasons.append("price_kind_not_official_direct")
    # 同一性: 型番が公式の証拠と一致し、JAN も一致するか、JAN の代わりになる証拠がある（商品名だけで決めない）
    ev = IDENTITY_EVIDENCE.get(pid) or {}
    model = str(p.get("model_number") or "").strip()
    jan = str(p.get("jan_code") or "").strip()
    equiv = str(o.get("identity_equivalent") or "").strip()
    # 説明文（identity_equivalent）は JAN の代わりとしてだけ使う。型番（または色違いの部品番号の組）の一致は必ず要る
    # （説明文だけで同一性の確認を飛ばさない。Phase 16 レビュー H-1）
    group = _variant_group_ok(p, ev) and not model and not jan
    if pid in USER_DECISIONS or pid in OFFICIAL_NOT_SOLD or identity_state(p)[0] != "IDENTITY_CONFIRMED":
        reasons.append("identity_not_confirmed")
    if not (model and ev.get("model_number") == model) and not group:
        reasons.append("model_not_exact")
    if model and ev.get("model_number") and ev["model_number"] != model:
        reasons.append("model_mismatch")
    if not (jan and ev.get("jan_code") == jan) and not (equiv and (group or model)):
        reasons.append("jan_not_exact")
    if group and o.get("price") not in {pr for _c, _col, pr in ev["variant_skus"].values()}:
        reasons.append("no_current_price")
    if jan and ev.get("jan_code") and ev["jan_code"] != jan:
        reasons.append("jan_mismatch")
    # 容量・ボディーかキットか・版
    cap_p, cap_o = _capacity_of(p.get("name")), _capacity_of(o.get("capacity"))
    if cap_p != cap_o:
        reasons.append("capacity_mismatch")
    kit_p = any(k in str(p.get("name") or "").lower() for k in _KIT_MARK)
    bk = o.get("body_kit")
    if bk not in ("body", "fixed_lens", "not_applicable", "kit") or (bk == "kit") != kit_p:
        reasons.append("body_kit_mismatch")
    if not str(o.get("edition") or "").startswith("日本向け"):
        reasons.append("edition_unknown")
    # 公式ストアの購入ページ・表示中の価格（記録と同じ値）
    if not (v.get("url") and v["url"] == o.get("url") and is_official_domain(v.get("source", ""), v["url"])):
        reasons.append("not_official_shop")
    if v.get("link_type") != "item":
        reasons.append("not_purchase_page")
    if not (isinstance(o.get("price"), int) and o["price"] > 0 and o["price"] == v.get("price")):
        reasons.append("no_current_price")
    # 送料（分からなければ 0円とみなさない）
    ship = osh.purchase_shipping(pid, v.get("url", ""), v.get("price"))
    if ship["fee"] is None:
        reasons.append("shipping_unknown")
    elif ship.get("source") != v.get("source") or not ship.get("checked_on"):
        reasons.append("shipping_source_mismatch")       # 別の店の送料の記録を使わない（監査 L-5）
    # 購入できる販売の形・在庫の表し方
    if o.get("sale_mode") not in _SALE_MODES_OK:
        reasons.append("sale_mode_not_purchasable")
    if o.get("stock") not in _STOCKS or not str(o.get("stock_semantics") or "").strip():
        reasons.append("stock_semantics_unknown")
    # 確認日（あること・未来でないこと・記録の確認日と同じ）
    day = str(o.get("checked_on") or "")
    try:
        d = date.fromisoformat(day)
        if d > date.fromisoformat(today or _today_jst()):
            reasons.append("verified_at_in_future")
        if day != v.get("checked_on"):
            reasons.append("verified_at_mismatch")
    except ValueError:
        reasons.append("no_verified_at")
    for r in o.get("rejected") or []:
        reasons.append(f"rejected:{r}")
    return not reasons, tuple(reasons)


def official_direct_audit(products: list[dict], today: str | None = None, recheck: list[dict] | None = None) -> list[dict]:
    """公式直販価格の監査（商品ごと: 価格・送料・在庫・使えるか・理由）。運営者向けの画面と集計で使う。

    登録表の判定（official_direct_gate）に加えて、今の状態も見る（Phase 16 監査 M-3）:
    - recheck（exports/official_recheck/latest.json の results）で、記録と同じ URL・価格に対する changed / sale_ended が
      あれば使えない（人の確認待ち）
    - 確認日（記録の確認日か、記録と同じ価格の unchanged の再確認の日の新しいほう）から
      OFFICIAL_DIRECT_STALE_DAYS（14日）を過ぎていれば使えない（古い）
    """
    from datetime import date

    from src.market import official_shipping as osh
    from src.market.normalized_prices import OFFICIAL_DIRECT_STALE_DAYS
    byid = {str(p.get("id") or p.get("product_id") or ""): p for p in products or []}
    t = date.fromisoformat(today or _today_jst())
    rows = []
    for pid, o in OFFICIAL_DIRECT_OFFERS.items():
        ok, why = official_direct_gate(pid, byid.get(pid), today)
        why = list(why)
        v = VERIFIED_URLS.get(pid) or {}
        last = str(v.get("checked_on") or "")
        for r in recheck or []:
            if not (isinstance(r, dict) and r.get("product_id") == pid and r.get("url") == v.get("url")
                    and r.get("recorded_price") == v.get("price")):
                continue
            day = str(r.get("observed_at") or "")[:10]
            if r.get("status") in ("changed", "sale_ended"):
                why.append(f"recheck_{r['status']}")
            elif r.get("status") == "unchanged" and r.get("price") == v.get("price") and last < day <= t.isoformat():
                last = day
        try:
            if (t - date.fromisoformat(last)).days > OFFICIAL_DIRECT_STALE_DAYS:
                why.append("verified_at_stale")
        except ValueError:
            pass
        ship = osh.purchase_shipping(pid, v.get("url", ""), v.get("price"))
        rows.append({"product_id": pid, "name": (byid.get(pid) or {}).get("name", pid), "shop": o["shop"],
                     "price": o.get("price"), "url": o.get("url"), "msrp": MSRP_OF.get(pid, ""),
                     "shipping_fee": ship["fee"], "shipping_status": ship["status"],
                     "stock": o.get("stock"), "sale_mode": o.get("sale_mode"), "verified_at": last,
                     "eligible": ok and not why, "reasons": why})
    return rows


# 公式の情報でも、この商品がどの版か決められないもの（Phase 15。推測で DB を書き換えない。ユーザーの判断を待つ）
# Phase 16（2026-10-08）にもう一度公式ページを確認した。どれも1つの候補に絞れない
USER_DECISIONS = {
    "prod_ps5_de": {
        "question": "この商品（型番の登録なし・設定の参考価格 72,980円）は、どの版のデジタル・エディションか",
        "candidates": ["日本語専用（公式で販売中・希望小売価格 55,000円。買取商店の行は CFI-2200B01・JAN 4948872417419）",
                       "日本語専用 DualSense ダブルパック（希望小売価格 65,000円・コントローラー2台のセット）",
                       "“Marvel’s Wolverine” バトルイエロー リミテッドエディション（96,980円・ソフト同梱の数量限定）",
                       "多言語の版（公式の本体ラインナップに無い）"],
        "found": "PlayStation 公式の本体ラインナップ（2026-10-08 再確認）のデジタル・エディションは日本語専用の3種類だけ。"
                 "参考価格 72,980円はどれとも合わない。価格の一致だけで版を決めない",
    },
    "prod_xbox_sx": {
        "question": "この商品（型番の登録なし・設定の参考価格 59,978円は旧価格）は、どの型か",
        "candidates": ["ディスク ドライブ 1TB（カーボン ブラック）", "オール デジタル 1TB（ロボット ホワイト）",
                       "ディスク ドライブ X25 限定エディション"],
        "found": "Xbox 公式の製品ページ（2026-10-08 再確認）に3つの型。表示中の価格は 109,980円（税込・オール デジタル）。"
                 "旧価格の一致だけで型を決めない。買取商店に行は無い",
    },
    "prod_switch2_mk": {
        "question": "この商品（設定の参考価格 59,980円）は、どのマリオカート入りのセットか",
        "candidates": ["Nintendo Switch 2 日本語・国内専用 マリオカート ワールド セット（生産終了。買取商店の行の "
                       "JAN 4902370553031）",
                       "Nintendo Switch 2（日本語・国内専用）選べるソフト セット（マリオカート ワールドなど3本から1本。"
                       "My Nintendo Store で予約 63,980円）"],
        "found": "任天堂公式の商品ラインナップ（2026-10-08 再確認）で、マリオカート ワールド セットは日本語・国内専用だけが"
                 "「生産終了」に載る（多言語対応のマリオカート セットは無い）。一方 My Nintendo Store に、マリオカート ワールドを"
                 "選べる新しい本体セット（予約）がある。参考価格はどちらとも合わない。単体の Switch 2 とは別の商品として扱う",
    },
}

IDENTITY_STATES = ("IDENTITY_CONFIRMED", "PARTIAL_IDENTITY", "AMBIGUOUS", "DISCONTINUED", "NEEDS_USER_DECISION")


def _variant_group_ok(product: dict, ev: dict) -> bool:
    """色だけが違う部品番号の組（variant_skus: 部品番号 → (容量, 色, 価格)）で、この商品と同じものだと言えるか。

    2件以上・容量がすべて商品名の容量と同じ・価格がすべて同じ、のときだけ（容量や価格の違う番号が混ざれば使わない）。
    """
    skus = ev.get("variant_skus") or {}
    if len(skus) < 2:
        return False
    # 商品名の機種が証拠の機種と同じ（「iPhone 17 Pro」に書き換えたら使わない。再レビュー R-1）
    from src.market.price_quality import model_compatible
    if not ev.get("model_name") or model_compatible(str(product.get("name") or ""), ev["model_name"]) is not True:
        return False
    caps = {_capacity_of(c) for c, _col, _p in skus.values()}
    prices = {pr for _c, _col, pr in skus.values()}
    cap_p = _capacity_of(product.get("name"))
    return cap_p is not None and caps == {cap_p} and len(prices) == 1 and all(
        isinstance(x, int) and x > 0 for x in prices)


def identity_state(product: dict) -> tuple[str, str]:
    """商品の同一性の状態と理由（product は config/products.yaml の1件の形: id・name・model_number・jan_code）。

    - NEEDS_USER_DECISION: 公式の情報でも版が決められない（USER_DECISIONS）
    - DISCONTINUED: 公式で販売終了（OFFICIAL_NOT_SOLD）
    - IDENTITY_CONFIRMED: 型番か JAN が登録されていて、その値を公式ページで確かめた証拠がある（IDENTITY_EVIDENCE）
    - PARTIAL_IDENTITY: 型番か JAN の登録はあるが公式の証拠が無い、または商品名に容量など一部の区別がある
    - AMBIGUOUS: 型番も JAN も無い
    """
    pid = str(product.get("id") or product.get("product_id") or "")
    model = str(product.get("model_number") or product.get("model") or "").strip()
    jan = str(product.get("jan_code") or product.get("jan") or "").strip()
    if pid in USER_DECISIONS:
        return "NEEDS_USER_DECISION", USER_DECISIONS[pid]["question"]
    if pid in OFFICIAL_NOT_SOLD:
        return "DISCONTINUED", OFFICIAL_NOT_SOLD[pid]["reason"]
    ev = IDENTITY_EVIDENCE.get(pid) or {}
    if not model and not jan and _variant_group_ok(product, ev):
        return "IDENTITY_CONFIRMED", (f"公式ページで同じ容量の色違いの部品番号 {len(ev['variant_skus'])}件"
                                      "（どれも同じ価格）を確認")
    ok_model = bool(model) and ev.get("model_number") == model
    ok_jan = bool(jan) and ev.get("jan_code") == jan
    # 証拠に書いた値と登録の値が食い違う（片方だけ一致・片方は別の値）なら確認済みにしない
    conflict = ((ev.get("model_number") and model and ev["model_number"] != model)
                or (ev.get("jan_code") and jan and ev["jan_code"] != jan))
    if (ok_model or ok_jan) and not conflict:
        return "IDENTITY_CONFIRMED", "公式ページで " + "・".join(
            x for x in (f"型番 {model}" if ok_model else "", f"JAN {jan}" if ok_jan else "") if x) + " を確認"
    if model or jan:
        return "PARTIAL_IDENTITY", "型番・JAN の登録はあるが公式ページの証拠が無い" if not conflict \
            else "登録の型番・JAN が公式の証拠と食い違う"
    return "AMBIGUOUS", "型番も JAN も無い（商品名・容量などで照合している）"


def identity_audit(products: list[dict]) -> dict:
    """45商品の同一性の監査（状態ごとの件数と商品ごとの行）。"""
    rows = []
    for p in products:
        st, why = identity_state(p)
        pid = str(p.get("id") or p.get("product_id") or "")
        rows.append({"product_id": pid, "name": p.get("name", ""), "state": st, "reason": why,
                     "model_number": p.get("model_number") or p.get("model") or "",
                     "jan_code": p.get("jan_code") or p.get("jan") or ""})
    counts = {s: sum(1 for r in rows if r["state"] == s) for s in IDENTITY_STATES}
    counts["missing_model"] = sum(1 for r in rows if not r["model_number"])
    counts["missing_jan"] = sum(1 for r in rows if not r["jan_code"])
    return {"counts": counts, "products": rows}


def records() -> list[dict]:
    """商品ごとの公式の確認を1つの形にまとめたもの（読むだけ。表の値をそのまま並べ替える）。

    product_id・official_url・verification_type（verified / not_sold / unverified）・price_kind・verified_price・
    verified_at（価格を確認した日）・sale_status・stock_status・stock_checked_at（在庫を確認した時刻）
    """
    out = []
    for pid, v in VERIFIED_URLS.items():
        out.append({"product_id": pid, "official_url": v["url"], "verification_type": "verified",
                    "price_kind": v.get("price_kind") or ("open_price" if v.get("open_price") else "msrp"),
                    "verified_price": v.get("price"), "verified_at": v.get("checked_on", VERIFIED_URLS_CHECKED_ON),
                    "sale_status": "ON_SALE", "stock_status": v.get("stock") or "",
                    "stock_checked_at": v.get("stock_checked_at") or "", "source": v["source"]})
    for pid, u in OFFICIAL_NOT_SOLD.items():
        out.append({"product_id": pid, "official_url": "", "verification_type": "not_sold", "price_kind": "",
                    "verified_price": None, "verified_at": u["checked_on"], "sale_status": "OFFICIAL_NOT_SOLD",
                    "stock_status": "", "stock_checked_at": "", "source": u["source"]})
    for pid, u in UNVERIFIED.items():
        out.append({"product_id": pid, "official_url": "", "verification_type": "unverified", "price_kind": "",
                    "verified_price": None, "verified_at": "", "sale_status": "UNKNOWN", "stock_status": "",
                    "stock_checked_at": "", "source": u["source"]})
    return out

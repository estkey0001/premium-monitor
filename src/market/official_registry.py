"""公式の確認の記録の正本（Phase 15。以前は scripts/audit_official_sources.py にあった表をそのまま移した）。

ここだけを読めば、商品ごとの公式の確認（公式 URL・確認の種類・価格・確認日・販売の状態・在庫・同一性の証拠）が分かる。
scripts/audit_official_sources.py は、ここの表を import して DB（products・product_source_config）に書く。

価格の意味（price_kind。Phase 15）:
- "msrp": メーカーが「希望小売価格」「定価」と明示している価格
- "official_direct": メーカーの公式ストアの販売価格（希望小売価格とは呼ばない。Apple Store など）
- "open_price": メーカーの希望小売価格はオープン価格（架空の希望小売価格を作らない）
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
    "prod_iphone17_256":    {"source": "src_apple_jp", "url": "https://www.apple.com/jp/shop/buy-iphone/iphone-17",         "link_type": "item",     "price": 159800, "conf": "high", "checked_on": "2026-10-03", "price_kind": "official_direct"},
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
    # ---- Nikon（オープン価格・URLは検証済みだが公式定価なし → category/価格null）----
    "prod_z8": {"source": "src_nikon_direct", "url": "https://nij.nikon.com/products/lineup/mirrorless/z8/", "link_type": "category", "price": None, "conf": "medium", "open_price": True, "price_kind": "open_price"},
    # ---- Fujifilm（オープン価格）----
    "prod_x100vi": {"source": "src_fujifilm_official", "url": "https://www.fujifilm-x.com/ja-jp/products/cameras/x100vi/", "link_type": "category", "price": None, "conf": "medium", "open_price": True, "price_kind": "open_price"},
}

# 検証できなかった/公式定価が存在しないメーカー（推測URLで verified 扱いしない）
# 実際の型番（同一性確認用）
UNVERIFIED = {
    "prod_r5ii":  {"source": "src_canon_official", "model": "EOS R5 Mark II",  "reason": "canon.jp が当環境からDNS解決不可（要手動検証）"},
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
#   その販売価格が仕入れ値になる）。この扱いは変えない
# - Sony（PS5 Pro）: PlayStation 公式の本体ラインナップに「希望小売価格：137,980円（税込）」→ msrp
# - Nintendo（Switch 2）: 任天堂公式の商品ラインナップに「希望小売価格： 59,980 円（税込）」→ msrp
# - Nikon（Z8）・Fujifilm（X100VI）: 希望小売価格はオープン価格 → open_price（価格を持たない）
PRICE_KINDS = ("msrp", "official_direct", "open_price")

# カメラのメーカー直販の監査（Phase 15。2026-10-08 にブラウザで確認。手順21）
# 希望小売価格（オープン価格）と、公式ストアの販売価格は別のもの。直販の販売価格は記録のみ（確定の仕入れ値に
# 自動では使わない。使うかはユーザーの判断。架空の希望小売価格は作らない）
CAMERA_DIRECT_SALE_AUDIT = {
    "src_fujifilm_official": {"shop": "フジフイルムモール", "msrp": "オープン価格",
                              "example": "X100VI シルバー 315,700円（税込）・在庫なし・5,000円以上送料無料",
                              "url": "https://mall-jp.fujifilm.com/shop/g/g16941878/", "checked_on": "2026-10-08"},
    "src_nikon_direct": {"shop": "ニコンダイレクト", "msrp": "（製品ページに希望小売価格の表示なし）",
                         "example": "Z8 ニコンダイレクト販売価格 575,300円（税込）",
                         "url": "https://nij.nikon.com/products/lineup/mirrorless/z8/", "checked_on": "2026-10-08"},
    "src_canon_official": {"shop": "キヤノンオンラインショップ", "msrp": "オープン価格",
                           "example": "EOS R5 Mark II・ボディー キヤノンオンラインショップ価格 654,500円（税込）",
                           "url": "https://personal.canon.jp/product/camera/eos/r5mk2", "checked_on": "2026-10-08"},
    "src_ricoh_imaging": {"shop": "リコーイメージングストア", "msrp": "公式ストアが「定価」と表記",
                          "example": "GR IV 系は抽選販売（定価の表記）",
                          "url": "https://ricohimagingstore.com/Page/GR.aspx", "checked_on": "2026-10-08"},
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
}

# 公式の情報でも、この商品がどの版か決められないもの（Phase 15。推測で DB を書き換えない。ユーザーの判断を待つ）
USER_DECISIONS = {
    "prod_ps5_de": {
        "question": "この商品（型番の登録なし・設定の参考価格 72,980円）は、どの版のデジタル・エディションか",
        "candidates": ["日本語専用（公式で販売中・希望小売価格 55,000円。買取商店の行は CFI-2200B01・JAN 4948872417419）",
                       "多言語の版（公式の本体ラインナップに無い）"],
        "found": "PlayStation 公式の本体ラインナップ（2026-10-08）は日本語専用だけ。価格の一致だけで版を決めない",
    },
    "prod_xbox_sx": {
        "question": "この商品（型番の登録なし・設定の参考価格 59,978円は旧価格）は、どの型か",
        "candidates": ["ディスク ドライブ 1TB（カーボン ブラック）", "オール デジタル 1TB（ロボット ホワイト）",
                       "ディスク ドライブ X25 限定エディション"],
        "found": "Xbox 公式の製品ページ（2026-10-08）に複数の型。表示中の価格は 109,980円（税込）。買取商店に行は無い",
    },
    "prod_switch2_mk": {
        "question": "この商品（設定の参考価格 59,980円）は、日本語・国内専用のセットか、多言語のセットか",
        "candidates": ["Nintendo Switch 2 マリオカート ワールドセット 日本語・国内専用（買取商店の行の JAN 4902370553031）",
                       "多言語対応のセット"],
        "found": "任天堂公式のラインナップでマリオカート ワールド セットは「生産終了」（2026-10-03）。"
                 "登録の参考価格が国内専用版と合わない（Phase 11）。単体の Switch 2 とは別の商品として扱う",
    },
}

IDENTITY_STATES = ("IDENTITY_CONFIRMED", "PARTIAL_IDENTITY", "AMBIGUOUS", "DISCONTINUED", "NEEDS_USER_DECISION")


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

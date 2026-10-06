# Official Source Registry & Validation

> 生成: 2026-10-06 12:08 JST / 公式ソース登録・検証（利益/AI/Opportunity/Notification/Capital/Execution は不変）

## メーカー別サマリ
| Maker | Products | URL verified | HTTP200 | exact match | price auto | high conf | failed |
|---|--:|--:|--:|--:|--:|--:|--:|
| Apple | 14 | 5 | 5 | 2 | 2 | 2 | 9 |
| Sony | 5 | 1 | 1 | 1 | 1 | 1 | 4 |
| Nintendo | 2 | 1 | 1 | 0 | 1 | 0 | 1 |
| Nikon | 3 | 1 | 1 | 0 | 0 | 0 | 2 |
| FUJIFILM | 1 | 1 | 1 | 0 | 0 | 0 | 0 |
| Canon | 3 | 0 | 0 | 0 | 0 | 0 | 3 |

## 自動取得率 Before → After
- Before: 公式定価あり商品 3 / 公式config 7
- After: URL検証済 9 / 価格取得 4 （検証対象 9 / 検証不能 9）

## Apple Source Audit（旧URL検出）
| product | current_url | http | action | note |
|---|---|--:|---|---|
| prod_iphone16pm_256 | https://www.apple.com/jp/shop/buy-iphone/iphone-16-pro-max | 404 | replace(old/404) | iPhone 16 世代の購入ページ。iphone-17-pro ページに統合/404 |
| prod_iphone16pm_512 | https://www.apple.com/jp/shop/buy-iphone/iphone-16-pro-max | 404 | replace(old/404) | iPhone 16 世代の購入ページ。iphone-17-pro ページに統合/404 |

## 自動取得できた公式価格（検証済）
| product | source | price | link_type | confidence |
|---|---|--:|---|---|
| prod_iphone17_256 | src_apple_jp | ¥159,800 | item | high |
| prod_airpods_pro3 | src_apple_jp | ¥42,800 | item | high |
| prod_ps5_pro | src_sony_store | ¥137,980 | item | high |
| prod_switch2 | src_nintendo_store | ¥59,980 | category | medium |

## 検証不能（要手動検証・推測登録しない）
| product | source | reason |
|---|---|---|
| prod_r5ii | src_canon_official | canon.jp が当環境からDNS解決不可（要手動検証） |
| prod_r6ii | src_canon_official | canon.jp が当環境からDNS解決不可（要手動検証） |
| prod_r3 | src_canon_official | canon.jp が当環境からDNS解決不可（要手動検証） |
| prod_z9 | src_nikon_direct | オープン価格の可能性・個別URL未検証 |
| prod_zf | src_nikon_direct | オープン価格の可能性・個別URL未検証 |
| prod_a1ii | src_sony_store | store.sony.jp が当環境からDNS解決不可（要手動検証） |
| prod_a7rv | src_sony_store | store.sony.jp が当環境からDNS解決不可（要手動検証） |
| prod_a7cr | src_sony_store | store.sony.jp が当環境からDNS解決不可（要手動検証） |
| prod_fx3 | src_sony_store | store.sony.jp が当環境からDNS解決不可（要手動検証） |
| prod_iphone17pro_256 | src_apple_jp | iPhone 17 Pro の購入ページが /buy-iphone へ移動。公式は iPhone 18 Pro を販売中 |
| prod_iphone17pro_512 | src_apple_jp | iPhone 17 Pro の購入ページが /buy-iphone へ移動。公式は iPhone 18 Pro を販売中 |
| prod_iphone17pm_256 | src_apple_jp | iPhone 17 Pro Max の購入ページが /buy-iphone へ移動。公式は iPhone 18 Pro Max を販売中 |
| prod_iphone17pm_512 | src_apple_jp | iPhone 17 Pro Max の購入ページが /buy-iphone へ移動。公式は iPhone 18 Pro Max を販売中 |
| prod_ipad_pro_m4_11 | src_apple_jp | 公式の iPad Pro は M5 チップ（M4 は販売していない） |
| prod_ipad_pro_m4_13 | src_apple_jp | 公式の iPad Pro は M5 チップ（M4 は販売していない） |
| prod_ipad_air_m3 | src_apple_jp | 公式の iPad Air は M4 チップ（M3 は販売していない） |
| prod_apple_watch_s11 | src_apple_jp | 公式は Apple Watch Series 12 を販売中（Series 11 は販売していない） |
| prod_apple_watch_ultra3 | src_apple_jp | 公式は Apple Watch Ultra 4 を販売中（Ultra 3 は販売していない） |
| prod_switch2_mk | src_nintendo_store | 任天堂公式のラインナップでマリオカート ワールド セットは「生産終了」 |

## 次に改善すべきsource
1. **EBAY_APP_ID 設定**（海外相場の自動fresh化・最優先）
2. **Canon/Sony 公式ストアの手動URL検証**（当環境からDNS不可のため）
3. **Apple 512GB等の個別config価格**（購入フローの個別ページ）

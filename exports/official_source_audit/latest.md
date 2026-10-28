# Official Source Registry & Validation

> 生成: 2026-10-28 19:34 JST / 公式ソース登録・検証（利益/AI/Opportunity/Notification/Capital/Execution は不変）

## メーカー別サマリ
| Maker | Products | URL verified | HTTP200 | exact match | price auto | high conf | failed |
|---|--:|--:|--:|--:|--:|--:|--:|
| Apple | 21 | 4 | 4 | 4 | 4 | 4 | 17 |
| Sony | 6 | 1 | 1 | 1 | 1 | 1 | 5 |
| Nintendo | 2 | 1 | 1 | 1 | 1 | 1 | 1 |
| Nikon | 3 | 2 | 2 | 2 | 2 | 2 | 1 |
| FUJIFILM | 1 | 1 | 1 | 1 | 1 | 1 | 0 |
| Canon | 3 | 2 | 2 | 2 | 2 | 2 | 1 |
| RICOH | 1 | 0 | 0 | 0 | 0 | 0 | 1 |

## 自動取得率 Before → After
- Before: 公式定価あり商品 3 / 公式config 7
- After: URL検証済 11 / 価格取得 11 （検証対象 11 / 検証不能 6）

## Apple Source Audit（旧URL検出）
| product | current_url | http | action | note |
|---|---|--:|---|---|
| prod_iphone16pm_256 | https://www.apple.com/jp/shop/buy-iphone/iphone-16-pro-max | 404 | replace(old/404) | iPhone 16 世代の購入ページ。iphone-17-pro ページに統合/404 |
| prod_iphone16pm_512 | https://www.apple.com/jp/shop/buy-iphone/iphone-16-pro-max | 404 | replace(old/404) | iPhone 16 世代の購入ページ。iphone-17-pro ページに統合/404 |

## 自動取得できた公式価格（検証済）
| product | source | price | link_type | confidence |
|---|---|--:|---|---|
| prod_iphone17_256 | src_apple_jp | ¥159,800 | item | high |
| prod_iphoneair_256 | src_apple_jp | ¥189,800 | item | high |
| prod_iphoneduo_256 | src_apple_jp | ¥364,800 | item | high |
| prod_airpods_pro3 | src_apple_jp | ¥42,800 | item | high |
| prod_ps5_pro | src_sony_store | ¥137,980 | item | high |
| prod_switch2 | src_nintendo_store | ¥59,980 | item | high |
| prod_z8 | src_nikon_direct | ¥575,300 | item | high |
| prod_z9 | src_nikon_direct | ¥772,200 | item | high |
| prod_x100vi | src_fujifilm_official | ¥315,700 | item | high |
| prod_r5ii | src_canon_official | ¥654,500 | item | high |
| prod_r6ii | src_canon_official | ¥319,000 | item | high |

## 設定の参考価格と公式で確認した価格の違い（読むだけ・人の確認待ち。自動で書き換えない）
| product | 設定の価格 | 確認した価格 | 差 |
|---|--:|--:|--:|
| prod_airpods_pro3 | ¥39,800 | ¥42,800 | +3,000 |
| prod_gr4 | ¥194,800 | ¥211,800 | +17,000 |
| prod_gr4_hdf | ¥0 | ¥222,000 | +222,000 |
| prod_gr4_mono | ¥283,800 | ¥299,800 | +16,000 |
| prod_iphone17_256 | ¥139,800 | ¥159,800 | +20,000 |
| prod_r5ii | ¥620,000 | ¥654,500 | +34,500 |
| prod_x100vi | ¥269,500 | ¥315,700 | +46,200 |
| prod_z8 | ¥590,000 | ¥575,300 | -14,700 |

## 識別の手がかりの割合（読むだけ）
- 商品 47: 部品番号 2件（4.3%） / 型番 24件（51.1%） / JAN 6件（12.8%） / 公式 URL 2件（4.3%） / 公式の証拠 14件（29.8%） / 強い手がかりのどれか 27件（57.4%）

## 検証不能（要手動検証・推測登録しない）
| product | source | reason |
|---|---|---|
| prod_r3 | src_canon_official | canon.jp が当環境からDNS解決不可（要手動検証） |
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
| prod_iphone16pro_256 | src_apple_jp | iPhone 16 Pro の購入ページが /jp/iphone へ移動。公式は iPhone 18 Pro を販売中 |
| prod_iphone16pm_256 | src_apple_jp | iPhone 16 Pro Max は公式で販売していない（公式は iPhone 18 Pro Max を販売中） |
| prod_iphone16pm_512 | src_apple_jp | iPhone 16 Pro Max は公式で販売していない（公式は iPhone 18 Pro Max を販売中） |
| prod_airpods_max | src_apple_jp | AirPods Max の購入ページが AirPods Max 2 へ移動（初代は販売していない） |
| prod_mac_mini_m4 | src_apple_jp | 公式の Mac mini は M6・M5 Pro チップ（M4 は販売していない） |
| prod_macbook_air_m4_13 | src_apple_jp | 公式の MacBook Air は M5 チップ（M4 は販売していない） |
| prod_macbook_air_m4_15 | src_apple_jp | 公式の MacBook Air は M5 チップ（M4 は販売していない） |
| prod_macbook_pro_m4_14 | src_apple_jp | 公式の MacBook Pro は M5・M5 Pro・M5 Max チップ（M4 は販売していない） |
| prod_ps5_de | src_sony_store | 公式の本体ラインナップのデジタル・エディションは日本語専用（55,000円）だけ。この商品の版は無い |
| prod_gr3 | src_ricoh_imaging | RICOH の製品ページに「RICOH GRIII 生産終了」 |

## 次に改善すべきsource
1. **EBAY_APP_ID 設定**（海外相場の自動fresh化・最優先）
2. **Canon/Sony 公式ストアの手動URL検証**（当環境からDNS不可のため）
3. **Apple 512GB等の個別config価格**（購入フローの個別ページ）

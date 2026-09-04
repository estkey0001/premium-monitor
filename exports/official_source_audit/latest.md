# Official Source Registry & Validation

> 生成: 2026-09-04 17:10 JST / 公式ソース登録・検証（利益/AI/Opportunity/Notification/Capital/Execution は不変）

## メーカー別サマリ
| Maker | Products | URL verified | HTTP200 | exact match | price auto | high conf | failed |
|---|--:|--:|--:|--:|--:|--:|--:|
| Apple | 14 | 14 | 14 | 7 | 9 | 7 | 0 |
| Nikon | 3 | 1 | 1 | 0 | 0 | 0 | 2 |
| FUJIFILM | 1 | 1 | 1 | 0 | 0 | 0 | 0 |
| Canon | 3 | 0 | 0 | 0 | 0 | 0 | 3 |
| Sony | 4 | 0 | 0 | 0 | 0 | 0 | 4 |

## 自動取得率 Before → After
- Before: 公式定価あり商品 4 / 公式config 7
- After: URL検証済 16 / 価格取得 9 （検証対象 16 / 検証不能 9）

## Apple Source Audit（旧URL検出）
| product | current_url | http | action | note |
|---|---|--:|---|---|
| prod_iphone16pm_256 | https://www.apple.com/jp/shop/buy-iphone/iphone-16-pro-max | 404 | replace(old/404) | iPhone 16 世代の購入ページ。iphone-17-pro ページに統合/404 |
| prod_iphone16pm_512 | https://www.apple.com/jp/shop/buy-iphone/iphone-16-pro-max | 404 | replace(old/404) | iPhone 16 世代の購入ページ。iphone-17-pro ページに統合/404 |

## 自動取得できた公式価格（検証済）
| product | source | price | link_type | confidence |
|---|---|--:|---|---|
| prod_iphone17_256 | src_apple_jp | ¥142,800 | item | high |
| prod_iphone17pro_256 | src_apple_jp | ¥194,800 | item | high |
| prod_iphone17pm_256 | src_apple_jp | ¥214,800 | item | high |
| prod_ipad_pro_m4_11 | src_apple_jp | ¥209,800 | item | high |
| prod_ipad_pro_m4_13 | src_apple_jp | ¥269,800 | item | high |
| prod_ipad_air_m3 | src_apple_jp | ¥129,800 | item | high |
| prod_apple_watch_s11 | src_apple_jp | ¥71,800 | category | medium |
| prod_apple_watch_ultra3 | src_apple_jp | ¥142,800 | category | medium |
| prod_airpods_pro3 | src_apple_jp | ¥42,800 | item | high |

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

## 次に改善すべきsource
1. **EBAY_APP_ID 設定**（海外相場の自動fresh化・最優先）
2. **Canon/Sony 公式ストアの手動URL検証**（当環境からDNS不可のため）
3. **Apple 512GB等の個別config価格**（購入フローの個別ページ）

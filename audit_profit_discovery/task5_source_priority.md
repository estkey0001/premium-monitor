# Task5: 次に取得優先度が高い価格ソース ランキング

不足データ取得で解放される潜在利益(合計)順。

## price_type 別

| 順位 | price_type | 解放件数 | 潜在利益合計 |
|---|---|---|---|
| 1 | overseas_sold_price | 4 | +¥426,304 |
| 2 | buyback_price | 4 | +¥232,251 |

## source/type 別 TOP10

| 順位 | source/type | 件数 | 潜在利益合計 |
|---|---|---|---|
| 1 | src_ebay/overseas_sold_price | 4 | +¥426,304 |
| 2 | ゲオ/buyback_price | 2 | +¥190,395 |
| 3 | モバイル一番/buyback_price | 1 | +¥29,656 |
| 4 | 買取商店/buyback_price | 1 | +¥12,200 |

## 推奨取得優先（運用的根拠）
1. **eBay sold（海外成約相場）の fresh 化** = EBAY_APP_ID 設定。stale(19.5日)で全除外中。最大の解放余地。
2. **メルカリ sold / ヤフオク落札（flea_sold）** = より安い buy 候補。買い側を下げ ROI 改善。
3. **フジヤ/マップ等の販売価格(shop_sale)を item_url 付きで取得** = buy の信頼性向上。
4. 国内買取の日次 fresh 維持（PS5/Switch は ¥0 や stale が多数）。

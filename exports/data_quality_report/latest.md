# データ取得品質レポート（2026-10-08 00:27 JST）

## 取得成功率
- 全対象店舗数: 16
- 成功店舗数: 2
- 全失敗店舗数: 12
- ジョブ成功率: 22.4%（OK 13 / 失敗 41 / SKIP 4 / 計 58）

## 前回比較
- 前回成功率: 25.9%
- 今回成功率: 22.4%
- 変化: -3.5pt（悪化）
- 7日移動平均: 22.0%
- 主要失敗理由 TOP5: price_not_found 9, product_not_listed 8, rate_limited_429 6, http_403 6, robots_unreachable 4

## 店舗別成功率（低い順）
- 2ndstreet（optional）: 0%（OK 0/失敗 4・price_not_found）
- bookoff（optional）: 0%（OK 0/失敗 0・not_supported）
- dosupara（optional）: 0%（OK 0/失敗 2・http_404）
- geo（optional）: 0%（OK 0/失敗 2・price_not_found）
- geo_mobile（optional）: 0%（OK 0/失敗 4・robots_unreachable）
- hardoff（optional）: 0%（OK 0/失敗 2・http_404）
- iosys: 0%（OK 0/失敗 6・http_403）
- janpara（optional）: 0%（OK 0/失敗 6・rate_limited_429）
- mobile_ichiban: 0%（OK 0/失敗 5・product_not_listed）
- netoff（optional）: 0%（OK 0/失敗 4・price_not_found）
- pasoko（optional）: 0%（OK 0/失敗 2・product_not_listed）
- sofmap（optional）: 0%（OK 0/失敗 2・service_unavailable）

## 商品別成功率
- ps5_pro: 10.0%
- switch2: 11.1%
- iphone17pro256: 25.0%
- iphone17pro512: 25.0%
- iphone17pm256: 25.0%
- iphone17pm512: 25.0%
- iphone17_256: 100.0%
- iphone16pro256: 100.0%
- airpods_pro3: 100.0%

## 連続失敗店舗（2回以上）
- 2ndstreet: 185回連続
- bookoff: 185回連続
- dosupara: 185回連続
- geo_mobile: 185回連続
- hardoff: 185回連続
- janpara: 185回連続
- pasoko: 185回連続
- sofmap: 185回連続
- surugaya: 185回連続
- tsutaya: 185回連続
- iosys: 118回連続
- netoff: 45回連続
- geo: 24回連続

## 改善優先順位（required店舗）
1. iosys（失敗6 / http_403）
2. mobile_ichiban（失敗5 / product_not_listed）

## 失敗理由（内訳）
- price_not_found: 9件
- product_not_listed: 8件
- rate_limited_429: 6件
- http_403: 6件
- robots_unreachable: 4件
- http_404: 4件
- not_supported: 4件
- service_unavailable: 2件
- site_blocked: 2件

## 有効データ量（新品・未使用 / 14日以内 / price>0）
- 有効買取データを持つ商品数: 9
  - prod_iphone17pro_256: 2店舗
  - prod_iphone17pro_512: 2店舗
  - prod_iphone17pm_256: 2店舗
  - prod_iphone17pm_512: 2店舗
  - prod_switch2: 1店舗
  - prod_ps5_pro: 1店舗
  - prod_iphone17_256: 1店舗
  - prod_iphone16pro_256: 1店舗
  - prod_airpods_pro3: 1店舗

## ランキングに使えたデータ数
- Beginner: 2 件
- Pro: 0 件

## せどりルートに使えたデータ数
- ルート: 0 件
- ⚠️ reason_if_empty: calculate-sedori-routes 未実行 or DBにルートデータなし

## 海外価格の鮮度
- fresh: 0 / stale: 4 / 計 4
- eBay取得モード: manual（EBAY_APP_ID設定: 未設定→stale除外）

## カメラ自動取得の信頼性
- auto_scraped 取得: 17 件（うち high: 17）
- manual fallback: 43 件
- 棄却候補数: 203
- 棄却理由: {'model_mismatch': 152, 'not_buyback_context': 51}

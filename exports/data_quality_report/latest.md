# データ取得品質レポート（2026-07-10 16:48 JST）

## 取得成功率
- 全対象店舗数: 16
- 成功店舗数: 4
- 全失敗店舗数: 10
- ジョブ成功率: 23.6%（OK 13 / 失敗 38 / SKIP 4 / 計 55）

## 前回比較
- 前回成功率: 29.1%
- 今回成功率: 23.6%
- 変化: -5.5pt（悪化）
- 7日移動平均: 35.3%
- 主要失敗理由 TOP5: rate_limited_429 6, http_403 6, site_blocked 6, price_not_found 6, timeout 5

## 店舗別成功率（低い順）
- 2ndstreet（optional）: 0%（OK 0/失敗 4・price_not_found）
- bookoff（optional）: 0%（OK 0/失敗 0・not_supported）
- dosupara（optional）: 0%（OK 0/失敗 2・http_404）
- geo_mobile（optional）: 0%（OK 0/失敗 4・site_blocked）
- hardoff（optional）: 0%（OK 0/失敗 2・http_404）
- iosys: 0%（OK 0/失敗 6・http_403）
- janpara（optional）: 0%（OK 0/失敗 6・rate_limited_429）
- mobile_ichiban: 0%（OK 0/失敗 5・timeout）
- pasoko（optional）: 0%（OK 0/失敗 2・product_not_listed）
- sofmap（optional）: 0%（OK 0/失敗 2・service_unavailable）
- surugaya（optional）: 0%（OK 0/失敗 2・site_blocked）
- tsutaya（optional）: 0%（OK 0/失敗 0・not_supported）

## 商品別成功率
- ps5_pro: 10.0%
- switch2: 22.2%
- iphone17pm256: 25.0%
- iphone17pm512: 25.0%
- iphone17pro256: 37.5%
- iphone17pro512: 37.5%

## 連続失敗店舗（2回以上）
- 2ndstreet: 69回連続
- bookoff: 69回連続
- dosupara: 69回連続
- geo_mobile: 69回連続
- hardoff: 69回連続
- janpara: 69回連続
- pasoko: 69回連続
- sofmap: 69回連続
- surugaya: 69回連続
- tsutaya: 69回連続
- iosys: 2回連続

## 改善優先順位（required店舗）
1. iosys（失敗6 / http_403）
2. mobile_ichiban（失敗5 / timeout）

## 失敗理由（内訳）
- rate_limited_429: 6件
- http_403: 6件
- site_blocked: 6件
- price_not_found: 6件
- timeout: 5件
- http_404: 4件
- not_supported: 4件
- product_not_listed: 3件
- service_unavailable: 2件

## 有効データ量（新品・未使用 / 14日以内 / price>0）
- 有効買取データを持つ商品数: 22
  - prod_iphone17pro_256: 3店舗
  - prod_iphone17pro_512: 3店舗
  - prod_iphone17pm_256: 2店舗
  - prod_iphone17pm_512: 2店舗
  - prod_switch2: 2店舗
  - prod_x100vi: 1店舗
  - prod_gfx100rf: 1店舗
  - prod_xt5: 1店舗
  - prod_gr3x: 1店舗
  - prod_gr4_hdf: 1店舗
  - prod_gr4_mono: 1店舗
  - prod_a7rv: 1店舗
  - prod_a1ii: 1店舗
  - prod_a7cr: 1店舗
  - prod_fx3: 1店舗

## ランキングに使えたデータ数
- Beginner: 4 件
- Pro: 0 件

## せどりルートに使えたデータ数
- ルート: 0 件
- ⚠️ reason_if_empty: calculate-sedori-routes 未実行 or DBにルートデータなし

## 海外価格の鮮度
- fresh: 0 / stale: 4 / 計 4
- eBay取得モード: manual（EBAY_APP_ID設定: 未設定→stale除外）

## カメラ自動取得の信頼性
- auto_scraped 取得: 16 件（うち high: 16）
- manual fallback: 44 件
- 棄却候補数: 218
- 棄却理由: {'not_buyback_context': 195, 'model_mismatch': 23}

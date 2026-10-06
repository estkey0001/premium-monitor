# データ取得品質レポート（2026-10-06 17:54 JST）

## 取得成功率
- 全対象店舗数: 16
- 成功店舗数: 3
- 全失敗店舗数: 11
- ジョブ成功率: 21.8%（OK 12 / 失敗 39 / SKIP 4 / 計 55）

## 前回比較
- 前回成功率: 18.2%
- 今回成功率: 21.8%
- 変化: +3.6pt（改善）
- 7日移動平均: 19.7%
- 主要失敗理由 TOP5: price_not_found 9, product_not_listed 6, rate_limited_429 6, http_403 6, site_blocked 6

## 店舗別成功率（低い順）
- 2ndstreet（optional）: 0%（OK 0/失敗 4・price_not_found）
- bookoff（optional）: 0%（OK 0/失敗 0・not_supported）
- dosupara（optional）: 0%（OK 0/失敗 2・http_404）
- geo（optional）: 0%（OK 0/失敗 2・price_not_found）
- geo_mobile（optional）: 0%（OK 0/失敗 4・site_blocked）
- hardoff（optional）: 0%（OK 0/失敗 2・http_404）
- iosys: 0%（OK 0/失敗 6・http_403）
- janpara（optional）: 0%（OK 0/失敗 6・rate_limited_429）
- netoff（optional）: 0%（OK 0/失敗 4・price_not_found）
- pasoko（optional）: 0%（OK 0/失敗 2・product_not_listed）
- sofmap（optional）: 0%（OK 0/失敗 2・service_unavailable）
- surugaya（optional）: 0%（OK 0/失敗 2・site_blocked）

## 商品別成功率
- switch2: 11.1%
- ps5_pro: 20.0%
- iphone17pro256: 25.0%
- iphone17pro512: 25.0%
- iphone17pm512: 25.0%
- iphone17pm256: 37.5%

## 連続失敗店舗（2回以上）
- 2ndstreet: 179回連続
- bookoff: 179回連続
- dosupara: 179回連続
- geo_mobile: 179回連続
- hardoff: 179回連続
- janpara: 179回連続
- pasoko: 179回連続
- sofmap: 179回連続
- surugaya: 179回連続
- tsutaya: 179回連続
- iosys: 112回連続
- netoff: 39回連続
- geo: 18回連続

## 改善優先順位（required店舗）
1. iosys（失敗6 / http_403）
2. mobile_ichiban（失敗3 / product_not_listed）

## 失敗理由（内訳）
- price_not_found: 9件
- product_not_listed: 6件
- rate_limited_429: 6件
- http_403: 6件
- site_blocked: 6件
- http_404: 4件
- not_supported: 4件
- service_unavailable: 2件

## 有効データ量（新品・未使用 / 14日以内 / price>0）
- 有効買取データを持つ商品数: 23
  - prod_iphone17pm_256: 3店舗
  - prod_iphone17pro_256: 2店舗
  - prod_iphone17pro_512: 2店舗
  - prod_iphone17pm_512: 2店舗
  - prod_ps5_pro: 2店舗
  - prod_x100vi: 1店舗
  - prod_gfx100rf: 1店舗
  - prod_xt5: 1店舗
  - prod_gr3x: 1店舗
  - prod_gr4: 1店舗
  - prod_gr4_hdf: 1店舗
  - prod_gr4_mono: 1店舗
  - prod_a7rv: 1店舗
  - prod_a1ii: 1店舗
  - prod_a7cr: 1店舗

## ランキングに使えたデータ数
- Beginner: 1 件
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
- 棄却候補数: 195
- 棄却理由: {'model_mismatch': 128, 'not_buyback_context': 67}

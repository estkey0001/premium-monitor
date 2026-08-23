# データ取得品質レポート（2026-08-23 14:45 JST）

## 取得成功率
- 全対象店舗数: 16
- 成功店舗数: 5
- 全失敗店舗数: 9
- ジョブ成功率: 32.7%（OK 18 / 失敗 33 / SKIP 4 / 計 55）

## 前回比較
- 前回成功率: 32.7%
- 今回成功率: 32.7%
- 変化: 0.0pt（横ばい）
- 7日移動平均: 29.9%
- 主要失敗理由 TOP5: rate_limited_429 6, http_403 6, site_blocked 6, product_not_listed 5, price_not_found 4

## 店舗別成功率（低い順）
- 2ndstreet（optional）: 0%（OK 0/失敗 4・price_not_found）
- bookoff（optional）: 0%（OK 0/失敗 0・not_supported）
- dosupara（optional）: 0%（OK 0/失敗 2・http_404）
- geo_mobile（optional）: 0%（OK 0/失敗 4・site_blocked）
- hardoff（optional）: 0%（OK 0/失敗 2・http_404）
- iosys: 0%（OK 0/失敗 6・http_403）
- janpara（optional）: 0%（OK 0/失敗 6・rate_limited_429）
- pasoko（optional）: 0%（OK 0/失敗 2・product_not_listed）
- sofmap（optional）: 0%（OK 0/失敗 2・service_unavailable）
- surugaya（optional）: 0%（OK 0/失敗 2・site_blocked）
- tsutaya（optional）: 0%（OK 0/失敗 0・not_supported）
- geo（optional）: 50%（OK 1/失敗 1・product_not_listed）

## 商品別成功率
- ps5_pro: 20.0%
- switch2: 22.2%
- iphone17pro512: 37.5%
- iphone17pm512: 37.5%
- iphone17pro256: 50.0%
- iphone17pm256: 50.0%

## 連続失敗店舗（2回以上）
- 2ndstreet: 113回連続
- bookoff: 113回連続
- dosupara: 113回連続
- geo_mobile: 113回連続
- hardoff: 113回連続
- janpara: 113回連続
- pasoko: 113回連続
- sofmap: 113回連続
- surugaya: 113回連続
- tsutaya: 113回連続
- iosys: 46回連続

## 改善優先順位（required店舗）
1. iosys（失敗6 / http_403）
2. mobile_ichiban（失敗2 / product_not_listed）

## 失敗理由（内訳）
- rate_limited_429: 6件
- http_403: 6件
- site_blocked: 6件
- product_not_listed: 5件
- price_not_found: 4件
- http_404: 4件
- not_supported: 4件
- service_unavailable: 2件

## 有効データ量（新品・未使用 / 14日以内 / price>0）
- 有効買取データを持つ商品数: 28
  - prod_x100vi: 6店舗
  - prod_gr4: 6店舗
  - prod_iphone17_256: 4店舗
  - prod_iphone16pro_256: 4店舗
  - prod_iphone16pm_256: 4店舗
  - prod_gr4_hdf: 4店舗
  - prod_gr4_mono: 4店舗
  - prod_gr3x: 4店舗
  - prod_macbook_air_m4_13: 3店舗
  - prod_switch2_mk: 3店舗
  - prod_ps5_de: 3店舗
  - prod_iphone17pro_256: 3店舗
  - prod_iphone17pro_512: 3店舗
  - prod_switch2: 3店舗
  - prod_macbook_air_m4_15: 2店舗

## ランキングに使えたデータ数
- Beginner: 3 件
- Pro: 0 件

## せどりルートに使えたデータ数
- ルート: 0 件
- ⚠️ reason_if_empty: calculate-sedori-routes 未実行 or DBにルートデータなし

## 海外価格の鮮度
- fresh: 0 / stale: 4 / 計 4
- eBay取得モード: manual（EBAY_APP_ID設定: 未設定→stale除外）

## カメラ自動取得の信頼性
- auto_scraped 取得: 20 件（うち high: 20）
- manual fallback: 40 件
- 棄却候補数: 116
- 棄却理由: {'not_buyback_context': 67, 'model_mismatch': 49}

# データ取得品質レポート（2026-06-26 17:00 JST）

## 取得成功率
- 全対象店舗数: 16
- 成功店舗数: 6
- 全失敗店舗数: 8
- ジョブ成功率: 40.0%（OK 22 / 失敗 29 / SKIP 4 / 計 55）

## 前回比較
- 前回成功率: 40.0%
- 今回成功率: 40.0%
- 変化: 0.0pt（横ばい）
- 7日移動平均: 38.4%
- 主要失敗理由 TOP5: rate_limited_429 6, site_blocked 6, price_not_found 6, product_not_listed 5, http_404 4

## 店舗別成功率（低い順）
- 2ndstreet（optional）: 0%（OK 0/失敗 4・price_not_found）
- bookoff（optional）: 0%（OK 0/失敗 0・not_supported）
- dosupara（optional）: 0%（OK 0/失敗 2・http_404）
- geo_mobile（optional）: 0%（OK 0/失敗 4・site_blocked）
- hardoff（optional）: 0%（OK 0/失敗 2・http_404）
- janpara（optional）: 0%（OK 0/失敗 6・rate_limited_429）
- pasoko（optional）: 0%（OK 0/失敗 2・product_not_listed）
- sofmap（optional）: 0%（OK 0/失敗 2・service_unavailable）
- surugaya（optional）: 0%（OK 0/失敗 2・site_blocked）
- tsutaya（optional）: 0%（OK 0/失敗 0・not_supported）
- geo（optional）: 50%（OK 1/失敗 1・product_not_listed）
- netoff（optional）: 50%（OK 2/失敗 2・price_not_found）

## 商品別成功率
- ps5_pro: 30.0%
- switch2: 33.3%
- iphone17pm512: 37.5%
- iphone17pro512: 50.0%
- iphone17pm256: 50.0%
- iphone17pro256: 62.5%

## 連続失敗店舗（2回以上）
- 2ndstreet: 55回連続
- bookoff: 55回連続
- dosupara: 55回連続
- geo_mobile: 55回連続
- hardoff: 55回連続
- janpara: 55回連続
- pasoko: 55回連続
- sofmap: 55回連続
- surugaya: 55回連続
- tsutaya: 55回連続

## 改善優先順位（required店舗）
1. mobile_ichiban（失敗2 / product_not_listed）

## 失敗理由（内訳）
- rate_limited_429: 6件
- site_blocked: 6件
- price_not_found: 6件
- product_not_listed: 5件
- http_404: 4件
- not_supported: 4件
- service_unavailable: 2件

## 有効データ量（新品・未使用 / 14日以内 / price>0）
- 有効買取データを持つ商品数: 22
  - prod_iphone17pro_256: 5店舗
  - prod_iphone17pro_512: 4店舗
  - prod_iphone17pm_256: 4店舗
  - prod_iphone17pm_512: 3店舗
  - prod_switch2: 3店舗
  - prod_ps5_pro: 3店舗
  - prod_x100vi: 1店舗
  - prod_gfx100rf: 1店舗
  - prod_xt5: 1店舗
  - prod_gr3x: 1店舗
  - prod_gr4_hdf: 1店舗
  - prod_gr4_mono: 1店舗
  - prod_a7rv: 1店舗
  - prod_a1ii: 1店舗
  - prod_a7cr: 1店舗

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
- auto_scraped 取得: 16 件（うち high: 16）
- manual fallback: 44 件
- 棄却候補数: 219
- 棄却理由: {'not_buyback_context': 196, 'model_mismatch': 23}

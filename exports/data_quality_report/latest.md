# データ取得品質レポート（2026-10-10 19:25 JST）

## 取得成功率
- 全対象店舗数: 16
- 成功店舗数: 3
- 全失敗店舗数: 11
- ジョブ成功率: 29.7%（OK 19 / 失敗 41 / SKIP 4 / 計 64）

## 前回比較
- 前回成功率: 28.1%
- 今回成功率: 29.7%
- 変化: +1.6pt（改善）
- 7日移動平均: 29.2%
- 主要失敗理由 TOP5: robots_unreachable 9, price_not_found 8, rate_limited_429 6, http_403 6, http_404 4

## 店舗別成功率（低い順）
- 2ndstreet（optional）: 0%（OK 0/失敗 4・price_not_found）
- bookoff（optional）: 0%（OK 0/失敗 0・not_supported）
- dosupara（optional）: 0%（OK 0/失敗 2・http_404）
- geo_mobile（optional）: 0%（OK 0/失敗 4・robots_unreachable）
- hardoff（optional）: 0%（OK 0/失敗 2・http_404）
- iosys: 0%（OK 0/失敗 6・http_403）
- janpara（optional）: 0%（OK 0/失敗 6・rate_limited_429）
- mobile_ichiban: 0%（OK 0/失敗 5・robots_unreachable）
- netoff（optional）: 0%（OK 0/失敗 4・price_not_found）
- pasoko（optional）: 0%（OK 0/失敗 2・product_not_listed）
- sofmap（optional）: 0%（OK 0/失敗 2・service_unavailable）
- surugaya（optional）: 0%（OK 0/失敗 2・site_blocked）

## 商品別成功率
- iphone16pro256: 0.0%
- ps5_pro: 10.0%
- switch2: 22.2%
- iphone17pro256: 25.0%
- iphone17pro512: 25.0%
- iphone17pm256: 25.0%
- iphone17pm512: 25.0%
- iphone17_256: 100.0%
- airpods_pro3: 100.0%
- x100vi: 100.0%
- gr4: 100.0%
- gr4_hdf: 100.0%
- gr4_mono: 100.0%
- z8: 100.0%
- r5ii: 100.0%

## 連続失敗店舗（2回以上）
- 2ndstreet: 197回連続
- bookoff: 197回連続
- dosupara: 197回連続
- geo_mobile: 197回連続
- hardoff: 197回連続
- janpara: 197回連続
- pasoko: 197回連続
- sofmap: 197回連続
- surugaya: 197回連続
- tsutaya: 197回連続
- iosys: 130回連続
- netoff: 57回連続
- mobile_ichiban: 2回連続

## 改善優先順位（required店舗）
1. iosys（失敗6 / http_403）
2. mobile_ichiban（失敗5 / robots_unreachable）
3. kaitori_shouten（失敗1 / product_not_listed）

## 失敗理由（内訳）
- robots_unreachable: 9件
- price_not_found: 8件
- rate_limited_429: 6件
- http_403: 6件
- http_404: 4件
- product_not_listed: 4件
- not_supported: 4件
- service_unavailable: 2件
- site_blocked: 2件

## 有効データ量（新品・未使用 / 14日以内 / price>0）
- 有効買取データを持つ商品数: 14
  - prod_iphone17pro_256: 2店舗
  - prod_iphone17pro_512: 2店舗
  - prod_iphone17pm_256: 2店舗
  - prod_iphone17pm_512: 2店舗
  - prod_switch2: 2店舗
  - prod_ps5_pro: 1店舗
  - prod_iphone17_256: 1店舗
  - prod_airpods_pro3: 1店舗
  - prod_x100vi: 1店舗
  - prod_gr4: 1店舗
  - prod_gr4_hdf: 1店舗
  - prod_gr4_mono: 1店舗
  - prod_z8: 1店舗
  - prod_r5ii: 1店舗

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

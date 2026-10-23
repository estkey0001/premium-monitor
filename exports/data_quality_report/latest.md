# データ取得品質レポート（2026-10-23 22:35 JST）

## 取得成功率
- 全対象店舗数: 16
- 成功店舗数: 2
- 全失敗店舗数: 12
- ジョブ成功率: 27.3%（OK 18 / 失敗 44 / SKIP 4 / 計 66）

## 前回比較
- 前回成功率: 30.3%
- 今回成功率: 27.3%
- 変化: -3.0pt（悪化）
- 7日移動平均: 30.1%
- 主要失敗理由 TOP5: http_403 12, product_not_listed 8, rate_limited_429 6, robots_unreachable 4, price_not_found 4

## 店舗別成功率（低い順）
- 2ndstreet（optional）: 0%（OK 0/失敗 4・http_403）
- bookoff（optional）: 0%（OK 0/失敗 0・not_supported）
- dosupara（optional）: 0%（OK 0/失敗 2・http_404）
- geo（optional）: 0%（OK 0/失敗 2・http_403）
- geo_mobile（optional）: 0%（OK 0/失敗 4・robots_unreachable）
- hardoff（optional）: 0%（OK 0/失敗 2・http_404）
- iosys: 0%（OK 0/失敗 6・http_403）
- janpara（optional）: 0%（OK 0/失敗 6・rate_limited_429）
- mobile_ichiban: 0%（OK 0/失敗 5・product_not_listed）
- netoff（optional）: 0%（OK 0/失敗 4・price_not_found）
- pasoko（optional）: 0%（OK 0/失敗 2・product_not_listed）
- sofmap（optional）: 0%（OK 0/失敗 2・service_unavailable）

## 商品別成功率
- ps5_pro: 0.0%
- iphone16pro256: 0.0%
- iphoneduo_256: 0.0%
- switch2: 11.1%
- iphone17pro256: 25.0%
- iphone17pro512: 25.0%
- iphone17pm256: 25.0%
- iphone17pm512: 25.0%
- iphone17_256: 100.0%
- airpods_pro3: 100.0%
- iphoneair_256: 100.0%
- x100vi: 100.0%
- gr4: 100.0%
- gr4_hdf: 100.0%
- gr4_mono: 100.0%
- z8: 100.0%
- r5ii: 100.0%

## 連続失敗店舗（2回以上）
- 2ndstreet: 220回連続
- bookoff: 220回連続
- dosupara: 220回連続
- geo_mobile: 220回連続
- hardoff: 220回連続
- janpara: 220回連続
- pasoko: 220回連続
- sofmap: 220回連続
- surugaya: 220回連続
- tsutaya: 220回連続
- iosys: 153回連続
- netoff: 80回連続
- geo: 12回連続

## 改善優先順位（required店舗）
1. iosys（失敗6 / http_403）
2. mobile_ichiban（失敗5 / product_not_listed）
3. kaitori_shouten（失敗3 / suspicious_rejected）

## 失敗理由（内訳）
- http_403: 12件
- product_not_listed: 8件
- rate_limited_429: 6件
- robots_unreachable: 4件
- price_not_found: 4件
- http_404: 4件
- not_supported: 4件
- service_unavailable: 2件
- site_blocked: 2件
- suspicious_rejected: 2件

## 有効データ量（新品・未使用 / 14日以内 / price>0）
- 有効買取データを持つ商品数: 14
  - prod_iphone17pro_256: 2店舗
  - prod_iphone17pro_512: 2店舗
  - prod_iphone17pm_256: 2店舗
  - prod_iphone17pm_512: 2店舗
  - prod_switch2: 1店舗
  - prod_iphone17_256: 1店舗
  - prod_airpods_pro3: 1店舗
  - prod_iphoneair_256: 1店舗
  - prod_x100vi: 1店舗
  - prod_gr4: 1店舗
  - prod_gr4_hdf: 1店舗
  - prod_gr4_mono: 1店舗
  - prod_z8: 1店舗
  - prod_r5ii: 1店舗

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
- 棄却候補数: 204
- 棄却理由: {'model_mismatch': 153, 'not_buyback_context': 51}

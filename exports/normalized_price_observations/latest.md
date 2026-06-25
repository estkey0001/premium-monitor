# Normalized Price Observations

生成: 2026-06-25 16:48 JST

全価格（買取/販売/出品/落札/海外/下取/公式）を単一スキーマに正規化。
`price_role`（buy/sell/official/trade_in）を必ず付与し、
`is_usable_for_beginner` / `is_usable_for_pro` で main calculation 利用可否を判定。
ranking / sedori / LP はこの定義（src/market/normalized_prices.py）を唯一の入力源とする。

## サマリ

- 総観測数: **239**
- Beginner 利用可: 79 / Pro 利用可: 45
- fresh(≤14日): 121

### price_role 別

| role | 件数 |
|---|---|
| buy | 49 |
| official | 44 |
| sell | 146 |

### price_type 別

| type | 件数 |
|---|---|
| buyback_price | 140 |
| flea_listing_price | 5 |
| flea_sold_price | 10 |
| official_price | 44 |
| overseas_listing_price | 5 |
| overseas_sold_price | 6 |
| shop_sale_price | 29 |

### rejection_reason 別（main calc 除外）

| reason | 件数 |
|---|---|
| accessory_or_wrong_product | 4 |
| price_zero | 28 |
| stale_over_14d | 118 |

## Beginner 利用可（official_price / buyback_price のみ）

| product | role | type | price | conf | age | source |
|---|---|---|---|---|---|---|
| iPhone 17 Pro 256GB SI | official | official_price | ¥179,800 | medium | 0.0d | メーカー公式/定価 |
| iPhone 17 Pro 512GB SI | official | official_price | ¥214,800 | medium | 0.0d | メーカー公式/定価 |
| iPhone 17 Pro Max 256G | official | official_price | ¥219,800 | medium | 0.0d | メーカー公式/定価 |
| iPhone 17 Pro Max 512G | official | official_price | ¥254,800 | medium | 0.0d | メーカー公式/定価 |
| iPhone 17 256GB SIMフリー | official | official_price | ¥139,800 | medium | 0.0d | メーカー公式/定価 |
| iPhone 16 Pro 256GB SI | official | official_price | ¥159,800 | medium | 0.0d | メーカー公式/定価 |
| iPhone 16 Pro Max 256G | official | official_price | ¥189,800 | medium | 0.0d | メーカー公式/定価 |
| iPhone 16 Pro Max 512G | official | official_price | ¥224,800 | medium | 0.0d | メーカー公式/定価 |
| MacBook Air M4 13インチ | official | official_price | ¥164,800 | medium | 0.0d | メーカー公式/定価 |
| MacBook Air M4 15インチ | official | official_price | ¥198,800 | medium | 0.0d | メーカー公式/定価 |
| MacBook Pro M4 14インチ | official | official_price | ¥248,800 | medium | 0.0d | メーカー公式/定価 |
| Mac mini M4 | official | official_price | ¥94,800 | medium | 0.0d | メーカー公式/定価 |
| iPad Pro M4 11インチ | official | official_price | ¥168,800 | medium | 0.0d | メーカー公式/定価 |
| iPad Pro M4 13インチ | official | official_price | ¥218,800 | medium | 0.0d | メーカー公式/定価 |
| iPad Air M3 | official | official_price | ¥98,800 | medium | 0.0d | メーカー公式/定価 |
| Apple Watch Series 11 | official | official_price | ¥59,800 | medium | 0.0d | メーカー公式/定価 |
| Apple Watch Ultra 3 | official | official_price | ¥128,800 | medium | 0.0d | メーカー公式/定価 |
| AirPods Pro 3 | official | official_price | ¥39,800 | medium | 0.0d | メーカー公式/定価 |
| AirPods Max | official | official_price | ¥84,800 | medium | 0.0d | メーカー公式/定価 |
| Nintendo Switch 2 | official | official_price | ¥49,980 | medium | 0.0d | メーカー公式/定価 |
| Nintendo Switch 2 マリオカ | official | official_price | ¥59,980 | medium | 0.0d | メーカー公式/定価 |
| PlayStation 5 Pro | official | official_price | ¥119,980 | medium | 0.0d | メーカー公式/定価 |
| PlayStation 5 Digital  | official | official_price | ¥72,980 | medium | 0.0d | メーカー公式/定価 |
| Xbox Series X | official | official_price | ¥59,978 | medium | 0.0d | メーカー公式/定価 |
| RICOH GR IV | official | official_price | ¥194,800 | medium | 0.0d | メーカー公式/定価 |
| RICOH GR IV Monochrome | official | official_price | ¥283,800 | medium | 0.0d | メーカー公式/定価 |
| RICOH GR IIIx | official | official_price | ¥139,800 | medium | 0.0d | メーカー公式/定価 |
| RICOH GR III HDF | official | official_price | ¥147,400 | medium | 0.0d | メーカー公式/定価 |
| RICOH GR III | official | official_price | ¥129,800 | medium | 0.0d | メーカー公式/定価 |
| FUJIFILM X100VI | official | official_price | ¥269,500 | medium | 0.0d | メーカー公式/定価 |

## Pro 利用可（buy=販売/出品/落札/海外出品, sell=買取/海外落札）

| product | role | type | price | cond | age | source |
|---|---|---|---|---|---|---|
| FUJIFILM X100VI | sell | buyback_price | ¥220,000 | new_unopened | 0.0d | フジヤカメラ |
| FUJIFILM GFX100RF | sell | buyback_price | ¥432,300 | new_unopened | 0.0d | フジヤカメラ |
| RICOH GR IIIx | sell | buyback_price | ¥167,200 | new_unopened | 0.0d | フジヤカメラ |
| RICOH GR IV HDF | sell | buyback_price | ¥213,400 | new_unopened | 0.0d | フジヤカメラ |
| RICOH GR IV Monochrome | sell | buyback_price | ¥213,400 | new_unopened | 0.0d | フジヤカメラ |
| SONY α7R V | sell | buyback_price | ¥236,500 | new_unopened | 0.0d | フジヤカメラ |
| SONY α1 II | sell | buyback_price | ¥584,100 | new_unopened | 0.0d | フジヤカメラ |
| SONY α7CR | sell | buyback_price | ¥242,000 | new_unopened | 0.0d | フジヤカメラ |
| SONY FX3 | sell | buyback_price | ¥421,300 | new_unopened | 0.0d | フジヤカメラ |
| Nikon Z8 | sell | buyback_price | ¥295,900 | new_unopened | 0.0d | フジヤカメラ |
| Nikon Z9 | sell | buyback_price | ¥354,200 | new_unopened | 0.0d | フジヤカメラ |
| Leica Q3 | sell | buyback_price | ¥833,800 | new_unopened | 0.0d | フジヤカメラ |
| Leica M11 | sell | buyback_price | ¥1,375,400 | new_unopened | 0.0d | フジヤカメラ |
| iPhone 17 Pro 256GB SI | sell | buyback_price | ¥178,000 | new_unopened_simfree | 0.0d | モバイル一番 |
| iPhone 17 Pro 256GB SI | sell | buyback_price | ¥178,000 | new_unopened_simfree | 0.0d | 買取商店 |
| iPhone 17 Pro 256GB SI | sell | buyback_price | ¥178,000 | new_unopened_simfree | 0.0d | 買取一丁目 |
| iPhone 17 Pro 256GB SI | sell | buyback_price | ¥157,000 | new_unopened_simfree | 0.0d | イオシス |
| iPhone 17 Pro 256GB SI | sell | buyback_price | ¥157,500 | new_unopened_simfree | 0.0d | ネットオフ |
| iPhone 17 Pro 512GB SI | sell | buyback_price | ¥213,500 | new_unopened_simfree | 0.0d | 買取商店 |
| iPhone 17 Pro 512GB SI | sell | buyback_price | ¥213,000 | new_unopened_simfree | 0.0d | 買取一丁目 |
| iPhone 17 Pro 512GB SI | sell | buyback_price | ¥187,000 | new_unopened_simfree | 0.0d | イオシス |
| iPhone 17 Pro 512GB SI | sell | buyback_price | ¥187,950 | new_unopened_simfree | 0.0d | ネットオフ |
| iPhone 17 Pro Max 256G | sell | buyback_price | ¥192,000 | new_unopened_simfree | 0.0d | モバイル一番 |
| iPhone 17 Pro Max 256G | sell | buyback_price | ¥191,000 | new_unopened_simfree | 0.0d | 買取商店 |
| iPhone 17 Pro Max 256G | sell | buyback_price | ¥192,000 | new_unopened_simfree | 0.0d | 買取一丁目 |
| iPhone 17 Pro Max 256G | sell | buyback_price | ¥172,000 | new_unopened_simfree | 0.0d | イオシス |
| iPhone 17 Pro Max 512G | sell | buyback_price | ¥227,000 | new_unopened_simfree | 0.0d | 買取商店 |
| iPhone 17 Pro Max 512G | sell | buyback_price | ¥229,000 | new_unopened_simfree | 0.0d | 買取一丁目 |
| iPhone 17 Pro Max 512G | sell | buyback_price | ¥205,000 | new_unopened_simfree | 0.0d | イオシス |
| Nintendo Switch 2 | sell | buyback_price | ¥45,000 | new_unopened | 0.0d | ゲオ |

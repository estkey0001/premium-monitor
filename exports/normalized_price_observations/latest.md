# Normalized Price Observations

生成: 2026-06-08 22:34 JST

全価格（買取/販売/出品/落札/海外/下取/公式）を単一スキーマに正規化。
`price_role`（buy/sell/official/trade_in）を必ず付与し、
`is_usable_for_beginner` / `is_usable_for_pro` で main calculation 利用可否を判定。
ranking / sedori / LP はこの定義（src/market/normalized_prices.py）を唯一の入力源とする。

## サマリ

- 総観測数: **913**
- Beginner 利用可: 116 / Pro 利用可: 130
- fresh(≤14日): 281

### price_role 別

| role | 件数 |
|---|---|
| buy | 177 |
| official | 44 |
| sell | 692 |

### price_type 別

| type | 件数 |
|---|---|
| buyback_price | 686 |
| flea_listing_price | 15 |
| flea_sold_price | 10 |
| official_price | 44 |
| overseas_listing_price | 17 |
| overseas_sold_price | 6 |
| shop_sale_price | 135 |

### rejection_reason 別（main calc 除外）

| reason | 件数 |
|---|---|
| accessory_or_wrong_product | 2 |
| manual_over_auto_high | 6 |
| price_zero | 410 |
| stale_over_14d | 321 |

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
| iPhone 17 Pro 256GB SI | sell | buyback_price | ¥181,500 | new_unopened_simfree | 12.2d | モバイル一番 |
| iPhone 17 Pro 256GB SI | sell | buyback_price | ¥181,500 | new_unopened_simfree | 12.2d | 買取商店 |
| iPhone 17 Pro 256GB SI | sell | buyback_price | ¥157,000 | new_unopened_simfree | 12.2d | イオシス |
| iPhone 17 Pro 256GB SI | sell | buyback_price | ¥159,600 | new_unopened_simfree | 12.2d | ネットオフ |
| iPhone 17 Pro 512GB SI | sell | buyback_price | ¥215,000 | new_unopened_simfree | 12.2d | 買取商店 |
| iPhone 17 Pro 512GB SI | sell | buyback_price | ¥187,000 | new_unopened_simfree | 12.2d | イオシス |
| iPhone 17 Pro 512GB SI | sell | buyback_price | ¥190,050 | new_unopened_simfree | 12.2d | ネットオフ |
| iPhone 17 Pro Max 256G | sell | buyback_price | ¥197,500 | new_unopened_simfree | 12.2d | モバイル一番 |
| iPhone 17 Pro Max 256G | sell | buyback_price | ¥197,500 | new_unopened_simfree | 12.2d | 買取商店 |
| iPhone 17 Pro Max 256G | sell | buyback_price | ¥172,000 | new_unopened_simfree | 12.2d | イオシス |
| iPhone 17 Pro Max 256G | sell | buyback_price | ¥173,250 | new_unopened_simfree | 12.2d | ネットオフ |
| iPhone 17 Pro Max 512G | sell | buyback_price | ¥227,000 | new_unopened_simfree | 12.2d | 買取商店 |
| iPhone 17 Pro Max 512G | sell | buyback_price | ¥205,000 | new_unopened_simfree | 12.2d | イオシス |
| iPhone 17 Pro Max 512G | sell | buyback_price | ¥204,750 | new_unopened_simfree | 12.2d | ネットオフ |
| Nintendo Switch 2 | sell | buyback_price | ¥50,000 | new_unopened | 12.2d | ゲオ |
| Nintendo Switch 2 | sell | buyback_price | ¥46,000 | new_unopened | 12.2d | イオシス |
| Nintendo Switch 2 | sell | buyback_price | ¥49,800 | new_unopened | 12.2d | 買取商店 |
| PlayStation 5 Pro | sell | buyback_price | ¥100,000 | new_unopened | 12.2d | イオシス |
| PlayStation 5 Pro | sell | buyback_price | ¥134,500 | new_unopened | 12.2d | 買取商店 |
| PlayStation 5 Pro | sell | buyback_price | ¥134,500 | new_unopened | 12.2d | モバイル一番 |
| RICOH GR IV | sell | buyback_price | ¥198,000 | new_unopened | 7.4d | マップカメラ |
| RICOH GR IV | sell | buyback_price | ¥196,000 | new_unopened | 7.4d | カメラのキタムラ |
| RICOH GR IV | sell | buyback_price | ¥194,000 | new_unopened | 7.4d | フジヤカメラ |
| RICOH GR IV | sell | buyback_price | ¥190,000 | new_unopened | 7.4d | ソフマップ |
| RICOH GR IV | sell | buyback_price | ¥188,000 | new_unopened | 7.4d | じゃんぱら |
| RICOH GR IV | sell | buyback_price | ¥185,000 | new_unopened | 7.4d | 買取商店 |
| RICOH GR IV HDF | sell | buyback_price | ¥205,000 | new_unopened | 7.4d | マップカメラ |
| RICOH GR IV HDF | sell | buyback_price | ¥203,000 | new_unopened | 7.4d | カメラのキタムラ |
| RICOH GR IV HDF | sell | buyback_price | ¥200,000 | new_unopened | 7.4d | フジヤカメラ |
| RICOH GR IV HDF | sell | buyback_price | ¥196,000 | new_unopened | 7.4d | ソフマップ |

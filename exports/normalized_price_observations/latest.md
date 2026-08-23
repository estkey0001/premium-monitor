# Normalized Price Observations

生成: 2026-08-23 14:45 JST

全価格（買取/販売/出品/落札/海外/下取/公式）を単一スキーマに正規化。
`price_role`（buy/sell/official/trade_in）を必ず付与し、
`is_usable_for_beginner` / `is_usable_for_pro` で main calculation 利用可否を判定。
ranking / sedori / LP はこの定義（src/market/normalized_prices.py）を唯一の入力源とする。

## サマリ

- 総観測数: **1427**
- Beginner 利用可: 134 / Pro 利用可: 137
- fresh(≤14日): 223

### price_role 別

| role | 件数 |
|---|---|
| buy | 297 |
| official | 45 |
| sell | 1085 |

### price_type 別

| type | 件数 |
|---|---|
| buyback_price | 1079 |
| flea_listing_price | 30 |
| flea_sold_price | 16 |
| official_price | 45 |
| overseas_listing_price | 32 |
| overseas_sold_price | 6 |
| shop_sale_price | 219 |

### rejection_reason 別（main calc 除外）

| reason | 件数 |
|---|---|
| accessory_or_wrong_product | 4 |
| price_zero | 521 |
| stale_over_14d | 720 |

## Beginner 利用可（official_price / buyback_price のみ）

| product | role | type | price | conf | age | source |
|---|---|---|---|---|---|---|
| iPhone 17 Pro 256GB SI | official | official_price | ¥194,800 | high | 0.0d | メーカー公式/定価 |
| iPhone 17 Pro 512GB SI | official | official_price | ¥214,800 | medium | 0.0d | メーカー公式/定価 |
| iPhone 17 Pro Max 256G | official | official_price | ¥214,800 | high | 0.0d | メーカー公式/定価 |
| iPhone 17 Pro Max 512G | official | official_price | ¥254,800 | medium | 0.0d | メーカー公式/定価 |
| iPhone 17 256GB SIMフリー | official | official_price | ¥142,800 | high | 0.0d | メーカー公式/定価 |
| iPhone 16 Pro 256GB SI | official | official_price | ¥159,800 | medium | 0.0d | メーカー公式/定価 |
| iPhone 16 Pro Max 256G | official | official_price | ¥189,800 | medium | 0.0d | メーカー公式/定価 |
| iPhone 16 Pro Max 512G | official | official_price | ¥224,800 | medium | 0.0d | メーカー公式/定価 |
| MacBook Air M4 13インチ | official | official_price | ¥164,800 | medium | 0.0d | メーカー公式/定価 |
| MacBook Air M4 15インチ | official | official_price | ¥198,800 | medium | 0.0d | メーカー公式/定価 |
| MacBook Pro M4 14インチ | official | official_price | ¥248,800 | medium | 0.0d | メーカー公式/定価 |
| Mac mini M4 | official | official_price | ¥94,800 | medium | 0.0d | メーカー公式/定価 |
| iPad Pro M4 11インチ | official | official_price | ¥209,800 | high | 0.0d | メーカー公式/定価 |
| iPad Pro M4 13インチ | official | official_price | ¥269,800 | high | 0.0d | メーカー公式/定価 |
| iPad Air M3 | official | official_price | ¥129,800 | high | 0.0d | メーカー公式/定価 |
| Apple Watch Series 11 | official | official_price | ¥71,800 | high | 0.0d | メーカー公式/定価 |
| Apple Watch Ultra 3 | official | official_price | ¥142,800 | high | 0.0d | メーカー公式/定価 |
| AirPods Pro 3 | official | official_price | ¥42,800 | high | 0.0d | メーカー公式/定価 |
| AirPods Max | official | official_price | ¥84,800 | medium | 0.0d | メーカー公式/定価 |
| Nintendo Switch 2 | official | official_price | ¥49,980 | medium | 0.0d | メーカー公式/定価 |
| Nintendo Switch 2 マリオカ | official | official_price | ¥59,980 | medium | 0.0d | メーカー公式/定価 |
| PlayStation 5 Pro | official | official_price | ¥119,980 | medium | 0.0d | メーカー公式/定価 |
| PlayStation 5 Digital  | official | official_price | ¥72,980 | medium | 0.0d | メーカー公式/定価 |
| Xbox Series X | official | official_price | ¥59,978 | medium | 0.0d | メーカー公式/定価 |
| RICOH GR IV | official | official_price | ¥299,800 | high | 0.0d | メーカー公式/定価 |
| RICOH GR IV HDF | official | official_price | ¥299,800 | high | 0.0d | メーカー公式/定価 |
| RICOH GR IV Monochrome | official | official_price | ¥299,800 | high | 0.0d | メーカー公式/定価 |
| RICOH GR IIIx | official | official_price | ¥155,400 | high | 0.0d | メーカー公式/定価 |
| RICOH GR III HDF | official | official_price | ¥147,400 | medium | 0.0d | メーカー公式/定価 |
| RICOH GR III | official | official_price | ¥129,800 | medium | 0.0d | メーカー公式/定価 |

## Pro 利用可（buy=販売/出品/落札/海外出品, sell=買取/海外落札）

| product | role | type | price | cond | age | source |
|---|---|---|---|---|---|---|
| iPhone 17 256GB SIMフリー | sell | buyback_price | ¥135,000 | new_unopened_simfree | 13.1d | モバイル一番 |
| iPhone 17 256GB SIMフリー | sell | buyback_price | ¥133,000 | new_unopened_simfree | 13.1d | 買取商店 |
| iPhone 17 256GB SIMフリー | sell | buyback_price | ¥131,000 | new_unopened_simfree | 13.1d | じゃんぱら |
| iPhone 17 256GB SIMフリー | sell | buyback_price | ¥129,000 | new_unopened_simfree | 13.1d | イオシス |
| iPhone 16 Pro 256GB SI | sell | buyback_price | ¥152,000 | new_unopened_simfree | 13.1d | モバイル一番 |
| iPhone 16 Pro 256GB SI | sell | buyback_price | ¥150,000 | new_unopened_simfree | 13.1d | 買取商店 |
| iPhone 16 Pro 256GB SI | sell | buyback_price | ¥148,000 | new_unopened_simfree | 13.1d | じゃんぱら |
| iPhone 16 Pro 256GB SI | sell | buyback_price | ¥145,000 | new_unopened_simfree | 13.1d | イオシス |
| iPhone 16 Pro Max 256G | sell | buyback_price | ¥178,000 | new_unopened_simfree | 13.1d | モバイル一番 |
| iPhone 16 Pro Max 256G | sell | buyback_price | ¥175,000 | new_unopened_simfree | 13.1d | 買取商店 |
| iPhone 16 Pro Max 256G | sell | buyback_price | ¥172,000 | new_unopened_simfree | 13.1d | じゃんぱら |
| iPhone 16 Pro Max 256G | sell | buyback_price | ¥169,000 | new_unopened_simfree | 13.1d | イオシス |
| MacBook Air M4 13インチ | sell | buyback_price | ¥143,000 | new_unopened | 13.1d | じゃんぱら |
| MacBook Air M4 13インチ | sell | buyback_price | ¥140,000 | new_unopened | 13.1d | イオシス |
| MacBook Air M4 13インチ | sell | buyback_price | ¥138,000 | new_unopened | 13.1d | ソフマップ |
| MacBook Air M4 15インチ | sell | buyback_price | ¥175,000 | new_unopened | 13.1d | じゃんぱら |
| MacBook Air M4 15インチ | sell | buyback_price | ¥172,000 | new_unopened | 13.1d | イオシス |
| MacBook Pro M4 14インチ | sell | buyback_price | ¥220,000 | new_unopened | 13.1d | じゃんぱら |
| MacBook Pro M4 14インチ | sell | buyback_price | ¥215,000 | new_unopened | 13.1d | イオシス |
| Mac mini M4 | sell | buyback_price | ¥78,000 | new_unopened | 13.1d | じゃんぱら |
| Mac mini M4 | sell | buyback_price | ¥75,000 | new_unopened | 13.1d | イオシス |
| iPad Pro M4 11インチ | sell | buyback_price | ¥148,000 | new_unopened | 13.1d | じゃんぱら |
| iPad Pro M4 13インチ | sell | buyback_price | ¥192,000 | new_unopened | 13.1d | じゃんぱら |
| iPad Air M3 | sell | buyback_price | ¥78,000 | new_unopened | 13.1d | じゃんぱら |
| Apple Watch Series 11 | sell | buyback_price | ¥48,000 | new_unopened | 13.1d | 買取商店 |
| Apple Watch Series 11 | sell | buyback_price | ¥46,000 | new_unopened | 13.1d | じゃんぱら |
| Apple Watch Ultra 3 | sell | buyback_price | ¥105,000 | new_unopened | 13.1d | 買取商店 |
| Apple Watch Ultra 3 | sell | buyback_price | ¥102,000 | new_unopened | 13.1d | じゃんぱら |
| AirPods Pro 3 | sell | buyback_price | ¥32,000 | new_unopened | 13.1d | 買取商店 |
| AirPods Pro 3 | sell | buyback_price | ¥30,000 | new_unopened | 13.1d | じゃんぱら |

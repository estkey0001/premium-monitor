# Pro 利益ルート（normalized_price_observations 由来・検証済み）

生成: 2026-08-29 00:53 JST

- **main 利益ルート: 2件**（route_confidence high/medium のみ）
- 参考ルート(海外sold stale・要fresh化): 5件
- confidence別: {'high': 1, 'medium': 1} / route_type別: {'flea_to_buyback': 2}

- 最大利益: PlayStation 5 Pro +¥46,000（Yahoo Auction sold→買取商店, ROI 36%）
- 最大ROI: PlayStation 5 Pro ROI 36%（+¥46,000）

## main 利益ルート

| product | buy | buy¥ | sell | sell¥ | net | ROI | conf | type |
|---|---|---|---|---|---|---|---|---|
| PlayStation 5 Pr | flea_sold_price | ¥129,000 | buyback_price | ¥178,500 | **+¥45,000** | 35% | high | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥128,000 | buyback_price | ¥178,500 | **+¥46,000** | 36% | medium | flea_to_buyback |

## 参考ルート（海外sold が stale・fresh化すれば成立）

| product | buy¥ | sell(海外sold)¥ | 潜在net | ROI | stale |
|---|---|---|---|---|---|
| FUJIFILM X100VI | ¥255,000 | ¥564,141 | +¥183,663 | 72% | overseas_sold_stale(6.6d) |
| FUJIFILM X100VI | ¥361,819 | ¥564,141 | +¥73,639 | 20% | overseas_sold_stale(6.6d) |
| RICOH GR IIIx | ¥150,000 | ¥248,668 | +¥38,934 | 26% | overseas_sold_stale(6.6d) |
| Nintendo Switch  | ¥46,000 | ¥87,425 | +¥13,940 | 30% | overseas_sold_stale(6.6d) |
| Nintendo Switch  | ¥46,500 | ¥87,425 | +¥13,440 | 29% | overseas_sold_stale(6.6d) |

## 0件商品の診断

### iPhone 17 Pro 256GB SIMフリー
- buy候補 0 / sell候補 3 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 4), ('stale_over_14d', 4), ('duplicate_price_collision', 1)]

### iPhone 17 Pro 512GB SIMフリー
- buy候補 0 / sell候補 3 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 4), ('stale_over_14d', 3), ('duplicate_price_collision', 1)]

### iPhone 17 Pro Max 256GB SIMフリー
- buy候補 0 / sell候補 3 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 4), ('stale_over_14d', 3), ('duplicate_price_collision', 1)]

### iPhone 17 Pro Max 512GB SIMフリー
- buy候補 0 / sell候補 3 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 4), ('duplicate_price_collision', 1)]

### iPhone 17 256GB SIMフリー
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### iPhone 16 Pro 256GB SIMフリー
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### iPhone 16 Pro Max 256GB
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### iPhone 16 Pro Max 512GB
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### MacBook Air M4 13インチ
- buy候補 0 / sell候補 0 / stale除外 5 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 5)]

### MacBook Air M4 15インチ
- buy候補 0 / sell候補 0 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### MacBook Pro M4 14インチ
- buy候補 0 / sell候補 0 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### Mac mini M4
- buy候補 0 / sell候補 0 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### iPad Pro M4 11インチ
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### iPad Pro M4 13インチ
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### iPad Air M3
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### Apple Watch Series 11
- buy候補 0 / sell候補 0 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### Apple Watch Ultra 3
- buy候補 0 / sell候補 0 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### AirPods Pro 3
- buy候補 0 / sell候補 0 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### AirPods Max
- buy候補 0 / sell候補 0 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### Nintendo Switch 2
- buy候補 3 / sell候補 2 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 8), ('stale_over_14d', 3)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥87,425 → 潜在 +¥13,940（ROI 30%）
  - src_ebay ¥87,425 → 潜在 +¥13,440（ROI 29%）

### Nintendo Switch 2 マリオカートセット
- buy候補 0 / sell候補 0 / stale除外 5 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 5)]

### PlayStation 5 Digital Edition
- buy候補 0 / sell候補 0 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 3)]

### Xbox Series X
- buy候補 0 / sell候補 0 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### RICOH GR IV
- buy候補 5 / sell候補 6 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4), ('manual_over_auto_high', 1), ('accessory_or_wrong_product', 1)]

### RICOH GR IV HDF
- buy候補 2 / sell候補 3 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('duplicate_price_collision', 2), ('accessory_or_wrong_product', 1)]

### RICOH GR IV Monochrome
- buy候補 3 / sell候補 4 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('duplicate_price_collision', 1)]

### RICOH GR IIIx
- buy候補 5 / sell候補 4 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 3), ('model_mismatch', 1)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥248,668 → 潜在 +¥38,934（ROI 26%）

### RICOH GR III HDF
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### RICOH GR III
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### FUJIFILM X100VI
- buy候補 6 / sell候補 0 / stale除外 6 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 6), ('manual_over_auto_high', 6), ('duplicate_price_collision', 1)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥564,141 → 潜在 +¥183,663（ROI 72%）
  - src_ebay ¥564,141 → 潜在 +¥73,639（ROI 20%）

### FUJIFILM GFX100RF
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### FUJIFILM X-T5
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('accessory_or_wrong_product', 1)]

### SONY α7R V
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('accessory_or_wrong_product', 1)]

### SONY α1 II
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### SONY α7CR
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### SONY FX3
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### Canon EOS R5 Mark II
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('accessory_or_wrong_product', 1)]

### Canon EOS R6 Mark II
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('accessory_or_wrong_product', 1)]

### Canon EOS R3
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('accessory_or_wrong_product', 1)]

### Nikon Z8
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### Nikon Zf
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('accessory_or_wrong_product', 1)]

### Nikon Z9
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### Leica Q3
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('model_mismatch', 1)]

### Leica M11
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('model_mismatch', 1)]


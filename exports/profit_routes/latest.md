# Pro 利益ルート（normalized_price_observations 由来・検証済み）

生成: 2026-07-22 15:31 JST

- **main 利益ルート: 1件**（route_confidence high/medium のみ）
- 参考ルート(海外sold stale・要fresh化): 4件
- confidence別: {'high': 1} / route_type別: {'flea_to_buyback': 1}

- 最大利益: RICOH GR IIIx +¥12,700（Mercari sold→フジヤカメラ, ROI 8%）
- 最大ROI: RICOH GR IIIx ROI 8%（+¥12,700）

## main 利益ルート

| product | buy | buy¥ | sell | sell¥ | net | ROI | conf | type |
|---|---|---|---|---|---|---|---|---|
| RICOH GR IIIx | flea_sold_price | ¥150,000 | buyback_price | ¥167,200 | **+¥12,700** | 8% | high | flea_to_buyback |

## 参考ルート（海外sold が stale・fresh化すれば成立）

| product | buy¥ | sell(海外sold)¥ | 潜在net | ROI | stale |
|---|---|---|---|---|---|
| FUJIFILM X100VI | ¥255,000 | ¥564,176 | +¥183,691 | 72% | overseas_sold_stale(14.2d) |
| RICOH GR IIIx | ¥150,000 | ¥248,683 | +¥38,947 | 26% | overseas_sold_stale(14.2d) |
| Nintendo Switch  | ¥46,000 | ¥87,431 | +¥13,945 | 30% | overseas_sold_stale(14.2d) |
| Nintendo Switch  | ¥46,500 | ¥87,431 | +¥13,445 | 29% | overseas_sold_stale(14.2d) |

## 0件商品の診断

### iPhone 17 Pro 256GB SIMフリー
- buy候補 0 / sell候補 3 / stale除外 120 / 海外sold stale 1
- 除外理由TOP5: [('stale_over_14d', 63), ('price_zero', 62)]

### iPhone 17 Pro 512GB SIMフリー
- buy候補 0 / sell候補 3 / stale除外 111 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 62), ('stale_over_14d', 54)]

### iPhone 17 Pro Max 256GB SIMフリー
- buy候補 0 / sell候補 2 / stale除外 113 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 65), ('stale_over_14d', 54)]

### iPhone 17 Pro Max 512GB SIMフリー
- buy候補 0 / sell候補 2 / stale除外 93 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 65), ('stale_over_14d', 34)]

### iPhone 17 256GB SIMフリー
- buy候補 0 / sell候補 0 / stale除外 8 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 8)]

### iPhone 16 Pro 256GB SIMフリー
- buy候補 0 / sell候補 0 / stale除外 8 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 8)]

### iPhone 16 Pro Max 256GB
- buy候補 0 / sell候補 0 / stale除外 9 / 海外sold stale 1
- 除外理由TOP5: [('stale_over_14d', 9)]

### iPhone 16 Pro Max 512GB
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### MacBook Air M4 13インチ
- buy候補 0 / sell候補 0 / stale除外 18 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 18)]

### MacBook Air M4 15インチ
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### MacBook Pro M4 14インチ
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### Mac mini M4
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### iPad Pro M4 11インチ
- buy候補 0 / sell候補 0 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### iPad Pro M4 13インチ
- buy候補 0 / sell候補 0 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### iPad Air M3
- buy候補 0 / sell候補 0 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### Apple Watch Series 11
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### Apple Watch Ultra 3
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### AirPods Pro 3
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### AirPods Max
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### Nintendo Switch 2
- buy候補 2 / sell候補 3 / stale除外 137 / 海外sold stale 1
- 除外理由TOP5: [('price_zero', 92), ('stale_over_14d', 52)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥87,431 → 潜在 +¥13,945（ROI 30%）
  - src_ebay ¥87,431 → 潜在 +¥13,445（ROI 29%）

### Nintendo Switch 2 マリオカートセット
- buy候補 0 / sell候補 0 / stale除外 18 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 18)]

### PlayStation 5 Pro
- buy候補 2 / sell候補 2 / stale除外 141 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 101), ('stale_over_14d', 48)]

### PlayStation 5 Digital Edition
- buy候補 0 / sell候補 0 / stale除外 6 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 6)]

### Xbox Series X
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### RICOH GR IV
- buy候補 4 / sell候補 6 / stale除外 30 / 海外sold stale 1
- 除外理由TOP5: [('stale_over_14d', 30)]

### RICOH GR IV Monochrome
- buy候補 2 / sell候補 5 / stale除外 12 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 12)]

### RICOH GR III HDF
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### RICOH GR III
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### FUJIFILM X100VI
- buy候補 5 / sell候補 1 / stale除外 46 / 海外sold stale 1
- 除外理由TOP5: [('stale_over_14d', 46), ('manual_over_auto_high', 6)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥564,176 → 潜在 +¥183,691（ROI 72%）

### FUJIFILM GFX100RF
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### FUJIFILM X-T5
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('accessory_or_wrong_product', 1)]

### SONY α7R V
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

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
- 除外理由TOP5: []

### Canon EOS R3
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('accessory_or_wrong_product', 1)]

### Nikon Z8
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### Nikon Zf
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### Nikon Z9
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### Leica Q3
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### Leica M11
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### RICOH GR IV HDF
- buy候補 2 / sell候補 5 / stale除外 11 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 11)]


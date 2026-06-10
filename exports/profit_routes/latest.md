# Pro 利益ルート（normalized_price_observations 由来・検証済み）

生成: 2026-06-10 22:21 JST

- **main 利益ルート: 0件**（route_confidence high/medium のみ）
- 参考ルート(海外sold stale・要fresh化): 3件
- confidence別: {} / route_type別: {}


## main 利益ルート

| product | buy | buy¥ | sell | sell¥ | net | ROI | conf | type |
|---|---|---|---|---|---|---|---|---|
| (main利益ルート0件) | | | | | | | | |

## 参考ルート（海外sold が stale・fresh化すれば成立）

| product | buy¥ | sell(海外sold)¥ | 潜在net | ROI | stale |
|---|---|---|---|---|---|
| FUJIFILM X100VI | ¥237,999 | ¥548,900 | +¥188,981 | 79% | overseas_sold_stale(21.5d) |
| FUJIFILM X100VI | ¥339,800 | ¥548,900 | +¥84,126 | 25% | overseas_sold_stale(21.5d) |
| Nintendo Switch  | ¥51,005 | ¥85,140 | +¥7,107 | 14% | overseas_sold_stale(21.5d) |

## 0件商品の診断

### iPhone 17 Pro 256GB SIMフリー
- buy候補 1 / sell候補 7 / stale除外 99 / 海外sold stale 1
- 除外理由TOP5: [('price_zero', 57), ('stale_over_14d', 51)]

### iPhone 17 Pro 512GB SIMフリー
- buy候補 1 / sell候補 6 / stale除外 92 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 57), ('stale_over_14d', 44)]

### iPhone 17 Pro Max 256GB SIMフリー
- buy候補 1 / sell候補 5 / stale除外 93 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 59), ('stale_over_14d', 45)]

### iPhone 17 Pro Max 512GB SIMフリー
- buy候補 1 / sell候補 4 / stale除外 77 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 59), ('stale_over_14d', 29)]

### iPhone 17 256GB SIMフリー
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### iPhone 16 Pro 256GB SIMフリー
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### iPhone 16 Pro Max 256GB
- buy候補 0 / sell候補 0 / stale除外 5 / 海外sold stale 1
- 除外理由TOP5: [('stale_over_14d', 5)]

### iPhone 16 Pro Max 512GB
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### MacBook Air M4 13インチ
- buy候補 0 / sell候補 0 / stale除外 13 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 13)]

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
- buy候補 1 / sell候補 6 / stale除外 113 / 海外sold stale 1
- 除外理由TOP5: [('price_zero', 85), ('stale_over_14d', 42)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥85,140 → 潜在 +¥7,107（ROI 14%）

### Nintendo Switch 2 マリオカートセット
- buy候補 0 / sell候補 0 / stale除外 13 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 13)]

### PlayStation 5 Pro
- buy候補 1 / sell候補 5 / stale除外 117 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 93), ('stale_over_14d', 39)]

### PlayStation 5 Digital Edition
- buy候補 0 / sell候補 0 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 3)]

### Xbox Series X
- buy候補 0 / sell候補 0 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### RICOH GR IV
- buy候補 13 / sell候補 6 / stale除外 6 / 海外sold stale 1
- 除外理由TOP5: [('stale_over_14d', 6), ('accessory_or_wrong_product', 1)]

### RICOH GR IV Monochrome
- buy候補 8 / sell候補 5 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### RICOH GR IIIx
- buy候補 11 / sell候補 5 / stale除外 4 / 海外sold stale 1
- 除外理由TOP5: [('stale_over_14d', 4)]

### RICOH GR III HDF
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### RICOH GR III
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### FUJIFILM X100VI
- buy候補 14 / sell候補 1 / stale除外 20 / 海外sold stale 1
- 除外理由TOP5: [('stale_over_14d', 20), ('manual_over_auto_high', 6)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥548,900 → 潜在 +¥188,981（ROI 79%）
  - src_ebay ¥548,900 → 潜在 +¥84,126（ROI 25%）

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
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('accessory_or_wrong_product', 1)]

### Leica Q3
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### Leica M11
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### RICOH GR IV HDF
- buy候補 6 / sell候補 5 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('accessory_or_wrong_product', 1)]


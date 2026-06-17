# Pro 利益ルート（normalized_price_observations 由来・検証済み）

生成: 2026-06-17 18:43 JST

- **main 利益ルート: 1件**（route_confidence high/medium のみ）
- 参考ルート(海外sold stale・要fresh化): 7件
- confidence別: {'medium': 1} / route_type別: {'flea_to_buyback': 1}

- 最大利益: RICOH GR IIIx +¥12,700（Mercari sold→フジヤカメラ, ROI 8%）
- 最大ROI: RICOH GR IIIx ROI 8%（+¥12,700）

## main 利益ルート

| product | buy | buy¥ | sell | sell¥ | net | ROI | conf | type |
|---|---|---|---|---|---|---|---|---|
| RICOH GR IIIx | flea_sold_price | ¥150,000 | buyback_price | ¥167,200 | **+¥12,700** | 8% | medium | flea_to_buyback |

## 参考ルート（海外sold が stale・fresh化すれば成立）

| product | buy¥ | sell(海外sold)¥ | 潜在net | ROI | stale |
|---|---|---|---|---|---|
| FUJIFILM X100VI | ¥255,000 | ¥567,767 | +¥186,563 | 73% | overseas_sold_stale(20.4d) |
| FUJIFILM X100VI | ¥339,800 | ¥567,767 | +¥99,219 | 29% | overseas_sold_stale(20.4d) |
| iPhone 17 Pro 25 | ¥200,739 | ¥320,812 | +¥44,889 | 22% | overseas_sold_stale(20.4d) |
| RICOH GR IIIx | ¥150,000 | ¥250,254 | +¥40,203 | 27% | overseas_sold_stale(20.4d) |
| Nintendo Switch  | ¥46,000 | ¥87,969 | +¥14,375 | 31% | overseas_sold_stale(20.4d) |
| Nintendo Switch  | ¥46,500 | ¥87,969 | +¥13,875 | 30% | overseas_sold_stale(20.4d) |
| Nintendo Switch  | ¥55,970 | ¥87,969 | +¥4,405 | 8% | overseas_sold_stale(20.4d) |

## 0件商品の診断

### iPhone 17 Pro 256GB SIMフリー
- buy候補 1 / sell候補 5 / stale除外 5 / 海外sold stale 1
- 除外理由TOP5: [('stale_over_14d', 5), ('price_zero', 3)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥320,812 → 潜在 +¥44,889（ROI 22%）

### iPhone 17 Pro 512GB SIMフリー
- buy候補 1 / sell候補 4 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 3), ('stale_over_14d', 3)]

### iPhone 17 Pro Max 256GB SIMフリー
- buy候補 1 / sell候補 4 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 4), ('stale_over_14d', 3)]

### iPhone 17 Pro Max 512GB SIMフリー
- buy候補 1 / sell候補 3 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 4)]

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
- buy候補 3 / sell候補 3 / stale除外 4 / 海外sold stale 1
- 除外理由TOP5: [('price_zero', 7), ('stale_over_14d', 4)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥87,969 → 潜在 +¥14,375（ROI 31%）
  - src_ebay ¥87,969 → 潜在 +¥13,875（ROI 30%）
  - src_ebay ¥87,969 → 潜在 +¥4,405（ROI 8%）

### Nintendo Switch 2 マリオカートセット
- buy候補 0 / sell候補 0 / stale除外 5 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 5)]

### PlayStation 5 Pro
- buy候補 3 / sell候補 3 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 7), ('stale_over_14d', 3)]

### PlayStation 5 Digital Edition
- buy候補 0 / sell候補 0 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 3)]

### Xbox Series X
- buy候補 0 / sell候補 0 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### RICOH GR IV
- buy候補 1 / sell候補 0 / stale除外 15 / 海外sold stale 1
- 除外理由TOP5: [('stale_over_14d', 15)]

### RICOH GR IV Monochrome
- buy候補 2 / sell候補 1 / stale除外 6 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 6)]

### RICOH GR III HDF
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### RICOH GR III
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### FUJIFILM X100VI
- buy候補 2 / sell候補 1 / stale除外 17 / 海外sold stale 1
- 除外理由TOP5: [('stale_over_14d', 17)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥567,767 → 潜在 +¥186,563（ROI 73%）
  - src_ebay ¥567,767 → 潜在 +¥99,219（ROI 29%）

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
- buy候補 0 / sell候補 1 / stale除外 6 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 6)]


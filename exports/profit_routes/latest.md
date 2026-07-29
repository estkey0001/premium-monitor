# Pro 利益ルート（normalized_price_observations 由来・検証済み）

生成: 2026-07-29 15:56 JST

- **main 利益ルート: 5件**（route_confidence high/medium のみ）
- 参考ルート(海外sold stale・要fresh化): 6件
- confidence別: {'medium': 5} / route_type別: {'flea_to_buyback': 5}

- 最大利益: PlayStation 5 Pro +¥35,500（Yahoo Auction sold→買取商店, ROI 28%）
- 最大ROI: PlayStation 5 Pro ROI 28%（+¥35,500）

## main 利益ルート

| product | buy | buy¥ | sell | sell¥ | net | ROI | conf | type |
|---|---|---|---|---|---|---|---|---|
| RICOH GR IIIx | flea_sold_price | ¥150,000 | buyback_price | ¥167,200 | **+¥12,700** | 8% | medium | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥128,000 | buyback_price | ¥168,000 | **+¥35,500** | 28% | medium | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥128,000 | buyback_price | ¥168,000 | **+¥35,500** | 28% | medium | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥129,000 | buyback_price | ¥168,000 | **+¥34,500** | 27% | medium | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥129,000 | buyback_price | ¥168,000 | **+¥34,500** | 27% | medium | flea_to_buyback |

## 参考ルート（海外sold が stale・fresh化すれば成立）

| product | buy¥ | sell(海外sold)¥ | 潜在net | ROI | stale |
|---|---|---|---|---|---|
| FUJIFILM X100VI | ¥255,000 | ¥579,981 | +¥196,335 | 77% | overseas_sold_stale(7.2d) |
| FUJIFILM X100VI | ¥378,000 | ¥579,981 | +¥69,645 | 18% | overseas_sold_stale(7.2d) |
| RICOH GR IIIx | ¥150,000 | ¥255,598 | +¥44,478 | 30% | overseas_sold_stale(7.2d) |
| iPhone 17 Pro 25 | ¥221,529 | ¥327,683 | +¥28,972 | 13% | overseas_sold_stale(7.2d) |
| Nintendo Switch  | ¥46,000 | ¥89,801 | +¥15,841 | 34% | overseas_sold_stale(7.2d) |
| Nintendo Switch  | ¥46,500 | ¥89,801 | +¥15,341 | 33% | overseas_sold_stale(7.2d) |

## 0件商品の診断

### iPhone 17 Pro 256GB SIMフリー
- buy候補 1 / sell候補 4 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 4), ('stale_over_14d', 4)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥327,683 → 潜在 +¥28,972（ROI 13%）

### iPhone 17 Pro 512GB SIMフリー
- buy候補 1 / sell候補 3 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 4), ('stale_over_14d', 3)]

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
  - src_ebay ¥89,801 → 潜在 +¥15,841（ROI 34%）
  - src_ebay ¥89,801 → 潜在 +¥15,341（ROI 33%）

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
- 除外理由TOP5: [('stale_over_14d', 4), ('accessory_or_wrong_product', 1)]

### RICOH GR IV HDF
- buy候補 3 / sell候補 5 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('accessory_or_wrong_product', 1)]

### RICOH GR IV Monochrome
- buy候補 3 / sell候補 5 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### RICOH GR III HDF
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### RICOH GR III
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### FUJIFILM X100VI
- buy候補 6 / sell候補 1 / stale除外 6 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 6), ('manual_over_auto_high', 6)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥579,981 → 潜在 +¥196,335（ROI 77%）
  - src_ebay ¥579,981 → 潜在 +¥69,645（ROI 18%）

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


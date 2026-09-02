# Pro 利益ルート（normalized_price_observations 由来・検証済み）

生成: 2026-09-02 17:35 JST

- **main 利益ルート: 12件**（route_confidence high/medium のみ）
- 参考ルート(海外sold stale・要fresh化): 6件
- confidence別: {'medium': 12} / route_type別: {'shop_to_buyback': 8, 'flea_to_buyback': 4}

- 最大利益: RICOH GR IV Monochrome +¥59,888（Amazon JP (新品出品)→マップカメラ, ROI 40%）
- 最大ROI: RICOH GR IV Monochrome ROI 40%（+¥59,888）

## main 利益ルート

| product | buy | buy¥ | sell | sell¥ | net | ROI | conf | type |
|---|---|---|---|---|---|---|---|---|
| RICOH GR IV Mono | shop_sale_price | ¥150,600 | buyback_price | ¥215,000 | **+¥59,888** | 40% | medium | shop_to_buyback |
| RICOH GR IV Mono | shop_sale_price | ¥150,600 | buyback_price | ¥212,000 | **+¥56,888** | 38% | medium | shop_to_buyback |
| RICOH GR IV Mono | shop_sale_price | ¥150,600 | buyback_price | ¥210,000 | **+¥54,888** | 36% | medium | shop_to_buyback |
| RICOH GR IV Mono | shop_sale_price | ¥150,600 | buyback_price | ¥205,000 | **+¥49,888** | 33% | medium | shop_to_buyback |
| RICOH GR IIIx | shop_sale_price | ¥109,449 | buyback_price | ¥145,000 | **+¥31,051** | 28% | medium | shop_to_buyback |
| RICOH GR IIIx | shop_sale_price | ¥109,449 | buyback_price | ¥143,000 | **+¥29,051** | 27% | medium | shop_to_buyback |
| RICOH GR IIIx | shop_sale_price | ¥109,449 | buyback_price | ¥140,000 | **+¥26,051** | 24% | medium | shop_to_buyback |
| RICOH GR IIIx | shop_sale_price | ¥109,449 | buyback_price | ¥138,000 | **+¥24,051** | 22% | medium | shop_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥128,000 | buyback_price | ¥179,900 | **+¥47,400** | 37% | medium | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥128,000 | buyback_price | ¥179,700 | **+¥47,200** | 37% | medium | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥129,000 | buyback_price | ¥179,900 | **+¥46,400** | 36% | medium | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥129,000 | buyback_price | ¥179,700 | **+¥46,200** | 36% | medium | flea_to_buyback |

## 参考ルート（海外sold が stale・fresh化すれば成立）

| product | buy¥ | sell(海外sold)¥ | 潜在net | ROI | stale |
|---|---|---|---|---|---|
| FUJIFILM X100VI | ¥255,000 | ¥566,887 | +¥185,860 | 73% | overseas_sold_stale(11.3d) |
| RICOH GR IIIx | ¥109,449 | ¥249,869 | +¥80,446 | 74% | overseas_sold_stale(11.3d) |
| FUJIFILM X100VI | ¥361,819 | ¥566,887 | +¥75,836 | 21% | overseas_sold_stale(11.3d) |
| RICOH GR IIIx | ¥150,000 | ¥249,869 | +¥39,895 | 27% | overseas_sold_stale(11.3d) |
| Nintendo Switch  | ¥46,000 | ¥87,837 | +¥14,270 | 31% | overseas_sold_stale(11.3d) |
| Nintendo Switch  | ¥46,500 | ¥87,837 | +¥13,770 | 30% | overseas_sold_stale(11.3d) |

## 0件商品の診断

### iPhone 17 Pro 256GB SIMフリー
- buy候補 0 / sell候補 3 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 4), ('stale_over_14d', 4), ('duplicate_price_collision', 1)]

### iPhone 17 Pro 512GB SIMフリー
- buy候補 0 / sell候補 3 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 4), ('stale_over_14d', 3), ('duplicate_price_collision', 1)]

### iPhone 17 Pro Max 256GB SIMフリー
- buy候補 0 / sell候補 4 / stale除外 3 / 海外sold stale 0
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
  - src_ebay ¥87,837 → 潜在 +¥14,270（ROI 31%）
  - src_ebay ¥87,837 → 潜在 +¥13,770（ROI 30%）

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
- 除外理由TOP5: [('stale_over_14d', 4), ('manual_over_auto_high', 1)]

### RICOH GR IV HDF
- buy候補 3 / sell候補 3 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('duplicate_price_collision', 2), ('accessory_or_wrong_product', 1)]

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
  - src_ebay ¥566,887 → 潜在 +¥185,860（ROI 73%）
  - src_ebay ¥566,887 → 潜在 +¥75,836（ROI 21%）

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


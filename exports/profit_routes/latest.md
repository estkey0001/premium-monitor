# Pro 利益ルート（normalized_price_observations 由来・検証済み）

生成: 2026-08-25 13:49 JST

- **main 利益ルート: 21件**（route_confidence high/medium のみ）
- 参考ルート(海外sold stale・要fresh化): 15件
- confidence別: {'high': 4, 'medium': 17} / route_type別: {'flea_to_buyback': 4, 'shop_to_buyback': 17}

- 最大利益: PlayStation 5 Pro +¥44,000（Yahoo Auction sold→買取商店, ROI 34%）
- 最大ROI: PlayStation 5 Pro ROI 34%（+¥44,000）

## main 利益ルート

| product | buy | buy¥ | sell | sell¥ | net | ROI | conf | type |
|---|---|---|---|---|---|---|---|---|
| PlayStation 5 Pr | flea_sold_price | ¥128,000 | buyback_price | ¥176,500 | **+¥44,000** | 34% | high | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥128,000 | buyback_price | ¥176,500 | **+¥44,000** | 34% | high | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥129,000 | buyback_price | ¥176,500 | **+¥43,000** | 33% | high | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥129,000 | buyback_price | ¥176,500 | **+¥43,000** | 33% | high | flea_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥41,500 | buyback_price | ¥51,500 | **+¥5,500** | 13% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥42,800 | buyback_price | ¥51,500 | **+¥4,200** | 10% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥43,500 | buyback_price | ¥51,500 | **+¥3,500** | 8% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥154,800 | buyback_price | ¥196,500 | **+¥37,104** | 24% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥154,800 | buyback_price | ¥196,500 | **+¥37,104** | 24% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥154,800 | buyback_price | ¥196,500 | **+¥37,104** | 24% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥157,800 | buyback_price | ¥196,500 | **+¥34,044** | 22% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥157,800 | buyback_price | ¥196,500 | **+¥34,044** | 22% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥157,800 | buyback_price | ¥196,500 | **+¥34,044** | 22% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥159,800 | buyback_price | ¥196,500 | **+¥32,004** | 20% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥159,800 | buyback_price | ¥196,500 | **+¥32,004** | 20% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥159,800 | buyback_price | ¥196,500 | **+¥32,004** | 20% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥154,800 | buyback_price | ¥184,800 | **+¥25,404** | 16% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥157,800 | buyback_price | ¥184,800 | **+¥22,344** | 14% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥159,800 | buyback_price | ¥184,800 | **+¥20,304** | 13% | medium | shop_to_buyback |
| iPhone 17 Pro 25 | shop_sale_price | ¥169,800 | buyback_price | ¥184,500 | **+¥9,804** | 6% | medium | shop_to_buyback |
| iPhone 17 Pro 25 | shop_sale_price | ¥169,800 | buyback_price | ¥184,500 | **+¥9,804** | 6% | medium | shop_to_buyback |

## 参考ルート（海外sold が stale・fresh化すれば成立）

| product | buy¥ | sell(海外sold)¥ | 潜在net | ROI | stale |
|---|---|---|---|---|---|
| FUJIFILM X100VI | ¥175,000 | ¥563,437 | +¥265,500 | 152% | overseas_sold_stale(3.2d) |
| FUJIFILM X100VI | ¥178,000 | ¥563,437 | +¥262,410 | 147% | overseas_sold_stale(3.2d) |
| FUJIFILM X100VI | ¥180,000 | ¥563,437 | +¥260,350 | 145% | overseas_sold_stale(3.2d) |
| FUJIFILM X100VI | ¥255,000 | ¥563,437 | +¥183,100 | 72% | overseas_sold_stale(3.2d) |
| iPhone 17 Pro 25 | ¥169,800 | ¥318,377 | +¥74,808 | 44% | overseas_sold_stale(3.2d) |
| FUJIFILM X100VI | ¥361,819 | ¥563,437 | +¥73,076 | 20% | overseas_sold_stale(3.2d) |
| iPhone 17 Pro 25 | ¥172,800 | ¥318,377 | +¥71,718 | 42% | overseas_sold_stale(3.2d) |
| iPhone 17 Pro 25 | ¥174,800 | ¥318,377 | +¥69,658 | 40% | overseas_sold_stale(3.2d) |
| iPhone 17 Pro 25 | ¥176,800 | ¥318,377 | +¥67,598 | 38% | overseas_sold_stale(3.2d) |
| RICOH GR IIIx | ¥150,000 | ¥248,360 | +¥38,688 | 26% | overseas_sold_stale(3.2d) |
| Nintendo Switch  | ¥41,500 | ¥87,320 | +¥18,355 | 44% | overseas_sold_stale(3.2d) |
| Nintendo Switch  | ¥42,800 | ¥87,320 | +¥17,055 | 40% | overseas_sold_stale(3.2d) |
| Nintendo Switch  | ¥43,500 | ¥87,320 | +¥16,355 | 38% | overseas_sold_stale(3.2d) |
| Nintendo Switch  | ¥46,000 | ¥87,320 | +¥13,855 | 30% | overseas_sold_stale(3.2d) |
| Nintendo Switch  | ¥46,500 | ¥87,320 | +¥13,355 | 29% | overseas_sold_stale(3.2d) |

## 0件商品の診断

### iPhone 17 Pro 512GB SIMフリー
- buy候補 3 / sell候補 3 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 4), ('duplicate_price_collision', 1)]

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
- buy候補 2 / sell候補 0 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 3)]

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

### Nintendo Switch 2 マリオカートセット
- buy候補 2 / sell候補 0 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 3)]

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
- buy候補 2 / sell候補 3 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('duplicate_price_collision', 2)]

### RICOH GR IV Monochrome
- buy候補 3 / sell候補 4 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('duplicate_price_collision', 1), ('accessory_or_wrong_product', 1)]

### RICOH GR IIIx
- buy候補 5 / sell候補 4 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 3), ('model_mismatch', 1), ('accessory_or_wrong_product', 1)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥248,360 → 潜在 +¥38,688（ROI 26%）

### RICOH GR III HDF
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### RICOH GR III
- buy候補 0 / sell候補 1 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### FUJIFILM X100VI
- buy候補 9 / sell候補 0 / stale除外 3 / 海外sold stale 0
- 除外理由TOP5: [('manual_over_auto_high', 6), ('stale_over_14d', 3), ('duplicate_price_collision', 1)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥563,437 → 潜在 +¥265,500（ROI 152%）
  - src_ebay ¥563,437 → 潜在 +¥262,410（ROI 147%）
  - src_ebay ¥563,437 → 潜在 +¥260,350（ROI 145%）
  - src_ebay ¥563,437 → 潜在 +¥183,100（ROI 72%）
  - src_ebay ¥563,437 → 潜在 +¥73,076（ROI 20%）

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


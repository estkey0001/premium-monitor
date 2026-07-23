# Pro 利益ルート（normalized_price_observations 由来・検証済み）

生成: 2026-07-23 17:17 JST

- **main 利益ルート: 22件**（route_confidence high/medium のみ）
- 参考ルート(海外sold stale・要fresh化): 16件
- confidence別: {'high': 1, 'medium': 21} / route_type別: {'flea_to_buyback': 1, 'shop_to_buyback': 21}

- 最大利益: PlayStation 5 Pro +¥62,000（じゃんぱら→買取商店, ROI 91%）
- 最大ROI: PlayStation 5 Pro ROI 91%（+¥62,000）

## main 利益ルート

| product | buy | buy¥ | sell | sell¥ | net | ROI | conf | type |
|---|---|---|---|---|---|---|---|---|
| RICOH GR IIIx | flea_sold_price | ¥150,000 | buyback_price | ¥167,200 | **+¥12,700** | 8% | high | flea_to_buyback |
| PlayStation 5 Pr | shop_sale_price | ¥68,000 | buyback_price | ¥134,500 | **+¥62,000** | 91% | medium | shop_to_buyback |
| PlayStation 5 Pr | shop_sale_price | ¥69,800 | buyback_price | ¥134,500 | **+¥60,200** | 86% | medium | shop_to_buyback |
| FUJIFILM X100VI | shop_sale_price | ¥175,000 | buyback_price | ¥220,000 | **+¥40,000** | 23% | medium | shop_to_buyback |
| FUJIFILM X100VI | shop_sale_price | ¥178,000 | buyback_price | ¥220,000 | **+¥36,940** | 21% | medium | shop_to_buyback |
| FUJIFILM X100VI | shop_sale_price | ¥180,000 | buyback_price | ¥220,000 | **+¥34,900** | 19% | medium | shop_to_buyback |
| PlayStation 5 Pr | shop_sale_price | ¥68,000 | buyback_price | ¥100,000 | **+¥27,500** | 40% | medium | shop_to_buyback |
| PlayStation 5 Pr | shop_sale_price | ¥69,800 | buyback_price | ¥100,000 | **+¥25,700** | 37% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥41,500 | buyback_price | ¥50,800 | **+¥4,800** | 12% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥42,800 | buyback_price | ¥50,800 | **+¥3,500** | 8% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥43,500 | buyback_price | ¥50,800 | **+¥2,800** | 6% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥154,800 | buyback_price | ¥192,000 | **+¥32,604** | 21% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥157,800 | buyback_price | ¥192,000 | **+¥29,544** | 19% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥159,800 | buyback_price | ¥192,000 | **+¥27,504** | 17% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥53,000 | buyback_price | ¥67,000 | **+¥9,500** | 18% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥54,800 | buyback_price | ¥67,000 | **+¥7,700** | 14% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥53,000 | buyback_price | ¥65,000 | **+¥7,500** | 14% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥53,000 | buyback_price | ¥63,500 | **+¥6,000** | 11% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥54,800 | buyback_price | ¥65,000 | **+¥5,700** | 10% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥154,800 | buyback_price | ¥172,000 | **+¥12,604** | 8% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥157,800 | buyback_price | ¥172,000 | **+¥9,544** | 6% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥54,800 | buyback_price | ¥63,500 | **+¥4,200** | 8% | medium | shop_to_buyback |

## 参考ルート（海外sold が stale・fresh化すれば成立）

| product | buy¥ | sell(海外sold)¥ | 潜在net | ROI | stale |
|---|---|---|---|---|---|
| FUJIFILM X100VI | ¥175,000 | ¥564,176 | +¥266,091 | 152% | overseas_sold_stale(1.3d) |
| FUJIFILM X100VI | ¥178,000 | ¥564,176 | +¥263,001 | 148% | overseas_sold_stale(1.3d) |
| FUJIFILM X100VI | ¥180,000 | ¥564,176 | +¥260,941 | 145% | overseas_sold_stale(1.3d) |
| FUJIFILM X100VI | ¥255,000 | ¥564,176 | +¥183,691 | 72% | overseas_sold_stale(1.3d) |
| FUJIFILM X100VI | ¥283,562 | ¥564,176 | +¥154,272 | 54% | overseas_sold_stale(1.3d) |
| iPhone 17 Pro 25 | ¥169,800 | ¥318,793 | +¥75,140 | 44% | overseas_sold_stale(1.3d) |
| iPhone 17 Pro 25 | ¥172,800 | ¥318,793 | +¥72,050 | 42% | overseas_sold_stale(1.3d) |
| iPhone 17 Pro 25 | ¥174,800 | ¥318,793 | +¥69,990 | 40% | overseas_sold_stale(1.3d) |
| iPhone 17 Pro 25 | ¥176,800 | ¥318,793 | +¥67,930 | 38% | overseas_sold_stale(1.3d) |
| RICOH GR IV | ¥195,925 | ¥327,556 | +¥55,242 | 28% | overseas_sold_stale(1.3d) |
| RICOH GR IIIx | ¥150,000 | ¥248,683 | +¥38,947 | 26% | overseas_sold_stale(1.3d) |
| Nintendo Switch  | ¥41,500 | ¥87,431 | +¥18,445 | 44% | overseas_sold_stale(1.3d) |
| Nintendo Switch  | ¥42,800 | ¥87,431 | +¥17,145 | 40% | overseas_sold_stale(1.3d) |
| Nintendo Switch  | ¥43,500 | ¥87,431 | +¥16,445 | 38% | overseas_sold_stale(1.3d) |
| Nintendo Switch  | ¥46,000 | ¥87,431 | +¥13,945 | 30% | overseas_sold_stale(1.3d) |
| Nintendo Switch  | ¥46,500 | ¥87,431 | +¥13,445 | 29% | overseas_sold_stale(1.3d) |

## 0件商品の診断

### iPhone 17 Pro 256GB SIMフリー
- buy候補 4 / sell候補 6 / stale除外 119 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 67), ('stale_over_14d', 62)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥318,793 → 潜在 +¥75,140（ROI 44%）
  - src_ebay ¥318,793 → 潜在 +¥72,050（ROI 42%）
  - src_ebay ¥318,793 → 潜在 +¥69,990（ROI 40%）
  - src_ebay ¥318,793 → 潜在 +¥67,930（ROI 38%）

### iPhone 17 Pro 512GB SIMフリー
- buy候補 3 / sell候補 6 / stale除外 111 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 67), ('stale_over_14d', 54)]

### iPhone 17 Pro Max 512GB SIMフリー
- buy候補 0 / sell候補 4 / stale除外 93 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 71), ('stale_over_14d', 34)]

### iPhone 17 256GB SIMフリー
- buy候補 0 / sell候補 4 / stale除外 8 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 8)]

### iPhone 16 Pro 256GB SIMフリー
- buy候補 0 / sell候補 4 / stale除外 8 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 8)]

### iPhone 16 Pro Max 256GB
- buy候補 0 / sell候補 4 / stale除外 8 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 8)]

### iPhone 16 Pro Max 512GB
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### MacBook Air M4 13インチ
- buy候補 2 / sell候補 3 / stale除外 18 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 18)]

### MacBook Air M4 15インチ
- buy候補 0 / sell候補 2 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### MacBook Pro M4 14インチ
- buy候補 0 / sell候補 2 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### Mac mini M4
- buy候補 0 / sell候補 2 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### iPad Pro M4 11インチ
- buy候補 0 / sell候補 1 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### iPad Pro M4 13インチ
- buy候補 0 / sell候補 1 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### iPad Air M3
- buy候補 0 / sell候補 1 / stale除外 2 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 2)]

### Apple Watch Series 11
- buy候補 0 / sell候補 2 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### Apple Watch Ultra 3
- buy候補 0 / sell候補 2 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### AirPods Pro 3
- buy候補 0 / sell候補 2 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### AirPods Max
- buy候補 0 / sell候補 2 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### PlayStation 5 Digital Edition
- buy候補 0 / sell候補 3 / stale除外 6 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 6)]

### Xbox Series X
- buy候補 0 / sell候補 2 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### RICOH GR IV
- buy候補 5 / sell候補 16 / stale除外 32 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 32)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥327,556 → 潜在 +¥55,242（ROI 28%）

### RICOH GR IV Monochrome
- buy候補 2 / sell候補 9 / stale除外 14 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 14)]

### RICOH GR III HDF
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### RICOH GR III
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

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
- buy候補 2 / sell候補 9 / stale除外 13 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 13)]


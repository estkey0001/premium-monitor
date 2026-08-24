# Pro 利益ルート（normalized_price_observations 由来・検証済み）

生成: 2026-08-24 13:15 JST

- **main 利益ルート: 22件**（route_confidence high/medium のみ）
- 参考ルート(海外sold stale・要fresh化): 13件
- confidence別: {'high': 6, 'medium': 16} / route_type別: {'flea_to_buyback': 6, 'domestic_to_buyback': 6, 'shop_to_buyback': 10}

- 最大利益: FUJIFILM X100VI +¥183,400（Yahoo Auction sold→マップカメラ, ROI 72%）
- 最大ROI: PlayStation 5 Pro ROI 91%（+¥62,000）

## main 利益ルート

| product | buy | buy¥ | sell | sell¥ | net | ROI | conf | type |
|---|---|---|---|---|---|---|---|---|
| FUJIFILM X100VI | flea_sold_price | ¥255,000 | buyback_price | ¥445,000 | **+¥183,400** | 72% | high | flea_to_buyback |
| FUJIFILM X100VI | flea_sold_price | ¥255,000 | buyback_price | ¥442,000 | **+¥180,400** | 71% | high | flea_to_buyback |
| FUJIFILM X100VI | flea_sold_price | ¥255,000 | buyback_price | ¥440,000 | **+¥178,400** | 70% | high | flea_to_buyback |
| FUJIFILM X100VI | flea_sold_price | ¥255,000 | buyback_price | ¥435,000 | **+¥173,400** | 68% | high | flea_to_buyback |
| FUJIFILM X100VI | flea_sold_price | ¥255,000 | buyback_price | ¥430,000 | **+¥168,400** | 66% | high | flea_to_buyback |
| FUJIFILM X100VI | flea_sold_price | ¥255,000 | buyback_price | ¥428,000 | **+¥166,400** | 65% | high | flea_to_buyback |
| FUJIFILM X100VI | overseas_listing_price | ¥283,562 | buyback_price | ¥445,000 | **+¥154,267** | 54% | medium | domestic_to_buyback |
| FUJIFILM X100VI | overseas_listing_price | ¥283,562 | buyback_price | ¥442,000 | **+¥151,267** | 53% | medium | domestic_to_buyback |
| FUJIFILM X100VI | overseas_listing_price | ¥283,562 | buyback_price | ¥440,000 | **+¥149,267** | 53% | medium | domestic_to_buyback |
| FUJIFILM X100VI | overseas_listing_price | ¥283,562 | buyback_price | ¥435,000 | **+¥144,267** | 51% | medium | domestic_to_buyback |
| FUJIFILM X100VI | overseas_listing_price | ¥283,562 | buyback_price | ¥430,000 | **+¥139,267** | 49% | medium | domestic_to_buyback |
| FUJIFILM X100VI | overseas_listing_price | ¥283,562 | buyback_price | ¥428,000 | **+¥137,267** | 48% | medium | domestic_to_buyback |
| PlayStation 5 Pr | shop_sale_price | ¥68,000 | buyback_price | ¥134,500 | **+¥62,000** | 91% | medium | shop_to_buyback |
| PlayStation 5 Pr | shop_sale_price | ¥69,800 | buyback_price | ¥134,500 | **+¥60,200** | 86% | medium | shop_to_buyback |
| PlayStation 5 Pr | shop_sale_price | ¥68,000 | buyback_price | ¥100,000 | **+¥27,500** | 40% | medium | shop_to_buyback |
| PlayStation 5 Pr | shop_sale_price | ¥69,800 | buyback_price | ¥100,000 | **+¥25,700** | 37% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥41,500 | buyback_price | ¥50,800 | **+¥4,800** | 12% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥42,800 | buyback_price | ¥50,800 | **+¥3,500** | 8% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥43,500 | buyback_price | ¥50,800 | **+¥2,800** | 6% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥154,800 | buyback_price | ¥192,000 | **+¥32,604** | 21% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥157,800 | buyback_price | ¥192,000 | **+¥29,544** | 19% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥159,800 | buyback_price | ¥192,000 | **+¥27,504** | 17% | medium | shop_to_buyback |

## 参考ルート（海外sold が stale・fresh化すれば成立）

| product | buy¥ | sell(海外sold)¥ | 潜在net | ROI | stale |
|---|---|---|---|---|---|
| FUJIFILM X100VI | ¥255,000 | ¥564,176 | +¥183,691 | 72% | overseas_sold_stale(2.1d) |
| FUJIFILM X100VI | ¥283,562 | ¥564,176 | +¥154,272 | 54% | overseas_sold_stale(2.1d) |
| iPhone 17 Pro 25 | ¥169,800 | ¥318,793 | +¥75,140 | 44% | overseas_sold_stale(2.1d) |
| iPhone 17 Pro 25 | ¥172,800 | ¥318,793 | +¥72,050 | 42% | overseas_sold_stale(2.1d) |
| iPhone 17 Pro 25 | ¥174,800 | ¥318,793 | +¥69,990 | 40% | overseas_sold_stale(2.1d) |
| iPhone 17 Pro 25 | ¥176,800 | ¥318,793 | +¥67,930 | 38% | overseas_sold_stale(2.1d) |
| RICOH GR IV | ¥195,925 | ¥327,556 | +¥55,242 | 28% | overseas_sold_stale(2.1d) |
| RICOH GR IIIx | ¥150,000 | ¥248,683 | +¥38,947 | 26% | overseas_sold_stale(2.1d) |
| Nintendo Switch  | ¥41,500 | ¥87,431 | +¥18,445 | 44% | overseas_sold_stale(2.1d) |
| Nintendo Switch  | ¥42,800 | ¥87,431 | +¥17,145 | 40% | overseas_sold_stale(2.1d) |
| Nintendo Switch  | ¥43,500 | ¥87,431 | +¥16,445 | 38% | overseas_sold_stale(2.1d) |
| Nintendo Switch  | ¥46,000 | ¥87,431 | +¥13,945 | 30% | overseas_sold_stale(2.1d) |
| Nintendo Switch  | ¥46,500 | ¥87,431 | +¥13,445 | 29% | overseas_sold_stale(2.1d) |

## 0件商品の診断

### iPhone 17 Pro 256GB SIMフリー
- buy候補 4 / sell候補 3 / stale除外 139 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 72), ('price_zero', 72)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥318,793 → 潜在 +¥75,140（ROI 44%）
  - src_ebay ¥318,793 → 潜在 +¥72,050（ROI 42%）
  - src_ebay ¥318,793 → 潜在 +¥69,990（ROI 40%）
  - src_ebay ¥318,793 → 潜在 +¥67,930（ROI 38%）

### iPhone 17 Pro 512GB SIMフリー
- buy候補 3 / sell候補 3 / stale除外 130 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 72), ('stale_over_14d', 63)]

### iPhone 17 Pro Max 512GB SIMフリー
- buy候補 0 / sell候補 2 / stale除外 109 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 77), ('stale_over_14d', 38)]

### iPhone 17 256GB SIMフリー
- buy候補 0 / sell候補 0 / stale除外 16 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 16)]

### iPhone 16 Pro 256GB SIMフリー
- buy候補 0 / sell候補 0 / stale除外 16 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 16)]

### iPhone 16 Pro Max 256GB
- buy候補 0 / sell候補 0 / stale除外 16 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 16)]

### iPhone 16 Pro Max 512GB
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### MacBook Air M4 13インチ
- buy候補 2 / sell候補 0 / stale除外 26 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 26)]

### MacBook Air M4 15インチ
- buy候補 0 / sell候補 0 / stale除外 8 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 8)]

### MacBook Pro M4 14インチ
- buy候補 0 / sell候補 0 / stale除外 8 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 8)]

### Mac mini M4
- buy候補 0 / sell候補 0 / stale除外 8 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 8)]

### iPad Pro M4 11インチ
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### iPad Pro M4 13インチ
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### iPad Air M3
- buy候補 0 / sell候補 0 / stale除外 4 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 4)]

### Apple Watch Series 11
- buy候補 0 / sell候補 0 / stale除外 8 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 8)]

### Apple Watch Ultra 3
- buy候補 0 / sell候補 0 / stale除外 8 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 8)]

### AirPods Pro 3
- buy候補 0 / sell候補 0 / stale除外 8 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 8)]

### AirPods Max
- buy候補 0 / sell候補 0 / stale除外 8 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 8)]

### Nintendo Switch 2 マリオカートセット
- buy候補 2 / sell候補 0 / stale除外 26 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 26)]

### PlayStation 5 Digital Edition
- buy候補 0 / sell候補 0 / stale除外 12 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 12)]

### Xbox Series X
- buy候補 0 / sell候補 0 / stale除外 8 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 8)]

### RICOH GR IV
- buy候補 5 / sell候補 6 / stale除外 56 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 56)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥327,556 → 潜在 +¥55,242（ROI 28%）

### RICOH GR IV HDF
- buy候補 2 / sell候補 4 / stale除外 24 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 24)]

### RICOH GR IV Monochrome
- buy候補 2 / sell候補 4 / stale除外 25 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 25)]

### RICOH GR IIIx
- buy候補 4 / sell候補 4 / stale除外 42 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 42)]
- eBay sold を fresh化すると成立する候補:
  - src_ebay ¥248,683 → 潜在 +¥38,947（ROI 26%）

### RICOH GR III HDF
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### RICOH GR III
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### FUJIFILM GFX100RF
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### FUJIFILM X-T5
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### SONY α7R V
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### SONY α1 II
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### SONY α7CR
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### SONY FX3
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### Canon EOS R5 Mark II
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### Canon EOS R6 Mark II
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### Canon EOS R3
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### Nikon Z8
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### Nikon Zf
- buy候補 0 / sell候補 0 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### Nikon Z9
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### Leica Q3
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]

### Leica M11
- buy候補 0 / sell候補 0 / stale除外 1 / 海外sold stale 0
- 除外理由TOP5: [('stale_over_14d', 1)]


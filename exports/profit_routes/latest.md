# Pro 利益ルート（normalized_price_observations 由来・検証済み）

生成: 2026-07-24 15:54 JST

- **main 利益ルート: 26件**（route_confidence high/medium のみ）
- 参考ルート(海外sold stale・要fresh化): 17件
- confidence別: {'high': 5, 'medium': 21} / route_type別: {'flea_to_buyback': 5, 'shop_to_buyback': 21}

- 最大利益: iPhone 17 Pro Max 256GB SIMフリー +¥40,604（ゲオ→モバイル一番, ROI 26%）
- 最大ROI: iPhone 17 Pro Max 256GB SIMフリー ROI 26%（+¥40,604）

## main 利益ルート

| product | buy | buy¥ | sell | sell¥ | net | ROI | conf | type |
|---|---|---|---|---|---|---|---|---|
| RICOH GR IIIx | flea_sold_price | ¥150,000 | buyback_price | ¥167,200 | **+¥12,700** | 8% | high | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥128,000 | buyback_price | ¥164,000 | **+¥31,500** | 25% | high | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥128,000 | buyback_price | ¥164,000 | **+¥31,500** | 25% | high | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥129,000 | buyback_price | ¥164,000 | **+¥30,500** | 24% | high | flea_to_buyback |
| PlayStation 5 Pr | flea_sold_price | ¥129,000 | buyback_price | ¥164,000 | **+¥30,500** | 24% | high | flea_to_buyback |
| FUJIFILM X100VI | shop_sale_price | ¥175,000 | buyback_price | ¥220,000 | **+¥40,000** | 23% | medium | shop_to_buyback |
| FUJIFILM X100VI | shop_sale_price | ¥178,000 | buyback_price | ¥220,000 | **+¥36,940** | 21% | medium | shop_to_buyback |
| FUJIFILM X100VI | shop_sale_price | ¥180,000 | buyback_price | ¥220,000 | **+¥34,900** | 19% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥41,500 | buyback_price | ¥50,800 | **+¥4,800** | 12% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥42,800 | buyback_price | ¥50,800 | **+¥3,500** | 8% | medium | shop_to_buyback |
| Nintendo Switch  | shop_sale_price | ¥43,500 | buyback_price | ¥50,800 | **+¥2,800** | 6% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥154,800 | buyback_price | ¥200,000 | **+¥40,604** | 26% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥154,800 | buyback_price | ¥200,000 | **+¥40,604** | 26% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥154,800 | buyback_price | ¥200,000 | **+¥40,604** | 26% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥157,800 | buyback_price | ¥200,000 | **+¥37,544** | 24% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥157,800 | buyback_price | ¥200,000 | **+¥37,544** | 24% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥157,800 | buyback_price | ¥200,000 | **+¥37,544** | 24% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥159,800 | buyback_price | ¥200,000 | **+¥35,504** | 22% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥159,800 | buyback_price | ¥200,000 | **+¥35,504** | 22% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥159,800 | buyback_price | ¥200,000 | **+¥35,504** | 22% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥154,800 | buyback_price | ¥173,250 | **+¥13,854** | 9% | medium | shop_to_buyback |
| iPhone 17 Pro 25 | shop_sale_price | ¥169,800 | buyback_price | ¥185,500 | **+¥10,804** | 6% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥157,800 | buyback_price | ¥173,250 | **+¥10,794** | 7% | medium | shop_to_buyback |
| iPhone 17 Pro 25 | shop_sale_price | ¥169,800 | buyback_price | ¥185,000 | **+¥10,304** | 6% | medium | shop_to_buyback |
| iPhone 17 Pro 25 | shop_sale_price | ¥169,800 | buyback_price | ¥184,000 | **+¥9,304** | 5% | medium | shop_to_buyback |
| iPhone 17 Pro Ma | shop_sale_price | ¥159,800 | buyback_price | ¥173,250 | **+¥8,754** | 5% | medium | shop_to_buyback |

## 参考ルート（海外sold が stale・fresh化すれば成立）

| product | buy¥ | sell(海外sold)¥ | 潜在net | ROI | stale |
|---|---|---|---|---|---|
| FUJIFILM X100VI | ¥175,000 | ¥579,488 | +¥278,340 | 159% | overseas_sold_stale(2.2d) |
| FUJIFILM X100VI | ¥178,000 | ¥579,488 | +¥275,250 | 155% | overseas_sold_stale(2.2d) |
| FUJIFILM X100VI | ¥180,000 | ¥579,488 | +¥273,190 | 152% | overseas_sold_stale(2.2d) |
| FUJIFILM X100VI | ¥255,000 | ¥579,488 | +¥195,940 | 77% | overseas_sold_stale(2.2d) |
| FUJIFILM X100VI | ¥319,800 | ¥579,488 | +¥129,196 | 40% | overseas_sold_stale(2.2d) |
| iPhone 17 Pro 25 | ¥169,800 | ¥327,406 | +¥82,031 | 48% | overseas_sold_stale(2.2d) |
| iPhone 17 Pro 25 | ¥172,800 | ¥327,406 | +¥78,941 | 46% | overseas_sold_stale(2.2d) |
| iPhone 17 Pro 25 | ¥174,800 | ¥327,406 | +¥76,881 | 44% | overseas_sold_stale(2.2d) |
| iPhone 17 Pro 25 | ¥176,800 | ¥327,406 | +¥74,821 | 42% | overseas_sold_stale(2.2d) |
| iPhone 17 Pro 25 | ¥191,800 | ¥327,406 | +¥59,371 | 31% | overseas_sold_stale(2.2d) |
| RICOH GR IIIx | ¥150,000 | ¥255,382 | +¥44,306 | 30% | overseas_sold_stale(2.2d) |
| Nintendo Switch  | ¥41,500 | ¥89,728 | +¥20,282 | 49% | overseas_sold_stale(2.2d) |
| Nintendo Switch  | ¥42,800 | ¥89,728 | +¥18,982 | 44% | overseas_sold_stale(2.2d) |
| Nintendo Switch  | ¥43,500 | ¥89,728 | +¥18,282 | 42% | overseas_sold_stale(2.2d) |
| Nintendo Switch  | ¥46,000 | ¥89,728 | +¥15,782 | 34% | overseas_sold_stale(2.2d) |
| Nintendo Switch  | ¥46,500 | ¥89,728 | +¥15,282 | 33% | overseas_sold_stale(2.2d) |
| Nintendo Switch  | ¥55,615 | ¥89,728 | +¥6,167 | 11% | overseas_sold_stale(2.2d) |

## 0件商品の診断

### iPhone 17 Pro 512GB SIMフリー
- buy候補 4 / sell候補 3 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('price_zero', 4)]

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
- 除外理由TOP5: [('stale_over_14d', 4)]

### RICOH GR IV HDF
- buy候補 3 / sell候補 5 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: []

### RICOH GR IV Monochrome
- buy候補 3 / sell候補 5 / stale除外 0 / 海外sold stale 0
- 除外理由TOP5: [('accessory_or_wrong_product', 1)]

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


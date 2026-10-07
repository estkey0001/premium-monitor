# Phase 11 Baseline（2026-10-06 23:29 の CI 生成物）

CI の生成物から `scripts/production_coverage_metrics.py` で計測した（読むだけ）。

## 生成物の時刻

- diagnostics: 2026-10-06T23:29:59+09:00
- observations: 2026-10-06 23:29 JST
- collector: 2026-10-06T22:07:09+09:00
- routes: 2026-10-06 23:29 JST
- tcg: 2026-10-06T22:59:42.518972+09:00
- health: 2026-10-06 23:29 JST

## 指標

| 指標 | 値 |
|---|---:|
| products | 45 |
| confirmed_opportunities | 1 |
| opportunity_candidates | 45 |
| confirmed_routes | 0 |
| reference_routes | 0 |
| verified_retail | 7 |
| unverified_retail | 38 |
| buyback_rows | 138 |
| fresh_buyback | 64 |
| stale_buyback | 74 |
| confirmed_buyback_rows | 6 |
| confirmed_buyback_products | 6 |
| buyback_attempts | 51 |
| buyback_success | 10 |
| buyback_success_rate | 0.196 |
| buyback_shops | 16 |
| buyback_shops_failed_all | 14 |
| valid_sold | 0 |
| sold_rows | 6 |
| eligible_sold_median | 0 |
| listing_rows | 0 |
| stock_in_stock | 0 |
| stock_out_of_stock | 1 |
| stock_unknown | 41 |
| stock_other | {"LOTTERY": 3} |
| stock_history_entries | 4 |
| stock_history_states | {"LOTTERY": 3, "OUT_OF_STOCK": 1} |
| restock_events | 0 |
| tcg_lotteries | 8 |
| tcg_lottery_status | {"RESULT_PENDING": 2, "CLOSED": 4, "ENDED": 2} |
| tcg_events | 14 |
| tcg_event_types | {"GENERAL_SALE/COMING_SOON": 13, "GENERAL_SALE/UNVERIFIED": 1} |
| tcg_preorder | 0 |
| tcg_first_come | 0 |
| tcg_restock | 0 |
| tcg_source_health | {"HEALTHY": 2, "OK_NO_EVENTS": 5} |
| system_health | 37.0 |
| exclusion_reasons | {"unverified_buy_price": 38, "stale_buyback": 17, "invalid_identity": 5, "no_sell_price": 5, "no_profit": 4} |

## 利益商品の候補の段階（上から順に落ちる件数）

| 段階 | 残り | 落ちた | 理由 |
|---|---:|---:|---|
| candidates | 45 | 0 |  |
| verified_buy | 7 | 38 | {"unverified_buy_price": 38} |
| fresh_sell | 5 | 2 | {"stale_buyback": 2} |
| identity | 5 | 0 |  |
| shipping | 5 | 0 |  |
| profitable | 1 | 4 | {"no_profit": 4} |
| actionable | 1 | 0 |  |

## 網羅表（商品 × データの種類）

| 種類 | CONFIRMED | REFERENCE | STALE | MISSING | FAILED | NOT_IMPLEMENTED |
|---|---:|---:|---:|---:|---:|---:|
| RETAIL | 7 | 38 | 0 | 0 | 0 | 0 |
| BUYBACK | 6 | 17 | 17 | 5 | 0 | 0 |
| STOCK | 4 | 0 | 0 | 41 | 0 | 0 |
| LISTING | 0 | 12 | 0 | 33 | 0 | 0 |
| SOLD | 0 | 6 | 0 | 0 | 0 | 39 |
| LOTTERY | 5 | 0 | 0 | 40 | 0 | 0 |

### 商品ごと

| 商品 | RETAIL | BUYBACK | STOCK | LISTING | SOLD | LOTTERY |
|---|---|---|---|---|---|---|
| AirPods Max | REFERENCE | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| AirPods Pro 3 | CONFIRMED | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| Apple Watch Series 11 | REFERENCE | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| Apple Watch Ultra 3 | REFERENCE | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| Canon EOS R3 | REFERENCE | REFERENCE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| Canon EOS R5 Mark II | REFERENCE | REFERENCE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| Canon EOS R6 Mark II | REFERENCE | MISSING | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| FUJIFILM GFX100RF | REFERENCE | REFERENCE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| FUJIFILM X-T5 | REFERENCE | REFERENCE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| FUJIFILM X100VI | REFERENCE | REFERENCE | MISSING | REFERENCE | REFERENCE | MISSING |
| Leica M11 | REFERENCE | MISSING | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| Leica Q3 | REFERENCE | REFERENCE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| Mac mini M4 | REFERENCE | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| MacBook Air M4 13インチ | REFERENCE | STALE | MISSING | REFERENCE | NOT_IMPLEMENTED | MISSING |
| MacBook Air M4 15インチ | REFERENCE | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| MacBook Pro M4 14インチ | REFERENCE | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| Nikon Z8 | REFERENCE | REFERENCE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| Nikon Z9 | REFERENCE | REFERENCE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| Nikon Zf | REFERENCE | REFERENCE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| Nintendo Switch 2 | CONFIRMED | CONFIRMED | MISSING | REFERENCE | REFERENCE | CONFIRMED |
| Nintendo Switch 2 マリオカートセット | REFERENCE | STALE | MISSING | REFERENCE | NOT_IMPLEMENTED | MISSING |
| PlayStation 5 Digital Edition | REFERENCE | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| PlayStation 5 Pro | CONFIRMED | CONFIRMED | CONFIRMED | REFERENCE | NOT_IMPLEMENTED | CONFIRMED |
| RICOH GR III | REFERENCE | MISSING | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| RICOH GR III HDF | REFERENCE | MISSING | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| RICOH GR IIIx | REFERENCE | REFERENCE | MISSING | REFERENCE | REFERENCE | MISSING |
| RICOH GR IV | CONFIRMED | REFERENCE | CONFIRMED | REFERENCE | REFERENCE | CONFIRMED |
| RICOH GR IV HDF | CONFIRMED | REFERENCE | CONFIRMED | REFERENCE | NOT_IMPLEMENTED | CONFIRMED |
| RICOH GR IV Monochrome | CONFIRMED | REFERENCE | CONFIRMED | REFERENCE | NOT_IMPLEMENTED | CONFIRMED |
| SONY FX3 | REFERENCE | REFERENCE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| SONY α1 II | REFERENCE | REFERENCE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| SONY α7CR | REFERENCE | REFERENCE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| SONY α7R V | REFERENCE | REFERENCE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| Xbox Series X | REFERENCE | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| iPad Air M3 | REFERENCE | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| iPad Pro M4 11インチ | REFERENCE | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| iPad Pro M4 13インチ | REFERENCE | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| iPhone 16 Pro 256GB SIMフリー | REFERENCE | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| iPhone 16 Pro Max 256GB | REFERENCE | STALE | MISSING | MISSING | REFERENCE | MISSING |
| iPhone 16 Pro Max 512GB | REFERENCE | MISSING | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| iPhone 17 256GB SIMフリー | CONFIRMED | STALE | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |
| iPhone 17 Pro 256GB SIMフリー | REFERENCE | CONFIRMED | MISSING | REFERENCE | REFERENCE | MISSING |
| iPhone 17 Pro 512GB SIMフリー | REFERENCE | CONFIRMED | MISSING | REFERENCE | NOT_IMPLEMENTED | MISSING |
| iPhone 17 Pro Max 256GB SIMフリー | REFERENCE | CONFIRMED | MISSING | REFERENCE | NOT_IMPLEMENTED | MISSING |
| iPhone 17 Pro Max 512GB SIMフリー | REFERENCE | CONFIRMED | MISSING | MISSING | NOT_IMPLEMENTED | MISSING |

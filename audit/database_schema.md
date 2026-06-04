# Database Schema — premium_monitor.db

- DB ファイル: `data/premium_monitor.db`
- サイズ: 3.68 MB
- テーブル数: 20

## テーブル一覧（row数）

| テーブル | カラム数 | row数 |
|---|---|---|
| `alerts` ★ | 16 | 0 |
| `beginner_deals` | 28 | 832 |
| `buyback_alerts` | 11 | 42 |
| `buyback_history` | 7 | 6173 |
| `buyback_prices` ★ | 13 | 816 |
| `collector_logs` | 9 | 0 |
| `lottery_events` ★ | 15 | 3 |
| `market_snapshots` | 36 | 1116 |
| `notification_dedup` | 5 | 0 |
| `observations` | 16 | 138 |
| `price_history` | 8 | 1947 |
| `product_candidates` | 28 | 9 |
| `product_source_config` | 9 | 23 |
| `products` ★ | 21 | 45 |
| `publish_queue` | 13 | 14 |
| `sale_prices` ★ | 12 | 137 |
| `schema_migrations` | 2 | 17 |
| `sedori_routes` | 27 | 108 |
| `source_health` | 9 | 0 |
| `sources` | 12 | 48 |

★ = 詳細出力対象

## 詳細テーブル

### `products`  (rows: 45)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| genre | TEXT | ✔ |  |  |
| name | TEXT | ✔ |  |  |
| brand | TEXT |  |  | '' |
| model_number | TEXT |  |  | '' |
| jan_code | TEXT |  |  |  |
| retail_price | INTEGER |  |  | 0 |
| keywords | TEXT |  |  | '[]' |
| image_url | TEXT |  |  |  |
| is_active | INTEGER |  |  | 1 |
| memo | TEXT |  |  | '' |
| created_at | TEXT | ✔ |  |  |
| updated_at | TEXT | ✔ |  |  |
| official_price | INTEGER |  |  |  |
| official_price_source | TEXT |  |  | '' |
| official_price_updated_at | TEXT |  |  |  |
| official_stock_status | TEXT |  |  | '' |
| is_lottery | INTEGER |  |  | 0 |
| is_discontinued | INTEGER |  |  | 0 |
| is_production_ended | INTEGER |  |  | 0 |
| retail_price_update_candidate | INTEGER |  |  | 0 |

**Index:**
- `idx_products_genre` (c) → (genre, is_active)
- `sqlite_autoindex_products_2` (UNIQUE u) → (jan_code)
- `sqlite_autoindex_products_1` (UNIQUE pk) → (id)

### `buyback_prices`  (rows: 816)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| product_id | TEXT | ✔ |  |  |
| shop_id | TEXT | ✔ |  |  |
| shop_name | TEXT | ✔ |  | '' |
| buyback_price | INTEGER | ✔ |  |  |
| condition | TEXT | ✔ |  | 'new_unopened' |
| buyback_url | TEXT |  |  | '' |
| observed_at | TEXT | ✔ |  |  |
| is_active | INTEGER |  |  | 1 |
| notes | TEXT |  |  | '' |
| data_source | TEXT | ✔ |  | 'manual_today' |
| link_verified | INTEGER | ✔ |  | 0 |
| confidence | TEXT | ✔ |  | "high" |

**Index:**
- `idx_buyback_shop` (c) → (shop_id)
- `idx_buyback_product` (c) → (product_id)
- `sqlite_autoindex_buyback_prices_1` (UNIQUE pk) → (id)

### `sale_prices`  (rows: 137)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| product_id | TEXT |  |  |  |
| product_alias | TEXT | ✔ |  | '' |
| shop_name | TEXT | ✔ |  | '' |
| shop_id | TEXT | ✔ |  | '' |
| sale_price | INTEGER | ✔ |  |  |
| condition | TEXT | ✔ |  | 'new_unopened' |
| url | TEXT | ✔ |  | '' |
| link_verified | INTEGER | ✔ |  | 0 |
| observed_at | TEXT | ✔ |  | datetime('now') |
| data_source | TEXT | ✔ |  | 'manual' |
| is_active | INTEGER | ✔ |  | 1 |

**Index:**
- `idx_sale_prices_observed_at` (c) → (observed_at)
- `idx_sale_prices_shop_id` (c) → (shop_id)
- `idx_sale_prices_product_alias` (c) → (product_alias)
- `idx_sale_prices_product_id` (c) → (product_id)
- `sqlite_autoindex_sale_prices_1` (UNIQUE pk) → (id)

**Foreign Keys:**
- product_id → products.id

### `alerts`  (rows: 0)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| observation_id | TEXT | ✔ |  |  |
| product_id | TEXT | ✔ |  |  |
| alert_rank | TEXT | ✔ |  |  |
| alert_type | TEXT | ✔ |  |  |
| title | TEXT | ✔ |  |  |
| body | TEXT | ✔ |  |  |
| estimated_profit | INTEGER |  |  |  |
| score | REAL |  |  |  |
| confidence | REAL |  |  |  |
| is_sent | INTEGER |  |  | 0 |
| sent_channels | TEXT |  |  | '[]' |
| is_false_positive | INTEGER |  |  | 0 |
| is_published | INTEGER |  |  | 0 |
| created_at | TEXT | ✔ |  |  |
| sent_at | TEXT |  |  |  |

**Index:**
- `idx_alerts_product` (c) → (product_id, created_at)
- `idx_alerts_rank` (c) → (alert_rank, created_at)
- `sqlite_autoindex_alerts_1` (UNIQUE pk) → (id)

**Foreign Keys:**
- product_id → products.id
- observation_id → observations.id

### `ranking`
> ⚠ このテーブルは存在しません（DB未作成 or 名称差異）。

### `lottery_events`  (rows: 3)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| product_id | TEXT |  |  |  |
| source_id | TEXT |  |  |  |
| product_name | TEXT | ✔ |  |  |
| brand | TEXT | ✔ |  | '' |
| title | TEXT | ✔ |  | '' |
| sale_method | TEXT | ✔ |  | 'lottery' |
| entry_start_at | TEXT |  |  |  |
| entry_end_at | TEXT |  |  |  |
| result_announcement_at | TEXT |  |  |  |
| sale_start_at | TEXT |  |  |  |
| url | TEXT | ✔ |  | '' |
| status | TEXT | ✔ |  | 'active' |
| detected_at | TEXT | ✔ |  | datetime('now') |
| raw_text | TEXT | ✔ |  | '' |

**Index:**
- `idx_lottery_events_detected_at` (c) → (detected_at)
- `idx_lottery_events_sale_start_at` (c) → (sale_start_at)
- `idx_lottery_events_sale_method` (c) → (sale_method)
- `idx_lottery_events_status` (c) → (status)
- `idx_lottery_events_product_id` (c) → (product_id)
- `sqlite_autoindex_lottery_events_1` (UNIQUE pk) → (id)

**Foreign Keys:**
- source_id → sources.id
- product_id → products.id

## その他テーブル

### `beginner_deals`  (rows: 832)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| product_id | TEXT | ✔ |  |  |
| product_name | TEXT | ✔ |  |  |
| category | TEXT | ✔ |  | '' |
| brand | TEXT | ✔ |  | '' |
| official_price_jpy | INTEGER |  |  |  |
| official_url | TEXT |  |  | '' |
| stock_status | TEXT |  |  | '' |
| sale_method | TEXT |  |  | 'normal' |
| best_buyback_price | INTEGER |  |  |  |
| best_buyback_shop | TEXT |  |  | '' |
| best_buyback_url | TEXT |  |  | '' |
| buyback_condition | TEXT |  |  | '' |
| gross_profit_jpy | INTEGER |  |  | 0 |
| estimated_costs_jpy | INTEGER |  |  | 0 |
| net_profit_jpy | INTEGER |  |  | 0 |
| net_profit_rate | REAL |  |  | 0 |
| beginner_score | REAL |  |  | 0 |
| difficulty_score | REAL |  |  | 0 |
| user_level | TEXT |  |  | '' |
| recommended_action | TEXT |  |  | '' |
| is_active | INTEGER |  |  | 1 |
| scanned_at | TEXT | ✔ |  |  |
| notes | TEXT |  |  | '' |
| median_buyback_price | INTEGER |  |  |  |
| buyback_shop_count | INTEGER | ✔ |  | 1 |
| buyback_prices_json | TEXT | ✔ |  | '' |
| best_link_verified | INTEGER | ✔ |  | 0 |

**Index:**
- `idx_deals_level` (c) → (user_level)
- `idx_deals_product` (c) → (product_id)
- `sqlite_autoindex_beginner_deals_1` (UNIQUE pk) → (id)

### `buyback_alerts`  (rows: 42)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| product_id | TEXT | ✔ |  |  |
| product_name | TEXT | ✔ |  | '' |
| shop_id | TEXT | ✔ |  |  |
| shop_name | TEXT | ✔ |  | '' |
| alert_type | TEXT | ✔ |  | '' |
| previous_price | INTEGER |  |  |  |
| current_price | INTEGER |  |  |  |
| price_change | INTEGER |  |  |  |
| detected_at | TEXT | ✔ |  |  |
| is_notified | INTEGER |  |  | 0 |

**Index:**
- `idx_ba_detected` (c) → (detected_at)
- `sqlite_autoindex_buyback_alerts_1` (UNIQUE pk) → (id)

### `buyback_history`  (rows: 6173)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| product_id | TEXT | ✔ |  |  |
| shop_id | TEXT | ✔ |  |  |
| shop_name | TEXT | ✔ |  | '' |
| price | INTEGER | ✔ |  |  |
| condition | TEXT | ✔ |  | 'new_unopened' |
| observed_at | TEXT | ✔ |  |  |

**Index:**
- `idx_bh_observed` (c) → (observed_at)
- `idx_bh_product` (c) → (product_id, shop_id)
- `sqlite_autoindex_buyback_history_1` (UNIQUE pk) → (id)

### `collector_logs`  (rows: 0)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| source_id | TEXT | ✔ |  |  |
| product_id | TEXT |  |  |  |
| started_at | TEXT | ✔ |  |  |
| finished_at | TEXT |  |  |  |
| status | TEXT | ✔ |  |  |
| http_status | INTEGER |  |  |  |
| error_message | TEXT |  |  |  |
| duration_ms | INTEGER |  |  |  |

**Index:**
- `idx_collector_logs_status` (c) → (status, started_at)
- `sqlite_autoindex_collector_logs_1` (UNIQUE pk) → (id)

**Foreign Keys:**
- source_id → sources.id

### `market_snapshots`  (rows: 1116)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| product_id | TEXT |  |  |  |
| candidate_id | TEXT |  |  |  |
| category | TEXT | ✔ |  | '' |
| brand | TEXT | ✔ |  | '' |
| product_name | TEXT | ✔ |  | '' |
| official_price_jpy | INTEGER |  |  |  |
| domestic_used_price_jpy | INTEGER |  |  |  |
| domestic_buyback_price_jpy | INTEGER |  |  |  |
| overseas_price_jpy | INTEGER |  |  |  |
| overseas_source | TEXT |  |  | '' |
| stock_status | TEXT |  |  | '' |
| sale_method | TEXT |  |  | '' |
| premium_gap_jpy | INTEGER |  |  |  |
| premium_gap_percent | REAL |  |  |  |
| overseas_gap_jpy | INTEGER |  |  |  |
| overseas_gap_percent | REAL |  |  |  |
| premium_score | REAL |  |  | 0 |
| scarcity_score | REAL |  |  | 0 |
| liquidity_score | REAL |  |  | 0 |
| overseas_gap_score | REAL |  |  | 0 |
| source_confidence | REAL |  |  | 0 |
| overall_score | REAL |  |  | 0 |
| captured_at | TEXT | ✔ |  |  |
| beginner_score | REAL |  |  | 0 |
| difficulty_score | REAL |  |  | 0 |
| beginner_profit_score | REAL |  |  | 0 |
| user_level | TEXT |  |  | '' |
| recommended_action | TEXT |  |  | '' |
| gross_profit_jpy | INTEGER |  |  | 0 |
| estimated_costs_jpy | INTEGER |  |  | 0 |
| net_profit_jpy | INTEGER |  |  | 0 |
| net_profit_rate | REAL |  |  | 0 |
| best_buyback_shop | TEXT |  |  | '' |
| best_buyback_url | TEXT |  |  | '' |
| buyback_condition | TEXT |  |  | '' |

**Index:**
- `sqlite_autoindex_market_snapshots_1` (UNIQUE pk) → (id)

### `notification_dedup`  (rows: 0)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| dedup_key | TEXT | ✔ |  |  |
| alert_id | TEXT | ✔ |  |  |
| created_at | TEXT | ✔ |  |  |
| expires_at | TEXT | ✔ |  |  |

**Index:**
- `idx_notification_dedup_key` (c) → (dedup_key)
- `sqlite_autoindex_notification_dedup_2` (UNIQUE u) → (dedup_key)
- `sqlite_autoindex_notification_dedup_1` (UNIQUE pk) → (id)

**Foreign Keys:**
- alert_id → alerts.id

### `observations`  (rows: 138)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| product_id | TEXT | ✔ |  |  |
| source_id | TEXT | ✔ |  |  |
| observation_type | TEXT | ✔ |  |  |
| observed_at | TEXT | ✔ |  |  |
| is_in_stock | INTEGER |  |  |  |
| price | INTEGER |  |  |  |
| buyback_price | INTEGER |  |  |  |
| lottery_status | TEXT |  |  |  |
| lottery_deadline | TEXT |  |  |  |
| raw_text | TEXT |  |  | '' |
| raw_html_hash | TEXT |  |  | '' |
| confidence | REAL |  |  | 1.0 |
| is_false_positive | INTEGER |  |  | 0 |
| is_manually_verified | INTEGER |  |  | 0 |
| created_at | TEXT | ✔ |  |  |

**Index:**
- `idx_observations_type` (c) → (observation_type, observed_at)
- `idx_observations_product` (c) → (product_id, observed_at)
- `sqlite_autoindex_observations_1` (UNIQUE pk) → (id)

**Foreign Keys:**
- source_id → sources.id
- product_id → products.id

### `price_history`  (rows: 1947)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| product_id | TEXT | ✔ |  |  |
| source_id | TEXT | ✔ |  |  |
| price_type | TEXT | ✔ |  |  |
| price | INTEGER | ✔ |  |  |
| currency | TEXT |  |  | 'JPY' |
| recorded_at | TEXT | ✔ |  |  |
| price_basis | TEXT |  |  | '' |

**Index:**
- `idx_price_history_product` (c) → (product_id, price_type, recorded_at)
- `sqlite_autoindex_price_history_1` (UNIQUE pk) → (id)

**Foreign Keys:**
- source_id → sources.id
- product_id → products.id

### `product_candidates`  (rows: 9)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| source_id | TEXT | ✔ |  |  |
| product_name | TEXT | ✔ |  |  |
| detected_keyword | TEXT |  |  | '' |
| detected_url | TEXT |  |  | '' |
| detected_at | TEXT | ✔ |  |  |
| confidence | REAL |  |  | 0.5 |
| status | TEXT |  |  | 'pending' |
| genre | TEXT |  |  | '' |
| brand | TEXT |  |  | '' |
| estimated_price | INTEGER |  |  |  |
| notes | TEXT |  |  | '' |
| reviewed_at | TEXT |  |  |  |
| approved_product_id | TEXT |  |  |  |
| user_level | TEXT |  |  | '' |
| beginner_score | REAL |  |  | 0 |
| difficulty_score | REAL |  |  | 0 |
| reason_for_beginner | TEXT |  |  | '' |
| caution_note | TEXT |  |  | '' |
| detected_source | TEXT |  |  | '' |
| official_price | INTEGER |  |  |  |
| release_date | TEXT |  |  | '' |
| reservation_start_at | TEXT |  |  | '' |
| lottery_start_at | TEXT |  |  | '' |
| lottery_end_at | TEXT |  |  | '' |
| sale_method | TEXT |  |  | 'normal' |
| resale_potential_score | REAL |  |  | 0.0 |
| category | TEXT |  |  | '' |

**Index:**
- `sqlite_autoindex_product_candidates_1` (UNIQUE pk) → (id)

### `product_source_config`  (rows: 23)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| product_id | TEXT | ✔ |  |  |
| source_id | TEXT | ✔ |  |  |
| target_url | TEXT |  |  | '' |
| css_selector_stock | TEXT |  |  | '' |
| css_selector_price | TEXT |  |  | '' |
| extra_config | TEXT |  |  | '{}' |
| is_active | INTEGER |  |  | 1 |
| created_at | TEXT | ✔ |  |  |

**Index:**
- `sqlite_autoindex_product_source_config_1` (UNIQUE pk) → (id)

**Foreign Keys:**
- source_id → sources.id
- product_id → products.id

### `publish_queue`  (rows: 14)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| source_type | TEXT | ✔ |  | 'alert' |
| source_id | TEXT |  |  | '' |
| channel | TEXT | ✔ |  | 'x' |
| title | TEXT | ✔ |  | '' |
| body | TEXT | ✔ |  | '' |
| hashtags | TEXT |  |  | '' |
| rank | TEXT |  |  | '' |
| status | TEXT | ✔ |  | 'draft' |
| generated_at | TEXT | ✔ |  |  |
| approved_at | TEXT |  |  |  |
| published_at | TEXT |  |  |  |
| memo | TEXT |  |  | '' |

**Index:**
- `sqlite_autoindex_publish_queue_1` (UNIQUE pk) → (id)

### `schema_migrations`  (rows: 17)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| version | TEXT |  | PK1 |  |
| applied_at | TEXT | ✔ |  |  |

**Index:**
- `sqlite_autoindex_schema_migrations_1` (UNIQUE pk) → (version)

### `sedori_routes`  (rows: 108)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| product_id | TEXT |  |  |  |
| product_name | TEXT | ✔ |  | '' |
| product_alias | TEXT | ✔ |  | '' |
| buy_shop_name | TEXT | ✔ |  | '' |
| buy_shop_id | TEXT | ✔ |  | '' |
| buy_price | INTEGER | ✔ |  |  |
| buy_url | TEXT | ✔ |  | '' |
| buy_condition | TEXT | ✔ |  | '' |
| sell_shop_name | TEXT | ✔ |  | '' |
| sell_shop_id | TEXT | ✔ |  | '' |
| sell_price | INTEGER | ✔ |  |  |
| sell_url | TEXT | ✔ |  | '' |
| gross_profit | INTEGER | ✔ |  | 0 |
| shipping_fee | INTEGER | ✔ |  | 1000 |
| transfer_fee | INTEGER | ✔ |  | 300 |
| travel_fee | INTEGER | ✔ |  | 500 |
| other_costs | INTEGER | ✔ |  | 0 |
| estimated_costs | INTEGER | ✔ |  | 0 |
| net_profit | INTEGER | ✔ |  | 0 |
| profit_rate | REAL | ✔ |  | 0.0 |
| rank | INTEGER | ✔ |  | 0 |
| calculated_at | TEXT | ✔ |  | datetime('now') |
| route_quality_score | REAL | ✔ |  | 1.0 |
| route_warning_flags | TEXT | ✔ |  | '[]' |
| needs_review | INTEGER | ✔ |  | 0 |
| sort_score | REAL | ✔ |  | 0.0 |

**Index:**
- `idx_sedori_routes_needs_review` (c) → (needs_review)
- `idx_sedori_routes_sort_score` (c) → (sort_score)
- `idx_sedori_routes_calculated_at` (c) → (calculated_at)
- `idx_sedori_routes_rank` (c) → (rank)
- `idx_sedori_routes_net_profit` (c) → (net_profit)
- `idx_sedori_routes_product_alias` (c) → (product_alias)
- `idx_sedori_routes_product_id` (c) → (product_id)
- `sqlite_autoindex_sedori_routes_1` (UNIQUE pk) → (id)

**Foreign Keys:**
- product_id → products.id

### `source_health`  (rows: 0)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| source_id | TEXT |  | PK1 |  |
| last_success_at | TEXT |  |  |  |
| last_error_at | TEXT |  |  |  |
| consecutive_errors | INTEGER |  |  | 0 |
| total_runs_24h | INTEGER |  |  | 0 |
| success_runs_24h | INTEGER |  |  | 0 |
| avg_duration_ms | INTEGER |  |  | 0 |
| auto_disabled | INTEGER |  |  | 0 |
| updated_at | TEXT | ✔ |  |  |

**Index:**
- `sqlite_autoindex_source_health_1` (UNIQUE pk) → (source_id)

### `sources`  (rows: 48)

| カラム | 型 | NotNull | PK | Default |
|---|---|---|---|---|
| id | TEXT |  | PK1 |  |
| name | TEXT | ✔ |  |  |
| source_type | TEXT | ✔ |  |  |
| base_url | TEXT | ✔ |  |  |
| collector_module | TEXT | ✔ |  |  |
| rate_limit_sec | INTEGER |  |  | 60 |
| requires_js | INTEGER |  |  | 0 |
| is_active | INTEGER |  |  | 1 |
| robots_txt_url | TEXT |  |  |  |
| memo | TEXT |  |  | '' |
| created_at | TEXT | ✔ |  |  |
| updated_at | TEXT | ✔ |  |  |

**Index:**
- `idx_sources_type` (c) → (source_type, is_active)
- `sqlite_autoindex_sources_1` (UNIQUE pk) → (id)


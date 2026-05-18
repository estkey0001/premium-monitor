-- Phase 9A: 買取価格専用テーブル + 初心者向け案件テーブル

CREATE TABLE IF NOT EXISTS buyback_prices (
    id                  TEXT PRIMARY KEY,
    product_id          TEXT NOT NULL,
    shop_id             TEXT NOT NULL,
    shop_name           TEXT NOT NULL DEFAULT '',
    buyback_price       INTEGER NOT NULL,
    condition           TEXT NOT NULL DEFAULT 'new_unopened',
    buyback_url         TEXT DEFAULT '',
    observed_at         TEXT NOT NULL,
    is_active           INTEGER DEFAULT 1,
    notes               TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_buyback_product ON buyback_prices(product_id);
CREATE INDEX IF NOT EXISTS idx_buyback_shop ON buyback_prices(shop_id);

CREATE TABLE IF NOT EXISTS beginner_deals (
    id                  TEXT PRIMARY KEY,
    product_id          TEXT NOT NULL,
    product_name        TEXT NOT NULL,
    category            TEXT NOT NULL DEFAULT '',
    brand               TEXT NOT NULL DEFAULT '',
    official_price_jpy  INTEGER,
    official_url        TEXT DEFAULT '',
    stock_status        TEXT DEFAULT '',
    sale_method         TEXT DEFAULT 'normal',
    best_buyback_price  INTEGER,
    best_buyback_shop   TEXT DEFAULT '',
    best_buyback_url    TEXT DEFAULT '',
    buyback_condition   TEXT DEFAULT '',
    gross_profit_jpy    INTEGER DEFAULT 0,
    estimated_costs_jpy INTEGER DEFAULT 0,
    net_profit_jpy      INTEGER DEFAULT 0,
    net_profit_rate     REAL DEFAULT 0,
    beginner_score      REAL DEFAULT 0,
    difficulty_score    REAL DEFAULT 0,
    user_level          TEXT DEFAULT '',
    recommended_action  TEXT DEFAULT '',
    is_active           INTEGER DEFAULT 1,
    scanned_at          TEXT NOT NULL,
    notes               TEXT DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_deals_product ON beginner_deals(product_id);
CREATE INDEX IF NOT EXISTS idx_deals_level ON beginner_deals(user_level);

-- market_snapshots に実利益カラム追加
ALTER TABLE market_snapshots ADD COLUMN gross_profit_jpy INTEGER DEFAULT 0;
ALTER TABLE market_snapshots ADD COLUMN estimated_costs_jpy INTEGER DEFAULT 0;
ALTER TABLE market_snapshots ADD COLUMN net_profit_jpy INTEGER DEFAULT 0;
ALTER TABLE market_snapshots ADD COLUMN net_profit_rate REAL DEFAULT 0;
ALTER TABLE market_snapshots ADD COLUMN best_buyback_shop TEXT DEFAULT '';
ALTER TABLE market_snapshots ADD COLUMN best_buyback_url TEXT DEFAULT '';
ALTER TABLE market_snapshots ADD COLUMN buyback_condition TEXT DEFAULT '';

-- Migration 014: 販売価格・せどりルートテーブル
-- 店舗間せどりルート比較に必要なデータを管理する

-- 販売価格テーブル（仕入れ候補店の販売価格）
CREATE TABLE IF NOT EXISTS sale_prices (
    id TEXT PRIMARY KEY,
    product_id TEXT,
    product_alias TEXT NOT NULL DEFAULT '',
    shop_name TEXT NOT NULL DEFAULT '',
    shop_id TEXT NOT NULL DEFAULT '',
    sale_price INTEGER NOT NULL,
    condition TEXT NOT NULL DEFAULT 'new_unopened',
    -- 'new_unopened'=新品未開封, 'new_opened'=新品開封済, 'used_a'=中古A, 'used_b'=中古B
    url TEXT NOT NULL DEFAULT '',
    link_verified INTEGER NOT NULL DEFAULT 0,
    observed_at TEXT NOT NULL DEFAULT (datetime('now')),
    data_source TEXT NOT NULL DEFAULT 'manual',
    is_active INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sale_prices_product_id ON sale_prices(product_id);
CREATE INDEX IF NOT EXISTS idx_sale_prices_product_alias ON sale_prices(product_alias);
CREATE INDEX IF NOT EXISTS idx_sale_prices_shop_id ON sale_prices(shop_id);
CREATE INDEX IF NOT EXISTS idx_sale_prices_observed_at ON sale_prices(observed_at);

-- せどりルートテーブル（計算済みの仕入れ→売却ルート）
CREATE TABLE IF NOT EXISTS sedori_routes (
    id TEXT PRIMARY KEY,
    product_id TEXT,
    product_name TEXT NOT NULL DEFAULT '',
    product_alias TEXT NOT NULL DEFAULT '',
    -- 仕入れ側（販売店から購入）
    buy_shop_name TEXT NOT NULL DEFAULT '',
    buy_shop_id TEXT NOT NULL DEFAULT '',
    buy_price INTEGER NOT NULL,
    buy_url TEXT NOT NULL DEFAULT '',
    buy_condition TEXT NOT NULL DEFAULT '',
    -- 売却側（買取店へ売却）
    sell_shop_name TEXT NOT NULL DEFAULT '',
    sell_shop_id TEXT NOT NULL DEFAULT '',
    sell_price INTEGER NOT NULL,
    sell_url TEXT NOT NULL DEFAULT '',
    -- 利益計算
    gross_profit INTEGER NOT NULL DEFAULT 0,
    shipping_fee INTEGER NOT NULL DEFAULT 1000,
    transfer_fee INTEGER NOT NULL DEFAULT 300,
    travel_fee INTEGER NOT NULL DEFAULT 500,
    other_costs INTEGER NOT NULL DEFAULT 0,
    estimated_costs INTEGER NOT NULL DEFAULT 0,
    net_profit INTEGER NOT NULL DEFAULT 0,
    profit_rate REAL NOT NULL DEFAULT 0.0,
    rank INTEGER NOT NULL DEFAULT 0,
    calculated_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_sedori_routes_product_id ON sedori_routes(product_id);
CREATE INDEX IF NOT EXISTS idx_sedori_routes_product_alias ON sedori_routes(product_alias);
CREATE INDEX IF NOT EXISTS idx_sedori_routes_net_profit ON sedori_routes(net_profit DESC);
CREATE INDEX IF NOT EXISTS idx_sedori_routes_rank ON sedori_routes(rank);
CREATE INDEX IF NOT EXISTS idx_sedori_routes_calculated_at ON sedori_routes(calculated_at);

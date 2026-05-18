ALTER TABLE products ADD COLUMN official_price INTEGER;
ALTER TABLE products ADD COLUMN official_price_source TEXT DEFAULT '';
ALTER TABLE products ADD COLUMN official_price_updated_at TEXT;
ALTER TABLE products ADD COLUMN official_stock_status TEXT DEFAULT '';
ALTER TABLE products ADD COLUMN is_lottery INTEGER DEFAULT 0;
ALTER TABLE products ADD COLUMN is_discontinued INTEGER DEFAULT 0;
ALTER TABLE products ADD COLUMN is_production_ended INTEGER DEFAULT 0;
ALTER TABLE products ADD COLUMN retail_price_update_candidate INTEGER DEFAULT 0;

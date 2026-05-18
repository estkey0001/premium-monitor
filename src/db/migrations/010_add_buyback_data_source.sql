-- 010_add_buyback_data_source
ALTER TABLE buyback_prices ADD COLUMN data_source TEXT NOT NULL DEFAULT 'manual_today';
ALTER TABLE buyback_prices ADD COLUMN link_verified INTEGER NOT NULL DEFAULT 0;

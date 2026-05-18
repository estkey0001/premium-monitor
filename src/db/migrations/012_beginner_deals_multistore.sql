-- Migration 012: beginner_deals に複数店舗比較カラムを追加
-- 中央値・店舗数・上位5店舗JSON・最高値店舗のlink_verified

ALTER TABLE beginner_deals ADD COLUMN median_buyback_price INTEGER;
ALTER TABLE beginner_deals ADD COLUMN buyback_shop_count INTEGER NOT NULL DEFAULT 1;
ALTER TABLE beginner_deals ADD COLUMN buyback_prices_json TEXT NOT NULL DEFAULT '';
ALTER TABLE beginner_deals ADD COLUMN best_link_verified INTEGER NOT NULL DEFAULT 0;

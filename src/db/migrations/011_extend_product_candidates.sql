-- product_candidatesテーブルに不足カラムを追加 (Phase 14)
ALTER TABLE product_candidates ADD COLUMN detected_source TEXT DEFAULT '';
ALTER TABLE product_candidates ADD COLUMN official_price INTEGER;
ALTER TABLE product_candidates ADD COLUMN release_date TEXT DEFAULT '';
ALTER TABLE product_candidates ADD COLUMN reservation_start_at TEXT DEFAULT '';
ALTER TABLE product_candidates ADD COLUMN lottery_start_at TEXT DEFAULT '';
ALTER TABLE product_candidates ADD COLUMN lottery_end_at TEXT DEFAULT '';
ALTER TABLE product_candidates ADD COLUMN sale_method TEXT DEFAULT 'normal';
ALTER TABLE product_candidates ADD COLUMN resale_potential_score REAL DEFAULT 0.0;
ALTER TABLE product_candidates ADD COLUMN category TEXT DEFAULT '';

-- Phase 7B-2: 初心者向け/上級者向け分類スコアリング

-- market_snapshots にビギナー評価列を追加
ALTER TABLE market_snapshots ADD COLUMN beginner_score REAL DEFAULT 0;
ALTER TABLE market_snapshots ADD COLUMN difficulty_score REAL DEFAULT 0;
ALTER TABLE market_snapshots ADD COLUMN beginner_profit_score REAL DEFAULT 0;
ALTER TABLE market_snapshots ADD COLUMN user_level TEXT DEFAULT '';
ALTER TABLE market_snapshots ADD COLUMN recommended_action TEXT DEFAULT '';

-- product_candidates にビギナー評価列を追加
ALTER TABLE product_candidates ADD COLUMN user_level TEXT DEFAULT '';
ALTER TABLE product_candidates ADD COLUMN beginner_score REAL DEFAULT 0;
ALTER TABLE product_candidates ADD COLUMN difficulty_score REAL DEFAULT 0;
ALTER TABLE product_candidates ADD COLUMN reason_for_beginner TEXT DEFAULT '';
ALTER TABLE product_candidates ADD COLUMN caution_note TEXT DEFAULT '';

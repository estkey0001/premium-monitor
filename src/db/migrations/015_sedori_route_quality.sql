-- Migration 015: せどりルート品質チェックフィールド追加
-- route_quality_score / warning_flags / needs_review / sort_score を追加

ALTER TABLE sedori_routes ADD COLUMN route_quality_score REAL NOT NULL DEFAULT 1.0;
-- 品質スコア (0.0〜1.0) 高いほど信頼性が高い

ALTER TABLE sedori_routes ADD COLUMN route_warning_flags TEXT NOT NULL DEFAULT '[]';
-- JSON配列: ["condition_mismatch", "stale_sale_price", ...]

ALTER TABLE sedori_routes ADD COLUMN needs_review INTEGER NOT NULL DEFAULT 0;
-- 1=要確認（異常値・条件ズレ等）, 0=通常

ALTER TABLE sedori_routes ADD COLUMN sort_score REAL NOT NULL DEFAULT 0.0;
-- net_profit * route_quality_score で算出。並び順に使用

-- インデックス追加
CREATE INDEX IF NOT EXISTS idx_sedori_routes_sort_score ON sedori_routes(sort_score DESC);
CREATE INDEX IF NOT EXISTS idx_sedori_routes_needs_review ON sedori_routes(needs_review);

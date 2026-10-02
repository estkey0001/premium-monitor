-- Migration 019: sale_prices に価格の種別（src/market/price_types.py の正本の値）を保存する
-- 出品（LISTING）と成約（SOLD）を店名の文字列から推測しないため。
-- 種別が記録されていない既存の行は UNKNOWN（推測で SOLD にしない）。

ALTER TABLE sale_prices ADD COLUMN price_type TEXT NOT NULL DEFAULT 'UNKNOWN';

-- 集計値のとき、元にした件数（出品の中央値なら出品の件数）
ALTER TABLE sale_prices ADD COLUMN sample_count INTEGER;

-- SOLD のときの成約日時（無ければ空。期間集計の成約データには使えない）
ALTER TABLE sale_prices ADD COLUMN sold_at TEXT NOT NULL DEFAULT '';

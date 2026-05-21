-- Migration 016: price_history に price_basis カラムを追加
-- 価格種別ラベル（出品価格 / 成約価格 / 中古販売価格 / 海外sold / 海外販売価格 等）

ALTER TABLE price_history ADD COLUMN price_basis TEXT DEFAULT '';

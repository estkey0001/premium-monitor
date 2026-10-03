-- Migration 020: 公式の在庫表示を確認した日時を、価格の確認日時とは別に持つ
-- 在庫の根拠（「在庫あり」「SOLD OUT」などの表示）がページに無かった取得では空のまま
-- （価格が取れた＝在庫ありと推測しない）。既存の行は空（確認日時不明 → 在庫未確認として扱う）。

ALTER TABLE products ADD COLUMN official_stock_observed_at TEXT NOT NULL DEFAULT '';

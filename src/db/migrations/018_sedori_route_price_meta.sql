-- Migration 018: せどりルートに正規化価格メタ情報を追加
-- normalized_price_observations を唯一の入力源とするため、各ルートに
-- 仕入れ/売却の price_type と source（正規化観測由来）を保持する。

ALTER TABLE sedori_routes ADD COLUMN buy_price_type TEXT NOT NULL DEFAULT '';
-- 仕入れ価格の種別: shop_sale_price / flea_listing_price / flea_sold_price / overseas_listing_price

ALTER TABLE sedori_routes ADD COLUMN sell_price_type TEXT NOT NULL DEFAULT '';
-- 売却価格の種別: buyback_price / overseas_sold_price

ALTER TABLE sedori_routes ADD COLUMN buy_source TEXT NOT NULL DEFAULT '';
-- 仕入れソース（source_id 等。例: src_geo, メルカリ, src_ebay）

ALTER TABLE sedori_routes ADD COLUMN sell_source TEXT NOT NULL DEFAULT '';
-- 売却ソース（source_id 等。例: src_janpara, overseas_src_ebay）

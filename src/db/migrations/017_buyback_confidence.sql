-- Phase 17: 買取価格の confidence（信頼度）カラム追加
-- high=商品名マッチあり, mid=部分マッチ, low=extract_price()使用（最高値フォールバック）

ALTER TABLE buyback_prices ADD COLUMN confidence TEXT NOT NULL DEFAULT 'high';

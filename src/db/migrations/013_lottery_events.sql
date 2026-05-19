-- Migration 013: 抽選・販売イベントテーブル
-- 商品の抽選販売・予約・限定販売情報を管理する

CREATE TABLE IF NOT EXISTS lottery_events (
    id TEXT PRIMARY KEY,
    product_id TEXT,
    source_id TEXT,
    product_name TEXT NOT NULL,
    brand TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    sale_method TEXT NOT NULL DEFAULT 'lottery',
    -- 'lottery'=抽選, 'reservation'=予約, 'limited'=数量限定, 'soldout'=売り切れ, 'waiting'=入荷待ち
    entry_start_at TEXT,
    entry_end_at TEXT,
    result_announcement_at TEXT,
    sale_start_at TEXT,
    url TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'active',
    -- 'active'=受付中, 'closed'=締切, 'announced'=結果発表済み, 'expired'=期限切れ
    detected_at TEXT NOT NULL DEFAULT (datetime('now')),
    raw_text TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (product_id) REFERENCES products(id) ON DELETE SET NULL,
    FOREIGN KEY (source_id) REFERENCES sources(id) ON DELETE SET NULL
);

CREATE INDEX IF NOT EXISTS idx_lottery_events_product_id ON lottery_events(product_id);
CREATE INDEX IF NOT EXISTS idx_lottery_events_status ON lottery_events(status);
CREATE INDEX IF NOT EXISTS idx_lottery_events_sale_method ON lottery_events(sale_method);
CREATE INDEX IF NOT EXISTS idx_lottery_events_sale_start_at ON lottery_events(sale_start_at);
CREATE INDEX IF NOT EXISTS idx_lottery_events_detected_at ON lottery_events(detected_at);

-- 買取価格推移 + 買取価格急変アラート

CREATE TABLE IF NOT EXISTS buyback_history (
    id              TEXT PRIMARY KEY,
    product_id      TEXT NOT NULL,
    shop_id         TEXT NOT NULL,
    shop_name       TEXT NOT NULL DEFAULT '',
    price           INTEGER NOT NULL,
    condition       TEXT NOT NULL DEFAULT 'new_unopened',
    observed_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_bh_product ON buyback_history(product_id, shop_id);
CREATE INDEX IF NOT EXISTS idx_bh_observed ON buyback_history(observed_at DESC);

CREATE TABLE IF NOT EXISTS buyback_alerts (
    id              TEXT PRIMARY KEY,
    product_id      TEXT NOT NULL,
    product_name    TEXT NOT NULL DEFAULT '',
    shop_id         TEXT NOT NULL,
    shop_name       TEXT NOT NULL DEFAULT '',
    alert_type      TEXT NOT NULL DEFAULT '',
    previous_price  INTEGER,
    current_price   INTEGER,
    price_change    INTEGER,
    detected_at     TEXT NOT NULL,
    is_notified     INTEGER DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_ba_detected ON buyback_alerts(detected_at DESC);

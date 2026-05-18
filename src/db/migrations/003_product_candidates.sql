CREATE TABLE IF NOT EXISTS product_candidates (
    id              TEXT PRIMARY KEY,
    source_id       TEXT NOT NULL,
    product_name    TEXT NOT NULL,
    detected_keyword TEXT DEFAULT '',
    detected_url    TEXT DEFAULT '',
    detected_at     TEXT NOT NULL,
    confidence      REAL DEFAULT 0.5,
    status          TEXT DEFAULT 'pending',
    genre           TEXT DEFAULT '',
    brand           TEXT DEFAULT '',
    estimated_price INTEGER,
    notes           TEXT DEFAULT '',
    reviewed_at     TEXT,
    approved_product_id TEXT
)

CREATE TABLE IF NOT EXISTS publish_queue (
    id              TEXT PRIMARY KEY,
    source_type     TEXT NOT NULL DEFAULT 'alert',
    source_id       TEXT DEFAULT '',
    channel         TEXT NOT NULL DEFAULT 'x',
    title           TEXT NOT NULL DEFAULT '',
    body            TEXT NOT NULL DEFAULT '',
    hashtags        TEXT DEFAULT '',
    rank            TEXT DEFAULT '',
    status          TEXT NOT NULL DEFAULT 'draft',
    generated_at    TEXT NOT NULL,
    approved_at     TEXT,
    published_at    TEXT,
    memo            TEXT DEFAULT ''
)

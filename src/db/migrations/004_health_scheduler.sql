CREATE TABLE IF NOT EXISTS source_health (
    source_id           TEXT PRIMARY KEY,
    last_success_at     TEXT,
    last_error_at       TEXT,
    consecutive_errors  INTEGER DEFAULT 0,
    total_runs_24h      INTEGER DEFAULT 0,
    success_runs_24h    INTEGER DEFAULT 0,
    avg_duration_ms     INTEGER DEFAULT 0,
    auto_disabled       INTEGER DEFAULT 0,
    updated_at          TEXT NOT NULL
)

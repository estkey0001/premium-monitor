-- =============================================
-- 001_initial.sql - 初期スキーマ
-- プレ値商品監視・速報システム
-- =============================================

-- 商品マスタ
CREATE TABLE IF NOT EXISTS products (
    id              TEXT PRIMARY KEY,
    genre           TEXT NOT NULL,
    name            TEXT NOT NULL,
    brand           TEXT DEFAULT '',
    model_number    TEXT DEFAULT '',
    jan_code        TEXT UNIQUE,
    retail_price    INTEGER DEFAULT 0,
    keywords        TEXT DEFAULT '[]',       -- JSON配列
    image_url       TEXT,
    is_active       INTEGER DEFAULT 1,
    memo            TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- 情報源マスタ
CREATE TABLE IF NOT EXISTS sources (
    id              TEXT PRIMARY KEY,
    name            TEXT NOT NULL,
    source_type     TEXT NOT NULL,
    base_url        TEXT NOT NULL,
    collector_module TEXT NOT NULL,
    rate_limit_sec  INTEGER DEFAULT 60,
    requires_js     INTEGER DEFAULT 0,
    is_active       INTEGER DEFAULT 1,
    robots_txt_url  TEXT,
    memo            TEXT DEFAULT '',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL
);

-- 商品×情報源 設定
CREATE TABLE IF NOT EXISTS product_source_config (
    id                  TEXT PRIMARY KEY,
    product_id          TEXT NOT NULL REFERENCES products(id),
    source_id           TEXT NOT NULL REFERENCES sources(id),
    target_url          TEXT DEFAULT '',
    css_selector_stock  TEXT DEFAULT '',
    css_selector_price  TEXT DEFAULT '',
    extra_config        TEXT DEFAULT '{}',    -- JSON
    is_active           INTEGER DEFAULT 1,
    created_at          TEXT NOT NULL
);

-- 取得データ
CREATE TABLE IF NOT EXISTS observations (
    id                   TEXT PRIMARY KEY,
    product_id           TEXT NOT NULL REFERENCES products(id),
    source_id            TEXT NOT NULL REFERENCES sources(id),
    observation_type     TEXT NOT NULL,
    observed_at          TEXT NOT NULL,
    is_in_stock          INTEGER,             -- NULL許可
    price                INTEGER,
    buyback_price        INTEGER,
    lottery_status       TEXT,
    lottery_deadline     TEXT,
    raw_text             TEXT DEFAULT '',
    raw_html_hash        TEXT DEFAULT '',
    confidence           REAL DEFAULT 1.0,
    is_false_positive    INTEGER DEFAULT 0,
    is_manually_verified INTEGER DEFAULT 0,
    created_at           TEXT NOT NULL
);

-- 価格推移
CREATE TABLE IF NOT EXISTS price_history (
    id          TEXT PRIMARY KEY,
    product_id  TEXT NOT NULL REFERENCES products(id),
    source_id   TEXT NOT NULL REFERENCES sources(id),
    price_type  TEXT NOT NULL,
    price       INTEGER NOT NULL,
    currency    TEXT DEFAULT 'JPY',
    recorded_at TEXT NOT NULL,
    price_basis TEXT DEFAULT ''
);

-- 通知ログ
CREATE TABLE IF NOT EXISTS alerts (
    id               TEXT PRIMARY KEY,
    observation_id   TEXT NOT NULL REFERENCES observations(id),
    product_id       TEXT NOT NULL REFERENCES products(id),
    alert_rank       TEXT NOT NULL,
    alert_type       TEXT NOT NULL,
    title            TEXT NOT NULL,
    body             TEXT NOT NULL,
    estimated_profit INTEGER,
    score            REAL,
    confidence       REAL,
    is_sent          INTEGER DEFAULT 0,
    sent_channels    TEXT DEFAULT '[]',   -- JSON配列
    is_false_positive INTEGER DEFAULT 0,
    is_published     INTEGER DEFAULT 0,
    created_at       TEXT NOT NULL,
    sent_at          TEXT
);

-- Collector実行ログ
CREATE TABLE IF NOT EXISTS collector_logs (
    id            TEXT PRIMARY KEY,
    source_id     TEXT NOT NULL REFERENCES sources(id),
    product_id    TEXT,
    started_at    TEXT NOT NULL,
    finished_at   TEXT,
    status        TEXT NOT NULL,
    http_status   INTEGER,
    error_message TEXT,
    duration_ms   INTEGER
);

-- 重複通知防止
CREATE TABLE IF NOT EXISTS notification_dedup (
    id         TEXT PRIMARY KEY,
    dedup_key  TEXT UNIQUE NOT NULL,
    alert_id   TEXT NOT NULL REFERENCES alerts(id),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- マイグレーション履歴
CREATE TABLE IF NOT EXISTS schema_migrations (
    version    TEXT PRIMARY KEY,
    applied_at TEXT NOT NULL
);

-- =============================================
-- インデックス
-- =============================================
CREATE INDEX IF NOT EXISTS idx_observations_product
    ON observations(product_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_observations_type
    ON observations(observation_type, observed_at DESC);

CREATE INDEX IF NOT EXISTS idx_price_history_product
    ON price_history(product_id, price_type, recorded_at DESC);

CREATE INDEX IF NOT EXISTS idx_alerts_rank
    ON alerts(alert_rank, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_alerts_product
    ON alerts(product_id, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_collector_logs_status
    ON collector_logs(status, started_at DESC);

CREATE INDEX IF NOT EXISTS idx_notification_dedup_key
    ON notification_dedup(dedup_key);

CREATE INDEX IF NOT EXISTS idx_products_genre
    ON products(genre, is_active);

CREATE INDEX IF NOT EXISTS idx_sources_type
    ON sources(source_type, is_active);

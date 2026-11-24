-- PakGovJobs schema for the local SQLite fallback (used when DATABASE_URL is not set).
-- Mirrors db/schema.sql (PostgreSQL). Idempotent. Dates are stored as ISO-8601 text; booleans as 0/1.
-- All business dates are Asia/Karachi (PKT); "today" is computed by the application, never by the database.

CREATE TABLE IF NOT EXISTS sources (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    name             TEXT        NOT NULL,
    url              TEXT        NOT NULL UNIQUE,
    sector           TEXT        NOT NULL
        CHECK (sector IN ('Federal','Provincial','Armed Forces','Police','Medical','Testing','Development & Societies','Banking & Finance')),
    province         TEXT        NOT NULL DEFAULT 'All Pakistan',
    is_active        BOOLEAN     NOT NULL DEFAULT 1,
    last_crawled_at  TIMESTAMPTZ,
    last_status      TEXT,
    last_error       TEXT,
    last_links_found INTEGER,
    last_new_jobs    INTEGER,
    last_duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS jobs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    slug             TEXT        NOT NULL UNIQUE,
    source_hash      TEXT        NOT NULL UNIQUE,
    source_id        INTEGER     REFERENCES sources(id) ON DELETE SET NULL,
    title            TEXT        NOT NULL,
    department       TEXT,
    sector           TEXT        NOT NULL
        CHECK (sector IN ('Federal','Provincial','Armed Forces','Police','Medical','Testing','Development & Societies','Banking & Finance')),
    province         TEXT        NOT NULL DEFAULT 'All Pakistan',
    education        TEXT,
    education_level  TEXT,
    total_posts      INTEGER,
    publish_date     DATE        NOT NULL,
    last_date        DATE,
    status           TEXT        NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','expired')),
    official_apply_url TEXT      NOT NULL,
    ad_media_url     TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    parse_method     TEXT        NOT NULL DEFAULT 'ai'
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_last_date ON jobs (status, last_date);
CREATE INDEX IF NOT EXISTS idx_jobs_sector   ON jobs (sector);
CREATE INDEX IF NOT EXISTS idx_jobs_province ON jobs (province);
CREATE INDEX IF NOT EXISTS idx_jobs_edu      ON jobs (education_level);
CREATE INDEX IF NOT EXISTS idx_jobs_created  ON jobs (created_at DESC);

CREATE TABLE IF NOT EXISTS seen_links (
    link_hash     TEXT PRIMARY KEY,
    source_id     INTEGER REFERENCES sources(id) ON DELETE CASCADE,
    url           TEXT NOT NULL,
    title         TEXT,
    is_job        BOOLEAN NOT NULL DEFAULT 0,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
);

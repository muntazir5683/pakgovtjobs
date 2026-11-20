-- PakGovJobs schema (PostgreSQL 14+). Idempotent: safe to run repeatedly.
-- All business dates are Asia/Karachi (PKT). `last_date` is a plain DATE (a PKT calendar day);
-- "today" is always computed by the application in PKT and passed in, never CURRENT_DATE.

CREATE TABLE IF NOT EXISTS sources (
    id               SERIAL PRIMARY KEY,
    name             TEXT        NOT NULL,
    url              TEXT        NOT NULL UNIQUE,
    sector           TEXT        NOT NULL
        CHECK (sector IN ('Federal','Provincial','Armed Forces','Police','Medical','Testing','Development & Societies','Banking & Finance')),
    province         TEXT        NOT NULL DEFAULT 'All Pakistan',
    is_active        BOOLEAN     NOT NULL DEFAULT TRUE,
    last_crawled_at  TIMESTAMPTZ,
    -- crawler health (shown on /admin)
    last_status      TEXT,            -- 'ok' | 'error' | 'running'
    last_error       TEXT,
    last_links_found INTEGER,
    last_new_jobs    INTEGER,
    last_duration_ms INTEGER
);

CREATE TABLE IF NOT EXISTS jobs (
    id               BIGSERIAL PRIMARY KEY,
    slug             TEXT        NOT NULL UNIQUE,
    source_hash      TEXT        NOT NULL UNIQUE,      -- sha256(url + title)
    source_id        INTEGER     REFERENCES sources(id) ON DELETE SET NULL,
    title            TEXT        NOT NULL,
    department       TEXT,
    sector           TEXT        NOT NULL
        CHECK (sector IN ('Federal','Provincial','Armed Forces','Police','Medical','Testing','Development & Societies','Banking & Finance')),
    province         TEXT        NOT NULL DEFAULT 'All Pakistan',
    education        TEXT,                              -- free text, as written in the ad
    education_level  TEXT,                              -- normalized facet used by the filter
    total_posts      INTEGER,
    publish_date     DATE        NOT NULL,
    last_date        DATE,                              -- NULL = deadline not stated in the ad
    status           TEXT        NOT NULL DEFAULT 'active'
        CHECK (status IN ('active','expired')),
    official_apply_url TEXT      NOT NULL,
    ad_media_url     TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_jobs_status_last_date ON jobs (status, last_date);
CREATE INDEX IF NOT EXISTS idx_jobs_sector   ON jobs (sector);
CREATE INDEX IF NOT EXISTS idx_jobs_province ON jobs (province);
CREATE INDEX IF NOT EXISTS idx_jobs_edu      ON jobs (education_level);
CREATE INDEX IF NOT EXISTS idx_jobs_created  ON jobs (created_at DESC);

-- Every candidate link the crawler has evaluated (job or not), so that non-job links
-- and already-processed links are never sent to the AI extractor twice.
CREATE TABLE IF NOT EXISTS seen_links (
    link_hash     TEXT PRIMARY KEY,                     -- sha256(url + title)
    source_id     INTEGER REFERENCES sources(id) ON DELETE CASCADE,
    url           TEXT NOT NULL,
    title         TEXT,
    is_job        BOOLEAN NOT NULL DEFAULT FALSE,
    first_seen_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- How the row was produced: 'ai' (Gemini) or 'fallback' (non-AI link/table parser, used when Gemini is unavailable).
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS parse_method TEXT NOT NULL DEFAULT 'ai';

-- Widen the sector check on databases created before 'Development & Societies' / 'Banking & Finance' existed.
-- (Guarded, so normal startups do not re-validate the tables.)
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['sources','jobs'] LOOP
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid = t::regclass AND conname = t || '_sector_check'
                   AND pg_get_constraintdef(oid) LIKE '%Banking & Finance%') THEN
      EXECUTE format('ALTER TABLE %I DROP CONSTRAINT IF EXISTS %I', t, t || '_sector_check');
      EXECUTE format('ALTER TABLE %I ADD CONSTRAINT %I CHECK (sector IN (''Federal'',''Provincial'',''Armed Forces'',''Police'',''Medical'',''Testing'',''Development & Societies'',''Banking & Finance''))', t, t || '_sector_check');
    END IF;
  END LOOP;
END $$;

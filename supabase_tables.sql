-- supabase_tables.sql
-- =====================================================================
-- Run these statements in the Supabase SQL editor (Dashboard > SQL)
-- to create the tables required for local SQLite → Supabase sync.
--
-- These tables power the cloud dashboard tabs:
--   • NHL Hits & Blocks  → nhl_hits_blocks_picks
--   • MLB Season Props   → mlb_season_projections
--   • MLB SZLN ML Picks  → mlb_szln_picks
-- =====================================================================


-- ── NHL Hits & Blocks ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS nhl_hits_blocks_picks (
    id                 BIGSERIAL PRIMARY KEY,
    run_date           TEXT        NOT NULL,   -- "YYYY-MM-DD", unique key
    generated_at       TEXT        NOT NULL,   -- ISO timestamp when Claude ran
    raw_output         TEXT        NOT NULL,   -- Full markdown text from Claude
    model              TEXT        NOT NULL DEFAULT '',
    prompt_tokens      INTEGER     NOT NULL DEFAULT 0,
    completion_tokens  INTEGER     NOT NULL DEFAULT 0,
    games_count        INTEGER     NOT NULL DEFAULT 0,
    odds_source        TEXT        NOT NULL DEFAULT 'grok_search',
    synced_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Unique constraint: one row per run_date (upsert key)
CREATE UNIQUE INDEX IF NOT EXISTS nhl_hits_blocks_picks_run_date_idx
    ON nhl_hits_blocks_picks (run_date);

-- Fast lookup by run_date (dashboard date selector)
CREATE INDEX IF NOT EXISTS nhl_hits_blocks_picks_run_date_brin
    ON nhl_hits_blocks_picks (run_date DESC);


-- ── MLB Season Projections ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS mlb_season_projections (
    id            BIGSERIAL PRIMARY KEY,
    season        TEXT     NOT NULL,   -- e.g. "2026"
    player_name   TEXT     NOT NULL,
    player_id     INTEGER,             -- MLB Stats API player ID (nullable for new players)
    team          TEXT,
    player_type   TEXT     NOT NULL,   -- "batter" | "pitcher"
    stat          TEXT     NOT NULL,   -- "hr", "k_total", etc.
    projection    REAL     NOT NULL,
    std_dev       REAL,
    confidence    TEXT,                -- "HIGH" | "MEDIUM" | "LOW" | "VERY LOW"
    seasons_used  INTEGER,
    age           INTEGER,
    method        TEXT     NOT NULL DEFAULT 'marcel',
    created_at    TEXT     NOT NULL,
    synced_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Unique constraint: one projection per (season, player_name, stat)
CREATE UNIQUE INDEX IF NOT EXISTS mlb_season_projections_unique_idx
    ON mlb_season_projections (season, player_name, stat);

-- Fast filter by season + player_type + stat (dashboard Rankings tab)
CREATE INDEX IF NOT EXISTS mlb_season_projections_season_idx
    ON mlb_season_projections (season DESC, player_type, stat);

CREATE INDEX IF NOT EXISTS mlb_season_projections_player_idx
    ON mlb_season_projections (player_name);


-- ── MLB SZLN ML Picks ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS mlb_szln_picks (
    id              BIGSERIAL PRIMARY KEY,
    season          TEXT     NOT NULL,   -- e.g. "2026"
    fetched_at      TEXT     NOT NULL,   -- ISO timestamp of the PrizePicks fetch batch
    player_name     TEXT     NOT NULL,
    player_id       INTEGER,
    team            TEXT,
    player_type     TEXT     NOT NULL,   -- "batter" | "pitcher"
    stat            TEXT     NOT NULL,
    pp_stat_type    TEXT,                -- PrizePicks display label
    line            REAL     NOT NULL,
    odds_type       TEXT,                -- "standard" | "goblin" | "demon"
    direction       TEXT     NOT NULL,   -- "OVER" | "UNDER"
    probability     REAL     NOT NULL,
    edge            REAL,
    projection      REAL,
    std_dev         REAL,
    confidence      TEXT,
    model_used      TEXT,               -- "ml" | "stat"
    key_factors     TEXT,               -- JSON or free-text string
    recommendation  TEXT,
    created_at      TEXT     NOT NULL,
    synced_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Unique constraint: one pick per (season, player_name, stat, fetched_at)
CREATE UNIQUE INDEX IF NOT EXISTS mlb_szln_picks_unique_idx
    ON mlb_szln_picks (season, player_name, stat, fetched_at);

-- Fast filter by season + fetched_at (dashboard SZLN tab)
CREATE INDEX IF NOT EXISTS mlb_szln_picks_season_fetched_idx
    ON mlb_szln_picks (season DESC, fetched_at DESC);

CREATE INDEX IF NOT EXISTS mlb_szln_picks_player_idx
    ON mlb_szln_picks (player_name);

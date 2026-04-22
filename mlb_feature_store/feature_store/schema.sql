-- MLB Feature Store — DuckDB schema
-- Run via build_duckdb.initialize_schema()

CREATE TABLE IF NOT EXISTS ingestion_metadata (
    data_type          VARCHAR  NOT NULL,
    last_ingested_date DATE     NOT NULL,
    updated_at         TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (data_type)
);

CREATE TABLE IF NOT EXISTS hitters_daily (
    player_id     VARCHAR  NOT NULL,
    date          DATE     NOT NULL,
    avg_ev        DOUBLE,
    avg_la        DOUBLE,
    xwoba         DOUBLE,
    pa            INTEGER,
    hard_hit_rate DOUBLE,
    PRIMARY KEY (player_id, date)
);

CREATE TABLE IF NOT EXISTS pitchers_daily (
    pitcher_id    VARCHAR  NOT NULL,
    date          DATE     NOT NULL,
    avg_velocity  DOUBLE,
    avg_break_x   DOUBLE,
    avg_break_z   DOUBLE,
    xwoba_allowed DOUBLE,
    whiff_rate    DOUBLE,
    pitches_thrown INTEGER,
    PRIMARY KEY (pitcher_id, date)
);

CREATE TABLE IF NOT EXISTS player_features (
    player_id          VARCHAR NOT NULL,
    date               DATE    NOT NULL,
    wrc_plus           DOUBLE,
    wpa                DOUBLE,
    re24               DOUBLE,
    avg_ev             DOUBLE,
    avg_la             DOUBLE,
    xwoba              DOUBLE,
    ev_7d              DOUBLE,
    xwoba_14d          DOUBLE,
    opp_strength_7d    DOUBLE,
    park_adjusted_woba DOUBLE,
    PRIMARY KEY (player_id, date)
);

CREATE TABLE IF NOT EXISTS pitcher_features (
    pitcher_id           VARCHAR NOT NULL,
    date                 DATE    NOT NULL,
    avg_velocity         DOUBLE,
    whiff_rate           DOUBLE,
    xwoba_allowed        DOUBLE,
    velocity_trend_7d    DOUBLE,
    opponent_strength    DOUBLE,
    park_adjusted_xwoba  DOUBLE,
    PRIMARY KEY (pitcher_id, date)
);

-- Prop outcome labels — actual stat values per player per game.
-- Apply any line threshold at query time: actual_value > line => OVER.
-- RBI, Runs, HRR require box score ingestion (future work).

CREATE TABLE IF NOT EXISTS hitter_labels (
    player_id   VARCHAR NOT NULL,
    game_date   DATE    NOT NULL,
    hits        INTEGER,
    total_bases INTEGER,
    home_runs   INTEGER,
    PRIMARY KEY (player_id, game_date)
);

CREATE TABLE IF NOT EXISTS pitcher_labels (
    player_id     VARCHAR NOT NULL,
    game_date     DATE    NOT NULL,
    strikeouts    INTEGER,
    walks         INTEGER,
    outs_recorded INTEGER,
    PRIMARY KEY (player_id, game_date)
);

-- Player name lookup — seeded from main MLB DB + pybaseball chadwick register.
-- Updated by ml/build_players.py.
CREATE TABLE IF NOT EXISTS players (
    player_id    VARCHAR PRIMARY KEY,
    player_name  VARCHAR NOT NULL,
    player_type  VARCHAR,           -- 'hitter', 'pitcher', 'both'
    updated_at   TIMESTAMP DEFAULT current_timestamp
);

-- ML model predictions — one row per (player, date, prop).
-- predicted_value is the raw regressor output (expected count).
-- Use Poisson CDF at query time to get P(OVER line).
-- game_date is the date predictions were generated FOR (not when generated).
CREATE TABLE IF NOT EXISTS ml_predictions (
    player_id       VARCHAR  NOT NULL,
    player_name     VARCHAR,
    game_date       DATE     NOT NULL,
    prop            VARCHAR  NOT NULL,
    predicted_value DOUBLE,
    model_version   VARCHAR  DEFAULT 'xgboost_v1',
    created_at      TIMESTAMP DEFAULT current_timestamp,
    PRIMARY KEY (player_id, game_date, prop)
);

-- Tracks which dates have been ML-graded so we don't double-grade.
CREATE TABLE IF NOT EXISTS ml_grading_log (
    game_date  DATE PRIMARY KEY,
    graded_at  TIMESTAMP DEFAULT current_timestamp,
    rows_graded INTEGER
);

CREATE TABLE IF NOT EXISTS name_aliases (
    fs_name        VARCHAR PRIMARY KEY,
    canonical_name VARCHAR NOT NULL,
    updated_at     TIMESTAMP DEFAULT current_timestamp
);

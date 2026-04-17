/// Database layer — SQLite via sqlx (runtime queries, no compile-time DATABASE_URL needed).
///
/// Handles:
///   - Schema creation (idempotent)
///   - UPSERT into `current_lines`
///   - INSERT into `line_history` whenever a line value changes
///   - Table creation for `news_context` and `watchlist` (written by Python layer)

use anyhow::Result;
use chrono::Utc;
use sqlx::{sqlite::SqlitePoolOptions, Row, SqlitePool};
use tracing::debug;

use crate::types::{Source, UnifiedProp};

// ── Schema ───────────────────────────────────────────────────────────────────

const SCHEMA: &str = r#"
PRAGMA journal_mode = WAL;
PRAGMA synchronous   = NORMAL;
PRAGMA foreign_keys  = ON;

CREATE TABLE IF NOT EXISTS current_lines (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id        TEXT    NOT NULL,
    name             TEXT    NOT NULL,
    team             TEXT,
    opponent         TEXT,
    sport            TEXT    NOT NULL,
    stat_type        TEXT    NOT NULL,

    prizepicks_line  REAL,
    underdog_line    REAL,
    kalshi_price     REAL,
    kalshi_market_id TEXT,

    ml_confidence    REAL,
    ml_prediction    TEXT,
    ml_tier          TEXT,
    ml_edge          REAL,
    odds_type        TEXT,

    line_discrepancy REAL,
    is_volatile      INTEGER DEFAULT 0,

    last_updated     TEXT    NOT NULL,

    UNIQUE(player_id, stat_type)
);

CREATE TABLE IF NOT EXISTS line_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   TEXT    NOT NULL,
    stat_type   TEXT    NOT NULL,
    source      TEXT    NOT NULL,
    old_value   REAL,
    new_value   REAL    NOT NULL,
    delta       REAL,
    recorded_at TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS news_context (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   TEXT    NOT NULL,
    stat_type   TEXT,
    summary     TEXT    NOT NULL,
    source_api  TEXT    NOT NULL DEFAULT 'gemini',
    trigger     TEXT,
    created_at  TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS watchlist (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    player_id   TEXT    NOT NULL,
    stat_type   TEXT    NOT NULL,
    note        TEXT,
    added_at    TEXT    NOT NULL,
    UNIQUE(player_id, stat_type)
);

CREATE TABLE IF NOT EXISTS smart_picks (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    sport        TEXT NOT NULL,
    player_name  TEXT NOT NULL,
    team         TEXT,
    opponent     TEXT,
    stat_type    TEXT NOT NULL,
    prediction   TEXT NOT NULL,
    pp_line      REAL NOT NULL,
    odds_type    TEXT NOT NULL,
    probability  REAL NOT NULL,
    edge         REAL NOT NULL,
    tier         TEXT NOT NULL,
    game_date    TEXT NOT NULL,
    ev_4leg      REAL,
    refreshed_at TEXT NOT NULL,
    UNIQUE(sport, player_name, stat_type, pp_line, odds_type, game_date)
);

CREATE INDEX IF NOT EXISTS idx_smart_sport_date ON smart_picks (sport, game_date, tier);

CREATE TABLE IF NOT EXISTS kalshi_tickers (
    ticker      TEXT    NOT NULL,
    cached_at   TEXT    NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_lines_sport     ON current_lines (sport);
CREATE INDEX IF NOT EXISTS idx_lines_volatile  ON current_lines (is_volatile);
CREATE INDEX IF NOT EXISTS idx_history_player  ON line_history  (player_id, stat_type, recorded_at);
CREATE INDEX IF NOT EXISTS idx_context_player  ON news_context  (player_id, created_at DESC);
"#;

// ── Pool init ────────────────────────────────────────────────────────────────

pub async fn init_pool(db_path: &str) -> Result<SqlitePool> {
    let url = format!("sqlite://{}?mode=rwc", db_path);

    let pool = SqlitePoolOptions::new()
        .max_connections(4)
        .connect(&url)
        .await?;

    sqlx::raw_sql(SCHEMA).execute(&pool).await?;

    tracing::info!("props.db ready at {}", db_path);
    Ok(pool)
}

// ── Upsert ───────────────────────────────────────────────────────────────────

/// Upsert one unified prop into `current_lines`.
/// Detects value changes and writes `line_history` rows automatically.
pub async fn upsert_prop(pool: &SqlitePool, prop: &UnifiedProp) -> Result<()> {
    let stat_db  = prop.stat_type.as_db_str();
    let sport_db = prop.sport.as_str();
    let now      = Utc::now().to_rfc3339();

    // ── 1. Read existing row ─────────────────────────────────────────────────
    let existing = sqlx::query(
        "SELECT prizepicks_line, underdog_line, kalshi_price
         FROM   current_lines
         WHERE  player_id = ? AND stat_type = ?"
    )
    .bind(&prop.player_id)
    .bind(&stat_db)
    .fetch_optional(pool)
    .await?;

    // ── 2. Detect delta and write history ────────────────────────────────────
    let (old_val, new_val): (Option<f64>, f64) = match prop.source {
        Source::PrizePicks => {
            let old = existing.as_ref()
                .and_then(|r| r.try_get::<Option<f64>, _>("prizepicks_line").ok().flatten());
            (old, prop.line)
        }
        Source::Underdog => {
            let old = existing.as_ref()
                .and_then(|r| r.try_get::<Option<f64>, _>("underdog_line").ok().flatten());
            (old, prop.line)
        }
        Source::Kalshi => {
            let old = existing.as_ref()
                .and_then(|r| r.try_get::<Option<f64>, _>("kalshi_price").ok().flatten());
            let price = prop.kalshi_price.unwrap_or(prop.line);
            (old, price)
        }
    };

    let has_changed = old_val.map_or(true, |o| (o - new_val).abs() > 0.001);
    if has_changed {
        let delta = old_val.map(|o| new_val - o);
        let src   = prop.source.as_str();

        sqlx::query(
            "INSERT INTO line_history
                (player_id, stat_type, source, old_value, new_value, delta, recorded_at)
             VALUES (?, ?, ?, ?, ?, ?, ?)"
        )
        .bind(&prop.player_id)
        .bind(&stat_db)
        .bind(src)
        .bind(old_val)
        .bind(new_val)
        .bind(delta)
        .bind(&now)
        .execute(pool)
        .await?;

        debug!(
            player = %prop.player_id,
            stat   = %stat_db,
            source = %src,
            old    = ?old_val,
            new    = new_val,
            "line change recorded"
        );
    }

    // ── 3. Upsert current_lines (source-specific column only) ────────────────
    match prop.source {
        Source::PrizePicks => {
            sqlx::query(
                "INSERT INTO current_lines
                     (player_id, name, team, opponent, sport, stat_type,
                      prizepicks_line, odds_type, last_updated)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(player_id, stat_type) DO UPDATE SET
                     name            = excluded.name,
                     team            = excluded.team,
                     opponent        = excluded.opponent,
                     prizepicks_line = excluded.prizepicks_line,
                     odds_type       = excluded.odds_type,
                     last_updated    = excluded.last_updated"
            )
            .bind(&prop.player_id)
            .bind(&prop.name)
            .bind(&prop.team)
            .bind(&prop.opponent)
            .bind(sport_db)
            .bind(&stat_db)
            .bind(prop.line)
            .bind(&prop.odds_type)
            .bind(&now)
            .execute(pool)
            .await?;
        }

        Source::Underdog => {
            sqlx::query(
                "INSERT INTO current_lines
                     (player_id, name, team, opponent, sport, stat_type,
                      underdog_line, last_updated)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(player_id, stat_type) DO UPDATE SET
                     name          = excluded.name,
                     team          = COALESCE(excluded.team,     current_lines.team),
                     opponent      = COALESCE(excluded.opponent, current_lines.opponent),
                     underdog_line = excluded.underdog_line,
                     last_updated  = excluded.last_updated"
            )
            .bind(&prop.player_id)
            .bind(&prop.name)
            .bind(&prop.team)
            .bind(&prop.opponent)
            .bind(sport_db)
            .bind(&stat_db)
            .bind(prop.line)
            .bind(&now)
            .execute(pool)
            .await?;
        }

        Source::Kalshi => {
            let price = prop.kalshi_price.unwrap_or(prop.line);
            sqlx::query(
                "INSERT INTO current_lines
                     (player_id, name, team, opponent, sport, stat_type,
                      kalshi_price, kalshi_market_id, last_updated)
                 VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                 ON CONFLICT(player_id, stat_type) DO UPDATE SET
                     name             = COALESCE(excluded.name, current_lines.name),
                     kalshi_price     = excluded.kalshi_price,
                     kalshi_market_id = excluded.kalshi_market_id,
                     last_updated     = excluded.last_updated"
            )
            .bind(&prop.player_id)
            .bind(&prop.name)
            .bind(&prop.team)
            .bind(&prop.opponent)
            .bind(sport_db)
            .bind(&stat_db)
            .bind(price)
            .bind(&prop.kalshi_market_id)
            .bind(&now)
            .execute(pool)
            .await?;
        }
    }

    // ── 4. Recompute discrepancy + volatility flag ───────────────────────────
    recompute_derived(pool, &prop.player_id, &stat_db).await?;

    Ok(())
}

/// Recompute `line_discrepancy` and `is_volatile` for one row.
async fn recompute_derived(pool: &SqlitePool, player_id: &str, stat_db: &str) -> Result<()> {
    sqlx::query(
        "UPDATE current_lines
         SET
             line_discrepancy = CASE
                 WHEN prizepicks_line IS NOT NULL AND underdog_line IS NOT NULL
                 THEN ABS(prizepicks_line - underdog_line)
                 ELSE NULL
             END,
             is_volatile = (
                 SELECT COUNT(*) >= 2
                 FROM   line_history h
                 WHERE  h.player_id = current_lines.player_id
                 AND    h.stat_type = current_lines.stat_type
                 AND    h.recorded_at >= datetime('now', '-15 minutes')
             )
         WHERE player_id = ? AND stat_type = ?"
    )
    .bind(player_id)
    .bind(stat_db)
    .execute(pool)
    .await?;

    Ok(())
}

// ── Kalshi ticker cache ───────────────────────────────────────────────────────

/// Return cached Kalshi market tickers if they were saved within `max_age_secs`.
/// Returns empty Vec if cache is stale or empty.
pub async fn load_cached_kalshi_tickers(pool: &SqlitePool, max_age_secs: i64) -> Vec<String> {
    let cutoff = (Utc::now() - chrono::Duration::seconds(max_age_secs))
        .to_rfc3339();

    let rows = sqlx::query(
        "SELECT ticker FROM kalshi_tickers WHERE cached_at >= ? ORDER BY ticker"
    )
    .bind(&cutoff)
    .fetch_all(pool)
    .await
    .unwrap_or_default();

    rows.iter()
        .filter_map(|r| r.try_get::<String, _>("ticker").ok())
        .collect()
}

/// Overwrite the Kalshi ticker cache with a fresh list.
pub async fn save_kalshi_tickers(pool: &SqlitePool, tickers: &[String]) -> Result<()> {
    let now = Utc::now().to_rfc3339();

    sqlx::query("DELETE FROM kalshi_tickers").execute(pool).await?;

    for ticker in tickers {
        sqlx::query("INSERT INTO kalshi_tickers (ticker, cached_at) VALUES (?, ?)")
            .bind(ticker)
            .bind(&now)
            .execute(pool)
            .await?;
    }

    tracing::info!("Kalshi ticker cache updated: {} tickers", tickers.len());
    Ok(())
}

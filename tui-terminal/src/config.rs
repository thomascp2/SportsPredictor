/// Runtime configuration loaded from environment variables.
///
/// Required env vars:
///   KALSHI_EMAIL          — Kalshi account email
///   KALSHI_PASSWORD       — Kalshi account password  (used for token exchange)
///   KALSHI_API_KEY        — Kalshi API key (alternative to email/password)
///
/// Optional env vars:
///   UNDERDOG_AUTH_TOKEN   — Bearer token for Underdog API
///   PROPS_DB_PATH         — Override default props.db location
///   RUST_LOG              — Tracing filter (default: "ingester=info")

#[derive(Debug, Clone)]
pub struct Config {
    /// Path to the local props.db SQLite file
    pub db_path: String,

    // ── Kalshi ───────────────────────────────────────────────────────────────
    /// Kalshi API key — used in the Authorization header
    pub kalshi_api_key: Option<String>,
    /// Sports market series to subscribe to (e.g. "NBA_POINTS_*", "NHL_*")
    /// Comma-separated list of ticker prefixes
    pub kalshi_series: Vec<String>,

    // ── Underdog ─────────────────────────────────────────────────────────────
    /// Underdog bearer token (optional — falls back to anonymous if absent)
    pub underdog_token: Option<String>,
    /// Poll interval in seconds (base — actual interval jitters ±20%)
    pub underdog_poll_secs: u64,

    // ── PrizePicks ───────────────────────────────────────────────────────────
    /// Poll interval in seconds (base)
    pub prizepicks_poll_secs: u64,
    /// League IDs to fetch: 7=NBA, 8=NHL, 2=MLB  (verified Apr 2026)
    pub prizepicks_leagues: Vec<u32>,
}

impl Config {
    pub fn from_env() -> anyhow::Result<Self> {
        // Load .env from tui-terminal/ directory if present
        let _ = dotenvy::from_filename(
            std::path::Path::new(env!("CARGO_MANIFEST_DIR")).join(".env"),
        );

        let db_path = std::env::var("PROPS_DB_PATH")
            .unwrap_or_else(|_| {
                // Default: place props.db next to the binary's manifest dir
                std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                    .join("props.db")
                    .to_string_lossy()
                    .to_string()
            });

        let kalshi_api_key = std::env::var("KALSHI_API_KEY").ok();

        let kalshi_series = std::env::var("KALSHI_SERIES")
            // NBA: pts/ast/reb/3pt (off-season but ready). NHL: KXNHLGOAL confirmed live Apr 2026.
            // MLB: hit/hrr/tb/ks/hr confirmed live Apr 2026.
            .unwrap_or_else(|_| "KXNBAPTS,KXNBAAST,KXNBAREB,KXNBA3PT,KXNHLGOAL,KXMLBHIT,KXMLBHRR,KXMLBTB,KXMLBKS,KXMLBHR".to_string())
            .split(',')
            .map(|s| s.trim().to_string())
            .collect();

        let underdog_token = std::env::var("UNDERDOG_AUTH_TOKEN").ok();
        let underdog_poll_secs = std::env::var("UNDERDOG_POLL_SECS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(90);

        let prizepicks_poll_secs = std::env::var("PRIZEPICKS_POLL_SECS")
            .ok()
            .and_then(|v| v.parse().ok())
            .unwrap_or(120);

        let prizepicks_leagues = std::env::var("PRIZEPICKS_LEAGUES")
            .unwrap_or_else(|_| "7,8,2".to_string()) // NBA=7, NHL=8, MLB=2
            .split(',')
            .filter_map(|s| s.trim().parse::<u32>().ok())
            .collect();

        Ok(Config {
            db_path,
            kalshi_api_key,
            kalshi_series,
            underdog_token,
            underdog_poll_secs,
            prizepicks_poll_secs,
            prizepicks_leagues,
        })
    }
}

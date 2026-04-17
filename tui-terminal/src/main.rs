/// props-ingester — headless sidecar for the TUI terminal.
///
/// Spawns three concurrent async tasks:
///   1. PrizePicks REST poller  (jittered ~30s interval, ETag-gated)
///   2. Underdog REST poller    (jittered ~30s interval, ETag-gated)
///   3. Kalshi WebSocket client (persistent, exponential backoff reconnect)
///
/// All tasks write normalized lines to tui-terminal/props.db via sqlx.
/// The Python Textual TUI reads that same file at 1-second intervals.

mod config;
mod db;
mod kalshi;
mod prizepicks;
mod types;
mod underdog;

use anyhow::Result;
use tracing::info;

#[tokio::main]
async fn main() -> Result<()> {
    // ── Logging ──────────────────────────────────────────────────────────────
    tracing_subscriber::fmt()
        .with_env_filter(
            std::env::var("RUST_LOG")
                .unwrap_or_else(|_| "ingester=info,props_ingester=info".to_string()),
        )
        .with_target(false)
        .compact()
        .init();

    info!("props-ingester starting up");

    // ── Config ───────────────────────────────────────────────────────────────
    let cfg = config::Config::from_env()?;
    info!("DB path: {}", cfg.db_path);

    // ── Database init ────────────────────────────────────────────────────────
    let pool = db::init_pool(&cfg.db_path).await?;

    // ── Spawn tasks ──────────────────────────────────────────────────────────
    let mut handles = Vec::new();

    // 1. PrizePicks poller
    {
        let pool_pp  = pool.clone();
        let leagues  = cfg.prizepicks_leagues.clone();
        let secs     = cfg.prizepicks_poll_secs;
        handles.push(tokio::spawn(async move {
            if let Err(e) = prizepicks::run_poller(pool_pp, leagues, secs).await {
                tracing::error!("PrizePicks poller crashed: {:#}", e);
            }
        }));
    }
    info!("PrizePicks poller task spawned");

    // 2. Underdog poller
    {
        let pool_ud = pool.clone();
        let token   = cfg.underdog_token.clone();
        let secs    = cfg.underdog_poll_secs;
        handles.push(tokio::spawn(async move {
            if let Err(e) = underdog::run_poller(pool_ud, token, secs).await {
                tracing::error!("Underdog poller crashed: {:#}", e);
            }
        }));
    }
    info!("Underdog poller task spawned");

    // 3. Kalshi WebSocket client (only if API key is set)
    if let Some(api_key) = cfg.kalshi_api_key.clone() {
        let pool_k = pool.clone();
        let series = cfg.kalshi_series.clone();
        handles.push(tokio::spawn(async move {
            if let Err(e) = kalshi::run_ws_client(pool_k, api_key, series).await {
                tracing::error!("Kalshi WS client crashed: {:#}", e);
            }
        }));
        info!("Kalshi WS task spawned");
    } else {
        tracing::warn!(
            "KALSHI_API_KEY not set — Kalshi task disabled. \
             Set KALSHI_API_KEY in tui-terminal/.env to enable."
        );
    }

    info!(
        "All tasks running. Writing to props.db at {}",
        cfg.db_path
    );
    info!("Press Ctrl-C to stop.");

    // ── Wait for all tasks ───────────────────────────────────────────────────
    // In production all three tasks run forever (they have internal reconnect
    // loops). If any crashes after exhausting retries this will join the rest.
    for handle in handles {
        if let Err(e) = handle.await {
            tracing::error!("Task panicked: {:?}", e);
        }
    }

    Ok(())
}

/// Kalshi V2 WebSocket client.
///
/// Connects to wss://api.elections.kalshi.com/trade-api/ws/v2
/// Subscribes to the orderbook channel for sports markets (KX* series).
///
/// Protocol:
///   1. HTTP POST /trade-api/v2/log_in  → receives a token
///   2. Open WS, send {"id":1,"cmd":"subscribe","params":{"channels":["orderbook_delta"],"market_tickers":[...]}}
///   3. Receive snapshot then delta updates
///   4. On disconnect: exponential backoff reconnect
///
/// NOTE: KX* prediction markets live on api.elections.kalshi.com — NOT trading-api.kalshi.com
/// (trading-api is Kalshi's financial derivatives exchange; KX sports are prediction markets).
///
/// We only care about the best-bid price (implied probability of OVER).

use anyhow::{Context, Result};
use chrono::Utc;
use futures_util::{SinkExt, StreamExt};
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use sqlx::SqlitePool;
use std::time::Duration;
use tokio::time::sleep;
use tokio_tungstenite::{
    connect_async, tungstenite::Message, MaybeTlsStream, WebSocketStream,
};
use tracing::{debug, error, info, warn};

use crate::db::{upsert_prop, load_cached_kalshi_tickers, save_kalshi_tickers};
use crate::types::{Source, Sport, StatType, UnifiedProp};

// ── Auth ──────────────────────────────────────────────────────────────────────

const LOGIN_URL: &str = "https://api.elections.kalshi.com/trade-api/v2/log_in";
const WS_URL:    &str = "wss://api.elections.kalshi.com/trade-api/ws/v2";

#[derive(Debug, Serialize)]
struct KalshiLoginReq {
    email:    String,
    password: String,
}

#[derive(Debug, Deserialize)]
struct KalshiLoginResp {
    token: String,
}

async fn get_token(client: &Client, api_key: &str) -> Result<String> {
    // Kalshi V2 supports a direct API key via Authorization: Token <key>
    // If the caller passes a raw API key (starts with "tok_") we use it directly.
    // Otherwise fall back to email/password exchange.
    if api_key.starts_with("tok_") || api_key.len() > 32 {
        return Ok(api_key.to_string());
    }

    // api_key used as a shorthand for "email:password" separated by ':'
    let mut parts = api_key.splitn(2, ':');
    let email    = parts.next().unwrap_or("").to_string();
    let password = parts.next().unwrap_or("").to_string();

    let resp: KalshiLoginResp = client
        .post(LOGIN_URL)
        .json(&KalshiLoginReq { email, password })
        .send()
        .await
        .context("Kalshi login request failed")?
        .json()
        .await
        .context("Kalshi login response parse failed")?;

    Ok(resp.token)
}

// ── Market discovery ──────────────────────────────────────────────────────────

const MARKETS_URL: &str = "https://api.elections.kalshi.com/trade-api/v2/markets";

#[derive(Debug, Deserialize)]
struct KalshiMarketsResp {
    markets: Vec<KalshiMarket>,
    #[serde(default)]
    cursor:  Option<String>,
}

#[derive(Debug, Deserialize)]
struct KalshiMarket {
    ticker:          String,
    title:           String,
    status:          String,
    #[serde(default)]
    yes_bid:         Option<i64>,   // cents
    #[serde(default)]
    yes_ask:         Option<i64>,
    #[serde(default)]
    series_ticker:   Option<String>,
}

/// Fetch all open markets matching our series prefixes, return tickers.
async fn discover_markets(
    client:  &Client,
    token:   &str,
    series:  &[String],
) -> Result<Vec<String>> {
    let mut tickers = Vec::new();

    for prefix in series {
        // Pause between series — Kalshi markets API has tight rate limits
        sleep(Duration::from_secs(2)).await;

        let mut cursor: Option<String> = None;

        loop {
            // Kalshi series_ticker is the uppercase series prefix (e.g. KXNHLGOAL)
            let mut url = format!(
                "{}?status=open&series_ticker={}&limit=100",
                MARKETS_URL, prefix
            );
            if let Some(c) = &cursor {
                url.push_str(&format!("&cursor={}", c));
            }

            let http_resp = client
                .get(&url)
                .header("Authorization", format!("Token {}", token))
                .send()
                .await
                .context("Kalshi markets list failed")?;

            let status = http_resp.status();
            if !status.is_success() {
                let body = http_resp.text().await.unwrap_or_default();
                anyhow::bail!(
                    "Kalshi markets API returned HTTP {}: {:.300}",
                    status,
                    body
                );
            }

            let resp: KalshiMarketsResp = http_resp
                .json()
                .await
                .context("Kalshi markets parse failed")?;

            for m in &resp.markets {
                if m.status == "open" {
                    tickers.push(m.ticker.clone());
                }
            }

            match resp.cursor {
                Some(c) if !c.is_empty() => cursor = Some(c),
                _ => break,
            }
        }
    }

    info!("Kalshi discovered {} open markets", tickers.len());
    Ok(tickers)
}

// ── WS message shapes ─────────────────────────────────────────────────────────

/// Kalshi WS orderbook_delta / orderbook_snapshot message.
/// We only need the best-bid (yes_bid) to compute implied probability.
#[derive(Debug, Deserialize)]
struct KalshiWsEnvelope {
    #[serde(rename = "type")]
    msg_type: String,
    msg:      Value,
}

// ── Main task ─────────────────────────────────────────────────────────────────

pub async fn run_ws_client(
    pool:      SqlitePool,
    api_key:   String,
    series:    Vec<String>,
) -> Result<()> {
    let http = Client::builder()
        .timeout(Duration::from_secs(15))
        .build()?;

    let mut backoff_secs: u64 = 2;

    loop {
        match run_ws_session(&http, &pool, &api_key, &series).await {
            Ok(()) => {
                // Clean disconnect — reconnect immediately
                warn!("Kalshi WS disconnected cleanly, reconnecting...");
                backoff_secs = 2;
            }
            Err(e) => {
                let err_str = format!("{:#}", e);
                error!("Kalshi WS error: {}", err_str);
                // Rate-limited: back off 10 min — don't hammer the markets discovery endpoint
                let wait = if err_str.contains("429") {
                    backoff_secs = 2; // reset so next non-429 error starts fresh
                    info!("Kalshi rate limited — waiting 600s before retry");
                    600
                } else {
                    let w = backoff_secs;
                    backoff_secs = (backoff_secs * 2).min(120);
                    info!("Kalshi reconnect in {}s", w);
                    w
                };
                sleep(Duration::from_secs(wait)).await;
            }
        }
    }
}

async fn run_ws_session(
    http:    &Client,
    pool:    &SqlitePool,
    api_key: &str,
    series:  &[String],
) -> Result<()> {
    // Auth
    let token = get_token(http, api_key).await?;

    // ── Market ticker cache (4-hour TTL) ─────────────────────────────────────
    // Check for a fresh cached list before hitting the REST markets endpoint.
    // This prevents rate-limit spirals when the WS reconnects frequently.
    const CACHE_TTL_SECS: i64 = 4 * 3600; // 4 hours
    let cached = load_cached_kalshi_tickers(pool, CACHE_TTL_SECS).await;

    let tickers = if !cached.is_empty() {
        info!("Kalshi using {} cached market tickers (skipping REST discovery)", cached.len());
        cached
    } else {
        info!("Kalshi cache empty/stale — running market discovery");
        let found = discover_markets(http, &token, series).await?;
        if found.is_empty() {
            warn!("Kalshi: no open markets found for series {:?}", series);
            sleep(Duration::from_secs(600)).await;
            return Ok(());
        }
        // Persist so reconnects skip discovery
        let _ = save_kalshi_tickers(pool, &found).await;
        found
    };

    // Connect WS — pass the URL string directly so Rust can infer the stream type
    let ws_url = format!("{}?token={}", WS_URL, token);
    let (mut ws_stream, _): (WebSocketStream<MaybeTlsStream<tokio::net::TcpStream>>, _) =
        connect_async(ws_url.as_str()).await.context("Kalshi WS connect")?;
    info!("Kalshi WS connected");

    // Subscribe in batches of 100 (Kalshi limit)
    for chunk in tickers.chunks(100) {
        let sub = json!({
            "id":  1,
            "cmd": "subscribe",
            "params": {
                "channels": ["orderbook_delta"],
                "market_tickers": chunk
            }
        });
        ws_stream.send(Message::Text(sub.to_string())).await?;
    }

    // Process messages
    while let Some(raw) = ws_stream.next().await {
        match raw {
            Err(e) => return Err(anyhow::anyhow!("WS recv error: {}", e)),

            Ok(Message::Ping(p)) => {
                ws_stream.send(Message::Pong(p)).await?;
            }

            Ok(Message::Text(text)) => {
                if let Err(e) = handle_ws_message(pool, &text).await {
                    debug!("WS message handle error: {:#}", e);
                }
            }

            Ok(Message::Close(_)) => {
                warn!("Kalshi WS close frame received");
                return Ok(());
            }

            _ => {}
        }
    }

    Ok(())
}

// ── Message parsing ───────────────────────────────────────────────────────────

async fn handle_ws_message(pool: &SqlitePool, text: &str) -> Result<()> {
    let envelope: KalshiWsEnvelope = serde_json::from_str(text)
        .context("Kalshi WS JSON parse")?;

    match envelope.msg_type.as_str() {
        "orderbook_snapshot" | "orderbook_delta" => {
            parse_and_upsert(pool, &envelope.msg).await?;
        }
        "subscribed" => {
            debug!("Kalshi subscribed ack");
        }
        other => {
            debug!("Kalshi unhandled msg type: {}", other);
        }
    }

    Ok(())
}

/// Extract ticker + yes_bid from an orderbook message and upsert.
///
/// Kalshi market ticker format (sports props):
///   KXNBAPLAYER-JOKIC-25-OVER   → Jokic over 25 points NBA
///   KXNHLPLAYER-MCDAVID-0-OVER  → McDavid over 0.5 points NHL (0 = 0.5)
///
/// yes_bid in cents (0-99) maps directly to implied probability.
async fn parse_and_upsert(pool: &SqlitePool, msg: &Value) -> Result<()> {
    let ticker = msg
        .get("market_ticker")
        .or_else(|| msg.get("ticker"))
        .and_then(|v| v.as_str())
        .context("no ticker in Kalshi msg")?;

    // yes_bid is the best bid on the "Yes" (OVER) contract in cents
    let yes_bid = msg
        .get("yes_bid")
        .and_then(|v| v.as_i64())
        .or_else(|| {
            // Delta messages may nest it differently
            msg.get("bids")
                .and_then(|b| b.as_array())
                .and_then(|arr| arr.first())
                .and_then(|first| first.get("price"))
                .and_then(|p| p.as_i64())
        });

    let Some(bid_cents) = yes_bid else {
        return Ok(()); // Some messages are metadata only
    };

    let implied_prob = bid_cents as f64 / 100.0;

    // Parse ticker into player info
    let Some((player_name, sport, stat_type, line)) = parse_kalshi_ticker(ticker) else {
        debug!("Kalshi ticker not parseable: {}", ticker);
        return Ok(());
    };

    let player_id = UnifiedProp::make_player_id(&player_name, &sport);
    let now       = Utc::now().to_rfc3339();

    let prop = UnifiedProp {
        player_id,
        name:            player_name,
        team:            None,
        opponent:        None,
        sport,
        stat_type,
        line,
        kalshi_price:    Some(implied_prob),
        kalshi_market_id: Some(ticker.to_string()),
        odds_type:       None,
        source:          Source::Kalshi,
        fetched_at:      now,
    };

    upsert_prop(pool, &prop).await?;
    Ok(())
}

// ── Ticker parsing ────────────────────────────────────────────────────────────

/// Parse a Kalshi sports ticker into (player_name, sport, stat_type, line).
///
/// Example formats:
///   KXNBAPLAYER-JOKICNIKOLA-25-OVER   → Jokic Nikola, NBA points, 25.5
///   KXNHLJR-MCDAVIDCONOR-0-OVER       → McDavid Conor, NHL points, 0.5
///   KXNBAPTS-CURRYSTEPHEN-22-OVER     → Curry Stephen, NBA points, 22.5
///
/// The exact format varies by series. This is a best-effort parser;
/// unknown formats are silently dropped.
fn parse_kalshi_ticker(ticker: &str) -> Option<(String, Sport, StatType, f64)> {
    let parts: Vec<&str> = ticker.split('-').collect();
    if parts.len() < 3 {
        return None;
    }

    let series = parts[0];

    // Map confirmed Kalshi series prefixes to (sport, stat_type).
    // Series names from WS tickers are uppercase; config stores them uppercase too.
    let (sport, base_stat) = match series {
        // NBA (off-season — markets will be empty but parser stays ready)
        "KXNBAPTS"  => (Sport::Nba, StatType::NbaPoints),
        "KXNBAAST"  => (Sport::Nba, StatType::NbaAssists),
        "KXNBAREB"  => (Sport::Nba, StatType::NbaRebounds),
        "KXNBA3PT"  => (Sport::Nba, StatType::NbaThrees),
        // NHL
        "KXNHLGOAL" => (Sport::Nhl, StatType::NhlGoals),
        // MLB
        "KXMLBHIT"  => (Sport::Mlb, StatType::MlbHits),
        "KXMLBHRR"  => (Sport::Mlb, StatType::MlbHrr),
        "KXMLBTB"   => (Sport::Mlb, StatType::MlbTotalBases),
        "KXMLBKS"   => (Sport::Mlb, StatType::MlbStrikeouts),
        "KXMLBHR"   => (Sport::Mlb, StatType::MlbHomeRuns),
        // Unknown / future series
        _           => return None,
    };

    // Player slug is second segment: "JOKICNIKOLA" or "JOKIC"
    let raw_player = parts[1];

    // Convert slug to display name: "JOKICNIKOLA" → "Jokic Nikola"
    // (best-effort — names with proper splits aren't available in ticker)
    let player_name = slug_to_name(raw_player);

    // Line value: Kalshi uses integers; 25 → 25.5 for most stats
    // (They typically set the line at N, meaning "over N" which is effectively N+0.5)
    let line_raw: f64 = parts.get(parts.len() - 2)
        .and_then(|s| s.parse().ok())
        .unwrap_or(0.0);
    let line = if line_raw == 0.0 { 0.5 } else { line_raw + 0.5 };

    Some((player_name, sport, base_stat, line))
}

/// Convert an all-caps slug like "JOKICNIKOLA" to "Jokic Nikola".
/// This is approximate — we capitalize the first letter and lowercase the rest,
/// treating the slug as one name. Full name resolution happens in ml_bridge.py.
fn slug_to_name(slug: &str) -> String {
    let lower = slug.to_lowercase();
    let mut chars = lower.chars();
    match chars.next() {
        None    => String::new(),
        Some(c) => c.to_uppercase().collect::<String>() + chars.as_str(),
    }
}

// ── Tests ─────────────────────────────────────────────────────────────────────

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_ticker_parse() {
        let result = parse_kalshi_ticker("KXNBAPLAYER-JOKICNIKOLA-25-OVER");
        assert!(result.is_some());
        let (name, sport, _, line) = result.unwrap();
        assert_eq!(sport, Sport::Nba);
        assert!((line - 25.5).abs() < 0.01);
    }

    #[test]
    fn test_zero_line() {
        let result = parse_kalshi_ticker("KXNHLPLAYER-MCDAVID-0-OVER");
        assert!(result.is_some());
        let (_, _, _, line) = result.unwrap();
        assert!((line - 0.5).abs() < 0.01);
    }
}

/// Underdog Fantasy REST poller.
///
/// Endpoint: GET https://api.underdogfantasy.com/v1/over_under_lines
///
/// Underdog uses a flat JSON response with an "over_under_lines" array
/// plus an "appearances" array that contains player + team + sport info.
/// We join on appearance_id.
///
/// Uses ETag / If-None-Match to avoid re-parsing unchanged responses.

use anyhow::{Context, Result};
use chrono::Utc;
use rand::Rng;
use reqwest::{header, Client};
use serde::{Deserialize, Deserializer};
use serde_json::Value;
use sqlx::SqlitePool;
use std::collections::HashMap;
use std::time::Duration;
use tokio::time::sleep;
use tracing::{info, warn};

use crate::db::upsert_prop;
use crate::types::{Source, Sport, StatType, UnifiedProp};

// ── Flexible ID deserializer ──────────────────────────────────────────────────
// Underdog API returns IDs as strings in some versions and integers in others.
// This visitor accepts either and converts to String.

fn deserialize_id<'de, D>(deserializer: D) -> Result<String, D::Error>
where
    D: Deserializer<'de>,
{
    use serde::de::{self, Visitor};
    struct IdVisitor;

    impl<'de> Visitor<'de> for IdVisitor {
        type Value = String;

        fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            f.write_str("string or integer ID")
        }

        fn visit_str<E: de::Error>(self, v: &str) -> Result<String, E> {
            Ok(v.to_string())
        }
        fn visit_string<E: de::Error>(self, v: String) -> Result<String, E> {
            Ok(v)
        }
        fn visit_i64<E: de::Error>(self, v: i64) -> Result<String, E> {
            Ok(v.to_string())
        }
        fn visit_u64<E: de::Error>(self, v: u64) -> Result<String, E> {
            Ok(v.to_string())
        }
    }

    deserializer.deserialize_any(IdVisitor)
}

// ── Optional flexible ID ──────────────────────────────────────────────────────
// match_id can be null, a string, or an integer — handle all three.

fn deserialize_f64_or_string<'de, D>(deserializer: D) -> Result<f64, D::Error>
where
    D: Deserializer<'de>,
{
    use serde::de::{self, Visitor};
    struct NumVisitor;

    impl<'de> Visitor<'de> for NumVisitor {
        type Value = f64;

        fn expecting(&self, f: &mut std::fmt::Formatter) -> std::fmt::Result {
            f.write_str("f64 or numeric string")
        }

        fn visit_f64<E: de::Error>(self, v: f64) -> Result<f64, E> { Ok(v) }
        fn visit_i64<E: de::Error>(self, v: i64) -> Result<f64, E> { Ok(v as f64) }
        fn visit_u64<E: de::Error>(self, v: u64) -> Result<f64, E> { Ok(v as f64) }
        fn visit_str<E: de::Error>(self, v: &str) -> Result<f64, E> {
            v.parse::<f64>().map_err(de::Error::custom)
        }
        fn visit_string<E: de::Error>(self, v: String) -> Result<f64, E> {
            v.parse::<f64>().map_err(de::Error::custom)
        }
    }

    deserializer.deserialize_any(NumVisitor)
}

fn deserialize_optional_id<'de, D>(deserializer: D) -> Result<Option<String>, D::Error>
where
    D: Deserializer<'de>,
{
    let v = Option::<Value>::deserialize(deserializer)?;
    Ok(v.and_then(|val| match val {
        Value::String(s) => Some(s),
        Value::Number(n) => Some(n.to_string()),
        _ => None,
    }))
}

// ── API response shapes ───────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct UdResponse {
    over_under_lines: Vec<serde_json::Value>,
    appearances:      Vec<UdAppearance>,
    // players maps player UUID → display name
    #[serde(default)]
    players:          Vec<UdPlayer>,
    #[serde(default)]
    positions:        Vec<UdPosition>,
    #[serde(default)]
    sports:           Vec<serde_json::Value>,
}

/// Player record — maps UUID player_id to a display name.
#[derive(Debug, Deserialize)]
struct UdPlayer {
    #[serde(deserialize_with = "deserialize_id")]
    id:   String,
    #[serde(default)]
    name: String,
}

#[derive(Debug, Deserialize)]
struct UdAppearance {
    #[serde(deserialize_with = "deserialize_id")]
    id:           String,
    #[serde(deserialize_with = "deserialize_id")]
    player_id:    String,
    // sport_id removed from UD API — now comes from position lookup
    #[serde(default)]
    sport_id:     String,
    #[serde(default, deserialize_with = "deserialize_optional_id")]
    match_id:     Option<String>,
    #[serde(default, deserialize_with = "deserialize_optional_id")]
    position_id:  Option<String>,
    #[serde(default, deserialize_with = "deserialize_optional_id")]
    team_id:      Option<String>,
}

/// Position entry — maps position_id → sport_id (e.g. "NBA", "NHL")
#[derive(Debug, Deserialize)]
struct UdPosition {
    #[serde(deserialize_with = "deserialize_id")]
    id:       String,
    #[serde(default)]
    sport_id: String,
    #[serde(default)]
    name:     String,
}

// ── Poller ────────────────────────────────────────────────────────────────────

pub async fn run_poller(
    pool:       SqlitePool,
    auth_token: Option<String>,
    base_secs:  u64,
) -> Result<()> {
    let mut headers = header::HeaderMap::new();

    // Underdog expects a consistent user-agent
    headers.insert(
        header::USER_AGENT,
        header::HeaderValue::from_static(
            "UnderdogFantasy/3.0 (iPhone; iOS 17.0; Scale/3.00)",
        ),
    );
    headers.insert(header::ACCEPT, header::HeaderValue::from_static("application/json"));

    if let Some(token) = &auth_token {
        let bearer = format!("Bearer {}", token);
        if let Ok(val) = header::HeaderValue::from_str(&bearer) {
            headers.insert(header::AUTHORIZATION, val);
        }
    }

    let client = Client::builder()
        .default_headers(headers)
        .timeout(Duration::from_secs(15))
        .build()?;

    let mut etag: Option<String> = None;

    info!("Underdog poller started");

    loop {
        match fetch_lines(&client, &pool, &mut etag).await {
            Ok(count) => {
                if count > 0 {
                    info!("UD fetched {} lines", count);
                }
            }
            Err(e) => {
                warn!("UD fetch error: {:#}", e);
            }
        }

        let jitter = rand::thread_rng().gen_range(0.80..=1.20);
        let secs = (base_secs as f64 * jitter) as u64;
        sleep(Duration::from_secs(secs)).await;
    }
}

async fn fetch_lines(
    client: &Client,
    pool:   &SqlitePool,
    etag:   &mut Option<String>,
) -> Result<usize> {
    const URL: &str = "https://api.underdogfantasy.com/v1/over_under_lines";

    let mut req = client.get(URL);

    if let Some(e) = etag.as_deref() {
        req = req.header(header::IF_NONE_MATCH, e);
    }

    let resp = req.send().await.context("UD request failed")?;

    if resp.status() == reqwest::StatusCode::NOT_MODIFIED {
        return Ok(0);
    }

    if !resp.status().is_success() {
        anyhow::bail!("UD API returned {}", resp.status());
    }

    if let Some(ev) = resp.headers().get(header::ETAG) {
        if let Ok(s) = ev.to_str() {
            *etag = Some(s.to_string());
        }
    }

    let raw = resp.text().await.context("UD read body")?;
    let body: UdResponse = serde_json::from_str(&raw).map_err(|e| {
        // Show first 800 chars of raw response to diagnose API drift
        warn!("UD parse error: {}  |  raw[:800]: {:.800}", e, raw);
        anyhow::anyhow!("UD JSON parse failed: {}", e)
    })?;

    // Build appearance map: id → UdAppearance
    // player UUID → display name
    let player_names: HashMap<&str, &str> = body
        .players
        .iter()
        .filter(|p| !p.name.is_empty())
        .map(|p| (p.id.as_str(), p.name.as_str()))
        .collect();

    // appearance id → UdAppearance
    let appearances: HashMap<&str, &UdAppearance> = body
        .appearances
        .iter()
        .map(|a| (a.id.as_str(), a))
        .collect();

    let now   = Utc::now().to_rfc3339();
    let mut count = 0usize;

    for line_val in &body.over_under_lines {
        // ── All stat/player info now lives inside over_under.appearance_stat ──
        let appearance_stat = &line_val["over_under"]["appearance_stat"];

        // ── Extract appearance_id ──────────────────────────────────────────
        let appearance_id = match &appearance_stat["appearance_id"] {
            serde_json::Value::String(s) => s.clone(),
            serde_json::Value::Number(n) => n.to_string(),
            _ => continue,
        };

        let Some(appearance) = appearances.get(appearance_id.as_str()) else {
            continue;
        };

        // ── Extract stat name ──────────────────────────────────────────────
        let stat = appearance_stat["stat"].as_str().unwrap_or("").to_string();
        if stat.is_empty() {
            continue;
        }

        // ── Extract stat_value (f64 or quoted string) ──────────────────────
        let stat_value = match &line_val["stat_value"] {
            serde_json::Value::Number(n) => match n.as_f64() {
                Some(f) => f,
                None    => continue,
            },
            serde_json::Value::String(s) => match s.parse::<f64>() {
                Ok(f)  => f,
                Err(_) => continue,
            },
            _ => continue,
        };

        // ── Infer sport + stat type from stat name alone ──────────────────
        // UD removed sport_id from the API (positions array is empty).
        // Stat names are sport-distinct so we derive both from the raw stat.
        let (sport, stat_type) = StatType::infer_from_ud(&stat);

        if matches!(sport, Sport::Unknown) {
            continue;
        }

        // Resolve display name from players array; skip if not found (no UUID fallback)
        let name = match player_names.get(appearance.player_id.as_str()) {
            Some(n) => n.to_string(),
            None    => continue,
        };
        let player_id = UnifiedProp::make_player_id(&name, &sport);

        let prop = UnifiedProp {
            player_id,
            name,
            team:            None,
            opponent:        None,
            sport,
            stat_type,
            line:            stat_value,
            kalshi_price:    None,
            kalshi_market_id: None,
            odds_type:       None,
            source:          Source::Underdog,
            fetched_at:      now.clone(),
        };

        upsert_prop(pool, &prop).await?;
        count += 1;
    }

    Ok(count)
}

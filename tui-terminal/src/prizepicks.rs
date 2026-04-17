/// PrizePicks REST poller.
///
/// Endpoint: GET https://api.prizepicks.com/projections?league_id={id}&per_page=250
///
/// Uses ETag / If-None-Match to skip re-parsing unchanged responses.
/// Polls on a jittered interval (base ± 20%).

use anyhow::{Context, Result};
use chrono::Utc;
use rand::Rng;
use reqwest::{header, Client};
use serde::Deserialize;
use sqlx::SqlitePool;
use std::collections::HashMap;
use std::time::Duration;
use tokio::time::sleep;
use tracing::{info, warn};

use crate::db::upsert_prop;
use crate::types::{Source, Sport, StatType, UnifiedProp};

// ── API response shapes ───────────────────────────────────────────────────────

#[derive(Debug, Deserialize)]
struct PpResponse {
    #[serde(default)]
    data:     Vec<PpProjection>,
    // PP occasionally returns responses without `included` (e.g. empty slates, rate-limit
    // partial responses). Default to empty so the parse doesn't fail.
    #[serde(default)]
    included: Vec<PpIncluded>,
}

#[derive(Debug, Deserialize)]
struct PpProjection {
    id:            String,
    attributes:    PpProjectionAttrs,
    relationships: PpRelationships,
}

#[derive(Debug, Deserialize)]
struct PpProjectionAttrs {
    stat_type:    String,
    line_score:   f64,
    #[serde(default)]
    odds_type:    Option<String>,   // "standard", "goblin", "demon"
    #[serde(default)]
    start_time:   Option<String>,
}

#[derive(Debug, Deserialize)]
struct PpRelationships {
    new_player: PpRelRef,
}

#[derive(Debug, Deserialize)]
struct PpRelRef {
    data: PpIdRef,
}

#[derive(Debug, Deserialize)]
struct PpIdRef {
    id:    String,
    #[serde(rename = "type")]
    rtype: String,
}

/// The "included" array contains both player and team records.
#[derive(Debug, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
#[allow(dead_code)]
enum PpIncluded {
    NewPlayer(PpPlayerRecord),
    #[serde(other)]
    Other,
}

#[derive(Debug, Deserialize)]
struct PpPlayerRecord {
    id:         String,
    attributes: PpPlayerAttrs,
}

#[derive(Debug, Deserialize)]
struct PpPlayerAttrs {
    name:              String,
    #[serde(default)]
    team:              Option<String>,
    #[serde(default)]
    position:          Option<String>,
}

// ── League → Sport mapping ────────────────────────────────────────────────────

fn league_to_sport(league_id: u32) -> Sport {
    match league_id {
        7 => Sport::Nba,
        8 => Sport::Nhl,
        2 => Sport::Mlb,
        _ => Sport::Unknown,
    }
}

// ── Poller ────────────────────────────────────────────────────────────────────

pub async fn run_poller(
    pool:        SqlitePool,
    league_ids:  Vec<u32>,
    base_secs:   u64,
) -> Result<()> {
    let client = Client::builder()
        .user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        .timeout(Duration::from_secs(15))
        .build()?;

    // ETag cache per league
    let mut etags: HashMap<u32, String> = HashMap::new();

    info!("PrizePicks poller started — leagues: {:?}", league_ids);

    loop {
        for &league_id in &league_ids {
            match fetch_league(&client, &pool, league_id, &mut etags).await {
                Ok(count) => {
                    if count > 0 {
                        info!("PP league={} fetched {} projections", league_id, count);
                    }
                }
                Err(e) => {
                    warn!("PP league={} fetch error: {:#}", league_id, e);
                }
            }
            // Stagger league requests to avoid PP rate limiting
            sleep(Duration::from_millis(800)).await;
        }

        // Jittered sleep: base ± 20%
        let jitter = rand::thread_rng().gen_range(0.80..=1.20);
        let secs = (base_secs as f64 * jitter) as u64;
        sleep(Duration::from_secs(secs)).await;
    }
}

async fn fetch_league(
    client:    &Client,
    pool:      &SqlitePool,
    league_id: u32,
    etags:     &mut HashMap<u32, String>,
) -> Result<usize> {
    let url = format!(
        "https://api.prizepicks.com/projections?league_id={}&per_page=250&single_stat=true",
        league_id
    );

    let mut req = client
        .get(&url)
        .header(header::ACCEPT, "application/json")
        .header(header::ACCEPT_ENCODING, "gzip, deflate");

    // Conditional GET — skip if server says Not Modified
    if let Some(etag) = etags.get(&league_id) {
        req = req.header(header::IF_NONE_MATCH, etag.clone());
    }

    let resp = req.send().await.context("PP request failed")?;

    // 304 Not Modified — nothing changed
    if resp.status() == reqwest::StatusCode::NOT_MODIFIED {
        return Ok(0);
    }

    if !resp.status().is_success() {
        anyhow::bail!("PP API returned {}", resp.status());
    }

    // Cache the ETag for next round
    if let Some(etag_val) = resp.headers().get(header::ETAG) {
        if let Ok(s) = etag_val.to_str() {
            etags.insert(league_id, s.to_string());
        }
    }

    let body: PpResponse = resp.json().await.context("PP JSON parse failed")?;

    // Build player lookup from included
    let players = build_player_map(&body.included);

    let sport = league_to_sport(league_id);
    let now   = Utc::now().to_rfc3339();
    let mut count = 0usize;

    for proj in &body.data {
        let player_ref_id = &proj.relationships.new_player.data.id;
        let Some(player)  = players.get(player_ref_id.as_str()) else {
            continue;
        };

        let name      = player.attributes.name.clone();
        let team      = player.attributes.team.clone();
        let stat_type = StatType::from_prizepicks(&sport, &proj.attributes.stat_type);

        // Skip unknown stat types we don't track
        if matches!(stat_type, StatType::Unknown(_)) {
            continue;
        }

        let player_id = UnifiedProp::make_player_id(&name, &sport);

        let prop = UnifiedProp {
            player_id,
            name,
            team,
            opponent:        None, // PP projections don't include opponent in this endpoint
            sport:           sport.clone(),
            stat_type,
            line:            proj.attributes.line_score,
            kalshi_price:    None,
            kalshi_market_id: None,
            odds_type:       proj.attributes.odds_type.clone(),
            source:          Source::PrizePicks,
            fetched_at:      now.clone(),
        };

        upsert_prop(pool, &prop).await?;
        count += 1;
    }

    Ok(count)
}

/// Build a map of player_id → PpPlayerRecord from the "included" array.
fn build_player_map<'a>(included: &'a [PpIncluded]) -> HashMap<&'a str, &'a PpPlayerRecord> {
    let mut map = HashMap::new();
    for item in included {
        if let PpIncluded::NewPlayer(p) = item {
            map.insert(p.id.as_str(), p);
        }
    }
    map
}

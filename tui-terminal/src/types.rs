/// Normalized representation of a prop line from any source.
///
/// All three APIs (PrizePicks, Underdog, Kalshi) are mapped into this
/// struct before writing to props.db.  Fields that a source doesn't
/// provide are left as `None`.

use serde::{Deserialize, Serialize};

// ── Sport / Prop enums ───────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum Sport {
    Nba,
    Nhl,
    Mlb,
    Unknown,
}

impl Sport {
    pub fn as_str(&self) -> &'static str {
        match self {
            Sport::Nba => "NBA",
            Sport::Nhl => "NHL",
            Sport::Mlb => "MLB",
            Sport::Unknown => "UNKNOWN",
        }
    }

    pub fn from_str(s: &str) -> Self {
        match s.to_uppercase().as_str() {
            "NBA" => Sport::Nba,
            "NHL" => Sport::Nhl,
            "MLB" => Sport::Mlb,
            _ => Sport::Unknown,
        }
    }
}

/// Canonical stat types — normalized across all sources.
#[derive(Debug, Clone, PartialEq, Eq, Hash, Serialize, Deserialize)]
pub enum StatType {
    // NBA
    NbaPoints,
    NbaRebounds,
    NbaAssists,
    NbaThrees,
    NbaSteals,
    NbaBlocks,
    NbaTurnovers,
    NbaFantasy,
    NbaPra,             // Points + Rebounds + Assists
    // NHL
    NhlPoints,
    NhlShots,
    NhlGoals,
    NhlAssists,
    NhlHits,
    NhlBlockedShots,
    // MLB — pitcher props
    MlbStrikeouts,      // pitcher Ks
    MlbOutsRecorded,
    MlbPitcherWalks,
    MlbHitsAllowed,
    MlbEarnedRuns,
    // MLB — batter props
    MlbHits,            // base hits
    MlbTotalBases,
    MlbHomeRuns,
    MlbRbis,
    MlbRuns,
    MlbStolenBases,
    MlbBatterWalks,
    MlbBatterStrikeouts,
    MlbHrr,             // Hits + Runs + RBIs
    // Fallback
    Unknown(String),
}

impl StatType {
    /// Canonical DB string used in `current_lines.stat_type`
    pub fn as_db_str(&self) -> String {
        match self {
            StatType::NbaPoints          => "NBA_POINTS".to_string(),
            StatType::NbaRebounds        => "NBA_REBOUNDS".to_string(),
            StatType::NbaAssists         => "NBA_ASSISTS".to_string(),
            StatType::NbaThrees          => "NBA_THREES".to_string(),
            StatType::NbaSteals          => "NBA_STEALS".to_string(),
            StatType::NbaBlocks          => "NBA_BLOCKS".to_string(),
            StatType::NbaTurnovers       => "NBA_TURNOVERS".to_string(),
            StatType::NbaFantasy         => "NBA_FANTASY".to_string(),
            StatType::NbaPra             => "NBA_PRA".to_string(),
            StatType::NhlPoints          => "NHL_POINTS".to_string(),
            StatType::NhlShots           => "NHL_SHOTS".to_string(),
            StatType::NhlGoals           => "NHL_GOALS".to_string(),
            StatType::NhlAssists         => "NHL_ASSISTS".to_string(),
            StatType::NhlHits            => "NHL_HITS".to_string(),
            StatType::NhlBlockedShots    => "NHL_BLOCKED_SHOTS".to_string(),
            StatType::MlbStrikeouts      => "MLB_STRIKEOUTS".to_string(),
            StatType::MlbOutsRecorded    => "MLB_OUTS_RECORDED".to_string(),
            StatType::MlbPitcherWalks    => "MLB_PITCHER_WALKS".to_string(),
            StatType::MlbHitsAllowed     => "MLB_HITS_ALLOWED".to_string(),
            StatType::MlbEarnedRuns      => "MLB_EARNED_RUNS".to_string(),
            StatType::MlbHits            => "MLB_HITS".to_string(),
            StatType::MlbTotalBases      => "MLB_TOTAL_BASES".to_string(),
            StatType::MlbHomeRuns        => "MLB_HOME_RUNS".to_string(),
            StatType::MlbRbis            => "MLB_RBIS".to_string(),
            StatType::MlbRuns            => "MLB_RUNS".to_string(),
            StatType::MlbStolenBases     => "MLB_STOLEN_BASES".to_string(),
            StatType::MlbBatterWalks     => "MLB_BATTER_WALKS".to_string(),
            StatType::MlbBatterStrikeouts => "MLB_BATTER_STRIKEOUTS".to_string(),
            StatType::MlbHrr             => "MLB_HRR".to_string(),
            StatType::Unknown(s)         => format!("UNKNOWN_{}", s.to_uppercase()),
        }
    }

    /// Map PrizePicks stat_type strings to canonical type.
    /// Sport context is required to resolve ambiguous stat names
    /// (e.g. "hits" means NHL body-checks for NHL but base-hits for MLB).
    pub fn from_prizepicks(sport: &Sport, raw: &str) -> Self {
        let s = raw.to_lowercase();
        match sport {
            Sport::Nba => match s.as_str() {
                "points"                          => StatType::NbaPoints,
                "rebounds"                        => StatType::NbaRebounds,
                "assists"                         => StatType::NbaAssists,
                "3-pt made" | "3 pointers made" | "3-pointers made"
                                                  => StatType::NbaThrees,
                "steals"                          => StatType::NbaSteals,
                "blocks"                          => StatType::NbaBlocks,
                "turnovers"                       => StatType::NbaTurnovers,
                "fantasy score"                   => StatType::NbaFantasy,
                "pts+reb+ast" | "pra"             => StatType::NbaPra,
                other                             => StatType::Unknown(other.to_string()),
            },
            Sport::Nhl => match s.as_str() {
                "points"                          => StatType::NhlPoints,
                "shots on goal" | "shots"         => StatType::NhlShots,
                "goals"                           => StatType::NhlGoals,
                "assists" | "hockey assists" | "assists (hockey)"
                                                  => StatType::NhlAssists,
                "hits"                            => StatType::NhlHits,
                "blocked shots"                   => StatType::NhlBlockedShots,
                other                             => StatType::Unknown(other.to_string()),
            },
            Sport::Mlb => match s.as_str() {
                // Pitcher props
                "strikeouts" | "pitcher strikeouts"  => StatType::MlbStrikeouts,
                "outs recorded"                      => StatType::MlbOutsRecorded,
                "pitcher walks" | "walks allowed"    => StatType::MlbPitcherWalks,
                "hits allowed"                       => StatType::MlbHitsAllowed,
                "earned runs" | "earned runs allowed" => StatType::MlbEarnedRuns,
                // Batter props
                "hits" | "batter hits"               => StatType::MlbHits,
                "total bases"                        => StatType::MlbTotalBases,
                "home runs"                          => StatType::MlbHomeRuns,
                "rbis" | "runs batted in"            => StatType::MlbRbis,
                "runs" | "runs scored"               => StatType::MlbRuns,
                "stolen bases"                       => StatType::MlbStolenBases,
                "walks"                              => StatType::MlbBatterWalks,
                "batter strikeouts" | "hitter strikeouts"
                                                     => StatType::MlbBatterStrikeouts,
                "hrr"                                => StatType::MlbHrr,
                other                                => StatType::Unknown(other.to_string()),
            },
            Sport::Unknown => StatType::Unknown(s),
        }
    }

    /// Infer (Sport, StatType) from Underdog stat name alone.
    /// UD no longer provides sport_id in the API — sport must be derived
    /// from the stat string since UD uses sport-distinct stat names.
    pub fn infer_from_ud(raw: &str) -> (Sport, Self) {
        match raw.to_lowercase().as_str() {
            // NBA
            "points"                              => (Sport::Nba, StatType::NbaPoints),
            "rebounds"                            => (Sport::Nba, StatType::NbaRebounds),
            "assists"                             => (Sport::Nba, StatType::NbaAssists),
            "3-pointers" | "three pointers"       => (Sport::Nba, StatType::NbaThrees),
            "steals"                              => (Sport::Nba, StatType::NbaSteals),
            "blocks"                              => (Sport::Nba, StatType::NbaBlocks),
            "turnovers"                           => (Sport::Nba, StatType::NbaTurnovers),
            "fantasy_score" | "fantasy score"     => (Sport::Nba, StatType::NbaFantasy),
            "pts_rebs_asts" | "pra"               => (Sport::Nba, StatType::NbaPra),
            // NHL — UD uses "hockey assists" to distinguish from NBA
            "shots on goal" | "shots"             => (Sport::Nhl, StatType::NhlShots),
            "goals"                               => (Sport::Nhl, StatType::NhlGoals),
            "hockey assists" | "assists (hockey)" => (Sport::Nhl, StatType::NhlAssists),
            "hits"                                => (Sport::Nhl, StatType::NhlHits),
            "blocked shots"                       => (Sport::Nhl, StatType::NhlBlockedShots),
            // MLB — pitcher props (sport-distinct names)
            "pitcher strikeouts"                  => (Sport::Mlb, StatType::MlbStrikeouts),
            "outs recorded"                       => (Sport::Mlb, StatType::MlbOutsRecorded),
            "pitcher walks" | "walks allowed"     => (Sport::Mlb, StatType::MlbPitcherWalks),
            "hits allowed"                        => (Sport::Mlb, StatType::MlbHitsAllowed),
            "earned runs" | "earned runs allowed" => (Sport::Mlb, StatType::MlbEarnedRuns),
            // MLB — batter props
            "batter hits"                         => (Sport::Mlb, StatType::MlbHits),
            "home runs"                           => (Sport::Mlb, StatType::MlbHomeRuns),
            "total bases"                         => (Sport::Mlb, StatType::MlbTotalBases),
            "rbis" | "runs batted in"             => (Sport::Mlb, StatType::MlbRbis),
            "runs scored"                         => (Sport::Mlb, StatType::MlbRuns),
            "stolen bases"                        => (Sport::Mlb, StatType::MlbStolenBases),
            "batter strikeouts" | "hitter strikeouts"
                                                  => (Sport::Mlb, StatType::MlbBatterStrikeouts),
            "hrr"                                 => (Sport::Mlb, StatType::MlbHrr),
            // Note: "hits" alone is ambiguous (NHL body-checks vs MLB base-hits).
            // UD uses "batter hits" for MLB and "hits" for NHL — so plain "hits" → NHL.
            // "strikeouts" alone kept as NHL/NBA unknown (UD uses "pitcher strikeouts" for MLB).
            // Golf, football, and anything else — skip
            other                                 => (Sport::Unknown, StatType::Unknown(other.to_string())),
        }
    }
}

// ── Source ───────────────────────────────────────────────────────────────────

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum Source {
    PrizePicks,
    Underdog,
    Kalshi,
}

impl Source {
    pub fn as_str(&self) -> &'static str {
        match self {
            Source::PrizePicks => "prizepicks",
            Source::Underdog   => "underdog",
            Source::Kalshi     => "kalshi",
        }
    }
}

// ── Core unified struct ──────────────────────────────────────────────────────

/// Normalized prop line from any source.
/// Written to `current_lines` via DB upserts; deltas go to `line_history`.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct UnifiedProp {
    /// Stable key across all sources: "{last}_{first}_{sport}" lowercased
    /// e.g. "jokic_nikola_nba"
    pub player_id: String,

    /// Display name as given by the source
    pub name: String,

    pub team: Option<String>,
    pub opponent: Option<String>,
    pub sport: Sport,
    pub stat_type: StatType,

    /// The numeric line (e.g. 25.5 points)
    pub line: f64,

    /// Kalshi-only: implied probability in [0,1] (price in cents / 100)
    /// None for PrizePicks and Underdog
    pub kalshi_price: Option<f64>,

    /// Kalshi market ticker (e.g. "KXNBAPLAYER-JOKIC-25-OVER")
    pub kalshi_market_id: Option<String>,

    /// PrizePicks odds type: "standard", "goblin", "demon" (None for UD/Kalshi)
    pub odds_type: Option<String>,

    pub source: Source,

    /// ISO 8601 timestamp when this record was fetched
    pub fetched_at: String,
}

impl UnifiedProp {
    /// Build a stable player_id from name + sport.
    /// Strips diacritics and punctuation for cross-source matching.
    pub fn make_player_id(name: &str, sport: &Sport) -> String {
        let normalized = name
            .to_lowercase()
            .replace(['.', '\'', '-'], "")
            .split_whitespace()
            .collect::<Vec<_>>()
            .join("_");
        format!("{}_{}", normalized, sport.as_str().to_lowercase())
    }
}

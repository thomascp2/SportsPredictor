"""
Canonical Feature Schema
========================

Single source of truth for feature names and outcome column names across
both NHL and NBA prediction pipelines.

All prediction scripts write features_json using these canonical f_ names.
The ML training pipeline reads features_json using these names directly —
no sport-specific mapping needed.

History
-------
- Pre-canonicalization (NHL ≤ Nov 2025): NHL used un-prefixed keys like
  'success_rate_l5', 'sog_l10', 'avg_toi_minutes'.  NBA used 'f_' prefix.
- Canonicalized (Dec 2025+): Both sports use f_ prefix keys below.

Backfill
--------
Run `python shared/migrate_features_schema.py` to rewrite old features_json
blobs in NHL predictions to the canonical key names.
"""

# ---------------------------------------------------------------------------
# Canonical feature key names (features_json)
# ---------------------------------------------------------------------------

# Binary classification features (points O/U, rebounds, assists, etc.)
BINARY_FEATURES = [
    'f_season_success_rate',    # % games over the line — full season
    'f_l20_success_rate',       # % games over — last 20
    'f_l10_success_rate',       # % games over — last 10
    'f_l5_success_rate',        # % games over — last 5
    'f_l3_success_rate',        # % games over — last 3
    'f_current_streak',         # consecutive overs (+) or unders (-)
    'f_max_streak',             # longest streak this season
    'f_recent_momentum',        # composite recent form score (NHL only)
    'f_trend_slope',            # linear trend of raw stat values
    'f_trend_acceleration',     # 2nd derivative of trend (NBA only)
    'f_home_away_split',        # home_avg - away_avg (sign adjusted for H/A)
    'f_games_played',           # sample size
    'f_insufficient_data',      # 1 if < MIN_GAMES_REQUIRED
    'f_is_home',                # 1 = home, 0 = away
    'f_line',                   # the specific O/U line being predicted
]

# Continuous/regression features (shots, PRA, minutes)
CONTINUOUS_FEATURES = [
    'f_season_avg',             # season-long average of the stat
    'f_l10_avg',                # last-10 average
    'f_l5_avg',                 # last-5 average
    'f_season_std',             # season std deviation
    'f_l10_std',                # last-10 std deviation
    'f_trend_slope',            # linear trend slope
    'f_trend_acceleration',     # 2nd derivative of trend
    'f_avg_minutes',            # average playing time (minutes or TOI)
    'f_consistency_score',      # inverse of CV: 1/(1+std/mean)
    'f_home_away_split',        # home vs away performance difference
    'f_games_played',           # sample size
    'f_is_home',                # 1 = home, 0 = away
    'f_line',                   # the specific O/U line being predicted
    'f_expected_value',         # model's expected stat (mu / lambda)
    'f_std_dev',                # std used in normal CDF
    'f_z_score',                # z-score of line vs expected value
    'f_prob_over',              # raw P(over) before direction correction
]

# Minutes trend features (NBA binary extractor — cross-signal suppressor)
MINUTES_TREND_FEATURES = [
    'f_minutes_season_avg',     # season avg minutes (alias of f_avg_minutes)
    'f_minutes_l5_avg',         # last-5 avg minutes
    'f_minutes_l3_avg',         # last-3 avg minutes
    'f_minutes_trending_down',  # 1.0 if L5 < season * 0.88 (load management flag)
    'f_minutes_pct_of_season',  # L5_avg / season_avg (1.0 = no change)
]

# Opponent defensive features
OPPONENT_FEATURES = [
    'f_opp_allowed_l10',            # opp's avg stat allowed over last 10 games
    'f_opp_allowed_l5',             # opp's avg stat allowed over last 5 games
    'f_opp_std',                    # std of opp's stat allowed
    'f_opp_defensive_trend',        # slope of opp's defensive rating trend
    'f_opp_defensive_consistency',  # consistency of opp's defense (NHL shots)
    'f_opp_scoring_pct_allowed',    # % of games opp allows the stat (NHL points)
]

# Rest / schedule features (both sports)
REST_FEATURES = [
    'f_days_rest',        # days since player's last game (0 = B2B)
    'f_opp_days_rest',    # days since opponent's last game
]

# All features combined
ALL_FEATURES = (
    BINARY_FEATURES
    + CONTINUOUS_FEATURES
    + MINUTES_TREND_FEATURES
    + OPPONENT_FEATURES
    + REST_FEATURES
)

# ---------------------------------------------------------------------------
# Outcome table column mapping
# Both sports write to a prediction_outcomes table but with different column
# names for historical reasons.  Use these mappings when reading outcomes
# for cross-sport analysis or ML training.
# ---------------------------------------------------------------------------

# Column that holds the AI's predicted direction ('OVER' or 'UNDER')
OUTCOME_PREDICTION_COL = {
    'nba': 'prediction',          # NBA: matches predictions.prediction
    'nhl': 'predicted_outcome',   # NHL: legacy name
}

# Column that holds the actual observed stat value (float)
OUTCOME_ACTUAL_VALUE_COL = {
    'nba': 'actual_value',
    'nhl': 'actual_stat_value',   # NHL: legacy name
}

# Column that holds the hit/miss result ('HIT' or 'MISS')
OUTCOME_RESULT_COL = {
    'nba': 'outcome',
    'nhl': 'outcome',   # same in both — no mapping needed
}


# ---------------------------------------------------------------------------
# Legacy key → canonical key mapping for NHL backfill migration
# ---------------------------------------------------------------------------

NHL_POINTS_LEGACY_TO_CANONICAL = {
    'success_rate_season':    'f_season_success_rate',
    'success_rate_l20':       'f_l20_success_rate',
    'success_rate_l10':       'f_l10_success_rate',
    'success_rate_l5':        'f_l5_success_rate',
    'success_rate_l3':        'f_l3_success_rate',
    'current_streak':         'f_current_streak',
    'max_hot_streak':         'f_max_streak',
    'recent_momentum':        'f_recent_momentum',
    'games_played':           'f_games_played',
    'is_home':                'f_is_home',
    'line':                   'f_line',
    'lambda_param':           'f_lambda_param',
    'poisson_prob':           'f_prob_over',
    'prob_over':              'f_prob_over',
    'opp_points_allowed_l10': 'f_opp_allowed_l10',
    'opp_points_allowed_l5':  'f_opp_allowed_l5',
    'opp_scoring_pct_allowed':'f_opp_scoring_pct_allowed',
    'opp_points_std':         'f_opp_std',
    'opp_defensive_trend':    'f_opp_defensive_trend',
}

NHL_SHOTS_LEGACY_TO_CANONICAL = {
    'sog_season':              'f_season_avg',
    'sog_l10':                 'f_l10_avg',
    'sog_l5':                  'f_l5_avg',
    'sog_std_season':          'f_season_std',
    'sog_std_l10':             'f_l10_std',
    'sog_trend':               'f_trend_slope',
    'avg_toi_minutes':         'f_avg_minutes',
    'games_played':            'f_games_played',
    'is_home':                 'f_is_home',
    'line':                    'f_line',
    'mean_shots':              'f_expected_value',
    'std_dev':                 'f_std_dev',
    'z_score':                 'f_z_score',
    'prob_over':               'f_prob_over',
    'opp_shots_allowed_l10':   'f_opp_allowed_l10',
    'opp_shots_allowed_l5':    'f_opp_allowed_l5',
    'opp_shots_std':           'f_opp_std',
    'opp_shots_trend':         'f_opp_defensive_trend',
    'opp_defensive_consistency':'f_opp_defensive_consistency',
}

# Count props (hits, blocked_shots): keys were dynamic like 'hits_season'
# These are normalized using the prop_type prefix pattern below.
NHL_COUNT_PROP_LEGACY_PATTERN = {
    # '{prop}_season' → 'f_season_avg'
    # '{prop}_l10'    → 'f_l10_avg'
    # '{prop}_l5'     → 'f_l5_avg'
    # '{prop}_std_l10'→ 'f_l10_std'
    # '{prop}_trend'  → 'f_trend_slope'
    'avg_toi_minutes': 'f_avg_minutes',
    'games_played':    'f_games_played',
    'is_home':         'f_is_home',
    'line':            'f_line',
    'mean_val':        'f_expected_value',
    'mean_hits':       'f_expected_value',    # legacy alias
    'mean_blocked':    'f_expected_value',    # legacy alias
    'std_dev':         'f_std_dev',
    'z_score':         'f_z_score',
    'prob_over':       'f_prob_over',
}


def normalize_features_json(features: dict, sport: str, prop_type: str = '') -> dict:
    """
    Convert a legacy features_json dict to the canonical f_ key schema.

    Args:
        features:  Raw features_json dict as loaded from the DB.
        sport:     'nhl' or 'nba'.
        prop_type: NHL prop type ('points', 'shots', 'hits', 'blocked_shots').

    Returns:
        New dict with canonical key names.  Unknown keys are passed through
        unchanged so no data is silently dropped.
    """
    if sport == 'nba':
        # NBA already uses canonical keys
        return dict(features)

    # NHL — pick the right mapping
    if prop_type == 'points':
        mapping = NHL_POINTS_LEGACY_TO_CANONICAL
    elif prop_type == 'shots':
        mapping = NHL_SHOTS_LEGACY_TO_CANONICAL
    else:
        # hits / blocked_shots — handle dynamic prefix pattern
        mapping = dict(NHL_COUNT_PROP_LEGACY_PATTERN)
        prop_lower = prop_type.lower()
        for suffix, canonical in [
            ('_season', 'f_season_avg'),
            ('_l10',    'f_l10_avg'),
            ('_l5',     'f_l5_avg'),
            ('_std_l10','f_l10_std'),
            ('_trend',  'f_trend_slope'),
        ]:
            legacy_key = f'{prop_lower}{suffix}'
            mapping[legacy_key] = canonical

    normalized = {}
    for key, value in features.items():
        canonical_key = mapping.get(key, key)   # unknown keys pass through
        normalized[canonical_key] = value
    return normalized

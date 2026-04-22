"""
data_orchestrator/normalizer.py

Player name standardization — maps sportsbook names (from The Odds API)
to the exact names used by the statistical libraries (nba_api, pybaseball, NHL API).

Why this is hard:
  - Sportsbooks use "LeBron James"; nba_api also uses "LeBron James" — usually fine.
  - Sportsbooks may use "OG Anunoby"; nba_api uses "O.G. Anunoby".
  - Sportsbooks use "Marcus Morris"; nba_api uses "Marcus Morris Sr.".
  - NHL API returns abbreviated "C. Caufield" in box scores (roster lookup fixes this).
  - pybaseball uses "LeBron James"-style full names, usually matching sportsbooks.
  - Mid-season trades can introduce unknown team pairings.

Strategy (in order):
  1. Exact match (fast path, covers ~90% of cases)
  2. Hardcoded exceptions (known mismatches with no pattern)
  3. Fuzzy match with `thefuzz` token_sort_ratio (covers suffix/prefix noise)
  4. Last-name-only match (last resort — only accepted if unambiguous on that team)

Usage:
    from data_orchestrator.normalizer import NameNormalizer

    norm = NameNormalizer()
    norm.load_stats_names("NBA", stats_player_names)

    canonical = norm.standardize("O.G. Anunoby", "NBA")
    # -> "OG Anunoby"  (or whatever nba_api returns for him)
"""

from __future__ import annotations

import logging
from typing import Optional

from thefuzz import fuzz, process

from .config import NAME_MATCH_THRESHOLD

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hardcoded exceptions: {(sportsbook_name, sport): stats_name}
# Add entries here when fuzzy matching fails consistently.
# ---------------------------------------------------------------------------

_EXCEPTIONS: dict[tuple[str, str], str] = {
    ("O.G. Anunoby",       "NBA"): "OG Anunoby",
    ("OG Anunoby",         "NBA"): "OG Anunoby",
    ("Marcus Morris",      "NBA"): "Marcus Morris Sr.",
    ("Jaren Jackson",      "NBA"): "Jaren Jackson Jr.",
    ("Wendell Carter",     "NBA"): "Wendell Carter Jr.",
    ("Gary Trent",         "NBA"): "Gary Trent Jr.",
    ("Kelly Oubre",        "NBA"): "Kelly Oubre Jr.",
    ("Tim Hardaway",       "NBA"): "Tim Hardaway Jr.",
    ("Marvin Bagley",      "NBA"): "Marvin Bagley III",
    ("Larry Nance",        "NBA"): "Larry Nance Jr.",
    ("Kenyon Martin",      "NBA"): "Kenyon Martin Jr.",
    ("Jabari Smith",       "NBA"): "Jabari Smith Jr.",
    ("Amen Thompson",      "NBA"): "Amen Thompson",
    ("Ausar Thompson",     "NBA"): "Ausar Thompson",
    ("Patrick Beverley",   "NBA"): "Patrick Beverley",
    ("DJ Augustin",        "NBA"): "D.J. Augustin",
    ("CJ McCollum",        "NBA"): "CJ McCollum",
    ("PJ Tucker",          "NBA"): "P.J. Tucker",
    ("RJ Barrett",         "NBA"): "RJ Barrett",
    ("TJ McConnell",       "NBA"): "T.J. McConnell",
    ("Wander Franco",      "MLB"): "Wander Franco",
    ("Josh Jung",          "MLB"): "Josh Jung",
    ("Ha-Seong Kim",       "MLB"): "Ha-Seong Kim",
    ("Ji-Man Choi",        "MLB"): "Ji-Man Choi",
    ("Sean Murphy",        "MLB"): "Sean Murphy",
}


class NameNormalizer:
    """
    Bidirectional name mapper between sportsbook names and stats library names.

    Workflow:
      1. Call load_stats_names(sport, names) after fetching box score data.
      2. Call standardize(sportsbook_name, sport) for each odds row.
      3. Unmatched names are logged as warnings with context for manual review.
    """

    def __init__(self, threshold: int = NAME_MATCH_THRESHOLD):
        self.threshold = threshold
        self._canonical: dict[str, list[str]] = {}   # sport -> list of known canonical names
        self._cache: dict[tuple[str, str], Optional[str]] = {}   # (name, sport) -> match

    def load_stats_names(self, sport: str, names: list[str]):
        """
        Register the known player names from the stats library for a sport.
        Call this after fetching box scores so standardize() has something to match against.
        """
        self._canonical[sport.upper()] = list(names)
        logger.debug(f"[Norm] Loaded {len(names)} {sport} canonical names")

    def standardize(self, sportsbook_name: str, sport: str) -> Optional[str]:
        """
        Map a sportsbook player name to its canonical stats-library equivalent.

        Returns:
            Matched canonical name, or None if no match above threshold.
        """
        sport = sport.upper()
        key   = (sportsbook_name, sport)

        if key in self._cache:
            return self._cache[key]

        result = self._resolve(sportsbook_name, sport)
        self._cache[key] = result

        if result is None:
            logger.warning(
                f"[Norm] No match for '{sportsbook_name}' ({sport}) "
                f"— add to _EXCEPTIONS if this player should be included"
            )
        return result

    def standardize_dataframe(
        self,
        df_odds: pd.DataFrame,
        sport: str,
        name_col: str = "player_name",
    ) -> pd.DataFrame:
        """
        Add a 'canonical_name' column to an odds DataFrame.
        Rows with no match get canonical_name=None and can be filtered out.
        """
        df = df_odds.copy()
        df["canonical_name"] = df[name_col].map(
            lambda n: self.standardize(n, sport)
        )
        unmatched = df["canonical_name"].isna().sum()
        if unmatched:
            logger.warning(f"[Norm] {unmatched} unmatched player names in {sport} odds")
        return df

    def match_rate(self, sport: str) -> dict:
        """Report match stats for a sport — useful for monitoring."""
        sport_keys = [(n, s) for n, s in self._cache if s == sport.upper()]
        matched    = sum(1 for k in sport_keys if self._cache[k] is not None)
        total      = len(sport_keys)
        return {
            "sport":    sport.upper(),
            "total":    total,
            "matched":  matched,
            "rate_pct": round(matched / total * 100, 1) if total else 0.0,
        }

    # ------------------------------------------------------------------
    # Resolution logic
    # ------------------------------------------------------------------

    def _resolve(self, name: str, sport: str) -> Optional[str]:
        canonical_list = self._canonical.get(sport, [])

        # 1. Hardcoded exception
        exc = _EXCEPTIONS.get((name, sport))
        if exc:
            return exc

        # 2. Case-insensitive exact match
        name_lower = name.lower().strip()
        for c in canonical_list:
            if c.lower().strip() == name_lower:
                return c

        # 3. Fuzzy match — token_sort_ratio handles word reordering and suffixes
        if canonical_list:
            best = process.extractOne(name, canonical_list, scorer=fuzz.token_sort_ratio)
            if best is None:
                return None
            match, score = best[0], best[1]
            if score >= self.threshold:
                logger.debug(f"[Norm] Fuzzy: '{name}' -> '{match}' ({score})")
                return match

        # 4. Last-name fallback (only when unambiguous)
        last_name = name.strip().split()[-1].lower() if name.strip() else ""
        if len(last_name) > 3:
            candidates = [
                c for c in canonical_list
                if c.lower().split()[-1] == last_name
            ]
            if len(candidates) == 1:
                logger.debug(f"[Norm] Last-name match: '{name}' -> '{candidates[0]}'")
                return candidates[0]

        return None


# ---------------------------------------------------------------------------
# Module-level convenience function (for callers that don't hold a Normalizer)
# ---------------------------------------------------------------------------

try:
    import pandas as pd
    _PANDAS_OK = True
except ImportError:
    _PANDAS_OK = False


def merge_odds_with_stats(
    df_stats: "pd.DataFrame",
    df_odds: "pd.DataFrame",
    sport: str,
    normalizer: NameNormalizer = None,
) -> "pd.DataFrame":
    """
    Join stats and odds DataFrames on player name after normalization.

    Steps:
      1. Build a NameNormalizer from stats player names (or use provided one)
      2. Add 'canonical_name' to df_odds
      3. Left-join df_stats on player_name == canonical_name
      4. Return merged DataFrame

    Args:
        df_stats:    Output of fetch_nba/nhl/mlb_boxscores()
        df_odds:     Output of OddsClient.fetch_props()
        sport:       'NBA', 'NHL', or 'MLB'
        normalizer:  Optional pre-built NameNormalizer (reuse across calls)

    Returns:
        Merged DataFrame with both actual stats and prop lines.
        Players with no odds data retain their stats rows (left join).
    """
    if not _PANDAS_OK:
        raise ImportError("pandas is required for merge_odds_with_stats")

    if df_stats.empty:
        return df_stats

    norm = normalizer or NameNormalizer()
    norm.load_stats_names(sport, df_stats["player_name"].tolist())

    df_odds_norm = normalizer.standardize_dataframe(df_odds, sport) if normalizer \
        else norm.standardize_dataframe(df_odds, sport)

    # Drop unmatched odds rows
    df_odds_matched = df_odds_norm.dropna(subset=["canonical_name"]).copy()
    df_odds_matched = df_odds_matched.rename(columns={"player_name": "sb_player_name"})

    merged = df_stats.merge(
        df_odds_matched,
        left_on="player_name",
        right_on="canonical_name",
        how="left",
        suffixes=("", "_odds"),
    )

    return merged

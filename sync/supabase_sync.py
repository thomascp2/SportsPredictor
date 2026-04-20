#!/usr/bin/env python3
"""
Supabase Sync - Bridge SQLite predictions to Supabase cloud database
====================================================================

One-directional sync: SQLite (local) -> Supabase (cloud)
User data lives ONLY in Supabase. Prediction data flows from local to cloud.

Usage:
    python -m sync.supabase_sync --sport nba --operation predictions
    python -m sync.supabase_sync --sport nba --operation grading
    python -m sync.supabase_sync --sport all --operation all
"""

import os
import sys
import json
import sqlite3
import argparse
import unicodedata
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

# Add project root and gsd_module to path so shared.odds / shared.inference_utils resolve
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "gsd_module"))

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    print("WARNING: supabase-py not installed. Run: pip install supabase")

from sync.config import (
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
    NHL_DB_PATH, NBA_DB_PATH, MLB_DB_PATH, GOLF_DB_PATH, SYNC_BATCH_SIZE
)

# Correct break-even constants (fix for confirmed production bug: 0.56 was wrong)
# shared.odds and shared.inference_utils live in gsd_module/shared/ (added to sys.path above)
from shared.odds import BREAK_EVEN_MAP
from shared.inference_utils import tier_from_edge


class SupabaseSync:
    """Syncs local SQLite prediction data to Supabase."""

    def __init__(self):
        if not SUPABASE_AVAILABLE:
            raise RuntimeError("supabase-py not installed")
        if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must be set")

        self.client: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)
        self.db_paths = {
            'nhl': os.path.normpath(NHL_DB_PATH),
            'nba': os.path.normpath(NBA_DB_PATH),
            'mlb': os.path.normpath(MLB_DB_PATH),
            'golf': os.path.normpath(GOLF_DB_PATH),
        }

    def sync_predictions(self, sport: str, game_date: Optional[str] = None) -> Dict:
        """
        Sync today's predictions from SQLite to Supabase daily_props.

        Args:
            sport: 'nhl' or 'nba'
            game_date: Date to sync (default: today)

        Returns:
            Dict with sync results
        """
        if game_date is None:
            game_date = date.today().isoformat()

        sport_upper = sport.upper()

        # Golf has no Supabase presence (dashboard reads SQLite directly).
        # Skip to avoid column-mismatch errors (no team/opponent in golf predictions).
        if sport.lower() == 'golf':
            print(f"[SYNC] Skipping Supabase prediction sync for GOLF (SQLite-only sport)")
            return {'synced': 0, 'sport': 'GOLF', 'skipped': True}

        db_path = self.db_paths[sport.lower()]
        print(f"[SYNC] Syncing {sport_upper} predictions for {game_date}...")

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Query predictions - different schemas per sport
        if sport.lower() in ('nhl', 'mlb'):
            rows = conn.execute('''
                SELECT player_name, team, opponent, prop_type, line,
                       prediction, probability, features_json
                FROM predictions
                WHERE game_date = ?
            ''', (game_date,)).fetchall()
        else:
            # NBA has f_l10_avg, f_l10_std as columns
            rows = conn.execute('''
                SELECT player_name, team, opponent, prop_type, line,
                       prediction, probability,
                       f_l10_avg, f_l10_std, f_season_avg, f_season_std
                FROM predictions
                WHERE game_date = ?
            ''', (game_date,)).fetchall()

        conn.close()

        if not rows:
            print(f"[SYNC] No predictions found for {sport_upper} on {game_date}")
            return {'synced': 0, 'sport': sport_upper, 'date': game_date}

        # Build PP team lookup to correct stale teams for traded players.
        # prizepicks_lines.db is the authoritative current-roster source.
        pp_db = PROJECT_ROOT / 'shared' / 'prizepicks_lines.db'
        pp_team_lookup = {}  # normalized_name_lower -> pp_team
        try:
            pp_conn = sqlite3.connect(str(pp_db))
            pp_rows = pp_conn.execute('''
                SELECT DISTINCT player_name, team
                FROM prizepicks_lines
                WHERE substr(start_time, 1, 10) = ?
                  AND league = ?
            ''', [game_date, sport_upper]).fetchall()
            pp_conn.close()
            for pp_name, pp_team in pp_rows:
                pp_team_lookup[pp_name.lower().strip()] = pp_team
        except Exception as e:
            print(f"[SYNC] Warning: could not load PP teams for trade check: {e}")

        # Transform to Supabase format
        props = []
        _logged_trades = set()
        for row in rows:
            row_dict = dict(row)
            probability = row_dict.get('probability', 0.5)
            prediction_dir = row_dict.get('prediction', 'OVER')

            # Directional confidence: depends on how each sport stores probability.
            # NBA stores P(OVER) for every prediction regardless of direction,
            #   so UNDER confidence = 1 - P(OVER).
            # NHL and MLB store P(predicted direction), so confidence = probability as-is.
            if sport.lower() in ('nhl', 'mlb'):
                confidence = probability
            else:
                confidence = probability if prediction_dir == 'OVER' else (1.0 - probability)
            # Cap at 0.95 — no model is 100% certain. Prevents degenerate 1.0 values
            # (e.g. UNDER with P(OVER)=0) from flooding the dashboard as T1-ELITE.
            confidence = min(confidence, 0.95)

            # Calculate edge and tier based on directional confidence
            # Default to standard; sync_odds_types corrects goblin/demon later
            be = BREAK_EVEN_MAP.get('standard', BREAK_EVEN_MAP['standard'])
            edge = round((confidence - be) * 100, 2) if confidence else 0.0
            tier = tier_from_edge(edge)

            # Calculate EV values using directional confidence
            ev_2leg = (confidence ** 2) * 3.0 - 1 if confidence else 0
            ev_3leg = (confidence ** 3) * 5.0 - 1 if confidence else 0
            ev_4leg = (confidence ** 4) * 10.0 - 1 if confidence else 0

            # Correct stale team for traded players using PP as authoritative source
            local_team = row_dict.get('team', '')
            norm_name = self._normalize_name(row_dict['player_name']).lower()
            pp_team = pp_team_lookup.get(norm_name, '')
            if pp_team and local_team and pp_team.upper() != local_team.upper():
                if norm_name not in _logged_trades:
                    pname_ascii = row_dict['player_name'].encode('ascii', 'replace').decode('ascii')
                    print(f"[SYNC] Trade correction: {pname_ascii} {local_team} -> {pp_team}")
                    _logged_trades.add(norm_name)
                team = pp_team
            else:
                team = local_team

            prop = {
                'game_date': game_date,
                'sport': sport_upper,
                'player_name': self._normalize_name(row_dict['player_name']),
                'team': team,
                'opponent': row_dict.get('opponent', ''),
                'prop_type': row_dict['prop_type'],
                'line': row_dict['line'],
                'odds_type': 'standard',
                'ai_prediction': row_dict.get('prediction', ''),
                'ai_probability': round(confidence, 4),
                'ai_edge': round(edge, 2),
                'ai_tier': tier,
                'ai_ev_2leg': round(ev_2leg, 4),
                'ai_ev_3leg': round(ev_3leg, 4),
                'ai_ev_4leg': round(ev_4leg, 4),
                'status': 'open',
                'is_smart_pick': False,  # sync_smart_picks() sets True for selected picks
            }
            # Include rationale and l5_trend if present in local row
            # (Plan 02 migration adds these columns to Supabase; silently ignored until then)
            if row_dict.get('rationale'):
                prop['rationale'] = row_dict['rationale']
            if row_dict.get('l5_trend') is not None:
                prop['l5_trend'] = row_dict['l5_trend']
            props.append(prop)

        # Upsert in batches
        synced = 0
        errors = []
        for i in range(0, len(props), SYNC_BATCH_SIZE):
            batch = props[i:i + SYNC_BATCH_SIZE]
            try:
                self.client.table('daily_props').upsert(
                    batch,
                    on_conflict='game_date,player_name,prop_type,line'
                ).execute()
                synced += len(batch)
            except Exception as e:
                errors.append(f"Batch {i//SYNC_BATCH_SIZE}: {str(e)}")
                print(f"[SYNC ERROR] Batch failed: {e}")

        print(f"[SYNC] Synced {synced}/{len(props)} {sport_upper} predictions")

        return {
            'synced': synced,
            'total': len(props),
            'sport': sport_upper,
            'date': game_date,
            'errors': errors,
        }

    def sync_grading(self, sport: str, game_date: Optional[str] = None) -> Dict:
        """
        Sync grading results from SQLite to Supabase daily_props.
        Updates actual_value, result, and status fields.

        Args:
            sport: 'nhl' or 'nba'
            game_date: Date to sync (default: yesterday)
        """
        if game_date is None:
            game_date = (date.today() - timedelta(days=1)).isoformat()

        sport_upper = sport.upper()
        db_path = self.db_paths[sport.lower()]
        print(f"[SYNC] Syncing {sport_upper} grading for {game_date}...")

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        rows = conn.execute('''
            SELECT o.player_name, o.prop_type, o.line,
                   o.actual_value,
                   o.outcome, o.prediction as ai_prediction
            FROM prediction_outcomes o
            WHERE o.game_date = ?
        ''', (game_date,)).fetchall()

        conn.close()

        if not rows:
            print(f"[SYNC] No grading results found for {sport_upper} on {game_date}")
            return {'synced': 0, 'sport': sport_upper, 'date': game_date}

        # Update each prop in Supabase
        synced = 0
        for row in rows:
            row_dict = dict(row)
            try:
                self.client.table('daily_props').update({
                    'actual_value': row_dict['actual_value'],
                    'result': row_dict['outcome'],  # HIT or MISS
                    'status': 'graded',
                    'graded_at': datetime.now().isoformat(),
                }).eq('game_date', game_date).eq(
                    'player_name', self._normalize_name(row_dict['player_name'])
                ).eq('prop_type', row_dict['prop_type']).eq(
                    'line', row_dict['line']
                ).execute()
                synced += 1
            except Exception as e:
                pname_ascii = row_dict['player_name'].encode('ascii', 'replace').decode('ascii')
                print(f"[SYNC ERROR] {pname_ascii}: {e}")

        print(f"[SYNC] Synced {synced}/{len(rows)} {sport_upper} grading results")

        # Sync model performance summary
        self._sync_model_performance(sport, game_date, rows)

        return {
            'synced': synced,
            'total': len(rows),
            'sport': sport_upper,
            'date': game_date,
        }

    def sync_smart_picks(self, sport: str, game_date: Optional[str] = None) -> Dict:
        """
        Sync SmartPick data (PrizePicks-matched predictions with EV) to daily_props.
        Enriches existing rows with PP-specific odds_type and recalculated probabilities.
        """
        if game_date is None:
            game_date = date.today().isoformat()

        sport_upper = sport.upper()
        print(f"[SYNC] Syncing {sport_upper} smart picks for {game_date}...")

        try:
            sys.path.insert(0, str(PROJECT_ROOT / "shared"))
            from smart_pick_selector import SmartPickSelector
            selector = SmartPickSelector(sport)
            picks = selector.get_smart_picks(
                game_date=game_date,
                min_edge=0,       # Sync all picks, filtering done on client
                min_prob=0.50,
                refresh_lines=True
            )
        except Exception as e:
            print(f"[SYNC ERROR] SmartPick fetch failed: {e}")
            return {'synced': 0, 'error': str(e)}

        synced = 0
        for pick in picks:
            try:
                # Use local DB name (abbreviated) as the conflict key so we UPDATE the
                # existing prediction row rather than INSERT a new full-name duplicate.
                # e.g. local "S. Bennett" upserts into the row sync_predictions() wrote,
                # instead of creating a separate "Sam Bennett" row.
                canonical_name = self._normalize_name(
                    pick.local_player_name if pick.local_player_name else pick.player_name
                )
                self.client.table('daily_props').upsert({
                    'game_date': game_date,
                    'sport': sport_upper,
                    'player_name': canonical_name,
                    'team': pick.team,
                    'opponent': pick.opponent,
                    'prop_type': pick.prop_type,
                    'line': pick.pp_line,
                    'odds_type': pick.pp_odds_type,
                    'ai_prediction': pick.prediction,
                    'ai_probability': round(pick.pp_probability, 4),
                    'ai_edge': round(pick.edge, 2),
                    'ai_tier': pick.tier,
                    'ai_ev_2leg': round(pick.ev_2leg, 4),
                    'ai_ev_3leg': round(pick.ev_3leg, 4),
                    'ai_ev_4leg': round(pick.ev_4leg, 4),
                    'status': 'open',
                    'is_smart_pick': True,  # Passed suppression filters and edge >= 0
                }, on_conflict='game_date,player_name,prop_type,line').execute()
                synced += 1
            except Exception as e:
                pname_ascii = pick.player_name.encode('ascii', 'replace').decode('ascii')
                print(f"[SYNC ERROR] {pname_ascii}: {e}")

        print(f"[SYNC] Synced {synced}/{len(picks)} {sport_upper} smart picks")

        # Write is_smart_pick=1 and ai_tier back to the local SQLite predictions table.
        # This is required for MLB and Golf, which have no Supabase rows — the dashboard
        # reads SQLite directly for those sports. Also keeps NHL/NBA SQLite in sync.
        sqlite_updated = 0
        db_path = self.db_paths.get(sport.lower())
        if db_path and picks:
            try:
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                for pick in picks:
                    local_name = pick.local_player_name if pick.local_player_name else pick.player_name
                    c.execute(
                        "UPDATE predictions SET is_smart_pick=1, ai_tier=?, odds_type=? "
                        "WHERE game_date=? AND player_name=? AND prop_type=? AND line=?",
                        (pick.tier, pick.pp_odds_type, game_date, local_name, pick.prop_type, pick.pp_line),
                    )
                    sqlite_updated += c.rowcount
                conn.commit()
                conn.close()
                print(f"[SYNC] SQLite write-back: {sqlite_updated} prediction rows flagged is_smart_pick=1")
            except Exception as e:
                print(f"[SYNC WARN] SQLite write-back failed: {e}")

        return {'synced': synced, 'sqlite_updated': sqlite_updated, 'total': len(picks), 'sport': sport_upper}

    def sync_odds_types(self, sport: str, game_date: Optional[str] = None) -> Dict:
        """
        Update odds_type for all daily_props rows to match PrizePicks actual classification.

        Runs after sync_predictions() + sync_smart_picks() to catch any rows where
        smart_picks didn't fire (e.g. edge below break-even for goblin/demon lines).
        Uses direct PP DB lookup — no edge filtering, purely factual label correction.

        Examples fixed:
          - SGA steals 0.5 → goblin (edge just below break-even, skipped by smart_picks)
          - Hartenstein points 7.5 → goblin (same)
          - Any goblin line our model isn't confident enough on still gets labeled correctly
        """
        if game_date is None:
            game_date = date.today().isoformat()

        sport_upper = sport.upper()
        pp_db = PROJECT_ROOT / 'shared' / 'prizepicks_lines.db'
        print(f"[SYNC] Syncing {sport_upper} odds_type labels from PP for {game_date}...")

        if sport_upper == 'NHL':
            props = ('shots', 'points', 'goals', 'assists', 'pp_points',
                     'hits', 'blocked_shots')
        elif sport_upper == 'MLB':
            props = ('strikeouts', 'outs_recorded', 'pitcher_walks', 'hits_allowed',
                     'earned_runs', 'hits', 'total_bases', 'home_runs', 'rbis',
                     'runs', 'stolen_bases', 'walks', 'batter_strikeouts', 'hrr')
        else:
            props = ('points', 'rebounds', 'assists', 'threes', 'pra',
                     'pts_rebs', 'pts_asts', 'rebs_asts', 'steals',
                     'blocked_shots', 'turnovers', 'fantasy')

        placeholders = ','.join(['?' for _ in props])
        conn = sqlite3.connect(str(pp_db))
        pp_rows = conn.execute(f'''
            SELECT DISTINCT player_name, prop_type, line, odds_type
            FROM prizepicks_lines
            WHERE substr(start_time, 1, 10) = ?
              AND league = ?
              AND prop_type IN ({placeholders})
        ''', [game_date, sport_upper] + list(props)).fetchall()
        conn.close()

        # Build lookup: (normalized_name_lower, prop_type, line) -> odds_type
        pp_lookup = {}
        for name, prop, line, odds in pp_rows:
            key = (self._normalize_name(name).lower(), prop, line)
            pp_lookup[key] = odds

        # Fetch all prediction rows for today from Supabase (paginate past 1000-row limit)
        all_rows = self._fetch_all_sport_date(
            sport_upper, game_date,
            'id,player_name,prop_type,line,odds_type,ai_probability,ai_prediction,ai_edge'
        )

        patches = []
        for row in all_rows:
            norm = self._normalize_name(row['player_name']).lower()
            prop = row['prop_type']
            line = row['line']

            pp_odds = pp_lookup.get((norm, prop, line))

            # For NHL abbreviated names, try initial matching as fallback
            if pp_odds is None and sport_upper == 'NHL':
                for (pp_norm, pp_prop, pp_line), odds in pp_lookup.items():
                    if pp_prop != prop or pp_line != line:
                        continue
                    # Check if pp_norm (full) matches norm (abbreviated) or vice versa
                    if self._initial_match(pp_norm, norm) or self._initial_match(norm, pp_norm):
                        pp_odds = odds
                        break

            # Lock odds_type at first write — don't overwrite once set.
            # PP reprices standard → demon once games go live; we want the pregame label
            # locked in so ML training data reflects what was actually bettable pregame.
            current_odds_type = row.get('odds_type') or ''
            needs_odds_update = pp_odds is not None and not current_odds_type

            # Edge recalculation uses the locked odds_type (or PP value if not yet set)
            effective_type = current_odds_type or (pp_odds if pp_odds is not None else 'standard')
            needs_dir_fix = (effective_type in ('goblin', 'demon')
                             and row.get('ai_prediction') == 'UNDER')

            ai_prob = row.get('ai_probability')
            if ai_prob is not None and effective_type in BREAK_EVEN_MAP:
                expected_edge = round((ai_prob - BREAK_EVEN_MAP[effective_type]) * 100, 2)
                stored_edge = row.get('ai_edge')
                needs_edge_fix = (stored_edge is None or
                                  abs(stored_edge - expected_edge) > 0.05)
            else:
                needs_edge_fix = False
                expected_edge = row.get('ai_edge')

            if not needs_odds_update and not needs_dir_fix and not needs_edge_fix:
                continue

            new_odds_type = pp_odds if needs_odds_update else row['odds_type']
            new_ai_edge = expected_edge
            new_ai_tier = tier_from_edge(new_ai_edge) if new_ai_edge is not None else 'T5-FADE'
            patches.append({
                'id': row['id'],
                'player_name': row['player_name'],
                'odds_type': new_odds_type,
                'ai_edge': new_ai_edge,
                'ai_tier': new_ai_tier,
                'ai_prediction': 'OVER' if needs_dir_fix else row.get('ai_prediction'),
            })

        # Atomic update: odds_type + ai_edge + ai_tier in a single .update() call per row
        updated = 0
        for patch in patches:
            row_id = patch['id']
            fields = {
                'odds_type': patch['odds_type'],
                'ai_edge': patch['ai_edge'],
                'ai_tier': patch['ai_tier'],
                'ai_prediction': patch['ai_prediction'],
            }
            try:
                self.client.table('daily_props').update(fields).eq('id', row_id).execute()
                updated += 1
            except Exception as e:
                pname = patch.get('player_name', 'unknown')
                pname_ascii = pname.encode('ascii', 'replace').decode('ascii')
                print(f"[SYNC ERROR] odds_type {pname_ascii}: {e}")

        print(f"[SYNC] Corrected {updated} odds_type labels for {sport_upper} on {game_date}")
        return {'updated': updated, 'sport': sport_upper, 'date': game_date}

    def sync_game_times(self, sport: str, game_date: Optional[str] = None) -> Dict:
        """
        Populate game_time field in daily_props from PrizePicks start_time data.
        Stored as "7:10 PM ET" so the dashboard can show tip-off time per pick.
        Batch-updates by team (all players on same team share one start_time).
        """
        if game_date is None:
            game_date = date.today().isoformat()

        sport_upper = sport.upper()
        pp_db = PROJECT_ROOT / 'shared' / 'prizepicks_lines.db'
        print(f"[SYNC] Syncing {sport_upper} game times for {game_date}...")

        conn = sqlite3.connect(str(pp_db))
        rows = conn.execute('''
            SELECT team, MIN(start_time) as start_time
            FROM prizepicks_lines
            WHERE substr(start_time, 1, 10) = ?
              AND league = ?
              AND team NOT LIKE "%/%"
            GROUP BY team
        ''', [game_date, sport_upper]).fetchall()
        conn.close()

        # Store raw ISO timestamp (Supabase game_time is TIMESTAMPTZ)
        # Dashboard formats to human-readable "h:MM PM ET" at display time
        team_times = {}
        for team, iso_time in rows:
            try:
                # Normalize: "2026-03-01T13:10:00.000-05:00" → "2026-03-01T13:10:00-05:00"
                ts = iso_time[:19] + iso_time[23:] if '.' in iso_time else iso_time
                team_times[team.upper()] = ts
            except Exception:
                pass

        updated = 0
        for team, game_time in team_times.items():
            try:
                r = self.client.table('daily_props').update({
                    'game_time': game_time
                }).eq('sport', sport_upper).eq('game_date', game_date).eq(
                    'team', team
                ).execute()
                if r.data:
                    updated += len(r.data)
            except Exception as e:
                print(f"[SYNC ERROR] game_time {team}: {e}")

        print(f"[SYNC] Set game_time for {updated} rows ({len(team_times)} teams) for {sport_upper}")
        return {'updated': updated, 'teams': len(team_times), 'sport': sport_upper}

    @staticmethod
    def _initial_match(full_name_lower: str, abbrev_lower: str) -> bool:
        """Check if abbrev_lower ('s. bennett') matches full_name_lower ('sam bennett')."""
        if '. ' not in abbrev_lower:
            return False
        parts = abbrev_lower.split('. ', 1)
        if len(parts[0]) != 1:
            return False
        full_parts = full_name_lower.split()
        if len(full_parts) < 2:
            return False
        return parts[0] == full_parts[0][0] and parts[1] == full_parts[-1]

    def trigger_user_grading(self, game_date: str, sport: Optional[str] = None) -> Dict:
        """
        Call the grade-user-picks Edge Function to grade user picks
        and award points after grading sync completes.
        """
        print(f"[SYNC] Triggering user pick grading for {game_date}...")
        last_error = None
        for attempt in range(1, 3):  # 2 attempts: immediate + 1 retry after 60s
            try:
                result = self.client.functions.invoke(
                    'grade-user-picks',
                    invoke_options={'body': {'game_date': game_date, 'sport': sport}}
                )
                print(f"[SYNC] User grading triggered (attempt {attempt}): {result}")
                return {'success': True, 'result': result}
            except Exception as e:
                last_error = e
                if attempt < 2:
                    print(f"[SYNC] User grading attempt {attempt} failed: {e} — retrying in 60s...")
                    import time
                    time.sleep(60)
        print(f"[SYNC ERROR] User grading failed after 2 attempts: {last_error}")
        return {'success': False, 'error': str(last_error)}

    def _sync_model_performance(self, sport: str, game_date: str, rows: list):
        """Sync daily model performance summary to model_performance table."""
        sport_upper = sport.upper()
        total = len(rows)
        hits = sum(1 for r in rows if dict(r).get('outcome') == 'HIT')
        accuracy = hits / total if total > 0 else 0

        # Count by prediction direction
        over_total = sum(1 for r in rows if dict(r).get('ai_prediction') == 'OVER')
        over_hits = sum(1 for r in rows if dict(r).get('ai_prediction') == 'OVER' and dict(r).get('outcome') == 'HIT')
        under_total = total - over_total
        under_hits = hits - over_hits

        # By prop type
        by_prop = {}
        for r in rows:
            rd = dict(r)
            pt = rd.get('prop_type', 'unknown')
            if pt not in by_prop:
                by_prop[pt] = {'total': 0, 'hits': 0}
            by_prop[pt]['total'] += 1
            if rd.get('outcome') == 'HIT':
                by_prop[pt]['hits'] += 1
        for pt in by_prop:
            t = by_prop[pt]['total']
            by_prop[pt]['accuracy'] = by_prop[pt]['hits'] / t if t > 0 else 0

        try:
            self.client.table('model_performance').upsert({
                'game_date': game_date,
                'sport': sport_upper,
                'total_predictions': total,
                'total_graded': total,
                'hits': hits,
                'accuracy': round(accuracy, 4),
                'over_accuracy': round(over_hits / over_total, 4) if over_total > 0 else None,
                'under_accuracy': round(under_hits / under_total, 4) if under_total > 0 else None,
                'by_prop': json.dumps(by_prop),
            }, on_conflict='game_date,sport').execute()
            print(f"[SYNC] Model performance synced: {hits}/{total} ({accuracy:.1%})")
        except Exception as e:
            print(f"[SYNC ERROR] Model performance sync failed: {e}")

    @staticmethod
    def _normalize_name(name: str) -> str:
        """Strip diacritics so 'Luka Dončić' and 'Luka Doncic' are the same key in Supabase."""
        return ''.join(
            c for c in unicodedata.normalize('NFD', name)
            if unicodedata.category(c) != 'Mn'
        )

    def _fetch_all_sport_date(self, sport_upper: str, game_date: str, columns: str) -> list:
        """
        Fetch all daily_props rows for a sport/date, paginating past the 1000-row Supabase limit.

        Supabase default cap is 1000 rows per query. ALL batch selects must loop via
        .range(offset, offset+999) until a batch smaller than page_size is returned.

        Args:
            sport_upper: Uppercase sport code ('NBA' or 'NHL')
            game_date:   ISO date string e.g. '2026-04-03'
            columns:     Comma-separated column names for .select()

        Returns:
            List of all matching rows across all pages.
        """
        all_rows = []
        page_size = 1000
        offset = 0
        while True:
            r = self.client.table('daily_props').select(columns).eq(
                'sport', sport_upper
            ).eq('game_date', game_date).range(
                offset, offset + page_size - 1
            ).execute()
            batch = r.data or []
            all_rows.extend(batch)
            if len(batch) < page_size:
                break
            offset += page_size
        return all_rows


def main():
    parser = argparse.ArgumentParser(description='Sync predictions to Supabase')
    parser.add_argument('--sport', choices=['nhl', 'nba', 'all'], default='all')
    parser.add_argument('--operation', choices=['predictions', 'grading', 'smart-picks', 'odds-types', 'game-times', 'all'], default='all')
    parser.add_argument('--date', help='Date to sync (YYYY-MM-DD)')
    args = parser.parse_args()

    syncer = SupabaseSync()
    sports = ['nba', 'nhl'] if args.sport == 'all' else [args.sport]

    for sport in sports:
        if args.operation in ('predictions', 'all'):
            syncer.sync_predictions(sport, args.date)

        if args.operation in ('smart-picks', 'all'):
            syncer.sync_smart_picks(sport, args.date)

        # Always run odds-type correction after smart-picks so labels are factually correct
        # even for lines our model doesn't recommend (below goblin break-even)
        if args.operation in ('odds-types', 'smart-picks', 'all'):
            syncer.sync_odds_types(sport, args.date)

        # Populate game_time from PP start_time data
        if args.operation in ('game-times', 'smart-picks', 'all'):
            syncer.sync_game_times(sport, args.date)

        if args.operation in ('grading', 'all'):
            grading_date = args.date or (date.today() - timedelta(days=1)).isoformat()
            syncer.sync_grading(sport, grading_date)
            syncer.trigger_user_grading(grading_date, sport.upper())


if __name__ == '__main__':
    main()

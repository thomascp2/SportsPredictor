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

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

try:
    from supabase import create_client, Client
    SUPABASE_AVAILABLE = True
except ImportError:
    SUPABASE_AVAILABLE = False
    print("WARNING: supabase-py not installed. Run: pip install supabase")

from sync.config import (
    SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY,
    NHL_DB_PATH, NBA_DB_PATH, SYNC_BATCH_SIZE
)


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
        db_path = self.db_paths[sport.lower()]
        print(f"[SYNC] Syncing {sport_upper} predictions for {game_date}...")

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row

        # Query predictions - different schemas per sport
        if sport.lower() == 'nhl':
            rows = conn.execute('''
                SELECT player_name, team, opponent, prop_type, line,
                       prediction, probability, features_json
                FROM predictions
                WHERE game_date = ?
            ''', (game_date,)).fetchall()
        else:
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

        # Transform to Supabase format
        props = []
        for row in rows:
            row_dict = dict(row)
            probability = row_dict.get('probability', 0.5)
            prediction_dir = row_dict.get('prediction', 'OVER')

            # Directional confidence: probability stores raw OVER probability.
            # For UNDER picks (probability < 0.5), the model confidence is 1-probability.
            # Use this for tier, edge, and ai_probability so UNDER picks rank correctly.
            confidence = probability if prediction_dir == 'OVER' else (1.0 - probability)

            # Calculate edge and tier based on directional confidence
            edge = (confidence - 0.56) * 100 if confidence else 0
            tier = self._get_tier(confidence)

            # Calculate EV values using directional confidence
            ev_2leg = (confidence ** 2) * 3.0 - 1 if confidence else 0
            ev_3leg = (confidence ** 3) * 5.0 - 1 if confidence else 0
            ev_4leg = (confidence ** 4) * 10.0 - 1 if confidence else 0

            prop = {
                'game_date': game_date,
                'sport': sport_upper,
                'player_name': self._normalize_name(row_dict['player_name']),
                'team': row_dict.get('team', ''),
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
            }
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

        # Query outcomes - different column names per sport
        if sport.lower() == 'nhl':
            prediction_col = 'predicted_outcome'
            actual_val_col = 'actual_stat_value'
        else:
            prediction_col = 'prediction'
            actual_val_col = 'actual_value'

        rows = conn.execute(f'''
            SELECT o.player_name, o.prop_type, o.line,
                   o.{actual_val_col} as actual_value,
                   o.outcome, o.{prediction_col} as ai_prediction
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
                print(f"[SYNC ERROR] {row_dict['player_name']}: {e}")

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
                self.client.table('daily_props').upsert({
                    'game_date': game_date,
                    'sport': sport_upper,
                    'player_name': self._normalize_name(pick.player_name),
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
                }, on_conflict='game_date,player_name,prop_type,line').execute()
                synced += 1
            except Exception as e:
                print(f"[SYNC ERROR] {pick.player_name}: {e}")

        print(f"[SYNC] Synced {synced}/{len(picks)} {sport_upper} smart picks")
        return {'synced': synced, 'total': len(picks), 'sport': sport_upper}

    def trigger_user_grading(self, game_date: str, sport: Optional[str] = None) -> Dict:
        """
        Call the grade-user-picks Edge Function to grade user picks
        and award points after grading sync completes.
        """
        print(f"[SYNC] Triggering user pick grading for {game_date}...")
        try:
            result = self.client.functions.invoke(
                'grade-user-picks',
                invoke_options={'body': {'game_date': game_date, 'sport': sport}}
            )
            print(f"[SYNC] User grading triggered: {result}")
            return {'success': True, 'result': result}
        except Exception as e:
            print(f"[SYNC ERROR] User grading failed: {e}")
            return {'success': False, 'error': str(e)}

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

    @staticmethod
    def _get_tier(probability: float) -> str:
        if probability >= 0.75:
            return 'T1-ELITE'
        elif probability >= 0.70:
            return 'T2-STRONG'
        elif probability >= 0.65:
            return 'T3-GOOD'
        elif probability >= 0.55:
            return 'T4-LEAN'
        else:
            return 'T5-FADE'


def main():
    parser = argparse.ArgumentParser(description='Sync predictions to Supabase')
    parser.add_argument('--sport', choices=['nhl', 'nba', 'all'], default='all')
    parser.add_argument('--operation', choices=['predictions', 'grading', 'smart-picks', 'all'], default='all')
    parser.add_argument('--date', help='Date to sync (YYYY-MM-DD)')
    args = parser.parse_args()

    syncer = SupabaseSync()
    sports = ['nba', 'nhl'] if args.sport == 'all' else [args.sport]

    for sport in sports:
        if args.operation in ('predictions', 'all'):
            syncer.sync_predictions(sport, args.date)

        if args.operation in ('smart-picks', 'all'):
            syncer.sync_smart_picks(sport, args.date)

        if args.operation in ('grading', 'all'):
            grading_date = args.date or (date.today() - timedelta(days=1)).isoformat()
            syncer.sync_grading(sport, grading_date)
            syncer.trigger_user_grading(grading_date, sport.upper())


if __name__ == '__main__':
    main()

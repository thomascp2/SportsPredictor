"""
ESPN Golf API Client
====================

Fetches PGA Tour tournament schedules, leaderboards, and round scores
from ESPN's public (no-auth) API endpoints.

ESPN golf data covers:
- Tournament calendar / scoreboard
- Live and final round-by-round scores per player
- Player IDs, names, and positions

Limitations vs. DataGolf:
- No Strokes Gained data (ESPN only has scoring, not shot-level tracking)
- Traditional stats (GIR, driving, putting) must come from pga_stats_scraper.py
- Historical data available but requires iterating past tournament IDs

Upgrade note: When adding DataGolf API integration, swap out score fetching
here and add a datagolf_api.py wrapper alongside this file.

Usage:
    from espn_golf_api import ESPNGolfApi
    api = ESPNGolfApi()
    events = api.get_tournament_schedule()
    leaderboard = api.get_leaderboard(event_id="401353232")
    rounds = api.get_player_rounds(event_id="401353232", player_id="3448")
"""

import requests
import time
import logging
from datetime import datetime, date, timedelta

logger = logging.getLogger(__name__)


class ESPNGolfApi:
    """ESPN Golf API client — PGA Tour events, scores, and player data."""

    BASE_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/leaderboard"
    SPORTS_CORE_URL = "https://sports.core.api.espn.com/v2/sports/golf/leagues/pga"
    CALENDAR_URL = "https://site.api.espn.com/apis/site/v2/sports/golf/leaderboard"
    TIMEOUT = 30
    RETRY_ATTEMPTS = 3
    RETRY_DELAY = 2  # seconds

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (compatible; SportsPredictor/1.0)",
        })

    # ------------------------------------------------------------------
    # Public methods
    # ------------------------------------------------------------------

    def get_current_tournament(self):
        """
        Get the currently active (or most recently completed) PGA Tour event.

        Returns:
            dict | None: Event info dict or None if no active event found.
            {
                'event_id': str,
                'name': str,
                'start_date': str,   # YYYY-MM-DD
                'end_date': str,     # YYYY-MM-DD
                'course_name': str,
                'status': str,       # 'pre', 'in', 'post'
                'current_round': int,
            }
        """
        data = self._get(self.BASE_URL, params={"league": "pga"})
        if not data:
            return None
        return self._parse_event_summary(data)

    def get_tournament_by_date(self, target_date: str):
        """
        Get the PGA Tour tournament active on a specific date.

        Args:
            target_date: YYYY-MM-DD string

        Returns:
            dict | None: Event info dict, same structure as get_current_tournament()
        """
        espn_date = target_date.replace("-", "")
        data = self._get(self.BASE_URL, params={"league": "pga", "dates": espn_date})
        if not data:
            return None
        return self._parse_event_summary(data)

    def get_leaderboard(self, event_id: str):
        """
        Get the full leaderboard for a tournament event.

        Args:
            event_id: ESPN event ID string (e.g., "401353232")

        Returns:
            list[dict]: One entry per player:
            {
                'player_id': str,
                'player_name': str,
                'position': int | None,
                'made_cut': bool | None,   # None if cut hasn't happened yet
                'total_score': int | None, # Score vs par
                'rounds': [               # List of round scores
                    {'round': 1, 'score': 68, 'vs_par': -4},
                    ...
                ]
            }
        """
        data = self._get(self.BASE_URL, params={"league": "pga", "event": event_id})
        if not data:
            return []
        return self._parse_leaderboard(data)

    def get_round_scores(self, event_id: str, round_number: int):
        """
        Get all player scores for a specific round in a tournament.

        Args:
            event_id: ESPN event ID
            round_number: 1, 2, 3, or 4

        Returns:
            list[dict]:
            {
                'player_id': str,
                'player_name': str,
                'round_number': int,
                'round_score': int | None,   # Gross score
                'score_vs_par': int | None,
                'made_cut': bool | None,
            }
        """
        leaderboard = self.get_leaderboard(event_id)
        results = []
        for entry in leaderboard:
            round_data = next(
                (r for r in entry.get("rounds", []) if r["round"] == round_number),
                None,
            )
            if round_data:
                results.append({
                    "player_id": entry["player_id"],
                    "player_name": entry["player_name"],
                    "round_number": round_number,
                    "round_score": round_data.get("score"),
                    "score_vs_par": round_data.get("vs_par"),
                    "made_cut": entry.get("made_cut"),
                    "position": entry.get("position"),
                })
        return results

    def get_upcoming_events(self, days_ahead: int = 14):
        """
        Get PGA Tour events in the next N days.

        Returns:
            list[dict]: List of event info dicts ordered by start_date.
        """
        today = date.today()
        end_date = today + timedelta(days=days_ahead)
        events = []
        # ESPN leaderboard endpoint returns the current/upcoming event;
        # we step through the calendar week by week
        check_date = today
        seen_ids = set()
        while check_date <= end_date:
            event = self.get_tournament_by_date(check_date.isoformat())
            if event and event.get("event_id") not in seen_ids:
                events.append(event)
                seen_ids.add(event["event_id"])
                # Skip to the Monday after this event ends
                end = date.fromisoformat(event["end_date"]) if event.get("end_date") else check_date
                check_date = end + timedelta(days=1)
            else:
                check_date += timedelta(days=7)
        return events

    def get_historical_event_ids(self, season: int):
        """
        Retrieve ESPN event IDs for all PGA Tour events in a given season.

        Uses the ESPN sports.core API seasons/{year}/types/2/events endpoint which
        returns all regular-season events for the PGA Tour. The site.api.espn.com
        leaderboard endpoint's ?season param and ?dates param both return only the
        current live tournament and do not support historical season queries.

        Args:
            season: PGA Tour season year (e.g., 2024)

        Returns:
            list[dict]: Lightweight event info dicts with 'event_id', 'name',
                        'start_date', 'end_date'
        """
        url = f"{self.SPORTS_CORE_URL}/seasons/{season}/types/2/events"
        data = self._get(url, params={"limit": 200})
        if not data:
            return []

        items = data.get("items", [])
        if not items:
            return []

        events = []
        for item in items:
            ref = item.get("$ref", "")
            if not ref:
                continue
            # Extract event ID from the ref URL, e.g.:
            # http://sports.core.api.espn.com/.../events/401580329?lang=...
            try:
                event_id = ref.split("/events/")[1].split("?")[0]
            except (IndexError, AttributeError):
                continue

            # Resolve the ref to get name and dates
            ev_data = self._get(ref)
            if not ev_data:
                # Fall back to ID-only stub; name will be set during leaderboard fetch
                events.append({
                    "event_id": event_id,
                    "name": f"Event {event_id}",
                    "start_date": "",
                    "end_date": "",
                })
                continue

            events.append({
                "event_id": str(ev_data.get("id", event_id)),
                "name": ev_data.get("name", f"Event {event_id}"),
                "start_date": ev_data.get("date", "")[:10],
                "end_date": ev_data.get("endDate", "")[:10],
            })
            time.sleep(self.RETRY_DELAY * 0.15)  # light rate-limit on ref resolution

        return events

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------

    def _parse_event_summary(self, data: dict):
        """Extract top-level event metadata from ESPN leaderboard response."""
        # ESPN leaderboard API returns data['events'] at the top level (no 'leagues' wrapper)
        events = data.get("events", [])
        if not events:
            return None

        event = events[0]
        competitions = event.get("competitions", [])
        competition = competitions[0] if competitions else {}
        venue = competition.get("venue", {})
        course_name = venue.get("fullName", "") or venue.get("shortName", "")
        status_obj = competition.get("status", {})
        status_type = status_obj.get("type", {})
        status_state = status_type.get("state", "pre")  # 'pre', 'in', 'post'

        # Determine current round from competitors' scorecard
        current_round = self._infer_current_round(competition)

        return {
            "event_id": str(event.get("id", "")),
            "name": event.get("name", event.get("shortName", "Unknown Tournament")),
            "start_date": event.get("date", competition.get("date", ""))[:10],
            "end_date": event.get("endDate", competition.get("endDate", ""))[:10],
            "course_name": course_name,
            "status": status_state,
            "current_round": current_round,
        }

    def _parse_leaderboard(self, data: dict):
        """Parse full player leaderboard from ESPN response."""
        players = []
        # ESPN leaderboard API returns data['events'] at the top level (no 'leagues' wrapper)
        for event in data.get("events", []):
            for competition in event.get("competitions", []):
                # Skip non-standard events (Presidents Cup, team events) where
                # competitions contains nested lists instead of player dicts
                if not isinstance(competition, dict):
                    continue
                for competitor in competition.get("competitors", []):
                    if not isinstance(competitor, dict):
                        continue
                    entry = self._parse_competitor(competitor)
                    if entry:
                        players.append(entry)
        return players

    def _parse_competitor(self, competitor: dict):
        """Parse a single player entry from the competitors list."""
        athlete = competitor.get("athlete", {})
        player_id = str(athlete.get("id", "") or competitor.get("id", ""))
        player_name = (
            athlete.get("displayName", "")
            or athlete.get("fullName", "")
            or f"Player_{player_id}"
        )
        if not player_id:
            return None

        # status is a dict: {type: {name: 'STATUS_FINISH'|'STATUS_CUT'|...}}
        status_obj = competitor.get("status", {})
        status_name = ""
        made_cut = None
        if isinstance(status_obj, dict):
            status_name = status_obj.get("type", {}).get("name", "")
            if status_name == "STATUS_FINISH":
                made_cut = True
            elif status_name == "STATUS_CUT":
                made_cut = False
        elif isinstance(status_obj, str):
            # Legacy format fallback
            if status_obj in ("active", "cut"):
                made_cut = status_obj != "cut"

        # Total score vs par
        score_str = competitor.get("score", "")
        total_score = self._parse_score(str(score_str) if score_str else "")

        # Position: in status.position.id (numeric finish position)
        position = None
        if isinstance(status_obj, dict):
            pos_obj = status_obj.get("position", {})
            try:
                pos_val = int(pos_obj.get("id", 0))
                position = pos_val if pos_val > 0 else None
            except (ValueError, TypeError):
                pass
        if position is None:
            try:
                position = int(competitor.get("sortOrder", 0)) or None
            except (ValueError, TypeError):
                pass

        # Round-by-round scores from linescores
        # linescore.value = gross score (float, e.g. 71.0)
        # linescore.displayValue = vs-par string (e.g. '-2')
        # linescore.period = round number (1, 2, 3, 4)
        rounds = []
        for ls in competitor.get("linescores", []):
            round_num = ls.get("period", len(rounds) + 1)
            raw_value = ls.get("value")
            score = None
            if raw_value is not None:
                try:
                    score = int(float(raw_value))
                except (ValueError, TypeError):
                    pass
            if score is None:
                score = self._parse_score(str(ls.get("displayValue", "")))
            vs_par_str = ls.get("displayValue", "")
            vs_par = self._parse_score(vs_par_str) if vs_par_str not in ("E", "", "--") else 0
            rounds.append({
                "round": round_num,
                "score": score,
                "vs_par": vs_par,
            })

        return {
            "player_id": player_id,
            "player_name": player_name,
            "position": position,
            "made_cut": made_cut,
            "total_score": total_score,
            "status": status_name,
            "rounds": rounds,
        }

    def _infer_current_round(self, competition: dict):
        """Guess the current round number from the competitors' round count."""
        competitors = competition.get("competitors", [])
        if not competitors:
            return 1
        max_rounds = max(
            len(c.get("linescores", [])) for c in competitors
        )
        return max(1, max_rounds)

    @staticmethod
    def _parse_score(value: str):
        """
        Convert ESPN score strings to integer.
        Handles: '68', '-4', 'E', 'WD', 'CUT', '--'
        Returns int for numeric scores, None for non-numeric.
        """
        if not value or value in ("--", "E", "WD", "CUT", "MDF", "DQ", ""):
            return None
        try:
            return int(value)
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    def _get(self, url: str, params: dict = None):
        """GET with retry logic. Returns parsed JSON or None."""
        for attempt in range(self.RETRY_ATTEMPTS):
            try:
                response = self.session.get(url, params=params, timeout=self.TIMEOUT)
                response.raise_for_status()
                return response.json()
            except requests.exceptions.HTTPError as e:
                logger.warning(f"ESPN Golf API HTTP error (attempt {attempt+1}): {e}")
            except requests.exceptions.RequestException as e:
                logger.warning(f"ESPN Golf API request error (attempt {attempt+1}): {e}")
            if attempt < self.RETRY_ATTEMPTS - 1:
                time.sleep(self.RETRY_DELAY * (attempt + 1))
        return None


# ------------------------------------------------------------------
# Standalone test
# ------------------------------------------------------------------

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    api = ESPNGolfApi()

    print("Fetching current PGA Tour tournament...")
    event = api.get_current_tournament()
    if event:
        print(f"  Event: {event['name']}")
        print(f"  Course: {event['course_name']}")
        print(f"  Status: {event['status']}, Round: {event['current_round']}")
        print(f"  Dates: {event['start_date']} to {event['end_date']}")

        print(f"\nFetching leaderboard for event {event['event_id']}...")
        lb = api.get_leaderboard(event["event_id"])
        print(f"  {len(lb)} players on leaderboard")
        for player in lb[:5]:
            rounds_str = ", ".join(
                f"R{r['round']}:{r['score']}" for r in player["rounds"] if r["score"]
            )
            print(f"  {player['player_name']}: {rounds_str} | cut={player['made_cut']}")
    else:
        print("  No active tournament found. Try a date during a tournament week.")
        today = __import__("datetime").date.today()
        print(f"\nChecking historical event IDs for 2024 season...")
        ids = api.get_historical_event_ids(2024)
        print(f"  Found {len(ids)} events in 2024 season")
        for ev in ids[:3]:
            print(f"  {ev['event_id']}: {ev['name']} ({ev['start_date']})")

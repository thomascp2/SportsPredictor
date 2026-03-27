"""
Game Prediction Discord Notifications — Send SHARP plays to Discord.

Called after game predictions are generated or graded.
Sends formatted embeds with moneyline, spread, and total picks.

Usage:
    from shared.game_discord_notifications import (
        send_game_predictions_alert,
        send_game_grading_alert,
    )

    send_game_predictions_alert("nhl", results_dict)
    send_game_grading_alert("nba", grading_results)
"""

import os
import json
import urllib.request
from datetime import datetime
from typing import Dict, List, Optional

# Discord webhook — must be set via environment variable (never hardcode)
DISCORD_WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL", "")

SPORT_EMOJI = {"nhl": "[NHL]", "nba": "[NBA]", "mlb": "[MLB]"}
TIER_EMOJI = {"SHARP": "[SHARP]", "LEAN": "[LEAN]", "PASS": ""}

COLOR_MAP = {
    "green": 3066993,
    "blue": 3447003,
    "red": 15158332,
    "yellow": 16776960,
    "purple": 10181046,
}


def _send_webhook(payload: dict) -> bool:
    """Send a payload to Discord webhook."""
    if not DISCORD_WEBHOOK_URL:
        print("  [DISCORD] No webhook URL configured")
        return False

    try:
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            DISCORD_WEBHOOK_URL,
            data=data,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"  [DISCORD] Send failed: {e}")
        return False


def send_game_predictions_alert(sport: str, results: Dict,
                                 predictions: List[Dict] = None) -> bool:
    """
    Send game prediction summary to Discord.

    Args:
        sport: 'nhl', 'nba', or 'mlb'
        results: Dict from GamePredictionEngine.predict_and_save()
        predictions: Optional full list of prediction dicts for detail
    """
    sport_tag = SPORT_EMOJI.get(sport.lower(), sport.upper())
    game_count = results.get("games", 0)
    pred_count = results.get("total_predictions", 0)
    sharp_count = results.get("sharp_plays", 0)
    sharp_details = results.get("sharp_details", [])

    # Choose color based on SHARP play count
    if sharp_count >= 3:
        color = COLOR_MAP["green"]
    elif sharp_count >= 1:
        color = COLOR_MAP["blue"]
    else:
        color = COLOR_MAP["yellow"]

    # Build SHARP plays text
    sharp_text = ""
    if sharp_details:
        lines = []
        for detail in sharp_details[:8]:  # Cap at 8 to stay under embed limits
            lines.append(f"-> {detail}")
        sharp_text = "\n".join(lines)
    else:
        sharp_text = "No SHARP plays today"

    # Build embed
    embed = {
        "title": f"{sport_tag} Game Lines - {datetime.now().strftime('%m/%d/%Y')}",
        "description": (
            f"**{game_count}** games | **{pred_count}** predictions | "
            f"**{sharp_count}** SHARP plays"
        ),
        "color": color,
        "fields": [
            {
                "name": "[SHARP] Top Plays",
                "value": f"```\n{sharp_text}\n```",
                "inline": False,
            },
        ],
        "footer": {
            "text": "FreePicks Game Lines | Statistical + ML Ensemble",
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    payload = {"embeds": [embed]}
    return _send_webhook(payload)


def send_game_grading_alert(sport: str, results: Dict) -> bool:
    """
    Send grading results to Discord.

    Args:
        sport: 'nhl', 'nba', or 'mlb'
        results: Dict from GamePredictionGrader.grade_date()
    """
    sport_tag = SPORT_EMOJI.get(sport.lower(), sport.upper())
    graded = results.get("graded", 0)
    hits = results.get("hits", 0)
    misses = results.get("misses", 0)
    pushes = results.get("pushes", 0)
    accuracy = results.get("accuracy", 0)
    game_date = results.get("game_date", "")

    if graded == 0:
        return False  # Nothing to report

    # Color based on accuracy
    if accuracy >= 60:
        color = COLOR_MAP["green"]
    elif accuracy >= 50:
        color = COLOR_MAP["blue"]
    else:
        color = COLOR_MAP["red"]

    embed = {
        "title": f"{sport_tag} Game Lines Graded - {game_date}",
        "description": f"**{accuracy:.1f}%** accuracy ({hits}/{hits+misses})",
        "color": color,
        "fields": [
            {"name": "Graded", "value": str(graded), "inline": True},
            {"name": "Hits", "value": str(hits), "inline": True},
            {"name": "Misses", "value": str(misses), "inline": True},
            {"name": "Pushes", "value": str(pushes), "inline": True},
        ],
        "footer": {
            "text": "FreePicks Game Lines | Auto-Graded",
        },
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    payload = {"embeds": [embed]}
    return _send_webhook(payload)


def send_convergence_alert(sport: str, game_date: str,
                            matchup: str, agreeing_bots: List[str],
                            bet_type: str, prediction: str,
                            probability: float) -> bool:
    """
    Send alert when 4+ bots converge on the same pick.
    (Placeholder for Bot Arena system)
    """
    sport_tag = SPORT_EMOJI.get(sport.lower(), sport.upper())
    bot_list = ", ".join(agreeing_bots)

    embed = {
        "title": f"{sport_tag} CONVERGENCE ALERT",
        "description": (
            f"**{len(agreeing_bots)} bots agree** on {matchup}\n"
            f"{bet_type.upper()}: **{prediction}** ({probability:.1%})"
        ),
        "color": COLOR_MAP["purple"],
        "fields": [
            {"name": "Bots", "value": bot_list, "inline": False},
        ],
        "footer": {"text": "FreePicks Bot Arena"},
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    payload = {"embeds": [embed]}
    return _send_webhook(payload)

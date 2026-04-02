"""
Feature fencepost verification using in-memory SQLite DB.

Verifies that rolling window queries correctly exclude the target game date
(strict less-than) to prevent future-data leakage into features.
"""


def test_current_game_excluded(in_memory_game_logs_db):
    """
    Query with game_date < '2026-01-08' must return exactly 7 rows
    (dates 01-01 through 01-07) and must NOT include 2026-01-08.
    """
    conn = in_memory_game_logs_db
    cursor = conn.execute(
        "SELECT game_date, points FROM player_game_logs "
        "WHERE player_name = 'Test Player' AND game_date < '2026-01-08' "
        "ORDER BY game_date DESC"
    )
    rows = cursor.fetchall()

    assert len(rows) == 7, (
        f"Expected 7 rows for dates 2026-01-01 through 2026-01-07, got {len(rows)}"
    )

    returned_dates = [row[0] for row in rows]
    assert '2026-01-08' not in returned_dates, (
        "2026-01-08 (the target date) must NOT appear in the window query results"
    )


def test_rolling_window_does_not_include_target_date(in_memory_game_logs_db):
    """
    Last-5 window before 2026-01-10 must return dates 01-05 through 01-09
    with points [24, 17, 23, 21, 19] (descending order) and must NOT
    include the 2026-01-10 row (points=20).
    """
    conn = in_memory_game_logs_db
    cursor = conn.execute(
        "SELECT points FROM player_game_logs "
        "WHERE player_name = 'Test Player' AND game_date < '2026-01-10' "
        "ORDER BY game_date DESC LIMIT 5"
    )
    rows = cursor.fetchall()
    points = [row[0] for row in rows]

    assert len(points) == 5, (
        f"Expected 5 rows for last-5 window before 2026-01-10, got {len(points)}"
    )

    # Dates 01-09 through 01-05 in descending order
    # Index mapping: 01-09 -> points[8]=24, 01-08 -> 17, 01-07 -> 23, 01-06 -> 21, 01-05 -> 19
    expected = [24.0, 17.0, 23.0, 21.0, 19.0]
    assert points == expected, (
        f"Expected points {expected} (dates 01-09 to 01-05 desc), got {points}"
    )

    # Target date value (2026-01-10 -> index 9 -> points=20) must NOT appear
    assert 20.0 not in points, (
        "20.0 (points for 2026-01-10, the target date) must NOT be in rolling window results"
    )

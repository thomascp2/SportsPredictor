from datetime import date, timedelta
from typing import Generator


def date_range(start: date, end: date) -> Generator[date, None, None]:
    """Yield each date from start to end inclusive."""
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def today() -> date:
    """Return today's date."""
    return date.today()


def yesterday() -> date:
    """Return yesterday's date."""
    return date.today() - timedelta(days=1)


def to_str(d: date) -> str:
    """Format date as YYYY-MM-DD string."""
    return d.strftime("%Y-%m-%d")


def from_str(s: str) -> date:
    """Parse YYYY-MM-DD string to date."""
    return date.fromisoformat(s)

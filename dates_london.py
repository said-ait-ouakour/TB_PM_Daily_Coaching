"""Yesterday calendar date in Europe/London (used as the business run date)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, time, timezone
from typing import Tuple
from zoneinfo import ZoneInfo

LONDON = ZoneInfo("Europe/London")


def yesterday_london_date() -> date:
    """Calendar date of 'yesterday' relative to now in London."""
    now_london = datetime.now(LONDON)
    return now_london.date() - timedelta(days=1)


def yesterday_london_iso() -> str:
    """YYYY-MM-DD for yesterday in London (default run_date everywhere)."""
    return yesterday_london_date().isoformat()


def yesterday_london_utc_bounds() -> Tuple[datetime, datetime]:
    """
    Start of yesterday London and start of today London, as UTC-aware datetimes.
    Mongo half-open range on UTC datetimes: {"$gte": start_utc, "$lt": end_utc}.
    """
    y = yesterday_london_date()
    start_london = datetime.combine(y, time.min, tzinfo=LONDON)
    end_london = start_london + timedelta(days=1)
    return (start_london.astimezone(timezone.utc), end_london.astimezone(timezone.utc))

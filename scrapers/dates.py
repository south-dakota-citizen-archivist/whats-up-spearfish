"""
scrapers/dates.py

Timestamp parsing shared by the scrapers (at save time) and the site build.

Everything is normalized to America/Denver. Date-only values stay dates (an
all-day thing); values with a time become aware datetimes. How a *naive*
timestamp (no offset) is interpreted depends on the source — iCal/Sidearm/OData
feeds tend to emit UTC, while hand-built HTML scrapers usually emit local
time — so callers pass ``naive_tz``.
"""

from __future__ import annotations

import re
from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo

from dateutil import parser as dateutil_parser

MT = ZoneInfo("America/Denver")
UTC = timezone.utc

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DEFAULT_A = datetime(2000, 1, 1, 0, 0)
_DEFAULT_B = datetime(2000, 1, 1, 12, 30)

_TZINFOS = {
    "MDT": -6 * 3600,
    "MST": -7 * 3600,
    "MT": MT,
    "CDT": -5 * 3600,
    "CST": -6 * 3600,
    "EDT": -4 * 3600,
    "EST": -5 * 3600,
    "PDT": -7 * 3600,
    "PST": -8 * 3600,
}


def now() -> datetime:
    return datetime.now(tz=MT)


def today() -> date:
    return now().date()


def parse(value, naive_tz=UTC) -> date | datetime | None:
    """
    Parse *value* into a ``date`` (date-only input) or an aware Mountain Time
    ``datetime``. Returns None for empty or unparseable input.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, date):
        return value
    else:
        s = str(value).strip()
        if _DATE_ONLY_RE.match(s):
            try:
                return date.fromisoformat(s)
            except ValueError:
                return None
        try:
            dt = dateutil_parser.parse(s, tzinfos=_TZINFOS, default=_DEFAULT_A)
            # No time in the string if the result depends on the default's time of day
            if dt.tzinfo is None and dt.time() != dateutil_parser.parse(s, default=_DEFAULT_B).time():
                return dt.date()
        except (ValueError, TypeError, OverflowError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=naive_tz if isinstance(naive_tz, (timezone, ZoneInfo)) else ZoneInfo(naive_tz))
    return dt.astimezone(MT)


def to_date(value, naive_tz=UTC) -> date | None:
    """Parse *value* and return its Mountain Time calendar date."""
    parsed = parse(value, naive_tz)
    if isinstance(parsed, datetime):
        return parsed.date()
    return parsed


def iso(value: date | datetime | None) -> str:
    """ISO string for a parsed value: 'YYYY-MM-DD' or 'YYYY-MM-DDTHH:MM:SS-06:00'."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat(timespec="seconds")
    return value.isoformat()

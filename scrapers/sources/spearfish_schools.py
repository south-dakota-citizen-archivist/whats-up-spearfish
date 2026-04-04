"""
scrapers/sources/spearfish_schools.py

Spearfish School District — campus calendar via iCal feed.
https://spearfish.ss20.sharpschool.com/calendar

SchoolMessenger Presence CMS. Exposes a public iCalendar feed at
/ICalendarHandler?calendarId=300447 — no auth required.
"""

from datetime import date, datetime, timezone

import requests
from icalendar import Calendar

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

ICAL_URL = "https://spearfish.ss20.sharpschool.com/ICalendarHandler?calendarId=300447"
SOURCE_URL = "https://spearfish.ss20.sharpschool.com/calendar"


def _to_iso(dt_val) -> str:
    """Convert a vDatetime / vDate / date / datetime to ISO 8601 string."""
    if dt_val is None:
        return ""
    # icalendar wraps values in vDDDTypes etc.; unwrap with .dt
    val = getattr(dt_val, "dt", dt_val)
    if isinstance(val, datetime):
        # Normalise to UTC then strip tz for a consistent naive ISO string
        if val.tzinfo is not None:
            val = val.astimezone(timezone.utc).replace(tzinfo=None)
        return val.isoformat()
    if isinstance(val, date):
        return val.isoformat()
    return str(val)


class SpearfishSchools(BaseScraper):
    name = "Spearfish School District"
    slug = "spearfish_schools"
    dedup_key = "uid"

    def scrape(self) -> list[dict]:
        resp = requests.get(ICAL_URL, timeout=30, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()

        cal = Calendar.from_ical(resp.content)
        records = []

        for component in cal.walk():
            if component.name != "VEVENT":
                continue

            uid = str(component.get("UID", ""))
            title = str(component.get("SUMMARY", "")).strip()
            description = str(component.get("DESCRIPTION", "")).strip()
            location = str(component.get("LOCATION", "")).strip()
            url = str(component.get("URL", SOURCE_URL)).strip() or SOURCE_URL

            start_dt = _to_iso(component.get("DTSTART"))
            end_dt = _to_iso(component.get("DTEND"))

            records.append(
                {
                    "uid": uid,
                    "url": url,
                    "title": title,
                    "slug": make_slug(title),
                    "description": description,
                    "start_dt": start_dt,
                    "end_dt": end_dt,
                    "location": location,
                    "record_type": "event",
                    "source_label": "Spearfish School District",
                }
            )

        return records

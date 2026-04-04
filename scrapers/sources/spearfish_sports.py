"""
scrapers/sources/spearfish_sports.py

Spearfish school sports schedules via gobound.com iCal feeds.
https://www.gobound.com/sd/schools/spearfish/calendar
https://www.gobound.com/sd/schools/spearfishmiddleschool/calendar

Public iCal endpoints — no auth required. Non-sport events (those with no
X-BND-ACTIVITYNAME), practices, and cancelled events are skipped.
"""

import re
from datetime import datetime, timezone

import requests
from icalendar import Calendar

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

_PRACTICE_RE = re.compile(r"\bpractis?e\b", re.IGNORECASE)


def _to_iso(val) -> str:
    if val is None:
        return ""
    dt = getattr(val, "dt", val)
    if isinstance(dt, datetime):
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return dt.isoformat()
    return dt.isoformat() if hasattr(dt, "isoformat") else str(dt)


class GoBoundSportsScraper(BaseScraper):
    """Base class for gobound.com iCal sports feed scrapers."""

    dedup_key = "uid"
    ical_url: str = ""
    source_url: str = ""

    def scrape(self) -> list[dict]:
        resp = requests.get(self.ical_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        resp.raise_for_status()

        cal = Calendar.from_ical(resp.content)
        records = []

        for component in cal.walk():
            if component.name != "VEVENT":
                continue

            sport = str(component.get("X-BND-ACTIVITYNAME", "")).strip()
            if not sport:
                continue

            summary = str(component.get("SUMMARY", "")).strip()
            status = str(component.get("STATUS", "")).strip()

            if status.upper() == "CANCELLED":
                continue
            if _PRACTICE_RE.search(summary):
                continue

            uid = str(component.get("UID", ""))
            url = str(component.get("URL", self.source_url)).strip() or self.source_url

            records.append(
                {
                    "uid": uid,
                    "url": url,
                    "title": summary,
                    "slug": make_slug(summary),
                    "sport": sport,
                    "level": str(component.get("X-BND-ACTIVITYLEVEL", "")).strip(),
                    "sex": str(component.get("X-BND-ACTIVITYSEX", "")).strip(),
                    "description": str(component.get("DESCRIPTION", "")).strip(),
                    "start_dt": _to_iso(component.get("DTSTART")),
                    "end_dt": _to_iso(component.get("DTEND")),
                    "location": str(component.get("LOCATION", "")).strip(),
                    "status": status,
                    "record_type": "event",
                    "source_label": self.name,
                }
            )

        return records


class SpearfishSports(GoBoundSportsScraper):
    name = "Spearfish HS Sports"
    slug = "spearfish_sports"
    ical_url = "https://gobound.com/sd/schools/spearfish/calendar/ical"
    source_url = "https://www.gobound.com/sd/schools/spearfish/calendar"


class SpearfishMSSports(GoBoundSportsScraper):
    name = "Spearfish MS Sports"
    slug = "spearfish_ms_sports"
    ical_url = "https://gobound.com/sd/schools/spearfishmiddleschool/calendar/ical"
    source_url = "https://www.gobound.com/sd/schools/spearfishmiddleschool/calendar"

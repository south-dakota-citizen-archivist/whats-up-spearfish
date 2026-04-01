"""
scrapers/sources/bhsu_calendar.py

Black Hills State University campus calendar.
https://bhsu.edu/campus-calendar.html

Backed by the Modern Campus Calendar API (no auth required).
Fetches the next 90 days of events from the Campus Calendar/Events category.
"""

from datetime import date, timedelta

import requests

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

CAL_ID = "45f13336-bc31-4b8d-8763-0d86ccd5c5ff"
CAT_ID = "ab35cb3f-8116-45c8-bfd0-dff0f9666880"
API_BASE = f"https://api.calendar.moderncampus.net/pubcalendar/{CAL_ID}"
SOURCE_URL = "https://bhsu.edu/campus-calendar.html"
LOOKAHEAD_DAYS = 90


class BHSUCalendar(BaseScraper):
    name = "BHSU Campus Calendar"
    slug = "bhsu_calendar"
    dedup_key = "event_id"

    def scrape(self) -> list[dict]:
        today = date.today()
        params = {
            "start": today.isoformat(),
            "end": (today + timedelta(days=LOOKAHEAD_DAYS)).isoformat(),
            "category": CAT_ID,
        }
        resp = requests.get(
            f"{API_BASE}/events",
            params=params,
            timeout=30,
        )
        resp.raise_for_status()

        records = []
        for event in resp.json():
            start_dt = event.get("startDatetime") or event.get("startDate", "")
            end_dt = event.get("endDatetime") or event.get("endDate", "")
            location_parts = filter(None, [
                event.get("location", ""),
                event.get("locationRoom", ""),
            ])
            location = " ".join(location_parts).strip()

            records.append({
                "event_id": event["id"],
                "url": f"{SOURCE_URL}#event-details/{event['id']}",
                "title": event.get("title", ""),
                "slug": make_slug(event.get("title", "")),
                "description": event.get("descriptionText", ""),
                "start_dt": start_dt,
                "end_dt": end_dt,
                "location": location,
                "image_url": event.get("image", ""),
                "image_alt": event.get("imageAltText", ""),
                "organizer": event.get("organizer", ""),
                "tags": event.get("tags", []),
                "featured": event.get("featured", False),
                "ticket_url": event.get("ticketUrl", ""),
                "category": event.get("categoryName", ""),
                "record_type": "event",
                "source_label": "BHSU Campus Calendar",
            })

        return records

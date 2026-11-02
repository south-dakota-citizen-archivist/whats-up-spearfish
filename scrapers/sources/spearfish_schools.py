"""
scrapers/sources/spearfish_schools.py

Spearfish School District calendar (https://www.spearfish.k12.sd.us/events).

The district site (Apptegy) puts a bot check in front of its pages, but the
page itself loads events from Apptegy's public Thrillshare API, which we call
directly. 32630 is the district's organization id.
"""

from __future__ import annotations

from datetime import timedelta

from scrapers import dates, net
from scrapers.base import BaseScraper

API_URL = "https://thrillshare-cmsv2.services.thrillshare.com/api/v4/o/32630/cms/events"
EVENTS_URL = "https://www.spearfish.k12.sd.us/events"
DAYS_AHEAD = 120


def parse_event(e: dict) -> dict | None:
    title = (e.get("title") or "").strip()
    if not title or not e.get("start_at"):
        return None
    location = ", ".join(x for x in (e.get("venue"), e.get("address"), e.get("city_state")) if x)
    all_day = bool(e.get("all_day"))
    return {
        "event_id": e.get("id"),
        "title": title,
        "url": EVENTS_URL,
        "start_dt": e["start_at"][:10] if all_day else e["start_at"],
        "end_dt": (e.get("end_at") or "")[:10] if all_day else e.get("end_at") or "",
        "all_day": all_day,
        "location": location,
        "description": e.get("description") or "",
    }


class SpearfishSchools(BaseScraper):
    name = "Spearfish School District"
    slug = "spearfish_schools"
    url = EVENTS_URL
    kind = "event"
    category = "schools"
    dedup_key = "event_id"
    min_records = 0  # summer can be empty

    def scrape(self) -> list[dict]:
        today = dates.today()
        params = {
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=DAYS_AHEAD)).isoformat(),
            "paginate": "false",
            "locale": "en",
        }
        resp = net.get(API_URL, params=params)
        resp.raise_for_status()
        return [r for r in map(parse_event, resp.json().get("events") or []) if r]

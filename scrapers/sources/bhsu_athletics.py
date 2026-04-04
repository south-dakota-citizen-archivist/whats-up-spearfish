"""
scrapers/sources/bhsu_athletics.py

BHSU Yellow Jackets athletics schedule.
https://bhsuathletics.com/calendar

Sidearm Sports platform. Uses the adaptive_components.ashx JSON endpoint
with type=events, sport_id=0 (all sports), and a 90-day lookahead window.
"""

from datetime import date, timedelta

import requests

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

API_URL = "https://bhsuathletics.com/services/adaptive_components.ashx"
SOURCE_URL = "https://bhsuathletics.com/calendar"
LOOKAHEAD_DAYS = 90


class BHSUAthletics(BaseScraper):
    name = "BHSU Athletics"
    slug = "bhsu_athletics"
    dedup_key = "game_id"

    def scrape(self) -> list[dict]:
        today = date.today()
        resp = requests.get(
            API_URL,
            params={
                "type": "events",
                "sport_id": 0,
                "start": today.isoformat(),
                "end": (today + timedelta(days=LOOKAHEAD_DAYS)).isoformat(),
                "count": 500,
                "name": "schedule-calendar",
            },
            headers={
                "User-Agent": "Mozilla/5.0",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": SOURCE_URL,
            },
            timeout=30,
        )
        resp.raise_for_status()
        events = resp.json() or []

        records = []
        for event in events:
            sport = event.get("sport") or {}
            opponent = event.get("opponent") or {}
            schedule = event.get("schedule") or {}
            media = event.get("media") or {}
            facility = event.get("game_facility") or {}

            sport_title = sport.get("title", "")
            opponent_name = opponent.get("name", "")
            home_away = event.get("location_indicator", "")  # H/A/N

            # Build a readable title: "Softball vs MSU Denver" or "at Colorado Mines"
            show_at_vs = sport.get("show_at_vs", True)
            if show_at_vs and opponent_name:
                prefix = "vs" if home_away == "H" else ("at" if home_away == "A" else "vs")
                title = f"{sport_title} {prefix} {opponent_name}"
            else:
                title = f"{sport_title}: {opponent_name}" if opponent_name else sport_title

            tournament = event.get("tournament")
            if tournament:
                title = f"{title} ({tournament})"

            start_dt = event.get("date_utc") or event.get("date", "")
            location = event.get("location", "")
            if facility.get("title"):
                location = facility["title"] + (f", {location}" if location else "")

            records.append(
                {
                    "game_id": event["id"],
                    "url": schedule.get("url") or SOURCE_URL,
                    "title": title,
                    "slug": make_slug(title),
                    "sport": sport_title,
                    "sport_shortname": sport.get("shortname", ""),
                    "opponent": opponent_name,
                    "home_away": home_away,
                    "is_conference": event.get("is_conference", False),
                    "start_dt": start_dt,
                    "time": event.get("time", ""),
                    "tbd": event.get("tbd", False),
                    "location": location,
                    "conference": event.get("conference", ""),
                    "status": event.get("status", ""),
                    "video_url": media.get("video", ""),
                    "stats_url": media.get("stats", ""),
                    "tickets_url": media.get("tickets", ""),
                    "result_team": (event.get("result") or {}).get("team_score"),
                    "result_opp": (event.get("result") or {}).get("opponent_score"),
                    "record_type": "event",
                    "source_label": "BHSU Athletics",
                }
            )

        return records

"""
scrapers/sources/spearfish_sasquatch.py

Spearfish Sasquatch home game schedule from local JSON data files (the
schedule and the theme nights are maintained by hand each season).
Only home (and exhibition) games at Black Hills Energy Stadium are emitted.
Fireworks nights get a 🎆 emoji appended to the title.
"""

from __future__ import annotations

import json
from pathlib import Path

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

_DATA_FILE = Path(__file__).parent / "spearfish_sasquatch_2026.json"
_THEMES_FILE = Path(__file__).parent / "spearfish_sasquatch_2026_themes.json"
SOURCE_URL = "https://www.spearfishsasquatch.com"


class SpearfishSasquatch(BaseScraper):
    name = "Spearfish Sasquatch"
    slug = "spearfish_sasquatch"
    kind = "event"
    category = "sports"
    url = SOURCE_URL
    dedup_key = "slug"
    max_stale_hours = 24 * 30

    def scrape(self) -> list[dict]:
        data = json.loads(_DATA_FILE.read_text())
        venue = data["venue"]
        location = f"{venue['name']}, {venue['city']}, {venue['state']}"
        themes = {}
        if _THEMES_FILE.exists():
            for night in json.loads(_THEMES_FILE.read_text()).get("theme_nights") or []:
                if night.get("date") and night.get("theme"):
                    themes[night["date"]] = night["theme"]
        records = []

        for game in data["schedule"]:
            if game["type"] not in ("home", "exhibition"):
                continue

            date_str = game["date"]
            opponent = game.get("opponent", "")
            special = game.get("special", "")
            start_time = game.get("start_time", "")

            fireworks = special == "fireworks_night"
            kids_day = special == "kids_day"
            title = f"Sasquatch vs. {opponent}"
            if fireworks:
                title += " 🎆"
            if kids_day:
                title += " 🧒"

            if theme := themes.get(date_str):
                title += f" — {theme}"

            # Build ISO datetime string with explicit MT offset so build.py
            # doesn't misinterpret it as UTC. MDT = -06:00, MST = -07:00.
            start_dt = date_str
            if start_time:
                time_clean = start_time.replace(" MDT", "").replace(" MST", "").strip()
                offset = "-07:00" if "MST" in start_time else "-06:00"
                start_dt = f"{date_str} {time_clean}{offset}"

            records.append(
                {
                    "url": SOURCE_URL,
                    "title": title,
                    "slug": make_slug(f"sasquatch-{date_str}"),
                    "start_dt": start_dt,
                    "location": location,
                    "opponent": opponent,
                    "game_type": game["type"],
                    "special": special,
                    "fireworks": fireworks,
                    "theme": themes.get(date_str, ""),
                    "description": "Fireworks after the game" if fireworks else "",
                    "record_type": "event",
                    "source_label": self.name,
                }
            )

        return records

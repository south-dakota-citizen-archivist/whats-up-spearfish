"""
scrapers/sources/bhnf.py

Black Hills National Forest — press releases and events.
https://www.fs.usda.gov/r02/blackhills/newsroom/releases
https://www.fs.usda.gov/r02/blackhills/events
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

BASE_URL = "https://www.fs.usda.gov"
RELEASES_URL = f"{BASE_URL}/r02/blackhills/newsroom/releases"
EVENTS_URL = f"{BASE_URL}/r02/blackhills/events"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_DATE_PREFIX_RE = re.compile(r"^Release Date:\s*", re.IGNORECASE)
_WS_RE = re.compile(r"\s+")


def _get(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=_HEADERS, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _scrape_releases() -> list[dict]:
    soup = _get(RELEASES_URL)
    records = []
    for row in soup.select(".views-row .wfs-news-release__teaser"):
        a = row.select_one("h3 a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "")
        url = BASE_URL + href if href.startswith("/") else href

        date_el = row.select_one(".news-release__publish")
        date_raw = date_el.get_text(strip=True) if date_el else ""
        date_raw = _DATE_PREFIX_RE.sub("", date_raw).strip()
        published = ""
        if date_raw:
            try:
                published = dateutil_parser.parse(date_raw).date().isoformat()
            except (ValueError, OverflowError):
                published = date_raw

        desc_el = row.select_one(".news-release__summary")
        description = _WS_RE.sub(" ", desc_el.get_text(" ", strip=True)).strip() if desc_el else ""

        records.append({
            "url": url,
            "title": title,
            "slug": make_slug(f"bhnf-release-{title}"),
            "published": published,
            "description": description,
            "record_type": "press_release",
            "source_label": "Black Hills National Forest",
        })
    return records


def _scrape_events() -> list[dict]:
    soup = _get(EVENTS_URL)
    records = []
    for card in soup.select(".wfs-event__teaser"):
        a = card.select_one("h3 a")
        if not a:
            continue
        title = a.get_text(strip=True)
        href = a.get("href", "")
        url = BASE_URL + href if href.startswith("/") else href

        # Dates field: "Dates: April 24 - 26, 2026" or "Date: April 24, 2026"
        start_dt = ""
        body_text = card.get_text(" ", strip=True)
        dates_m = re.search(r"Dates?:\s*(.+?)(?:\s+(?:Times?:|Contact|$))", body_text)
        if dates_m:
            date_str = dates_m.group(1).strip()
            # Take the first date for start_dt
            first_date = re.split(r"\s*[-–]\s*", date_str)[0].strip()
            try:
                start_dt = dateutil_parser.parse(first_date, fuzzy=True).date().isoformat()
            except (ValueError, OverflowError):
                pass

        desc_el = card.select_one(".usa-card__body")
        description = _WS_RE.sub(" ", desc_el.get_text(" ", strip=True)).strip() if desc_el else ""

        records.append({
            "url": url,
            "title": title,
            "slug": make_slug(f"bhnf-event-{title}"),
            "start_dt": start_dt,
            "location": "Black Hills National Forest",
            "description": description,
            "record_type": "event",
            "source_label": "Black Hills National Forest",
        })
    return records


class BHNF(BaseScraper):
    name = "Black Hills National Forest"
    slug = "bhnf"
    dedup_key = "slug"

    def scrape(self) -> list[dict]:
        records = []
        releases = _scrape_releases()
        print(f"  releases: {len(releases)}")
        records.extend(releases)
        events = _scrape_events()
        print(f"  events: {len(events)}")
        records.extend(events)
        return records

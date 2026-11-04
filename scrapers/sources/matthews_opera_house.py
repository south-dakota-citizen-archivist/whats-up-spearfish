"""
scrapers/sources/matthews_opera_house.py

Matthews Opera House & Arts Center — events.
https://www.matthewsopera.com/events/

Read from the site's events calendar API (The Events Calendar's REST endpoint),
which lists upcoming events a page at a time. The event list pages themselves
now sit behind a bot check that turns the scraper away.
"""

from __future__ import annotations

import html
import re

from scrapers import dates, net
from scrapers.base import BaseScraper
from scrapers.utils import make_slug

BASE_URL = "https://www.matthewsopera.com"
API_URL = f"{BASE_URL}/wp-json/tribe/events/v1/events"

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    """Unescape HTML entities, strip tags, collapse whitespace."""
    text = _TAG_RE.sub(" ", text or "")
    return _WHITESPACE_RE.sub(" ", html.unescape(text)).strip()


def _local(value: str) -> str:
    """'2026-11-06 19:00:00' (the venue's own clock) → '2026-11-06T19:00:00'."""
    return (value or "").strip().replace(" ", "T")


def _short(text: str, limit: int = 600) -> str:
    """Up to `limit` characters, cut at a word; stray marks at the start dropped."""
    text = re.sub(r"^[^\w\"'“(]+", "", text)
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:") + "…"


def parse_event(item: dict) -> dict | None:
    """One event from the API → a scraper record."""
    if item.get("status", "publish") != "publish":
        return None
    title = _strip_html(item.get("title", ""))
    url = (item.get("url") or "").strip()
    if not title or not url or re.search(r"\b(cancel+ed|postponed)\b", title, re.I):
        return None
    all_day = bool(item.get("all_day"))
    start, end = _local(item.get("start_date", "")), _local(item.get("end_date", ""))
    if all_day:
        start, end = start[:10], end[:10]
    image = item.get("image") or {}
    venue = item.get("venue") or {}
    return {
        "title": title,
        "url": url,
        "slug": make_slug(title),
        "start_dt": start,
        "end_dt": end if end != start else "",
        "all_day": all_day,
        "description": _short(_strip_html(item.get("excerpt") or item.get("description", ""))),
        "location": _strip_html(venue.get("venue", "")) if isinstance(venue, dict) else "",
        "image_url": image.get("url", "") if isinstance(image, dict) else "",
        "cost": _strip_html(item.get("cost", "")),
        "record_type": "event",
        "source_label": "Matthews Opera House",
    }


def fetch_events(max_pages: int = 10) -> list[dict]:
    records = []
    for page in range(1, max_pages + 1):
        resp = net.get(API_URL, params={"per_page": 50, "page": page})
        if resp.status_code in (400, 404) and page > 1:
            break  # past the last page
        resp.raise_for_status()
        data = resp.json()
        records.extend(r for r in map(parse_event, data.get("events", [])) if r)
        if page >= int(data.get("total_pages") or 1):
            break
    return records


class MatthewsOperaHouse(BaseScraper):
    name = "Matthews Opera House"
    slug = "matthews_opera_house"
    kind = "event"
    url = "https://www.matthewsopera.com/events/"
    category = "arts"
    dedup_key = "url"
    naive_tz = dates.MT

    def scrape(self) -> list[dict]:
        return fetch_events()

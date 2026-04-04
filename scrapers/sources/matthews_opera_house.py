"""
scrapers/sources/matthews_opera_house.py

Matthews Opera House & Arts Center — events.
https://www.matthewsopera.com/events/

Event details are embedded as a JSON-LD array
(<script type="application/ld+json">) on each page of the event list.
Paginates through /events/list/page/N/ until no events are found.
"""

from __future__ import annotations

import html
import json
import re

from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

BASE_URL = "https://www.matthewsopera.com"
LIST_URL = f"{BASE_URL}/events/list/"

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    """Unescape HTML entities, strip tags, collapse whitespace."""
    text = html.unescape(text)
    text = _TAG_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


def _extract_events(page_html: str) -> list[dict]:
    """Return the Event ld+json array from a page, or []."""
    blocks = re.findall(
        r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        page_html,
        re.DOTALL | re.IGNORECASE,
    )
    for block in blocks:
        try:
            parsed = json.loads(block.strip())
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, list) and parsed and parsed[0].get("@type") == "Event":
            return parsed
    return []


def _parse_event(item: dict) -> dict | None:
    """Map a schema.org Event dict to a scraper record."""
    # Skip cancelled events
    if "EventCancelled" in item.get("eventStatus", ""):
        return None

    title = _strip_html(item.get("name", ""))
    if not title:
        return None

    url = item.get("url", "").strip()
    if not url:
        return None

    start_dt = item.get("startDate", "")
    end_dt = item.get("endDate", "")

    description = _strip_html(item.get("description", ""))

    location = ""
    loc = item.get("location", {})
    if isinstance(loc, dict):
        location = _strip_html(loc.get("name", ""))

    image_url = item.get("image", "")
    if isinstance(image_url, dict):
        image_url = image_url.get("url", "")

    return {
        "title": title,
        "url": url,
        "slug": make_slug(title),
        "start_dt": start_dt,
        "end_dt": end_dt,
        "description": description,
        "location": location,
        "image_url": image_url,
        "record_type": "event",
        "source_label": "Matthews Opera House",
    }


def _fetch_all_events() -> list[dict]:
    records = []
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True)
        page_obj = browser.new_page()
        page_num = 1
        while True:
            url = LIST_URL if page_num == 1 else f"{LIST_URL}page/{page_num}/"
            try:
                page_obj.goto(url, wait_until="domcontentloaded", timeout=30000)
                html_content = page_obj.content()
            except Exception as exc:
                print(f"[MatthewsOperaHouse] Warning: page {page_num} failed: {exc}")
                break

            items = _extract_events(html_content)
            if not items:
                break

            for item in items:
                record = _parse_event(item)
                if record:
                    records.append(record)

            page_num += 1

        browser.close()
    return records


class MatthewsOperaHouse(BaseScraper):
    name = "Matthews Opera House"
    slug = "matthews_opera_house"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        return _fetch_all_events()

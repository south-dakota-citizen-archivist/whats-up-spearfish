"""
scrapers/sources/spearfish_chamber.py

Spearfish Chamber of Commerce events calendar.
https://business.spearfishchamber.org/events/calendar/

Monthly calendar pages contain day cells with links to event detail pages.
We fetch the current month + next month, collect all detail URLs, then fetch
each detail page to extract time, location, description, and fees.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

BASE_URL = "https://business.spearfishchamber.org"
CALENDAR_URL = f"{BASE_URL}/events/calendar"
_HEADERS = {"User-Agent": "Mozilla/5.0"}

_TIME_SEP_RE = re.compile(r"\s*[-–]\s*")


def _get_soup(url: str) -> BeautifulSoup:
    resp = requests.get(url, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _collect_month_events(year: int, month: int) -> list[tuple[str, str, str]]:
    """Return list of (date_str, detail_url, link_title) from one month's calendar page."""
    url = f"{CALENDAR_URL}/{year:04d}-{month:02d}-01"
    soup = _get_soup(url)
    results: list[tuple[str, str, str]] = []

    for cell in soup.select("td.gz-cal-days"):
        day_div = cell.select_one("div.gz-cal-day")
        if not day_div:
            continue

        # Extract date from the day number link: href="/events/index/YYYY-MM-DD"
        day_link = day_div.select_one("a[href]")
        if not day_link:
            continue
        href = day_link["href"]
        m = re.search(r"/events/index/(\d{4}-\d{2}-\d{2})", href)
        if not m:
            continue
        date_str = m.group(1)

        for event_link in cell.select("li.gz-cal-event a[href]"):
            detail_href = event_link["href"]
            if not detail_href.startswith("http"):
                detail_href = BASE_URL + detail_href
            # Strip calendarMonth query param so URL is stable for dedup
            detail_href = detail_href.split("?")[0]
            link_title = event_link.get_text(strip=True)
            results.append((date_str, detail_href, link_title))

    return results


def _parse_detail(date_str: str, url: str, link_title: str = "") -> dict | None:
    """Fetch and parse one event detail page; return normalized dict or None."""
    try:
        soup = _get_soup(url)
    except Exception:
        return None

    title_el = soup.select_one(".gz-pagetitle")
    title = title_el.get_text(strip=True) if title_el else link_title
    if not title:
        return None

    # Time range — e.g. "8:30 AM - 10:00 AM MDT"
    time_el = soup.select_one(".gz-details-time")
    time_str = time_el.get_text(" ", strip=True) if time_el else ""

    # Build ISO start_dt by combining the calendar date with start time
    start_dt = date_str
    end_time_str = ""
    if time_str:
        # Capture trailing timezone label (e.g. "MDT", "MST") before splitting
        tz_match = re.search(r"\s+([A-Z]{2,4})$", time_str)
        tz_suffix = f" {tz_match.group(1)}" if tz_match else ""
        clean = re.sub(r"\s+[A-Z]{2,4}$", "", time_str)
        parts = _TIME_SEP_RE.split(clean)
        start_dt = f"{date_str} {parts[0].strip()}{tz_suffix}" if parts[0].strip() else date_str
        if len(parts) > 1:
            end_time_str = f"{date_str} {parts[1].strip()}{tz_suffix}"

    location_el = soup.select_one(".gz-event-location p")
    location = location_el.get_text(" ", strip=True) if location_el else ""

    fees_el = soup.select_one(".gz-event-fees p")
    fees = fees_el.get_text(" ", strip=True) if fees_el else ""

    desc_el = soup.select_one(".gz-event-description p, .gz-event-description .col")
    description = desc_el.get_text(" ", strip=True) if desc_el else ""
    # Strip leading "Description" label if present
    if description.startswith("Description"):
        description = description[len("Description") :].strip()

    website_el = soup.select_one(".gz-event-website a[href]")
    website = website_el["href"] if website_el else ""

    return {
        "url": url,
        "title": title,
        "slug": make_slug(title),
        "start_dt": start_dt,
        "end_dt": end_time_str,
        "location": location,
        "fees": fees,
        "description": description,
        "website": website,
        "record_type": "event",
        "source_label": "Spearfish Chamber",
    }


class SpearfishChamber(BaseScraper):
    name = "Spearfish Chamber"
    slug = "spearfish_chamber"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        today = date.today()
        next_month = (today.replace(day=1) + timedelta(days=32)).replace(day=1)
        months = [(today.year, today.month), (next_month.year, next_month.month)]

        seen: set[str] = set()
        candidates: list[tuple[str, str, str]] = []
        for year, month in months:
            for date_str, url, link_title in _collect_month_events(year, month):
                if url not in seen:
                    seen.add(url)
                    candidates.append((date_str, url, link_title))

        records = []
        for date_str, url, link_title in candidates:
            record = _parse_detail(date_str, url, link_title)
            if record:
                records.append(record)

        return records

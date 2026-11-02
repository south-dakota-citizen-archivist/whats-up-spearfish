"""
scrapers/sources/lawrence_county.py

Lawrence County, SD — meeting agendas, packets and minutes posted to the
CivicEngage Agenda Center, via its RSS feed. The feed's titles carry the
meeting date ("October 27, 2026 ~ County Commission ..."), which is used as
the document date; the post date is the fallback.
"""

from __future__ import annotations

import re

from scrapers.base import BaseScraper
from scrapers.utils import fetch_feed

FEED_URL = "https://www.lawrence.sd.us/RSSFeed.aspx?ModID=65&CID=All-0"

_DATE_RE = re.compile(
    r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}"
)
# Boilerplate the county appends to titles
_TAIL_RE = re.compile(r"\s+(Please follow|All applications|Questions\?).*$", re.S)


def parse_entry(entry: dict) -> dict:
    raw_title = re.sub(r"\s+", " ", entry.get("title", "")).strip()
    title = _TAIL_RE.sub("", raw_title).rstrip(" .")
    m = _DATE_RE.search(raw_title)
    return {
        "url": entry.get("link", ""),
        "title": title,
        "meeting_date": m.group(0) if m else "",
        "published": entry.get("published", ""),
        "updated_note": "minutes" if "Minutes added" in entry.get("summary", "") else "",
        "record_type": "document",
        "source_label": "Lawrence County",
    }


class LawrenceCounty(BaseScraper):
    name = "Lawrence County Agenda Center"
    slug = "lawrence_county"
    kind = "document"
    url = "https://www.lawrence.sd.us/AgendaCenter"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        feed = fetch_feed(FEED_URL)
        return [parse_entry(e) for e in feed.entries]

"""
scrapers/sources/lawrence_county.py

Lawrence County, SD — meeting agendas, packets and minutes posted to the
CivicEngage Agenda Center, via its RSS feed. The feed's titles carry the
meeting date ("October 27, 2026 ~ County Commission ..."), which is used as
the document date; the post date is the fallback.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from scrapers import dates
from scrapers.base import BaseScraper
from scrapers.utils import agenda_details, fetch_feed

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
        records = [parse_entry(e) for e in feed.entries]
        saved = {r.get("url"): r for r in self.load_existing() if "dial_in" in r}
        add_agenda_details(records, saved)
        return records


def agenda_pdf_url(rec: dict) -> str:
    """The agenda file behind an Agenda Center entry: …/PreviousVersions/1361 of November 5, 2026 →
    …/ViewFile/Agenda/_11052026-1361."""
    m = re.search(r"/(\d+)$", rec.get("url", ""))
    try:
        day = datetime.strptime(rec.get("meeting_date", ""), "%B %d, %Y")
    except ValueError:
        return ""
    return f"https://www.lawrence.sd.us/AgendaCenter/ViewFile/Agenda/_{day:%m%d%Y}-{m.group(1)}" if m else ""


def add_agenda_details(records: list[dict], saved: dict) -> None:
    """Start time and online join link for meetings from yesterday on, read from their agendas (once each)."""
    since = dates.today() - timedelta(days=1)
    for rec in records:
        try:
            day = datetime.strptime(rec.get("meeting_date", ""), "%B %d, %Y").date()
        except ValueError:
            continue
        if day < since:
            continue
        if before := saved.get(rec["url"]):
            found = {k: before.get(k, "") for k in ("start_time", "join_url", "dial_in")}
        else:
            found = agenda_details(url) if (url := agenda_pdf_url(rec)) else {}
        rec["start_time"], rec["join_url"] = found.get("start_time", ""), found.get("join_url", "")
        rec["dial_in"] = found.get("dial_in") or {}

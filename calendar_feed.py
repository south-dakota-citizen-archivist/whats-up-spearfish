"""
calendar_feed.py

Generates two feeds from scraped data:

  _site/calendar.ics   — iCalendar feed of all records with a start_dt field
  _site/events.xml     — RSS 2.0 feed of all event records

Run after build.py so that _site/ already exists.
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import format_datetime
from pathlib import Path

from icalendar import Calendar
from icalendar import Event as ICalEvent

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUTPUT_DIR = ROOT / "_site"

print(OUTPUT_DIR)

SITE_URL = "https://south-dakota-citizen-archivist.github.io/whats-up-spearfish"  # update to match your Pages URL


# ---------------------------------------------------------------------------
# Data loading (mirrors build.py but self-contained)
# ---------------------------------------------------------------------------


def load_all_records() -> list[dict]:
    records: list[dict] = []
    for json_file in sorted(DATA_DIR.glob("*.json")):
        try:
            with json_file.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            if isinstance(data, list):
                slug = json_file.stem
                for r in data:
                    records.append({**r, "_source": slug})
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[calendar] Warning: could not read {json_file.name}: {exc}")
    return records


def _parse_dt(value: str | None) -> datetime | None:
    """Parse an ISO date/datetime string into an aware datetime (UTC)."""
    if not value:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# iCalendar (.ics)
# ---------------------------------------------------------------------------


def generate_ics(records: list[dict]) -> None:
    cal = Calendar()
    cal.add("prodid", "-//Spearfish Bulletin//spearfish-bulletin//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "Spearfish Bulletin Events")
    cal.add("x-wr-caldesc", "Local events aggregated by Spearfish Bulletin")

    count = 0
    for record in records:
        start_dt = _parse_dt(record.get("start_dt") or record.get("date"))
        if not start_dt:
            continue

        event = ICalEvent()
        event.add("summary", record.get("title", "(no title)"))
        event.add("dtstart", start_dt)

        end_dt = _parse_dt(record.get("end_dt"))
        if end_dt:
            event.add("dtend", end_dt)

        url = record.get("url", "")
        if url:
            event.add("url", url)

        description_parts = []
        if record.get("description"):
            description_parts.append(record["description"])
        if url:
            description_parts.append(f"Source: {url}")
        if description_parts:
            event.add("description", "\n\n".join(description_parts))

        if record.get("location"):
            event.add("location", record["location"])

        if record.get("lat") and record.get("lon"):
            event.add("geo", (float(record["lat"]), float(record["lon"])))

        # Stable UID: prefer an id field, otherwise derive from url.
        uid_base = record.get("id") or url or record.get("title", "unknown")
        event.add("uid", f"{uid_base}@spearfish-bulletin")

        cal.add_component(event)
        count += 1

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    ics_path = OUTPUT_DIR / "calendar.ics"
    ics_path.write_bytes(cal.to_ical())
    print(f"[calendar] Wrote {ics_path.relative_to(ROOT)} ({count} event(s))")


# ---------------------------------------------------------------------------
# RSS 2.0 feed (events.xml)
# ---------------------------------------------------------------------------


def generate_rss(records: list[dict]) -> None:
    # Filter to event-like records only.
    events = [r for r in records if r.get("record_type") == "event" or r.get("start_dt")]
    events.sort(
        key=lambda r: r.get("start_dt") or r.get("date") or "",
        reverse=True,
    )

    rss = ET.Element("rss", version="2.0")
    rss.set("xmlns:atom", "http://www.w3.org/2005/Atom")

    channel = ET.SubElement(rss, "channel")

    _text(channel, "title", "Spearfish Bulletin — Events")
    _text(channel, "link", SITE_URL)
    _text(channel, "description", "Upcoming local events aggregated by Spearfish Bulletin")
    _text(channel, "language", "en-us")
    _text(channel, "lastBuildDate", format_datetime(datetime.now(tz=timezone.utc)))

    atom_link = ET.SubElement(channel, "atom:link")
    atom_link.set("href", f"{SITE_URL}/feed.xml")
    atom_link.set("rel", "self")
    atom_link.set("type", "application/rss+xml")

    for record in events[:100]:  # cap at 100 items
        item = ET.SubElement(channel, "item")

        title = record.get("title", "(no title)")
        _text(item, "title", title)

        url = record.get("url", "") or SITE_URL
        _text(item, "link", url)
        # Use source URL as GUID (isPermaLink=false if it's the site root fallback)
        guid_el = ET.SubElement(item, "guid")
        guid_el.text = url
        if url == SITE_URL:
            guid_el.set("isPermaLink", "false")

        description_parts = []
        if record.get("start_dt") or record.get("date"):
            dt_val = record.get("start_dt") or record.get("date")
            description_parts.append(f"<strong>Date:</strong> {dt_val}")
        if record.get("location"):
            description_parts.append(f"<strong>Location:</strong> {record['location']}")
        if record.get("description"):
            description_parts.append(record["description"])
        if url:
            description_parts.append(f'<a href="{url}">Source</a>')
        _text(item, "description", "<br>".join(description_parts))

        pub_dt = _parse_dt(record.get("start_dt") or record.get("date"))
        if pub_dt:
            _text(item, "pubDate", format_datetime(pub_dt))

        if record.get("_source"):
            _text(item, "category", record["_source"])

    tree = ET.ElementTree(rss)
    ET.indent(tree, space="  ")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    rss_path = OUTPUT_DIR / "feed.xml"
    with rss_path.open("w", encoding="utf-8") as fh:
        fh.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        tree.write(fh, encoding="unicode", xml_declaration=False)
    print(f"[calendar] Wrote {rss_path.relative_to(ROOT)} ({len(events)} item(s))")


def _text(parent: ET.Element, tag: str, text: str) -> ET.Element:
    el = ET.SubElement(parent, tag)
    el.text = text
    return el


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> None:
    records = load_all_records()
    generate_ics(records)
    generate_rss(records)


if __name__ == "__main__":
    main()

"""
sitegen/feeds.py

Machine-readable outputs of the unified calendar:
  events.json   — consumed by the /events/ page
  calendar.ics  — subscribe in any calendar app
  events.xml    — RSS of the next two weeks of events
"""

from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

from icalendar import Calendar, Event

from scrapers import dates


def write_json(events: list[dict], path: Path) -> None:
    path.write_text(json.dumps(events, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def write_ics(events: list[dict], path: Path, site_url: str) -> None:
    cal = Calendar()
    cal.add("prodid", "-//What's up, Spearfish?//EN")
    cal.add("version", "2.0")
    cal.add("x-wr-calname", "What's up, Spearfish?")
    cal.add("x-wr-timezone", "America/Denver")
    stamp = dates.now()
    for e in events:
        ev = Event()
        ev.add("uid", f"{e['id']}@whats-up-spearfish")
        ev.add("dtstamp", stamp)
        ev.add("summary", e["title"])
        start = dates.parse(e["start"])
        end = dates.parse(e["end"]) if e["end"] else None
        if e["all_day"]:
            start = start if not isinstance(start, datetime) else start.date()
            end = (end if isinstance(end, date) and not isinstance(end, datetime) else start) + timedelta(days=1)
        ev.add("dtstart", start)
        if end:
            ev.add("dtend", end)
        if e["location"]:
            ev.add("location", e["location"])
        desc = "\n\n".join(x for x in (e["description"], f"Source: {e['source_label']}") if x)
        ev.add("description", desc)
        ev.add("url", e["url"] or f"{site_url}/events/")
        cal.add_component(ev)
    path.write_bytes(cal.to_ical())


def write_rss(events: list[dict], path: Path, site_url: str, days: int = 14) -> None:
    cutoff = (dates.today() + timedelta(days=days)).isoformat()
    rss = ET.Element("rss", version="2.0")
    ch = ET.SubElement(rss, "channel")
    ET.SubElement(ch, "title").text = "What's up, Spearfish? — Events"
    ET.SubElement(ch, "link").text = f"{site_url}/events/"
    ET.SubElement(ch, "description").text = "Upcoming events in Spearfish and the Northern Black Hills"
    ET.SubElement(ch, "lastBuildDate").text = format_datetime(dates.now())
    for e in events:
        if e["date"] > cutoff:
            break
        item = ET.SubElement(ch, "item")
        when = dates.parse(e["start"])
        label = when.strftime("%a, %b %-d") + (f", {e['time']}" if e["time"] and not e["all_day"] else "")
        ET.SubElement(item, "title").text = f"{e['title']} ({label})"
        ET.SubElement(item, "link").text = e["url"] or f"{site_url}/events/"
        ET.SubElement(item, "guid", isPermaLink="false").text = e["id"]
        ET.SubElement(item, "description").text = " · ".join(
            x for x in (e["location"], e["source_label"], e["description"]) if x
        )
    ET.ElementTree(rss).write(path, encoding="utf-8", xml_declaration=True)

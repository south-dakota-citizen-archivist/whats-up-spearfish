"""
scrapers/schema.py

Record normalization, applied to every record before it is saved.

Each scraper keeps whatever source-specific fields it likes, but after
normalization every record also carries a predictable core:

    id            stable short hash (source slug + dedup key)
    source        scraper slug
    source_label  human-readable source name
    kind          record kind (see KINDS)
    title, url

plus kind-specific fields:

    event         start, end (ISO, Mountain Time), all_day, date (YYYY-MM-DD), event_category
    school_menu   date
    dated kinds   published (ISO), date (YYYY-MM-DD)

Records that can't satisfy their kind's requirements are dropped (and counted
in the run's health report) rather than reaching the site half-broken.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from scrapers import dates


@dataclass(frozen=True)
class Kind:
    #: Fields to look in (in order) for the record's primary date.
    date_fields: tuple[str, ...] = ()
    #: Merge-mode retention: drop records whose date is older than this many days.
    #: Events/menus are retained from (today - window_days) forward.
    window_days: int = 60
    #: Whether a record without a parseable date is invalid.
    date_required: bool = False


KINDS: dict[str, Kind] = {
    "event": Kind(("start_dt", "start", "date"), window_days=1, date_required=True),
    "school_menu": Kind(("start_dt", "date"), window_days=7, date_required=True),
    "news": Kind(("published", "date", "start_dt"), window_days=30),
    "press_release": Kind(("published", "date", "start_dt"), window_days=60),
    "document": Kind(("start_dt", "meeting_date", "published", "date"), window_days=90),
    "youtube_video": Kind(("published", "date"), window_days=120),
    "job": Kind(("published", "date"), window_days=60),
    "alert": Kind(("published", "date", "start_dt"), window_days=14),
    "bid": Kind(("closes_iso", "closes"), window_days=30),
    "permit": Kind(("date_submitted", "date_created"), window_days=365),
    # Kept indefinitely: the monthly reports are the only ongoing permit record (see building_permits.py)
    "building_permit": Kind(("issued", "date"), window_days=365 * 100),
    "planning_item": Kind(("meeting_date",), window_days=365 * 100),  # kept indefinitely
    "sighting": Kind(("observed_on",), window_days=14),
    "notice": Kind(("deadline_iso",), window_days=60),
    "project": Kind(),
    "case": Kind(),  # contested permit cases: the whole current list each time
    "spill": Kind(),
    "beer": Kind(),
    "flavor": Kind(),
    "library_book": Kind(),
    "adoptable": Kind(),
    "movie": Kind(),  # the theater's whole current list each time
}

DEFAULT_KIND = Kind()

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def kind_of(record: dict, default: str) -> str:
    return record.get("record_type") or default


def clean_text(value) -> str:
    if not value:
        return ""
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", str(value))).strip()


def stable_id(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def _first(record: dict, fields: tuple[str, ...]):
    for f in fields:
        if record.get(f):
            return record[f]
    return None


def record_date(record: dict, kind: str) -> date | None:
    """Primary Mountain Time date of an already-normalized record."""
    value = record.get("date") or record.get("start") or record.get("published")
    return dates.to_date(value) if value else None


def normalize(
    record: dict, *, kind: str, source: str, source_label: str, dedup_key: str, naive_tz, category: str = ""
) -> dict | None:
    """Return a normalized copy of *record*, or None if it's invalid for its kind."""
    rec = dict(record)
    spec = KINDS.get(kind, DEFAULT_KIND)

    rec["kind"] = kind
    rec.setdefault("record_type", kind)
    rec["source"] = source
    rec["source_label"] = rec.get("source_label") or source_label
    rec["title"] = clean_text(rec.get("title"))
    rec["url"] = (rec.get("url") or "").strip()
    rec["id"] = stable_id(source, rec.get(dedup_key, ""))

    if kind == "event":
        start = dates.parse(_first(rec, spec.date_fields), naive_tz)
        end = dates.parse(_first(rec, ("end_dt", "end")), naive_tz)
        if start is None or not rec["title"]:
            return None
        all_day = rec.get("all_day")
        if all_day is None:
            all_day = not isinstance(start, datetime)
        if isinstance(start, datetime) and all_day:
            start = start.date()
        if isinstance(end, datetime) and isinstance(start, date) and not isinstance(start, datetime):
            end = end.date()
        rec["start"] = dates.iso(start)
        rec["end"] = dates.iso(end) if end and end != start else ""
        rec["all_day"] = bool(all_day)
        rec["date"] = (start.date() if isinstance(start, datetime) else start).isoformat()
        rec["location"] = clean_text(rec.get("location"))
        rec["description"] = clean_text(rec.get("description"))
        rec["event_category"] = rec.get("event_category") or category or "community"
        return rec

    raw = _first(rec, spec.date_fields) if spec.date_fields else None
    parsed = dates.parse(raw, naive_tz) if raw else None
    if parsed is None and spec.date_required:
        return None
    if parsed is not None:
        rec["published"] = dates.iso(parsed)
        rec["date"] = (parsed.date() if isinstance(parsed, datetime) else parsed).isoformat()
    if not rec["title"] and kind not in ("sighting",):
        return None
    return rec


def is_expired(record: dict, kind: str, today: date, first_seen_cutoff: date) -> bool:
    """Merge-mode retention check for a normalized record."""
    spec = KINDS.get(kind, DEFAULT_KIND)
    d = record_date(record, kind)
    if kind in ("event", "school_menu"):
        if d is None:
            return True
        end = dates.to_date(record.get("end")) if record.get("end") else None
        return (end or d) < today - timedelta(days=spec.window_days)
    if d is not None:
        return d < today - timedelta(days=spec.window_days)
    seen = record.get("_first_seen")
    return bool(seen) and date.fromisoformat(seen[:10]) < first_seen_cutoff

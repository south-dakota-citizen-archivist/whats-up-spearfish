"""
sitegen/events.py

The unified events calendar: every event record from every source, upcoming
only, with cross-source duplicates merged (e.g. a city council meeting listed
on both the city calendar and the chamber calendar).
"""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta

from scrapers import dates
from sitegen.data import Site

HORIZON_DAYS = 180

#: When duplicates collide, the first source in this list wins (others are
#: kept as "also listed on" links). Sources not listed rank after these.
SOURCE_PRIORITY = [
    "bhsu_calendar",
    "bhsu_athletics",
    "spearfish_calendar",
    "spearfish_sasquatch",
    "spearfish_sports",
    "spearfish_ms_sports",
    "spearfish_schools",
    "spearfish_chamber",
]

CATEGORY_LABELS = {
    "community": "Community",
    "arts": "Arts & culture",
    "sasquatch": "Sasquatch baseball",
    "schools": "School calendar",
    "school sports": "School sports",
    "campus": "Campus events",
    "bhsu sports": "Yellow Jackets sports",
}

#: The event types by who they're for, as the events page groups its filters
CATEGORY_GROUPS = [
    ("Around town", ("community", "arts", "sasquatch")),
    ("Spearfish schools", ("schools", "school sports")),
    ("Black Hills State", ("campus", "bhsu sports")),
]

#: A source's events are this type, whatever it calls them ('sports' alone was BHSU's and the Sasquatch's)
SOURCE_CATEGORY = {
    "bhsu_athletics": "bhsu sports",
    "bhsu_calendar": "campus",
    "spearfish_sasquatch": "sasquatch",
    "spearfish_schools": "schools",
    "spearfish_sports": "school sports",
    "spearfish_ms_sports": "school sports",
}

_STOPWORDS = {"the", "a", "an", "of", "and", "at", "in", "for", "meeting", "spearfish", "city", "regular", "vs"}


def _tokens(title: str) -> frozenset[str]:
    words = re.findall(r"[a-z0-9]+", title.lower())
    return frozenset(w for w in words if w not in _STOPWORDS)


def _same(a: frozenset, b: frozenset) -> bool:
    if not a or not b:
        return False
    if a <= b or b <= a:
        return True
    return len(a & b) / len(a | b) >= 0.6


def _rank(slug: str) -> int:
    return SOURCE_PRIORITY.index(slug) if slug in SOURCE_PRIORITY else len(SOURCE_PRIORITY)


def time_label(start: str, end: str, all_day: bool) -> str:
    if all_day:
        return "All day"
    s = dates.parse(start)
    if not isinstance(s, datetime):
        return ""
    label = fmt_clock(s)
    e = dates.parse(end) if end else None
    if isinstance(e, datetime) and e.date() == s.date() and e > s:
        # "3–5 PM", but "11 AM–1:30 PM" when the range crosses noon
        start = label.removesuffix(s.strftime(" %p")) if s.strftime("%p") == e.strftime("%p") else label
        label = f"{start}–{fmt_clock(e)}"
    return label


def fmt_clock(dt: datetime) -> str:
    return dt.strftime("%-I %p" if dt.minute == 0 else "%-I:%M %p")


def _words(s: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", (s or "").lower()))


def undouble(text: str) -> str:
    """Drop a phrase repeated back to back, as some feeds join a venue and its room:
    'Lyman High School Lyman High School' → 'Lyman High School',
    'Student Union Student Union Lobby' → 'Student Union Lobby'. Single repeated words
    ('Walla Walla') are left alone."""
    words = (text or "").split()
    changed = True
    while changed:
        changed = False
        for n in range(len(words) // 2, 1, -1):
            for i in range(len(words) - 2 * n + 1):
                if [w.lower().strip(",") for w in words[i : i + n]] == [
                    w.lower().strip(",") for w in words[i + n : i + 2 * n]
                ]:
                    del words[i + n : i + 2 * n]
                    changed = True
                    break
            if changed:
                break
    return " ".join(words)


def tidy_description(title: str, description: str) -> str:
    """A description that only repeats the title says nothing; one that starts with it
    gets the repeat trimmed off."""
    desc = (description or "").strip()
    if not desc or _words(desc) == _words(title):
        return ""
    if title and desc.lower().startswith(title.strip().lower()):
        rest = desc[len(title.strip()) :].lstrip(" .,:;-–—")
        if rest and _words(rest) != _words(title):
            return rest[0].upper() + rest[1:]
    return desc


def home_tickets(r: dict) -> str:
    """Where to buy tickets to a game here in town (a home game, by the schedule's H/A/N), or ''."""
    return (r.get("tickets_url") or "") if r.get("home_away", "H") == "H" else ""


def unified_events(site: Site, today: date | None = None) -> list[dict]:
    today = today or dates.today()
    horizon = today + timedelta(days=HORIZON_DAYS)

    raw = []
    for r in site.records(kind="event"):
        d = date.fromisoformat(r["date"])
        end = dates.to_date(r["end"]) if r.get("end") else d
        if (end or d) < today or d > horizon:
            continue
        raw.append(r)

    # Bucket by start date + start minute ("all day" is its own slot), then merge
    # titles that look alike within a bucket.
    buckets: dict[tuple, list[dict]] = {}
    for r in sorted(raw, key=lambda r: _rank(r["source"])):
        slot = "all" if r.get("all_day") else r["start"][11:16]
        bucket = buckets.setdefault((r["date"], slot), [])
        toks = _tokens(r["title"])
        for kept in bucket:
            if kept["source"] != r["source"] and _same(kept["_tokens"], toks):
                kept["also"].append({"source": r["source_label"], "url": r["url"]})
                kept["tickets_url"] = kept["tickets_url"] or home_tickets(r)
                if not kept["location"] and r.get("location"):
                    kept["location"] = undouble(r["location"])
                break
        else:
            bucket.append(
                {
                    "id": r["id"],
                    "title": r["title"],
                    "start": r["start"],
                    "end": r.get("end", ""),
                    "all_day": bool(r.get("all_day")),
                    "date": r["date"],
                    "time": time_label(r["start"], r.get("end", ""), bool(r.get("all_day"))),
                    "location": undouble(r.get("location", "")),
                    "description": tidy_description(r["title"], r.get("description") or "")[:400],
                    "url": r["url"],
                    "tickets_url": home_tickets(r),
                    "category": SOURCE_CATEGORY.get(r["source"]) or r.get("event_category") or "community",
                    "source": r["source"],
                    "source_label": r["source_label"],
                    "also": [],
                    "_tokens": toks,
                }
            )

    events = [e for bucket in buckets.values() for e in bucket]
    for e in events:
        del e["_tokens"]
    # Multi-day events that started earlier sort as "today"
    events.sort(key=lambda e: (max(e["date"], today.isoformat()), not e["all_day"], e["start"], e["title"]))
    return events

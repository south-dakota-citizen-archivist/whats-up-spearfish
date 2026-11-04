"""
sitegen/pages.py

One context function per page. Each takes the loaded Site, the unified events
list and today's date, and returns the template variables for that page.
"""

from __future__ import annotations

import json
import random
import re
import statistics
from collections import Counter, defaultdict
from datetime import date, timedelta

from scrapers import geo
from sitegen import trends
from sitegen.data import Site, Source
from sitegen.events import CATEGORY_LABELS
from sitegen.parcels import BEACON, ParcelLinks, record_key
from sitegen.sources import DIRECTORY

# ── shared helpers ──────────────────────────────────────────────────────────

MENU_SOURCES = [
    # (slug, school level, meal)
    ("spearfish_elem_breakfast", "Elementary", "Breakfast"),
    ("spearfish_elem_k2_lunch", "Elementary K–2", "Lunch"),
    ("spearfish_elem_35_lunch", "Elementary 3–5", "Lunch"),
    ("spearfish_mshs_breakfast", "Middle & High School", "Breakfast"),
    ("spearfish_ms_lunch", "Middle School", "Lunch"),
    ("spearfish_hs_lunch", "High School", "Lunch"),
]

# The daily menu table: one row per school group, breakfast and lunch columns.
# Breakfast menus are shared (one for K–5, one for 6–12), so they span rows.
MENU_GRID = [
    ("Elementary K–2", "spearfish_elem_breakfast", "spearfish_elem_k2_lunch"),
    ("Elementary 3–5", "spearfish_elem_breakfast", "spearfish_elem_35_lunch"),
    ("Middle School", "spearfish_mshs_breakfast", "spearfish_ms_lunch"),
    ("High School", "spearfish_mshs_breakfast", "spearfish_hs_lunch"),
]

NEWS_SOURCES = [
    "black_hills_pioneer",
    "rapid_city_journal",
    "sdpb_news",
    "news_feeds",
    "sundance_times",
    "custer_county_chronicle",
]
PRESS_SOURCES = ["spearfish_news", "spearfish_school_news", "bhnf"]
JOB_SOURCES = ["spearfish_jobs", "lawrence_county_jobs", "spearfish_schools_jobs", "bhsu_jobs", "bhpioneer_jobs"]
TAP_SOURCES = [
    "crow_peak_brewing",
    "spearfish_brewing",
    "sawyer_brewing",
    "killians",
    "redwater_kitchen",
    "clubhouse_spearfish",
]


def newest(records: list[dict], key: str = "published") -> list[dict]:
    return sorted(records, key=lambda r: r.get(key) or r.get("date") or "", reverse=True)


def since(records: list[dict], days: int, today: date) -> list[dict]:
    cutoff = (today - timedelta(days=days)).isoformat()
    return [r for r in records if (r.get("date") or "") >= cutoff]


def sources_of(site: Site, slugs: list[str]) -> list[Source]:
    return [site.get(s) for s in slugs if site.get(s).enabled]


# ── page: home ──────────────────────────────────────────────────────────────


def menus_for_day(site: Site, day: str) -> list[dict]:
    out = []
    for slug, level, meal in MENU_SOURCES:
        rec = next((r for r in site.get(slug).records if r.get("date") == day), None)
        if not rec:
            continue
        items = rec.get("menu_items") or []
        entrees = [i["name"] for i in items if i.get("is_entree")]
        if not entrees and rec.get("title"):
            entrees = [rec["title"]]
        if any("no school" in e.lower() for e in entrees):
            continue
        out.append(
            {
                "key": f"{slug}|{day}",
                "slug": slug,
                "level": level,
                "meal": meal,
                "date": day,
                "entrees": entrees,
                "url": site.get(slug).url,
                "items": [_menu_item(i) for i in items],
            }
        )
    return merge_identical(out)


# Names for school groups whose menus are merged because they're the same that day
_MERGED_LEVELS = {
    frozenset({"Elementary K–2", "Elementary 3–5"}): "Elementary (K–5)",
    frozenset({"Middle School", "High School"}): "Middle & High School",
}


def merge_identical(menus: list[dict]) -> list[dict]:
    """
    One entry per distinct menu: when two school groups get exactly the same
    meal (every dish, not just the main ones), they share a single entry
    (e.g. "Middle & High School" lunch) instead of repeating it.
    """
    out: list[dict] = []
    seen: dict[tuple, dict] = {}
    for m in menus:
        sig = (m["meal"], tuple(i.get("name", "") for i in m["items"]) or tuple(m["entrees"]))
        if first := seen.get(sig):
            first["slugs"].append(m["slug"])
            first["levels"].append(m["level"])
            continue
        m = dict(m, slugs=[m["slug"]], levels=[m["level"]])
        seen[sig] = m
        out.append(m)
    for m in out:
        if len(m["levels"]) > 1:
            same_meal = [x for x in menus if x["meal"] == m["meal"]]
            if len(m["levels"]) == len(same_meal) and len(same_meal) > 2:
                m["level"] = "All schools"
            else:
                m["level"] = _MERGED_LEVELS.get(frozenset(m["levels"]), " & ".join(m["levels"]))
    return out


def _menu_item(i: dict) -> dict:
    keep = ("name", "category", "is_entree", "description", "ingredients", "image_url", "serving_size")
    item = {k: i.get(k) for k in keep if i.get(k)}
    for k in ("tags", "food_groups", "nutrition_facts"):
        if i.get(k):
            item[k] = i[k]
    # The menu system lists "No Allergens" / "Not Available" as if they were allergens
    allergens = i.get("allergens") or []
    real = [a for a in allergens if a.lower() not in ("no allergens", "not available")]
    if real:
        item["allergens"] = real
    elif any(a.lower() == "no allergens" for a in allergens):
        item["no_allergens"] = True
    return item


def menu_grid(menus: list[dict]) -> list[dict]:
    """
    Rows for the menu table. School groups whose breakfast and lunch are both
    the same that day share one row; a breakfast shared by consecutive rows is
    shown once with a rowspan (the rows it covers get breakfast_span 0).
    """
    by_slug = {slug: m for m in menus for slug in m.get("slugs", [m["slug"]])}
    rows: list[dict] = []
    for level, b, lunch in MENU_GRID:
        row = {"level": level, "breakfast": by_slug.get(b), "lunch": by_slug.get(lunch)}
        if not (row["breakfast"] or row["lunch"]):
            continue
        prev = rows[-1] if rows else None
        if prev and prev["breakfast"] is row["breakfast"] and prev["lunch"] is row["lunch"]:
            prev["levels"].append(level)
            continue
        rows.append({**row, "levels": [level]})
    for r in rows:
        r["level"] = _MERGED_LEVELS.get(frozenset(r["levels"]), " & ".join(r["levels"]))
    i = 0
    while i < len(rows):
        j = i
        while j + 1 < len(rows) and rows[j + 1]["breakfast"] is rows[i]["breakfast"]:
            j += 1
        rows[i]["breakfast_span"] = j - i + 1
        for k in range(i + 1, j + 1):
            rows[k]["breakfast_span"] = 0
        i = j + 1
    return rows


def menu_details(site: Site, today: date) -> dict:
    """Full menus (every dish, with photos, allergens and nutrition) keyed "slug|date", for the menu pop-up."""
    return {
        m["key"]: {k: m[k] for k in ("level", "meal", "date", "url", "items")}
        for d in menu_days(site, today, 10)
        for m in d["menus"]
    }


def menu_days(site: Site, today: date, count: int) -> list[dict]:
    all_days = sorted({r["date"] for slug, _, _ in MENU_SOURCES for r in site.get(slug).records if r.get("date")})
    days = []
    for d in all_days:
        if d < today.isoformat():
            continue
        menus = menus_for_day(site, d)
        if menus:
            days.append({"date": d, "menus": menus, "grid": menu_grid(menus)})
        if len(days) >= count:
            break
    return days


def creek_context(site: Site) -> dict:
    src = site.get("creek_gauge")
    data = src.data or {}
    current = data.get("current") or {}
    daily = data.get("daily30") or []
    series = data.get("series7d") or []
    median = statistics.median(d["cfs"] for d in daily) if daily else None
    return {
        "source": src,
        "current": current,
        "median30": round(median) if median is not None else None,
        "spark": sparkline([p["cfs"] for p in series], 240, 48),
        "daily": daily,
        "series": series,
    }


def sparkline(values: list[float], width: int, height: int) -> dict | None:
    """Polyline points for a simple inline SVG chart."""
    if len(values) < 2:
        return None
    lo, hi = min(values), max(values)
    # Keep at least ±10% around the midpoint so small wiggles don't look dramatic
    mid = (lo + hi) / 2
    floor_span = max(abs(mid) * 0.2, 1)
    if hi - lo < floor_span:
        lo, hi = mid - floor_span / 2, mid + floor_span / 2
    span = hi - lo
    pad = 4
    pts = []
    for i, v in enumerate(values):
        x = round(i / (len(values) - 1) * width, 1)
        y = round(pad + (1 - (v - lo) / span) * (height - 2 * pad), 1)
        pts.append(f"{x},{y}")
    return {
        "points": " ".join(pts),
        "width": width,
        "height": height,
        "min": round(min(values)),
        "max": round(max(values)),
    }


def fire_context(site: Site) -> dict:
    src = site.get("fire")
    data = src.data or {}
    danger = data.get("danger") or {}
    zones = danger.get("zones") or []
    # Spearfish sits in the NWS "Northern Foothills" rangeland zone
    local = next((z for z in zones if "Northern Foothills" in z["name"]), None)
    return {
        "source": src,
        "danger": danger,
        "local_danger": local,
        "incidents": data.get("incidents") or [],
    }


def board_doc_label(r: dict) -> str:
    """'Addendum' or 'Audio minutes' from the title when it says so; else the district's type ('Agenda')."""
    title = (r.get("title") or "").lower()
    if "addendum" in title:
        return "Addendum"
    if "audio" in title:
        return "Audio minutes" if "minutes" in title else "Audio"
    return (r.get("asset_type") or "Document").capitalize()


def meetings(site: Site) -> list[dict]:
    """Agendas/minutes from the city, county and school board, grouped into meetings."""
    out: dict[str, dict] = {}
    for r in site.get("spearfish_city").records:
        key = f"city-{r.get('event_id')}"
        m = out.setdefault(
            key,
            {
                "date": r.get("date", ""),
                "body": "City of Spearfish",
                "name": r.get("event_name") or r.get("category") or "Meeting",
                "url": r.get("portal_url") or r["url"],
                "video": r.get("media_url") or "",
                "docs": [],
            },
        )
        m["docs"].append({"label": r.get("doc_type") or "Document", "url": r.get("file_url") or r["url"]})
    for r in site.get("lawrence_county").records:
        out[f"county-{r['id']}"] = {
            "date": r.get("date", ""),
            "body": "Lawrence County",
            "name": r["title"],
            "url": r["url"],
            "video": "",
            "docs": [{"label": "Agenda & packet", "url": r["url"]}],
        }
    for r in site.get("spearfish_school_board_docs").records:
        if not r.get("date"):
            continue  # a document that names no meeting date can't be placed with its meeting
        key = f"school-{r.get('date')}"
        m = out.setdefault(
            key,
            {
                "date": r.get("date", ""),
                "body": "School Board",
                "name": "Board of Education",
                "url": r["url"],
                "video": "",
                "docs": [],
            },
        )
        m["docs"].append({"label": board_doc_label(r), "url": r["url"]})
    return sorted(out.values(), key=lambda m: m["date"])


def _interleave(groups: list[list]) -> list:
    """[a1, b1, c1, a2, b2, …]: one from each group in turn."""
    out = []
    for i in range(max((len(g) for g in groups), default=0)):
        out += [g[i] for g in groups if i < len(g)]
    return out


def recent_permit_count(site: Site, today: date) -> int:
    """Building permits in the city's latest monthly report, plus applications on
    Planning Commission agendas in the past 30 days: the front page's permits callout."""
    permits = site.get("building_permits").records
    latest = max((r.get("date", "") for r in permits), default="")
    cutoff = (today - timedelta(days=30)).isoformat()
    applications = [
        r
        for r in site.get("planning_commission").records
        if r.get("site") and (r.get("meeting_date") or "")[:10] >= cutoff
    ]
    return sum(1 for r in permits if latest and r.get("date") == latest) + len(applications)


def mixed_pets(pets: list[dict]) -> list[dict]:
    """Every pet, species taking turns (the shelter lists its many cats first), photos first."""
    by_species: dict[str, list] = defaultdict(list)
    for p in pets:
        by_species[(p.get("species") or "other").lower()].append(p)
    mixed = _interleave([v for _, v in sorted(by_species.items())])
    return sorted(mixed, key=lambda p: not p.get("image_url"))


def pet_tally(records: list[dict]) -> dict:
    """How many pets are up for adoption, by species: {'total': 50, 'kinds': '40 cats, 10 dogs'}."""
    plural = {"cat": "cats", "dog": "dogs", "rabbit": "rabbits", "puppy": "puppies", "kitten": "kittens"}
    by_kind = Counter((r.get("species") or "other").lower() for r in records)
    kinds = [f"{n} {k if n == 1 else plural.get(k, k + 's')}" for k, n in by_kind.most_common()]
    return {"total": len(records), "kinds": ", ".join(kinds) if len(kinds) > 1 else ""}


def pet_picks(site: Site, n: int, rng: random.Random) -> list[dict]:
    """Pets with photos, chosen at random with an even split between species (the
    shelter usually has far more cats than dogs), alternating so the row looks mixed."""
    by_species: dict[str, list] = defaultdict(list)
    for p in site.get("whhs_adoptable").records:
        if p.get("image_url"):
            by_species[(p.get("species") or "other").lower()].append(p)
    groups = [rng.sample(v, len(v)) for _, v in sorted(by_species.items())]
    # deal shares smallest group first, so a species short of its share leaves the rest to the others
    picked: dict[int, list] = {}
    left = n
    for i, g in sorted(enumerate(groups), key=lambda ig: len(ig[1])):
        share = left // (len(groups) - len(picked))
        picked[i] = g[:share]
        left -= len(picked[i])
    return _interleave([picked[i] for i in range(len(groups))])


def tap_picks(site: Site, n: int, rng: random.Random) -> list[dict]:
    """Beers with photos chosen at random, every venue that has photos represented (one
    each), then more to fill the row, in random order. Venues without photos (the
    Clubhouse posts none) are on the tap list page, not here: the front page shows no
    placeholders."""
    venues = []
    for src in sources_of(site, TAP_SOURCES):
        beers = [dict(b, venue=src.label, venue_slug=src.slug) for b in src.records if b.get("image_url")]
        if beers:
            venues.append(rng.sample(beers, len(beers)))
    if len(venues) > n:
        venues = rng.sample(venues, n)
    picks = [v[0] for v in venues]
    rest = [b for v in venues for b in v[1:]]
    picks += rng.sample(rest, min(len(rest), n - len(picks)))
    return rng.sample(picks, len(picks))


def book_picks(site: Site, n: int, rng: random.Random) -> list[dict]:
    """New books with a cover, chosen at random."""
    books = [b for b in site.get("spearfish_library").records if b.get("image_url")]
    return rng.sample(books, min(n, len(books)))


def menu_lists(menus: list[dict]) -> dict:
    """Front-page menus: breakfast and lunch lists, one line per school group."""
    out: dict[str, list] = {"Breakfast": [], "Lunch": []}
    short = {"Elementary": "Elementary (K–5)", "Middle & High School": "Middle & high school"}
    for m in menus:
        out[m["meal"]].append(dict(m, label=short.get(m["level"], m["level"])))
    return out


def home(site: Site, events: list[dict], today: date) -> dict:
    rng = random.Random()
    t = today.isoformat()
    week_end = (today + timedelta(days=6)).isoformat()
    if today.weekday() == 6:
        wk_lo = wk_hi = t
    else:
        sat = today + timedelta(days=5 - today.weekday())
        wk_lo, wk_hi = sat.isoformat(), (sat + timedelta(days=1)).isoformat()

    todays = [e for e in events if e["date"] <= t]
    birds = []
    seen = set()
    for r in newest(site.get("ebird").records, "published"):
        if r.get("photo_url") and r["common_name"] not in seen:
            seen.add(r["common_name"])
            birds.append(r)

    upcoming_meetings = [m for m in meetings(site) if t <= m["date"] <= week_end]
    next_menus = menu_days(site, today, 1)
    alerts = newest(since(site.get("spearfish_alert_center").records, 14, today))

    return {
        "today_events": todays,
        "weekend_count": sum(1 for e in events if e["date"] <= wk_hi and (e["end"][:10] or e["date"]) >= wk_lo),
        "week_count": sum(1 for e in events if e["date"] <= week_end),
        "menu_days": next_menus,
        "menu_lists": menu_lists(next_menus[0]["menus"]) if next_menus else {},
        # a fresh mix on every build (several times a day)
        "pets": pet_picks(site, 8, rng),
        "pet_tally": pet_tally(site.get("whhs_adoptable").records),
        "beers": tap_picks(site, 8, rng),
        "books": book_picks(site, 8, rng),
        "creek": creek_context(site),
        "fire": fire_context(site),
        "ski": terry_peak_context(site, today),
        "birds": birds[:4],
        "ebird": site.get("ebird"),
        "leones": site.get("leones_creamery"),
        "flavors": [f for f in site.get("leones_creamery").records if f.get("image_url")][:8],
        "headlines": newest(site.records(kind="news"))[:8],
        "meetings": upcoming_meetings[:6],
        "bids": site.get("public_bids").records,
        "recent_permits": recent_permit_count(site, today),
        "plant": plant_of_the_day(site, today),
        "alerts": alerts,
    }


# ── other pages ─────────────────────────────────────────────────────────────


def events_page(site: Site, events: list[dict], today: date) -> dict:
    cats = defaultdict(int)
    for e in events:
        cats[e["category"]] += 1
    return {
        "categories": [(k, CATEGORY_LABELS.get(k, k.title()), n) for k, n in sorted(cats.items(), key=lambda x: -x[1])],
        "event_count": len(events),
        "event_source_objs": [s for s in site.by_kind("event")],
    }


def schools(site: Site, events: list[dict], today: date) -> dict:
    two_weeks = (today + timedelta(days=14)).isoformat()
    return {
        "menu_days": menu_days(site, today, 10),
        "menu_sources": [site.get(slug) for slug, _, _ in MENU_SOURCES],
        "school_events": [
            e for e in events if e["category"] in ("schools", "school sports") and e["date"] <= two_weeks
        ],
        "news": newest(site.get("spearfish_school_news").records)[:10],
        "board": [m for m in reversed(meetings(site)) if m["body"] == "School Board"][:8],
        "jobs": site.get("spearfish_schools_jobs"),
        "district_calendar": site.get("spearfish_schools"),
    }


def plant_of_the_day(site: Site, today: date) -> dict | None:
    """One native plant per day, cycling through the whole list before any repeats.
    The order is a fixed shuffle (so neighbors in the list, often relatives, aren't
    back to back), the same on every build for a given list."""
    plants = sorted(
        (p for p in site.get("native_plants_spotlight").records if p.get("summary")), key=lambda p: p["taxon_id"]
    )
    if not plants:
        return None
    random.Random(57783).shuffle(plants)
    return plants[today.toordinal() % len(plants)]


SKI_MONTHS = (12, 1, 2, 3)


def terry_peak_context(site: Site, today: date) -> dict:
    """The ski area's snow report and what's open, for the Outdoors card."""
    src = site.get("terry_peak")
    data = src.data or {}
    lifts, trails = data.get("lifts") or [], data.get("trails") or []
    open_trails = [t for t in trails if t.get("open")]
    return {
        "source": src,
        "snow": data.get("snow") or {},
        "lifts": lifts,
        "lifts_open": [lift for lift in lifts if lift.get("open")],
        "trails": trails,
        "trails_open": {
            level: [t["name"] for t in open_trails if t.get("difficulty") == level]
            for level in ("beginner", "intermediate", "advanced")
        },
        "trails_open_count": len(open_trails),
        "webcams": data.get("webcams") or "https://terrypeak.com/the-mountain/live-web-cams/",
        # top of the Outdoors page in ski season: winter, or whenever a lift is running
        "first": today.month in SKI_MONTHS or any(lift.get("open") for lift in lifts),
    }


def outdoors(site: Site, events: list[dict], today: date) -> dict:
    projects = [p for p in site.get("bhnf_projects").records if p.get("status") == "In Progress"]
    return {
        "creek": creek_context(site),
        "fire": fire_context(site),
        "ski": terry_peak_context(site, today),
        "birds": newest(site.get("ebird").records, "published"),
        "ebird": site.get("ebird"),
        "forest_alerts": newest(site.get("bhnf_alerts").records)[:15],
        "bhnf_alerts": site.get("bhnf_alerts"),
        "projects": projects,
        "bhnf_projects": site.get("bhnf_projects"),
        "plant": plant_of_the_day(site, today),
        "plants": site.get("native_plants_spotlight"),
    }


def on_tap(site: Site, events: list[dict], today: date) -> dict:
    # a venue the scrapers have never heard of (no data, no health entry) has nothing to show
    return {"venues": [v for v in sources_of(site, TAP_SOURCES) if v.records or v.health]}


def civic(site: Site, events: list[dict], today: date) -> dict:
    t = today.isoformat()
    all_meetings = meetings(site)
    bp = site.get("building_permits")
    planning_parcels = ParcelLinks.load(site.data_dir)
    return {
        "upcoming": [m for m in all_meetings if m["date"] >= t][:20],
        "recent": [m for m in reversed(all_meetings) if (today - timedelta(days=45)).isoformat() <= m["date"] < t],
        "meeting_sources": sources_of(site, ["spearfish_city", "lawrence_county", "spearfish_school_board_docs"]),
        "videos": newest(site.get("public_meetings_youtube").records)[:9],
        "youtube": site.get("public_meetings_youtube"),
        "building_permits": bp,
        "building_records": sorted(
            bp.records, key=lambda r: (r.get("date", ""), r.get("cost_approximate") or 0), reverse=True
        )[:60],
        "bids": site.get("public_bids"),
        "planning": site.get("planning_commission"),
        "planning_items": [
            dict(r, site_key=pc_site_key(r, planning_parcels))
            for r in sorted(
                (r for r in site.get("planning_commission").records if r.get("site")),
                key=lambda r: r.get("meeting_date", ""),
                reverse=True,
            )[:12]
        ],
        "press": newest(site.records(kind="press_release", slugs=PRESS_SOURCES))[:20],
        "notices": site.get("danr_public_notices"),
        # soonest comment deadline first; notices without one go last
        "notice_list": sorted(
            site.get("danr_public_notices").records,
            key=lambda n: (not n.get("deadline_iso"), n.get("deadline_iso", "")),
        ),
        "cases": site.get("danr_contested_cases"),
        "case_list": sorted(site.get("danr_contested_cases").records, key=lambda c: c.get("updated", ""), reverse=True),
        "spills": site.get("danr_spills"),
        "spill_list": sorted(site.get("danr_spills").records, key=lambda r: r.get("report_no", ""), reverse=True),
    }


def news(site: Site, events: list[dict], today: date) -> dict:
    items = newest(since(site.records(kind="news", slugs=NEWS_SOURCES), 14, today))
    for r in items:
        r.setdefault("source_label", site.get(r.get("source", "")).label)
    outlet_counts = Counter(r["source_label"] for r in items if r["source_label"])
    by_day: dict[str, list] = defaultdict(list)
    for r in items:
        by_day[r.get("date", "")].append(r)
    return {
        "news_days": sorted(by_day.items(), reverse=True),
        "outlets": dict(sorted(outlet_counts.items())),
        "news_sources": sources_of(site, NEWS_SOURCES),
        "news_count": len(items),
    }


def jobs(site: Site, events: list[dict], today: date) -> dict:
    return {"employers": [s for s in sources_of(site, JOB_SOURCES)]}


def community(site: Site, events: list[dict], today: date) -> dict:
    library = site.get("spearfish_library")
    return {
        "library": library,
        # covers first: a shelf of placeholders up front looks broken
        "books": sorted(library.records, key=lambda b: not b.get("image_url")),
        "pets": site.get("whhs_adoptable"),
        "pet_list": mixed_pets(site.get("whhs_adoptable").records),
        "pet_tally": pet_tally(site.get("whhs_adoptable").records),
        "checkouts": checkouts_context(site),
    }


#: Monthly library checkouts, by how people borrow (keys in library_circulation rows)
CHECKOUT_SERIES = [
    ("loans", "Physical items", "Books, movies and other things you can hold"),
    ("overdrive", "Libby", "E-books and audiobooks through Libby (OverDrive)"),
    ("hoopla", "Hoopla", "Streaming movies, music, e-books and audiobooks through Hoopla"),
]


def checkouts_context(site: Site) -> dict:
    src = site.get("library_circulation")
    rows = (src.data or {}).get("rows") or []
    if not rows:
        return {"source": src, "rows": []}
    years: dict[str, dict] = {}
    for r in rows:
        y = years.setdefault(r["month"][:4], {"year": r["month"][:4], "months": 0})
        y["months"] += 1
        for key, *_ in CHECKOUT_SERIES:
            if r.get(key) is not None:
                y[key] = y.get(key, 0) + r[key]
    latest = rows[-1]
    return {
        "source": src,
        "rows": [{k: r.get(k) for k in ("month", *[s[0] for s in CHECKOUT_SERIES])} for r in rows],
        "series": CHECKOUT_SERIES,
        "latest": latest,
        "years": sorted(years.values(), key=lambda y: y["year"], reverse=True),
        "first": rows[0]["month"],
    }


# ── page: sources ───────────────────────────────────────────────────────────


def sources_page(site: Site, events: list[dict], today: date) -> dict:
    """The plain-language "Where this comes from" page: what we show, and whether it's current."""
    groups = []
    for heading, orgs in DIRECTORY:
        rows = []
        for org in orgs:
            items = []
            for item in org.items:
                srcs = [site.get(slug) for slug in item.slugs]
                if item.slugs and not any(s.enabled for s in srcs):
                    continue  # switched off; readers don't need to know
                srcs = [s for s in srcs if s.enabled]
                fetched = max((s.fetched_at for s in srcs if s.fetched_at), default=None)
                # current unless the data is past its freshness limit; one failed try doesn't count
                ok = not any(s.stale for s in srcs)
                if item.needs and all((s.data or {}).get(item.needs) is None for s in srcs):
                    ok, fetched = False, None  # the source ran, but this part of it came back empty
                items.append({"what": item.what, "note": item.note, "ok": ok, "updated": fetched})
            if items:
                rows.append({"name": org.name, "url": org.url, "offers": items})
        if rows:
            groups.append({"heading": heading, "orgs": rows})
    return {"groups": groups}


# ── page: permits ("Building permits and planning records") ─────────────────


def load_planning_archive(site: Site) -> dict:
    path = site.data_dir / "archive" / "planning_index.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"meta": {}, "records": []}


# Permit categories for the map: residential, commercial, land & streets, other.
# Permit numbers carry the clearest signal (RNC-26-55 residential, CAA-25-3 commercial);
# otherwise the type name decides.
_COMMERCIAL = re.compile(
    r"\b(com|comm|co mm|commercial|tenant|sign|sing|change of use|occupancy|business|vendor|food|c of occ"
    r"|fire (alarm|supp|code|suppression))",
    re.I,
)
_RESIDENTIAL = re.compile(
    r"\b(res|residential|dwelling|manuf|mfg|mh|mobile home|basement|garage|carport|deck|shed|fence|greenhouse"
    r"|studio|patio)",
    re.I,
)
_LAND = re.compile(
    r"\b(plat|zone|zoning|rezone|grading|right of way|rt of way|row|floodplain|flood|encroach|vacate|annex"
    r"|subdivision|development|tap|wa/se|wa extend|water|sewer|engineerin|legal|tif|tax increment"
    r"|conditional use|variance|moving)",
    re.I,
)


def permit_category(type_name: str, number: str = "") -> str:
    """'r' residential, 'c' commercial, 'l' land/streets/zoning, 'o' other."""
    no = (number or "").strip().lstrip("*X")
    if re.match(r"R[A-Z]{2}\b", no):
        return "r"
    if re.match(r"C[A-Z]{2}\b", no):
        return "c"
    t = type_name or ""
    if _COMMERCIAL.search(t):
        return "c"
    if _RESIDENTIAL.search(t):
        return "r"
    if _LAND.search(t):
        return "l"
    return "o"


# Abbreviated type names from the city's old (pre-2020) permit system
_OLD_TYPES = {
    "res new": "Residential new construction",
    "res alt": "Residential alteration",
    "res add": "Residential addition",
    "res garage": "Residential garage",
    "res deck": "Residential deck",
    "res repair": "Residential repair",
    "res demo": "Residential demolition",
    "res roof": "Residential roof",
    "res mech": "Residential heating/cooling",
    "res plumb": "Residential plumbing",
    "res ret": "Residential retaining wall",
    "res drive": "Residential driveway",
    "res side": "Residential siding",
    "com new": "Commercial new construction",
    "com alt": "Commercial alteration",
    "com add": "Commercial addition",
    "com roof": "Commercial roof",
    "com repair": "Commercial repair",
    "com demo": "Commercial demolition",
    "com mech": "Commercial heating/cooling",
    "com plumb": "Commercial plumbing",
    "com deck": "Commercial deck",
    "com side": "Commercial siding",
    "zone/dev": "Zoning or development",
    "rt of way": "Street or sidewalk work",
    "row": "Street or sidewalk work",
    "mech perm": "Heating/cooling",
    "mechanical permit": "Heating/cooling",
    "manuf mh": "Manufactured home",
    "mfg mh placement": "Manufactured home",
    "wa/se rep": "Water/sewer repair",
    "wa extend": "Water line extension",
    "tap": "Water/sewer hookup",
    "encroach": "Encroachment",
    "flood": "Floodplain",
    "engineerin": "Engineering",
    "retaining": "Retaining wall",
    "fire supp": "Fire sprinklers",
    "c of occ": "Certificate of occupancy",
    "moving": "Moving a building",
}
_ABBREVIATIONS = {
    "alt": "alteration",
    "addn": "addition",
    "bsmt": "basement",
    "bldg": "building",
    "fndn": "foundation",
    "mh": "mobile home",
    "twnhs": "townhouses",
}
_JUNK_TYPE = re.compile(r"^(\$|owner$|permit fee$)", re.I)
_KNOWN_TYPE = re.compile(
    _COMMERCIAL.pattern
    + "|"
    + _RESIDENTIAL.pattern
    + "|"
    + _LAND.pattern
    + r"|mech|plumb|gas|demo|roof|retain|wall|elect|repair|finish|addition|alteration|new|permit|sign",
    re.I,
)


def friendly_type(t: str) -> str:
    """'Res-New Dwelling' → 'Residential new dwelling'; 'Com Alt (pre-2020 system)' → 'Commercial alteration'."""
    t = re.sub(r"\(.*?\)|\*|\s+-\s+spearfish$", "", t or "", flags=re.I)
    t = " ".join(t.split()).strip(" -")
    if not t or _JUNK_TYPE.match(t) or not _KNOWN_TYPE.search(t):
        return "Building permit"  # the report's type column held something else
    if t.lower() in _OLD_TYPES:
        return _OLD_TYPES[t.lower()]
    t = re.sub(r"^res\b[-\s]*", "Residential ", t, flags=re.I)
    t = re.sub(r"^(comm?|co mm)\b[-\s]*", "Commercial ", t, flags=re.I)
    for short, word in _ABBREVIATIONS.items():
        t = re.sub(rf"\b{short}\b\.?", word, t, flags=re.I)
    return t[:1].upper() + t[1:].lower()


_STATUS = {
    "complete": "Completed",
    "open": "Open",
    "active": "In progress",
    "draft": "Not submitted",
    "voided": "Canceled",
    "no insp": "No inspection",
    "stopped": "Stopped",
    "suspended": "Suspended",
}


def friendly_status(s: str) -> str:
    return _STATUS.get((s or "").strip().lower(), "")


_KEEP_UPPER = {"SD", "N", "S", "E", "W", "NE", "NW", "SE", "SW", "US", "HWY", "PO", "STE", "LLC"}


def pretty_address(a: str) -> str:
    """'2312 PLATINUM DRIVE, SPEARFISH, SD 57783' → '2312 Platinum Drive, Spearfish, SD 57783'."""
    a = " ".join((a or "").split())
    if a != a.upper():
        return a
    return " ".join(w if w.strip(",.") in _KEEP_UPPER or w[:1].isdigit() else w.capitalize() for w in a.split())


def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in ("", None, [], 0)}


def pc_site_key(r: dict, links: ParcelLinks | None = None) -> str:
    """Permits-page key for a Planning Commission item: its parcel, else its street address, else its location text."""
    if links and (pid := links.pid(record_key("pc", r), r.get("address", ""))):
        return f"P {pid}"
    return r.get("address_key") or ("LOC " + " ".join(r.get("location", "").upper().rstrip(".").split()))


#: The permits page opens on the past two years, so it first loads only places
#: active in that window (with their full history); everything else loads when a
#: reader searches or picks a longer period. A month of slack covers the site
#: going a while without a rebuild.
RECENT_DAYS = 2 * 365 + 31


def recent_sites(sites: list[dict], today: date) -> list[dict]:
    cutoff = (today - timedelta(days=RECENT_DAYS)).isoformat()
    return [s for s in sites if any((r.get("d") or "") >= cutoff for r in s["r"])]


def report_link(site: Site, r: dict) -> str:
    """The month's permit report as this site serves it (relative to the permits page), else the city's copy."""
    ym = r.get("report") or (f"{r.get('year')}-{str(r.get('month')).zfill(2)}" if r.get("year") else "")
    if ym and (site.data_dir / "permit_reports" / f"{ym}.pdf").exists():
        return f"reports/{ym}.pdf"
    return r.get("url") or ""


def site_key(parcels: ParcelLinks | None, key: str, addr: str, fallback: str) -> str:
    """The permits page's key for a record's place: its county parcel when linked, else its address."""
    if parcels and (pid := parcels.pid(key, addr)):
        return f"P {pid}"
    return fallback


def permit_site_key(r: dict, parcels: ParcelLinks | None) -> str:
    """Where a building permit sits on the permits page (its #site= link)."""
    addr = r.get("site_address", "")
    return site_key(parcels, record_key("permit", r), addr, geo.normalize_address(addr))


def permit_sites(site: Site, parcels: ParcelLinks | None = None) -> list[dict]:
    """
    Every planning application (OpenGov archive), issued building permit
    (monthly reports) and Planning Commission agenda item, grouped by site.

    A site is a county parcel whenever a record can be linked to one (see
    sitegen/parcels.py, via parcel_links.json); the parcel supplies the map position, owner, acreage
    and outline. Otherwise records group by standardized street address, and
    agenda items placed only by a description ("Intersection of St. Onge Road
    and Highway 14") get their own entry, searchable but not mapped.
    Each record gets a reader-friendly type, status and map category ("c").
    """
    parcels = parcels if parcels is not None else ParcelLinks.load(site.data_dir)
    groups: dict[str, dict] = {}

    def add(key, address, lat, lon, rec):
        if not key:
            return
        g = groups.get(key)
        if g is None:
            g = groups[key] = {"k": key, "a": pretty_address(address), "r": []}
            if key.startswith("P "):
                pf = parcels.site_fields(key[2:])
                situs = parcels.by_id[key[2:]].get("situs")
                g.update(pf)
                if situs and not address:
                    g["a"] = pretty_address(situs)
        if lat and lon and "lat" not in g:
            g["lat"], g["lon"] = round(lat, 5), round(lon, 5)
        if not g["a"] and address:
            g["a"] = pretty_address(address)
        g["r"].append(_compact(rec))

    def place(key: str, addr: str, fallback: str) -> str:
        return site_key(parcels, key, addr, fallback)

    for r in load_planning_archive(site)["records"]:
        if not r.get("site") or "practice record" in (r.get("type") or "").lower():
            continue
        add(
            place(record_key("app", r), r.get("address", ""), geo.normalize_address(r.get("address", ""))),
            r.get("address"),
            r.get("lat"),
            r.get("lon"),
            {
                "src": "app",
                "d": r.get("submitted") or r.get("created"),
                "t": friendly_type(r.get("type")),
                "c": permit_category(r.get("type"), r.get("no") or r.get("historical_no")),
                "s": friendly_status(r.get("status")),
                "no": r.get("no") or r.get("historical_no"),
                "v": r.get("valuation") if isinstance(r.get("valuation"), (int, float)) else None,
                "desc": r.get("description"),
                "who": r.get("applicant"),
                "own": r.get("owner"),
                "own_c": " · ".join(x for x in (r.get("owner_phone"), r.get("owner_email")) if x),
                "con": r.get("contractor"),
                "con_c": " · ".join(x for x in (r.get("contractor_phone"), r.get("contractor_email")) if x),
            },
        )

    for r in site.get("building_permits").records:
        add(
            permit_site_key(r, parcels),
            r.get("site_address"),
            r.get("lat"),
            r.get("lon"),
            {
                "src": "permit",
                "d": r.get("date"),
                "t": friendly_type(r.get("construction_type")),
                "c": permit_category(r.get("construction_type"), r.get("permit_number")),
                "no": r.get("permit_number"),
                "v": r.get("cost_approximate"),
                "who": (r.get("applicant_name") or "").title(),
                "con": (r.get("contractor") or "").title(),
                "u": report_link(site, r),
            },
        )

    for r in site.get("planning_commission").records:
        if not r.get("site"):
            continue
        add(
            pc_site_key(r, parcels),
            r.get("address") or r.get("location", "").rstrip("."),
            r.get("lat"),
            r.get("lon"),
            # Until the details read from agendas are checked, a Planning Commission entry says only
            # that the place was on a meeting's agenda, with that meeting's own documents.
            {
                "src": "pc",
                "d": (r.get("meeting_date") or "")[:10],
                "t": "On the meeting agenda",
                "c": "l",
                "u": r.get("report_url"),
                "mu": r.get("meeting_url"),
                "docs": [[d["name"], d["url"]] for d in r.get("meeting_docs") or []],
                "att": [[a["name"], a["url"]] for a in r.get("attachments") or []],
            },
        )

    out = []
    for g in groups.values():
        g["r"].sort(key=lambda x: x.get("d") or "", reverse=True)
        g["last"] = g["r"][0].get("d", "")
        if g["r"][0].get("src") == "permit":
            g["lp"] = 1  # latest record only has a month
        out.append(g)
    out.sort(key=lambda g: g["last"], reverse=True)
    return out


def permits_page(site: Site, events: list[dict], today: date) -> dict:
    archive = load_planning_archive(site)
    bp = site.get("building_permits")
    latest_report = max((r.get("date", "") for r in bp.records), default="")
    return {
        "archive_meta": archive["meta"],
        "building_permits": bp,
        "latest_report": latest_report,
        "first_permit": min((r.get("date", "") for r in bp.records if r.get("date")), default=""),
        "pc_first": min((r.get("meeting_date", "")[:10] for r in site.get("planning_commission").records), default=""),
        "beacon": BEACON,
    }


def permit_trends_page(site: Site, events: list[dict], today: date) -> dict:
    parcels = ParcelLinks.load(site.data_dir)
    return {
        "t": trends.build(
            site.get("building_permits").records,
            today,
            trends.cpi_lookup(),
            place=lambda r: permit_site_key(r, parcels),
        )
    }

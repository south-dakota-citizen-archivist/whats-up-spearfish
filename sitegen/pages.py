"""
sitegen/pages.py

One context function per page. Each takes the loaded Site, the unified events
list and today's date, and returns the template variables for that page.
"""

from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import date, timedelta

from scrapers import geo
from sitegen.data import Site, Source
from sitegen.events import CATEGORY_LABELS

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

NEWS_SOURCES = [
    "black_hills_pioneer",
    "rapid_city_journal",
    "sdpb_news",
    "news_feeds",
    "sundance_times",
    "custer_county_chronicle",
]
PRESS_SOURCES = ["spearfish_news", "spearfish_blog", "lawrence_county_news", "spearfish_school_news", "bhnf"]
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
        out.append({"slug": slug, "level": level, "meal": meal, "entrees": entrees, "url": site.get(slug).url})
    return out


def menu_days(site: Site, today: date, count: int) -> list[dict]:
    all_days = sorted({r["date"] for slug, _, _ in MENU_SOURCES for r in site.get(slug).records if r.get("date")})
    days = []
    for d in all_days:
        if d < today.isoformat():
            continue
        menus = menus_for_day(site, d)
        if menus:
            days.append({"date": d, "menus": menus})
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
        "chart": sparkline([d["cfs"] for d in daily], 600, 140),
        "daily": daily,
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
    restrictions = data.get("restrictions") or []
    danger = data.get("danger") or {}
    zones = danger.get("zones") or []
    # Spearfish sits in the NWS "Northern Foothills" rangeland zone
    local = next((z for z in zones if "Northern Foothills" in z["name"]), None)
    return {
        "source": src,
        "restrictions": restrictions,
        "restricted": [r for r in restrictions if r["restricted"]],
        "danger": danger,
        "local_danger": local,
        "incidents": data.get("incidents") or [],
    }


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
        m["docs"].append({"label": (r.get("asset_type") or "Document").title(), "url": r["url"]})
    return sorted(out.values(), key=lambda m: m["date"])


def home(site: Site, events: list[dict], today: date) -> dict:
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
        if r["common_name"] not in seen:
            seen.add(r["common_name"])
            birds.append(r)

    upcoming_meetings = [m for m in meetings(site) if t <= m["date"] <= week_end]
    alerts = newest(since(site.get("spearfish_alert_center").records, 14, today))

    return {
        "today_events": todays,
        "weekend_count": sum(1 for e in events if e["date"] <= wk_hi and (e["end"][:10] or e["date"]) >= wk_lo),
        "week_count": sum(1 for e in events if e["date"] <= week_end),
        "menu_days": menu_days(site, today, 1),
        "creek": creek_context(site),
        "fire": fire_context(site),
        "birds": birds[:4],
        "ebird": site.get("ebird"),
        "taps": [s for s in sources_of(site, TAP_SOURCES) if s.records],
        "leones": site.get("leones_creamery"),
        "headlines": newest(site.records(kind="news"))[:8],
        "meetings": upcoming_meetings[:6],
        "bids": site.get("public_bids").records,
        "alerts": alerts,
    }


# ── other pages ─────────────────────────────────────────────────────────────


def events_page(site: Site, events: list[dict], today: date) -> dict:
    cats = defaultdict(int)
    srcs = defaultdict(int)
    for e in events:
        cats[e["category"]] += 1
        srcs[e["source_label"]] += 1
    return {
        "categories": [(k, CATEGORY_LABELS.get(k, k.title()), n) for k, n in sorted(cats.items(), key=lambda x: -x[1])],
        "event_sources": sorted(srcs.items()),
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


def outdoors(site: Site, events: list[dict], today: date) -> dict:
    projects = [p for p in site.get("bhnf_projects").records if p.get("status") == "In Progress"]
    return {
        "creek": creek_context(site),
        "fire": fire_context(site),
        "birds": newest(site.get("ebird").records, "published"),
        "ebird": site.get("ebird"),
        "forest_alerts": newest(site.get("bhnf_alerts").records)[:15],
        "bhnf_alerts": site.get("bhnf_alerts"),
        "projects": projects,
        "bhnf_projects": site.get("bhnf_projects"),
    }


def on_tap(site: Site, events: list[dict], today: date) -> dict:
    return {"venues": sources_of(site, TAP_SOURCES), "leones": site.get("leones_creamery")}


def civic(site: Site, events: list[dict], today: date) -> dict:
    t = today.isoformat()
    all_meetings = meetings(site)
    bp = site.get("building_permits")
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
        "press": newest(site.records(kind="press_release", slugs=PRESS_SOURCES))[:20],
        "notices": site.get("danr_public_notices"),
    }


def news(site: Site, events: list[dict], today: date) -> dict:
    items = newest(since(site.records(kind="news", slugs=NEWS_SOURCES), 14, today))
    outlets = sorted({r["source_label"] for r in items})
    by_day: dict[str, list] = defaultdict(list)
    for r in items:
        by_day[r.get("date", "")].append(r)
    return {
        "news_days": sorted(by_day.items(), reverse=True),
        "outlets": outlets,
        "news_sources": sources_of(site, NEWS_SOURCES),
        "news_count": len(items),
    }


def jobs(site: Site, events: list[dict], today: date) -> dict:
    return {"employers": [s for s in sources_of(site, JOB_SOURCES)]}


def community(site: Site, events: list[dict], today: date) -> dict:
    return {"library": site.get("spearfish_library"), "pets": site.get("whhs_adoptable")}


STATUS_ORDER = {"error": 0, "empty": 1, "stale": 2, "missing": 3, "ok": 4, "disabled": 5}


def status(site: Site, events: list[dict], today: date) -> dict:
    rows = sorted(site.sources.values(), key=lambda s: (STATUS_ORDER.get(s.status, 9), s.name.lower()))
    counts = defaultdict(int)
    for s in rows:
        counts[s.status] += 1
    return {"rows": rows, "counts": dict(counts), "health_updated": site.health.get("updated")}


def status_summary(site: Site) -> dict:
    live = [s for s in site.sources.values() if s.enabled]
    bad = [s for s in live if s.status not in ("ok",)]
    return {"total": len(live), "bad": len(bad)}


# ── page: permits ("What's being built here?") ─────────────────────────────


def load_planning_archive(site: Site) -> dict:
    path = site.data_dir / "archive" / "planning_index.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"meta": {}, "records": []}


_KEEP_UPPER = {"SD", "N", "S", "E", "W", "NE", "NW", "SE", "SW", "US", "HWY", "PO", "STE", "LLC"}


def pretty_address(a: str) -> str:
    """'2312 PLATINUM DRIVE, SPEARFISH, SD 57783' → '2312 Platinum Drive, Spearfish, SD 57783'."""
    a = " ".join((a or "").split())
    if a != a.upper():
        return a
    return " ".join(w if w.strip(",.") in _KEEP_UPPER or w[:1].isdigit() else w.capitalize() for w in a.split())


def _compact(d: dict) -> dict:
    return {k: v for k, v in d.items() if v not in ("", None, [], 0)}


def permit_sites(site: Site) -> list[dict]:
    """
    Every planning application (OpenGov archive) and issued building permit
    (monthly reports), grouped by normalized street address.
    """
    groups: dict[str, dict] = {}

    def add(key, address, lat, lon, rec):
        if not key:
            return
        g = groups.setdefault(key, {"k": key, "a": pretty_address(address), "r": []})
        if lat and lon and "lat" not in g:
            g["lat"], g["lon"] = round(lat, 5), round(lon, 5)
        g["r"].append(_compact(rec))

    for r in load_planning_archive(site)["records"]:
        if not r.get("site"):
            continue
        add(
            geo.normalize_address(r.get("address", "")),
            r.get("address"),
            r.get("lat"),
            r.get("lon"),
            {
                "src": "app",
                "d": r.get("submitted") or r.get("created"),
                "t": r.get("type"),
                "s": r.get("status"),
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
            geo.normalize_address(r.get("site_address", "")),
            r.get("site_address"),
            r.get("lat"),
            r.get("lon"),
            {
                "src": "permit",
                "d": r.get("date"),
                "t": (r.get("construction_type") or "").title(),
                "no": r.get("permit_number"),
                "v": r.get("cost_approximate"),
                "who": (r.get("applicant_name") or "").title(),
                "con": (r.get("contractor") or "").title(),
                "u": r.get("url"),
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
        "permit_count": len(bp.records),
    }

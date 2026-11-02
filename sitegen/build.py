"""
sitegen/build.py

Renders the static site into _site/:

    /                 today's digest
    /events/          unified calendar (+ events.json, calendar.ics, events.xml)
    /schools/         menus, school events, district news
    /outdoors/        creek, fire, birds, national forest
    /on-tap/          tap lists and ice cream flavors
    /civic/           meetings, permits, bids, notices
    /news/            regional headlines
    /jobs/            local job postings
    /community/       library new arrivals, adoptable pets
    /sources/         where the information comes from (/status/ redirects here)

Usage: python -m sitegen [--data DIR] [--out DIR]
"""

from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from jinja2 import Environment, FileSystemLoader, select_autoescape

from scrapers import dates
from sitegen import feeds, pages
from sitegen.data import Site
from sitegen.events import CATEGORY_LABELS, unified_events

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "site" / "templates"
STATIC = ROOT / "site" / "static"
SITE_URL = "https://south-dakota-citizen-archivist.github.io/whats-up-spearfish"
TAILWIND_VERSION = "v4.2.2"

NAV = [
    ("", "Today"),
    ("events/", "Events"),
    ("schools/", "Schools"),
    ("outdoors/", "Outdoors"),
    ("on-tap/", "On tap"),
    ("civic/", "Civic"),
    ("permits/", "Permits"),
    ("news/", "News"),
    ("jobs/", "Jobs"),
    ("community/", "Community"),
]

PAGES = [
    # (path, template, title, context fn)
    ("", "pages/home.html", "", pages.home),
    ("events/", "pages/events.html", "Events", pages.events_page),
    ("schools/", "pages/schools.html", "Schools", pages.schools),
    ("outdoors/", "pages/outdoors.html", "Outdoors", pages.outdoors),
    ("on-tap/", "pages/on_tap.html", "On tap", pages.on_tap),
    ("civic/", "pages/civic.html", "Civic", pages.civic),
    ("permits/", "pages/permits.html", "What's being built here?", pages.permits_page),
    ("news/", "pages/news.html", "News", pages.news),
    ("jobs/", "pages/jobs.html", "Jobs", pages.jobs),
    ("community/", "pages/community.html", "Community", pages.community),
    ("sources/", "pages/sources.html", "Where this comes from", pages.sources_page),
]


# ── template filters ────────────────────────────────────────────────────────


def _dt(value):
    if isinstance(value, datetime):
        return value
    return dates.parse(value) if value else None


def fmt_day(value, fmt="%a, %b %-d") -> str:
    d = _dt(value)
    return d.strftime(fmt) if d else ""


def fmt_time(value) -> str:
    d = _dt(value)
    if not isinstance(d, datetime):
        return ""
    return d.strftime("%-I %p" if d.minute == 0 else "%-I:%M %p")


def ago(value) -> str:
    d = _dt(value)
    if not isinstance(d, datetime):
        return "never"
    secs = (dates.now() - d).total_seconds()
    if secs < 90:
        return "just now"
    for unit, size in (("day", 86400), ("hour", 3600), ("minute", 60)):
        if secs >= size:
            n = int(secs // size)
            return f"{n} {unit}{'s' if n != 1 else ''} ago"
    return "just now"


def day_heading(value: str) -> str:
    d = dates.to_date(value)
    if not d:
        return ""
    delta = (d - dates.today()).days
    if delta == 0:
        return "Today"
    if delta == 1:
        return "Tomorrow"
    if delta == -1:
        return "Yesterday"
    return d.strftime("%A, %B %-d")


def domain(url: str) -> str:
    return urlparse(url or "").netloc.removeprefix("www.")


def intcomma(value) -> str:
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value or "")


def make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters.update(
        fmt_day=fmt_day,
        fmt_time=fmt_time,
        ago=ago,
        day_heading=day_heading,
        domain=domain,
        intcomma=intcomma,
        permit_type=pages.friendly_type,
    )
    env.globals.update(NAV=NAV, CATEGORY_LABELS=CATEGORY_LABELS, SITE_URL=SITE_URL)
    return env


# ── build ───────────────────────────────────────────────────────────────────


def compile_css(out_dir: Path) -> str:
    """Compile Tailwind to static/site.css; return a cache-busting version string."""
    css_out = out_dir / "static" / "site.css"
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytailwindcss",
            "-i",
            str(STATIC / "css" / "input.css"),
            "-o",
            str(css_out),
            "--minify",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "TAILWINDCSS_VERSION": os.environ.get("TAILWINDCSS_VERSION", TAILWIND_VERSION)},
    )
    if result.returncode != 0:
        raise SystemExit(f"[sitegen] Tailwind failed:\n{result.stderr}")
    return hashlib.sha1(css_out.read_bytes()).hexdigest()[:10]


def build(data_dir: Path, out_dir: Path) -> None:
    today = dates.today()
    site = Site(data_dir)
    events = unified_events(site, today)

    if out_dir.exists():
        shutil.rmtree(out_dir)
    shutil.copytree(STATIC, out_dir / "static", ignore=shutil.ignore_patterns("css"))
    css_version = compile_css(out_dir)

    env = make_env()
    common = {
        "build_time": dates.now(),
        "today": today,
        "css_version": css_version,
    }
    for path, template, title, ctx_fn in PAGES:
        depth = path.count("/")
        ctx = {**common, **ctx_fn(site, events, today), "page_path": path, "page_title": title, "root": "../" * depth}
        dest = out_dir / path / "index.html"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(env.get_template(template).render(**ctx), encoding="utf-8")
        print(f"[sitegen] {dest.relative_to(out_dir)} ({dest.stat().st_size // 1024} KB)")

    (out_dir / "404.html").write_text(
        env.get_template("pages/404.html").render(
            **common, page_path="404", page_title="Not found", root="/whats-up-spearfish/"
        ),
        encoding="utf-8",
    )

    # The old technical status page moved; keep its URL working
    (out_dir / "status").mkdir(exist_ok=True)
    (out_dir / "status" / "index.html").write_text(
        '<!DOCTYPE html><meta charset="utf-8"><title>Moved</title>'
        '<meta http-equiv="refresh" content="0; url=../sources/"><a href="../sources/">Where this comes from</a>',
        encoding="utf-8",
    )

    feeds.write_json(events, out_dir / "events.json")
    feeds.write_json(pages.permit_sites(site), out_dir / "permits" / "sites.json")
    feeds.write_json(pages.menu_details(site, today), out_dir / "schools" / "menus.json")
    feeds.write_ics(events, out_dir / "calendar.ics", SITE_URL)
    feeds.write_rss(events, out_dir / "events.xml", SITE_URL)
    (out_dir / ".nojekyll").touch()
    print(f"[sitegen] {len(events)} events, {len(site.sources)} sources → {out_dir}")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m sitegen")
    ap.add_argument("--data", type=Path, default=Path(os.environ.get("WUS_DATA_DIR") or ROOT / "data"))
    ap.add_argument("--out", type=Path, default=ROOT / "_site")
    args = ap.parse_args(argv)
    build(args.data, args.out)

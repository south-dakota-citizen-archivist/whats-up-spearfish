"""
scrapers/sources/bhnf_projects.py

Black Hills National Forest — public projects requiring NEPA review.
Scrapes the project listing page for all projects, then fetches detail
pages for in-progress projects to pull milestones and contact info.

https://www.fs.usda.gov/r02/blackhills/projects

Not a BaseScraper subclass — run directly or from the daily scrape workflow.

Usage:
    uv run python -c "from scrapers.sources.bhnf_projects import fetch_bhnf_projects; fetch_bhnf_projects()"
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "bhnf_projects.json"
BASE_URL = "https://www.fs.usda.gov"
LISTING_URL = f"{BASE_URL}/r02/blackhills/projects"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}

_PHONE_RE = re.compile(r"^\d{3}[-.\s]\d{3}[-.\s]\d{4}$")


def _get(url: str) -> BeautifulSoup:
    r = requests.get(url, headers=_HEADERS, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _milestone_sort_key(date_str: str) -> str:
    """Return a sortable YYYY-MM[-DD] string, or '9999-99' on parse failure."""
    s = re.sub(r"\s*\(.*?\)", "", date_str).strip()
    # MM/DD/YYYY
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", s)
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    # M/YYYY or MM/YYYY
    m = re.match(r"^(\d{1,2})/(\d{4})$", s)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}"
    return "9999-99"


def _scrape_listing() -> list[dict]:
    """Scrape all project cards from the listing page via data attributes."""
    soup = _get(LISTING_URL)
    projects = []
    for card in soup.select(".wfs-project__teaser"):
        a = card.select_one("h3 a")
        if not a:
            continue
        href = a.get("href", "")
        url = BASE_URL + href if href.startswith("/") else href
        project_id = href.rstrip("/").split("/")[-1]
        desc_el = card.select_one(".usa-card__body p")
        projects.append(
            {
                "project_id": project_id,
                "title": a.get_text(strip=True),
                "url": url,
                "status": card.get("data-status", "").strip(),
                "district": card.get("data-unit", "").strip(),
                "purpose": card.get("data-purposeid", "").strip().title(),
                "description": desc_el.get_text(" ", strip=True) if desc_el else "",
                "milestones": [],
                "comment_period_date": None,
                "comment_period_sort": "9999-99",
                "location_summary": "",
                "counties": [],
                "contact": {},
                "last_updated": "",
            }
        )
    return projects


def _scrape_detail(url: str) -> dict:
    """Fetch a project detail page and extract milestones, contact, and location."""
    try:
        soup = _get(url)
    except Exception as exc:
        print(f"  [bhnf_projects] Warning: {url}: {exc}")
        return {}

    result: dict = {}
    accordion = soup.select_one(".usa-accordion.usa-accordion--bordered")
    if not accordion:
        return result

    for btn in accordion.select(".usa-accordion__button"):
        label = btn.get_text(strip=True)
        content_id = btn.get("aria-controls", "")
        content = soup.find(id=content_id)
        if not content:
            continue

        if "Overview" in label or "Summary" in label:
            # Milestones table
            table = content.find("table")
            if table:
                milestones = []
                for row in table.select("tbody tr"):
                    cells = row.find_all("td")
                    if len(cells) == 2:
                        milestones.append(
                            {
                                "name": cells[0].get_text(strip=True),
                                "date": cells[1].get_text(strip=True).replace("\xa0", " ").strip(),
                            }
                        )
                result["milestones"] = milestones

            # Labeled fields via <b> tags
            for p in content.find_all("p"):
                b = p.find("b")
                if not b:
                    continue
                field = b.get_text(strip=True).rstrip(":").strip()
                value = p.get_text(" ", strip=True)
                value = value[len(b.get_text(strip=True)) :].lstrip(":").strip()
                if field == "Location Summary":
                    result["location_summary"] = value
                elif field == "Counties":
                    result["counties"] = [c.strip() for c in value.split(",") if c.strip()]

        elif "Connected" in label:
            p = content.find("p")
            if p:
                lines = [ln.strip() for ln in p.get_text("\n").split("\n") if ln.strip()]
                contact: dict[str, str] = {"name": lines[0] if lines else ""}
                # Email
                email_a = p.find("a", href=re.compile(r"^mailto:", re.I))
                if email_a:
                    contact["email"] = re.sub(r"^mailto:", "", email_a["href"]).split("?")[0]
                # Phone: prefer tel: href, fall back to text line matching phone pattern
                tel_a = p.find("a", href=re.compile(r"^tel:", re.I))
                if tel_a:
                    contact["phone"] = re.sub(r"^tel:", "", tel_a["href"]).strip()
                else:
                    for ln in lines[1:]:
                        if _PHONE_RE.match(ln):
                            contact["phone"] = ln
                            break
                result["contact"] = contact

    # Last updated date
    last_el = soup.select_one("p.text-align-right i")
    if last_el:
        m = re.search(r"(\d{1,2}/\d{1,2}/\d{4})", last_el.get_text())
        if m:
            result["last_updated"] = m.group(1)

    return result


def fetch_bhnf_projects() -> None:
    print("[bhnf_projects] Fetching project listing…")
    projects = _scrape_listing()
    print(f"[bhnf_projects] {len(projects)} total projects")

    in_progress = [p for p in projects if p.get("status") == "In Progress"]
    print(f"[bhnf_projects] {len(in_progress)} in-progress — fetching detail pages")

    for i, p in enumerate(projects):
        if p.get("status") != "In Progress":
            continue
        time.sleep(0.5)
        detail = _scrape_detail(p["url"])
        p.update(detail)

        ms = p.get("milestones") or []
        comment_ms = next((m for m in ms if "comment" in m["name"].lower()), None)
        p["comment_period_date"] = comment_ms["date"] if comment_ms else None
        p["comment_period_sort"] = _milestone_sort_key(comment_ms["date"]) if comment_ms else "9999-99"
        print(f"  [{i + 1}] {p['title']} — comment: {p['comment_period_date']}")

    # Sort: in-progress first (by comment period soonest), then others by title
    projects.sort(
        key=lambda p: (
            0 if p["status"] == "In Progress" else 1,
            p.get("comment_period_sort", "9999-99"),
            p.get("title", "").lower(),
        )
    )

    DATA_FILE.write_text(
        json.dumps(
            {"fetched_at": datetime.now(timezone.utc).isoformat(), "projects": projects},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[bhnf_projects] {len(projects)} projects → {DATA_FILE.name}")


if __name__ == "__main__":
    fetch_bhnf_projects()

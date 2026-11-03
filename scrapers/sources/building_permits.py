"""
scrapers/sources/building_permits.py

Monthly building permit reports from the City of Spearfish archive. Every
report is kept: each run downloads any the city has posted that we don't have
yet (into DATA_DIR/permit_reports/YYYY-MM.pdf, served with the site), then reads
the most recent RECENT_MONTHS of them (scrapers/permit_reports.py reads every
layout the city has used since 2013).

Records are kept indefinitely: with the city's OpenGov portal closed to the
public, these reports are the only ongoing record of permits issued. The
2013 – September 2025 history was checked by hand against the reports.
"""

from __future__ import annotations

import difflib
import re
import time
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers import base, geo, net
from scrapers.base import BaseScraper
from scrapers.permit_reports import parse_report

BASE_URL = "https://www.spearfish.gov"  # cityofspearfish.com redirects here
ARCHIVE_URL = f"{BASE_URL}/Archive.aspx?AMID=37"

RECENT_MONTHS = 6

# Addresses corrected by hand for permits whose report has a wrong or unreadable one
ADDRESS_FIXES: dict[str, str] = {
    "14-0253": "1610 COLLEGE",
    "220316": "1996 RUSSELL STREET",
    "220317": "1992 RUSSELL STREET",
    "220318": "1988 RUSSELL STREET",
    "220319": "1984 RUSSELL STREET",
    "220320": "1980 RUSSELL STREET",
    "220500": "2555 CLEAR SPRING ROAD",
    "220204": "2555 CLEAR SPRING ROAD",
    "180140": "2555 CLEAR SPRING ROAD",
    "200744": "2555 CLEAR SPRING ROAD",
    "200253": "2555 CLEAR SPRING ROAD",
    "210541": "1015 CANYON STREET N",
    "15-0463": "407 ST. JOE ST.",
    "230186": "625 WOODLAND DR",
    "15-0385": "1020 N. CANYON",
    "210707": "2555 CLEAR SPRING ROAD",
    "13-0254": "834 AMES STREET",
    "13-0429": "1630 COLLEGE",
    "16-0449": "119 YUKON PL",
    "230141": "7100 CENTENNIAL RD",
    "PMG-24-23": "311 EVANS LANE",
    "RND-24-15": "7923 DUKE PARKWAY",
    "CNC-25-7": "300 AVIATION PL, UNIT 254",
    "NCM-25-5": "300 AVIATION PL, UNIT 449",
    "180213": "4025 E. COLORADO BLVD.",
    "180214": "4025 E. COLORADO BLVD.",
    "180215": "4025 E. COLORADO BLVD.",
    "180216": "4025 E. COLORADO BLVD.",
}


def _categorize(construction_type: str) -> str:
    """Map a construction_type string to a broad category slug."""
    t = construction_type.upper()
    # Demolition
    if any(k in t for k in ("DEMOLITION", "DEMO")):
        return "demolition"
    # Mechanical / plumbing / gas (standalone)
    if any(
        k in t
        for k in (
            "PLUMBING",
            "MECHANICAL",
            "GAS",
            "STANDALONE",
            "RES-MECHANICAL",
            "COMM-MECHANICAL",
            "RES-PLUMBING",
            "COMM-PLUMBING",
            "WATER/SEWER",
            "ELECTRIC",
        )
    ):
        return "mechanical"
    # New construction
    if any(
        k in t
        for k in (
            "NEW CONSTRUCTION",
            "NEW DWELLING",
            "NEW BUILDING",
            "RES-NEW",
            "RESIDENTIAL NEW",
            "COMMERCIAL NEW",
            "COMM-NEW",
            "MFG MH PLACEMENT",
            "MANUFACTURED HOME",
        )
    ):
        return "new_construction"
    # Everything else (additions, alterations, roofs, garages, basements, decks, etc.)
    return "alterations"


def reports_dir() -> Path:
    """Where the monthly reports are kept: DATA_DIR/permit_reports (the data branch), served at permits/reports/."""
    return base.DATA_DIR / "permit_reports"


def read_report(pdf_path: Path, year: str, month: str) -> list[dict]:
    """Records for one month's report, ready to save."""
    records = []
    for p in parse_report(pdf_path):
        addr = ADDRESS_FIXES.get(p["permit_number"].replace("/", "-"), p["site_address"])
        records.append(
            p
            | {
                "year": year,
                "month": month,
                "date": f"{year}-{month}-01",
                "report": f"{year}-{month}",
                "applicant_name": p["applicant_name"].upper(),
                "site_address": " ".join(addr.split()),
                "contractor": p["contractor"].upper(),
                "category": _categorize(p["construction_type"]),
            }
        )
    return records


MONTHS = ["january", "february", "march", "april", "may", "june", "july", "august", "september", "october",
          "november", "december"]  # fmt: skip


def month_of(label: str) -> tuple[str, str] | None:
    """('2026', '07') from a link like 'Monthly Building Permit Report - July 2026 (PDF)', typos and all
    ('Juy 2026', 'August2026'): the month is whichever name the word is closest to."""
    m = re.search(r"([A-Za-z]{3,})\.?\s*,?\s*(\d{4})", label.split("-")[-1] if "-" in label else label)
    if not m:
        return None
    word = m.group(1).lower()
    close = difflib.get_close_matches(word, MONTHS, n=1, cutoff=0.7) or [x for x in MONTHS if x.startswith(word[:3])]
    if not close:
        return None
    return m.group(2), str(MONTHS.index(close[0]) + 1).zfill(2)


def _scrape_archive() -> list[dict]:
    """Scrape city archive page; return list of {year, month, url} dicts."""
    resp = net.get(ARCHIVE_URL, timeout=20)
    resp.raise_for_status()
    time.sleep(1)

    soup = BeautifulSoup(resp.text, "html.parser")
    container = soup.find("div", {"id": "modulecontent"})
    if not container:
        return []

    reports: list[dict] = []
    for link in container.find_all("a"):
        href = link.get("href", "")
        if not href or "?ADID=" not in href.upper():
            continue

        url = urljoin(BASE_URL, href)
        # Fix a known report that has no year in its label
        if "ADID=1500" in href:
            year, month = "2023", "07"
        elif parsed := month_of(link.text):
            year, month = parsed
        else:
            print(f"[{BuildingPermits.slug}] couldn't tell which month this report is: {link.text!r}")
            continue

        reports.append({"year": year, "month": month, "url": url})

    return reports


class BuildingPermits(BaseScraper):
    name = "Spearfish building permit reports"
    slug = "building_permits"
    kind = "building_permit"
    url = ARCHIVE_URL
    dedup_key = "permit_key"
    max_stale_hours = 24 * 7

    def scrape(self) -> list[dict]:
        listed = sorted(_scrape_archive(), key=lambda r: (r["year"], r["month"]), reverse=True)
        if not listed:
            raise RuntimeError("no reports found on the city's archive page")
        folder = reports_dir()
        folder.mkdir(parents=True, exist_ok=True)
        new = []
        for report in listed:
            path = folder / f"{report['year']}-{report['month']}.pdf"
            if path.exists():
                continue
            resp = net.get(report["url"], timeout=60)
            resp.raise_for_status()
            if not resp.content.startswith(b"%PDF"):
                print(f"[{self.slug}] {report['url']} isn't a PDF; skipped")
                continue
            path.write_bytes(resp.content)
            new.append(report)
            print(f"[{self.slug}] new report: {path.name}")
            time.sleep(1)
        records: list[dict] = []
        for report in {id(r): r for r in listed[:RECENT_MONTHS] + new}.values():
            path = folder / f"{report['year']}-{report['month']}.pdf"
            if not path.exists():
                continue
            for r in read_report(path, report["year"], report["month"]):
                r["url"] = report["url"]  # the city's own copy, as the source
                records.append(finish_record(r))
        add_coordinates(records)
        return records


def finish_record(r: dict) -> dict:
    """Fields shared by scraped and seeded permit records."""
    r["title"] = " — ".join(x for x in (r.get("construction_type"), r.get("site_address")) if x)
    r["permit_key"] = f"{r.get('permit_number')}|{r.get('year')}-{str(r.get('month')).zfill(2)}"
    r["address_key"] = geo.normalize_address(r.get("site_address", ""))
    return r


def add_coordinates(records: list[dict]) -> None:
    coords = geo.geocode(r["site_address"] for r in records if r.get("site_address"))
    for r in records:
        if c := coords.get(r.get("address_key", "")):
            r["lat"], r["lon"] = c

"""
scrapers/sources/building_permits.py

Monthly building permit reports (PDF) from the City of Spearfish archive.
Each run parses the most recent RECENT_MONTHS reports and merges them into the
saved history, which is kept indefinitely: with the city's OpenGov portal closed
to the public, these reports are the only ongoing record of permits issued.
History before the scraper (2013–2025) was seeded by scripts/build_planning_archive.py
from the spearfish-building-permits project.
"""

from __future__ import annotations

import re
import tempfile
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers import geo, net
from scrapers.base import BaseScraper

BASE_URL = "https://www.spearfish.gov"  # cityofspearfish.com redirects here
ARCHIVE_URL = f"{BASE_URL}/Archive.aspx?AMID=37"

RECENT_MONTHS = 6

MONTH_YEAR_FORMATS = ["%B %Y", "%B%Y"]

# Permit types to skip (signs, ROW work, grading, burns)
SKIP_TYPES = {
    "VOID",
    "ROW",
    "ROW/GRADING",
    "ROW (2)",
    "SIGN",
    "GRADING PERMIT",
    "BURN PERMIT",
    "SIGN PERMIT",
    "GRADING",
    "ROW PERMIT",
    "BURN",
    "RIGHT OF WAY PERMIT",
    "SING PERMIT",
}

# Manual address fixes for known bad permit IDs (from spearfish-building-permits/const.py)
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


def _is_valid_permit(r: dict) -> bool:
    """Return False for summary/totals rows that slipped through the PDF parser."""
    pid = (r.get("permit_number") or "").strip()
    if not pid:
        return False
    # Section headers ("2026 January Permits") and totals rows ("Total Permits Issued")
    if re.search(r"^total|\d{4}\s+\w+\s+permits?|permits?\s+issued", pid, re.IGNORECASE):
        return False
    # Count rows: small integer permit ID with dollar amounts in type/addr columns
    if re.match(r"^\d{1,4}$", pid):
        ctype = r.get("construction_type", "") or ""
        addr = r.get("site_address", "") or ""
        if ctype.startswith("$") or addr.startswith("$"):
            return False
    return True


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


def _clean_money(val: str | None) -> float | None:
    if not val:
        return None
    val = "".join((val or "").replace("$", "").replace(",", "").split())
    if val in ("", "-", "‐"):
        return None
    try:
        return float(val)
    except ValueError:
        return None


def _parse_pdf(pdf_path: Path, year: str, month: str) -> list[dict]:
    """
    Parse a building permit PDF using pdfplumber.

    Handles the 2025+ format (8-column table):
        permit_id | applicant | address | const_type | valuation | permit_fee | contractor | jurisdiction

    Returns a list of normalized record dicts.
    """
    try:
        import pdfplumber
    except ImportError:
        raise ImportError("pdfplumber is required — run: uv add pdfplumber")

    table_data: list[list] = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if tables:
                table_data.extend(tables[0])

    records: list[dict] = []
    for line in table_data[1:]:
        if not any(line):
            continue
        # Stop at summary / totals block (section header or totals row)
        if line[0] and re.search(
            r"^total|\d{4}\s+\w+\s+permits?|permits?\s+issued",
            line[0],
            re.IGNORECASE,
        ):
            break
        if len(line) < 8:
            continue

        permit_id, applicant, address, const_type, valuation, permit_fee, contractor, jurisdiction = line[:8]

        permit_id = (permit_id or "").strip()
        if not permit_id:
            continue

        const_type_clean = " ".join((const_type or "").split())

        # Skip non-building permit types
        if const_type_clean.upper() in SKIP_TYPES:
            continue

        outside = (jurisdiction or "").lower().strip() not in ("city", "")

        # Use manual address fix if available
        pid_norm = permit_id.replace("/", "-")
        addr = ADDRESS_FIXES.get(pid_norm, address or "")
        addr = " ".join(addr.split())

        records.append(
            {
                "year": year,
                "month": month,
                "date": f"{year}-{month}-01",
                "permit_number": permit_id,
                "applicant_name": " ".join((applicant or "").upper().split()),
                "site_address": addr,
                "construction_type": const_type_clean,
                "category": _categorize(const_type_clean),
                "contractor": " ".join((contractor or "").upper().split()),
                "cost_approximate": _clean_money(valuation),
                "permit_fee": _clean_money(permit_fee),
                "outside_city_limits": outside,
            }
        )

    return records


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
        text = link.text.lower()
        month_year = text.split("permits")[-1].split("report")[-1].strip().lstrip("-").split("(")[0].strip()

        # Fix a known report that has no year in its label
        if "ADID=1500" in href:
            year, month = "2023", "07"
        else:
            parsed = None
            for fmt in MONTH_YEAR_FORMATS:
                try:
                    parsed = datetime.strptime(month_year, fmt)
                    break
                except ValueError:
                    continue
            if not parsed:
                print(f"[BuildingPermits] Could not parse date from link: {link.text!r}")
                continue
            year = str(parsed.year)
            month = str(parsed.month).zfill(2)

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
        reports = sorted(_scrape_archive(), key=lambda r: (r["year"], r["month"]), reverse=True)
        records: list[dict] = []
        for report in reports[:RECENT_MONTHS]:
            with tempfile.TemporaryDirectory() as tmp:
                pdf = Path(tmp) / "report.pdf"
                resp = net.get(report["url"], timeout=60)
                resp.raise_for_status()
                pdf.write_bytes(resp.content)
                parsed = [r for r in _parse_pdf(pdf, report["year"], report["month"]) if _is_valid_permit(r)]
            for r in parsed:
                r["url"] = report["url"]
                finish_record(r)
            records.extend(parsed)
            time.sleep(1)
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

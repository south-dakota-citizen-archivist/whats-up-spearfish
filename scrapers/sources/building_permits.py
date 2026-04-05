"""
scrapers/sources/building_permits.py

Downloads and parses monthly building permit PDF reports from the City of Spearfish.
Historical data (2013–2025-09) must be seeded once from the existing
spearfish-building-permits combined CSV before first deployment.

Seeding (run once locally):
    uv run python -c "
    from scrapers.sources.building_permits import seed_from_csv
    seed_from_csv('/Users/cjwinchester/spearfish-building-permits/spearfish-building-permits.csv')
    "

Ongoing scraping (picks up new PDFs not already in the data file):
    uv run python -c "
    from scrapers.sources.building_permits import fetch_building_permits
    fetch_building_permits()
    "
"""

from __future__ import annotations

import csv
import json
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "building_permits.json"

BASE_URL = "https://www.cityofspearfish.com"
ARCHIVE_URL = f"{BASE_URL}/Archive.aspx?AMID=37"

USER_AGENT = "whats-up-in-spearfish/1.0 (public data aggregator)"

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
        # Stop at summary row
        if line[0] and re.search(r"permits issued", line[0], re.IGNORECASE):
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
    resp = requests.get(ARCHIVE_URL, headers={"User-Agent": USER_AGENT}, timeout=20)
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


def fetch_building_permits() -> None:
    """
    Fetch new building permit PDFs and merge into data/building_permits.json.
    Only downloads PDFs for year-month combos not already present in the data file.
    """
    # Load existing data
    existing: list[dict] = []
    existing_month_urls: dict[str, str] = {}
    if DATA_FILE.exists():
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            existing = raw.get("records") or []
            existing_month_urls = raw.get("month_urls") or {}
        except Exception as exc:
            print(f"[BuildingPermits] Warning: could not load existing data: {exc}")

    covered_months: set[tuple[str, str]] = {
        (str(r.get("year", "")), str(r.get("month", "")).zfill(2)) for r in existing
    }  # noqa

    # Scrape archive — always update month_urls even if no new PDFs
    try:
        archive = _scrape_archive()
    except Exception as exc:
        print(f"[BuildingPermits] Warning: could not scrape archive: {exc}")
        return

    # Update month_urls from archive (merge with existing)
    month_urls = dict(existing_month_urls)
    for item in archive:
        key = f"{item['year']}-{item['month']}"
        month_urls[key] = item["url"]

    new_months = [(r["year"], r["month"], r["url"]) for r in archive if (r["year"], r["month"]) not in covered_months]
    print(
        f"[BuildingPermits] Archive: {len(archive)} reports; {len(covered_months)} covered; {len(new_months)} to fetch"
    )  # noqa

    new_records: list[dict] = []

    for year, month, url in new_months:
        print(f"[BuildingPermits] Downloading {year}-{month} ...")
        tmp_path = Path(tempfile.mktemp(suffix=".pdf"))
        try:
            with requests.get(url, stream=True, headers={"User-Agent": USER_AGENT}, timeout=30) as r:
                r.raise_for_status()
                with open(tmp_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            time.sleep(1)

            records = _parse_pdf(tmp_path, year, month)
            print(f"[BuildingPermits]   Parsed {len(records)} permits from {year}-{month}")
            new_records.extend(records)
        except Exception as exc:
            print(f"[BuildingPermits] Warning: could not process {year}-{month}: {exc}")
        finally:
            tmp_path.unlink(missing_ok=True)

    all_records = existing + new_records
    all_records.sort(
        key=lambda r: (r.get("year", ""), r.get("month", ""), r.get("cost_approximate") or 0), reverse=True
    )

    DATA_FILE.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "month_urls": month_urls,
                "records": all_records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[BuildingPermits] {len(all_records)} total records, {len(month_urls)} month URLs → {DATA_FILE.name}")


def populate_month_urls() -> None:
    """
    One-time backfill: scrape the city archive and add month_urls to the data file.
    Run after seeding from CSV.

    Usage:
        uv run python -c "
        from scrapers.sources.building_permits import populate_month_urls
        populate_month_urls()
        "
    """
    if not DATA_FILE.exists():
        print("[BuildingPermits] No data file found — run seed_from_csv first.")
        return
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[BuildingPermits] Could not read data file: {exc}")
        return

    try:
        archive = _scrape_archive()
    except Exception as exc:
        print(f"[BuildingPermits] Could not scrape archive: {exc}")
        return

    month_urls = raw.get("month_urls") or {}
    for item in archive:
        key = f"{item['year']}-{item['month']}"
        month_urls[key] = item["url"]

    raw["month_urls"] = month_urls
    DATA_FILE.write_text(json.dumps(raw, indent=2), encoding="utf-8")
    print(f"[BuildingPermits] Saved {len(month_urls)} month URLs → {DATA_FILE.name}")


def seed_from_csv(csv_path: str | Path) -> None:
    """
    One-time seed: import historical records from the combined spearfish-building-permits CSV.
    Run this locally before first deployment, then commit data/building_permits.json.

    Usage:
        uv run python -c "
        from scrapers.sources.building_permits import seed_from_csv
        seed_from_csv('/Users/cjwinchester/spearfish-building-permits/spearfish-building-permits.csv')
        "
    """
    csv_path = Path(csv_path).expanduser()
    records: list[dict] = []

    with open(csv_path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            year = str(row.get("year", "")).strip()
            month = str(row.get("month", "")).strip().zfill(2)
            const_type = (row.get("construction_type") or "").strip()

            # Skip non-building permit types
            if const_type.upper() in SKIP_TYPES:
                continue

            outside_raw = (row.get("outside_city_limits") or "").strip().lower()
            outside = outside_raw == "true"

            records.append(
                {
                    "year": year,
                    "month": month,
                    "date": f"{year}-{month}-01",
                    "permit_number": (row.get("permit_number") or "").strip(),
                    "applicant_name": (row.get("applicant_name") or "").strip(),
                    "site_address": (row.get("site_address") or "").strip(),
                    "construction_type": const_type,
                    "category": _categorize(const_type),
                    "contractor": (row.get("contractor") or "").strip(),
                    "cost_approximate": _clean_money(row.get("cost_approximate")),
                    "permit_fee": _clean_money(row.get("permit_fee")),
                    "outside_city_limits": outside,
                }
            )

    records.sort(key=lambda r: (r.get("year", ""), r.get("month", ""), r.get("cost_approximate") or 0), reverse=True)

    DATA_FILE.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "records": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[BuildingPermits] Seeded {len(records)} records from {csv_path}")
    print(f"[BuildingPermits] → {DATA_FILE}")


if __name__ == "__main__":
    fetch_building_permits()

"""
scrapers/sources/planning_zoning.py

Fetches permit and application records from the ViewpointCloud REST API
for Spearfish, SD. Accumulates history across runs by merging with the
existing data file (old records are kept, new ones added).

Not a BaseScraper subclass — run directly or from the daily scrape workflow.

Usage:
    uv run python -c "
    from scrapers.sources.planning_zoning import fetch_planning_zoning
    fetch_planning_zoning()
    "
"""

from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "planning_zoning.json"

BASE_URL = "https://api-east.viewpointcloud.com/v2/spearfishsd"

_HEADERS = {
    "User-Agent": "whats-up-in-spearfish/1.0 (public data aggregator)",
    "Accept": "application/json",
}

# ---------------------------------------------------------------------------
# Category mapping
# ---------------------------------------------------------------------------

CATEGORIES: dict[int, str] = {
    6476: "new_construction",  # Residential New Construction
    6477: "new_construction",  # Commercial New Construction
    6479: "alterations",  # Residential Additions or Alterations
    6478: "alterations",  # Commercial Alterations, Additions, or Tenant Improvements
    6480: "alterations",  # Residential Decks, Covered Patios, or Fences
    6482: "alterations",  # Residential Demolition
    6481: "alterations",  # Commercial Demolition
    6541: "alterations",  # Change of Use or Occupancy
    6516: "alterations",  # Floodplain Development
    6429: "planning",  # Rezone
    6459: "planning",  # Conditional Use Permit
    6543: "planning",  # Variance Application
    6549: "planning",  # Annexation
    6550: "planning",  # Tax Increment Financing (TIF)
    6555: "planning",  # Zoning Text Amendment
    6456: "planning",  # Sketch Plat
    6457: "planning",  # Minor Final Plat
    6436: "planning",  # Major Preliminary Plat
    6439: "planning",  # Major Final Plat
    6513: "planning",  # Subdivision Development Plans
    6475: "planning",  # Development Review District
    6440: "infrastructure",  # Right of Way Permit
    6467: "infrastructure",  # Grading Permit
    6464: "infrastructure",  # Encroachment Agreement Request
    6515: "infrastructure",  # Water/Sewer Service Agreement
    6544: "infrastructure",  # Vacate of Right of Way or Easement
    6460: "infrastructure",  # Sign Permit
    6514: "infrastructure",  # Standalone Permits
    6359: "infrastructure",  # Fire Code Permit
}

# Record type IDs to skip entirely
SKIP_TYPES: set[int] = {6428, 6540}

PORTAL_BASE = "https://spearfishsd.portal.opengov.com/records"

LIMIT = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get(path: str, params: dict | None = None) -> dict:
    url = f"{BASE_URL}{path}"
    resp = requests.get(url, headers=_HEADERS, params=params, timeout=30)
    resp.raise_for_status()
    return resp.json()


def _fetch_record_type_ids() -> list[int]:
    """
    Fetch /record_types and return IDs for non-skipped types we track.
    Falls back to hardcoded CATEGORIES keys if the endpoint fails.
    """
    try:
        data = _get("/record_types")
        ids = []
        # Response is JSON:API: {"data": [{"id": "6440", "type": "record_types", ...}]}
        for rt in data.get("data") or data.get("record_types") or []:
            rid = int(rt["id"])
            if rid not in SKIP_TYPES and rid in CATEGORIES:
                ids.append(rid)
        print(f"[planning_zoning] {len(ids)} record type(s) from API")
        return ids
    except Exception as exc:
        print(f"[planning_zoning] Warning: could not fetch record_types ({exc}); using hardcoded list")
        return [rid for rid in CATEGORIES if rid not in SKIP_TYPES]


def _normalize(attrs: dict) -> dict:
    """Flatten a JSON:API record attributes dict into our normalized format."""
    record_id = int(attrs.get("recordID") or 0)
    record_type_id = int(attrs.get("recordTypeID") or 0)

    # Address: prefer fullAddress, fall back to streetNo + streetName
    address = (attrs.get("fullAddress") or "").strip()
    if not address:
        parts = [str(attrs.get("streetNo") or ""), str(attrs.get("streetName") or "")]
        address = " ".join(p for p in parts if p).strip()
    # Treat placeholder "0 No Street..." values as blank
    if address.lower().startswith("0 no street"):
        address = ""

    # Lat/lon: store as float; treat 0.0 or missing as None
    def _coord(val) -> float | None:
        try:
            f = float(val)
            return f if f != 0.0 else None
        except (TypeError, ValueError):
            return None

    # Applicant: prefer applicantFullName, fall back to ownerName
    applicant = (attrs.get("applicantFullName") or attrs.get("ownerName") or "").strip()

    return {
        "id": record_id,
        "record_no": attrs.get("recordNo") or "",
        "record_type": attrs.get("recordTypeName") or "",
        "record_type_id": record_type_id,
        "category": CATEGORIES.get(record_type_id, "infrastructure"),
        "status": attrs.get("status"),
        "date_created": attrs.get("dateCreated") or "",
        "date_submitted": attrs.get("dateSubmitted") or "",
        "last_updated": attrs.get("lastUpdatedDate") or "",
        "address": address,
        "lat": _coord(attrs.get("latitude")),
        "lon": _coord(attrs.get("longitude")),
        "applicant": applicant,
        "portal_url": f"{PORTAL_BASE}/{record_id}",
    }


def _fetch_all_for_type(record_type_id: int) -> list[dict]:
    """Paginate through all records for a given record type ID."""
    records: list[dict] = []
    offset = 0

    while True:
        try:
            data = _get(
                "/records",
                params={"recordTypeID": record_type_id, "offset": offset, "limit": LIMIT},
            )
        except Exception as exc:
            print(f"  [planning_zoning] Warning: type {record_type_id} offset {offset}: {exc}")
            break

        items = data.get("data") or []
        for item in items:
            attrs = item.get("attributes") or {}
            if not attrs.get("isEnabled", True):
                continue
            records.append(_normalize(attrs))

        total = (data.get("meta") or {}).get("total", 0)
        offset += len(items)

        if not items or offset >= total:
            break

        time.sleep(0.2)

    return records


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def fetch_planning_zoning() -> None:
    type_ids = _fetch_record_type_ids()

    # Load existing records to merge (accumulate history)
    existing: dict[int, dict] = {}
    if DATA_FILE.exists():
        try:
            raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
            for r in raw.get("records") or []:
                existing[r["id"]] = r
            print(f"[planning_zoning] Loaded {len(existing)} existing record(s) from {DATA_FILE.name}")
        except Exception as exc:
            print(f"[planning_zoning] Warning: could not read existing data: {exc}")

    # Fetch fresh records from API
    fresh: dict[int, dict] = {}
    for type_id in type_ids:
        records = _fetch_all_for_type(type_id)
        for r in records:
            fresh[r["id"]] = r
        type_name = records[0]["record_type"] if records else str(type_id)
        print(f"  {type_name}: {len(records)} record(s)")

    # Merge: start with existing, overwrite/add fresh records
    merged = {**existing, **fresh}

    # Filter out isEnabled=false records (already excluded during fetch,
    # but also purge any that may have been disabled since last run)
    # We can only do this for types we fetched; existing-only records stay.
    all_records = list(merged.values())

    # Sort by date_created descending (empty strings sort last)
    all_records.sort(key=lambda r: r.get("date_created") or "", reverse=True)

    DATA_FILE.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "records": all_records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[planning_zoning] {len(all_records)} total record(s) → {DATA_FILE.name}")


if __name__ == "__main__":
    fetch_planning_zoning()

"""
scripts/fetch_bh_county_plant_ids.py

Queries the USDA PLANTS API for each Black Hills county and collects
the set of plant IDs that actually occur there.  Writes the result to
data/bh_county_plant_ids.json (a sorted list of integer IDs).

Run once to generate the filter file; re-run to refresh.

Usage:
    uv run python scripts/fetch_bh_county_plant_ids.py
"""

from __future__ import annotations

import json
import math
import time
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Black Hills counties: (PlantLocationId, display_name)
# SD: Lawrence, Pennington, Meade, Custer, Butte, Fall River, Harding
# WY: Crook, Weston, Campbell
# ---------------------------------------------------------------------------
BH_COUNTIES = [
    (326, "Lawrence"),
    (339, "Pennington"),
    (276, "Meade"),
    (402, "Custer"),
    (267, "Butte"),
    (455, "Fall River"),
    (206, "Harding"),
    (285, "Crook"),
    (375, "Weston"),
    (287, "Campbell"),
]

OUTPUT = Path(__file__).resolve().parent.parent / "data" / "bh_county_plant_ids.json"
PAGE_SIZE = 25  # what the API returns per page
SLEEP = 0.3  # seconds between requests
API = "https://plantsservices.sc.egov.usda.gov/api/plants-search-results"
HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Content-Type": "application/json",
    "Origin": "https://plants.sc.egov.usda.gov",
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
}


def _base_body(location_id: int, location_name: str) -> dict:
    return {
        "Text": None,
        "Field": None,
        "Locations": [
            {
                "PlantLocationId": location_id,
                "PlantLocationName": location_name,
                "PlantLocationCategory": None,
                "countyName": None,
            }
        ],
        "Groups": None,
        "Durations": None,
        "GrowthHabits": None,
        "WetlandRegions": None,
        "NoxiousLocations": None,
        "InvasiveLocations": None,
        "Countries": None,
        "Provinces": None,
        "Counties": None,
        "Cities": None,
        "Localities": None,
        "ArtistFirstLetters": None,
        "ImageLocations": None,
        "Artists": None,
        "CopyrightStatuses": None,
        "ImageReferences": None,
        "ImageTypes": None,
        "SortBy": "sortSciName",
        "Offset": -1,
        "FilterOptions": None,
        "UnfilteredPlantIds": None,
        "Type": "State",
        "TaxonSearchCriteria": None,
        "MasterId": -1,
        "allData": 0,
    }


def fetch_county(location_id: int, name: str) -> set[int]:
    """Return the set of plant IDs found in this county."""
    ids: set[int] = set()
    page = 1
    total_pages = 1

    while page <= total_pages:
        body = _base_body(location_id, name)
        body["pageNumber"] = page

        # Retry up to 3 times per page
        data = None
        for attempt in range(3):
            try:
                resp = requests.post(API, json=body, headers=HEADERS, timeout=20)
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as e:
                wait = 2**attempt
                print(f"    page {page} attempt {attempt + 1} error: {type(e).__name__} — retrying in {wait}s")
                time.sleep(wait)

        if data is None:
            print(f"    page {page} failed after 3 attempts — skipping")
            page += 1
            continue

        results = data.get("PlantResults") or []
        total = data.get("TotalResults", 0)
        if page == 1:
            total_pages = math.ceil(total / PAGE_SIZE) if total else 1
            print(f"  {name}: {total} plants, {total_pages} pages")

        for r in results:
            if r.get("Id"):
                ids.add(r["Id"])
            if r.get("AcceptedId"):
                ids.add(r["AcceptedId"])

        page += 1
        if page <= total_pages:
            time.sleep(SLEEP)

    return ids


def main() -> None:
    all_ids: set[int] = set()
    for loc_id, name in BH_COUNTIES:
        print(f"Fetching {name} county …")
        county_ids = fetch_county(loc_id, name)
        print(f"  → {len(county_ids)} IDs (running total: {len(all_ids | county_ids)})")
        all_ids |= county_ids

    sorted_ids = sorted(all_ids)
    OUTPUT.write_text(json.dumps(sorted_ids, indent=2), encoding="utf-8")
    print(f"\nWrote {len(sorted_ids)} unique plant IDs → {OUTPUT.name}")


if __name__ == "__main__":
    main()

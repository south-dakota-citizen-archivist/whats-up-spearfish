"""
scrapers/sources/ebird.py

Fetches recent bird sightings near Spearfish, SD from the eBird API,
then enriches each unique species with a photo from iNaturalist.

Requires EBIRD_API_KEY in the environment (free at https://ebird.org/api/keygen).

Not a BaseScraper subclass — run directly or from the daily scrape workflow.

Usage:
    uv run python -c "from scrapers.sources.ebird import fetch_ebird; fetch_ebird()"
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "ebird.json"

LAT, LNG    = 44.48, -103.86
RADIUS_KM   = 50
MAX_RESULTS = 50
BACK_DAYS   = 14

EBIRD_API = "https://api.ebird.org/v2"
INAT_API  = "https://api.inaturalist.org/v1"
INAT_HEADERS = {
    "User-Agent": "whats-up-in-spearfish/1.0",
    "Accept": "application/json",
}


def _inat_photo(scientific_name: str) -> str:
    """Return a square photo URL from iNaturalist for the given species, or ''."""
    parts = scientific_name.split()
    query = " ".join(parts[:2]) if len(parts) >= 2 else scientific_name
    try:
        resp = requests.get(
            f"{INAT_API}/taxa/autocomplete",
            params={"q": query, "rank": "species", "per_page": 3},
            headers=INAT_HEADERS,
            timeout=10,
        )
        if not resp.ok:
            return ""
        for result in resp.json().get("results") or []:
            name = result.get("name", "").lower()
            if name.startswith(query.lower()):
                photo = result.get("default_photo") or {}
                return photo.get("square_url") or ""
    except Exception:
        pass
    return ""


def fetch_ebird() -> None:
    api_key = os.environ.get("EBIRD_API_KEY", "")
    if not api_key:
        print("[eBird] EBIRD_API_KEY not set — skipping")
        DATA_FILE.write_text(
            json.dumps({"fetched_at": None, "observations": []}, indent=2),
            encoding="utf-8",
        )
        return

    headers = {"X-eBirdApiToken": api_key}

    try:
        resp = requests.get(
            f"{EBIRD_API}/data/obs/geo/recent",
            headers=headers,
            params={
                "lat": LAT, "lng": LNG, "dist": RADIUS_KM,
                "back": BACK_DAYS, "maxResults": MAX_RESULTS,
                "includeProvisional": "true", "fmt": "json",
            },
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json()
    except Exception as exc:
        print(f"[eBird] Warning: fetch failed: {exc}")
        return

    # Fetch iNat photos for each unique species (by scientific name)
    photo_cache: dict[str, str] = {}
    seen_sci: set[str] = set()
    for obs in raw:
        sci = obs.get("sciName", "")
        if sci and sci not in seen_sci:
            seen_sci.add(sci)
            photo_cache[sci] = _inat_photo(sci)
            time.sleep(0.3)

    print(f"[eBird] photos: {sum(1 for v in photo_cache.values() if v)}/{len(photo_cache)} found")

    observations = []
    for obs in raw:
        sci = obs.get("sciName", "")
        observations.append({
            "species_code":    obs.get("speciesCode", ""),
            "common_name":     obs.get("comName", ""),
            "scientific_name": sci,
            "observed_on":     obs.get("obsDt", "")[:10],
            "count":           obs.get("howMany"),
            "location_name":   obs.get("locName", ""),
            "lat":             obs.get("lat"),
            "lng":             obs.get("lng"),
            "location_id":     obs.get("locId", ""),
            "checklist_id":    obs.get("subId", ""),
            "photo_url":       photo_cache.get(sci, ""),
        })

    DATA_FILE.write_text(
        json.dumps(
            {"fetched_at": datetime.now(timezone.utc).isoformat(), "observations": observations},
            indent=2, ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(f"[eBird] {len(observations)} recent sightings → {DATA_FILE.name}")


if __name__ == "__main__":
    fetch_ebird()

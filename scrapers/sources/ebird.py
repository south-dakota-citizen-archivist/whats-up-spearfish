"""
scrapers/sources/ebird.py

Fetches recent bird sightings near Spearfish, SD from the eBird API,
then enriches each unique species with a photo from iNaturalist.

Requires EBIRD_API_KEY in the environment (free at https://ebird.org/api/keygen).

"""

from __future__ import annotations

import os
import time

from scrapers import dates, net
from scrapers.base import BaseScraper

LAT, LNG = 44.48, -103.86
RADIUS_KM = 50
MAX_RESULTS = 50
BACK_DAYS = 14

EBIRD_API = "https://api.ebird.org/v2"
INAT_API = "https://api.inaturalist.org/v1"
INAT_HEADERS = {
    "User-Agent": net.USER_AGENT,
    "Accept": "application/json",
}


def _inat_photo(scientific_name: str) -> str:
    """Return a square photo URL from iNaturalist for the given species, or ''."""
    parts = scientific_name.split()
    query = " ".join(parts[:2]) if len(parts) >= 2 else scientific_name
    try:
        resp = net.get(
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


class EBird(BaseScraper):
    name = "eBird recent sightings"
    slug = "ebird"
    kind = "sighting"
    url = "https://ebird.org/region/US-SD-081"
    replace = True
    dedup_key = "obs_key"
    naive_tz = dates.MT  # obsDt is local time

    def scrape(self) -> list[dict]:
        api_key = os.environ.get("EBIRD_API_KEY", "")
        if not api_key:
            raise RuntimeError("EBIRD_API_KEY not set")

        resp = net.get(
            f"{EBIRD_API}/data/obs/geo/recent",
            headers={"X-eBirdApiToken": api_key},
            params={
                "lat": LAT,
                "lng": LNG,
                "dist": RADIUS_KM,
                "back": BACK_DAYS,
                "maxResults": MAX_RESULTS,
                "includeProvisional": "true",
                "fmt": "json",
            },
            timeout=20,
        )
        resp.raise_for_status()
        raw = resp.json()

        # One iNaturalist photo lookup per species
        photos: dict[str, str] = {}
        for obs in raw:
            sci = obs.get("sciName", "")
            if sci and sci not in photos:
                photos[sci] = _inat_photo(sci)
                time.sleep(0.3)

        observations = []
        for obs in raw:
            sci = obs.get("sciName", "")
            sub_id = obs.get("subId", "")
            observations.append(
                {
                    "obs_key": f"{sub_id}:{obs.get('speciesCode', '')}",
                    "title": obs.get("comName", ""),
                    "url": f"https://ebird.org/checklist/{sub_id}" if sub_id else self.url,
                    "species_code": obs.get("speciesCode", ""),
                    "common_name": obs.get("comName", ""),
                    "scientific_name": sci,
                    "observed_on": obs.get("obsDt", ""),
                    "count": obs.get("howMany"),
                    "location_name": obs.get("locName", ""),
                    "lat": obs.get("lat"),
                    "lng": obs.get("lng"),
                    "location_id": obs.get("locId", ""),
                    "checklist_id": sub_id,
                    "photo_url": photos.get(sci, ""),
                }
            )
        return observations

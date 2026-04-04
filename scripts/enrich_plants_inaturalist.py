"""
scripts/enrich_plants_inaturalist.py

For every plant in data/native_plants_spotlight.json, fetches:
  - The iNaturalist taxon ID (via /taxa/autocomplete)
  - Recent research-grade observations within 100 km of Spearfish, SD

Writes data/inaturalist_plant_cache.json — a dict keyed by USDA symbol:
  {
    "BASA3": {
      "taxon_id": 62266,
      "inat_url": "https://www.inaturalist.org/taxa/62266",
      "nearby_obs_count": 34,
      "recent_obs": [
        {
          "id": 304842327,
          "url": "https://www.inaturalist.org/observations/304842327",
          "observed_on": "2025-08-08",
          "observer": "marisaszubryt",
          "photo_url": "https://static.inaturalist.org/photos/.../medium.jpg",
          "place_guess": "Black Hills National Forest"
        },
        ...
      ]
    },
    ...
  }

Run once to populate, then re-run to refresh. Already-cached entries are
skipped on re-run (delete the file to force a full refresh).

Usage:
    uv run python scripts/enrich_plants_inaturalist.py
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
SPOTLIGHT = ROOT / "data" / "native_plants_spotlight.json"
CACHE_FILE = ROOT / "data" / "inaturalist_plant_cache.json"

INAT_API = "https://api.inaturalist.org/v1"
# Spearfish, SD
LAT, LNG = 44.48, -103.86
RADIUS_KM = 100
OBS_PER_PLANT = 3  # most recent research-grade observations to store
SLEEP = 0.5  # seconds between requests — be polite

HEADERS = {
    "User-Agent": "whats-up-in-spearfish/1.0 (https://github.com/south-dakota-citizen-archivist/whats-up-spearfish)",
    "Accept": "application/json",
}


def _get(path: str, params: dict | None = None, timeout: int = 15) -> dict | None:
    try:
        resp = requests.get(f"{INAT_API}{path}", params=params, headers=HEADERS, timeout=timeout)
        if resp.status_code == 429:
            print("  rate limited — sleeping 60s")
            time.sleep(60)
            resp = requests.get(f"{INAT_API}{path}", params=params, headers=HEADERS, timeout=timeout)
        if not resp.ok:
            return None
        return resp.json()
    except Exception as e:
        print(f"  request error: {e}")
        return None


def _taxon_id(scientific_name: str) -> int | None:
    """Return the iNaturalist taxon ID for a scientific name, or None."""
    # Strip author suffixes — iNat autocomplete works best with just genus + epithet
    parts = scientific_name.split()
    query = " ".join(parts[:2]) if len(parts) >= 2 else scientific_name
    data = _get("/taxa/autocomplete", {"q": query, "rank": "species", "per_page": 5})
    if not data:
        return None
    for result in data.get("results") or []:
        # Match on the bare genus+species
        name = result.get("name", "").lower()
        q = query.lower()
        if name == q or name.startswith(q + " "):
            return result["id"]
    # Fallback: take the first result if it shares the genus
    results = data.get("results") or []
    if results and results[0].get("name", "").lower().split()[0] == query.lower().split()[0]:
        return results[0]["id"]
    return None


def _recent_obs(taxon_id: int) -> tuple[int, list[dict]]:
    """
    Return (total_count, [recent_obs_dicts]) for research-grade observations
    within RADIUS_KM of Spearfish.
    """
    data = _get(
        "/observations",
        {
            "taxon_id": taxon_id,
            "lat": LAT,
            "lng": LNG,
            "radius": RADIUS_KM,
            "quality_grade": "research",
            "order_by": "observed_on",
            "order": "desc",
            "per_page": OBS_PER_PLANT,
            "photos": "true",
        },
    )
    if not data:
        return 0, []

    total = data.get("total_results", 0)
    obs_list = []
    for obs in data.get("results") or []:
        photo_url = ""
        photos = obs.get("photos") or []
        if photos:
            raw = photos[0].get("url") or ""
            # iNat square URLs end in /square.jpg — swap for medium
            photo_url = raw.replace("/square.", "/medium.")

        obs_list.append(
            {
                "id": obs.get("id"),
                "url": obs.get("uri") or f"https://www.inaturalist.org/observations/{obs.get('id')}",
                "observed_on": obs.get("observed_on") or "",
                "observer": (obs.get("user") or {}).get("login") or "",
                "photo_url": photo_url,
                "place_guess": obs.get("place_guess") or "",
            }
        )

    return total, obs_list


def main() -> None:
    if not SPOTLIGHT.exists():
        print(f"Spotlight file not found: {SPOTLIGHT}")
        return

    plants = json.loads(SPOTLIGHT.read_text(encoding="utf-8"))
    print(f"Loaded {len(plants)} plants from spotlight pool")

    # Load existing cache
    cache: dict[str, dict] = {}
    if CACHE_FILE.exists():
        cache = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
        print(f"Resuming — {len(cache)} symbols already cached")

    newly_fetched = 0

    for i, plant in enumerate(plants):
        symbol = plant.get("symbol", "")
        sci_name = plant.get("scientific_name", "")
        if not symbol or not sci_name:
            continue

        if symbol in cache:
            continue  # already done

        print(f"[{i + 1}/{len(plants)}] {symbol} {sci_name} …", end=" ", flush=True)

        time.sleep(SLEEP)
        taxon_id = _taxon_id(sci_name)
        if not taxon_id:
            print("no taxon match")
            cache[symbol] = {"taxon_id": None, "inat_url": None, "nearby_obs_count": 0, "recent_obs": []}
            newly_fetched += 1
            continue

        time.sleep(SLEEP)
        total, recent = _recent_obs(taxon_id)

        inat_url = f"https://www.inaturalist.org/taxa/{taxon_id}"
        print(f"taxon={taxon_id}, nearby={total}, photos={len(recent)}")

        cache[symbol] = {
            "taxon_id": taxon_id,
            "inat_url": inat_url,
            "nearby_obs_count": total,
            "recent_obs": recent,
        }
        newly_fetched += 1

        # Save incrementally every 10 plants
        if newly_fetched % 10 == 0:
            CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")

    CACHE_FILE.write_text(json.dumps(cache, indent=2, ensure_ascii=False), encoding="utf-8")

    with_obs = sum(1 for v in cache.values() if v.get("nearby_obs_count", 0) > 0)
    print(f"\nDone. {len(cache)} symbols cached, {with_obs} have nearby observations.")
    print(f"→ {CACHE_FILE.name}")


if __name__ == "__main__":
    main()

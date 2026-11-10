"""
scrapers/geo.py

Address keys and geocoding for Spearfish addresses, on sdplaces.geocode.

- normalize_address() turns "2312 Platinum Drive, Spearfish, SD 57783" and "2312 PLATINUM DR"
  into the same key (via scrapers.address), so records from different sources can be grouped
  by site.
- geocode() resolves addresses to (lat, lon) with the free US Census batch geocoder, caching
  every answer (including misses) in {DATA_DIR}/_geocode_cache.json so each address is only
  ever looked up once.
- locate_streets() is the fallback for what the Census misses, mostly houses on streets too
  new for its map: OpenStreetMap's Nominatim, which often has the new street if not the house
  number. Answers go in {DATA_DIR}/_geocode_osm.json as [lat, lon, "house"] (the house
  itself) or [lat, lon, "street"] (somewhere on the street: approximate); a miss is retried
  after a month. Nominatim asks for one request a second at most.
"""

from __future__ import annotations

from datetime import date

from sdplaces.geocode import Box, Geocoder, JsonCache

from scrapers import address, base

# Rough box around Spearfish and its outskirts; coordinates outside it are bad data.
SPEARFISH = Box(min_lat=44.40, max_lat=44.60, min_lon=-104.05, max_lon=-103.70)

# A requests-like session for the lookups (tests swap in a fake); None for a fresh one.
session = None


def in_spearfish(lat, lon) -> bool:
    return SPEARFISH(lat, lon)


def normalize_address(text: str) -> str:
    """Matching key for a street address ('' if there's no usable house number + street)."""
    return address.key(text)


def geocoder(cache: dict | None = None) -> Geocoder:
    return Geocoder(
        city="Spearfish",
        zip="57783",
        within=SPEARFISH,
        cache=JsonCache(base.DATA_DIR / "_geocode_cache.json") if cache is None else cache,
        osm_cache=JsonCache(base.DATA_DIR / "_geocode_osm.json"),
        session=session,
    )


def geocode(addresses, cache: dict | None = None) -> dict:
    """Map normalized address keys to [lat, lon] (or None when unmatched). Only keys missing
    from the cache are looked up; the cache file is saved as it goes."""
    return geocoder(cache).batch(addresses)


def locate_streets(keys, limit: int = 300, today: date | None = None) -> dict:
    """OpenStreetMap positions for address keys the Census couldn't place (see the module
    notes). Looks up at most `limit` keys a run, so a backlog can't stall a scrape."""
    return geocoder().locate_streets(keys, limit, today)

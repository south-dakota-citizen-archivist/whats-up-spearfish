"""
scrapers/geo.py

Address normalization and geocoding for Spearfish addresses.

- normalize_address() turns "2312 Platinum Drive, Spearfish, SD 57783" and
  "2312 PLATINUM DR" into the same key, so records from different sources
  can be grouped by site.
- geocode() resolves addresses to (lat, lon) with the free US Census batch
  geocoder, caching every answer (including misses) in {DATA_DIR}/_geocode_cache.json
  so each address is only ever looked up once.
"""

from __future__ import annotations

import csv
import io
import json
import re

from scrapers import base, net

# Rough box around Spearfish and its outskirts; coordinates outside it are bad data.
BBOX = {"min_lat": 44.40, "max_lat": 44.60, "min_lon": -104.05, "max_lon": -103.70}

CENSUS_BATCH = "https://geocoding.geo.census.gov/geocoder/locations/addressbatch"
BATCH_SIZE = 2000

_SUFFIXES = {
    "STREET": "ST",
    "AVENUE": "AVE",
    "AV": "AVE",
    "DRIVE": "DR",
    "ROAD": "RD",
    "LANE": "LN",
    "COURT": "CT",
    "CIRCLE": "CIR",
    "PLACE": "PL",
    "BOULEVARD": "BLVD",
    "PARKWAY": "PKWY",
    "HIGHWAY": "HWY",
    "TRAIL": "TRL",
    "TERRACE": "TER",
    "LOOP": "LOOP",
    "WAY": "WAY",
    "NORTH": "N",
    "SOUTH": "S",
    "EAST": "E",
    "WEST": "W",
}
_CITY_RE = re.compile(r",?\s*(SPEARFISH|SPEARISH)\b.*$")


def in_spearfish(lat, lon) -> bool:
    try:
        lat, lon = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    return BBOX["min_lat"] <= lat <= BBOX["max_lat"] and BBOX["min_lon"] <= lon <= BBOX["max_lon"]


def normalize_address(address: str) -> str:
    """Comparable key for a street address ('' if there's no usable house number + street)."""
    s = (address or "").upper()
    s = _CITY_RE.sub("", s)
    s = re.sub(r",?\s*SD\s*\d{5}(-\d{4})?\s*$", "", s)
    s = re.sub(r"[^\w\s&/-]", " ", s)
    words = [_SUFFIXES.get(w, w) for w in s.split()]
    if len(words) < 2 or not re.match(r"^\d", words[0]):
        return ""
    # Group units/suites with their building: drop "UNIT 3", "STE B", "#4" and a bare trailing unit number
    for i, w in enumerate(words[1:], 1):
        if w in ("UNIT", "STE", "SUITE", "APT", "BLDG", "LOT", "SPACE") or w.startswith("#"):
            words = words[:i]
            break
    street_suffixes = set(_SUFFIXES.values()) - {"N", "S", "E", "W", "HWY"}
    if len(words) > 2 and re.fullmatch(r"\d+[A-Z]?", words[-1]) and words[-2] in street_suffixes:
        words = words[:-1]
    # "515 27TH ST N" and "515 N 27TH ST" are the same place
    if len(words) > 2 and words[-1] in ("N", "S", "E", "W") and words[1] not in ("N", "S", "E", "W"):
        words = [words[0], words[-1], *words[1:-1]]
    return " ".join(words)


def _cache_path():
    return base.DATA_DIR / "_geocode_cache.json"


def load_cache() -> dict:
    try:
        return json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def save_cache(cache: dict) -> None:
    _cache_path().parent.mkdir(parents=True, exist_ok=True)
    _cache_path().write_text(json.dumps(cache, sort_keys=True, separators=(",", ":")), encoding="utf-8")


def _census_batch(keys: list[str]) -> dict[str, list | None]:
    buf = io.StringIO()
    w = csv.writer(buf)
    for i, k in enumerate(keys):
        w.writerow([i, k, "Spearfish", "SD", "57783"])
    resp = net.post(
        CENSUS_BATCH,
        files={"addressFile": ("addresses.csv", buf.getvalue(), "text/csv")},
        data={"benchmark": "Public_AR_Current"},
        timeout=600,
    )
    resp.raise_for_status()
    out: dict[str, list | None] = {k: None for k in keys}
    for row in csv.reader(io.StringIO(resp.text)):
        if len(row) >= 6 and row[2] == "Match" and row[5]:
            lon, lat = (float(x) for x in row[5].split(","))
            if in_spearfish(lat, lon):
                out[keys[int(row[0])]] = [round(lat, 6), round(lon, 6)]
    return out


def geocode(addresses, cache: dict | None = None) -> dict:
    """
    Map normalized address keys to [lat, lon] (or None when unmatched).
    Only keys missing from the cache hit the network; the cache is updated in place and saved.
    """
    own_cache = cache is None
    cache = load_cache() if own_cache else cache
    keys = sorted({normalize_address(a) for a in addresses} - {""})
    todo = [k for k in keys if k not in cache]
    for i in range(0, len(todo), BATCH_SIZE):
        chunk = todo[i : i + BATCH_SIZE]
        print(f"[geo] geocoding {len(chunk)} address(es) via Census ({i + len(chunk)}/{len(todo)})")
        cache.update(_census_batch(chunk))
    if todo and own_cache:
        save_cache(cache)
    return {k: cache.get(k) for k in keys}

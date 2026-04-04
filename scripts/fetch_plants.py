"""
Fetch USDA PLANTS data for native Black Hills plants.

Steps:
1. Download complete plant symbol list from plantlst.txt
2. Fetch PlantProfile for every symbol (threadpool, 4 workers)
3. Filter to plants native to L48 whose CONUS bbox overlaps the Black Hills
4. Fetch supplemental endpoints for each filtered plant
5. Write results to data/plants_native_black_hills.json
"""

import csv
import io
import json
import time
import sys
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BASE_API = "https://plantsservices.sc.egov.usda.gov/api"
BASE_IMAGES = "https://plants.sc.egov.usda.gov"
PLANT_LIST_URL = "https://plants.sc.egov.usda.gov/DocumentLibrary/Txt/plantlst.txt"
OUTPUT_PATH = Path("/Users/cjwinchester/whats-up-in-spearfish/data/plants_native_black_hills.json")
CACHE_DIR = Path("/Users/cjwinchester/whats-up-in-spearfish/data/.plants_cache")
PROFILES_CACHE = CACHE_DIR / "profiles.json"
ENRICHED_CACHE_DIR = CACHE_DIR / "enriched"

# Black Hills bounding box (lon_min, lat_min, lon_max, lat_max)
BH_XMIN, BH_YMIN, BH_XMAX, BH_YMAX = -104.5, 43.5, -103.0, 45.0

MAX_WORKERS = 4
SLEEP_BETWEEN = 0.1  # seconds between sequential calls per thread

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"Accept": "application/json", "User-Agent": "whats-up-in-spearfish/1.0"})
    return s


def bbox_overlaps(plant_xmin, plant_ymin, plant_xmax, plant_ymax,
                  ref_xmin, ref_ymin, ref_xmax, ref_ymax) -> bool:
    """Return True if two bounding boxes overlap (touch counts)."""
    return (
        plant_xmin <= ref_xmax and plant_xmax >= ref_xmin and
        plant_ymin <= ref_ymax and plant_ymax >= ref_ymin
    )


# ---------------------------------------------------------------------------
# Step 1: Fetch plant symbol list
# ---------------------------------------------------------------------------

def fetch_symbol_list(session: requests.Session) -> list[str]:
    log.info("Fetching plant symbol list from %s", PLANT_LIST_URL)
    # Override Accept for plain-text file — server rejects application/json
    resp = session.get(PLANT_LIST_URL, timeout=60, headers={"Accept": "text/plain,*/*"})
    resp.raise_for_status()
    # File is quoted CSV (not TSV as docs suggest); may have synonym rows with
    # the same symbol repeated — deduplicate while preserving first-seen order.
    text = resp.content.decode("latin-1")
    reader = csv.DictReader(io.StringIO(text))
    seen: set[str] = set()
    symbols: list[str] = []
    for row in reader:
        sym = row.get("Symbol", "").strip()
        if sym and sym not in seen:
            seen.add(sym)
            symbols.append(sym)
    log.info("Found %d unique symbols", len(symbols))
    return symbols


# ---------------------------------------------------------------------------
# Step 2: Fetch PlantProfile (bulk, threaded)
# ---------------------------------------------------------------------------

def fetch_profile(symbol: str) -> dict | None:
    """Fetch a single PlantProfile. Returns dict or None on failure."""
    session = make_session()
    url = f"{BASE_API}/PlantProfile?symbol={symbol}"
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not isinstance(data, dict) or not data.get("Id"):
            return None
        return data
    except Exception:
        return None


def fetch_all_profiles(symbols: list[str]) -> list[dict]:
    # Resume from cache if available
    if PROFILES_CACHE.exists():
        log.info("Loading profiles from cache: %s", PROFILES_CACHE)
        profiles = json.loads(PROFILES_CACHE.read_text(encoding="utf-8"))
        log.info("Loaded %d cached profiles", len(profiles))
        return profiles

    profiles = []
    total = len(symbols)
    completed = 0

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_sym = {executor.submit(fetch_profile, sym): sym for sym in symbols}
        for future in as_completed(future_to_sym):
            completed += 1
            result = future.result()
            if result:
                profiles.append(result)
            if completed % 500 == 0:
                log.info("Profiles fetched: %d / %d  (kept %d so far)", completed, total, len(profiles))
            if completed % MAX_WORKERS == 0:
                time.sleep(SLEEP_BETWEEN)

    log.info("Profile fetch complete: %d / %d returned valid data", len(profiles), total)
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    PROFILES_CACHE.write_text(json.dumps(profiles), encoding="utf-8")
    log.info("Profiles cached to %s", PROFILES_CACHE)
    return profiles


# ---------------------------------------------------------------------------
# Step 3: Filter
# ---------------------------------------------------------------------------

def is_native_l48(profile: dict) -> bool:
    for entry in profile.get("NativeStatuses") or []:
        if entry.get("Region") == "L48" and entry.get("Type") == "Native":
            return True
    return False


def get_l48_bbox(profile: dict) -> tuple | None:
    for entry in profile.get("MapCoordinates") or []:
        if entry.get("StateAbbr") == "L48":
            try:
                return (
                    float(entry["XMin"]),
                    float(entry["YMin"]),
                    float(entry["XMax"]),
                    float(entry["YMax"]),
                )
            except (KeyError, TypeError, ValueError):
                return None
    return None


def filter_plants(profiles: list[dict]) -> list[dict]:
    kept = []
    for p in profiles:
        if not is_native_l48(p):
            continue
        bbox = get_l48_bbox(p)
        if bbox is None:
            continue
        if bbox_overlaps(*bbox, BH_XMIN, BH_YMIN, BH_XMAX, BH_YMAX):
            kept.append(p)
    log.info("Filter complete: %d plants pass (native L48 + Black Hills bbox overlap)", len(kept))
    return kept


# ---------------------------------------------------------------------------
# Step 4: Supplemental endpoints
# ---------------------------------------------------------------------------

def fetch_characteristics(session: requests.Session, plant_id: int) -> dict:
    """Fetch PlantCharacteristics and pivot by category."""
    url = f"{BASE_API}/PlantCharacteristics/{plant_id}"
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        if not isinstance(data, list):
            return {}
        result = {}
        for item in data:
            cat = item.get("PlantCharacteristicCategory", "Other")
            name = item.get("PlantCharacteristicName", "")
            value = item.get("PlantCharacteristicValue", "")
            result.setdefault(cat, {})[name] = value
        return result
    except Exception:
        return {}


def fetch_json_list(session: requests.Session, url: str) -> list:
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code != 200:
            return []
        data = resp.json()
        return data if isinstance(data, list) else []
    except Exception:
        return []


def fetch_json_obj(session: requests.Session, url: str) -> dict:
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code != 200:
            return {}
        data = resp.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def fetch_images(session: requests.Session, plant_id: int) -> list:
    url = f"{BASE_API}/plantImages?plantId={plant_id}"
    raw = fetch_json_list(session, url)
    images = []
    for img in raw:
        standard = img.get("StandardSizeImageLibraryPath", "")
        thumb = img.get("ThumbnailSizeImageLibraryPath", "")
        images.append({
            **img,
            "StandardSizeImageUrl": f"{BASE_IMAGES}{standard}" if standard else "",
            "ThumbnailSizeImageUrl": f"{BASE_IMAGES}{thumb}" if thumb else "",
        })
    return images


def enrich_plant(profile: dict) -> dict:
    """Add supplemental data to a profile dict. Returns enriched dict."""
    plant_id = profile["Id"]
    cache_file = ENRICHED_CACHE_DIR / f"{plant_id}.json"

    # Resume from per-plant cache
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    session = make_session()

    time.sleep(SLEEP_BETWEEN)
    characteristics = fetch_characteristics(session, plant_id)

    time.sleep(SLEEP_BETWEEN)
    pollinators = fetch_json_list(session, f"{BASE_API}/PlantPollinator/{plant_id}")

    time.sleep(SLEEP_BETWEEN)
    ethnobotany = fetch_json_list(session, f"{BASE_API}/PlantEthnobotany/{plant_id}")

    time.sleep(SLEEP_BETWEEN)
    wildlife = fetch_json_obj(session, f"{BASE_API}/PlantWildlife/{plant_id}")

    time.sleep(SLEEP_BETWEEN)
    related_links = fetch_json_list(session, f"{BASE_API}/PlantRelatedLinks/{plant_id}")

    time.sleep(SLEEP_BETWEEN)
    images = fetch_images(session, plant_id)

    result = {
        **profile,
        "Characteristics": characteristics,
        "Pollinators": pollinators,
        "Ethnobotany": ethnobotany,
        "Wildlife": wildlife,
        "RelatedLinks": related_links,
        "Images": images,
    }
    cache_file.write_text(json.dumps(result), encoding="utf-8")
    return result


def enrich_all(filtered: list[dict]) -> list[dict]:
    ENRICHED_CACHE_DIR.mkdir(parents=True, exist_ok=True)

    already_cached = sum(1 for p in filtered if (ENRICHED_CACHE_DIR / f"{p['Id']}.json").exists())
    if already_cached:
        log.info("Resuming enrichment: %d / %d already cached", already_cached, len(filtered))

    enriched = []
    total = len(filtered)

    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        future_to_id = {executor.submit(enrich_plant, p): p["Id"] for p in filtered}
        completed = 0
        for future in as_completed(future_to_id):
            completed += 1
            result = future.result()
            enriched.append(result)
            if completed % 50 == 0 or completed == total:
                log.info("Enrichment: %d / %d complete", completed, total)

    # Sort by symbol for deterministic output
    enriched.sort(key=lambda x: x.get("Symbol", ""))
    return enriched


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    session = make_session()

    # Step 1
    symbols = fetch_symbol_list(session)

    # Step 2
    log.info("Fetching %d plant profiles (4 workers) ...", len(symbols))
    profiles = fetch_all_profiles(symbols)
    log.info("Total valid profiles: %d", len(profiles))

    # Step 3
    filtered = filter_plants(profiles)

    # Step 4
    log.info("Enriching %d filtered plants with supplemental data ...", len(filtered))
    enriched = enrich_all(filtered)

    # Step 5
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(enriched, indent=2), encoding="utf-8")
    log.info("Written %d plants to %s", len(enriched), OUTPUT_PATH)

    print("\n=== SUMMARY ===")
    print(f"Total symbols in plantlst.txt : {len(symbols)}")
    print(f"Valid profiles returned        : {len(profiles)}")
    print(f"Passed filter (native + bbox)  : {len(filtered)}")
    print(f"Enriched records written       : {len(enriched)}")
    print(f"Output file                    : {OUTPUT_PATH}")


if __name__ == "__main__":
    main()

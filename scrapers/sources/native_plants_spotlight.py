"""
scrapers/sources/native_plants_spotlight.py

Builds the native plant spotlight pool from locally-curated plant lists
(data/black_hills_wildflowers.json, data/sd_flowering_plants.json,
data/sd_living_landscapes.json) cross-referenced against the USDA PLANTS
database dump (data/plants_native_black_hills.json).

Only plants explicitly mentioned in the local reference files are included,
so every plant in the pool is known to be relevant to the Black Hills.

Writes data/native_plants_spotlight.json.

Not a BaseScraper subclass — run directly or via build.py.
Usage:
    uv run python -c "
    from scrapers.sources.native_plants_spotlight import build_spotlight
    build_spotlight()
    "
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SOURCE_FILE = ROOT / "data" / "plants_native_black_hills.json"
OUTPUT_FILE = ROOT / "data" / "native_plants_spotlight.json"

BH_WILDFLOWERS_FILE = ROOT / "data" / "black_hills_wildflowers.json"
SD_FLOWERING_FILE = ROOT / "data" / "sd_flowering_plants.json"
SD_LANDSCAPES_FILE = ROOT / "data" / "sd_living_landscapes.json"

PLANTS_IMAGE_BASE = "https://plants.sc.egov.usda.gov"
PLANTS_PROFILE_BASE = "https://plants.sc.egov.usda.gov/plant-profile/"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _strip_html(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s).strip()


def _genus_species(sci_name: str) -> tuple[str, str | None]:
    clean = _strip_html(sci_name).lower()
    parts = clean.split()
    if len(parts) >= 2:
        return parts[0], parts[1]
    if parts:
        return parts[0], None
    return "", None


def _months_to_period(months: list[str]) -> str:
    month_order = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    months_norm = [m.capitalize() for m in months]
    indices = [month_order.index(m) for m in months_norm if m in month_order]
    if not indices:
        return ", ".join(months_norm)
    indices.sort()
    first = month_order[indices[0]]
    last = month_order[indices[-1]]
    return first if first == last else f"{first}–{last}"


# ---------------------------------------------------------------------------
# Collect locally-documented scientific names + supplemental bloom data
# ---------------------------------------------------------------------------


def _local_names() -> tuple[list[tuple[str, str | None]], dict[str, dict]]:
    """
    Returns:
        pairs       — list of (genus, species|None) from all local files
        supplement  — {genus_species: {bloom_period: str}} from sd_flowering
    """
    pairs: list[tuple[str, str | None]] = []
    supplement: dict[str, dict] = {}

    def _add(raw: str) -> None:
        # handle slash-separated variants like "hierochloe hirta / hierochloe odorata"
        raw = re.sub(r"\).*", "", raw).strip()
        for variant in raw.split("/"):
            toks = variant.strip().lower().split()
            if len(toks) >= 2:
                pairs.append((toks[0], toks[1]))
            elif toks:
                pairs.append((toks[0], None))

    if BH_WILDFLOWERS_FILE.exists():
        bh = json.loads(BH_WILDFLOWERS_FILE.read_text(encoding="utf-8"))
        for season_entry in bh.get("plants") or []:
            for _season, plants in season_entry.items():
                for p in plants:
                    name = p.get("name", "")
                    if "(" in name and ")" in name:
                        _add(name[name.index("(") + 1 : name.rindex(")")])

    if SD_FLOWERING_FILE.exists():
        sdp = json.loads(SD_FLOWERING_FILE.read_text(encoding="utf-8"))
        for p in sdp.get("plants") or []:
            raw = (p.get("scientific_name") or "").lower().strip()
            if not raw:
                continue
            _add(raw)
            toks = raw.split()
            if len(toks) >= 2:
                key = f"{toks[0]} {toks[1]}"
                bloom = p.get("bloom_period") or []
                if bloom and key not in supplement:
                    supplement[key] = {"bloom_period": _months_to_period(bloom)}

    if SD_LANDSCAPES_FILE.exists():
        sdl = json.loads(SD_LANDSCAPES_FILE.read_text(encoding="utf-8"))
        for p in sdl.get("plants") or []:
            _add((p.get("scientific_name") or "").lower().strip())

    return pairs, supplement


# ---------------------------------------------------------------------------
# Match local names against PLANTS DB
# ---------------------------------------------------------------------------


def _match_symbols(raw: list[dict], pairs: list[tuple[str, str | None]]) -> set[str]:
    """
    Return symbols of PLANTS DB records that:
      - match at least one local (genus, species) pair, AND
      - have at least one image (displayable)

    Matching: genus must match; species matches if:
      1. exact first-two-word match, OR
      2. species epithet appears anywhere in the stripped name
         (handles synonym/variety cases like prunus pumila var. besseyi)
      3. species is None (genus-only entry) → any record in that genus
    """
    found: set[str] = set()
    for record in raw:
        if not record.get("Images"):
            continue
        sci = record.get("ScientificName", "")
        genus, species = _genus_species(sci)
        if not genus:
            continue
        stripped_words = _strip_html(sci).lower().split()

        for loc_genus, loc_species in pairs:
            if genus != loc_genus:
                continue
            if loc_species is None or species == loc_species or loc_species in stripped_words:
                found.add(record["Symbol"])
                break

    return found


# ---------------------------------------------------------------------------
# Flatten
# ---------------------------------------------------------------------------


def _flatten(plant: dict, bloom_supplement: str = "") -> dict:
    chars = plant.get("Characteristics") or {}
    morph = chars.get("Morphology/Physiology") or {}
    growth = chars.get("Growth Requirements") or {}
    repro = chars.get("Reproduction") or {}
    use = chars.get("Suitability/Use") or {}

    images = []
    for img in plant.get("Images") or []:
        std = img.get("StandardSizeImageLibraryPath") or ""
        thumb = img.get("ThumbnailSizeImageLibraryPath") or ""
        large = img.get("LargeSizeImageLibraryPath") or ""
        if std:
            images.append(
                {
                    "url": f"{PLANTS_IMAGE_BASE}{std}",
                    "thumb_url": f"{PLANTS_IMAGE_BASE}{thumb}" if thumb else "",
                    "large_url": f"{PLANTS_IMAGE_BASE}{large}" if large else "",
                    "credit": img.get("CommonName") or "",
                    "location": img.get("ImageLocation") or "",
                    "date": img.get("ImageCreationDate") or "",
                }
            )

    symbol = plant.get("Symbol", "")
    bloom_period = repro.get("Bloom Period") or morph.get("Active Growth Period") or bloom_supplement or ""

    return {
        "symbol": symbol,
        "common_name": plant.get("CommonName") or "",
        "scientific_name": _strip_html(plant.get("ScientificName") or ""),
        "group": plant.get("Group") or "",
        "durations": plant.get("Durations") or [],
        "growth_habits": plant.get("GrowthHabits") or [],
        "plants_url": f"{PLANTS_PROFILE_BASE}{symbol}",
        "flower_color": morph.get("Flower Color") or "",
        "flower_conspicuous": morph.get("Flower Conspicuous") or "",
        "bloom_period": bloom_period,
        "height_ft": morph.get("Height, Mature (feet)") or "",
        "foliage_color": morph.get("Foliage Color") or "",
        "fall_conspicuous": morph.get("Fall Conspicuous") or "",
        "fruit_color": morph.get("Fruit/Seed Color") or "",
        "growth_rate": morph.get("Growth Rate") or "",
        "lifespan": morph.get("Lifespan") or "",
        "toxicity": morph.get("Toxicity") or "",
        "drought_tolerance": growth.get("Drought Tolerance") or "",
        "shade_tolerance": growth.get("Shade Tolerance") or "",
        "moisture_use": growth.get("Moisture Use") or "",
        "soil_fine": growth.get("Adapted to Fine Textured Soils") or "",
        "soil_coarse": growth.get("Adapted to Coarse Textured Soils") or "",
        "ph_min": growth.get("pH, Minimum") or "",
        "ph_max": growth.get("pH, Maximum") or "",
        "temp_min_f": growth.get("Temperature, Minimum (°F)") or "",
        "palatable_browse": use.get("Palatable Browse Animal") or "",
        "palatable_graze": use.get("Palatable Graze Animal") or "",
        "palatable_human": use.get("Palatable Human") or "",
        "wildlife_food": (plant.get("Wildlife") or {}).get("Food") or [],
        "ethnobotany": plant.get("Ethnobotany") or [],
        "images": images,
        "related_links": [
            {"url": lnk.get("Url", ""), "text": lnk.get("LinkText", "")}
            for lnk in (plant.get("RelatedLinks") or [])
            if lnk.get("Url")
        ],
    }


# ---------------------------------------------------------------------------
# Build
# ---------------------------------------------------------------------------


def build_spotlight() -> None:
    if not SOURCE_FILE.exists():
        print(f"[native_plants_spotlight] Source file not found: {SOURCE_FILE}")
        return

    print(f"[native_plants_spotlight] Loading {SOURCE_FILE.name} …")
    raw = json.loads(SOURCE_FILE.read_text(encoding="utf-8"))

    pairs, supplement = _local_names()
    print(f"[native_plants_spotlight] {len(pairs)} name references from local files")

    matched_symbols = _match_symbols(raw, pairs)
    print(f"[native_plants_spotlight] {len(matched_symbols)} symbols matched with images")

    by_symbol = {p["Symbol"]: p for p in raw}
    candidates = [by_symbol[sym] for sym in matched_symbols if sym in by_symbol]

    # Sort: forbs first, then shrubs, trees, graminoids; more images = richer
    def _sort_key(p: dict) -> tuple:
        habits = set(p.get("GrowthHabits") or [])
        if "Forb/herb" in habits:
            prio = 0
        elif "Shrub" in habits or "Subshrub" in habits:
            prio = 1
        elif "Tree" in habits:
            prio = 2
        elif "Graminoid" in habits:
            prio = 3
        else:
            prio = 4
        return (prio, -len(p.get("Images") or []))

    candidates.sort(key=_sort_key)

    def _bloom_supplement(plant: dict) -> str:
        g, s = _genus_species(plant.get("ScientificName", ""))
        if g and s:
            return (supplement.get(f"{g} {s}") or {}).get("bloom_period", "")
        return ""

    spotlight = [_flatten(p, _bloom_supplement(p)) for p in candidates]

    OUTPUT_FILE.write_text(json.dumps(spotlight, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[native_plants_spotlight] Wrote {len(spotlight)} plants → {OUTPUT_FILE.name}")


if __name__ == "__main__":
    build_spotlight()

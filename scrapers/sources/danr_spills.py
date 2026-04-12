"""
scrapers/sources/danr_spills.py

Detects new spill report records from the SD DANR ArcGIS MapServer for the
Black Hills region by caching known OBJECTIDs and flagging new ones with the
date they were first seen.

Source: SD DANR / NR42_SpillReports_Public
Web UI: https://apps.sd.gov/NR42InteractiveMap
API:    https://arcgis.sd.gov/arcgis/rest/services/DENR/NR42_SpillReports_Public/MapServer/0

Year is derived from the `id` field (format: YEAR.SEQUENCE, e.g. 2011.100).

Usage:
    uv run python -m scrapers.sources.danr_spills
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "danr_spills.json"

BASE_URL = "https://arcgis.sd.gov/arcgis/rest/services/DENR/NR42_SpillReports_Public/MapServer/0/query"

HEADERS = {"User-Agent": "whats-up-in-spearfish/1.0 (public data aggregator)"}

# SD Black Hills counties tracked
BH_COUNTIES = ("Lawrence", "Pennington", "Custer", "Meade", "Fall River", "Butte")

LOOKBACK_DAYS = 30
PAGE_SIZE = 1000

OUT_FIELDS = ",".join(
    [
        "OBJECTID",
        "id",
        "site_name",
        "site_type",
        "status",
        "street",
        "city",
        "county",
        "spill_cat",
        "material",
        "sor_type",
        "resp_party",
    ]
)


def _year_from_id(id_val: float | int | None) -> int | None:
    """Extract year from the id field (YEAR.SEQUENCE format, e.g. 2011.100)."""
    if id_val is None:
        return None
    year = int(id_val)
    if year < 100:
        year += 1900
    return year


def _pdf_url_from_id(id_val: float | int | None) -> str | None:
    """Construct source PDF URL from id field (YEAR.SEQUENCE format, e.g. 2011.100).

    PDF archive starts around 1990; older records return None.
    """
    if id_val is None:
        return None
    year_raw = int(id_val)
    year = year_raw + 1900 if year_raw < 100 else year_raw
    if year < 1990:
        return None
    seq = round((id_val - year_raw) * 1000)
    if seq <= 0:
        return None
    return f"https://danr.sd.gov/spillimages/{year}/{year}.{seq:03d}.pdf"


def _fetch_all() -> list[dict]:
    """Fetch all BH region records with pagination."""
    counties_sql = ", ".join(f"'{c}'" for c in BH_COUNTIES)
    features = []
    offset = 0

    while True:
        params = {
            "where": f"county IN ({counties_sql})",
            "outFields": OUT_FIELDS,
            "returnGeometry": "true",
            "outSR": "4326",
            "resultRecordCount": PAGE_SIZE,
            "resultOffset": offset,
            "f": "json",
        }
        try:
            resp = requests.get(BASE_URL, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as exc:
            print(f"[DANR Spills] Warning: fetch failed at offset {offset}: {exc}")
            break

        if "error" in data:
            print(f"[DANR Spills] API error: {data['error']}")
            break

        page = data.get("features") or []
        features.extend(page)

        if len(page) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    return features


def fetch_danr_spills() -> None:
    # Load existing cached data
    if DATA_FILE.exists():
        try:
            existing = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except Exception:
            existing = {}
    else:
        existing = {}

    known_ids: set[int] = set(existing.get("known_ids", []))
    new_records: list[dict] = existing.get("new_records", [])

    # Prune new_records older than LOOKBACK_DAYS
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=LOOKBACK_DAYS)).isoformat()
    new_records = [r for r in new_records if r.get("first_seen", "") >= cutoff]
    new_record_ids = {r["objectid"] for r in new_records}

    current_year = datetime.now(timezone.utc).year

    # Fetch all current BH records
    features = _fetch_all()
    if not features:
        print("[DANR Spills] Warning: no records fetched; aborting update.")
        return

    today = datetime.now(timezone.utc).date().isoformat()
    all_ids: set[int] = set()
    added = 0

    # Index existing new_records by objectid for fast retroactive patching
    new_records_by_id = {r["objectid"]: r for r in new_records}

    for feat in features:
        attrs = feat.get("attributes") or {}
        geom = feat.get("geometry") or {}
        objectid = attrs.get("OBJECTID")
        if objectid is None:
            continue

        all_ids.add(objectid)
        id_raw = attrs.get("id")
        year = _year_from_id(id_raw)

        # Backfill pdf_url on existing records that predate the id_raw field
        if objectid in new_records_by_id:
            existing_rec = new_records_by_id[objectid]
            if existing_rec.get("pdf_url") is None and "id_raw" not in existing_rec:
                existing_rec["id_raw"] = id_raw
                existing_rec["pdf_url"] = _pdf_url_from_id(id_raw)

        # Include all current-year records, plus any genuinely new records from prior years
        is_new_to_known = objectid not in known_ids
        is_current_year = year == current_year
        if objectid not in new_record_ids and (is_current_year or is_new_to_known):
            lat = geom.get("y")
            lon = geom.get("x")
            new_records.append(
                {
                    "objectid": objectid,
                    "first_seen": today,
                    "id_raw": id_raw,
                    "year": year,
                    "pdf_url": _pdf_url_from_id(id_raw),
                    "site_name": (attrs.get("site_name") or "").strip(),
                    "site_type": (attrs.get("site_type") or "").strip(),
                    "status": (attrs.get("status") or "").strip(),
                    "street": (attrs.get("street") or "").strip(),
                    "city": (attrs.get("city") or "").strip(),
                    "county": (attrs.get("county") or "").strip(),
                    "spill_cat": (attrs.get("spill_cat") or "").strip(),
                    "material": (attrs.get("material") or "").strip() or None,
                    "sor_type": (attrs.get("sor_type") or "").strip() or None,
                    "resp_party": (attrs.get("resp_party") or "").strip() or None,
                    "lat": round(lat, 6) if lat else None,
                    "lon": round(lon, 6) if lon else None,
                }
            )
            added += 1

    known_ids.update(all_ids)

    new_records.sort(key=lambda r: r["first_seen"], reverse=True)

    DATA_FILE.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "lookback_days": LOOKBACK_DAYS,
                "total_bh_sites": len(all_ids),
                "known_ids": sorted(known_ids),
                "new_records": new_records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    print(
        f"[DANR Spills] {len(all_ids)} total BH sites, {added} added this run, {len(new_records)} in pool → {DATA_FILE.name}"  # noqa
    )


if __name__ == "__main__":
    fetch_danr_spills()

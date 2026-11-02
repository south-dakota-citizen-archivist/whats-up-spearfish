"""
scrapers/sources/roadkill.py

Fetches recent wildlife carcass pickup records from the SD DOT ArcGIS
FeatureServer, filtered to the Black Hills bounding box.

Source: SD DOT / Survey123 "DOT Wildlife Carcass Pickup" layer
API: https://services1.arcgis.com/PwrabBhZHUggYYSp/ArcGIS/rest/services/
     service_45cc7abd52f846ce8ad10dba811a5535/FeatureServer/0

Usage:
    uv run python -c "
    from scrapers.sources.roadkill import fetch_roadkill
    fetch_roadkill()
    "
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scrapers import net
from scrapers.base import BaseScraper

DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "roadkill.json"

SERVICE_BASE = (
    "https://services1.arcgis.com/PwrabBhZHUggYYSp/ArcGIS/rest/services"
    "/service_45cc7abd52f846ce8ad10dba811a5535/FeatureServer/0"
)
BASE_URL = f"{SERVICE_BASE}/query"
ATTACHMENTS_URL = f"{SERVICE_BASE}/queryAttachments"

HEADERS = {"User-Agent": "whats-up-in-spearfish/1.0 (public data aggregator)"}

# How far back to fetch
LOOKBACK_DAYS = 30

# The Black Hills and the towns around them, Hot Springs/Edgemont to Spearfish/Belle Fourche
# and Rapid City into the Wyoming foothills (WGS84)
BBOX = {"min_lat": 43.30, "max_lat": 44.80, "min_lon": -104.70, "max_lon": -103.00}

# ArcGIS envelope geometry for BBOX
BH_ENVELOPE = (
    f'{{"xmin":{BBOX["min_lon"]},"ymin":{BBOX["min_lat"]},'
    f'"xmax":{BBOX["max_lon"]},"ymax":{BBOX["max_lat"]},'
    f'"spatialReference":{{"wkid":4326}}}}'
)


def _ts_to_iso(ms: int | None) -> str:
    """Convert ArcGIS epoch-milliseconds timestamp to ISO date string."""
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%d")


def fetch_roadkill() -> None:
    cutoff = datetime.now(tz=timezone.utc) - timedelta(days=LOOKBACK_DAYS)
    cutoff_str = cutoff.strftime("%Y-%m-%d %H:%M:%S")

    params = {
        "where": f"Date > TIMESTAMP '{cutoff_str}'",
        "geometry": BH_ENVELOPE,
        "geometryType": "esriGeometryEnvelope",
        "spatialRel": "esriSpatialRelIntersects",
        "outFields": "OBJECTID,Date,Species,Highway,Sex,Present,Comments,Contractor",
        "orderByFields": "Date DESC",
        "resultRecordCount": 1000,
        "f": "json",
    }

    try:
        resp = net.get(BASE_URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        print(f"[Roadkill] Warning: fetch failed: {exc}")
        return

    if "error" in data:
        print(f"[Roadkill] API error: {data['error']}")
        return

    records = []
    for feature in data.get("features") or []:
        attrs = feature.get("attributes") or {}
        geom = feature.get("geometry") or {}

        species = (attrs.get("Species") or "").strip()
        if not species:
            continue

        lat = geom.get("y") or attrs.get("Latitude")
        lon = geom.get("x") or attrs.get("Longitude")

        # Skip records with no usable coordinates
        if not lat or not lon:
            continue

        highway = (attrs.get("Highway") or "").strip()
        if highway.upper() in ("N/A", "NA", "NONE", ""):
            highway = ""

        records.append(
            {
                "objectid": attrs.get("objectid") or attrs.get("OBJECTID"),
                "date": _ts_to_iso(attrs.get("Date")),
                "species": species,
                "highway": highway,
                "sex": (attrs.get("Sex") or "").strip(),
                "present": attrs.get("Present"),
                "comments": (attrs.get("Comments") or "").strip() or None,
                "contractor": (attrs.get("Contractor") or "").strip() or None,
                "lat": round(lat, 6),
                "lon": round(lon, 6),
                "image_url": None,
            }
        )

    # Fetch attachments in batches and map image URLs back to records
    oid_to_record = {r["objectid"]: r for r in records if r["objectid"] is not None}
    oids = list(oid_to_record.keys())
    batch_size = 100
    for i in range(0, len(oids), batch_size):
        batch = oids[i : i + batch_size]
        try:
            att_resp = net.get(
                ATTACHMENTS_URL,
                params={
                    "objectIds": ",".join(str(o) for o in batch),
                    "definitionExpression": "1=1",
                    "f": "json",
                },
                headers=HEADERS,
                timeout=30,
            )
            att_resp.raise_for_status()
            att_data = att_resp.json()
        except Exception as exc:
            print(f"[Roadkill] Warning: attachment fetch failed: {exc}")
            continue

        for group in att_data.get("attachmentGroups") or []:
            oid = group.get("parentObjectId")
            if oid not in oid_to_record:
                continue
            for info in group.get("attachmentInfos") or []:
                if (info.get("contentType") or "").startswith("image/"):
                    oid_to_record[oid]["image_url"] = f"{SERVICE_BASE}/{oid}/attachments/{info['id']}"
                    break  # first image only

    with_images = sum(1 for r in records if r["image_url"])
    print(f"[Roadkill] {len(records)} records, {with_images} with images → {DATA_FILE.name}")

    DATA_FILE.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "lookback_days": LOOKBACK_DAYS,
                "records": records,
            },
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    fetch_roadkill()


class Roadkill(BaseScraper):
    """On ice: kept for later, not run. Still uses its own standalone fetch
    function and file format; port it to scrape() before enabling."""

    name = "Wildlife carcass pickups (SD DOT)"
    slug = "roadkill"
    kind = "sighting"
    enabled = False

    def scrape(self) -> list[dict]:
        raise NotImplementedError("roadkill is on ice")

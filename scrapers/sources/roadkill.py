"""
scrapers/sources/roadkill.py

Every wildlife carcass the state picked up off Black Hills roads, from SD DOT's
"DOT Wildlife Carcass Pickup" layer (filled in by crews in the field with
Survey123), with every field the layer has and every photo.

  layer   https://services1.arcgis.com/PwrabBhZHUggYYSp/ArcGIS/rest/services/
          service_45cc7abd52f846ce8ad10dba811a5535/FeatureServer/0

The whole Black Hills history (about 22,600 pickups since 2010, ~4,000 a year) is
re-read each day: 1,000 records a request, then the photos for 1,000 records a
request, about 50 requests in all. Re-reading everything keeps edits and deletions
current without any bookkeeping.

A photo's file is {LAYER}/{objectid}/attachments/{photo id}; add ?w=320 for a
smaller copy, which the server makes.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from scrapers import net
from scrapers.base import BaseScraper
from scrapers.dates import MT

LAYER = (
    "https://services1.arcgis.com/PwrabBhZHUggYYSp/ArcGIS/rest/services"
    "/service_45cc7abd52f846ce8ad10dba811a5535/FeatureServer/0"
)
PAGE = 1000  # the layer's most records a request
DELAY = 1.0  # seconds between requests

# The Black Hills and the towns around them, Hot Springs/Edgemont to Spearfish/Belle Fourche
# and Rapid City into the Wyoming foothills (WGS84)
BBOX = {"xmin": -104.70, "ymin": 43.30, "xmax": -103.00, "ymax": 44.80}
_GEOMETRY = {
    "geometry": '{{"xmin":{xmin},"ymin":{ymin},"xmax":{xmax},"ymax":{ymax},"spatialReference":{{"wkid":4326}}}}'.format(
        **BBOX
    ),
    "geometryType": "esriGeometryEnvelope",
    "inSR": 4326,
    "spatialRel": "esriSpatialRelIntersects",
}
NO_HIGHWAY = {"", "N/A", "NA", "NONE"}


def _when(ms: int | None) -> str:
    """ArcGIS epoch milliseconds → Mountain time, ISO."""
    if not ms:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(MT).isoformat(timespec="seconds")


def _text(value) -> str:
    return " ".join(str(value).split()) if value not in (None, "") else ""


def parse_feature(feature: dict) -> dict | None:
    """One pickup, every field the layer has."""
    a = feature.get("attributes") or {}
    g = feature.get("geometry") or {}
    oid = a.get("objectid") or a.get("OBJECTID")
    if oid is None:
        return None
    lat, lon = g.get("y", a.get("Latitude")), g.get("x", a.get("Longitude"))
    when = _when(a.get("Date"))
    highway = _text(a.get("Highway"))
    rec = {
        "objectid": oid,
        "globalid": a.get("globalid") or "",
        "date": when[:10],  # the day of the pickup; the form's time is a placeholder (noon)
        "species": _text(a.get("Species")),
        "sex": _text(a.get("Sex")),
        "present": _text(a.get("Present")),
        "highway": "" if highway.upper() in NO_HIGHWAY else highway,
        "highway_raw": highway,
        "comments": _text(a.get("Comments")),
        "contractor": _text(a.get("Contractor")),
        "pcn": _text(a.get("PCN")),
        "lat": round(lat, 6) if isinstance(lat, (int, float)) else None,
        "lon": round(lon, 6) if isinstance(lon, (int, float)) else None,
        "date_raw": when,
        "created": _when(a.get("CreationDate")),
        "creator": _text(a.get("Creator")),
        "edited": _when(a.get("EditDate")),
        "editor": _text(a.get("Editor")),
        "parentglobalid": a.get("parentglobalid") or "",
        "photos": [],
    }
    # the form's own GPS reading, when it differs from the point on the map
    for key, attr, ref in (("gps_lat", "Latitude", rec["lat"]), ("gps_lon", "Longitude", rec["lon"])):
        v = a.get(attr)
        if isinstance(v, (int, float)) and (ref is None or abs(v - ref) > 1e-5):
            rec[key] = round(v, 6)
    return rec


def add_photos(records: dict[int, dict], groups: list[dict]) -> None:
    """Attach each record's photos (from queryAttachments) in place."""
    for group in groups:
        rec = records.get(group.get("parentObjectId"))
        if not rec:
            continue
        for info in group.get("attachmentInfos") or []:
            rec["photos"].append(
                {
                    "id": info.get("id"),
                    "name": info.get("name") or "",
                    "type": info.get("contentType") or "",
                    "size": info.get("size"),
                    "keywords": info.get("keywords") or "",
                }
            )


def photo_url(rec: dict, photo: dict, width: int | None = None) -> str:
    url = f"{LAYER}/{rec['objectid']}/attachments/{photo['id']}"
    return f"{url}?w={width}" if width else url


def _json(method, url: str, data: dict) -> dict:
    resp = method(url, **({"params": data} if method is net.get else {"data": data}), timeout=60)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        raise RuntimeError(f"layer error: {body['error']}")
    return body


class Roadkill(BaseScraper):
    name = "Wildlife carcass pickups"
    slug = "roadkill"
    kind = "stats"
    url = "https://dot.sd.gov/"
    timeout = 15 * 60
    max_stale_hours = 24 * 3

    def scrape(self) -> dict:
        ids = _json(net.get, f"{LAYER}/query", {"where": "1=1", **_GEOMETRY, "returnIdsOnly": "true", "f": "json"})
        oids = sorted(ids.get("objectIds") or [])
        records: dict[int, dict] = {}
        for i in range(0, len(oids), PAGE):
            time.sleep(DELAY)
            chunk = oids[i : i + PAGE]
            body = _json(
                net.post,
                f"{LAYER}/query",
                {"objectIds": ",".join(map(str, chunk)), "outFields": "*", "outSR": 4326, "f": "json"},
            )
            for feature in body.get("features") or []:
                if rec := parse_feature(feature):
                    records[rec["objectid"]] = rec
        for i in range(0, len(oids), PAGE):
            time.sleep(DELAY)
            chunk = oids[i : i + PAGE]
            body = _json(net.post, f"{LAYER}/queryAttachments", {"objectIds": ",".join(map(str, chunk)), "f": "json"})
            add_photos(records, body.get("attachmentGroups") or [])
        rows = sorted(records.values(), key=lambda r: (r["date"], r["objectid"]), reverse=True)
        return {"layer": LAYER, "bbox": BBOX, "records": rows}

    def is_empty(self, payload: dict) -> bool:
        return len(payload.get("records") or []) < 1000  # the full history is far more; a short read is a failure

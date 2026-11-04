"""
The state's list of spills: the public layer behind DANR's Tanks and Spills Map
(https://apps.sd.gov/NR42InteractiveMap/), on the sdgis.sd.gov ArcGIS server.

A spill's number is YEAR.SEQUENCE, logged in order: 2026.146, and before 2000 a
two-digit year, 93.042 (filed as 1993.042). Two other series share the layer:
seven-digit YEARNNN numbers (2026005) and, before 2000, five-digit YYNNN (93047),
which hold tank-removal checks; and placeholder numbers (4444, 7777, 8888, 9999).
All are kept, each marked with its series.
"""

from __future__ import annotations

from . import net

LAYER = "https://sdgis.sd.gov/danr/rest/services/BIT_Systems/NR42_SpillReports_Public/MapServer/0/query"
BLACK_HILLS = ("Lawrence", "Meade", "Butte", "Pennington", "Custer", "Fall River")
STATUS = {"O": "Open", "C": "Closed", "NFA": "No further action"}
PLACEHOLDERS = {4444, 7777, 8888, 9999}


def number(raw: float) -> dict:
    """The layer's id (a float) → {'number': '1993.042', 'year': 1993, 'series': 'spill'}."""
    whole = int(raw)
    if whole in PLACEHOLDERS:
        return {"number": f"{raw:g}", "year": None, "series": "placeholder"}
    if whole >= 1_000_000:  # 2026005
        return {"number": str(whole), "year": whole // 1000, "series": "tank check"}
    if 10_000 <= whole < 100_000:  # 93047
        yy = whole // 1000
        return {"number": str(whole), "year": 1900 + yy if yy > 50 else 2000 + yy, "series": "tank check"}
    year = whole if whole >= 1000 else (1900 + whole if whole > 50 else 2000 + whole)
    seq = round((raw - whole) * 1000)
    return {"number": f"{year}.{seq:03d}", "year": year, "series": "spill"}


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def fetch(counties=BLACK_HILLS, delay: float = 1.0) -> list[dict]:
    """Every spill on the layer in these counties, with its place and what the layer says."""
    where = "county IN (" + ",".join("'" + c.replace("'", "''") + "'" for c in counties) + ")"
    out, offset = [], 0
    while True:
        resp = net.request("GET", LAYER, delay=delay, params={
            "where": where, "outFields": "*", "returnGeometry": "true", "outSR": 4326, "f": "json",
            "orderByFields": "OBJECTID", "resultOffset": offset, "resultRecordCount": 1000,
        })  # fmt: skip
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"spill layer: {data['error']}")
        for f in data.get("features", []):
            a, g = f.get("attributes") or {}, f.get("geometry") or {}
            if a.get("id") is None:
                continue
            out.append({
                "layer_id": a["id"],  # as the state's systems know it, for looking up files
                **number(a["id"]),
                "site_name": _clean(a.get("site_name")),
                "site_type": _clean(a.get("site_type")),
                "status": STATUS.get(_clean(a.get("status")), _clean(a.get("status"))),
                "street": _clean(a.get("street")),
                "city": _clean(a.get("city")),
                "zip": _clean(a.get("zip_code")),
                "county": _clean(a.get("county")),
                "responsible_party": _clean(a.get("resp_party")),
                "category": _clean(a.get("spill_cat")),
                "material": _clean(a.get("material")),
                "source": _clean(a.get("sor_type")),
                "lat": round(g["y"], 6) if g.get("y") is not None else None,
                "lon": round(g["x"], 6) if g.get("x") is not None else None,
            })  # fmt: skip
        if not data.get("exceededTransferLimit"):
            return out
        offset += len(data.get("features", []))

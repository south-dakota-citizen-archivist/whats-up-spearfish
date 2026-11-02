"""
scrapers/sources/danr_spills.py

Spill reports in the Black Hills counties, this year and last, from the SD DANR
Tanks and Spills Map (https://apps.sd.gov/NR42InteractiveMap/), whose layer
lives on the state's sdgis.sd.gov ArcGIS server.

The layer carries no report date. Each report's number is YEAR.SEQUENCE
(2026.140), in the order DANR logged them, and the runner stamps the day each
first showed up here. A second numbering series (2026005) holds tank-removal
checks that found nothing; those aren't spills and are left out.

Each report's scanned case file is a PDF that DANR posts some time after the
report; until it's there, the link goes to the map.
"""

from __future__ import annotations

from scrapers import dates, net
from scrapers.base import BaseScraper

MAP_URL = "https://apps.sd.gov/NR42InteractiveMap/"
LAYER = "https://sdgis.sd.gov/danr/rest/services/BIT_Systems/NR42_SpillReports_Public/MapServer/0/query"
PDF_URL = "https://danr.sd.gov/spillimages/{year}/{number}.pdf"
COUNTIES = ("Lawrence", "Meade", "Butte", "Pennington", "Custer", "Fall River")
STATUS = {"O": "Open", "C": "Closed", "NFA": "No further action"}
SOURCES = {"AST": "Above-ground tank", "UST": "Underground tank"}
_HEADERS = {"User-Agent": "whats-up-spearfish (https://github.com/south-dakota-citizen-archivist/whats-up-spearfish)"}


def report_number(raw) -> str | None:
    """2026.14 → "2026.140"; None for the other numbering series and junk."""
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    year = int(value)
    seq = round((value - year) * 1000)
    if not 1990 <= year <= 2100 or seq <= 0:
        return None
    return f"{year}.{seq:03d}"


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def sentence_case(text: str) -> str:
    """ "Hydraulic Oil" → "Hydraulic oil"; acronyms (PFAS, NonPCB) stay as they are."""
    first, *rest = text.split() or [""]
    return " ".join([first] + [w.lower() if w[:1].isupper() and w[1:].islower() else w for w in rest])


def spill_record(attrs: dict, geometry: dict | None) -> dict | None:
    number = report_number(attrs.get("id"))
    if not number:
        return None
    material = _clean(attrs.get("material"))
    source = _clean(attrs.get("sor_type"))
    return {
        "report_no": number,
        "year": int(number[:4]),
        "title": _clean(attrs.get("site_name")),
        "status": STATUS.get(_clean(attrs.get("status")).upper(), _clean(attrs.get("status"))),
        "category": _clean(attrs.get("spill_cat")).replace("(See Case File)", "").strip(),
        "material": "" if material.lower() in ("none", "unknown") else sentence_case(material),
        "spill_source": sentence_case(SOURCES.get(source.upper(), source)),
        "street": _clean(attrs.get("street")),
        "city": _clean(attrs.get("city")),
        "county": _clean(attrs.get("county")).title(),
        "responsible_party": _clean(attrs.get("resp_party")),
        "lat": round(geometry["y"], 5) if geometry and geometry.get("y") else None,
        "lon": round(geometry["x"], 5) if geometry and geometry.get("x") else None,
    }


def _pdf_posted(url: str) -> bool:
    try:
        resp = net.request("HEAD", url, headers=_HEADERS, timeout=15, allow_redirects=True)
    except Exception:  # noqa: BLE001 — a missing link isn't worth failing the scrape over
        return False
    return resp.ok and "pdf" in resp.headers.get("Content-Type", "")


class DANRSpills(BaseScraper):
    name = "SD DANR spill reports"
    slug = "danr_spills"
    kind = "spill"
    url = MAP_URL
    replace = True
    dedup_key = "report_no"
    max_stale_hours = 24 * 3

    def scrape(self) -> list[dict]:
        since = dates.today().year - 1
        counties = ", ".join(f"'{c}'" for c in COUNTIES)
        resp = net.get(
            LAYER,
            params={
                # county is sometimes typed lowercase
                "where": f"UPPER(county) IN ({counties.upper()}) AND id >= {since} AND id < {since + 2}",
                "outFields": "id,site_name,status,spill_cat,material,sor_type,street,city,county,resp_party",
                "returnGeometry": "true",
                "outSR": "4326",
                "orderByFields": "id DESC",
                "resultRecordCount": 2000,
                "f": "json",
            },
            headers=_HEADERS,
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"spill layer error: {data['error']}")

        spills: dict[str, dict] = {}
        for feature in data.get("features", []):
            rec = spill_record(feature.get("attributes") or {}, feature.get("geometry"))
            if rec and rec["title"] and rec["report_no"] not in spills:  # a report can be listed twice
                spills[rec["report_no"]] = rec
        for rec in spills.values():
            pdf = PDF_URL.format(year=rec["year"], number=rec["report_no"])
            rec["url"] = pdf if _pdf_posted(pdf) else MAP_URL
        return sorted(spills.values(), key=lambda r: r["report_no"], reverse=True)

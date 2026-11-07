"""
scrapers/sources/danr_spills.py

Spill reports in the Black Hills counties, this year and last, from the SD DANR
Tanks and Spills Map (https://apps.sd.gov/NR42InteractiveMap/), whose layer
lives on the state's sdgis.sd.gov ArcGIS server.

The layer carries no report date. Each report's number is YEAR.SEQUENCE
(2026.140), in the order DANR logged them, and the runner stamps the day each
first showed up here. A second numbering series (2026005) holds tank-removal
checks that found nothing; those aren't spills and are left out.

Each report's case file is one or more PDFs that DANR posts some time after the
report (until then, the link goes to the map). Their forms are read with
spillarchive (the standalone spill-archive tool in this repo): the spill date, the
material and how much, the source and cause, the response, and the follow-up
report's cleanup details. A PDF is read once and its reading kept; it's read again
only if the state replaces it (a different size).
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

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
    timeout = 40 * 60  # the first run reads every case file once; later runs only new or changed ones

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
        before = {r.get("report_no"): r for r in self.load_existing()}
        for rec in spills.values():
            add_case_file(rec, before.get(rec["report_no"]) or {})
        return sorted(spills.values(), key=sort_key, reverse=True)


def sort_key(rec: dict) -> tuple:
    """Newest first: by the spill date the form gives, else the date it was reported, else its number."""
    return (rec.get("spill_date") or rec.get("reported_date") or "", rec["report_no"])


def _fields_only(reading: dict | None) -> bool:
    """A reading (since readers version 2) whose forms all came from fillable fields."""
    from spillarchive import extract

    if not reading or (reading.get("version") or 0) < extract.REREAD_FROM:
        return False
    return all(f.get("method") == "fields" for f in reading.get("forms") or [])


def _size(url: str) -> int | None:
    try:
        resp = net.request("HEAD", url, headers=_HEADERS, timeout=20, allow_redirects=True)
    except Exception:  # noqa: BLE001
        return None
    if not resp.ok or "pdf" not in resp.headers.get("Content-Type", ""):
        return None
    return int(resp.headers.get("Content-Length") or 0) or None


def is_case_file(name: str, number: str) -> bool:
    """The case file itself ('2026.146.pdf', '1985.075A.pdf'), not an attachment ('2025.044_invoice.pdf')."""
    return bool(re.fullmatch(re.escape(number) + r"[A-Za-z]?\.pdf", name, re.I))


def add_case_file(rec: dict, before: dict) -> None:
    """The spill's PDFs and what their forms say, reusing the last reading of any PDF that hasn't changed."""
    from spillarchive import extract, files

    try:
        urls = files.lookup(float(rec["report_no"]), delay=0.5)
    except Exception as exc:  # noqa: BLE001 — keep what we had
        print(f"[danr_spills] {rec['report_no']}: couldn't list its PDFs ({exc})")
        urls = [p["url"] for p in before.get("pdfs", [])]
    if not urls:  # the state's list can lag the posted file
        guess = PDF_URL.format(year=rec["year"], number=rec["report_no"])
        urls = [guess] if _pdf_posted(guess) else []
    seen = {p["url"]: p for p in before.get("pdfs", [])}
    readings = dict(before.get("_readings") or {})
    pdfs = []
    for url in urls:
        size = _size(url)
        if size is None:
            continue
        pdfs.append({"url": url, "size": size})
        name = url.rsplit("/", 1)[-1]
        if not is_case_file(name, rec["report_no"]):
            continue  # an attachment (photos, invoices, work plans): linked, not read for forms
        same_file = seen.get(url, {}).get("size") == size
        if same_file and readings.get(name, {}).get("version") == extract.VERSION:
            continue  # read before, unchanged, by the same readers
        if same_file and _fields_only(readings.get(name)):
            readings[name]["version"] = extract.VERSION
            continue  # fillable-form answers: a change to the text readers can't change them
        try:
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / name
                resp = net.request("GET", url, headers=_HEADERS, timeout=180)
                resp.raise_for_status()
                path.write_bytes(resp.content)
                reading = extract.read_pdf(path, "rapidocr", 4)
            readings[name] = {"forms": reading["forms"], "version": extract.VERSION}
            found = ", ".join(f"{f['form']} ({f['method']})" for f in reading["forms"])
            print(f"[danr_spills] read {name}: {found or 'no forms'}")
        except Exception as exc:  # noqa: BLE001
            print(f"[danr_spills] couldn't read {url}: {exc}")
    rec["pdfs"] = pdfs
    rec["url"] = pdfs[0]["url"] if pdfs else MAP_URL
    names = {p["url"].rsplit("/", 1)[-1] for p in pdfs}
    rec["_readings"] = {k: v for k, v in readings.items() if k in names}
    summary = extract.summarize({"year": rec["year"]}, [p["url"] for p in pdfs], rec["_readings"])
    for key in ("spill_date", "reported_date", "report", "follow_up"):
        if summary.get(key):
            rec[key] = summary[key]

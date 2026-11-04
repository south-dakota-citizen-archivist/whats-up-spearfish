"""
extract: what each PDF says.  build: one row per spill.

A PDF is a spill's whole case file: the report form, follow-up reports, letters,
photos, lab results. Each page is read the best way available:

  fields  a fillable form filled in on a computer: every answer exactly (forms.py)
  text    a page with a text layer: its text
  ocr     a scanned page: OCR (ocr.py), and the state's forms read from it (scanned.py)

OCR is slow (a couple of seconds a page) and the case files run to hundreds of pages,
so by default only the first pages are read, until the report form turns up
(--ocr-pages, default 4; 'all' reads everything, for full-text search). Each PDF's
result is saved as it's done, so a stopped run picks up where it left off.
"""

from __future__ import annotations

import csv
import logging
import re
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date
from pathlib import Path

from . import forms, ocr, scanned
from .store import Archive

VERSION = 2  # bump to re-read every PDF after a change to the readers


def read_pdf(path: Path, engine: str = "rapidocr", ocr_pages: int | None = 4) -> dict:
    """Everything worth keeping from one PDF."""
    import pdfplumber

    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    out: dict = {"file": path.name, "version": VERSION, "pages": [], "forms": []}
    use_ocr = engine != "none" and ocr.available(engine)
    with pdfplumber.open(path) as pdf:
        out["page_count"] = len(pdf.pages)
        follow_up_pages = []
        found_report = False
        for i, page in enumerate(pdf.pages):
            entry: dict = {"n": i + 1}
            has_fields = any("Widget" in str((a.get("data") or {}).get("Subtype")) for a in page.annots or [])
            text = page.extract_text() or "" if len(page.chars) > 30 else ""
            kind = forms.form_kind(page) if (has_fields or text) else None
            if has_fields and kind == "spill report":
                entry.update(method="fields", form=kind)
                out["forms"].append({**forms.spill_report(page), "page": i + 1, "method": "fields"})
                found_report = True
            elif has_fields and kind == "follow-up":
                entry.update(method="fields", form=kind)
                follow_up_pages.append((i + 1, page))
            elif text:
                entry.update(method="text", text=text)
                if form := scanned.read(text):
                    out["forms"].append({**form, "page": i + 1, "method": "text"})
                    found_report = found_report or form["form"] == "spill report"
            elif use_ocr and (ocr_pages is None or i < ocr_pages or (not found_report and i < ocr_pages * 2)):
                pieces = ocr.page_lines(path, i, engine)
                page_text = ocr.as_text(pieces)
                entry.update(method="ocr", engine=engine, text=page_text)
                if form := scanned.read(page_text):
                    out["forms"].append({**form, "page": i + 1, "method": "ocr"})
                    found_report = found_report or form["form"] == "spill report"
            else:
                entry.update(method="not read")
            out["pages"].append(entry)
        if follow_up_pages:
            out["forms"].append({**forms.follow_up([p for _, p in follow_up_pages]),
                                 "page": follow_up_pages[0][0], "method": "fields"})  # fmt: skip
    return out


def _done(arc: Archive, pdf: Path) -> bool:
    saved = arc.read(f"extracted/{pdf.name}.json", None)
    return bool(saved) and saved.get("version") == VERSION


def _work(args):
    path, engine, pages = args
    try:
        return path, read_pdf(path, engine, pages), None
    except Exception as exc:  # noqa: BLE001 — a damaged PDF shouldn't stop the run
        return path, None, f"{type(exc).__name__}: {exc}"


def step_extract(arc: Archive, args) -> None:
    pdfs = sorted(arc.path("pdfs").rglob("*.pdf"))
    todo = [p for p in pdfs if not _done(arc, p)]
    pages = None if str(getattr(args, "ocr_pages", "4")) == "all" else int(getattr(args, "ocr_pages", 4))
    workers = max(1, int(getattr(args, "workers", 4)))
    print(f"[extract] {len(todo)} of {len(pdfs)} PDFs to read (OCR: {args.ocr}, pages: {pages or 'all'})")
    started = time.monotonic()
    with ProcessPoolExecutor(max_workers=workers) as pool:
        jobs = [pool.submit(_work, (p, args.ocr, pages)) for p in todo]
        for n, job in enumerate(as_completed(jobs), 1):
            path, result, error = job.result()
            if error:
                print(f"[extract] {path.name}: {error}", file=sys.stderr)
                continue
            arc.write(f"extracted/{path.name}.json", result)
            if n % 10 == 0 or n == len(todo):
                rate = (time.monotonic() - started) / n
                print(f"[extract] {n}/{len(todo)} ({rate:.1f}s each)", flush=True)


# ── build ────────────────────────────────────────────────────────────────────


def iso_date(value: str, year_hint: int | None = None) -> str:
    """'9/18/26', '09/03/26', '9/17/2026', '08/15/02' → '2026-09-18'; '' if it isn't a date."""
    m = re.search(r"(\d{1,2})\s*[/\-.]\s*(\d{1,2})\s*[/\-.]\s*(\d{2,4})", value or "")
    if not m:
        return ""
    month, day, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
    if year < 100:
        century = (year_hint // 100 * 100) if year_hint else 2000
        year = century + year
        if year_hint and year > year_hint + 1:
            year -= 100
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


SUMMARY_FIELDS = (
    "spill_date", "reported_date", "materials", "material", "source", "source_description", "cause",
    "cause_description", "medium", "waterway_affected", "location", "city", "county", "discharger",
    "reported_by", "reporter_organization", "response_action", "comments", "injuries", "fatalities",
)  # fmt: skip
FOLLOW_UP_FIELDS = ("cleanup_date", "contractor", "soil_excavated", "contained", "water_impacted", "amount", "product")


def summarize(spill: dict, files: list[str], extracted: dict[str, dict]) -> dict:
    """One spill: what the state's list says, plus what its forms say (the first of each form)."""
    row = dict(spill)
    row["pdfs"] = files
    reports, follow_ups = [], []
    for url in files:
        data = extracted.get(url.rsplit("/", 1)[-1])
        if not data:
            continue
        for form in data.get("forms", []):
            (reports if form["form"] == "spill report" else follow_ups).append((url, form))
    if reports:
        url, form = sorted(reports, key=lambda uf: uf[1]["method"] != "fields")[0]  # an exact reading first
        row["report"] = {k: form[k] for k in SUMMARY_FIELDS if form.get(k)}
        row["report"].update(read_from=form["method"], pdf=url, page=form["page"])
    if follow_ups:
        url, form = sorted(follow_ups, key=lambda uf: uf[1]["method"] != "fields")[0]
        row["follow_up"] = {k: form[k] for k in FOLLOW_UP_FIELDS if form.get(k)}
        row["follow_up"].update(read_from=form["method"], pdf=url, page=form["page"])
    hint = spill.get("year")
    report = row.get("report", {})
    row["spill_date"] = iso_date(report.get("spill_date", ""), hint) or iso_date(
        row.get("follow_up", {}).get("spill_date", ""), hint)  # fmt: skip
    row["reported_date"] = iso_date(report.get("reported_date", ""), hint)
    return row


def _csv_report(rep: dict) -> dict:
    mats = rep.get("materials") or []
    cause = "; ".join(rep.get("cause", []))
    if rep.get("cause_description"):
        cause = f"{cause} — {rep['cause_description']}" if cause else rep["cause_description"]
    return {
        "read_from": rep.get("read_from", ""),
        "report_material": "; ".join(m.get("name", "") for m in mats) or rep.get("material", ""),
        "report_quantity": "; ".join(f"{m.get('quantity', '')} {m.get('units', '')}".strip() for m in mats),
        "report_cause": cause,
        "report_response": rep.get("response_action", ""),
    }


def step_build(arc: Archive, args) -> None:
    index = arc.read("index.json", {})
    files = arc.read("files.json", {})
    folder = arc.path("extracted")
    saved = sorted(folder.glob("*.json")) if folder.exists() else []
    extracted = {p.name[: -len(".json")]: arc.read(f"extracted/{p.name}", {}) for p in saved}
    rows = [summarize(s, files.get(s["number"], []), extracted) for s in index.get("spills", [])]
    rows.sort(key=lambda r: (r.get("spill_date") or r.get("reported_date") or str(r.get("year") or ""), r["number"]),
              reverse=True)  # fmt: skip
    arc.write("spills.json", {"counties": index.get("counties"), "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
                              "spills": rows})  # fmt: skip
    columns = ["number", "series", "year", "spill_date", "reported_date", "county", "city", "street", "site_name",
               "responsible_party", "status", "category", "material", "source", "lat", "lon", "read_from",
               "report_material", "report_quantity", "report_cause", "report_response", "pdfs"]  # fmt: skip
    with open(arc.path("spills.csv"), "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({**r, **_csv_report(r.get("report", {})), "pdfs": " ".join(r.get("pdfs", []))})
    have = sum(1 for r in rows if r.get("report"))
    print(f"[build] {len(rows)} spills; {have} with a report form read; spills.json and spills.csv")

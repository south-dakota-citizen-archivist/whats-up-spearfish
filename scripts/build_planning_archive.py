"""
scripts/build_planning_archive.py

Consolidates every Spearfish planning/permit record we have ever collected from
the city's OpenGov (ViewpointCloud) portal into one archive. The city turned
the public portal off in 2026 (publicPortalEnabled=false), so this is a
one-time consolidation, not a scraper.

Inputs
  - raw API dumps (one directory per record: record, form fields + entries,
    locations, attachments, docs, multi-entry items) made from the portal
    before it closed — complete records through mid-2025
  - every version of data/planning_zoning.json in git history on main —
    summary fields only, through July 2026

Outputs (into --out, default $WUS_DATA_DIR/archive or data/archive)
  planning_records.jsonl.gz  one JSON object per record, everything we have:
                             {"record_id", "detail": "full"|"summary", "record": {...},
                              "form": [{"section", "label", "value"}], "locations", "attachments",
                              "multi_entries", "docs", "summary", "sources"}
  planning_index.json        flattened rows for the site (address, coords, type, status,
                             dates, people, description, valuation, key form answers)
  README.md                  provenance

Usage:
  uv run python scripts/build_planning_archive.py \
      --raw <folder of raw record dumps> [--raw <another folder> …]
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scrapers import geo  # noqa: E402
from scrapers.schema import clean_text  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
PORTAL = "https://spearfishsd.portal.opengov.com/records"

# ViewpointCloud record status codes
STATUS = {-1: "Stopped", 0: "Draft", 1: "Active", 2: "Complete"}

# "Historical …" records (migrated from the city's previous system) carry eight unlabeled form
# fields whose definitions the API doesn't return; the order is the same for every type.
HISTORICAL_LABELS = [
    "Name",
    "Expiration date",
    "Issued date",
    "Historical permit number",
    "Permit type code",
    "Historical status",
    "Street name",
    "Street number",
]

# Record types that aren't about a place (shown in the archive, left off the map/lookup)
NOT_A_SITE = re.compile(r"contractor license|raffle|special event|alcohol|burn", re.I)

# The city's archive of monthly permit reports (its own copies; ours are on the data branch in permit_reports/)
BUILDING_PERMITS_PDF = "https://www.spearfish.gov/Archive.aspx?AMID=37"

# Form-field labels worth surfacing in the index (matched case-insensitively, first hit wins)
FIELD_PICKS = {
    "description": [r"^description of work", r"^project description", r"^describe", r"^scope of work", r"description"],
    "valuation": [r"valuation", r"estimated cost", r"project cost", r"value of work"],
    "contractor": [r"^business name", r"contractor.*name", r"^dba business name"],
    "contractor_phone": [r"^contractor phone"],
    "contractor_email": [r"^contractor email"],
    "owner": [r"^property owner name", r"^owner name"],
    "owner_phone": [r"^property owner phone"],
    "owner_email": [r"^property owner email"],
    "building_type": [r"^type of building"],
}


def _load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _data(obj) -> list:
    if not obj:
        return []
    d = obj.get("data")
    return d if isinstance(d, list) else ([d] if d else [])


def read_raw(record_dir: Path) -> dict | None:
    rid = record_dir.name
    main = _load(record_dir / f"{rid}.json")
    if not main or not main.get("data"):
        return None
    attrs = main["data"].get("attributes") or {}

    fields = {f["id"]: f.get("attributes") or {} for f in _data(_load(record_dir / f"{rid}-form-fields.json"))}
    form = []
    for e in _data(_load(record_dir / f"{rid}-form-field-entries.json")):
        a = e.get("attributes") or {}
        f = fields.get(str(a.get("formFieldID"))) or {}
        if a.get("value") in (None, ""):
            continue
        form.append(
            {
                "field_id": a.get("formFieldID"),
                "label": (f.get("fieldLabel") or "").strip(),
                "value": a.get("value"),
                "section_id": f.get("formSectionID"),
                "order": f.get("orderNo"),
                "show_to_public": bool(f.get("showToPublic")),
            }
        )
    form.sort(key=lambda x: (x["section_id"] or 0, x["order"] or 0, x["field_id"] or 0))
    if (
        form
        and not any(x["label"] for x in form)
        and (attrs.get("recordTypeName") or "").lower().startswith("historical")
    ):
        for i, x in enumerate(sorted(form, key=lambda x: x["field_id"] or 0)):
            x["label"] = HISTORICAL_LABELS[i] if i < len(HISTORICAL_LABELS) else f"Field {i + 1}"
            x["label_inferred"] = True

    return {
        "record": attrs,
        "form": form,
        "locations": _data(_load(record_dir / f"{rid}-locations.json")),
        "attachments": [x.get("attributes") for x in _data(_load(record_dir / f"{rid}-record-attachments.json"))],
        "multi_entries": {
            "items": [x.get("attributes") for x in _data(_load(record_dir / f"{rid}-multi-entry-items.json"))],
            "entries": [x.get("attributes") for x in _data(_load(record_dir / f"{rid}-multi-entry-item-entries.json"))],
        },
        "docs": [x.get("attributes") for x in _data(_load(record_dir / f"{rid}-docs.json"))],
        "fetched": datetime.fromtimestamp((record_dir / f"{rid}.json").stat().st_mtime, timezone.utc).isoformat(),
    }


def read_git_summaries() -> dict[int, dict]:
    """Latest version of each record across every commit of data/planning_zoning.json on origin/main."""
    log = subprocess.run(
        ["git", "log", "--format=%H %cI", "origin/main", "--", "data/planning_zoning.json"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split("\n")
    out: dict[int, dict] = {}
    for line in reversed([x for x in log if x]):  # oldest → newest so newer versions win
        sha, when = line.split()
        show = subprocess.run(["git", "show", f"{sha}:data/planning_zoning.json"], cwd=REPO, capture_output=True)
        if show.returncode != 0:
            continue
        try:
            raw = json.loads(show.stdout)
        except json.JSONDecodeError:
            continue
        for r in raw.get("records", []):
            rid = int(r.get("id") or r.get("record_id") or 0)
            if rid:
                out[rid] = {**r, "_seen_in_commit": sha[:10], "_seen_at": when}
    return out


def pick(form: list[dict], patterns: list[str]) -> str:
    for pat in patterns:
        for f in form:
            value = clean_text(f["value"])
            if re.search(pat, f["label"], re.I) and value.lower() not in ("false", "true", "n/a"):
                return value
    return ""


def _us_date(v) -> str:
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", str(v or ""))
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else ""


def form_value(form: list[dict], label: str) -> str:
    return next((str(x["value"]).strip() for x in form if x["label"] == label), "")


def _num(v):
    try:
        f = float(str(v).replace("$", "").replace(",", ""))
        return f if f else None
    except (TypeError, ValueError):
        return None


def index_row(entry: dict) -> dict:
    r = entry.get("record") or {}
    s = entry.get("summary") or {}
    form = entry.get("form") or []
    rid = entry["record_id"]
    address = (r.get("fullAddress") or s.get("address") or "").strip()
    if address.lower().startswith("0 no street"):
        address = ""
    status = r.get("status", s.get("status"))
    historical = (r.get("recordTypeName") or "").lower().startswith("historical")
    if historical:
        street = " ".join(x for x in (form_value(form, "Street number"), form_value(form, "Street name")) if x)
        address = address or street
    row = {
        "id": rid,
        "no": r.get("recordNo") or s.get("record_no") or "",
        "type": r.get("recordTypeName") or s.get("record_type") or s.get("permit_type") or "",
        "status": STATUS.get(status, "" if status is None else str(status)),
        "created": (r.get("dateCreated") or s.get("date_created") or "")[:10],
        "submitted": (r.get("dateSubmitted") or s.get("date_submitted") or "")[:10],
        "address": address,
        "lat": _num(r.get("latitude") if r else s.get("lat")),
        "lon": _num(r.get("longitude") if r else s.get("lon")),
        "applicant": (r.get("applicantFullName") or s.get("applicant") or "").strip(),
        "detail": entry["detail"],
        "url": f"{PORTAL}/{rid}",
    }
    if historical:
        row["created"] = _us_date(form_value(form, "Issued date")) or row["created"]
        row["submitted"] = row["created"]
        row["expires"] = _us_date(form_value(form, "Expiration date"))
        row["status"] = form_value(form, "Historical status") or row["status"]
        row["applicant"] = form_value(form, "Name") or row.get("applicant", "")
        row["historical_no"] = form_value(form, "Historical permit number")
        row["type"] = re.sub(r"^historical\s+", "", row["type"], flags=re.I).title() + " (pre-2020 system)"
    if not geo.in_spearfish(row.get("lat"), row.get("lon")):
        row.pop("lat", None), row.pop("lon", None)
    row["address_key"] = geo.normalize_address(address)
    row["site"] = not NOT_A_SITE.search(row["type"])
    for key, pats in FIELD_PICKS.items():
        v = pick(form, pats)
        if v:
            row[key] = v[:600]
    if not row.get("owner") and r.get("ownerName"):
        row["owner"] = r["ownerName"]
    if r.get("description") and not row.get("description"):
        row["description"] = str(r["description"])[:600]
    if "valuation" in row:
        row["valuation"] = _num(row["valuation"]) or row["valuation"]
    row["attachments"] = len(entry.get("attachments") or [])
    return {k: v for k, v in row.items() if v not in ("", None)}


def seed_building_permits(csv_path: Path) -> None:
    """
    Seed data/building_permits.json with the full report history: the hand-checked
    CSV (2013–2025-09) plus every record ever saved in this repo's legacy building_permits.json,
    merged with whatever the scraper has already saved.
    """
    from scrapers.sources.building_permits import BuildingPermits, _categorize, add_coordinates, finish_record

    def money(v):
        return _num(v)

    seeded: dict[str, dict] = {}
    with open(csv_path, newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            ym = f"{row['year']}-{row['month'].zfill(2)}"
            rec = {
                "year": row["year"],
                "month": row["month"].zfill(2),
                "date": f"{ym}-01",
                "permit_number": row["permit_number"].strip(),
                "applicant_name": row["applicant_name"].strip(),
                "site_address": " ".join(row["site_address"].split()),
                "construction_type": " ".join(row["construction_type"].split()),
                "category": _categorize(row["construction_type"]),
                "contractor": row["contractor"].strip(),
                "cost_approximate": money(row["cost_approximate"]),
                "permit_fee": money(row["permit_fee"]),
                "outside_city_limits": str(row.get("outside_city_limits", "")).lower() in ("true", "1", "yes"),
                "url": BUILDING_PERMITS_PDF,
                "report": ym,
            }
            seeded[finish_record(rec)["permit_key"]] = rec

    show = subprocess.run(["git", "show", "cf5f766:data/building_permits.json"], cwd=REPO, capture_output=True)
    if show.returncode == 0:
        legacy = json.loads(show.stdout)
        urls = legacy.get("month_urls") or {}
        for rec in legacy.get("records", []):
            ym = f"{rec.get('year')}-{str(rec.get('month')).zfill(2)}"
            rec["url"] = urls.get(ym) or BUILDING_PERMITS_PDF
            rec["report"] = ym
            seeded.setdefault(finish_record(rec)["permit_key"], rec)

    scraper = BuildingPermits()
    records = list(seeded.values())
    add_coordinates(records)
    fresh, dropped = scraper.normalize(records)
    existing = {finish_record(r)["permit_key"]: r for r in scraper.load_existing()}
    for r in fresh:
        r["_first_seen"] = r.get("date", "")
        existing.setdefault(r["permit_key"], r)
    merged = sorted(existing.values(), key=lambda r: r.get("date", ""))
    scraper.save(merged)
    print(f"building_permits: {len(merged)} records ({dropped} dropped) → {scraper.data_file}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw", action="append", type=Path, default=[], help="directory of raw per-record dumps")
    default_out = Path(os.environ.get("WUS_DATA_DIR") or REPO / "data") / "archive"
    ap.add_argument("--out", type=Path, default=default_out)
    ap.add_argument("--permits-csv", type=Path, help="hand-checked combined CSV of permits to seed building_permits")
    args = ap.parse_args()
    if args.permits_csv:
        seed_building_permits(args.permits_csv.expanduser())

    entries: dict[int, dict] = {}
    for raw_dir in args.raw:
        raw_dir = raw_dir.expanduser()
        n = 0
        for d in raw_dir.iterdir():
            if not d.name.isdigit():
                continue
            rec = read_raw(d)
            if not rec:
                continue
            rid = int(d.name)
            prev = entries.get(rid)
            newer = (rec["record"].get("lastUpdatedDate") or "") >= (
                (prev or {}).get("record", {}).get("lastUpdatedDate") or ""
            )
            if not prev or newer:
                rec["sources"] = sorted(set((prev or {}).get("sources", [])) | {raw_dir.parent.name})
                entries[rid] = {"record_id": rid, "detail": "full", **rec}
            else:
                prev["sources"] = sorted(set(prev["sources"]) | {raw_dir.parent.name})
            n += 1
        print(f"{raw_dir}: {n} records")

    summaries = read_git_summaries()
    print(f"git history: {len(summaries)} summary records")
    for rid, s in summaries.items():
        if rid in entries:
            entries[rid]["summary"] = s
        else:
            entries[rid] = {
                "record_id": rid,
                "detail": "summary",
                "record": {},
                "form": [],
                "summary": s,
                "sources": ["whats-up-spearfish git history"],
            }

    args.out.mkdir(parents=True, exist_ok=True)
    ordered = [entries[k] for k in sorted(entries)]
    with gzip.open(args.out / "planning_records.jsonl.gz", "wt", encoding="utf-8") as fh:
        for e in ordered:
            fh.write(json.dumps(e, ensure_ascii=False, default=str) + "\n")

    rows = [index_row(e) for e in ordered]
    need = [r["address"] for r in rows if r.get("site") and r.get("address") and "lat" not in r]
    coords = geo.geocode(need)
    for r in rows:
        if "lat" not in r and (c := coords.get(r.get("address_key", ""))):
            r["lat"], r["lon"], r["geocoded"] = c[0], c[1], True
    meta = {
        "built": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(rows),
        "full_detail": sum(1 for e in ordered if e["detail"] == "full"),
        "summary_only": sum(1 for e in ordered if e["detail"] == "summary"),
        "newest_created": max((r.get("created", "") for r in rows), default=""),
        "note": "The city disabled public access to its OpenGov portal in 2026; no newer records are available.",
    }
    (args.out / "planning_index.json").write_text(
        json.dumps({"meta": meta, "records": rows}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    (args.out / "README.md").write_text(
        f"""# Spearfish planning & permit records archive

Every record collected from the City of Spearfish's OpenGov (ViewpointCloud) permitting
portal, consolidated {meta["built"][:10]}. The city disabled public access to the portal in
2026 (`publicPortalEnabled: false`, `allowPublicRecordSearch: false`), so nothing newer
than {meta["newest_created"]} is available from it.

- `planning_records.jsonl.gz` — {meta["count"]:,} records, one JSON object per line.
  {meta["full_detail"]:,} have full detail (record, every form answer, locations, attachments,
  multi-entry items, documents) from raw API dumps made 2025; {meta["summary_only"]:,} more are
  summary-only (type, status, dates, address, coordinates, applicant) from the daily
  snapshots this project committed through 2026.
- `planning_index.json` — one flattened row per record, used by the site's
  "What's being built?" page.

Built by `scripts/build_planning_archive.py` on the main branch.
""",
        encoding="utf-8",
    )
    for f in sorted(args.out.iterdir()):
        print(f"{f.name}: {f.stat().st_size / 1e6:.1f} MB")
    print(json.dumps(meta, indent=1))


if __name__ == "__main__":
    main()

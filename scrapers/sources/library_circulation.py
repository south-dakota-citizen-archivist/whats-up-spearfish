"""
scrapers/sources/library_circulation.py

Fetches library circulation statistics from a manually-maintained
Google Sheets CSV and saves to data/library_circulation.json.

Not a BaseScraper subclass — run directly or from the daily scrape workflow.

Usage:
    uv run python -c "from scrapers.sources.library_circulation import fetch_circulation; fetch_circulation()"
"""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from pathlib import Path

import requests

DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "library_circulation.json"

SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vT4s9mwwmYYg0itwRMXAyY8W_-hmKbeSO2QnXtbfhRqRMv1O23TTzYSX5fS3_Dz2L0SoD4w9PHn_JKC"
    "/pub?gid=0&single=true&output=csv"
)

MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _int_or_none(val: str) -> int | None:
    val = val.strip()
    if not val:
        return None
    try:
        return int(val)
    except ValueError:
        return None


def fetch_circulation() -> None:
    try:
        resp = requests.get(SHEET_URL, timeout=20, allow_redirects=True)
        resp.raise_for_status()
        text = resp.text
    except Exception as exc:
        print(f"[LibraryCirculation] Warning: fetch failed: {exc}")
        return

    rows = []
    reader = csv.DictReader(io.StringIO(text))
    for raw in reader:
        year = _int_or_none(raw.get("year", ""))
        month = _int_or_none(raw.get("month", ""))
        if not year or not month:
            continue

        loans = _int_or_none(raw.get("loans", ""))
        renewals = _int_or_none(raw.get("renewals", ""))
        overdrive = _int_or_none(raw.get("overdrive_loans", ""))
        hoopla = _int_or_none(raw.get("hoopla_loans", ""))
        minutes_link = (raw.get("minutes_link") or "").strip()

        # Skip completely empty rows (no data at all)
        if loans is None and overdrive is None and hoopla is None and not minutes_link:
            continue

        rows.append({
            "year": year,
            "month": month,
            "month_name": MONTH_NAMES[month],
            "loans": loans,
            "renewals": renewals,
            "overdrive_loans": overdrive,
            "hoopla_loans": hoopla,
            "minutes_link": minutes_link or None,
        })

    DATA_FILE.write_text(
        json.dumps(
            {
                "fetched_at": datetime.now(timezone.utc).isoformat(),
                "rows": rows,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[LibraryCirculation] {len(rows)} months of data → {DATA_FILE.name}")


if __name__ == "__main__":
    fetch_circulation()

"""
scrapers/sources/library_circulation.py

Monthly checkouts at the Grace Balloch Memorial Library, from a Google Sheet
kept by hand from the library board's meeting packets: print and physical
items ("loans", plus renewals through 2021) and digital checkouts through
OverDrive/Libby (2022 on) and hoopla (2022–2025). Each month links to the board
minutes it came from.
"""

from __future__ import annotations

import csv
import io

from scrapers import net
from scrapers.base import BaseScraper

SHEET_URL = (
    "https://docs.google.com/spreadsheets/d/e/"
    "2PACX-1vT4s9mwwmYYg0itwRMXAyY8W_-hmKbeSO2QnXtbfhRqRMv1O23TTzYSX5fS3_Dz2L0SoD4w9PHn_JKC"
    "/pub?gid=0&single=true&output=csv"
)


def _int_or_none(val: str | None) -> int | None:
    try:
        return int((val or "").replace(",", "").strip())
    except ValueError:
        return None


def parse_rows(text: str) -> list[dict]:
    rows = []
    for raw in csv.DictReader(io.StringIO(text)):
        year, month = _int_or_none(raw.get("year")), _int_or_none(raw.get("month"))
        if not year or not month or not 1 <= month <= 12:
            continue
        row = {
            "month": f"{year}-{month:02d}",
            "loans": _int_or_none(raw.get("loans")),
            "renewals": _int_or_none(raw.get("renewals")),
            "overdrive": _int_or_none(raw.get("overdrive_loans")),
            "hoopla": _int_or_none(raw.get("hoopla_loans")),
            "minutes": (raw.get("minutes_link") or "").strip(),
        }
        if row["loans"] is None and row["overdrive"] is None and row["hoopla"] is None:
            continue  # a month not filled in yet
        rows.append(row)
    return sorted(rows, key=lambda r: r["month"])


class LibraryCirculation(BaseScraper):
    name = "Library checkouts"
    slug = "library_circulation"
    kind = "stats"
    url = "https://spearfish.blackhills.bywatersolutions.com"
    max_stale_hours = 24 * 7

    def scrape(self) -> dict:
        resp = net.get(SHEET_URL, timeout=20, allow_redirects=True)
        resp.raise_for_status()
        return {"rows": parse_rows(resp.text)}

    def is_empty(self, payload: dict) -> bool:
        return not payload.get("rows")

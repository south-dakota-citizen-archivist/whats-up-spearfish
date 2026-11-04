"""
sitegen/trends.py

Year-by-year figures for the building trends page, from the city's monthly
building permit reports (2013 on): permits for new homes, the reported value of
all construction, what a typical new home was reported to cost, and the biggest
projects.

Only measures that mean the same thing in every year are used. The city's
permit types were renamed more than once (2025's broad "Residential Additions or
Alterations" swallowed garages, basements and roofs), so counts of those kinds
of work aren't comparable across the years and aren't shown.
"""

from __future__ import annotations

import math
import re
import statistics
from collections import defaultdict
from datetime import date

# a new home: new residential construction, but not a garage, shed or deck built new
_NOT_A_HOME = re.compile(r"COMM|GARAGE|SHED|ACCESS|DECK|PATIO|ADDN|ADDITION|FOUND\b|FNDN|FND\b", re.I)
_COMMERCIAL = re.compile(r"COMM", re.I)


def is_new_home(r: dict) -> bool:
    return r.get("category") == "new_construction" and not _NOT_A_HOME.search(r.get("construction_type") or "")


def is_new_commercial(r: dict) -> bool:
    t = r.get("construction_type") or ""
    if r.get("category") != "new_construction" or not _COMMERCIAL.search(t):
        return False
    # "Commercial New Build or Addition" (2024 – 2025) covers small additions too
    return "ADDITION" not in t.upper() or (r.get("cost_approximate") or 0) >= 250_000


_KEEP_UPPER = {"LLC", "LP", "LLP", "INC", "HME", "SLH", "USA", "BH", "SD", "II", "III", "NE", "NW", "SE", "SW"}
_KEEP_LOWER = {"of", "and", "the", "at", "for"}


def tidy(text: str) -> str:
    """'HME COMPANIES LLC' → 'HME Companies LLC'; 'CITY OF SPEARFISH' → 'City of Spearfish'."""
    words = []
    for i, w in enumerate(" ".join((text or "").split()).split(" ")):
        bare = re.sub(r"[^\w]", "", w)
        if bare.upper() in _KEEP_UPPER:
            words.append(w.upper())
        elif i and bare.lower() in _KEEP_LOWER:
            words.append(w.lower())
        elif re.fullmatch(r"\d+(st|nd|rd|th)", bare, re.I):
            words.append(w.lower())
        else:
            words.append(w[:1].upper() + w[1:].lower())
    return " ".join(words).replace("Llc", "LLC")


def project_type(text: str) -> str:
    """The city's permit type, in plain words: 'COMM-NEW BLDG' → 'Commercial new building'."""
    t = " ".join((text or "").split()).upper()
    t = re.sub(r"\bCOMM\b-?|^COMM-", "COMMERCIAL ", t)
    t = re.sub(r"\bBLDG\b", "BUILDING", t).replace("-", " ")
    t = " ".join(t.split()).capitalize()
    return t


def money_short(v: float) -> str:
    """$83.3 million → '$83.3M'; $325,000 → '$325K'."""
    if v >= 1_000_000:
        return f"${v / 1_000_000:.1f}M".replace(".0M", "M")
    if v >= 1_000:
        return f"${v / 1_000:.0f}K"
    return f"${v:,.0f}"


def nice_max(v: float) -> tuple[float, float]:
    """A round axis top and step at or above v, in four or five steps."""
    if v <= 0:
        return 1, 1
    raw = v / 4
    mag = 10 ** math.floor(math.log10(raw))
    step = next(s * mag for s in (1, 2, 2.5, 5, 10) if s * mag >= raw)
    return step * math.ceil(v / step), step


def bars(rows: list[dict], key: str, fmt) -> dict:
    """Bar heights (percent of the axis) and gridlines for one measure."""
    top, step = nice_max(max((r[key] or 0) for r in rows))
    peak = max(rows, key=lambda r: r[key] or 0)
    return {
        "ticks": [{"pct": round(i * step / top * 100, 2), "label": fmt(i * step)} for i in range(int(top / step) + 1)],
        "bars": [
            {
                "year": r["year"],
                "value": r[key],
                "label": fmt(r[key]) if r[key] is not None else "—",
                "pct": round((r[key] or 0) / top * 100, 2),
                "partial": r["months"] < 12,
                "months": r["months"],
                # always labeled: the highest bar and the latest one
                "labeled": r is peak or r is rows[-1],
            }
            for r in rows
        ],
    }


def update_cpi() -> None:
    """
    Download the latest CPI into the cpi package's database. If the BLS can't be
    reached, the build carries on with the copy the package already has.
    """
    import warnings

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            import cpi

            cpi.update()
        print("[sitegen] Consumer Price Index updated")
    except Exception as exc:  # noqa: BLE001
        print(f"[sitegen] couldn't update the Consumer Price Index ({exc}); using the copy on hand")


def cpi_lookup():
    """
    Monthly Consumer Price Index values (CPI-U, U.S. city average) from the cpi
    package's bundled copy of the BLS series, as {'2026-08': 323.4, …}; None if
    the package or its data isn't available.
    """
    import warnings

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # "out of date" just means the newest month isn't bundled yet
            import cpi

            df = cpi.series.get().to_dataframe()
    except Exception:  # noqa: BLE001 — the page still works in reported dollars
        return None
    monthly = df[df["period_type"] == "monthly"]
    return {str(d)[:7]: float(v) for d, v in zip(monthly["date"], monthly["value"])}


class Deflator:
    """Converts a month's dollars to the dollars of one base month."""

    def __init__(self, index: dict[str, float], latest_report: str):
        self.index = index
        self.base_month = max(m for m in index if m <= latest_report) if any(m <= latest_report for m in index) else ""
        self.base = index.get(self.base_month)

    def value_of(self, month: str) -> float | None:
        # a month the BLS skipped (October 2025) or hasn't published uses the nearest month before it
        earlier = [m for m in self.index if m <= month]
        return self.index[max(earlier)] if earlier else None

    def __call__(self, amount: float | None, month: str) -> float | None:
        then = self.value_of(month)
        if amount is None or not then or not self.base:
            return amount
        return amount * self.base / then

    @property
    def label(self) -> str:
        return date(int(self.base_month[:4]), int(self.base_month[5:]), 1).strftime("%B %Y") if self.base_month else ""


def _values(rs: list[dict], adjust) -> tuple[float, float | None]:
    """Total reported value, and the median new home, for a set of permits."""
    total = sum(adjust(r.get("cost_approximate") or 0, r["report"]) for r in rs)
    homes = [adjust(r["cost_approximate"], r["report"]) for r in rs if is_new_home(r) and r.get("cost_approximate")]
    return total, (statistics.median(homes) if homes else None)


def _project(r: dict, value: float, place) -> dict:
    address = re.sub(r",?\s*Spearfish,?\s*SD\s*\d{5}\s*$", "", r.get("site_address", ""), flags=re.I)
    return {
        "year": r["year"],
        "report": r.get("report", ""),
        "type": project_type(r.get("construction_type", "")),
        "owner": tidy(r.get("applicant_name", "")),
        "address": tidy(address).replace("Tbd ", "").strip(),
        "value": value,
        "site": place(r) if place else "",  # its #site= key on the permits page
    }


def build(records: list[dict], today: date, index: dict[str, float] | None = None, place=None) -> dict | None:
    records = [r for r in records if str(r.get("year", "")).isdigit() and r.get("report")]
    by_year: dict[int, list[dict]] = defaultdict(list)
    for r in records:
        by_year[int(r["year"])].append(r)
    if not by_year:
        return None
    latest_report = max(r["report"] for r in records)
    deflate = Deflator(index, latest_report) if index else None

    def as_reported(amount, month):
        return amount

    rows = []
    for year in sorted(by_year):
        rs = by_year[year]
        homes = [r for r in rs if is_new_home(r)]
        value, median = _values(rs, as_reported)
        value_real, median_real = _values(rs, deflate) if deflate else (value, median)
        rows.append(
            {
                "year": year,
                "months": len({r["month"] for r in rs}),
                "last_month": max(int(r["month"]) for r in rs),
                "permits": len(rs),
                "homes": len(homes),
                "commercial": sum(1 for r in rs if is_new_commercial(r)),
                "demolitions": sum(1 for r in rs if r.get("category") == "demolition"),
                "value": value,
                "value_real": value_real,
                "median_home": median,
                "median_home_real": median_real,
            }
        )

    latest = rows[-1]
    through = latest["last_month"]
    ytd = None
    if latest["months"] < 12 and len(rows) > 1:
        before = [r for r in by_year[latest["year"] - 1] if int(r["month"]) <= through]
        ytd = {
            "year": latest["year"],
            "span": f"January – {date(2000, through, 1):%B}" if through > 1 else "January",
            "now": latest,
            "then": {
                "year": latest["year"] - 1,
                "permits": len(before),
                "homes": sum(1 for r in before if is_new_home(r)),
                "value": _values(before, as_reported)[0],
                "value_real": _values(before, deflate)[0] if deflate else _values(before, as_reported)[0],
            },
        }

    def biggest(adjust) -> list[dict]:
        valued = [(adjust(r["cost_approximate"], r["report"]), r) for r in records if r.get("cost_approximate")]
        return [_project(r, v, place) for v, r in sorted(valued, key=lambda x: -x[0])[:10]]

    return {
        "rows": rows,
        "first_year": rows[0]["year"],
        "latest": latest,
        "ytd": ytd,
        "dollars_of": deflate.label if deflate else "",
        "homes_chart": bars(rows, "homes", lambda v: f"{v:,.0f}"),
        "value_chart": bars(rows, "value", money_short),
        "value_chart_real": bars(rows, "value_real", money_short),
        "median_chart": bars(rows, "median_home", money_short),
        "median_chart_real": bars(rows, "median_home_real", money_short),
        "biggest": biggest(as_reported),
        "biggest_real": biggest(deflate) if deflate else biggest(as_reported),
    }

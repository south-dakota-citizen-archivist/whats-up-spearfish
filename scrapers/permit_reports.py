"""
scrapers/permit_reports.py

Reads the City of Spearfish's monthly building permit reports (PDF tables), in
every layout the city has used since 2013:

  2013 – 2020   one row per permit, eight columns, a header row on some pages
                ("PERMIT # | NAME | ADDRESS | TYPE OF CONST. | CONTRACTOR | …");
                the type and contractor columns traded places in 2019
  2021 – 2024   a two-row card per permit: number, owner, type, cost, fee, then
                ADDRESS … CONTRACTOR … HOOKUP FEE
  2025 –        one row per permit under "Record # | Property Owner | Address |
                Record Type | Reported Valuation | Permit Fee | Contractor |
                Jurisdictional Area"

Columns are found from a header row when there is one, else from what the cells
look like. Totals and count rows at the end are left out, and so are permit
types that aren't building (signs, burns, right-of-way, grading).
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

FIELDS = (
    "permit_number",
    "applicant_name",
    "site_address",
    "construction_type",
    "contractor",
    "cost_approximate",
    "permit_fee",
    "hookup_fee",
    "outside_city_limits",
)

# Header cell text → field, by keyword, most specific first: the city's headers vary ("APPROX. COST",
# "JOB COST", "Reported Valuation"; "ADDRESS", "SITE ADDRESS"; and once, "Contracor")
HEADER_WORDS = (
    ("hookup", "hookup_fee"),
    ("permit fee", "permit_fee"),
    ("juris", "jurisdiction"),
    ("contrac", "contractor"),
    ("cost", "cost_approximate"),
    ("valuation", "cost_approximate"),
    ("address", "site_address"),
    ("type", "construction_type"),
    ("permit", "permit_number"),
    ("record", "permit_number"),
    ("name", "applicant_name"),
    ("owner", "applicant_name"),
)


# The usual order before headers said otherwise (2013 – 2018), and after the 2019 swap
ORDER_TYPE_FIRST = (
    "permit_number", "applicant_name", "site_address", "construction_type", "contractor",
    "cost_approximate", "permit_fee", "hookup_fee",
)  # fmt: skip
ORDER_CONTRACTOR_FIRST = (
    "permit_number", "applicant_name", "site_address", "contractor", "construction_type",
    "cost_approximate", "permit_fee", "hookup_fee",
)  # fmt: skip

# Permit types that aren't building work
SKIP_TYPES = {
    "VOID", "ROW", "ROW/GRADING", "ROW (2)", "SIGN", "GRADING PERMIT", "BURN PERMIT", "SIGN PERMIT",
    "GRADING", "ROW PERMIT", "BURN", "RIGHT OF WAY PERMIT", "SING PERMIT",
}  # fmt: skip

# Words that mark a construction type ("Res-Garage", "COMMERCIAL ALTERATIONS", "Basement")
_TYPE_WORDS = re.compile(
    r"\b(res|comm|commercial|residential|new|dwelling|alter\w*|addition|addn|garage|basement|deck|roof\w*|"
    r"demo\w*|shed|fence|remodel|repair|mechanical|plumbing|sign|interior|tenant|finish|manuf|porch|patio|"
    r"accessory|carport|pool|siding|windows?|egress|foundation|fire|standalone)\b",
    re.I,
)
_TOTALS = re.compile(r"^total|\d{4}\s+\w+\s+permits?|permits?\s+issued|^count\b", re.I)


def squeeze(value) -> str:
    return " ".join(str(value or "").split())


def money(value) -> float | None:
    """'$ 2 1,950.00' → 21950.0; '$ -', 'N/A', 'Waived' → None."""
    v = "".join(str(value or "").replace("$", "").replace(",", "").replace("‐", "-").split())
    if not v or v in ("-", "--") or not re.fullmatch(r"-?\d+(\.\d+)?", v):
        return None
    return float(v)


def _unspill(left: str, right: str, numeric: bool) -> tuple[str, str]:
    """
    Older reports let long text run past its cell; the overflow letters land at the start
    of the next cell, sometimes woven between its digits: "…Abrahams" | "o4n02 Belleview Court"
    for "…Abrahamson" | "402 Belleview Court", or "…Foundation Re" | "pair $ 7,781.60".
    Letters ahead of a number that should start the next cell go back where they came from.
    """
    head, _, rest = right.partition(" ")
    if numeric:
        m = re.match(r"^([A-Za-z.,'&]+)\s*(?=[$\d-])", right)
        if m:
            return left + m.group(1), right[m.end() :]
        return left, right
    # an address: its first word should be a house number
    if re.search(r"\d", head) and re.search(r"[a-z]", head) and not re.search(r"[A-Z]", head):
        letters = "".join(c for c in head if c.isalpha())
        digits = "".join(c for c in head if not c.isalpha())
        if re.fullmatch(r"\d+[-/]?\d*", digits) and len(letters) <= 4 and not re.fullmatch(r"\d+(st|nd|rd|th)", head):
            return left + letters, (digits + " " + rest).strip()
    return left, right


def _header_field(cell) -> str | None:
    text = squeeze(cell).lower()
    if not text or len(text) > 40 or re.search(r"\d", text.replace("#", "")):
        return None
    return next((field for word, field in HEADER_WORDS if word in text), None)


def _header_map(row: list) -> dict[int, str] | None:
    """Columns from a header row; None if the row isn't one."""
    cols = {i: f for i, cell in enumerate(row) if (f := _header_field(cell))}
    if len(set(cols.values())) < 3:
        # a header the PDF merged into one cell still gives the column order away
        text = squeeze(" ".join(str(c or "") for c in row)).upper()
        if text.startswith("PERMIT #") and "ADDRESS" in text and "CONTRACTOR" in text and "TYPE" in text:
            order = ORDER_CONTRACTOR_FIRST if text.index("CONTRACTOR") < text.index("TYPE") else ORDER_TYPE_FIRST
            return dict(enumerate(order))
        return None
    if "permit_number" not in cols.values() and 0 not in cols:
        cols[0] = "permit_number"  # a header whose first cell was left blank
    return cols


def _guess_order(rows: list[list]) -> dict[int, str]:
    """For a headerless table: whichever of columns 3 and 4 reads more like a construction type is the type."""
    third = sum(bool(_TYPE_WORDS.search(squeeze(r[3]))) for r in rows if len(r) > 4)
    fourth = sum(bool(_TYPE_WORDS.search(squeeze(r[4]))) for r in rows if len(r) > 4)
    order = ORDER_CONTRACTOR_FIRST if fourth > third else ORDER_TYPE_FIRST
    return dict(enumerate(order))


def _record(values: dict) -> dict | None:
    values = {k: squeeze(v) for k, v in values.items()}
    values["applicant_name"], values["site_address"] = _unspill(
        values.get("applicant_name", ""), values.get("site_address", ""), numeric=False
    )
    values["contractor"], values["cost_approximate"] = _unspill(
        values.get("contractor", ""), values.get("cost_approximate", ""), numeric=True
    )
    pid = squeeze(values.get("permit_number")).lstrip("*").rstrip("*").strip()
    if not pid or _TOTALS.search(pid) or pid.lower() in ("permit #", "record #", "none"):
        return None
    if re.fullmatch(r"\d{1,3}", pid):
        return None  # a count in a summary table; permit numbers are longer
    ctype = squeeze(values.get("construction_type"))
    if ctype.upper() in SKIP_TYPES or squeeze(values.get("applicant_name")).upper() in SKIP_TYPES:
        return None
    jurisdiction = squeeze(values.get("jurisdiction")).lower()
    return {
        "permit_number": pid,
        "applicant_name": squeeze(values.get("applicant_name")),
        "site_address": squeeze(values.get("site_address")),
        "construction_type": ctype,
        "contractor": squeeze(values.get("contractor")),
        "cost_approximate": money(values.get("cost_approximate")),
        "permit_fee": money(values.get("permit_fee")),
        "hookup_fee": money(values.get("hookup_fee")),
        "outside_city_limits": bool(jurisdiction) and jurisdiction != "city",
    }


def parse_tables(tables: list[list[list]]) -> list[dict]:
    """Permit records from a report's tables, in the order they appear."""
    records: list[dict] = []
    columns: dict[int, str] | None = None
    for table in tables:
        rows = [r for r in table if r and any(squeeze(c) for c in r)]
        if not rows:
            continue
        # 2021 – 2024: two-row cards, the second row labeled ADDRESS / CONTRACTOR / HOOKUP FEE
        if any(squeeze(r[0]).upper() == "ADDRESS" for r in rows):
            for top, bottom in zip(rows, rows[1:]):
                if squeeze(bottom[0]).upper() != "ADDRESS" or squeeze(top[0]).upper() == "ADDRESS":
                    continue
                vals = {
                    "permit_number": top[0],
                    "applicant_name": top[1] if len(top) > 1 else "",
                    "construction_type": top[2] if len(top) > 2 else "",
                    "cost_approximate": top[4] if len(top) > 4 else "",
                    "permit_fee": top[5] if len(top) > 5 else "",
                    "site_address": bottom[1] if len(bottom) > 1 else "",
                    "contractor": bottom[3] if len(bottom) > 3 else "",
                    "hookup_fee": bottom[5] if len(bottom) > 5 else "",
                }
                if rec := _record(vals):
                    records.append(rec)
            continue
        if len(rows[0]) < 6:
            continue  # totals or counts tables
        for row in rows:
            if header := _header_map(row):
                columns = header
                continue
            if _TOTALS.search(squeeze(row[0])) or re.search(r"total", squeeze(" ".join(map(str, row[:3]))), re.I):
                break  # the totals at the end of the report
            cols = columns or _guess_order(rows)
            if rec := _record({field: row[i] for i, field in cols.items() if i < len(row)}):
                records.append(rec)
    return records


def parse_report(path: str | Path) -> list[dict]:
    """Every building permit in one monthly report."""
    import pdfplumber

    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    with pdfplumber.open(path) as pdf:
        tables = [t for page in pdf.pages for t in page.extract_tables()]
    return parse_tables(tables)

"""
tests/test_scraper_building_permits.py

The monthly building permit reports behind the permits map: the city's
archive page, the archive of reports we keep, and the PDF parser (against real
reports in every layout since 2013, checked by hand).
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from scrapers import permit_reports
from scrapers.sources import building_permits as bp

FIXTURES = Path(__file__).parent / "fixtures"
REPORT = FIXTURES / "building_permits_2026_09.pdf"


class FakeResponse:
    def __init__(self, text="", content=b""):
        self.text = text
        self.content = content

    def raise_for_status(self):
        pass


@pytest.fixture(scope="module")
def september():
    return bp.read_report(REPORT, "2026", "09")


def test_report_parses_every_permit(september):
    assert len(september) == 32  # what the city's report lists for September 2026
    assert {r["date"] for r in september} == {"2026-09-01"} and {r["report"] for r in september} == {"2026-09"}
    assert not {r["construction_type"].upper() for r in september} & permit_reports.SKIP_TYPES
    assert sum(r["outside_city_limits"] for r in september) == 5


def test_report_row_fields(september):
    first = september[0]
    assert first == {
        "year": "2026",
        "month": "09",
        "date": "2026-09-01",
        "report": "2026-09",
        "permit_number": "CAA-26-22",
        "applicant_name": "DANIEL AND KRISTEN ABEAR",
        "site_address": "412 W Jackson Blvd, Spearfish, SD 57783",
        "construction_type": "Commercial Alterations, Additions, or Tenant Improvements",
        "category": "alterations",
        "contractor": "OWNER",
        "cost_approximate": 10000.0,
        "permit_fee": 98.59,
        "hookup_fee": None,
        "outside_city_limits": False,
    }
    by_no = {r["permit_number"]: r for r in september}
    assert by_no["RNC-26-55"]["category"] == "new_construction"
    assert by_no["RNC-26-55"]["site_address"] == "3813 & 3815 Rock Ridge, Spearfish, SD 57783"  # wrapped cell joined


# One report in each layout the city has used, against the version checked by hand
@pytest.mark.parametrize("ym", ["2013-04", "2019-03", "2021-04", "2025-09"])
def test_every_layout_matches_the_hand_checked_version(ym):
    def norm(v):
        return " ".join(str(v or "").split()).upper()

    gold = {
        r["permit_number"].strip("*"): r
        for r in csv.DictReader(open(FIXTURES / "permit_reports" / f"{ym}.csv"))
        if norm(r["construction_type"]) not in permit_reports.SKIP_TYPES
        and norm(r["applicant_name"]) not in permit_reports.SKIP_TYPES
    }
    got = {r["permit_number"]: r for r in permit_reports.parse_report(FIXTURES / "permit_reports" / f"{ym}.pdf")}
    assert set(got) == set(gold)
    for pid, g in gold.items():
        for field in ("applicant_name", "site_address", "construction_type", "contractor"):
            assert norm(got[pid][field]) == norm(g[field]), (pid, field)
        for field in ("cost_approximate", "permit_fee"):
            assert (got[pid][field] or 0) == (permit_reports.money(g[field]) or 0), (pid, field)
        if ym < "2021":  # starred in the report: issued outside city limits
            assert got[pid]["outside_city_limits"] == (g["outside_city_limits"] == "True"), pid


def test_totals_counts_and_headers_are_not_permits():
    rows = [
        ["PERMIT #", "NAME", "ADDRESS", "CONTRACTOR", "TYPE OF CONST.", "JOB COST", "PERMIT FEES", "HOOKUP FEES"],
        ["190013", "SAFEWAY INC.", "1606 NORTH AVENUE", "PIONEER", "COMMERCIAL ALTERATION", "$ 8 0,000.00",
         "$ 912.00", "n/a"],
        ["190014", "CITY", "1 MAIN ST", "SELF", "SIGN", "$ 100.00", "$ 10.00", "n/a"],
        ["17TOTAL", "$ 1,109,739.00", "$ 7,868.00", "", "", "", "", ""],
    ]  # fmt: skip
    counts = [["12", "$45,000", "", "", "", "", "", ""]]
    out = permit_reports.parse_tables([rows, counts])
    assert [r["permit_number"] for r in out] == ["190013"]  # the sign permit, totals and counts left out
    assert out[0]["contractor"] == "PIONEER" and out[0]["construction_type"] == "COMMERCIAL ALTERATION"
    assert out[0]["cost_approximate"] == 80000.0


def test_summary_by_type_and_title_rows_are_not_permits():
    # 2018 reports end with a table of counts by type; a 2026 one put its title in the first cell
    rows = [
        ["PERMIT #", "NAME", "ADDRESS", "TYPE OF CONST.", "CONTRACTOR", "APPROX. COST", "PERMIT FEES", "HOOKUP FEES"],
        ["*180351", "SMITH", "19940 GOBBLER RD", "RES-GARAGE", "SELF", "$ 4,000.00", "$ 74.00", "n/a"],
        ["180352", "JONES", "12 MAIN ST", "RES-DECK", "SELF", "$ 2,000.00", "$ 40.00", "n/a"],
        ["PROJECT TYPE", "# OF PERMITS", "VALUATION", "FEES", "", "", "", ""],
        ["Res-New Dwelling", "$ 13,063.60", "4000.0", "$ 2,083,200.00", "", "", "", ""],
        ["Building Permit Report - August 2026", "", "", "", "", "", "", ""],
    ]  # fmt: skip
    out = permit_reports.parse_tables([rows])
    assert [r["permit_number"] for r in out] == ["180351", "180352"]
    assert [r["outside_city_limits"] for r in out] == [True, False]


def test_text_that_ran_into_the_next_cell_goes_back():
    row = ["13-0296", "Don/Marlyce Abrahams", "o4n02 Belleview Court", "Res-Deck", "Rapid Foundation Re",
           "pair $ 7,781.60", "$ 96.00", "N/A"]  # fmt: skip
    (r,) = permit_reports.parse_tables([[row]])
    assert r["applicant_name"] == "Don/Marlyce Abrahamson" and r["site_address"] == "402 Belleview Court"
    assert r["contractor"] == "Rapid Foundation Repair" and r["cost_approximate"] == 7781.6


@pytest.mark.parametrize(
    "raw, value",
    [("$1,234.50", 1234.5), ("$ 2 1,950.00", 21950.0), ("$ -", None), ("", None), (None, None), ("N/A", None),
     ("Waived", None)],
)  # fmt: skip
def test_money(raw, value):
    assert permit_reports.money(raw) == value


@pytest.mark.parametrize(
    "kind, category",
    [
        ("Demolition", "demolition"),
        ("Standalone Permits - Plumbing, Mechanical, Gas", "mechanical"),
        ("Residential New Construction", "new_construction"),
        ("MFG MH Placement", "new_construction"),
        ("Residential Additions or Alterations", "alterations"),
    ],
)
def test_categorize(kind, category):
    assert bp._categorize(kind) == category


ARCHIVE = """
<div id="modulecontent">
  <a href="Archive.aspx?ADID=1587">Building Permits Report - September 2026</a>
  <a href="Archive.aspx?ADID=1584">Building Permits August2026</a>
  <a href="Archive.aspx?ADID=1580">Monthly Building Permit Report - Juy 2026 (PDF)</a>
  <a href="Archive.aspx?ADID=1500">Building Permits Report - July</a>
  <a href="Archive.aspx?ADID=9">Building Permits Report - Sometime</a>
  <a href="/Documents/unrelated.pdf">Something else</a>
</div>
"""


def test_archive_links(monkeypatch):
    monkeypatch.setattr(bp.net, "get", lambda url, **kw: FakeResponse(text=ARCHIVE))
    monkeypatch.setattr(bp.time, "sleep", lambda s: None)
    reports = bp._scrape_archive()
    assert reports == [
        {"year": "2026", "month": "09", "url": "https://www.spearfish.gov/Archive.aspx?ADID=1587"},
        {"year": "2026", "month": "08", "url": "https://www.spearfish.gov/Archive.aspx?ADID=1584"},
        {"year": "2026", "month": "07", "url": "https://www.spearfish.gov/Archive.aspx?ADID=1580"},  # "Juy"
        {"year": "2023", "month": "07", "url": "https://www.spearfish.gov/Archive.aspx?ADID=1500"},  # known fix
    ]


def test_scrape_keeps_every_report_and_reads_the_newest(monkeypatch, tmp_path):
    months = ["January", "February", "March", "April", "May", "June", "July", "August"]
    links = "".join(
        f'<a href="Archive.aspx?ADID={100 + m}">Building Permits Report - {month} 2026</a>'
        for m, month in enumerate(months, 1)
    )
    fetched = []

    def get(url, **kw):
        fetched.append(url)
        if url == bp.ARCHIVE_URL:
            return FakeResponse(text=f'<div id="modulecontent">{links}</div>')
        if url.endswith("ADID=103"):
            return FakeResponse(content=b"<html>Not found</html>")  # not a PDF: skipped, not saved
        return FakeResponse(content=REPORT.read_bytes())

    monkeypatch.setattr(bp.base, "DATA_DIR", tmp_path)
    monkeypatch.setattr(bp.net, "get", get)
    monkeypatch.setattr(bp.time, "sleep", lambda s: None)
    monkeypatch.setattr(bp.geo, "geocode", lambda addresses: {"412 W JACKSON BLVD": (44.49, -103.86)})
    records = bp.BuildingPermits().scrape()

    saved = sorted(p.name for p in (tmp_path / "permit_reports").iterdir())
    assert len(saved) == 7 and "2026-03.pdf" not in saved  # every report kept, but not the broken one
    # a new report is always read; after that, only the newest RECENT_MONTHS are read again
    assert {r["month"] for r in records} == {"01", "02", "04", "05", "06", "07", "08"}
    r = next(r for r in records if r["permit_number"] == "CAA-26-22" and r["month"] == "08")
    assert r["permit_key"] == "CAA-26-22|2026-08" and r["report"] == "2026-08"
    assert r["url"].endswith("ADID=108")  # the city's copy, as the source
    assert (r["lat"], r["lon"]) == (44.49, -103.86)

    fetched.clear()
    again = bp.BuildingPermits().scrape()  # the next run downloads only what's new (here: retries the broken one)
    assert [u for u in fetched if u != bp.ARCHIVE_URL] == ["https://www.spearfish.gov/Archive.aspx?ADID=103"]
    # the newest six months, less March, which still isn't a PDF
    assert {r["month"] for r in again} == {"04", "05", "06", "07", "08"}

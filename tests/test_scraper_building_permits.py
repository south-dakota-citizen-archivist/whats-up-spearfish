"""
tests/test_scraper_building_permits.py

The monthly building permit reports behind the permits map: the city's
archive page, the PDF table parser (against a real report, September 2026)
and the cleanup rules.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from scrapers.sources import building_permits as bp

REPORT = Path(__file__).parent / "fixtures" / "building_permits_2026_09.pdf"


class FakeResponse:
    def __init__(self, text="", content=b""):
        self.text = text
        self.content = content

    def raise_for_status(self):
        pass


@pytest.fixture(scope="module")
def september():
    return bp._parse_pdf(REPORT, "2026", "09")


def test_report_parses_every_permit(september):
    assert len(september) == 32  # what the city's report lists for September 2026
    assert all(bp._is_valid_permit(r) for r in september)  # no headers or totals rows
    assert {r["date"] for r in september} == {"2026-09-01"}
    assert not {r["construction_type"].upper() for r in september} & bp.SKIP_TYPES
    assert sum(r["outside_city_limits"] for r in september) == 5


def test_report_row_fields(september):
    first = september[0]
    assert first == {
        "year": "2026",
        "month": "09",
        "date": "2026-09-01",
        "permit_number": "CAA-26-22",
        "applicant_name": "DANIEL AND KRISTEN ABEAR",
        "site_address": "412 W Jackson Blvd, Spearfish, SD 57783",
        "construction_type": "Commercial Alterations, Additions, or Tenant Improvements",
        "category": "alterations",
        "contractor": "OWNER",
        "cost_approximate": 10000.0,
        "permit_fee": 98.59,
        "outside_city_limits": False,
    }
    by_no = {r["permit_number"]: r for r in september}
    assert by_no["RNC-26-55"]["category"] == "new_construction"
    assert by_no["RNC-26-55"]["site_address"] == "3813 & 3815 Rock Ridge, Spearfish, SD 57783"  # wrapped cell joined


@pytest.mark.parametrize(
    "row, ok",
    [
        ({"permit_number": "RAA-26-11"}, True),
        ({"permit_number": "220127"}, True),
        ({"permit_number": ""}, False),
        ({"permit_number": "Total Permits Issued"}, False),
        ({"permit_number": "2026 January Permits"}, False),
        ({"permit_number": "12", "construction_type": "$45,000"}, False),  # a count row from the totals block
    ],
)
def test_is_valid_permit(row, ok):
    assert bp._is_valid_permit(row) is ok


@pytest.mark.parametrize(
    "raw, value", [("$1,234.50", 1234.5), ("$ 10, 000", 10000.0), ("-", None), ("", None), (None, None), ("n/a", None)]
)
def test_clean_money(raw, value):
    assert bp._clean_money(raw) == value


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
        {"year": "2023", "month": "07", "url": "https://www.spearfish.gov/Archive.aspx?ADID=1500"},  # known fix
    ]


def test_scrape_reads_the_newest_reports(monkeypatch):
    links = "".join(
        f'<a href="Archive.aspx?ADID={100 + m}">Building Permits Report - {month} 2026</a>'
        for m, month in enumerate(["January", "February", "March", "April", "May", "June", "July", "August"], 1)
    )
    fetched = []

    def get(url, **kw):
        fetched.append(url)
        if url == bp.ARCHIVE_URL:
            return FakeResponse(text=f'<div id="modulecontent">{links}</div>')
        return FakeResponse(content=REPORT.read_bytes())

    monkeypatch.setattr(bp.net, "get", get)
    monkeypatch.setattr(bp.time, "sleep", lambda s: None)
    monkeypatch.setattr(bp.geo, "geocode", lambda addresses: {"412 W JACKSON BLVD": (44.49, -103.86)})
    records = bp.BuildingPermits().scrape()

    assert len(fetched) == 1 + bp.RECENT_MONTHS  # archive page, then only the newest reports
    assert "ADID=108" in fetched[1] and "ADID=101" not in " ".join(fetched)
    r = next(r for r in records if r["permit_number"] == "CAA-26-22" and r["month"] == "08")
    assert r["permit_key"] == "CAA-26-22|2026-08"
    assert r["url"].endswith("ADID=108")
    assert (
        r["title"]
        == "Commercial Alterations, Additions, or Tenant Improvements — 412 W Jackson Blvd, Spearfish, SD 57783"
    )
    assert (r["lat"], r["lon"]) == (44.49, -103.86)

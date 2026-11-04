"""
tests/test_trends.py

The building trends page's figures: which permits count as new homes, money
labels, inflation adjustment, and the year-by-year rows.
"""

from __future__ import annotations

from datetime import date

import pytest
from markupsafe import Markup

from sitegen import trends
from sitegen.build import together


def _permit(report, kind="Residential New Construction", cost=100_000, category="new_construction", **extra):
    return {"year": report[:4], "month": report[5:], "report": report, "construction_type": kind,
            "cost_approximate": cost, "category": category, **extra}  # fmt: skip


@pytest.mark.parametrize(
    "kind, home",
    [("RES-NEW DWELLING", True), ("Residential New Construction", True), ("MFG MH PLACEMENT", True),
     ("RES-NEW DWELL-TWNHS-1OF4", True), ("RES-GARAGE", False), ("COMM-NEW BUILDING", False),
     ("RES-NEW DECK W PATIO", False), ("RES-NEW DWELLING FNDN", False)],
)  # fmt: skip
def test_new_homes(kind, home):
    assert trends.is_new_home(_permit("2020-01", kind)) is home


def test_money_short():
    assert trends.money_short(83_300_000) == "$83.3M"
    assert trends.money_short(52_000_000) == "$52M"
    assert trends.money_short(325_000) == "$325K"


def test_deflator_uses_the_month_before_a_skipped_one():
    index = {"2025-09": 300.0, "2025-11": 303.0, "2026-08": 330.0}  # no October 2025, as the BLS skipped it
    d = trends.Deflator(index, latest_report="2026-09")
    assert d.base_month == "2026-08" and d.label == "August 2026"
    assert d(100, "2025-10") == pytest.approx(110)  # October priced at September's index
    assert d(100, "2026-09") == pytest.approx(100)  # a month not yet published counts as the base
    assert d(None, "2025-09") is None


def test_rows_ytd_and_biggest_projects_both_ways():
    records = [
        _permit("2024-03", cost=200_000),
        _permit("2024-11", cost=300_000),
        _permit("2025-02", cost=250_000),
        _permit("2025-02", kind="COMMERCIAL ALTERATION", cost=1_000_000, category="alterations"),
    ]
    index = {"2024-03": 100.0, "2024-11": 100.0, "2025-02": 125.0}
    t = trends.build(records, date(2025, 3, 15), index)
    y2024, y2025 = t["rows"]
    assert (y2024["homes"], y2024["value"], y2024["median_home"]) == (2, 500_000, 250_000)
    assert y2024["value_real"] == pytest.approx(625_000) and y2024["median_home_real"] == pytest.approx(312_500)
    assert y2025["months"] == 1 and t["ytd"]["then"]["homes"] == 0  # Jan–Feb 2024 had none
    assert t["dollars_of"] == "February 2025"
    assert [p["value"] for p in t["biggest"]][:2] == [1_000_000, 300_000]
    assert t["biggest_real"][1]["value"] == pytest.approx(375_000)


def test_without_cpi_the_adjusted_figures_are_the_reported_ones():
    t = trends.build([_permit("2024-03")], date(2025, 1, 1), None)
    assert t["dollars_of"] == "" and t["rows"][0]["value_real"] == t["rows"][0]["value"]


def test_together_keeps_each_piece_whole():
    out = together(["Police", "", "posted Oct 16", "<b>"])
    assert isinstance(out, Markup)
    assert out == ('<span class="inline-block">Police</span> · <span class="inline-block">posted Oct 16</span> · '
                   '<span class="inline-block">&lt;b&gt;</span>')  # fmt: skip

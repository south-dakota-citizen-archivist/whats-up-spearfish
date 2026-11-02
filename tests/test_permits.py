"""
tests/test_permits.py

Address normalization, the planning archive index, and the per-address grouping
behind the "What's being built here?" page.
"""

from __future__ import annotations

import json

import pytest

from scrapers import geo
from scripts.build_planning_archive import HISTORICAL_LABELS, index_row
from sitegen.data import Site
from sitegen.pages import friendly_status, friendly_type, permit_category, permit_sites, pretty_address


class TestNormalizeAddress:
    @pytest.mark.parametrize(
        "a, b",
        [
            ("2312 Platinum Drive, Spearfish, SD 57783", "2312 PLATINUM DR"),
            ("2430 PLATINUM DR, Unit 3, SPEARFISH, SD 57783", "2430 PLATINUM DR"),
            ("2430 Platinum Drive 2", "2430 PLATINUM DR"),
            ("517 N Main Street, Unit STE B", "517 N MAIN ST"),
            ("1 Main St #4", "1 MAIN ST"),
            ("515 27TH ST N.", "515 N 27TH ST"),
        ],
    )
    def test_same_place(self, a, b):
        assert geo.normalize_address(a) == b

    def test_keeps_highway_number(self):
        assert geo.normalize_address("100 HWY 14") == "100 HWY 14"

    @pytest.mark.parametrize("a", ["", "Spearfish, SD", "Main Street", "0"])
    def test_no_house_number(self, a):
        assert geo.normalize_address(a) == ""

    def test_bbox(self):
        assert geo.in_spearfish(44.49, -103.86)
        assert not geo.in_spearfish(53.34, 4.74)
        assert not geo.in_spearfish(None, None)


def test_pretty_address():
    assert pretty_address("2312 PLATINUM DRIVE, SPEARFISH, SD 57783") == "2312 Platinum Drive, Spearfish, SD 57783"
    assert pretty_address("515 N 27th St") == "515 N 27th St"  # mixed case left alone


class TestFriendly:
    @pytest.mark.parametrize(
        "raw, nice",
        [
            ("Res New (pre-2020 system)", "Residential new construction"),
            ("Rt Of Way (pre-2020 system)", "Street or sidewalk work"),
            ("Res-New Dwelling", "Residential new dwelling"),
            ("Comm-Alteration", "Commercial alteration"),
            ("BASEMENT FINISH", "Basement finish"),
            ("Business Occupancy Permit - Spearfish", "Business occupancy permit"),
            ("$ 216.00", "Building permit"),  # column misread in the PDF
            ("ALLIED CON", "Building permit"),  # a contractor name in the type column
            ("", "Building permit"),
        ],
    )
    def test_type(self, raw, nice):
        assert friendly_type(raw) == nice

    @pytest.mark.parametrize(
        "type_name, number, cat",
        [
            ("Residential New Construction", "RNC-26-55", "r"),
            ("Standalone Permits - Plumbing, Mechanical, Gas", "CBP-25-3", "c"),  # number wins
            ("Com Roof (pre-2020 system)", "130303", "c"),
            ("Res Garage (pre-2020 system)", "", "r"),
            ("Basement", "", "r"),
            ("Sign Permit", "", "c"),
            ("Minor Final Plat", "", "l"),
            ("Rt Of Way (pre-2020 system)", "", "l"),
            ("Mech Perm (pre-2020 system)", "", "o"),
        ],
    )
    def test_category(self, type_name, number, cat):
        assert permit_category(type_name, number) == cat

    def test_status(self):
        assert friendly_status("Complete") == "Completed"
        assert friendly_status("Voided") == "Canceled"
        assert friendly_status("HERITAGE DRIVE") == ""  # misfiled street name


class TestIndexRow:
    def _historical(self):
        values = ["SMITH, JANE", "08/20/2014", "08/22/2013", "130303", "BASEMENT", "Complete", "WARD AVENUE", "3793"]
        form = [
            {"field_id": 20866 + i, "label": label, "value": v}
            for i, (label, v) in enumerate(zip(HISTORICAL_LABELS, values))
        ]
        return {
            "record_id": 2000,
            "detail": "full",
            "record": {"recordTypeName": "Historical Basement", "status": 2, "dateCreated": "2020-03-01T00:00:00Z"},
            "form": form,
        }

    def test_historical_uses_form_dates_and_address(self):
        row = index_row(self._historical())
        assert row["created"] == "2013-08-22"  # issued date, not the 2020 migration date
        assert row["expires"] == "2014-08-20"
        assert row["address"] == "3793 WARD AVENUE"
        assert row["applicant"] == "SMITH, JANE"
        assert row["historical_no"] == "130303"
        assert row["type"] == "Basement (pre-2020 system)"
        assert row["site"] is True

    def test_contractor_license_not_a_site(self):
        row = index_row(
            {"record_id": 1, "detail": "full", "record": {"recordTypeName": "Contractor License"}, "form": []}
        )
        assert row["site"] is False

    def test_bad_coordinates_dropped(self):
        rec = {"recordTypeName": "Sign Permit", "fullAddress": "1 Main St", "latitude": "53.3", "longitude": "4.7"}
        row = index_row({"record_id": 1, "detail": "full", "record": rec, "form": []})
        assert "lat" not in row

    def test_html_stripped_from_picked_fields(self):
        form = [{"field_id": 1, "label": "Description of Work", "value": "<div>Replace <b>roof</b></div>"}]
        row = index_row({"record_id": 1, "detail": "full", "record": {"recordTypeName": "Roof"}, "form": form})
        assert row["description"] == "Replace roof"


def test_permit_sites_groups_by_address(tmp_path):
    (tmp_path / "archive").mkdir()
    archive = {
        "meta": {},
        "records": [
            {
                "id": 1,
                "site": True,
                "address": "2430 PLATINUM DR, Unit 3, SPEARFISH, SD 57783",
                "type": "Sign Permit",
                "submitted": "2024-11-19",
                "lat": 44.47,
                "lon": -103.82,
            },
            {
                "id": 2,
                "site": False,
                "address": "9 Elsewhere St",
                "type": "Contractor License",
                "submitted": "2024-01-01",
            },
        ],
    }
    (tmp_path / "archive" / "planning_index.json").write_text(json.dumps(archive))
    permits = {
        "records": [
            {
                "site_address": "2430 Platinum Drive",
                "date": "2026-09-01",
                "construction_type": "SHED",
                "permit_number": "26-1",
                "url": "https://example.com/r.pdf",
            }
        ]
    }
    (tmp_path / "building_permits.json").write_text(json.dumps(permits))

    sites = permit_sites(Site(tmp_path))
    assert len(sites) == 1
    s = sites[0]
    assert s["k"] == "2430 PLATINUM DR"
    assert s["lat"] == 44.47
    assert [r["src"] for r in s["r"]] == ["permit", "app"]  # newest first
    assert [r["c"] for r in s["r"]] == ["r", "c"]
    assert s["r"][0]["t"] == "Shed"
    assert s["lp"] == 1

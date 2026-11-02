"""
tests/test_address.py

Address standardization (scrapers/address.py): the cases local records
actually contain, from city permits, OpenGov, agendas and county parcels.
"""

from __future__ import annotations

import pytest

from scrapers import address


@pytest.mark.parametrize(
    "a, b",
    [
        ("1725 MAIN ST N", "1725 N Main Street"),  # direction before or after the street
        ("515 27TH ST N.", "515 N 27TH ST"),
        ("2312 Platinum Drive, Spearfish, SD 57783", "2312 PLATINUM DR"),
        ("2430 PLATINUM DR, Unit 3, SPEARFISH, SD 57783", "2430 Platinum Drive 2"),  # units share the building
        ("4025 E. COLORADO BLVD.", "4025 E COLORADO BLVD"),
        ("6845 SAINT ONGE RD", "6845 ST ONGE RD"),
        ("540 32ND ST-GA OFFICE", "540 32ND ST"),  # tag glued to the street type
        ("20189 US HWY 85-CAMPGROUND", "20189 US Highway 85"),
        ("440 HERITAGE DR, SPEARFISH, SD  57783", "440 Heritage Drive"),  # county SITUS format
    ],
)
def test_same_place(a, b):
    assert address.key(a) == address.key(b)


def test_key_and_loose():
    assert address.key("1440 N MAIN ST") == "1440 N MAIN ST"
    assert address.loose("1440 N MAIN ST") == address.loose("1440 MAIN ST") == "1440 MAIN ST"


def test_units_kept_apart_from_key():
    (a,) = address.parse("300 AVIATION PL, UNIT 254")
    assert a.key() == "300 AVIATION PL" and a.unit == "UNIT 254"


def test_several_addresses_in_one_field():
    assert address.keys("2545 & 2555 CLEAR SPRING RD") == ["2545 CLEAR SPRING RD", "2555 CLEAR SPRING RD"]
    assert address.keys("3813 & 3815 Rock Ridge, Spearfish, SD 57783") == ["3813 ROCK RDG", "3815 ROCK RDG"]


@pytest.mark.parametrize("text", ["", "0", "Main Street", "Intersection of St. Onge Road and HWY 85", "City-wide"])
def test_not_an_address(text):
    assert address.parse(text) == ()
    assert address.key(text) == ""

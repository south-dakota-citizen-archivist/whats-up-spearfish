"""
tests/test_scraper_public_bids.py

Tests for the _closes_iso() helper in scrapers/sources/public_bids.py.
"""

from __future__ import annotations

import pytest

from scrapers.sources.public_bids import _closes_iso


class TestClosesIso:
    def test_full_datetime_with_time(self):
        assert _closes_iso("4/8/2026 1:30 PM") == "2026-04-08T13:30:00"

    def test_date_only(self):
        assert _closes_iso("4/8/2026") == "2026-04-08T00:00:00"

    def test_midnight(self):
        assert _closes_iso("1/1/2026 12:00 AM") == "2026-01-01T00:00:00"

    def test_noon(self):
        assert _closes_iso("6/15/2026 12:00 PM") == "2026-06-15T12:00:00"

    def test_single_digit_month_and_day(self):
        assert _closes_iso("1/2/2026 9:00 AM") == "2026-01-02T09:00:00"

    def test_whitespace_stripped(self):
        assert _closes_iso("  4/8/2026 1:30 PM  ") == "2026-04-08T13:30:00"

    def test_empty_string_returns_empty(self):
        assert _closes_iso("") == ""

    def test_unparseable_returns_empty(self):
        assert _closes_iso("not a date") == ""

    def test_sorts_correctly(self):
        """ISO strings from _closes_iso sort in chronological order."""
        dates = ["4/15/2026 1:30 PM", "4/1/2026 1:30 PM", "4/8/2026 1:30 PM"]
        sorted_iso = sorted(_closes_iso(d) for d in dates)
        assert sorted_iso == [
            "2026-04-01T13:30:00",
            "2026-04-08T13:30:00",
            "2026-04-15T13:30:00",
        ]

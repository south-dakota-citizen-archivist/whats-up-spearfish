"""
tests/test_scraper_library_circulation.py

Unit tests for scrapers/sources/library_circulation.py:
  - _int_or_none()
"""

from __future__ import annotations


class TestIntOrNone:
    def _fn(self, val):
        from scrapers.sources.library_circulation import _int_or_none

        return _int_or_none(val)

    def test_integer_string(self):
        assert self._fn("5539") == 5539

    def test_zero(self):
        assert self._fn("0") == 0

    def test_empty_string(self):
        assert self._fn("") is None

    def test_whitespace_only(self):
        assert self._fn("   ") is None

    def test_whitespace_padded_number(self):
        assert self._fn("  7482  ") == 7482

    def test_non_numeric(self):
        assert self._fn("n/a") is None

    def test_float_string(self):
        # CSV values are always integers for this dataset; floats are invalid
        assert self._fn("5539.0") is None

    def test_negative(self):
        # Loan counts are never negative, but the function should handle it
        assert self._fn("-1") == -1

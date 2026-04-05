"""
tests/test_scraper_bhnf_projects.py

Unit tests for scrapers/sources/bhnf_projects.py:
  - _milestone_sort_key()
"""

from __future__ import annotations


class TestMilestoneSortKey:
    def _fn(self, date_str):
        from scrapers.sources.bhnf_projects import _milestone_sort_key

        return _milestone_sort_key(date_str)

    # Full MM/DD/YYYY dates
    def test_full_date(self):
        assert self._fn("01/28/2026") == "2026-01-28"

    def test_single_digit_month_day(self):
        assert self._fn("9/1/2025") == "2025-09-01"

    def test_zero_padded(self):
        assert self._fn("04/10/2026") == "2026-04-10"

    # Month/year only (estimated)
    def test_month_year_only(self):
        assert self._fn("02/2026") == "2026-02"

    def test_month_year_single_digit(self):
        assert self._fn("7/2026") == "2026-07"

    # With "(Estimated)" suffix stripped
    def test_estimated_suffix_stripped(self):
        assert self._fn("06/2026 (Estimated)") == "2026-06"

    def test_estimated_with_nbsp(self):
        # Non-breaking space before "(Estimated)" — already replaced by scraper,
        # but key function should handle the plain space version
        assert self._fn("07/2026 (Estimated)") == "2026-07"

    # Fallback
    def test_empty_returns_fallback(self):
        assert self._fn("") == "9999-99"

    def test_unparseable_returns_fallback(self):
        assert self._fn("Unknown") == "9999-99"

    def test_text_only_returns_fallback(self):
        assert self._fn("TBD") == "9999-99"

    # Ordering
    def test_earlier_date_sorts_before_later(self):
        assert self._fn("01/28/2026") < self._fn("06/2026 (Estimated)")

    def test_2025_sorts_before_2026(self):
        assert self._fn("9/1/2025") < self._fn("02/2026")

    def test_real_dates_sort_before_fallback(self):
        assert self._fn("12/31/2099") < self._fn("TBD")

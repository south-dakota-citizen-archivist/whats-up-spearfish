"""
tests/test_build.py

Tests for build.py: _to_mountain timezone parsing, group_records filtering/sorting,
and the Jinja2 custom filters and tests.
"""

from __future__ import annotations

import datetime
import hashlib
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# _to_mountain
# ---------------------------------------------------------------------------


class TestToMountain:
    def _fn(self, value):
        from build import _to_mountain

        return _to_mountain(value)

    def test_none_returns_none(self):
        assert self._fn(None) is None

    def test_empty_returns_none(self):
        assert self._fn("") is None

    def test_invalid_returns_none(self):
        assert self._fn("not a date") is None

    def test_date_only_is_midnight_mountain(self):
        from zoneinfo import ZoneInfo

        MT = ZoneInfo("America/Denver")
        result = self._fn("2026-04-01")
        assert result is not None
        assert result.date() == datetime.date(2026, 4, 1)
        assert result.tzinfo == MT
        assert result.hour == 0
        assert result.minute == 0

    def test_naive_datetime_assumed_utc_and_shifted(self):
        # "2026-04-01 14:30:00" is naive → treated as UTC → 08:30 MDT (UTC-6)
        result = self._fn("2026-04-01 14:30:00")
        assert result is not None
        assert result.hour == 8
        assert result.minute == 30

    def test_aware_iso8601_converted_to_mt(self):
        # 2026-04-01T14:30:00-06:00 is already at MDT offset; should stay 14:30
        result = self._fn("2026-04-01T14:30:00-06:00")
        assert result is not None
        assert result.hour == 14
        assert result.minute == 30

    def test_mdt_string_stays_at_stated_time(self):
        # Chamber-style string with MDT label
        result = self._fn("2026-04-01 8:30 AM MDT")
        assert result is not None
        assert result.hour == 8
        assert result.minute == 30

    def test_mst_string_stays_at_stated_time(self):
        result = self._fn("2026-01-15 8:30 AM MST")
        assert result is not None
        assert result.hour == 8
        assert result.minute == 30


# ---------------------------------------------------------------------------
# group_records
# ---------------------------------------------------------------------------

_TODAY = datetime.date(2026, 4, 1)


class TestGroupRecords:
    def _call(self, data, today=_TODAY):
        import build

        with patch("build.TODAY", today):
            return build.group_records(data)

    def test_groups_by_record_type(self):
        data = {
            "src": [
                {"record_type": "news", "title": "A", "published": "2026-04-01"},
                {"record_type": "event", "title": "B", "start_dt": "2026-04-02"},
            ]
        }
        groups = self._call(data)
        assert "news" in groups
        assert "event" in groups

    def test_source_slug_attached(self):
        data = {"my_source": [{"record_type": "news", "published": "2026-04-01"}]}
        groups = self._call(data)
        assert groups["news"][0]["_source"] == "my_source"

    def test_past_events_excluded(self):
        data = {
            "src": [
                {"record_type": "event", "title": "Past", "start_dt": "2026-03-31"},
                {"record_type": "event", "title": "Future", "start_dt": "2026-04-05"},
            ]
        }
        titles = [e["title"] for e in self._call(data).get("event", [])]
        assert "Past" not in titles
        assert "Future" in titles

    def test_today_event_included(self):
        data = {"src": [{"record_type": "event", "title": "Today", "start_dt": "2026-04-01"}]}
        titles = [e["title"] for e in self._call(data).get("event", [])]
        assert "Today" in titles

    def test_events_sorted_ascending(self):
        data = {
            "src": [
                {"record_type": "event", "title": "Later", "start_dt": "2026-04-10"},
                {"record_type": "event", "title": "Sooner", "start_dt": "2026-04-02"},
            ]
        }
        titles = [e["title"] for e in self._call(data)["event"]]
        assert titles == ["Sooner", "Later"]

    def test_event_without_date_not_filtered_out(self):
        # Events with no parseable date should survive (dt is None → kept)
        data = {"src": [{"record_type": "event", "title": "No Date"}]}
        titles = [e["title"] for e in self._call(data).get("event", [])]
        assert "No Date" in titles

    def test_school_menus_future_only(self):
        data = {
            "src": [
                {"record_type": "school_menu", "title": "Old Menu", "start_dt": "2026-03-31"},
                {"record_type": "school_menu", "title": "New Menu", "start_dt": "2026-04-05"},
            ]
        }
        titles = [m["title"] for m in self._call(data).get("school_menu", [])]
        assert "Old Menu" not in titles
        assert "New Menu" in titles

    def test_news_sorted_descending(self):
        data = {
            "src": [
                {"record_type": "news", "title": "Older", "published": "2026-03-30"},
                {"record_type": "news", "title": "Newer", "published": "2026-04-01"},
            ]
        }
        titles = [n["title"] for n in self._call(data)["news"]]
        assert titles[0] == "Newer"

    def test_empty_data_returns_empty(self):
        assert self._call({}) == {}

    def test_multiple_sources_merged_into_same_type(self):
        data = {
            "src_a": [{"record_type": "news", "title": "A", "published": "2026-04-01"}],
            "src_b": [{"record_type": "news", "title": "B", "published": "2026-03-31"}],
        }
        groups = self._call(data)
        assert len(groups["news"]) == 2

    # 30-day cutoff for document / news / press_release
    def test_news_older_than_30_days_excluded(self):
        data = {
            "src": [
                {"record_type": "news", "title": "Old", "published": "2026-03-01"},  # 31 days before TODAY
                {"record_type": "news", "title": "Recent", "published": "2026-03-15"},
            ]
        }
        titles = [r["title"] for r in self._call(data).get("news", [])]
        assert "Old" not in titles
        assert "Recent" in titles

    def test_document_older_than_30_days_excluded(self):
        data = {
            "src": [
                {"record_type": "document", "title": "Stale", "date": "2026-02-01"},
                {"record_type": "document", "title": "Fresh", "date": "2026-03-20"},
            ]
        }
        titles = [r["title"] for r in self._call(data).get("document", [])]
        assert "Stale" not in titles
        assert "Fresh" in titles

    def test_press_release_older_than_30_days_excluded(self):
        data = {
            "src": [
                {"record_type": "press_release", "title": "Old PR", "date": "2026-01-01"},
                {"record_type": "press_release", "title": "New PR", "date": "2026-04-01"},
            ]
        }
        titles = [r["title"] for r in self._call(data).get("press_release", [])]
        assert "Old PR" not in titles
        assert "New PR" in titles

    def test_record_exactly_30_days_ago_included(self):
        data = {
            "src": [
                {"record_type": "news", "title": "Boundary", "published": "2026-03-02"},  # exactly 30 days before Apr 1
            ]
        }
        titles = [r["title"] for r in self._call(data).get("news", [])]
        assert "Boundary" in titles

    def test_undated_record_kept_by_30_day_filter(self):
        data = {"src": [{"record_type": "document", "title": "No Date"}]}
        titles = [r["title"] for r in self._call(data).get("document", [])]
        assert "No Date" in titles

    def test_future_dated_record_kept_by_30_day_filter(self):
        data = {
            "src": [
                {"record_type": "news", "title": "Future News", "published": "2026-06-01"},
            ]
        }
        titles = [r["title"] for r in self._call(data).get("news", [])]
        assert "Future News" in titles


# ---------------------------------------------------------------------------
# Jinja2 filters
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def jinja_env():
    import build

    with patch("build.TODAY", _TODAY):
        return build.make_env()


class TestFormatDate:
    def test_iso_date(self, jinja_env):
        f = jinja_env.filters["format_date"]
        assert f("2026-04-01") == "April 1, 2026"

    def test_none_returns_empty(self, jinja_env):
        f = jinja_env.filters["format_date"]
        assert f(None) == ""

    def test_custom_format(self, jinja_env):
        f = jinja_env.filters["format_date"]
        result = f("2026-04-01", fmt="%Y/%m/%d")
        assert result == "2026/04/01"


class TestFormatDatetime:
    def test_datetime_string_returns_time(self, jinja_env):
        f = jinja_env.filters["format_datetime"]
        result = f("2026-04-01T14:30:00-06:00")
        assert result == "2:30 PM"

    def test_date_only_returns_empty(self, jinja_env):
        f = jinja_env.filters["format_datetime"]
        assert f("2026-04-01") == ""

    def test_none_returns_empty(self, jinja_env):
        f = jinja_env.filters["format_datetime"]
        assert f(None) == ""

    def test_midnight_returns_empty(self, jinja_env):
        f = jinja_env.filters["format_datetime"]
        # A naive midnight datetime is treated as UTC midnight → 6 PM MT
        # The important test is the date-only fast-path
        assert f("2026-04-01") == ""


class TestFormatDay:
    def test_wednesday_april_first(self, jinja_env):
        f = jinja_env.filters["format_day"]
        assert f("2026-04-01") == "Wed, Apr 1"

    def test_none_returns_empty(self, jinja_env):
        f = jinja_env.filters["format_day"]
        assert f(None) == ""


class TestStableId:
    def test_returns_12_char_hex(self, jinja_env):
        f = jinja_env.filters["stable_id"]
        result = f("hello")
        assert len(result) == 12
        assert all(c in "0123456789abcdef" for c in result)

    def test_deterministic(self, jinja_env):
        f = jinja_env.filters["stable_id"]
        assert f("same") == f("same")

    def test_different_inputs_differ(self, jinja_env):
        f = jinja_env.filters["stable_id"]
        assert f("a") != f("b")

    def test_matches_sha1(self, jinja_env):
        f = jinja_env.filters["stable_id"]
        expected = hashlib.sha1(b"test").hexdigest()[:12]
        assert f("test") == expected


# ---------------------------------------------------------------------------
# Jinja2 tests (is_today, is_this_week)
# ---------------------------------------------------------------------------


class TestIsToday:
    def _test(self, value):
        import build

        with patch("build.TODAY", _TODAY):
            return build.make_env().tests["today"](value)

    def test_today_is_true(self):
        assert self._test("2026-04-01") is True

    def test_yesterday_is_false(self):
        assert self._test("2026-03-31") is False

    def test_tomorrow_is_false(self):
        assert self._test("2026-04-02") is False

    def test_none_is_false(self):
        assert self._test(None) is False


class TestIsThisWeek:
    def _test(self, value):
        import build

        with patch("build.TODAY", _TODAY):
            return build.make_env().tests["this_week"](value)

    def test_today_is_this_week(self):
        assert self._test("2026-04-01") is True

    def test_six_days_ahead_is_this_week(self):
        assert self._test("2026-04-07") is True

    def test_seven_days_ahead_is_not_this_week(self):
        assert self._test("2026-04-08") is False

    def test_yesterday_is_not_this_week(self):
        assert self._test("2026-03-31") is False

    def test_none_is_false(self):
        assert self._test(None) is False

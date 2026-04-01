"""
tests/test_utils.py

Tests for scrapers/utils.py: parse_date, make_slug, fetch_html, fetch_json.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from scrapers.utils import fetch_html, fetch_json, make_slug, parse_date


class TestParseDate:
    # ── None / empty ──────────────────────────────────────────────────────────

    def test_none_returns_none(self):
        assert parse_date(None) is None

    def test_empty_returns_none(self):
        assert parse_date("") is None

    def test_whitespace_only_returns_none(self):
        assert parse_date("   ") is None

    # ── ISO formats ───────────────────────────────────────────────────────────

    def test_iso_datetime(self):
        assert parse_date("2026-04-01T08:30:00") == "2026-04-01T08:30:00"

    def test_iso_datetime_z(self):
        assert parse_date("2026-04-01T08:30:00Z") == "2026-04-01T08:30:00"

    def test_iso_datetime_with_offset(self):
        # isoformat() preserves the offset when tzinfo is present
        result = parse_date("2026-04-01T08:30:00-06:00")
        assert result is not None
        assert result.startswith("2026-04-01T08:30:00")

    def test_iso_date_only(self):
        assert parse_date("2026-04-01") == "2026-04-01"

    def test_iso_datetime_with_space_separator(self):
        assert parse_date("2026-04-01 08:30:00") == "2026-04-01T08:30:00"

    # ── US slash formats ──────────────────────────────────────────────────────

    def test_mm_dd_yyyy_12hr(self):
        assert parse_date("04/01/2026 08:30 AM") == "2026-04-01T08:30:00"

    def test_mm_dd_yyyy_24hr(self):
        assert parse_date("04/01/2026 08:30") == "2026-04-01T08:30:00"

    def test_mm_dd_yyyy_date_only(self):
        assert parse_date("04/01/2026") == "2026-04-01"

    # ── Long month name formats ───────────────────────────────────────────────

    def test_long_month_with_time(self):
        assert parse_date("April 1, 2026 8:30 AM") == "2026-04-01T08:30:00"

    def test_long_month_date_only(self):
        assert parse_date("April 1, 2026") == "2026-04-01"

    def test_abbr_month(self):
        assert parse_date("Apr 1, 2026") == "2026-04-01"

    def test_abbr_month_with_period(self):
        assert parse_date("Apr. 1, 2026") == "2026-04-01"

    def test_day_long_month_year(self):
        assert parse_date("1 April 2026") == "2026-04-01"

    def test_weekday_long_month(self):
        assert parse_date("Wednesday, April 1, 2026") == "2026-04-01"

    # ── Midnight → date-only ─────────────────────────────────────────────────

    def test_midnight_datetime_returns_date_only(self):
        assert parse_date("2026-04-01T00:00:00") == "2026-04-01"

    def test_midnight_with_space_returns_date_only(self):
        assert parse_date("2026-04-01 00:00:00") == "2026-04-01"

    # ── Non-midnight has time component ──────────────────────────────────────

    def test_non_midnight_returns_datetime(self):
        result = parse_date("2026-04-01 08:30:00")
        assert "T" in result
        assert "08:30:00" in result

    # ── Whitespace normalisation ──────────────────────────────────────────────

    def test_extra_whitespace_normalised(self):
        assert parse_date("  April  1,  2026  ") == "2026-04-01"

    # ── Unparseable ───────────────────────────────────────────────────────────

    def test_unparseable_string_returns_none(self):
        assert parse_date("not a date") is None

    def test_partial_date_returns_none(self):
        assert parse_date("April 2026") is None


class TestMakeSlug:
    def test_basic(self):
        assert make_slug("Hello World") == "hello-world"

    def test_special_chars_removed(self):
        assert make_slug("Events & Activities!") == "events-activities"

    def test_unicode_transliterated(self):
        assert make_slug("Café") == "cafe"

    def test_numbers_preserved(self):
        assert "2026" in make_slug("Event 2026")

    def test_max_length_respected(self):
        assert len(make_slug("a" * 100)) <= 80

    def test_empty_string(self):
        assert make_slug("") == ""

    def test_source_slug_pattern(self):
        # Common usage: make_slug("SourceName-Title of Article")
        result = make_slug("Black Hills Pioneer-Some Big Story")
        assert len(result) <= 80
        assert "black" in result


class TestFetchHtml:
    def _mock_resp(self, text="<html></html>"):
        resp = MagicMock()
        resp.text = text
        resp.raise_for_status.return_value = None
        return resp

    def test_returns_beautifulsoup(self):
        from bs4 import BeautifulSoup

        with patch("scrapers.utils.requests.get", return_value=self._mock_resp()):
            result = fetch_html("http://example.com")
        assert isinstance(result, BeautifulSoup)

    def test_default_timeout_30(self):
        with patch("scrapers.utils.requests.get", return_value=self._mock_resp()) as mock_get:
            fetch_html("http://example.com")
        _, kwargs = mock_get.call_args
        assert kwargs.get("timeout") == 30

    def test_default_headers_set(self):
        with patch("scrapers.utils.requests.get", return_value=self._mock_resp()) as mock_get:
            fetch_html("http://example.com")
        _, kwargs = mock_get.call_args
        assert "User-Agent" in kwargs.get("headers", {})

    def test_caller_can_override_timeout(self):
        with patch("scrapers.utils.requests.get", return_value=self._mock_resp()) as mock_get:
            fetch_html("http://example.com", timeout=5)
        _, kwargs = mock_get.call_args
        assert kwargs.get("timeout") == 5

    def test_raises_on_http_error(self):
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("404")
        with patch("scrapers.utils.requests.get", return_value=resp):
            with pytest.raises(requests.HTTPError):
                fetch_html("http://example.com")


class TestFetchJson:
    def _mock_resp(self, data=None):
        resp = MagicMock()
        resp.json.return_value = data or {}
        resp.raise_for_status.return_value = None
        return resp

    def test_returns_parsed_json(self):
        with patch("scrapers.utils.requests.get", return_value=self._mock_resp({"key": "val"})):
            result = fetch_json("http://example.com/api")
        assert result == {"key": "val"}

    def test_default_timeout_30(self):
        with patch("scrapers.utils.requests.get", return_value=self._mock_resp()) as mock_get:
            fetch_json("http://example.com/api")
        _, kwargs = mock_get.call_args
        assert kwargs.get("timeout") == 30

    def test_raises_on_http_error(self):
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("500")
        with patch("scrapers.utils.requests.get", return_value=resp):
            with pytest.raises(requests.HTTPError):
                fetch_json("http://example.com/api")

"""
tests/test_calendar_feed.py

Tests for calendar_feed.py: _parse_dt, generate_ics, generate_rss.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import timezone

import pytest

from calendar_feed import _parse_dt, generate_ics, generate_rss

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def patch_output_dir(tmp_path, monkeypatch):
    """Redirect OUTPUT_DIR and ROOT to a temp directory for every test in this module."""
    import calendar_feed
    monkeypatch.setattr(calendar_feed, "OUTPUT_DIR", tmp_path)
    monkeypatch.setattr(calendar_feed, "ROOT", tmp_path)
    return tmp_path


# ---------------------------------------------------------------------------
# _parse_dt
# ---------------------------------------------------------------------------

class TestParseDt:
    def test_none_returns_none(self):
        assert _parse_dt(None) is None

    def test_empty_returns_none(self):
        assert _parse_dt("") is None

    def test_invalid_returns_none(self):
        assert _parse_dt("not-a-date") is None

    def test_iso_with_offset(self):
        result = _parse_dt("2026-04-01T10:00:00-06:00")
        assert result is not None
        assert result.tzinfo is not None
        assert result.year == 2026

    def test_iso_utc_z(self):
        result = _parse_dt("2026-04-01T10:00:00Z")
        assert result.hour == 10

    def test_date_only_has_utc_tzinfo(self):
        result = _parse_dt("2026-04-01")
        assert result is not None
        assert result.tzinfo == timezone.utc

    def test_naive_datetime_gets_utc(self):
        result = _parse_dt("2026-04-01T10:00:00")
        assert result.tzinfo == timezone.utc

    def test_space_separated_datetime(self):
        result = _parse_dt("2026-04-01 10:00:00")
        assert result is not None
        assert result.hour == 10


# ---------------------------------------------------------------------------
# generate_ics
# ---------------------------------------------------------------------------

class TestGenerateIcs:
    def _records(self, **overrides):
        r = {"title": "Test Event", "start_dt": "2026-04-01", "url": "http://example.com"}
        r.update(overrides)
        return [r]

    def test_creates_ics_file(self, tmp_path):
        generate_ics(self._records())
        assert (tmp_path / "calendar.ics").exists()

    def test_empty_records_creates_file(self, tmp_path):
        generate_ics([])
        assert (tmp_path / "calendar.ics").exists()

    def test_skips_record_without_date(self, tmp_path):
        generate_ics([{"title": "No Date", "record_type": "event"}])
        content = (tmp_path / "calendar.ics").read_bytes().decode()
        assert "No Date" not in content

    def test_includes_title(self, tmp_path):
        generate_ics(self._records(title="My Special Event"))
        content = (tmp_path / "calendar.ics").read_bytes().decode()
        assert "My Special Event" in content

    def test_includes_url(self, tmp_path):
        generate_ics(self._records(url="http://specific.com/event"))
        content = (tmp_path / "calendar.ics").read_bytes().decode()
        assert "http://specific.com/event" in content

    def test_includes_location(self, tmp_path):
        generate_ics(self._records(location="Main Street Park"))
        content = (tmp_path / "calendar.ics").read_bytes().decode()
        assert "Main Street Park" in content

    def test_uses_date_field_fallback(self, tmp_path):
        generate_ics([{"title": "Date Field Event", "date": "2026-04-01"}])
        content = (tmp_path / "calendar.ics").read_bytes().decode()
        assert "Date Field Event" in content

    def test_multiple_events(self, tmp_path):
        records = [
            {"title": "Event A", "start_dt": "2026-04-01"},
            {"title": "Event B", "start_dt": "2026-04-02"},
        ]
        generate_ics(records)
        content = (tmp_path / "calendar.ics").read_bytes().decode()
        assert "Event A" in content
        assert "Event B" in content


# ---------------------------------------------------------------------------
# generate_rss
# ---------------------------------------------------------------------------

class TestGenerateRss:
    def _event(self, **overrides):
        r = {"title": "Test Event", "start_dt": "2026-04-01", "record_type": "event",
             "url": "http://example.com"}
        r.update(overrides)
        return r

    def test_creates_feed_xml(self, tmp_path):
        generate_rss([self._event()])
        assert (tmp_path / "feed.xml").exists()

    def test_event_records_included(self, tmp_path):
        generate_rss([self._event(title="Local Meetup")])
        content = (tmp_path / "feed.xml").read_text()
        assert "Local Meetup" in content

    def test_news_record_excluded(self, tmp_path):
        records = [
            self._event(title="Event"),
            {"title": "News Article", "record_type": "news", "published": "2026-04-01"},
        ]
        generate_rss(records)
        content = (tmp_path / "feed.xml").read_text()
        assert "Event" in content
        assert "News Article" not in content

    def test_record_with_start_dt_included_regardless_of_type(self, tmp_path):
        records = [{"title": "Menu Day", "start_dt": "2026-04-01", "record_type": "school_menu"}]
        generate_rss(records)
        content = (tmp_path / "feed.xml").read_text()
        assert "Menu Day" in content

    def test_caps_at_100_items(self, tmp_path):
        records = [self._event(title=f"Event {i}") for i in range(150)]
        generate_rss(records)
        tree = ET.parse(tmp_path / "feed.xml")
        items = tree.findall(".//item")
        assert len(items) == 100

    def test_empty_records_creates_file(self, tmp_path):
        generate_rss([])
        assert (tmp_path / "feed.xml").exists()

    def test_valid_xml(self, tmp_path):
        generate_rss([self._event()])
        # Should parse without error
        ET.parse(tmp_path / "feed.xml")

    def test_sorted_descending_by_start_dt(self, tmp_path):
        records = [
            self._event(title="Earlier", start_dt="2026-04-01"),
            self._event(title="Later", start_dt="2026-04-10"),
        ]
        generate_rss(records)
        tree = ET.parse(tmp_path / "feed.xml")
        titles = [el.text for el in tree.findall(".//item/title")]
        assert titles[0] == "Later"

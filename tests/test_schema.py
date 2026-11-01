"""
tests/test_schema.py

Timestamp parsing (scrapers/dates.py) and record normalization (scrapers/schema.py).
"""

from __future__ import annotations

from datetime import date

import pytest

from scrapers import dates, schema


class TestParse:
    @pytest.mark.parametrize(
        "value, expected",
        [
            ("2026-11-02", "2026-11-02"),
            ("November 2, 2026", "2026-11-02"),  # date-only text stays a date (no UTC shift)
            ("7/13/2026", "2026-07-13"),
            ("2026-10-24 2:00 PM MDT", "2026-10-24T14:00:00-06:00"),
            ("Wed, 09 Sep 2026 14:46:04 -0700", "2026-09-09T15:46:04-06:00"),
            ("2026-11-03T22:00:00Z", "2026-11-03T15:00:00-07:00"),
        ],
    )
    def test_formats(self, value, expected):
        assert dates.iso(dates.parse(value)) == expected

    def test_naive_defaults_to_utc(self):
        assert dates.iso(dates.parse("2026-11-08T00:00:00")) == "2026-11-07T17:00:00-07:00"

    def test_naive_local(self):
        assert dates.iso(dates.parse("2026-11-08T18:00:00", dates.MT)) == "2026-11-08T18:00:00-07:00"

    @pytest.mark.parametrize("value", [None, "", "not a date"])
    def test_unparseable(self, value):
        assert dates.parse(value) is None


def _norm(rec, kind="event", **kw):
    args = dict(kind=kind, source="src", source_label="Source", dedup_key="url", naive_tz=dates.UTC)
    args.update(kw)
    return schema.normalize(rec, **args)


class TestEvents:
    def test_timed_event(self):
        r = _norm({"url": "u", "title": "Game", "start_dt": "2026-11-03T22:00:00Z", "end_dt": "2026-11-04T00:00:00Z"})
        assert r["start"] == "2026-11-03T15:00:00-07:00"
        assert r["end"] == "2026-11-03T17:00:00-07:00"
        assert r["all_day"] is False
        assert r["date"] == "2026-11-03"

    def test_date_only_is_all_day(self):
        r = _norm({"url": "u", "title": "Fair", "start_dt": "2026-11-03"})
        assert r["all_day"] is True
        assert r["start"] == "2026-11-03"

    def test_explicit_all_day_drops_time(self):
        r = _norm(
            {"url": "u", "title": "TBA game", "start_dt": "2026-11-03T00:00:00", "all_day": True}, naive_tz=dates.MT
        )
        assert r["start"] == "2026-11-03"

    def test_category_default(self):
        assert _norm({"url": "u", "title": "x", "start_dt": "2026-11-03"}, category="arts")["event_category"] == "arts"

    def test_missing_start_is_invalid(self):
        assert _norm({"url": "u", "title": "x"}) is None

    def test_missing_title_is_invalid(self):
        assert _norm({"url": "u", "title": " ", "start_dt": "2026-11-03"}) is None

    def test_html_stripped(self):
        r = _norm({"url": "u", "title": "<b>Show</b>", "start_dt": "2026-11-03", "description": "<p>Fun</p>"})
        assert r["title"] == "Show"
        assert r["description"] == "Fun"


class TestOtherKinds:
    def test_news_gets_published_and_date(self):
        r = _norm({"url": "u", "title": "Story", "published": "Wed, 09 Sep 2026 14:46:04 -0700"}, kind="news")
        assert r["date"] == "2026-09-09"
        assert r["published"].startswith("2026-09-09T15:46")

    def test_undated_kind_is_fine(self):
        assert _norm({"url": "u", "title": "IPA"}, kind="beer")["kind"] == "beer"

    def test_stable_id(self):
        a = _norm({"url": "u", "title": "x"}, kind="beer")
        b = _norm({"url": "u", "title": "y"}, kind="beer")
        assert a["id"] == b["id"]

    def test_record_type_overrides_default_kind(self):
        assert schema.kind_of({"record_type": "event"}, "press_release") == "event"


class TestExpiry:
    today = date(2026, 11, 1)
    cutoff = date(2026, 9, 1)

    def test_past_event_expires(self):
        assert schema.is_expired({"date": "2026-10-30"}, "event", self.today, self.cutoff)

    def test_multiday_event_still_running(self):
        assert not schema.is_expired({"date": "2026-10-29", "end": "2026-11-02"}, "event", self.today, self.cutoff)

    def test_old_news_expires(self):
        assert schema.is_expired({"date": "2026-09-15"}, "news", self.today, self.cutoff)

    def test_undated_uses_first_seen(self):
        assert schema.is_expired({"_first_seen": "2026-08-01"}, "project", self.today, self.cutoff)
        assert not schema.is_expired({"_first_seen": "2026-10-01"}, "project", self.today, self.cutoff)

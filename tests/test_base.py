"""
tests/test_base.py

Tests for scrapers/base.py: envelopes, normalization on save, merge/replace,
retention windows and the empty-result guard.
"""

from __future__ import annotations

import json
from datetime import timedelta

import pytest

from scrapers import dates
from scrapers.base import BaseScraper, ScrapeEmpty


class _Scraper(BaseScraper):
    name = "Test Scraper"
    slug = "test_scraper"
    kind = "news"

    def __init__(self, records=None):
        super().__init__()
        self._fresh = list(records or [])

    def scrape(self):
        return list(self._fresh)


def _news(url, days_ago=0, **kw):
    return {
        "url": url,
        "title": f"Story {url}",
        "published": (dates.today() - timedelta(days=days_ago)).isoformat(),
        **kw,
    }


def _saved(data_dir, slug="test_scraper"):
    return json.loads((data_dir / f"{slug}.json").read_text())


class TestInit:
    def test_missing_name_raises(self):
        class S(BaseScraper):
            slug = "s"

            def scrape(self):
                return []

        with pytest.raises(ValueError, match="name"):
            S()

    def test_missing_slug_raises(self):
        class S(BaseScraper):
            name = "S"

            def scrape(self):
                return []

        with pytest.raises(ValueError, match="slug"):
            S()

    def test_data_file_path(self, data_dir):
        assert _Scraper().data_file == data_dir / "test_scraper.json"


class TestEnvelope:
    def test_writes_envelope(self, data_dir):
        _Scraper([_news("a")]).run()
        env = _saved(data_dir)
        assert env["slug"] == "test_scraper"
        assert env["kind"] == "news"
        assert env["count"] == 1
        assert env["fetched_at"]
        assert env["records"][0]["url"] == "a"

    def test_records_are_normalized(self, data_dir):
        _Scraper([_news("a")]).run()
        rec = _saved(data_dir)["records"][0]
        assert rec["source"] == "test_scraper"
        assert rec["source_label"] == "Test Scraper"
        assert rec["kind"] == "news"
        assert rec["date"] == dates.today().isoformat()
        assert len(rec["id"]) == 12
        assert rec["_first_seen"] == dates.today().isoformat()

    def test_legacy_list_file_is_readable(self, data_dir):
        (data_dir / "test_scraper.json").write_text(json.dumps([{"url": "old"}]))
        assert _Scraper().load_existing() == [{"url": "old"}]

    def test_malformed_file_reads_as_empty(self, data_dir):
        (data_dir / "test_scraper.json").write_text("{not json")
        assert _Scraper().load_existing() == []

    def test_object_source_saves_data(self, data_dir):
        class Obj(BaseScraper):
            name, slug, kind = "Obj", "obj", "gauge"

            def scrape(self):
                return {"current": {"cfs": 10}}

        Obj().run()
        assert _saved(data_dir, "obj")["data"] == {"current": {"cfs": 10}}


class TestMerge:
    def test_new_count(self, data_dir):
        _Scraper([_news("a")]).run()
        result = _Scraper([_news("a"), _news("b")]).run()
        assert result.new == 1
        assert result.count == 2

    def test_keeps_records_no_longer_listed(self, data_dir):
        _Scraper([_news("a"), _news("b")]).run()
        _Scraper([_news("b"), _news("c")]).run()
        assert {r["url"] for r in _saved(data_dir)["records"]} == {"a", "b", "c"}

    def test_fresh_record_wins_but_keeps_first_seen(self, data_dir):
        _Scraper([_news("a", title="Old title")]).run()
        env = _saved(data_dir)
        env["records"][0]["_first_seen"] = "2026-01-01"
        (data_dir / "test_scraper.json").write_text(json.dumps(env))
        _Scraper([_news("a", title="New title")]).run()
        rec = _saved(data_dir)["records"][0]
        assert rec["title"] == "New title"
        assert rec["_first_seen"] == "2026-01-01"

    def test_prunes_records_outside_window(self, data_dir):
        _Scraper([_news("old", days_ago=45), _news("new")]).run()  # news window is 30 days
        assert [r["url"] for r in _saved(data_dir)["records"]] == ["new"]

    def test_dedupes_within_batch(self, data_dir):
        _Scraper([_news("a"), _news("a")]).run()
        assert _saved(data_dir)["count"] == 1


class TestReplace:
    def test_replace_drops_missing_records(self, data_dir):
        class Taps(_Scraper):
            kind = "beer"
            replace = True

        Taps([{"url": "x", "title": "IPA"}, {"url": "y", "title": "Stout"}]).run()
        Taps([{"url": "y", "title": "Stout"}]).run()
        assert [r["title"] for r in _saved(data_dir)["records"]] == ["Stout"]


class TestGuards:
    def test_empty_scrape_raises_and_keeps_previous(self, data_dir):
        _Scraper([_news("a")]).run()
        before = (data_dir / "test_scraper.json").read_text()
        with pytest.raises(ScrapeEmpty):
            _Scraper([]).run()
        assert (data_dir / "test_scraper.json").read_text() == before

    def test_min_records_zero_allows_empty(self, data_dir):
        class Alerts(_Scraper):
            kind = "alert"
            replace = True
            min_records = 0

        assert Alerts([]).run().count == 0
        assert _saved(data_dir)["records"] == []

    def test_invalid_records_dropped(self, data_dir):
        result = _Scraper([_news("a"), {"url": "no-title"}, "junk"]).run()
        assert result.count == 1
        assert result.dropped == 2

    def test_all_invalid_counts_as_empty(self, data_dir):
        with pytest.raises(ScrapeEmpty, match="invalid"):
            _Scraper([{"url": "no-title"}]).run()

    def test_fix_hook_runs_before_normalize(self, data_dir):
        class Fixed(_Scraper):
            def fix(self, record):
                return {**record, "title": record["title"].upper()}

        Fixed([_news("a")]).run()
        assert _saved(data_dir)["records"][0]["title"] == "STORY A"


def test_data_folder_is_the_named_one_or_the_live_copy(monkeypatch, tmp_path):
    from scrapers import livedata

    monkeypatch.setenv("WUS_DATA_DIR", str(tmp_path))
    assert livedata.data_dir() == tmp_path
    monkeypatch.delenv("WUS_DATA_DIR")
    assert livedata.data_dir() == livedata.CACHE  # never a stale folder in the repo
    assert livedata.CACHE.relative_to(livedata.ROOT).parts[0] == ".cache"

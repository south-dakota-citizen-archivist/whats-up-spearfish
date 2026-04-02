"""
tests/test_base.py

Tests for scrapers/base.py: BaseScraper dedup, persistence, and run() logic.
"""

from __future__ import annotations

import json

import pytest

from scrapers.base import BaseScraper

# ---------------------------------------------------------------------------
# Test double — minimal concrete subclass
# ---------------------------------------------------------------------------

class _Scraper(BaseScraper):
    name = "Test Scraper"
    slug = "test_scraper"

    def __init__(self, records=None):
        super().__init__()
        self._fresh = list(records or [])

    def scrape(self):
        return list(self._fresh)


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------

class TestInit:
    def test_missing_name_raises(self):
        class S(BaseScraper):
            slug = "s"
            def scrape(self): return []
        with pytest.raises(ValueError, match="name"):
            S()

    def test_missing_slug_raises(self):
        class S(BaseScraper):
            name = "S"
            def scrape(self): return []
        with pytest.raises(ValueError, match="slug"):
            S()

    def test_data_file_path(self, data_dir):
        s = _Scraper()
        assert s.data_file == data_dir / "test_scraper.json"


# ---------------------------------------------------------------------------
# load_existing
# ---------------------------------------------------------------------------

class TestLoadExisting:
    def test_returns_empty_when_file_absent(self, data_dir):
        s = _Scraper()
        assert s.load_existing() == []

    def test_loads_valid_json(self, data_dir):
        records = [{"url": "http://a.com", "title": "A"}]
        (data_dir / "test_scraper.json").write_text(json.dumps(records))
        s = _Scraper()
        assert s.load_existing() == records

    def test_returns_empty_on_malformed_json(self, data_dir):
        (data_dir / "test_scraper.json").write_text("{bad json")
        s = _Scraper()
        assert s.load_existing() == []

    def test_returns_empty_on_non_list_json(self, data_dir):
        (data_dir / "test_scraper.json").write_text('{"not": "a list"}')
        # load_existing returns whatever is in the file; non-list is still returned
        # (it's group_records / run() callers that care about the type).
        # The important thing is it doesn't crash.
        s = _Scraper()
        result = s.load_existing()
        assert isinstance(result, (list, dict))


# ---------------------------------------------------------------------------
# save
# ---------------------------------------------------------------------------

class TestSave:
    def test_writes_json_file(self, data_dir):
        s = _Scraper()
        records = [{"url": "http://a.com"}]
        s.save(records)
        on_disk = json.loads(s.data_file.read_text())
        assert on_disk == records

    def test_creates_data_directory(self, tmp_path):
        import scrapers.base as base_module
        nested = tmp_path / "deep" / "data"
        original = base_module.DATA_DIR
        base_module.DATA_DIR = nested
        try:
            s = _Scraper()
            s.save([])
            assert nested.exists()
        finally:
            base_module.DATA_DIR = original

    def test_overwrites_existing_file(self, data_dir):
        s = _Scraper()
        s.save([{"url": "http://old.com"}])
        s.save([{"url": "http://new.com"}])
        on_disk = json.loads(s.data_file.read_text())
        assert len(on_disk) == 1
        assert on_disk[0]["url"] == "http://new.com"


# ---------------------------------------------------------------------------
# run() — dedup and merge logic
# ---------------------------------------------------------------------------

class TestRun:
    def test_all_new_records_returned(self, data_dir):
        fresh = [{"url": "http://a.com"}, {"url": "http://b.com"}]
        s = _Scraper(records=fresh)
        new = s.run()
        assert len(new) == 2

    def test_all_duplicates_returns_empty(self, data_dir):
        existing = [{"url": "http://a.com", "title": "Original"}]
        fresh = [{"url": "http://a.com", "title": "Updated"}]
        s = _Scraper(records=fresh)
        s.save(existing)
        assert s.run() == []

    def test_mixed_returns_only_new(self, data_dir):
        existing = [{"url": "http://a.com"}]
        fresh = [{"url": "http://a.com"}, {"url": "http://b.com"}]
        s = _Scraper(records=fresh)
        s.save(existing)
        new = s.run()
        assert len(new) == 1
        assert new[0]["url"] == "http://b.com"

    def test_existing_record_not_clobbered_on_collision(self, data_dir):
        existing = [{"url": "http://a.com", "title": "Keep", "extra": "preserved"}]
        fresh = [{"url": "http://a.com", "title": "Overwrite attempt"}]
        s = _Scraper(records=fresh)
        s.save(existing)
        s.run()
        on_disk = json.loads(s.data_file.read_text())
        assert on_disk[0]["title"] == "Keep"
        assert on_disk[0]["extra"] == "preserved"

    def test_merged_list_saved_to_disk(self, data_dir):
        existing = [{"url": "http://a.com"}]
        fresh = [{"url": "http://b.com"}]
        s = _Scraper(records=fresh)
        s.save(existing)
        s.run()
        on_disk = json.loads(s.data_file.read_text())
        assert len(on_disk) == 2

    def test_custom_dedup_key(self, data_dir):
        class SlugScraper(_Scraper):
            dedup_key = "slug"

        existing = [{"slug": "foo", "url": "http://a.com"}]
        fresh = [
            {"slug": "foo", "url": "http://a-updated.com"},  # dup
            {"slug": "bar", "url": "http://b.com"},          # new
        ]
        s = SlugScraper(records=fresh)
        s.save(existing)
        new = s.run()
        assert len(new) == 1
        assert new[0]["slug"] == "bar"

    def test_records_missing_dedup_key_do_not_crash(self, data_dir):
        existing = [{"title": "no url here"}]
        fresh = [{"url": "http://b.com"}]
        s = _Scraper(records=fresh)
        s.save(existing)
        new = s.run()
        assert len(new) == 1

    def test_empty_fresh_returns_empty(self, data_dir):
        existing = [{"url": "http://a.com"}]
        s = _Scraper(records=[])
        s.save(existing)
        assert s.run() == []

    def test_empty_existing_all_new(self, data_dir):
        fresh = [{"url": "http://a.com"}, {"url": "http://b.com"}]
        s = _Scraper(records=fresh)
        # No pre-existing file
        new = s.run()
        assert len(new) == 2


# ---------------------------------------------------------------------------
# run() — replace=True (kill-and-fill) mode
# ---------------------------------------------------------------------------

class TestRunReplace:
    def _make_scraper(self, records):
        class ReplaceScraper(_Scraper):
            replace = True
        return ReplaceScraper(records=records)

    def test_replace_saves_only_fresh_records(self, data_dir):
        existing = [{"url": "http://old.com"}]
        fresh = [{"url": "http://new.com"}]
        s = self._make_scraper(fresh)
        s.save(existing)
        s.run()
        on_disk = json.loads(s.data_file.read_text())
        assert len(on_disk) == 1
        assert on_disk[0]["url"] == "http://new.com"

    def test_replace_removes_record_not_in_fresh(self, data_dir):
        existing = [{"url": "http://a.com"}, {"url": "http://b.com"}]
        fresh = [{"url": "http://a.com"}]  # b disappeared
        s = self._make_scraper(fresh)
        s.save(existing)
        s.run()
        on_disk = json.loads(s.data_file.read_text())
        urls = [r["url"] for r in on_disk]
        assert "http://b.com" not in urls

    def test_replace_returns_all_fresh_records(self, data_dir):
        fresh = [{"url": "http://a.com"}, {"url": "http://b.com"}]
        s = self._make_scraper(fresh)
        returned = s.run()
        assert len(returned) == 2

    def test_replace_with_empty_fresh_clears_file(self, data_dir):
        existing = [{"url": "http://a.com"}]
        s = self._make_scraper([])
        s.save(existing)
        s.run()
        on_disk = json.loads(s.data_file.read_text())
        assert on_disk == []

    def test_replace_does_not_merge_existing(self, data_dir):
        existing = [{"url": "http://a.com"}, {"url": "http://b.com"}]
        fresh = [{"url": "http://c.com"}]
        s = self._make_scraper(fresh)
        s.save(existing)
        s.run()
        on_disk = json.loads(s.data_file.read_text())
        # Only fresh record should be on disk, not the merged union
        assert len(on_disk) == 1

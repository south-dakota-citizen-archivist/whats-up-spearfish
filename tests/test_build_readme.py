"""
tests/test_build_readme.py

Unit tests for scripts/build_readme.py:
  - _data_stats() handles nested-list JSON (ebird, library_circulation, bhnf_projects, danr_public_notices)
  - _data_stats() handles flat-dict JSON (inaturalist_plant_cache)
  - _data_stats() handles plain-list JSON (the common case)
  - _build_readme() produces a table with the expected rows
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(tmp_path: Path, stem: str, data) -> None:
    (tmp_path / f"{stem}.json").write_text(json.dumps(data))


# ---------------------------------------------------------------------------
# _data_stats
# ---------------------------------------------------------------------------


class TestDataStats:
    def _call(self, tmp_path):
        # Ensure the script's repo root is on sys.path

        with patch("scripts.build_readme.DATA_DIR", tmp_path):
            from scripts.build_readme import _data_stats

            return _data_stats()

    def test_plain_list_json(self, tmp_path):
        records = [{"record_type": "event"}, {"record_type": "event"}]
        _write_json(tmp_path, "my_source", records)
        stats = self._call(tmp_path)
        assert stats["my_source"]["count"] == 2
        assert "event" in stats["my_source"]["types"]

    def test_ebird_nested_observations(self, tmp_path):
        data = {"fetched_at": "2026-04-04", "observations": [{"a": 1}, {"b": 2}]}
        _write_json(tmp_path, "ebird", data)
        stats = self._call(tmp_path)
        assert stats["ebird"]["count"] == 2

    def test_library_circulation_nested_rows(self, tmp_path):
        rows = [{"year": 2026, "month": 1}] * 24
        _write_json(tmp_path, "library_circulation", {"fetched_at": "", "rows": rows})
        stats = self._call(tmp_path)
        assert stats["library_circulation"]["count"] == 24

    def test_bhnf_projects_nested_projects(self, tmp_path):
        projects = [{"title": "Project A"}, {"title": "Project B"}]
        _write_json(tmp_path, "bhnf_projects", {"fetched_at": "", "projects": projects})
        stats = self._call(tmp_path)
        assert stats["bhnf_projects"]["count"] == 2

    def test_danr_public_notices_nested_notices(self, tmp_path):
        notices = [{"notice_type": "Water Rights"} for _ in range(8)]
        _write_json(tmp_path, "danr_public_notices", {"fetched_at": "", "notices": notices})
        stats = self._call(tmp_path)
        assert stats["danr_public_notices"]["count"] == 8

    def test_flat_dict_json_counts_keys(self, tmp_path):
        # inaturalist_plant_cache is a flat dict keyed by USDA symbol
        cache = {f"SYM{i}": {"taxon_id": i} for i in range(317)}
        _write_json(tmp_path, "inaturalist_plant_cache", cache)
        stats = self._call(tmp_path)
        assert stats["inaturalist_plant_cache"]["count"] == 317

    def test_malformed_json_returns_zero_count(self, tmp_path):
        # _data_stats silently catches parse errors and returns count=0
        (tmp_path / "broken.json").write_text("{bad json")
        stats = self._call(tmp_path)
        assert stats["broken"]["count"] == 0

    def test_record_types_extracted(self, tmp_path):
        records = [
            {"record_type": "news"},
            {"record_type": "event"},
            {"record_type": "news"},
        ]
        _write_json(tmp_path, "src", records)
        stats = self._call(tmp_path)
        assert set(stats["src"]["types"]) == {"news", "event"}

    def test_records_without_type_omitted_from_types(self, tmp_path):
        records = [{"title": "No type"}]
        _write_json(tmp_path, "typeless", records)
        stats = self._call(tmp_path)
        assert stats["typeless"]["types"] == []

    def test_empty_nested_list(self, tmp_path):
        _write_json(tmp_path, "ebird", {"fetched_at": "", "observations": []})
        stats = self._call(tmp_path)
        assert stats["ebird"]["count"] == 0


# ---------------------------------------------------------------------------
# _build_readme — table content spot-checks
# ---------------------------------------------------------------------------


class TestBuildReadme:
    def _call(self, slug_to_name, stats):
        from scripts.build_readme import _build_readme

        return _build_readme(slug_to_name, stats)

    def test_table_header_present(self):
        md = self._call({}, {})
        assert "| Source | Slug | Record types | Count |" in md

    def test_known_slug_in_table(self):
        md = self._call({"my_scraper": "My Scraper"}, {"my_scraper": {"count": 5, "types": ["event"]}})
        assert "My Scraper" in md
        assert "`my_scraper`" in md
        assert "5" in md

    def test_extra_names_shown(self):
        md = self._call({}, {"native_plants_spotlight": {"count": 317, "types": []}})
        assert "USDA PLANTS Database" in md

    def test_count_formatted_with_comma(self):
        md = self._call({"big": "Big Source"}, {"big": {"count": 24984, "types": []}})
        assert "24,984" in md

    def test_auto_titlecase_for_unknown_slug(self):
        # A slug with no BaseScraper class and not in _EXTRA_NAMES gets auto-titled
        md = self._call({}, {"some_data_source": {"count": 1, "types": []}})
        assert "Some Data Source" in md

    def test_dash_for_empty_types(self):
        md = self._call({"x": "X"}, {"x": {"count": 0, "types": []}})
        # The "—" dash for no types
        assert "—" in md

    def test_bhnf_projects_extra_name(self):
        md = self._call({}, {"bhnf_projects": {"count": 48, "types": []}})
        assert "Black Hills National Forest" in md

    def test_danr_extra_name(self):
        md = self._call({}, {"danr_public_notices": {"count": 8, "types": []}})
        assert "DANR" in md or "Agriculture" in md

    def test_ebird_extra_name(self):
        md = self._call({}, {"ebird": {"count": 50, "types": []}})
        assert "eBird" in md

    def test_library_circulation_extra_name(self):
        md = self._call({}, {"library_circulation": {"count": 124, "types": []}})
        assert "circulation" in md.lower()

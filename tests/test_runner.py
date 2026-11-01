"""
tests/test_runner.py

The runner isolates failures and records health without touching good data.
"""

from __future__ import annotations

import json

from scrapers import runner
from scrapers.base import BaseScraper


class Good(BaseScraper):
    name, slug, kind, replace = "Good", "good", "beer", True

    def scrape(self):
        return [{"url": "u", "title": "IPA"}]


class Broken(BaseScraper):
    name, slug, kind = "Broken", "broken", "beer"

    def scrape(self):
        raise RuntimeError("site changed")


class Empty(BaseScraper):
    name, slug, kind = "Empty", "empty", "beer"

    def scrape(self):
        return []


class Iced(BaseScraper):
    name, slug, kind, enabled = "Iced", "iced", "beer", False

    def scrape(self):
        raise AssertionError("should not run")


def _run(monkeypatch, classes, **kw):
    monkeypatch.setattr(runner, "discover", lambda: classes)
    return runner.run(**kw)


def test_outcomes_recorded(data_dir, monkeypatch):
    health = _run(monkeypatch, [Good, Broken, Empty, Iced])["sources"]
    assert health["good"]["status"] == "ok"
    assert health["good"]["count"] == 1
    assert health["broken"]["status"] == "error"
    assert "site changed" in health["broken"]["error"]
    assert health["empty"]["status"] == "empty"
    assert health["iced"]["status"] == "disabled"
    assert "last_run" not in health["iced"]


def test_failures_accumulate_and_reset(data_dir, monkeypatch):
    _run(monkeypatch, [Broken])
    health = _run(monkeypatch, [Broken])["sources"]
    assert health["broken"]["failures"] == 2

    class Fixed(Broken):
        def scrape(self):
            return [{"url": "u", "title": "IPA"}]

    Fixed.slug = "broken"
    health = _run(monkeypatch, [Fixed])["sources"]
    assert health["broken"]["failures"] == 0
    assert health["broken"]["status"] == "ok"


def test_failure_keeps_previous_data(data_dir, monkeypatch):
    (data_dir / "broken.json").write_text(json.dumps({"records": [{"url": "keep"}]}))
    _run(monkeypatch, [Broken])
    assert json.loads((data_dir / "broken.json").read_text())["records"] == [{"url": "keep"}]


def test_health_file_written(data_dir, monkeypatch):
    _run(monkeypatch, [Good])
    saved = json.loads((data_dir / "_health.json").read_text())
    assert saved["updated"]
    assert saved["sources"]["good"]["name"] == "Good"


def test_removed_sources_dropped_from_health(data_dir, monkeypatch):
    _run(monkeypatch, [Good, Broken])
    assert set(_run(monkeypatch, [Good])["sources"]) == {"good"}


def test_select_by_tier_and_only():
    class Frequent(Good):
        slug, tier = "frequent", "frequent"

    classes = [Good, Frequent]
    assert runner.select(classes, tier="frequent", only=None, browser=None) == [Frequent]
    assert runner.select(classes, tier=None, only=["good"], browser=None) == [Good]


def test_discover_finds_real_sources():
    slugs = {c.slug for c in runner.discover()}
    assert {"spearfish_hs_lunch", "creek_gauge", "ebird", "fire"} <= slugs


def test_health_issue_threshold():
    from scripts.health_issue import body, failing

    health = {
        "sources": {
            "a": {"status": "error", "failures": 3, "enabled": True, "name": "A", "error": "403"},
            "b": {"status": "error", "failures": 2, "enabled": True},
            "c": {"status": "empty", "failures": 5, "enabled": False},
            "d": {"status": "ok", "failures": 0, "enabled": True},
        }
    }
    rows = failing(health)
    assert [slug for slug, _ in rows] == ["a"]
    assert "`a` (A)" in body(rows)

"""
tests/test_sitegen.py

Unified events (dedupe, windowing) and a smoke build of every page from
fixture envelopes.
"""

from __future__ import annotations

import json
from datetime import date, timedelta

import pytest

from scrapers import dates
from sitegen.build import build
from sitegen.data import Site
from sitegen.events import unified_events

TODAY = dates.today()


def _iso(days=0):
    return (TODAY + timedelta(days=days)).isoformat()


def _event(source, title, day=0, time="18:00", **kw):
    start = f"{_iso(day)}T{time}:00-07:00" if time else _iso(day)
    return {
        "id": f"{source}-{title}",
        "kind": "event",
        "title": title,
        "url": f"https://example.com/{source}/{title}",
        "start": start,
        "end": "",
        "all_day": time is None,
        "date": _iso(day),
        "location": kw.pop("location", ""),
        "source": source,
        "source_label": source.replace("_", " ").title(),
        "event_category": "community",
        **kw,
    }


def _write(data_dir, slug, records=None, data=None, kind="event", status="ok", fetched=True):
    env = {"slug": slug, "name": slug.replace("_", " ").title(), "kind": kind, "url": f"https://example.com/{slug}"}
    if fetched:
        env["fetched_at"] = dates.now().isoformat()
    if data is not None:
        env["data"] = data
    else:
        env["records"] = records or []
    (data_dir / f"{slug}.json").write_text(json.dumps(env))
    health = _health(data_dir)
    health["sources"][slug] = {
        "name": env["name"],
        "kind": kind,
        "url": env["url"],
        "enabled": True,
        "status": status,
        "max_stale_hours": 48,
        "error": "boom" if status != "ok" else "",
    }
    (data_dir / "_health.json").write_text(json.dumps(health))


def _health(data_dir):
    p = data_dir / "_health.json"
    return json.loads(p.read_text()) if p.exists() else {"updated": dates.now().isoformat(), "sources": {}}


class TestUnifiedEvents:
    def test_merges_cross_posted_events(self, tmp_path):
        _write(
            tmp_path, "spearfish_calendar", [_event("spearfish_calendar", "City Council Meeting", location="City Hall")]
        )
        _write(tmp_path, "spearfish_chamber", [_event("spearfish_chamber", "Spearfish City Council Meeting")])
        events = unified_events(Site(tmp_path), TODAY)
        assert len(events) == 1
        assert events[0]["source"] == "spearfish_calendar"  # higher priority source wins
        assert events[0]["also"][0]["source"] == "Spearfish Chamber of Commerce"

    def test_different_times_not_merged(self, tmp_path):
        _write(tmp_path, "spearfish_calendar", [_event("spearfish_calendar", "Planning Commission", time="14:00")])
        _write(tmp_path, "spearfish_chamber", [_event("spearfish_chamber", "Planning Commission", time="16:00")])
        assert len(unified_events(Site(tmp_path), TODAY)) == 2

    def test_same_source_not_merged(self, tmp_path):
        recs = [_event("spearfish_sports", "Volleyball", id="a"), _event("spearfish_sports", "Volleyball", id="b")]
        _write(tmp_path, "spearfish_sports", recs)
        assert len(unified_events(Site(tmp_path), TODAY)) == 2

    def test_past_events_dropped_but_running_multiday_kept(self, tmp_path):
        recs = [
            _event("x", "Yesterday", day=-1),
            _event("x", "Book sale", day=-3, time=None, end=_iso(1)),
            _event("x", "Tomorrow", day=1),
        ]
        _write(tmp_path, "x", recs)
        titles = [e["title"] for e in unified_events(Site(tmp_path), TODAY)]
        assert titles == ["Book sale", "Tomorrow"]

    def test_time_labels(self, tmp_path):
        _write(
            tmp_path,
            "x",
            [_event("x", "Show", time="19:30", end=f"{_iso()}T21:00:00-07:00"), _event("x", "Fair", time=None)],
        )
        labels = {e["title"]: e["time"] for e in unified_events(Site(tmp_path), TODAY)}
        assert labels == {"Show": "7:30 PM–9 PM", "Fair": "All day"}


class TestSiteData:
    def test_disabled_sources_ignored(self, tmp_path):
        _write(tmp_path, "x", [_event("x", "Show")])
        h = _health(tmp_path)
        h["sources"]["x"]["enabled"] = False
        (tmp_path / "_health.json").write_text(json.dumps(h))
        assert Site(tmp_path).records(kind="event") == []

    @pytest.mark.parametrize("status, expected", [("ok", "ok"), ("error", "error"), ("empty", "empty")])
    def test_status(self, tmp_path, status, expected):
        _write(tmp_path, "x", [], status=status)
        assert Site(tmp_path).get("x").status == expected

    def test_never_fetched_is_missing(self, tmp_path):
        _write(tmp_path, "x", [], fetched=False)
        assert Site(tmp_path).get("x").status == "missing"


@pytest.fixture
def fixture_data(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    _write(d, "spearfish_calendar", [_event("spearfish_calendar", "Story Time", time="10:00")])
    _write(d, "matthews_opera_house", [_event("matthews_opera_house", "Nutcracker", day=2)])
    menu_item = {"name": "Tacos", "is_entree": True}
    _write(
        d,
        "spearfish_hs_lunch",
        [{"id": "m1", "kind": "school_menu", "title": "Tacos", "url": "u", "date": _iso(1), "menu_items": [menu_item]}],
        kind="school_menu",
    )
    _write(
        d,
        "creek_gauge",
        data={
            "current": {"cfs": 40, "ft": 4.8, "time": dates.now().isoformat()},
            "series7d": [{"t": "a", "cfs": 39}, {"t": "b", "cfs": 41}],
            "daily30": [{"date": _iso(-1), "cfs": 40}, {"date": _iso(), "cfs": 42}],
        },
        kind="gauge",
    )
    _write(d, "fire", data={"restrictions": None, "incidents": [], "danger": {"zones": []}, "errors": []}, kind="fire")
    _write(
        d,
        "ebird",
        [
            {
                "id": "b1",
                "kind": "sighting",
                "title": "Magpie",
                "common_name": "Black-billed Magpie",
                "url": "u",
                "published": dates.now().isoformat(),
                "date": _iso(),
                "location_name": "Spearfish",
            }
        ],
        kind="sighting",
    )
    _write(
        d,
        "black_hills_pioneer",
        [
            {
                "id": "n1",
                "kind": "news",
                "title": "Big news",
                "url": "u",
                "published": _iso(),
                "date": _iso(),
                "source_label": "Black Hills Pioneer",
            }
        ],
        kind="news",
    )
    _write(d, "planning_zoning", [], kind="permit", status="error")
    return d


def test_smoke_build(fixture_data, tmp_path):
    out = tmp_path / "site"
    build(fixture_data, out)
    for page in [
        "",
        "events/",
        "schools/",
        "outdoors/",
        "on-tap/",
        "civic/",
        "news/",
        "jobs/",
        "community/",
        "sources/",
        "status/",  # redirect to sources/
    ]:
        assert (out / page / "index.html").exists(), page
    for f in ["events.json", "calendar.ics", "events.xml", "404.html", "static/site.css", ".nojekyll"]:
        assert (out / f).exists(), f

    home = (out / "index.html").read_text()
    assert "Story Time" in home
    assert "Tacos" in home
    assert "Big news" in home
    assert "Black-billed Magpie" in home

    events = json.loads((out / "events.json").read_text())
    assert [e["title"] for e in events] == ["Story Time", "Nutcracker"]
    assert b"BEGIN:VEVENT" in (out / "calendar.ics").read_bytes()

    sources = (out / "sources" / "index.html").read_text()
    assert "Black Hills Pioneer" in sources
    assert "boom" not in sources  # no error messages for readers
    assert "planning_zoning" not in sources  # no internal names
    assert "url=../sources/" in (out / "status" / "index.html").read_text()


def test_relative_links(fixture_data, tmp_path):
    out = tmp_path / "site"
    build(fixture_data, out)
    assert 'href="../static/site.css' in (out / "events" / "index.html").read_text()
    assert 'href="static/site.css' in (out / "index.html").read_text()


def test_today_is_date():
    assert isinstance(TODAY, date)


def test_every_enabled_source_is_in_the_directory():
    from scrapers.runner import discover
    from sitegen.sources import directory_slugs

    enabled = {cls.slug for cls in discover() if cls.enabled}
    assert enabled - directory_slugs() == set()


def test_credit_relabels_records(tmp_path):
    _write(
        tmp_path,
        "spearfish_news",
        [
            {
                "id": "1",
                "kind": "press_release",
                "title": "t",
                "url": "u",
                "source_label": "City of Spearfish News Flash",
            }
        ],
        kind="press_release",
    )
    site = Site(tmp_path)
    assert site.get("spearfish_news").records[0]["source_label"] == "City of Spearfish"
    assert site.get("spearfish_news").label == "City of Spearfish"


def test_sources_page_plain_status(tmp_path):
    from sitegen.pages import sources_page

    _write(tmp_path, "black_hills_pioneer", [], kind="news", status="error")
    _write(tmp_path, "sdpb_news", [], kind="news")
    _write(tmp_path, "planning_zoning", [], kind="permit")
    h = _health(tmp_path)
    h["sources"]["planning_zoning"]["enabled"] = False
    (tmp_path / "_health.json").write_text(json.dumps(h))

    groups = {g["heading"]: g for g in sources_page(Site(tmp_path), [], TODAY)["groups"]}
    orgs = {o["name"]: o for o in groups["News"]["orgs"]}
    assert orgs["Black Hills Pioneer"]["offers"][0]["ok"] is False
    assert orgs["SDPB"]["offers"][0]["ok"] is True
    city = next(o for o in groups["Local government"]["orgs"] if o["name"] == "City of Spearfish")
    assert all("OpenGov" not in i["what"] for i in city["offers"])


def test_sources_page_flags_a_missing_part(tmp_path):
    from sitegen.pages import sources_page

    _write(
        tmp_path, "fire", data={"restrictions": [], "danger": {"zones": [{"name": "x", "level": "Low"}]}}, kind="fire"
    )
    groups = {g["heading"]: g for g in sources_page(Site(tmp_path), [], TODAY)["groups"]}
    offers = {i["what"]: i for o in groups["Outdoors"]["orgs"] for i in o["offers"]}
    assert offers["Fire danger"]["ok"] is True
    assert offers["Burn restrictions by county and city"]["ok"] is False

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
from sitegen.build import ago, build, day_heading
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
        assert labels == {"Show": "7:30–9 PM", "Fair": "All day"}


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
    _write(d, "fire", data={"incidents": [], "danger": {"zones": []}, "errors": []}, kind="fire")
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
                "photo_url": "https://example.com/magpie.jpg",
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
    for f in [
        "events.json",
        "calendar.ics",
        "events.xml",
        "404.html",
        "static/site.css",
        ".nojekyll",
        "permits/sites.json",
        "permits/recent.json",
    ]:
        assert (out / f).exists(), f

    home = (out / "index.html").read_text()
    assert "Story Time" in home
    assert "Tacos" in home
    assert "Big news" in home
    assert "Black-billed Magpie" in home

    events = json.loads((out / "events.json").read_text())
    assert [e["title"] for e in events] == ["Story Time", "Nutcracker"]
    assert b"BEGIN:VEVENT" in (out / "calendar.ics").read_bytes()
    # the subscribe links live on the events page only, not in every footer
    assert "calendar.ics" not in home
    events_page = (out / "events" / "index.html").read_text()
    assert "webcal://" in events_page and "calendar.google.com/calendar/render?cid=" in events_page

    # accessibility basics on every page
    for page in out.rglob("index.html"):
        html = page.read_text()
        if "Moved" in html:
            continue
        assert 'href="#main"' in html and 'id="main"' in html, page  # skip link and its target
        assert html.count("<h1") == 1, page
        assert 'role="tab"' not in html, page  # toggle buttons use aria-pressed instead
    assert ":aria-pressed=\"range === 'week'\"" in events_page  # filter buttons say which one is on

    # every page carries its build time for the "hasn't updated" note, and loads the script that shows it
    assert 'id="behind" data-built="' in home and "static/js/time.js" in home
    assert "Happening <time" in home

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

    _write(tmp_path, "black_hills_pioneer", [], kind="news", status="error")  # one failed try, data still fresh
    _write(tmp_path, "rapid_city_journal", [], kind="news", status="error", fetched=False)  # nothing current
    _write(tmp_path, "sdpb_news", [], kind="news")
    _write(tmp_path, "planning_zoning", [], kind="permit")
    h = _health(tmp_path)
    h["sources"]["planning_zoning"]["enabled"] = False
    (tmp_path / "_health.json").write_text(json.dumps(h))

    groups = {g["heading"]: g for g in sources_page(Site(tmp_path), [], TODAY)["groups"]}
    orgs = {o["name"]: o for o in groups["News"]["orgs"]}
    assert orgs["Black Hills Pioneer"]["offers"][0]["ok"] is True  # not "not updating" over one blip
    assert orgs["Rapid City Journal"]["offers"][0]["ok"] is False
    assert orgs["SDPB"]["offers"][0]["ok"] is True
    city = next(o for o in groups["Local government"]["orgs"] if o["name"] == "City of Spearfish")
    assert all("OpenGov" not in i["what"] for i in city["offers"])


def test_sources_page_flags_a_missing_part(tmp_path):
    from sitegen.pages import sources_page

    _write(
        tmp_path, "fire", data={"incidents": None, "danger": {"zones": [{"name": "x", "level": "Low"}]}}, kind="fire"
    )
    groups = {g["heading"]: g for g in sources_page(Site(tmp_path), [], TODAY)["groups"]}
    offers = {i["what"]: i for o in groups["Outdoors"]["orgs"] for i in o["offers"]}
    assert offers["Fire danger"]["ok"] is True
    assert offers["Active South Dakota wildfires"]["ok"] is False  # that part failed


def test_menu_details_full_record(tmp_path):
    from sitegen.pages import menu_details

    items = [
        {
            "name": "Pizza",
            "is_entree": True,
            "allergens": ["Milk", "Wheat"],
            "nutrition_facts": [["Calories", "200", False]],
        },
        {"name": "Juice", "allergens": ["No Allergens"], "image_url": "https://x/j.png"},
        {"name": "Cereal", "allergens": ["Not Available"]},
    ]
    _write(
        tmp_path,
        "spearfish_hs_lunch",
        [{"id": "1", "kind": "school_menu", "title": "Pizza", "url": "u", "date": _iso(1), "menu_items": items}],
        kind="school_menu",
    )
    menus = menu_details(Site(tmp_path), TODAY)
    m = menus[f"spearfish_hs_lunch|{_iso(1)}"]
    assert m["level"] == "High School" and m["meal"] == "Lunch"
    pizza, juice, cereal = m["items"]
    assert pizza["allergens"] == ["Milk", "Wheat"] and pizza["nutrition_facts"]
    assert juice["no_allergens"] is True and juice["image_url"]
    assert "allergens" not in cereal and "no_allergens" not in cereal


@pytest.mark.parametrize(
    "start, end, label",
    [
        ("2026-11-02T15:00:00-07:00", "2026-11-02T17:00:00-07:00", "3–5 PM"),
        ("2026-11-02T11:00:00-07:00", "2026-11-02T13:30:00-07:00", "11 AM–1:30 PM"),
        ("2026-11-02T09:15:00-07:00", "2026-11-02T10:00:00-07:00", "9:15–10 AM"),
        ("2026-11-02T19:00:00-07:00", "", "7 PM"),
    ],
)
def test_time_range_drops_repeated_am_pm(start, end, label):
    from sitegen.events import time_label

    assert time_label(start, end, False) == label


def test_menu_grid_spans_shared_breakfasts():
    from sitegen.pages import menu_grid

    def m(slug):
        return {"slug": slug, "key": slug, "entrees": ["x"]}

    rows = menu_grid(
        [
            m("spearfish_elem_breakfast"),
            m("spearfish_elem_k2_lunch"),
            m("spearfish_mshs_breakfast"),
            m("spearfish_hs_lunch"),
        ]
    )
    assert [(r["level"], r["breakfast_span"]) for r in rows] == [
        ("Elementary K–2", 2),
        ("Elementary 3–5", 0),
        ("Middle School", 2),
        ("High School", 0),
    ]
    assert rows[1]["lunch"] is None and rows[3]["lunch"]["slug"] == "spearfish_hs_lunch"
    assert menu_grid([]) == []


def _pets(species, n, photo=True):
    return [
        {
            "id": f"{species}{i}",
            "kind": "adoptable",
            "title": f"{species} {i}",
            "url": "u",
            "species": species,
            "image_url": f"https://example.com/{species}{i}.jpg" if photo else "",
        }
        for i in range(n)
    ]


def test_pet_picks_even_split_with_photos(tmp_path):
    import random

    from sitegen.pages import pet_picks

    _write(
        tmp_path, "whhs_adoptable", _pets("cat", 30) + _pets("dog", 6) + _pets("dog", 3, photo=False), kind="adoptable"
    )
    site = Site(tmp_path)
    picks = pet_picks(site, 8, random.Random(1))
    assert [p["species"] for p in picks] == ["cat", "dog"] * 4  # even split, alternating
    assert all(p["image_url"] for p in picks)
    assert picks != pet_picks(site, 8, random.Random(2))  # a different mix each build

    # not enough dogs with photos: cats make up the difference
    _write(tmp_path, "whhs_adoptable", _pets("cat", 30) + _pets("dog", 2), kind="adoptable")
    picks = pet_picks(Site(tmp_path), 8, random.Random(1))
    assert sorted(p["species"] for p in picks).count("dog") == 2 and len(picks) == 8


def test_tap_picks_every_venue_with_photos_represented(tmp_path):
    import random

    from sitegen.pages import tap_picks

    def beers(venue, n, photo=True):
        return [
            {"id": f"{venue}{i}", "kind": "beer", "title": f"{venue} beer {i}", "url": "u", "slug": f"{venue}-{i}",
             "image_url": f"https://example.com/{venue}{i}.png" if photo else ""}
            for i in range(n)
        ]  # fmt: skip

    _write(tmp_path, "sawyer_brewing", beers("sawyer", 20), kind="beer")
    _write(tmp_path, "killians", beers("killians", 3), kind="beer")
    _write(tmp_path, "clubhouse_spearfish", beers("clubhouse", 4, photo=False), kind="beer")
    site = Site(tmp_path)
    for seed in range(5):
        picks = tap_picks(site, 8, random.Random(seed))
        assert len(picks) == 8 and len({p["id"] for p in picks}) == 8
        assert {p["venue_slug"] for p in picks} == {"sawyer_brewing", "killians"}
        assert all(p["image_url"] for p in picks)  # no placeholders on the front page


def test_book_picks_only_with_covers(tmp_path):
    import random

    from sitegen.pages import book_picks

    books = [
        {"id": f"b{i}", "kind": "library_book", "title": f"Book {i}", "url": f"u{i}",
         "image_url": f"https://example.com/{i}.jpg" if i % 2 else ""}
        for i in range(20)
    ]  # fmt: skip
    _write(tmp_path, "spearfish_library", books, kind="library_book")
    picks = book_picks(Site(tmp_path), 8, random.Random(3))
    assert len(picks) == 8 and all(b["image_url"] for b in picks)


def _menu(slug, level, meal, dishes):
    return {
        "slug": slug,
        "key": f"{slug}|d",
        "level": level,
        "meal": meal,
        "entrees": dishes[:1],
        "items": [{"name": d} for d in dishes],
    }


def test_identical_menus_merge_into_one_group():
    from sitegen.pages import menu_grid, merge_identical

    lunch = ["Pizza", "Corn", "Milk"]
    menus = merge_identical(
        [
            _menu("spearfish_elem_breakfast", "Elementary", "Breakfast", ["Cereal"]),
            _menu("spearfish_elem_k2_lunch", "Elementary K–2", "Lunch", ["Tacos", "Milk"]),
            _menu("spearfish_elem_35_lunch", "Elementary 3–5", "Lunch", ["Tacos", "Rice", "Milk"]),  # differs by a side
            _menu("spearfish_mshs_breakfast", "Middle & High School", "Breakfast", ["Bagel"]),
            _menu("spearfish_ms_lunch", "Middle School", "Lunch", lunch),
            _menu("spearfish_hs_lunch", "High School", "Lunch", lunch),
        ]
    )
    lunches = [m["level"] for m in menus if m["meal"] == "Lunch"]
    assert lunches == ["Elementary K–2", "Elementary 3–5", "Middle & High School"]

    rows = menu_grid(menus)
    assert [(r["level"], r["breakfast_span"]) for r in rows] == [
        ("Elementary K–2", 2),
        ("Elementary 3–5", 0),
        ("Middle & High School", 1),
    ]
    assert rows[2]["lunch"]["slugs"] == ["spearfish_ms_lunch", "spearfish_hs_lunch"]


# ── dates that stay true after the build (static/js/time.js keeps them current) ──


def test_ago_is_a_time_element_the_browser_can_update():
    when = dates.now() - timedelta(hours=3)
    out = str(ago(when))
    assert out == f'<time datetime="{when.isoformat()}" data-ago>3 hours ago</time>'
    assert ">3 hours ago<" in str(ago(when.isoformat()))
    assert "data-cap>Just now<" in str(ago(dates.now(), cap=True))
    assert ago(None) == "never"


def test_day_heading_is_a_time_element_the_browser_can_relabel():
    today = dates.today()
    assert str(day_heading(today.isoformat())) == f'<time datetime="{today.isoformat()}" data-day>Today</time>'
    assert ">Tomorrow<" in str(day_heading((today + timedelta(days=1)).isoformat()))
    # mid-sentence ("Happening today") it's lowercase and flagged so the browser keeps it that way
    assert "data-lower>today<" in str(day_heading(today.isoformat(), lower=True))
    far = today + timedelta(days=9)
    assert f">{far.strftime('%A, %B %-d')}<" in str(day_heading(far.isoformat(), lower=True))
    assert day_heading("") == ""


def test_recent_sites_keep_full_history():
    from sitegen.pages import recent_sites

    today = date(2026, 11, 2)
    sites = [
        {"k": "new", "r": [{"d": "2026-09-01"}, {"d": "2009-04-01"}]},
        {"k": "old", "r": [{"d": "2015-01-01"}]},
        {"k": "edge", "r": [{"d": "2024-10-03"}]},  # two years and a month back
        {"k": "nodate", "r": [{}]},
    ]
    out = recent_sites(sites, today)
    assert [s["k"] for s in out] == ["new", "edge"]
    assert len(out[0]["r"]) == 2  # older records ride along, so a place's history is complete


# ── event text tidying ───────────────────────────────────────────────────────


def test_undouble_repeated_venue():
    from sitegen.events import undouble

    assert undouble("Lyman High School Lyman High School") == "Lyman High School"
    assert undouble("Student Union Student Union Lobby near Starbucks") == "Student Union Lobby near Starbucks"
    assert undouble("Spearfish High School Spearfish High School Auditorium") == "Spearfish High School Auditorium"
    assert undouble("Walla Walla") == "Walla Walla"  # one word repeated is a real name
    assert undouble("City Hall, 625 N 5th St") == "City Hall, 625 N 5th St"
    assert undouble("") == ""


def test_tidy_description():
    from sitegen.events import tidy_description

    assert tidy_description("Fall Play", "Fall Play") == ""
    assert tidy_description("Fall Play", "fall play.") == ""
    assert (
        tidy_description(
            "Lawrence County Democrats Monthly Meetings",
            "Lawrence County Democrats Monthly Meetings held on the 2nd Wednesday.",
        )
        == "Held on the 2nd Wednesday."
    )
    assert tidy_description("Story Time", "Songs and stories for toddlers.") == "Songs and stories for toddlers."
    assert tidy_description("Story Time", "") == ""


def test_state_notices_soonest_deadline_first_and_newest_spills(tmp_path):
    from sitegen.pages import civic

    notices = [
        {"title": "No deadline", "url": "u1", "deadline_iso": ""},
        {"title": "Later", "url": "u2", "deadline_iso": "2026-11-16"},
        {"title": "Sooner", "url": "u3", "deadline_iso": "2026-11-02"},
    ]
    _write(tmp_path, "danr_public_notices", notices, kind="notice")
    _write(tmp_path, "danr_spills", [{"title": t, "report_no": n} for t, n in (("a", "2025.189"), ("b", "2026.040"))],
           kind="spill")  # fmt: skip
    _write(tmp_path, "danr_contested_cases", [{"title": "Old", "updated": "2026-07-24"},
                                               {"title": "New", "updated": "2026-11-02"}], kind="case")  # fmt: skip
    ctx = civic(Site(tmp_path), [], date(2026, 11, 2))
    assert [n["title"] for n in ctx["notice_list"]] == ["Sooner", "Later", "No deadline"]
    assert [r["report_no"] for r in ctx["spill_list"]] == ["2026.040", "2025.189"]
    assert [c["title"] for c in ctx["case_list"]] == ["New", "Old"]


def test_text_wraps_only_when_it_runs_out_of_room():
    """No balanced wrapping and no width caps on text: both break lines that would fit."""
    import re
    from pathlib import Path

    root = Path(__file__).parent.parent / "site"
    assert not re.search(r"text-wrap:\s*(balance|pretty)", (root / "static" / "css" / "input.css").read_text())
    capped_text = re.compile(r'<(?!table|dialog)[a-z0-9]+\b[^>]*\bclass="[^"]*\bmax-w-(?!6xl|none)[^"]*"')
    found = []
    for f in (root / "templates").rglob("*.html"):
        html = f.read_text()
        found += [f"{f.name}: {tag[:80]}" for tag in capped_text.findall(html)]
        if re.search(r"\btext-(balance|pretty)\b", html):
            found.append(f"{f.name}: text-balance/text-pretty")
    assert found == []


@pytest.mark.parametrize(
    "today, lift_open, first",
    [(date(2026, 12, 5), False, True), (date(2027, 3, 30), False, True), (date(2026, 11, 4), False, False),
     (date(2026, 11, 20), True, True), (date(2027, 7, 1), False, False)],
)  # fmt: skip
def test_terry_peak_tops_the_outdoors_page_in_ski_season(today, lift_open, first):
    from sitegen.data import Source
    from sitegen.pages import terry_peak_context

    lifts = [{"name": "Stewart Lift", "open": lift_open, "type": "triple chair"}]
    site = type("S", (), {"get": lambda self, slug: Source(slug, data={"lifts": lifts, "trails": [], "snow": {}})})()
    assert terry_peak_context(site, today)["first"] is first


def test_pet_links_jump_to_the_pet_on_the_shelter_page():
    from sitegen.pages import pet_link

    cat = {"url": "https://www.westernhillshumanesociety.com/cats", "title": "Pine Cone", "description": "Male | 2 yrs"}
    assert pet_link(cat) == "https://www.westernhillshumanesociety.com/cats#:~:text=Pine%20Cone,-Male"
    assert pet_link(dict(cat, description="")).endswith("#:~:text=Pine%20Cone")
    assert pet_link(dict(cat, url="https://example.com/a#b")) == "https://example.com/a#b"  # its own anchor wins

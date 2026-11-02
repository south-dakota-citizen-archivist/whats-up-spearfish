"""
tests/test_browser.py

The built site in a real (headless) browser: every page passes an automated
accessibility check (axe) at desktop and phone widths without script errors or
sideways scrolling, and the interactive pieces work: event picks and the
calendar file, school menu pop-up, permit lookup, dates that stay true after
the build, and clear messages when data doesn't load.

Uses Playwright's Chromium; skipped when it isn't installed
(`uv run playwright install chromium`). Requests to other sites are blocked,
so nothing here touches the network.
"""

from __future__ import annotations

import functools
import http.server
import threading
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from icalendar import Calendar

from scrapers import dates
from sitegen.build import PAGES, build
from tests.test_sitegen import _event, _iso, _write

sync_api = pytest.importorskip("playwright.sync_api")

AXE = Path(pytest.importorskip("axe_playwright_python").__file__).parent / "axe.min.js"
AXE_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa", "best-practice"]
DESKTOP = {"width": 1280, "height": 900}
PHONE = {"width": 390, "height": 844}

pytestmark = pytest.mark.browser


# ── a small but complete site ────────────────────────────────────────────────


def _menu(slug, day, dishes):
    items = [
        {
            "name": d,
            "is_entree": True,
            "category": "Entree",
            "allergens": ["Milk"],
            "nutrition_facts": [["Calories", "250", False], ["Protein", "12 g", True]],
        }
        for d in dishes
    ]
    return {
        "id": f"{slug}-{day}",
        "kind": "school_menu",
        "title": dishes[0],
        "url": "https://example.com/menus",
        "date": _iso(day),
        "menu_items": items,
    }


def _permit(no, address, date, kind="Res-Deck", lat=44.49, lon=-103.86):
    return {
        "kind": "building_permit",
        "permit_number": no,
        "permit_key": f"{no}|{date[:7]}",
        "site_address": address,
        "date": date,
        "construction_type": kind,
        "cost_approximate": 12000,
        "contractor": "ACME BUILDERS",
        "applicant_name": "PAT EXAMPLE",
        "lat": lat,
        "lon": lon,
        "url": f"https://example.com/permits/{date[:7]}.pdf",
    }


@pytest.fixture(scope="module")
def site_url(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("browser")
    data = tmp / "data"
    data.mkdir()
    _write(
        data,
        "spearfish_calendar",
        [
            _event("spearfish_calendar", "Story Time", time="10:00", location="City Hall, 625 N 5th St"),
            _event("spearfish_calendar", "Craft Fair", day=1, time=None),
            _event("spearfish_calendar", "Trail Cleanup", day=3, time="09:00"),
            # long unbroken text, as real listings have, is what pushes a page sideways on small phones
            _event(
                "spearfish_calendar",
                "Registration",
                day=1,
                time="08:00",
                location="https://www.spearfish.k12.sd.us/o/spearfish-school-district/page/registration-information",
                description="Sign-up at https://www.spearfish.k12.sd.us/o/spearfish-school-district/page/registration",
            ),
        ],
    )
    _write(data, "bhsu_athletics", [_event("bhsu_athletics", "Football vs Mines", day=2, event_category="sports")])
    for slug, dishes in [("spearfish_hs_lunch", ["Tacos", "Salad bar"]), ("spearfish_mshs_breakfast", ["Pancakes"])]:
        _write(data, slug, [_menu(slug, 0, dishes), _menu(slug, 1, dishes[::-1])], kind="school_menu")
    recent = (dates.today() - timedelta(days=60)).isoformat()
    _write(
        data,
        "building_permits",
        [
            _permit("26-101", "440 Heritage Drive", recent),
            _permit("15-007", "12 Old Mill Road", "2015-06-01", kind="Comm-Roof", lon=-103.85),
        ],
        kind="building_permit",
    )
    _write(
        data,
        "creek_gauge",
        data={
            "current": {"cfs": 40, "ft": 4.8, "time": dates.now().isoformat()},
            "series7d": [
                {"t": (dates.now() - timedelta(hours=h)).isoformat(), "cfs": 38 + h % 5} for h in range(48, 0, -1)
            ],
            "daily30": [{"date": _iso(-d), "cfs": 40 + d % 4} for d in range(10, -1, -1)],
        },
        kind="gauge",
    )
    _write(data, "fire", data={"incidents": [], "danger": {"zones": []}, "errors": []}, kind="fire")
    _write(
        data,
        "black_hills_pioneer",
        [
            {
                "id": "n1",
                "kind": "news",
                "title": "Council approves budget",
                "url": "https://example.com/n1",
                "published": dates.now().isoformat(),
                "date": _iso(),
            }
        ],
        kind="news",
    )

    # community: a long shelf of new books (with links that open new tabs), pets, checkouts
    _write(
        data,
        "spearfish_library",
        [
            {"id": f"b{i}", "kind": "library_book", "title": f"A rather long book title number {i}",
             "url": f"https://example.com/book/{i}", "image_url": ""}
            for i in range(30)
        ],
        kind="library_book",
    )  # fmt: skip
    _write(
        data,
        "whhs_adoptable",
        [
            {"id": f"p{i}", "kind": "adoptable", "title": f"Pet {i}", "url": f"https://example.com/pet/{i}",
             "species": "cat" if i % 3 else "dog", "image_url": ""}
            for i in range(20)
        ],
        kind="adoptable",
    )  # fmt: skip
    _write(
        data,
        "library_circulation",
        data={
            "rows": [
                {"month": f"{y}-{m:02d}", "loans": 6000 + (m * 97) % 900, "overdrive": 3500 if y >= 2022 else None,
                 "hoopla": 800 if 2022 <= y <= 2025 else None}
                for y in range(2019, 2027) for m in range(1, 13) if (y, m) <= (2026, 4) and (y, m) != (2021, 5)
            ]
        },
        kind="stats",
    )  # fmt: skip

    # served the way GitHub Pages serves it, under /whats-up-spearfish/
    root = tmp / "root"
    build(data, root / "whats-up-spearfish")
    handler = functools.partial(QuietHandler, directory=str(root))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_port}/whats-up-spearfish/"
    server.shutdown()


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # browser not installed
            pytest.skip(f"Chromium isn't available: {exc}")
        yield b
        b.close()


@pytest.fixture
def open_page(browser, site_url):
    """open_page(path, viewport=…, clock=…, timezone=…, block=[…]) → page, with JS errors collected on page.errors."""
    contexts = []

    def _open(path="", viewport=DESKTOP, clock=None, timezone="America/Denver", block=(), wait=None):
        ctx = browser.new_context(viewport=viewport, timezone_id=timezone, accept_downloads=True)
        contexts.append(ctx)
        page = ctx.new_page()
        page.errors = []
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        # nothing leaves the machine: map tiles and photos from other sites are refused
        page.route(lambda url: not url.startswith(site_url.split("/whats-up")[0]), lambda r: r.abort())
        for name in block:
            page.route(f"**/{name}", lambda r: r.abort())
        if clock:
            page.clock.install(time=clock)
        page.goto(site_url + path)
        if wait:
            page.wait_for_selector(wait)
        page.wait_for_timeout(300)  # Alpine and the page scripts settle
        return page

    yield _open
    for ctx in contexts:
        ctx.close()


def _axe(page) -> list[str]:
    page.add_script_tag(path=str(AXE))
    result = page.evaluate("tags => axe.run(document, {runOnly: tags})", AXE_TAGS)
    return [f"{v['id']}: {v['help']} ({len(v['nodes'])}× e.g. {v['nodes'][0]['target']})" for v in result["violations"]]


# ── every page ───────────────────────────────────────────────────────────────

ALL_PAGES = [path for path, *_ in PAGES] + ["404.html"]


@pytest.mark.parametrize("viewport", [DESKTOP, PHONE], ids=["desktop", "phone"])
@pytest.mark.parametrize("path", ALL_PAGES, ids=lambda p: p or "home")
def test_page_is_accessible(open_page, path, viewport):
    page = open_page(path, viewport=viewport)
    assert _axe(page) == []
    assert page.errors == []


@pytest.mark.parametrize("path", ALL_PAGES, ids=lambda p: p or "home")
def test_page_fits_a_small_phone(open_page, path):
    page = open_page(path, viewport={"width": 320, "height": 640})
    assert page.evaluate("document.documentElement.scrollWidth") <= 320


def test_skip_link_is_first_and_focus_is_visible(open_page):
    page = open_page()
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.textContent.trim()") == "Skip to content"
    page.keyboard.press("Tab")
    page.keyboard.press("Tab")  # a link in the dark green header
    style = page.evaluate("(s => [s.outlineStyle, s.outlineWidth])(getComputedStyle(document.activeElement))")
    assert style == ["solid", "3px"]


# ── events ───────────────────────────────────────────────────────────────────


def test_events_filters_say_which_is_on(open_page):
    page = open_page("events/", wait="li input[type=checkbox]")
    assert page.locator("aside button[aria-pressed=true]").all_inner_texts() == ["Next 7 days"]
    page.locator("aside button", has_text="Sports").click()
    assert page.locator("aside button[aria-pressed=true]").count() == 2
    assert page.get_by_role("status").first.inner_text() == "1 events"


def test_events_picks_become_a_calendar_file(open_page, tmp_path):
    page = open_page("events/", wait="li input[type=checkbox]")
    page.get_by_label("Add Story Time to my calendar").check()
    page.get_by_label("Add Craft Fair to my calendar").check()
    assert page.get_by_role("status").filter(has_text="picked").inner_text().startswith("2 events picked")
    with page.expect_download() as dl:
        page.get_by_role("button", name="Add to calendar", exact=True).click()
    path = tmp_path / "picked.ics"
    dl.value.save_as(path)
    events = {str(e["summary"]): e for e in Calendar.from_ical(path.read_bytes()).walk("VEVENT")}
    assert set(events) == {"Story Time", "Craft Fair"}
    story = events["Story Time"]
    assert story.decoded("dtstart") == datetime.fromisoformat(f"{_iso()}T10:00:00-07:00")
    assert str(story["location"]) == "City Hall, 625 N 5th St"  # commas survive escaping
    fair = events["Craft Fair"]  # all day: ends the next day, calendar-style
    assert (fair.decoded("dtend") - fair.decoded("dtstart")).days == 1

    page.reload()
    page.wait_for_selector("li input[type=checkbox]")
    assert page.locator("li input[type=checkbox]:checked").count() == 2  # remembered


def test_events_today_is_spearfish_today_for_a_faraway_reader(open_page):
    # 8 PM in Spearfish is already tomorrow in Tokyo
    evening = datetime.fromisoformat(f"{_iso()}T20:00:00-07:00")
    page = open_page("events/", clock=evening, timezone="Asia/Tokyo", wait="li input[type=checkbox]")
    page.locator("aside button", has_text="Today").click()
    assert page.locator("section h2").first.inner_text().lower() == "today"
    assert "Story Time" in page.locator("section ul").first.inner_text()


def test_events_say_so_when_they_dont_load(open_page):
    page = open_page("events/", block=["events.json"])
    assert "didn't load" in page.get_by_role("alert").inner_text()
    assert page.locator("text=Loading events").is_hidden()


# ── dates after the build ────────────────────────────────────────────────────


def test_next_morning_dates_relabel_and_stale_note_shows(open_page):
    tomorrow = datetime.fromisoformat(f"{_iso(1)}T10:00:00-07:00")
    assert open_page().locator("#behind").is_hidden()
    page = open_page(clock=tomorrow)
    assert page.locator("#behind").is_visible()
    assert "hasn't updated since" in page.locator("#behind").inner_text()
    expected = (dates.today() + timedelta(days=1)).strftime("%a, %b %-d")
    assert page.locator("[data-today]").inner_text() == expected
    assert page.locator("#today h2").inner_text() == "Happening " + dates.today().strftime("%A, %B %-d")

    page = open_page("schools/", clock=tomorrow)
    assert page.locator("[aria-pressed=true]").first.inner_text() == (dates.today() + timedelta(days=1)).strftime(
        "%a %-m/%-d"
    )


# ── schools ──────────────────────────────────────────────────────────────────


def test_menu_popup_opens_with_focus_inside_and_closes(open_page):
    page = open_page("schools/")
    cell = page.locator("table button", has_text="Tacos").first
    assert "High School lunch" in cell.inner_text() or "Tacos" in cell.inner_text()
    cell.focus()
    page.keyboard.press("Enter")
    page.wait_for_selector("dialog[open]")
    assert page.evaluate("!!document.activeElement.closest('dialog')")
    assert "Contains milk" in page.locator("dialog").inner_text()
    page.keyboard.press("Escape")
    assert page.locator("dialog[open]").count() == 0


def test_old_menu_link_explains(open_page):
    page = open_page("schools/#menu=gone%7C2020-01-01")
    assert "isn't posted any more" in page.get_by_role("alert").inner_text()


# ── permits ──────────────────────────────────────────────────────────────────


def test_permits_open_with_recent_places_and_fetch_the_rest_on_search(open_page):
    fetched = []
    page = open_page("permits/", wait="#sheet-body li button")
    page.on("request", lambda r: r.url.endswith(".json") and fetched.append(r.url.rsplit("/", 1)[1]))
    assert page.locator("#sheet-body li button").all_inner_texts()[0].startswith("440 Heritage")
    assert page.locator("#sheet-body li button", has_text="Old Mill").count() == 0  # 2015: not loaded yet

    page.fill("#pq", "old mill")
    page.wait_for_selector("#sheet-body li button:has-text('Old Mill')")
    assert "sites.json" in fetched
    page.locator("#sheet-body li button", has_text="Old Mill").focus()
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    assert page.evaluate("document.activeElement.tagName") == "H2"  # focus moved to the details
    assert "15-007" in page.locator("section[x-ref=detail]").inner_text()


def test_permits_say_so_when_records_dont_load(open_page):
    page = open_page("permits/", block=["recent.json"])
    assert "didn't load" in page.get_by_role("alert").inner_text()


# ── community ────────────────────────────────────────────────────────────────


def test_community_chart_and_pets(open_page):
    page = open_page("community/", wait="#checkouts svg")
    assert page.locator("#checkouts svg path").count() == 3  # one line per way of borrowing
    assert "In April 2026" in page.locator("#checkouts").inner_text()
    shown = page.locator("#pets li:visible")
    assert shown.count() == 12
    assert "Dog" in page.locator("#pets").inner_text().split("Show all")[0]  # dogs mixed in, not after all the cats
    page.get_by_role("button", name="Show all 20 pets").click()
    page.locator("#pets li").nth(19).wait_for(state="visible")
    assert page.locator("#pets li:visible").count() == 20


def test_permits_location_refused_explains_and_offers_the_map(open_page, browser, site_url):
    # no location permission granted; on a phone the list waits behind the sheet's handle
    page = open_page("permits/", viewport=PHONE, wait="button[aria-controls=sheet-body]:has-text('most recent first')")
    page.get_by_role("button", name="Near me").click()
    alert = page.get_by_role("alert")
    alert.wait_for()
    assert "Location sharing is off" in alert.inner_text() and "Settings" in alert.inner_text()
    page.get_by_role("button", name="Show places near the middle of the map instead").click()
    assert "Closest to the middle of the map" in page.locator("button[aria-controls=sheet-body]").inner_text()

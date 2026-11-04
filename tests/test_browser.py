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
        "year": date[:4],
        "month": date[5:7],
        "report": date[:7],
        "category": "new_construction" if "New" in kind else "alterations",
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
            # a title wider than its place line, so its box is sized by the title alone
            _event("spearfish_calendar", "Toddler Story Time Downstairs", time="09:30", location="Spearfish"),
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
            # a house on a street too new for the Census geocoder; OpenStreetMap has the street
            _permit("16-003", "2312 Platinum Drive", "2016-03-01", kind="Comm-New", lat=None, lon=None),
        ],
        kind="building_permit",
    )
    (data / "_geocode_osm.json").write_text('{"2312 PLATINUM DR": [44.4789, -103.8169, "street"]}')
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
                "source": "black_hills_pioneer",
                "source_label": "Black Hills Pioneer",
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
    # beer photos are off-site, so (like every off-site request here) they fail to load
    _write(
        data,
        "sawyer_brewing",
        [
            {"id": f"s{i}", "kind": "beer", "title": f"Beer {i}", "url": "https://example.com/beer",
             "image_url": f"https://images.example.com/beer{i}.png" if i else ""}
            for i in range(3)
        ],
        kind="beer",
    )  # fmt: skip
    _write(
        data,
        "library_circulation",
        data={
            "rows": [
                {"month": f"{y}-{m:02d}", "loans": 6000 + (m * 97) % 900, "overdrive": 3500 if y >= 2022 else None,
                 "hoopla": 800 if 2022 <= y <= 2025 else None,
                 "minutes": f"https://example.com/minutes/{y}-{(m + 1) // 2}"}
                for y in range(2019, 2027) for m in range(1, 13) if (y, m) <= (2026, 4) and (y, m) != (2021, 5)
            ]
        },
        kind="stats",
    )  # fmt: skip

    # roadkill: 20 pickups in the past three weeks, each with a photo (served from nowhere)
    _write(
        data,
        "roadkill",
        data={
            "layer": "http://127.0.0.1:9/layer",
            "records": [
                {"objectid": i, "date": (dates.today() - timedelta(days=i)).isoformat(),
                 "species": ["White-tailed Deer", "Mule Deer", "Small Animal", "Elk"][i % 4], "sex": "Female",
                 "highway": "85", "comments": "Exit 10" if i == 2 else "", "lat": 44.5, "lon": -103.9,
                 "photos": [{"id": 100 + i, "type": "image/jpeg"}]}
                for i in range(1, 21)
            ],
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
def playwright():
    # one Playwright session for the module: a second one can't start while another is open
    with sync_api.sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def browser(playwright):
    try:
        b = playwright.chromium.launch()
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


def test_menu_cells_hold_their_lists_in_firefox(playwright, site_url):
    # Firefox sized rows to one line under the old 1px-tall-cell trick, so lists spilled over each other
    try:
        b = playwright.firefox.launch()
    except Exception as exc:  # browser not installed
        pytest.skip(f"Firefox isn't available: {exc}")
    page = b.new_page(viewport=DESKTOP)
    page.route(lambda url: not url.startswith(site_url.split("/whats-up")[0]), lambda r: r.abort())
    page.goto(site_url + "schools/")
    page.wait_for_selector("#menus table")
    spill = page.evaluate(
        """() => Math.max(0, ...[...document.querySelectorAll('#menus td')].flatMap(td =>
            [...td.querySelectorAll('.list-item')].map(li =>
                li.getBoundingClientRect().bottom - td.getBoundingClientRect().bottom)))"""
    )
    b.close()
    assert spill <= 1


def test_menu_cell_is_tappable_below_a_short_list(open_page):
    page = open_page("schools/")
    # the bottom-left corner of a cell, under its last dish: the whole cell opens the menu
    box = page.locator("#menus table tbody td").first.bounding_box()
    page.mouse.click(box["x"] + 4, box["y"] + box["height"] - 3)
    page.wait_for_selector("dialog[open]")


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


PLACES = "ul[aria-label=Places] li button"


def test_permits_search_waits_for_the_search_button(open_page):
    fetched = []
    page = open_page("permits/", wait=PLACES)
    page.on("request", lambda r: r.url.endswith(".json") and fetched.append(r.url.rsplit("/", 1)[1]))
    assert page.locator(PLACES).all_inner_texts()[0].startswith("440 Heritage")
    assert page.locator(PLACES, has_text="Old Mill").count() == 0  # 2015: not loaded yet
    zoom = page.locator(".permits-map").get_attribute("data-zoom")

    page.fill("#pq", "old mill")  # typing alone changes nothing: no fetch, no new list, no map move
    page.wait_for_timeout(500)
    assert "sites.json" not in fetched and page.locator(PLACES).all_inner_texts()[0].startswith("440 Heritage")
    assert page.locator(".permits-map").get_attribute("data-zoom") == zoom

    page.keyboard.press("Enter")
    page.wait_for_selector(PLACES + ":has-text('Old Mill')")  # from 2015: a search covers every year
    assert "sites.json" in fetched and page.locator("#since").input_value() == "all"
    page.locator(PLACES, has_text="Old Mill").focus()
    page.keyboard.press("Enter")
    page.wait_for_timeout(300)
    assert page.evaluate("document.activeElement.id") == "place-name"  # focus moved to its history
    assert "15-007" in page.locator("section[aria-labelledby=place-name]").text_content()  # behind "Details"
    page.get_by_role("button", name="Back to results").click()
    assert page.locator(PLACES, has_text="Old Mill").count() == 1
    page.get_by_role("button", name="Start over").click()  # and the time period goes back to what it was
    assert page.locator("#since").input_value() == "latest" and page.locator("#pq").input_value() == ""


def test_permits_start_over_puts_everything_back(open_page):
    page = open_page("permits/", wait=PLACES)
    start_over = page.get_by_role("button", name="Start over")
    assert not start_over.is_visible()  # nothing to undo yet
    view = "(() => { const m = document.querySelector('.permits-map').leaflet, c = m.getCenter();" \
           " return [+c.lat.toFixed(3), +c.lng.toFixed(3), m.getZoom()]; })()"  # fmt: skip
    before = page.evaluate(view)
    page.select_option("#what", "r")
    page.select_option("#since", "all")
    page.locator(PLACES).first.click()  # a place chosen, and the map gone to it
    page.wait_for_selector("#place-name")
    start_over.click()
    page.wait_for_timeout(1200)  # the map glides back
    assert page.locator("#since").input_value() == "latest" and page.locator("#what").input_value() == "all"
    assert page.locator("#place-name").count() == 0 and page.evaluate("location.hash") == ""
    assert page.evaluate(view) == before
    assert not start_over.is_visible()
    assert page.errors == []


def test_permits_custom_dates(open_page):
    fetched = []
    page = open_page("permits/", wait=PLACES)
    page.on("request", lambda r: r.url.endswith(".json") and fetched.append(r.url.rsplit("/", 1)[1]))
    assert page.locator("#since").input_value() == "latest"  # opens on the latest monthly report
    page.select_option("#since", "custom")
    page.fill("#from", "2015-01-01")
    page.fill("#to", "2015-12-31")
    page.wait_for_selector(PLACES + ":has-text('Old Mill')")  # older than the first download: fetched
    assert "sites.json" in fetched
    assert "Jan 1, 2015 – Dec 31, 2015" in page.locator("#results-summary").inner_text()
    assert page.locator(PLACES, has_text="440 Heritage").count() == 0  # its records are all from later


def test_dropdowns_leave_room_for_their_arrow(open_page):
    for path in ("permits/", "news/"):
        page = open_page(path)
        pads = page.evaluate(
            "[...document.querySelectorAll('select, #outlet-button')]"
            ".map(s => parseFloat(getComputedStyle(s).paddingRight))"
        )
        assert pads and min(pads) >= 30, (path, pads)


def test_permits_filters_drive_the_list_and_the_map(open_page):
    page = open_page("permits/", wait=PLACES)
    everything = page.locator("#results-summary").inner_text()
    dots = page.locator(".permits-map")
    assert int(dots.get_attribute("data-dots")) >= 1
    page.select_option("#what", "c")  # businesses: none in the past 2 years here
    page.wait_for_timeout(200)
    assert page.locator("#results-summary").inner_text().startswith("0 places") != everything.startswith("0")
    assert page.get_by_text("Nothing matches").is_visible()
    # and the map shows the same: nothing
    assert dots.get_attribute("data-dots") == "0"


def test_permits_say_so_when_records_dont_load(open_page):
    page = open_page("permits/", block=["recent.json"])
    assert "didn't load" in page.get_by_role("alert").inner_text()


# ── community ────────────────────────────────────────────────────────────────


def test_home_shows_no_placeholder_pictures(open_page):
    page = open_page("")
    # Beer 0 has no photo, so it's never picked; the others' photos fail, and a tile whose
    # photo fails goes away, taking the card with it once nothing is left
    page.wait_for_function("!document.querySelector('#taps')")
    assert page.locator("img[data-tile-photo]").count() == 0
    assert page.get_by_text("Beer 0").count() == 0


def test_titles_dont_wrap_when_their_row_has_room(open_page):
    # the hidden "(opens in a new tab)" once made links measure 1px short, so a short title wrapped,
    # and later, as a 1px box, dropped to a line of its own under a title that filled its line
    page = open_page("")
    titles = page.evaluate(
        """() => [...document.querySelectorAll('li.flex > div.min-w-0 > a')].map(a => {
            const room = a.parentElement.parentElement.getBoundingClientRect().right
                - a.parentElement.getBoundingClientRect().right;
            const lines = new Set([...a.getClientRects()].map(r => Math.round(r.top))).size;  // rows, not boxes
            return [a.textContent.trim(), lines, room];
        })"""
    )
    assert any(t.startswith("Toddler") for t, *_ in titles), titles
    assert [t for t, lines, room in titles if lines > 1 and room > 20] == []


def test_community_chart_and_pets(open_page):
    page = open_page("community/", wait="#checkouts svg")
    assert page.locator("#checkouts svg path").count() == 3  # one line per way of borrowing
    assert "In April 2026" in page.locator("#checkouts").inner_text()
    assert page.locator("#checkouts a", has_text="Library Board of Trustees meeting minutes").count() == 1
    # a year in the table opens to its months, each linked to its minutes
    page.locator("#checkouts summary").click()
    year = page.get_by_role("button", name="2025")
    assert year.get_attribute("aria-expanded") == "false"
    assert not page.locator("#checkouts-2025").is_visible()
    year.click()
    months = page.locator("#checkouts-2025 tr")
    months.first.wait_for(state="visible")
    assert months.count() == 12 and year.get_attribute("aria-expanded") == "true"
    assert "January" in months.first.inner_text()
    assert (
        months.first.get_by_role("link", name="Minutes").get_attribute("href") == "https://example.com/minutes/2025-1"
    )
    year.click()
    page.locator("#checkouts-2025").wait_for(state="hidden")
    shown = page.locator("#pets li:visible")
    assert shown.count() == 12
    assert "Dog" in page.locator("#pets").inner_text().split("Show all")[0]  # dogs mixed in, not after all the cats
    page.get_by_role("button", name="Show all 20 pets").click()
    page.locator("#pets li").nth(19).wait_for(state="visible")
    assert page.locator("#pets li:visible").count() == 20


def test_permits_location_refused_explains_and_offers_the_map(open_page):
    page = open_page("permits/", viewport=PHONE, wait=PLACES)  # no location permission granted
    page.get_by_role("button", name="Near me").click()
    alert = page.get_by_role("alert")
    alert.wait_for()
    assert "Location sharing is off" in alert.inner_text() and "Settings" in alert.inner_text()
    page.get_by_role("button", name="Use the middle of the map instead").click()
    assert "closest to the middle of the map" in page.locator("#results-summary").inner_text()


def test_permits_map_shows_at_once_and_says_records_are_loading(browser, site_url):
    ctx = browser.new_context(viewport=DESKTOP)
    page = ctx.new_page()
    page.route(lambda url: not url.startswith(site_url.split("/whats-up")[0]), lambda r: r.abort())
    held = []
    page.route("**/recent.json", lambda r: held.append(r))  # the records are slow to come
    page.goto(site_url + "permits/")
    page.wait_for_selector(".permits-map[data-zoom]")  # the map is up without them
    summary = page.locator("#results-summary")
    assert "Loading permits and applications" in summary.inner_text()
    for r in held:
        r.continue_()
    page.wait_for_function("!document.querySelector('#results-summary').innerText.includes('Loading')")
    page.locator(PLACES).first.wait_for()
    ctx.close()


def test_permits_map_double_tap_zooms_one_level(browser, site_url):
    # a phone (touch) context; iPhones don't send dblclick for taps, so the page watches taps itself
    ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    page.route(lambda url: not url.startswith(site_url.split("/whats-up")[0]), lambda r: r.abort())
    page.goto(site_url + "permits/")
    page.wait_for_selector(".permits-map[data-zoom]", state="attached")  # phones open on the list
    page.get_by_role("button", name="Map", exact=True).click()
    box = page.locator(".permits-map").bounding_box()
    x, y = box["x"] + 40, box["y"] + box["height"] / 2
    start = int(page.locator(".permits-map").get_attribute("data-zoom"))
    page.touchscreen.tap(x, y)
    page.wait_for_timeout(80)
    page.touchscreen.tap(x, y)
    page.wait_for_function(f"document.querySelector('.permits-map').dataset.zoom != '{start}'")
    page.wait_for_timeout(600)  # a second (browser) zoom would land by now
    assert int(page.locator(".permits-map").get_attribute("data-zoom")) == start + 1
    ctx.close()


# Where a place sits on screen (the map exposes its Leaflet map for this; places come from the page's data)
WHERE = """(k) => { const el = document.querySelector('.permits-map'), m = el.leaflet;
    const d = Alpine.$data(el.closest('[x-data]')), s = d.matches.find(x => k ? x.k === k : x.lat != null);
    const p = m.latLngToContainerPoint([s.lat, s.lon]), b = el.getBoundingClientRect();
    return {k: s.k, x: b.left + p.x, y: b.top + p.y}; }"""


def test_permits_on_a_phone_a_map_tap_opens_the_place(browser, site_url):
    ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    page.route(lambda url: not url.startswith(site_url.split("/whats-up")[0]), lambda r: r.abort())
    page.goto(site_url + "permits/")
    page.wait_for_selector(PLACES)
    assert page.locator(".permits-map").is_hidden()  # the list first; the page scrolls like any other
    page.get_by_role("button", name="Map", exact=True).click()
    page.wait_for_timeout(300)  # the map measures itself once it shows
    place = page.evaluate(WHERE, None)
    page.touchscreen.tap(place["x"] + 14, place["y"] + 10)  # beside the dot, not on it: a fingertip's reach
    page.wait_for_selector("dialog[open]")
    assert page.locator("#dialog-title").inner_text().strip()
    assert page.locator("dialog ol li").count() >= 1  # the place's history
    page.get_by_role("button", name="Close").click()
    assert page.locator("dialog[open]").count() == 0 and page.locator(".permits-map").is_visible()
    ctx.close()


def test_permits_swiping_the_pop_up_never_moves_the_map(browser, site_url):
    ctx = browser.new_context(viewport=PHONE, has_touch=True, is_mobile=True)
    page = ctx.new_page()
    cdp = ctx.new_cdp_session(page)
    page.route(lambda url: not url.startswith(site_url.split("/whats-up")[0]), lambda r: r.abort())
    page.goto(site_url + "permits/")
    page.wait_for_selector(PLACES)
    page.get_by_role("button", name="Map", exact=True).click()
    page.wait_for_timeout(300)
    place = page.evaluate(WHERE, None)
    page.touchscreen.tap(place["x"], place["y"])
    page.wait_for_selector("dialog[open]")
    center = (
        "(() => { const c = document.querySelector('.permits-map').leaflet.getCenter(); return [c.lat, c.lng]; })()"
    )
    before = page.evaluate(center)

    def swipe(y0, y1):
        cdp.send("Input.dispatchTouchEvent", {"type": "touchStart", "touchPoints": [{"x": 195, "y": y0}]})
        for i in range(1, 9):
            point = {"x": 195, "y": y0 + (y1 - y0) * i / 8}
            cdp.send("Input.dispatchTouchEvent", {"type": "touchMove", "touchPoints": [point]})
            page.wait_for_timeout(16)
        cdp.send("Input.dispatchTouchEvent", {"type": "touchEnd", "touchPoints": []})
        page.wait_for_timeout(200)

    for y0, y1 in [(700, 300), (700, 300), (300, 780), (300, 780)]:  # past the pop-up's ends, both ways
        swipe(y0, y1)
    assert page.evaluate(center) == before and page.evaluate("scrollY") == 0
    page.get_by_role("button", name="Close").click()
    # the dialog's close event arrives a moment after the click; the map is draggable again once it has
    page.wait_for_function("document.querySelector('.permits-map').leaflet.dragging.enabled()", timeout=2000)
    ctx.close()


def test_permits_a_click_on_large_screens_shows_the_history_beside_the_map(open_page):
    page = open_page("permits/", wait=PLACES)
    place = page.evaluate(WHERE, None)
    page.mouse.click(place["x"] + 6, place["y"])
    page.wait_for_selector("#place-name")
    assert page.locator("dialog[open]").count() == 0


def test_permits_back_to_results_puts_the_map_back(open_page):
    page = open_page("permits/", wait=PLACES)
    view = (
        "const m = document.querySelector('.permits-map').leaflet, c = m.getCenter();"
        " const v = [+c.lat.toFixed(4), +c.lng.toFixed(4), m.getZoom()];"
    )
    before = page.evaluate(f"(() => {{ {view} return v; }})()")
    page.locator(PLACES).first.click()  # from the list: the map flies to the place
    page.wait_for_selector("#place-name")
    page.wait_for_function(f"b => {{ {view} return JSON.stringify(v) !== JSON.stringify(b); }}", arg=before)
    page.get_by_role("button", name="Back to results").click()
    page.wait_for_function(f"b => {{ {view} return JSON.stringify(v) === JSON.stringify(b); }}", arg=before)
    assert page.errors == []


def test_trends_dollars_switch_between_reported_and_adjusted(open_page):
    page = open_page("permits/trends/")
    # the 2015 permit: $12,000 then is more in today's dollars
    row_2015 = page.locator("tbody tr", has=page.locator("th", has_text="2015"))
    reported = row_2015.locator("td").nth(4).inner_text()
    assert reported == "$12K"
    adjusted_button = page.get_by_role("button", name="Adjusted for inflation")
    assert adjusted_button.get_attribute("aria-pressed") == "false"
    adjusted_button.click()
    page.wait_for_timeout(100)
    assert adjusted_button.get_attribute("aria-pressed") == "true"
    assert page.get_by_text("dollars, using the Consumer Price Index").is_visible()
    assert row_2015.locator("td").nth(4).inner_text() not in ("", reported)
    # every reported-dollars figure is hidden: the tiles, charts, table and biggest projects switch together
    hidden = page.evaluate(
        "[...document.querySelectorAll('main [x-show=\"!real\"]')].every(el => getComputedStyle(el).display === 'none')"
    )
    assert hidden
    page.reload()
    page.wait_for_timeout(300)
    assert page.get_by_role("button", name="Adjusted for inflation").get_attribute("aria-pressed") == "true"
    assert page.errors == []


def test_trends_biggest_projects_open_their_place_on_the_permits_page(open_page):
    page = open_page("permits/trends/")
    biggest = page.locator("section", has=page.get_by_role("heading", name="The biggest projects since 2015"))
    link = biggest.locator("ol:visible a[href*='#site=']").first
    link.click()
    page.wait_for_selector("#place-name", timeout=10000)
    assert page.locator("#place-name").inner_text() in ("440 Heritage Drive", "12 Old Mill Road")
    assert page.errors == []


def test_news_outlet_picker_takes_any_mix_and_saves_a_default(open_page):
    page = open_page("news/")
    button = page.locator("#outlet-button")
    assert "All outlets" in button.inner_text() and button.get_attribute("aria-expanded") == "false"
    button.click()
    assert button.get_attribute("aria-expanded") == "true"
    outlet = page.locator("#outlet-menu input[type=checkbox]").first
    outlet.check()
    page.wait_for_timeout(100)
    assert "Black Hills Pioneer" in button.inner_text()
    assert page.get_by_role("link", name="Council approves budget").is_visible()
    page.keyboard.press("Escape")
    assert not page.locator("#outlet-menu").is_visible()
    page.reload()
    page.wait_for_timeout(300)
    assert "All outlets" in page.locator("#outlet-button").inner_text()  # a pick isn't kept unless saved

    # saved as the default, it's what the page opens with
    page.locator("#outlet-button").click()
    page.locator("#outlet-menu input[type=checkbox]").first.check()
    page.get_by_role("button", name="Save as my default").click()
    page.get_by_role("button", name="Save as my default").wait_for(state="hidden")
    assert "Your default on this device" in page.locator("#outlet-menu").inner_text()
    page.reload()
    page.wait_for_timeout(300)
    assert "Black Hills Pioneer" in page.locator("#outlet-button").inner_text()

    # cleared, the page opens with everything again
    page.locator("#outlet-button").click()
    page.get_by_role("button", name="Clear my default").click()
    page.get_by_role("button", name="Clear my default").wait_for(state="hidden")
    page.reload()
    page.wait_for_timeout(300)
    assert "All outlets" in page.locator("#outlet-button").inner_text()
    assert page.errors == []


def test_roadkill_gallery_steps_through_photos(open_page):
    page = open_page("outdoors/", wait="#roadkill img")
    card = page.locator("#roadkill")
    assert "20 in the past 30 days" in " ".join(card.inner_text().split())
    assert "5 white-tailed deer" in card.inner_text() and "5 small animals" in card.inner_text()
    assert card.locator("svg use").count() >= 4  # an animal shape beside each species
    page.locator("#roadkill li a").nth(1).click()
    dialog = page.locator("#roadkill dialog")
    dialog.get_by_text("2 of 20").wait_for()
    assert "Small animal, female" in dialog.inner_text() and "Exit 10" in dialog.inner_text()
    page.keyboard.press("ArrowRight")
    dialog.get_by_text("3 of 20").wait_for()
    dialog.get_by_role("button", name="Previous photo").click()
    dialog.get_by_role("button", name="Previous photo").click()
    dialog.get_by_text("1 of 20").wait_for()
    page.keyboard.press("ArrowLeft")  # wraps around
    dialog.get_by_text("20 of 20").wait_for()
    page.keyboard.press("Escape")
    assert not dialog.evaluate("d => d.open")
    assert page.errors == []


def test_home_roadkill_teaser(open_page):
    page = open_page("", wait="#roadkill")
    teaser = page.locator("#roadkill")
    assert "20 animals scraped off Black Hills roads in the past 30 days" in " ".join(teaser.inner_text().split())
    assert teaser.locator("img").count() == 4
    assert teaser.locator("a[href$='outdoors/#roadkill']").count() >= 1


def test_a_shared_link_to_a_place_moves_the_map_there(open_page):
    page = open_page("permits/#site=2312%20PLATINUM%20DR", wait=".permits-map[data-zoom]")
    page.locator("#place-name", has_text="2312 Platinum Drive").wait_for()
    page.wait_for_selector(".permits-map[data-zoom='16']")
    assert "The spot on the map is approximate." in page.locator("section[aria-labelledby=place-name]").inner_text()
    assert page.errors == []

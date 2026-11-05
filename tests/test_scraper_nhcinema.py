"""Northern Hills Cinema: what's playing (with showtimes) and coming soon, and how the site shows them."""

from __future__ import annotations

import json
from datetime import date

from bs4 import BeautifulSoup

from scrapers.sources import nhcinema
from sitegen.data import Site
from sitegen.pages import movies_context, runtime_label

TODAY = date(2026, 11, 4)

NOW_PLAYING = """
<div class="movie-list np">
  <div class="small-12 columns"><h2 class="title"><a href="https://nhcinema.com/view/clayface">Clayface</a></h2></div>
  <div class="movie-thumb">
    <a href="https://nhcinema.com/view/clayface"><img src="/images/movies/3721/clayface__standard.jpg" /></a>
    <div class="notify-label"><span class="secondary label">Ends Thursday 11/5</span></div>
  </div>
  <div class="rating-graphic"><img src="https://nhcinema.com/images/rated_r.png" alt="PG13" /></div>
  <div class="text info-line">108 Minutes | No Passes <hr></div>
  <div class="full-showtimes"><table>
    <tr id="first"><td class="heavier">Thu<br>11/5</td><td class="times">3:30-Luxury |  6:15</td></tr>
  </table></div>
</div>
<div class="movie-list np">
  <div><h2 class="title"><a href="https://nhcinema.com/view/drummer-boy">Drummer Boy</a></h2></div>
  <div class="movie-thumb"><img src="https://nhcinema.com/images/movies/3723/drummer__standard.jpg" />
    <div class="notify-label"><span class="secondary label"> </span></div></div>
  <div class="rating-graphic"><img src="https://nhcinema.com/images/rated_pg13.png" /></div>
  <div class="text info-line">129 Minutes</div>
  <div class="full-showtimes"><table>
    <tr><td class="heavier">Sat<br>11/7</td><td class="times">11:45 |  12:00-Luxury |  9:30</td></tr>
    <tr><td class="heavier">Fri<br>11/6</td><td class="times">3:00</td></tr>
  </table></div>
</div>
"""

COMING_SOON = """
<div class="small-12 columns sm-full movie-list">
  <a name="How to Rob a Bank"></a>
  <div class="small-12 columns"><h2 class="title">How to Rob a Bank</h2></div>
  <div class="movie-thumb"><img src="https://nhcinema.com/images/movies/3733/rob__standard.jpg" />
    <div class="hide-for-small-only"><iframe src="https://www.youtube.com/embed/B9XOzCUvFB8?feature=oembed"></iframe></div>
  </div>
  <div class="small-7 columns">
    <div class="rating-graphic"><img src="https://nhcinema.com/images/rated_r.png" /></div>
    <div class="hide-for-small-only"><h3>Synopsis</h3><p>A crew of bank robbers broadcasts their heists.</p></div>
  </div>
</div>
"""

DETAIL = """
<div class="movie-info">
  <div class="heading">MPAA RATING</div>(R)for strong bloody violence
  <div class="heading">GENRE</div>Horror
  <div class="heading">STARRING</div>Tom Rhys Harries, Naomi Ackie
  <div class="heading">DIRECTOR(S)</div>James Watkins
  <div class="heading">WRITER(S)</div>N/A
</div>
<iframe src="https://www.youtube.com/embed/OGO4Mqvo3jI?feature=oembed"></iframe>
<h3>Synopsis</h3><p>One man&rsquo;s descent.</p>
"""


def _soup(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "html.parser")


def test_times_without_am_pm():
    assert nhcinema.parse_times("3:30-Luxury |  6:15") == [
        {"time": "15:30", "luxury": True},
        {"time": "18:15", "luxury": False},
    ]
    # mornings start at 10 or 11; noon is noon; the rest are afternoons and evenings
    assert [t["time"] for t in nhcinema.parse_times("10:45 | 11:30 | 12:15 | 1:00 | 9:30")] == [
        "10:45", "11:30", "12:15", "13:00", "21:30",
    ]  # fmt: skip


def test_dates_take_the_nearest_year():
    assert nhcinema.nearest(11, 5, TODAY) == date(2026, 11, 5)
    assert nhcinema.nearest(1, 2, date(2026, 12, 30)) == date(2027, 1, 2)
    assert nhcinema.nearest(12, 31, date(2027, 1, 1)) == date(2026, 12, 31)


def test_now_playing():
    clay, drummer = nhcinema.parse_now_playing(_soup(NOW_PLAYING), TODAY)
    assert clay["title"] == "Clayface" and clay["url"] == "https://nhcinema.com/view/clayface"
    assert clay["status"] == "now" and clay["rating"] == "R" and clay["runtime"] == 108 and clay["no_passes"]
    assert clay["image_url"].endswith("clayface__standard.jpg")
    assert clay["note"] == "Ends Thursday 11/5" and clay["ends"] == "2026-11-05"
    assert clay["showtimes"] == [
        {"date": "2026-11-05", "times": [{"time": "15:30", "luxury": True}, {"time": "18:15", "luxury": False}]}
    ]
    assert drummer["rating"] == "PG-13" and "note" not in drummer and not drummer["no_passes"]
    # days in order, whatever order the table has them in
    assert [d["date"] for d in drummer["showtimes"]] == ["2026-11-06", "2026-11-07"]
    assert [t["time"] for t in drummer["showtimes"][1]["times"]] == ["11:45", "12:00", "21:30"]


def test_coming_soon():
    (rob,) = nhcinema.parse_coming_soon(_soup(COMING_SOON))
    assert rob["title"] == "How to Rob a Bank" and rob["status"] == "soon" and rob["rating"] == "R"
    assert rob["url"] == "https://nhcinema.com/coming-soon#How%20to%20Rob%20a%20Bank"
    assert rob["trailer"] == "B9XOzCUvFB8" and rob["synopsis"].startswith("A crew of bank robbers")


def test_detail_page():
    d = nhcinema.parse_detail(_soup(DETAIL))
    assert d == {
        "genre": "Horror",
        "starring": "Tom Rhys Harries, Naomi Ackie",
        "director": "James Watkins",
        "synopsis": "One man’s descent.",
        "trailer": "OGO4Mqvo3jI",
    }


def test_scrape_puts_both_lists_together(monkeypatch):
    pages = {nhcinema.NOW_URL: NOW_PLAYING, nhcinema.SOON_URL: COMING_SOON}
    monkeypatch.setattr(nhcinema, "fetch_html", lambda url, **kw: _soup(pages.get(url, DETAIL)))
    monkeypatch.setattr(nhcinema, "DELAY", 0)
    monkeypatch.setattr(nhcinema.dates, "today", lambda: TODAY)
    movies = nhcinema.NorthernHillsCinema().scrape()
    assert [(m["title"], m["status"]) for m in movies] == [
        ("Clayface", "now"), ("Drummer Boy", "now"), ("How to Rob a Bank", "soon"),
    ]  # fmt: skip
    assert movies[0]["genre"] == "Horror" and movies[0]["slug"] == "clayface"
    assert movies[2]["record_type"] == "movie"


def test_runtime_label():
    assert [runtime_label(m) for m in (101, 90, 120, 45, None)] == ["1 hr 41 min", "1 hr 30 min", "2 hr", "45 min", ""]


def test_movies_context(tmp_path):
    now = nhcinema.parse_now_playing(_soup(NOW_PLAYING), TODAY)
    now[0]["genre"] = "Horror"
    soon = nhcinema.parse_coming_soon(_soup(COMING_SOON))
    env = {"slug": "nhcinema", "name": "Northern Hills Cinema", "kind": "movie", "url": "https://nhcinema.com/"}
    (tmp_path / "nhcinema.json").write_text(json.dumps({**env, "records": now + soon}))
    ctx = movies_context(Site(tmp_path), date(2026, 11, 6))
    # Clayface's last show was the 5th: on the 6th it's gone
    assert [m["title"] for m in ctx["now"]] == ["Drummer Boy"]
    assert ctx["days"] == [
        {"date": "2026-11-06", "last": "2026-11-06T15:00", "label": "Fri, Nov 6"},
        {"date": "2026-11-07", "last": "2026-11-07T21:30", "label": "Sat, Nov 7"},
    ]
    drummer = ctx["now"][0]
    assert drummer["info"] == "PG-13 • 2 hr 9 min" and drummer["dates"] == ["2026-11-06", "2026-11-07"]
    assert [t["label"] for t in drummer["days"][1]["times"]] == ["11:45 AM", "12 PM", "9:30 PM"]
    assert drummer["days"][1]["times"][1] == {"label": "12 PM", "at": "2026-11-07T12:00", "luxury": True}
    (rob,) = ctx["soon"]
    assert rob["trailer_url"] == "https://www.youtube.com/watch?v=B9XOzCUvFB8" and rob["info"] == "R"
    # on the 4th, Clayface is still on, with its last day noted
    clay = movies_context(Site(tmp_path), TODAY)["now"][0]
    assert clay["note"] == "Last day Thu, Nov 5" and clay["info"] == "R • 1 hr 48 min • Horror"

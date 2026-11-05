"""
scrapers/sources/nhcinema.py

Northern Hills Cinema, Spearfish's movie theater: what's playing, with a week of
showtimes, and what's coming soon.

  https://nhcinema.com/now-playing   each movie with its showtimes, one row a day
                                     ("Thu<br>11/5" | "3:30 |  6:15-Luxury")
  https://nhcinema.com/view/{slug}   one movie: genre, cast, synopsis, trailer
  https://nhcinema.com/coming-soon   upcoming movies: synopsis and trailer (no dates)

Times carry no AM/PM; the theater's first shows are late morning and its last
start by 10, so 10 and 11 o'clock are morning shows and the rest afternoon and
evening. "-Luxury" marks a show in the luxury-seating auditorium ($2 more).
Dates carry no year; each gets the year that puts it nearest today.

The lists turn over every week; replace=True drops a movie once it's gone.
"""

from __future__ import annotations

import re
import time
from datetime import date
from urllib.parse import quote, urljoin

from bs4 import BeautifulSoup, Tag

from scrapers import dates
from scrapers.base import BaseScraper
from scrapers.utils import fetch_html, make_slug

BASE = "https://nhcinema.com/"
NOW_URL = urljoin(BASE, "now-playing")
SOON_URL = urljoin(BASE, "coming-soon")
DELAY = 1.0  # seconds between detail pages

RATINGS = {"g": "G", "pg": "PG", "pg13": "PG-13", "r": "R", "nc17": "NC-17", "nr": "Not rated"}
_RATING_IMG = re.compile(r"rated_([a-z0-9]+)\.", re.I)
_RUNTIME = re.compile(r"(\d+)\s*Min", re.I)
_DAY = re.compile(r"(\d{1,2})/(\d{1,2})")
_TIME = re.compile(r"(\d{1,2}):(\d{2})\s*(-\s*Luxury)?", re.I)
_NOTE = re.compile(r"^(Starts|Ends|Opens)\b.*?(\d{1,2}/\d{1,2})", re.I)
_YOUTUBE = re.compile(r"youtube\.com/embed/([\w-]{6,})")


def _text(el: Tag | None) -> str:
    return " ".join(el.get_text(" ", strip=True).split()) if el else ""


def nearest(month: int, day: int, today: date) -> date:
    """The month/day nearest *today*: 1/2 seen on Dec 30 is next January."""
    options = []
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            options.append(date(year, month, day))
        except ValueError:
            continue
    return min(options, key=lambda d: abs((d - today).days))


def clock(hour: int, minute: int) -> str:
    """A showtime with no AM/PM, as 24-hour 'HH:MM': 10 and 11 are mornings, the rest afternoons and evenings."""
    if hour < 10:
        hour += 12
    return f"{hour:02d}:{minute:02d}"


def parse_times(text: str) -> list[dict]:
    """'3:30-Luxury |  6:15' → [{'time': '15:30', 'luxury': True}, {'time': '18:15', 'luxury': False}]."""
    return [
        {"time": clock(int(h), int(m)), "luxury": bool(lux)} for h, m, lux in _TIME.findall(text) if 1 <= int(h) <= 12
    ]


def parse_showtimes(block: Tag, today: date) -> list[dict]:
    """A movie's showtimes table, one entry a day: [{'date': '2026-11-05', 'times': [...]}]."""
    days = []
    for row in block.select(".full-showtimes tr"):
        cells = row.find_all("td")
        if len(cells) < 2 or not (m := _DAY.search(_text(cells[0]))):
            continue
        times = parse_times(_text(cells[1]))
        if times:
            days.append({"date": nearest(int(m.group(1)), int(m.group(2)), today).isoformat(), "times": times})
    return sorted(days, key=lambda d: d["date"])


def _rating(block: Tag) -> str:
    img = block.select_one(".rating-graphic img")
    m = _RATING_IMG.search(img.get("src", "")) if img else None
    return RATINGS.get(m.group(1).lower(), m.group(1).upper()) if m else ""


def _poster(block: Tag) -> str:
    img = block.select_one(".movie-thumb img")
    return urljoin(BASE, img["src"].strip()) if img and img.get("src") else ""


def _common(block: Tag) -> dict:
    info = _text(block.select_one(".info-line"))
    runtime = _RUNTIME.search(info)
    return {
        "image_url": _poster(block),
        "rating": _rating(block),
        "runtime": int(runtime.group(1)) if runtime else None,
        "no_passes": "no passes" in info.lower(),
    }


def _note(block: Tag, today: date) -> dict:
    """'Ends Thursday 11/5' / 'Starts Wednesday 11/11' → {'note': …, 'ends' or 'starts': ISO date}."""
    label = _text(block.select_one(".notify-label"))
    m = _NOTE.match(label)
    if not m:
        return {}
    month, day = (int(x) for x in m.group(2).split("/"))
    key = "ends" if m.group(1).lower() == "ends" else "starts"
    return {"note": label, key: nearest(month, day, today).isoformat()}


def parse_now_playing(soup: BeautifulSoup, today: date) -> list[dict]:
    movies = []
    for block in soup.select(".movie-list"):
        link = block.select_one("h2.title a")
        title = _text(link)
        if not title:
            continue
        movies.append(
            {
                "title": title,
                "url": urljoin(BASE, link.get("href", "")),
                "status": "now",
                **_common(block),
                **_note(block, today),
                "showtimes": parse_showtimes(block, today),
            }
        )
    return movies


def parse_coming_soon(soup: BeautifulSoup) -> list[dict]:
    movies = []
    for block in soup.select(".movie-list"):
        title = _text(block.select_one("h2.title"))
        if not title:
            continue
        anchor = block.find("a", attrs={"name": True})
        frame = block.find("iframe", src=_YOUTUBE)
        synopsis = block.select_one(".hide-for-small-only p")
        movies.append(
            {
                "title": title,
                "url": f"{SOON_URL}#{quote(anchor['name'] if anchor else title)}",
                "status": "soon",
                **_common(block),
                "trailer": _YOUTUBE.search(frame["src"]).group(1) if frame else "",
                "synopsis": _text(synopsis),
            }
        )
    return movies


_INFO_KEYS = {"GENRE": "genre", "STARRING": "starring", "DIRECTOR(S)": "director"}


def parse_detail(soup: BeautifulSoup) -> dict:
    """Genre, cast, director, synopsis and trailer from a movie's own page."""
    out: dict = {}
    info = soup.select_one(".movie-info")
    if info:
        for head in info.select(".heading"):
            key = _INFO_KEYS.get(_text(head).upper())
            value = head.next_sibling
            if key and isinstance(value, str) and value.strip() and value.strip().upper() != "N/A":
                out[key] = " ".join(value.split())
    if (h := soup.find("h3", string=re.compile("Synopsis", re.I))) and (p := h.find_next("p")):
        out["synopsis"] = _text(p)
    if frame := soup.find("iframe", src=_YOUTUBE):
        out["trailer"] = _YOUTUBE.search(frame["src"]).group(1)
    return out


class NorthernHillsCinema(BaseScraper):
    name = "Northern Hills Cinema"
    slug = "nhcinema"
    kind = "movie"
    url = BASE
    replace = True

    def scrape(self) -> list[dict]:
        today = dates.today()
        movies = parse_now_playing(fetch_html(NOW_URL), today)
        for m in movies:
            time.sleep(DELAY)
            try:
                m.update(parse_detail(fetch_html(m["url"])))
            except Exception as exc:  # noqa: BLE001 — the showtimes matter more than the details
                print(f"[{self.slug}] couldn't read {m['url']}: {exc}")
        playing = {m["title"].lower() for m in movies}
        try:
            movies += [m for m in parse_coming_soon(fetch_html(SOON_URL)) if m["title"].lower() not in playing]
        except Exception as exc:  # noqa: BLE001
            print(f"[{self.slug}] couldn't read coming soon: {exc}")
        for m in movies:
            m.update(slug=make_slug(m["title"]), record_type="movie", source_label="Northern Hills Cinema")
        return movies

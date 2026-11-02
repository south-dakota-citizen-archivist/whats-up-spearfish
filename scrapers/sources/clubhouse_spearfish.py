"""
scrapers/sources/clubhouse_spearfish.py

The Clubhouse of Spearfish — beers on tap, from the "Draft Beers" list on the
venue's own food and drink menu (it stopped using Untappd in 2026).

The menu is an Elementor price list: each draft is an li with
  .elementor-price-list-title        → beer name
  .elementor-price-list-description  → description, then "<br>- Brewery Name"
The page has other price lists (food, premium and domestic beer), so we take
the first list after the "Draft Beers" heading.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from scrapers.utils import fetch_html, make_slug

MENU_URL = "https://clubhouseofspearfish.com/food-and-drink/"
VENUE = "The Clubhouse"


def parse_drafts(soup: BeautifulSoup) -> list[dict]:
    heading = soup.find(string=re.compile(r"^\s*Draft Beers\s*$", re.I))
    if not heading:
        return []
    menu = heading.find_next("ul", class_="elementor-price-list")
    if not menu:
        return []

    records = []
    for li in menu.find_all("li"):
        title_el = li.select_one(".elementor-price-list-title")
        name = title_el.get_text(" ", strip=True) if title_el else ""
        if not name:
            continue
        desc_el = li.select_one(".elementor-price-list-description")
        lines = [s.strip() for s in desc_el.stripped_strings] if desc_el else []
        brewery = ""
        if lines and lines[-1].startswith("-"):
            brewery = lines.pop().lstrip("- ").strip()
        if brewery.lower().startswith("the clubhouse"):
            brewery = ""  # the house beer; the venue name already heads the list
        records.append(
            {
                "url": MENU_URL,
                "title": name,
                "slug": make_slug(name),
                "description": " ".join(lines),
                "brewery": brewery,
                "image_url": "",
                "record_type": "beer",
                "source_label": VENUE,
            }
        )
    return records


class ClubhouseSpearfish(BaseScraper):
    name = VENUE
    slug = "clubhouse_spearfish"
    kind = "beer"
    url = MENU_URL
    dedup_key = "slug"
    replace = True

    def scrape(self) -> list[dict]:
        return parse_drafts(fetch_html(MENU_URL))

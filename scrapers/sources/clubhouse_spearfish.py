"""
scrapers/sources/clubhouse_spearfish.py

The Clubhouse of Spearfish, Spearfish SD — beers on tap via Untappd venue menu.
https://untappd.com/v/the-clubhouse-of-spearfish/9898973?menu_id=248990
"""

import re

from scrapers.base import BaseScraper
from scrapers.utils import fetch_html, make_slug

SOURCE_URL = "https://untappd.com/v/the-clubhouse-of-spearfish/9898973?menu_id=248990"
_STATS_RE = re.compile(r"([\d.]+)%\s*ABV(?:\s*•\s*([\d.]+)\s*IBU)?", re.IGNORECASE)


class ClubhouseSpearfish(BaseScraper):
    name = "The Clubhouse"
    slug = "clubhouse_spearfish"
    dedup_key = "slug"
    replace = True

    def scrape(self) -> list[dict]:
        soup = fetch_html(SOURCE_URL)
        records = []

        for li in soup.select("li.menu-item"):
            h5 = li.select_one(".beer-details h5")
            if not h5:
                continue

            a = h5.find("a")
            name_raw = a.get_text(strip=True) if a else h5.get_text(strip=True)
            name = re.sub(r"^\d+\.\s*", "", name_raw).strip()
            if not name:
                continue

            beer_url = ("https://untappd.com" + a["href"]) if a and a.get("href") else SOURCE_URL

            em = h5.find("em")
            category = em.get_text(strip=True) if em else ""

            h6_span = li.select_one(".beer-details h6 span")
            stats = h6_span.get_text(" ", strip=True) if h6_span else ""
            m = _STATS_RE.search(stats)
            abv = (m.group(1) + "%") if m else ""
            ibu = m.group(2) if m and m.group(2) else ""

            brewery_a = li.select_one("[data-href=':brewery']")
            brewery = brewery_a.get_text(strip=True) if brewery_a else ""

            rating_el = li.select_one(".num")
            rating = rating_el.get_text(strip=True).strip("()") if rating_el else ""

            img = li.select_one(".beer-label img")
            image_url = img["src"] if img and img.get("src") else ""

            records.append({
                "url": beer_url,
                "title": name,
                "slug": make_slug(name),
                "category": category,
                "abv": abv,
                "ibu": ibu,
                "brewery": brewery,
                "rating": rating,
                "image_url": image_url,
                "record_type": "beer",
                "source_label": "The Clubhouse of Spearfish",
            })

        return records

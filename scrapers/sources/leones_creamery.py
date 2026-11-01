"""
scrapers/sources/leones_creamery.py

Leone's Creamery, Spearfish SD — current flavor board including photos.
https://leonescreamery.com/flavors

The board rotates regularly; replace=True ensures removed flavors drop off
immediately rather than persisting from a previous scrape.
"""

from urllib.parse import urljoin

from scrapers.base import BaseScraper
from scrapers.utils import fetch_html, make_slug

SOURCE_URL = "https://leonescreamery.com/flavors"


class LeonesCreamery(BaseScraper):
    name = "Leone's Creamery"
    slug = "leones_creamery"
    kind = "flavor"
    url = "https://leonescreamery.com/flavors"
    dedup_key = "url"
    replace = True

    def scrape(self) -> list[dict]:
        soup = fetch_html(SOURCE_URL)
        records, seen = [], set()
        for card in soup.select("a.spearfish-flavors_features-list_item"):
            href = card.get("href", "")
            if not href or href in seen:
                continue
            seen.add(href)
            img = card.find("img")
            heading = card.find(["h3", "h4"])
            name = heading.get_text(strip=True) if heading else (img.get("alt", "") if img else "")
            if not name:
                continue
            records.append(
                {
                    "url": urljoin(SOURCE_URL, href),
                    "image_url": img.get("src", "").strip() if img else "",
                    "title": name,
                    "slug": make_slug(name),
                    "record_type": "flavor",
                    "source_label": "Leone's Creamery",
                }
            )
        return records

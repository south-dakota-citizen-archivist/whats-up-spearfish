"""
scrapers/sources/leones_creamery.py

Leone's Creamery, Spearfish SD — current flavor board including photos.
https://leonescreamery.com/flavors

The board rotates regularly; replace=True ensures removed flavors drop off
immediately rather than persisting from a previous scrape.
"""

from scrapers.base import BaseScraper
from scrapers.utils import fetch_html, make_slug

SOURCE_URL = "https://leonescreamery.com/flavors"


class LeonesCreamery(BaseScraper):
    name = "Leone's Creamery"
    slug = "leones_creamery"
    dedup_key = "image_url"
    replace = True

    def scrape(self) -> list[dict]:
        soup = fetch_html(SOURCE_URL)
        records = []

        for card in soup.select(".flavor-card"):
            img = card.find("img")
            if not img:
                continue

            name = card.select_one(".flavor-title")
            name = name.get_text(strip=True) if name else img.get("alt", "").split(".")[0].strip()
            description = img.get("alt", "").strip()
            image_url = img.get("src", "").strip()

            records.append(
                {
                    "url": SOURCE_URL,
                    "image_url": image_url,
                    "title": name,
                    "slug": make_slug(name),
                    "description": description,
                    "record_type": "flavor",
                    "source_label": "Leone's Creamery",
                }
            )

        return records

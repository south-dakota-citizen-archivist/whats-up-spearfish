"""
scrapers/sources/spearfish_brewing.py

Spearfish Brewing Company — current beers list.
https://www.spearfishbrewing.com/beers/

WordPress/Beaver Builder page with a .beer-list > .beer-item structure.
Each item has a real name in <h2>, a description paragraph (ABV embedded),
and a linked photo.
"""

import re
from datetime import date

from scrapers.base import BaseScraper
from scrapers.utils import fetch_html, make_slug

SOURCE_URL = "https://www.spearfishbrewing.com/beers/"
_ABV_RE = re.compile(r"ABV\s*([\d.]+)\s*%", re.IGNORECASE)


class SpearfishBrewing(BaseScraper):
    name = "Spearfish Brewing Company"
    slug = "spearfish_brewing"
    dedup_key = "image_url"

    def scrape(self) -> list[dict]:
        soup = fetch_html(SOURCE_URL)
        today = date.today().isoformat()
        records = []

        for item in soup.select(".beer-item"):
            h2 = item.find("h2")
            if not h2:
                continue
            name = h2.get_text(strip=True)

            # Description: all text in the item except the h2
            h2.extract()
            description = item.get_text(" ", strip=True)

            abv_match = _ABV_RE.search(description)
            abv = abv_match.group(1) + "%" if abv_match else ""

            img = item.find("img")
            image_url = img.get("src", "").strip() if img else ""

            records.append({
                "url": SOURCE_URL,
                "image_url": image_url,
                "title": name,
                "slug": make_slug(name),
                "description": description,
                "abv": abv,
                "first_seen": today,
                "last_seen": today,
                "record_type": "beer",
                "source_label": "Spearfish Brewing Company",
            })

        return records

    def run(self) -> list[dict]:
        """Track first_seen / last_seen across runs."""
        today = date.today().isoformat()
        existing = self.load_existing()
        fresh = self.scrape()

        existing_by_key = {r[self.dedup_key]: r for r in existing if r.get(self.dedup_key)}
        fresh_keys = {r[self.dedup_key] for r in fresh if r.get(self.dedup_key)}

        new_records = []
        for record in fresh:
            key = record.get(self.dedup_key)
            if key in existing_by_key:
                existing_by_key[key]["last_seen"] = today
            else:
                new_records.append(record)

        merged = list(existing_by_key.values()) + new_records
        self.save(merged)
        print(
            f"[{self.name}] {len(new_records)} new / {len(existing_by_key)} existing "
            f"({len(fresh_keys)} on tap today) → {len(merged)} total saved to {self.data_file.name}"
        )
        return new_records

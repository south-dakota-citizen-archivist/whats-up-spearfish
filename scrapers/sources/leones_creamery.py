"""
scrapers/sources/leones_creamery.py

Leone's Creamery, Spearfish SD — current flavor board including photos.
https://leonescreamery.com/flavors

The board rotates regularly, so each flavor is stored with a first_seen /
last_seen date. Dedup key is the image URL (unique per flavor photo); if a
flavor returns with a new photo it gets a new record.
"""

from datetime import date

from scrapers.base import BaseScraper
from scrapers.utils import fetch_html, make_slug

SOURCE_URL = "https://leonescreamery.com/flavors"


class LeonesCreamery(BaseScraper):
    name = "Leone's Creamery"
    slug = "leones_creamery"
    dedup_key = "image_url"

    def scrape(self) -> list[dict]:
        soup = fetch_html(SOURCE_URL)
        today = date.today().isoformat()
        records = []

        for card in soup.select(".flavor-card"):
            img = card.find("img")
            if not img:
                continue

            name = card.select_one(".flavor-title")
            name = name.get_text(strip=True) if name else img.get("alt", "").split(".")[0].strip()
            description = img.get("alt", "").strip()
            image_url = img.get("src", "").strip()

            records.append({
                "url": SOURCE_URL,
                "image_url": image_url,
                "title": name,
                "slug": make_slug(name),
                "description": description,
                "first_seen": today,
                "last_seen": today,
                "record_type": "flavor",
                "source_label": "Leone's Creamery",
            })

        return records

    def run(self) -> list[dict]:
        """
        Override run() to also update last_seen on existing records that are
        still on the board, so we can track how long each flavor has been available.
        """
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
            f"({len(fresh_keys)} on board today) → {len(merged)} total saved to {self.data_file.name}"
        )
        return new_records

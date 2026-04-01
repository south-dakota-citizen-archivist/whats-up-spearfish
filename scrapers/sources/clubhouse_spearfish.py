"""
scrapers/sources/clubhouse_spearfish.py

The Clubhouse of Spearfish, Spearfish SD — beers on tap via Untappd venue menu.
https://untappd.com/v/the-clubhouse-of-spearfish/9898973?menu_id=248990
"""

import re
from datetime import date

from scrapers.base import BaseScraper
from scrapers.utils import fetch_html, make_slug

SOURCE_URL = "https://untappd.com/v/the-clubhouse-of-spearfish/9898973?menu_id=248990"
_STATS_RE = re.compile(r"([\d.]+)%\s*ABV(?:\s*•\s*([\d.]+)\s*IBU)?", re.IGNORECASE)


class ClubhouseSpearfish(BaseScraper):
    name = "The Clubhouse"
    slug = "clubhouse_spearfish"
    dedup_key = "slug"

    def scrape(self) -> list[dict]:
        soup = fetch_html(SOURCE_URL)
        today = date.today().isoformat()
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
                "first_seen": today,
                "last_seen": today,
                "record_type": "beer",
                "source_label": "The Clubhouse of Spearfish",
            })

        return records

    def run(self) -> list[dict]:
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

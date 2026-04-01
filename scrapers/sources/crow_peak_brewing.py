"""
scrapers/sources/crow_peak_brewing.py

Crow Peak Brewing Company, Spearfish SD — beers on tap.
https://crowpeakbrewing.com/

WordPress / WPBakery page. The tap list uses `.vc_info_list` items with
an h2 for the beer name and a <p> for ABV / IBU. Descriptions for
year-round beers are fetched from the /beers/ page and merged by slug.
"""

import re
from datetime import date

from scrapers.base import BaseScraper
from scrapers.utils import fetch_html, make_slug

SOURCE_URL = "https://crowpeakbrewing.com/"
BEERS_URL = "https://crowpeakbrewing.com/beers/"
_ABV_TAP_RE = re.compile(r"ABV\s*([\d.]+)", re.IGNORECASE)
_IBU_RE = re.compile(r"IBU\s*([\d.]+)", re.IGNORECASE)
_ABV_BEERS_RE = re.compile(r"([\d.]+%\s*ABV)", re.IGNORECASE)


def _fetch_descriptions() -> dict[str, str]:
    """Return slug → description from the /beers/ year-round page."""
    try:
        soup = fetch_html(BEERS_URL)
    except Exception:
        return {}
    desc_map = {}
    for el in soup.find_all("p"):
        text = el.get_text(strip=True)
        m = _ABV_BEERS_RE.search(text)
        if not m:
            continue
        name = text[:m.start()].strip()
        description = text[m.end():].strip()
        if name and description:
            desc_map[make_slug(name)] = description
    return desc_map


class CrowPeakBrewing(BaseScraper):
    name = "Crow Peak Brewing"
    slug = "crow_peak_brewing"
    dedup_key = "slug"

    def scrape(self) -> list[dict]:
        soup = fetch_html(SOURCE_URL)
        today = date.today().isoformat()
        descriptions = _fetch_descriptions()
        records = []

        for item in soup.select(".vc_info_list"):
            h2 = item.find("h2")
            p = item.find("p")
            if not h2:
                continue

            name = h2.get_text(strip=True)
            stats = p.get_text(strip=True) if p else ""

            abv_m = _ABV_TAP_RE.search(stats)
            ibu_m = _IBU_RE.search(stats)

            # Non-beer items (food vendors, CTAs) have no ABV — skip them
            if not abv_m:
                continue

            img = item.select_one(".info-list-img img")
            image_url = img["src"] if img and img.get("src") else ""
            slug = make_slug(name)

            records.append({
                "url": SOURCE_URL,
                "title": name,
                "slug": slug,
                "abv": abv_m.group(1) + "%" if abv_m else "",
                "ibu": ibu_m.group(1) if ibu_m else "",
                "image_url": image_url,
                "description": descriptions.get(slug, ""),
                "first_seen": today,
                "last_seen": today,
                "record_type": "beer",
                "source_label": "Crow Peak Brewing",
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

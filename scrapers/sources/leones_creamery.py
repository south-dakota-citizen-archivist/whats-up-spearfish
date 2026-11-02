"""
scrapers/sources/leones_creamery.py

Leone's Creamery, Spearfish SD — current flavor board including photos,
plus each flavor's description, gluten-free status and allergens from its
detail page (e.g. /flavor-detail/blueberry-goats-cheese).
https://leonescreamery.com/flavors

The board rotates regularly; replace=True ensures removed flavors drop off
immediately rather than persisting from a previous scrape.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from scrapers.utils import fetch_html, make_slug

SOURCE_URL = "https://leonescreamery.com/flavors"


def parse_detail(soup: BeautifulSoup) -> dict:
    """Description, gluten-free and allergens from a flavor detail page."""
    out: dict = {}
    desc = []
    for p in soup.select("p.text-size-medium"):
        text = p.get_text(" ", strip=True)
        if m := re.match(r"gluten[- ]free:\s*(.+)", text, re.I):
            out["gluten_free"] = m.group(1).strip().lower().startswith("y")
        elif m := re.match(r"contains:\s*(.+)", text, re.I):
            out["contains"] = [x.strip().capitalize() for x in re.split(r",|\band\b", m.group(1)) if x.strip()]
        elif text:
            desc.append(text)
    out["description"] = " ".join(desc)
    return out


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
        for r in records:
            try:
                r.update(parse_detail(fetch_html(r["url"])))
            except Exception as exc:  # noqa: BLE001
                print(f"[{self.slug}] couldn't read {r['url']}: {exc}")
        return records

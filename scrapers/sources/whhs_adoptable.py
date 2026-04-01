"""
scrapers/sources/whhs_adoptable.py

Western Hills Humane Society — adoptable dogs and cats.
https://www.westernhillshumanesociety.com/cats
https://www.westernhillshumanesociety.com/dogs

Squarespace site — pet data is embedded as JSON in a
data-current-context attribute on the UserItemsListSimple <ul>.
"""

from __future__ import annotations

import html
import json
import re

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

BASE_URL = "https://www.westernhillshumanesociety.com"
_TAG_RE = re.compile(r"<[^>]+>")


def _fetch_pets(url: str, species: str) -> list[dict]:
    resp = requests.get(url, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    ul = soup.find("ul", {"data-controller": "UserItemsListSimple"})
    if not ul:
        return []

    ctx = json.loads(ul["data-current-context"])
    records = []
    for item in ctx.get("userItems", []):
        title = item.get("title", "").strip()
        if not title:
            continue

        description_html = item.get("description", "")
        # Convert block-level tags to newlines before stripping
        description_html = re.sub(r"<br\s*/?>|</(p|div|li|h[1-6])>", "\n", description_html, flags=re.IGNORECASE)
        description = _TAG_RE.sub("", description_html)
        description = html.unescape(description)
        # Collapse runs of spaces (but preserve newlines)
        description = re.sub(r"[^\S\n]+", " ", description)
        description = re.sub(r"\n{3,}", "\n\n", description).strip()

        image_url = ""
        image = item.get("image") or {}
        if image.get("assetUrl"):
            image_url = image["assetUrl"] + "?format=500w"

        image_alt = item.get("imageAltText", "") or title

        records.append({
            "url": url,
            "title": title,
            "slug": make_slug(f"{species}-{title}"),
            "species": species,
            "description": description,
            "image_url": image_url,
            "image_alt": image_alt,
            "record_type": "adoptable",
            "source_label": "Western Hills Humane Society",
        })

    return records


class WHHSAdoptable(BaseScraper):
    name = "Western Hills Humane Society"
    slug = "whhs_adoptable"
    dedup_key = "slug"

    def scrape(self) -> list[dict]:
        records = []
        records.extend(_fetch_pets(f"{BASE_URL}/cats", "cat"))
        records.extend(_fetch_pets(f"{BASE_URL}/dogs", "dog"))
        return records

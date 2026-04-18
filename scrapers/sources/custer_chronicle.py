"""
scrapers/sources/custer_chronicle.py

Custer County Chronicle / Hill City Prevailer — news articles.
Both papers share custercountychronicle.com; term/8 is the "News" tag.
"""

from __future__ import annotations

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

BASE_URL = "https://custercountychronicle.com"
LISTING_URL = f"{BASE_URL}/taxonomy/term/8"
MAX_PAGES = 5

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _get(url: str, params: dict | None = None) -> BeautifulSoup:
    r = requests.get(url, headers=_HEADERS, params=params, timeout=20)
    r.raise_for_status()
    return BeautifulSoup(r.text, "html.parser")


def _parse_page(soup: BeautifulSoup) -> list[dict]:
    records = []
    for node in soup.select("div.node-article"):
        a = node.select_one("h2.article-title a")
        if not a:
            continue

        title = a.get_text(strip=True)
        href = a.get("href", "")
        if not title or not href:
            continue
        url = BASE_URL + href if href.startswith("/") else href

        # ISO datetime lives in the content attribute of the dc:date span
        published = ""
        dt_span = node.select_one("span[property~='dc:date']")
        if dt_span and dt_span.get("content"):
            try:
                published = dateutil_parser.parse(dt_span["content"]).date().isoformat()
            except (ValueError, TypeError):
                pass

        # First paragraph of the excerpt
        description = ""
        body = node.select_one(".field-name-body .field-item")
        if body:
            p = body.find("p")
            if p:
                description = p.get_text(" ", strip=True)

        records.append(
            {
                "url": url,
                "title": title,
                "slug": make_slug(f"custer-county-chronicle-{title}"),
                "published": published,
                "byline": "",
                "description": description,
                "record_type": "news",
                "source_label": "Custer County Chronicle",
            }
        )
    return records


class CusterCountyChronicle(BaseScraper):
    name = "Custer County Chronicle"
    slug = "custer_county_chronicle"

    def scrape(self) -> list[dict]:
        records = []
        for page in range(MAX_PAGES):
            params = {"page": page} if page > 0 else None
            soup = _get(LISTING_URL, params=params)
            page_records = _parse_page(soup)
            if not page_records:
                break
            records.extend(page_records)
            # Stop early if pagination link for next page is absent
            if not soup.select_one("li.pager-next a"):
                break
        print(f"  [{self.name}] {len(records)} articles fetched")
        return records

"""
scrapers/sources/kota.py

KOTA Territory News — local news from the Arc Publishing-based site.
No RSS/API available; extracts deduplicated article links from the /news/ page.
"""

from __future__ import annotations

import re
from collections import defaultdict

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

BASE_URL = "https://www.kotatv.com"
NEWS_URL = f"{BASE_URL}/news/"

_DATE_RE = re.compile(r"/(\d{4}/\d{2}/\d{2})/")
_SKIP_LABELS = {
    "",
    "News",
    "Local",
    "Community",
    "Crime",
    "Politics",
    "Sports",
    "Weather",
    "Nation World",
    "Video",
    "Watch",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class KOTA(BaseScraper):
    name = "KOTA Territory News"
    slug = "kota"

    def scrape(self) -> list[dict]:
        r = requests.get(NEWS_URL, headers=_HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        # Same URL appears multiple times (category label, empty, full title).
        # Collect all text variants per href and pick the longest non-label one.
        by_href: dict[str, list[str]] = defaultdict(list)
        for a in soup.find_all("a", href=_DATE_RE):
            by_href[a["href"]].append(a.get_text(strip=True))

        records = []
        for href, texts in by_href.items():
            title = max(
                (t for t in texts if t not in _SKIP_LABELS),
                key=len,
                default="",
            )
            if not title or len(title) < 15:
                continue

            m = _DATE_RE.search(href)
            published = m.group(1).replace("/", "-") if m else ""
            url = BASE_URL + href if href.startswith("/") else href

            records.append(
                {
                    "url": url,
                    "title": title,
                    "slug": make_slug(f"kota-{title}"),
                    "published": published,
                    "byline": "",
                    "description": "",
                    "record_type": "news",
                    "source_label": "KOTA Territory News",
                }
            )

        records.sort(key=lambda r: r["published"], reverse=True)
        print(f"  [{self.name}] {len(records)} articles fetched")
        return records

"""
scrapers/sources/sundance_times.py

Sundance Times — local news from sundancetimes.com.
URL pattern: /story/YYYY/MM/DD/category/slug/
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

BASE_URL = "https://www.sundancetimes.com"
_DATE_RE = re.compile(r"/story/(\d{4}/\d{2}/\d{2})/")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class SundanceTimes(BaseScraper):
    name = "Sundance Times"
    slug = "sundance_times"

    def scrape(self) -> list[dict]:
        r = requests.get(BASE_URL + "/", headers=_HEADERS, timeout=20)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        seen = set()
        records = []
        for a in soup.find_all("a", href=_DATE_RE):
            url = a["href"]
            if not url.startswith("http"):
                url = BASE_URL + url
            if url in seen:
                continue
            seen.add(url)

            h3 = a.find("h3")
            if not h3:
                continue
            title = h3.get_text(strip=True)
            if not title:
                continue

            m = _DATE_RE.search(a["href"])
            published = m.group(1).replace("/", "-") if m else ""

            byline = ""
            p = a.find("p")
            if p:
                span = p.find("span")
                if span:
                    byline = span.get_text(strip=True)

            records.append(
                {
                    "url": url,
                    "title": title,
                    "slug": make_slug(f"sundance-times-{title}"),
                    "published": published,
                    "byline": byline,
                    "description": "",
                    "record_type": "news",
                    "source_label": "Sundance Times",
                }
            )

        print(f"  [{self.name}] {len(records)} articles fetched")
        return records

"""
scrapers/sources/spearfish_library.py

Grace Balloch Memorial Library — recently added books via Koha coverflow API.

Each report ID corresponds to a collection/category in the ILS.
Books are fetched as HTML fragments and parsed for title, cover image,
and OPAC detail URL.

The Koha instance is behind Cloudflare, so we use a playwright stealth
browser to bypass the bot challenge.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from scrapers.base import BaseScraper

BASE_URL = "https://spearfish.blackhills.bywatersolutions.com"
API_URL = f"{BASE_URL}/api/v1/contrib/coverflow/reports/{{report_id}}"

# Report IDs for recently-added collections
REPORT_IDS = [260, 261, 281, 282, 373, 1168, 1171, 1348]

_TRAILING_PUNCT_RE = re.compile(r"[\s/:,]+$")


def _parse_html(html: str, report_id: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for li in soup.select(".koha-coverflow ul li"):
        a = li.find("a", href=True)
        img = li.find("img")
        p = li.find("p")

        if not a or not p:
            continue

        href = a["href"].strip()
        if not href.startswith("http"):
            href = BASE_URL + href

        raw_title = p.get_text(" ", strip=True)
        title = _TRAILING_PUNCT_RE.sub("", raw_title).strip()
        if not title:
            continue

        image_url = img["src"].strip() if img and img.get("src") else ""
        # Skip placeholder "no image" images
        if "NoImage" in image_url:
            image_url = ""
        elif image_url and not image_url.startswith("http"):
            image_url = BASE_URL + image_url

        records.append({
            "url": href,
            "title": title,
            "image_url": image_url,
            "record_type": "library_book",
            "source_label": "Grace Balloch Memorial Library",
        })

    return records


def _fetch_all_books() -> list[dict]:
    records = []
    seen_urls: set[str] = set()

    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        for report_id in REPORT_IDS:
            url = API_URL.format(report_id=report_id)
            try:
                resp = page.goto(url, timeout=20000)
                if resp and resp.status != 200:
                    print(f"[SpearfishLibrary] Warning: report {report_id} returned {resp.status}")
                    continue
                html = page.content()
            except Exception as exc:
                print(f"[SpearfishLibrary] Warning: report {report_id} failed: {exc}")
                continue

            for record in _parse_html(html, report_id):
                if record["url"] not in seen_urls:
                    seen_urls.add(record["url"])
                    records.append(record)

        browser.close()

    return records


class SpearfishLibrary(BaseScraper):
    name = "Grace Balloch Memorial Library"
    slug = "spearfish_library"
    dedup_key = "url"
    replace = True

    def scrape(self) -> list[dict]:
        return _fetch_all_books()

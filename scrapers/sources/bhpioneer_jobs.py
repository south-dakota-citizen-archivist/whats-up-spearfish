"""
scrapers/sources/bhpioneer_jobs.py

Black Hills Pioneer classified job listings.
https://www.bhpioneer.com/classifieds/job/
"""

from __future__ import annotations

import json
import time

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

BASE_URL = "https://www.bhpioneer.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
_LIST_URL = BASE_URL + "/classifieds/job/?c%5B0%5D=job&m=56448c72-888d-11e0-8e12-001cc4c002e0&l=10&o={offset}"


def _parse_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for article in soup.select("article.card.product"):
        track_raw = article.get("data-track-object", "")
        try:
            track = json.loads(track_raw)
        except (json.JSONDecodeError, TypeError):
            track = {}

        title = track.get("title", "").strip()
        rel_url = track.get("url", "")
        url = BASE_URL + rel_url if rel_url.startswith("/") else rel_url

        if not title or not url:
            continue

        time_el = article.select_one("time[datetime]")
        published = time_el["datetime"] if time_el else ""

        category_el = article.select_one(".tnt-section-tag")
        category = category_el.get_text(strip=True) if category_el else ""

        records.append(
            {
                "url": url,
                "title": title,
                "slug": make_slug(title),
                "category": category,
                "published": published,
                "record_type": "job",
                "source_label": "Black Hills Pioneer",
            }
        )
    return records


def _has_next(html: str) -> bool:
    soup = BeautifulSoup(html, "html.parser")
    nxt = soup.select_one("li.next")
    return bool(nxt and not nxt.has_attr("disabled") and "disabled" not in nxt.get("class", []))


class BHPioneerJobs(BaseScraper):
    name = "Black Hills Pioneer"
    slug = "bhpioneer_jobs"
    dedup_key = "url"
    replace = True

    def scrape(self) -> list[dict]:
        records = []
        offset = 0
        while True:
            url = _LIST_URL.format(offset=offset)
            resp = requests.get(url, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            page_records = _parse_page(resp.text)
            records.extend(page_records)
            if not page_records or not _has_next(resp.text):
                break
            offset += 10
            time.sleep(1)
        return records

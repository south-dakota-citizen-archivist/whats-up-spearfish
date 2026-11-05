"""
scrapers/sources/town_news.py

Black Hills Pioneer and Rapid City Journal — both use the TownNews/BLOX CMS
JSON search API with the same query parameters, differing only in base URL and
collection string.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from scrapers import net
from scrapers.base import BaseScraper
from scrapers.utils import make_slug

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "tr"}


def _first_paragraph(html_chunks: list[str]) -> str:
    """Return the text of the first non-empty <p> tag across all content chunks."""
    for chunk in html_chunks:
        soup = BeautifulSoup(chunk, "html.parser")
        for p in soup.find_all("p"):
            text = p.get_text(" ", strip=True)
            if text:
                return text
    return ""


def _fetch_articles(search_url: str, collection_string: str) -> list[dict]:
    resp = net.get(
        search_url,
        params={
            "l": 100,
            "sd": "desc",
            "s": "start_time",
            "f": "json",
            "t": "article",
            "c": collection_string,
        },
        headers=_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("rows", [])


def _fetch_from_proxy(proxy_url: str) -> list[dict]:
    """Fetch articles from S3 proxy URL (used when GitHub Actions is blocked)."""
    resp = net.get(proxy_url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    # Proxy returns a list directly, not a dict with "rows" key
    if isinstance(data, list):
        return data
    return data.get("rows", [])


def _parse_record(item: dict, source_label: str) -> dict | None:
    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    if not title or not url:
        return None

    # Date from starttime.iso8601
    published = ""
    starttime = item.get("starttime") or {}
    iso = starttime.get("iso8601") or ""
    if iso:
        try:
            published = dateutil_parser.parse(iso).date().isoformat()
        except (ValueError, TypeError):
            pass

    byline = re.sub(r"\s+", " ", (item.get("byline") or "")).strip()

    content_chunks: list[str] = item.get("content") or []
    description = _first_paragraph(content_chunks)

    return {
        "url": url,
        "title": title,
        "slug": make_slug(f"{source_label}-{title}"),
        "published": published,
        "byline": byline,
        "description": description,
        "record_type": "news",
        "source_label": source_label,
    }


class _TownNewsScraper(BaseScraper):
    """Shared base for TownNews/BLOX CMS sources."""

    search_url: str
    collection_string: str

    def scrape(self) -> list[dict]:
        rows = _fetch_articles(self.search_url, self.collection_string)
        if not rows:
            raise RuntimeError(
                f"[{self.name}] API returned 0 rows — possible IP block or endpoint change. URL: {self.search_url}"
            )
        records = []
        for item in rows:
            record = _parse_record(item, self.name)
            if record:
                records.append(record)
        print(f"  [{self.name}] {len(records)} articles fetched")
        return records


class BlackHillsPioneer(_TownNewsScraper):
    name = "Black Hills Pioneer"
    slug = "black_hills_pioneer"
    tier = "frequent"  # news: every 3 hours
    kind = "news"
    url = "https://www.bhpioneer.com/"
    search_url = "https://www.bhpioneer.com/search"
    collection_string = "local_news,state_news"
    # Proxy URL (GitHub Actions blocked, data fetched via external proxy)
    proxy_url = "https://8085c7a2-365c-4367-aada-45882f0d7164.s3.us-west-2.amazonaws.com/bhp-latest.json"

    def scrape(self) -> list[dict]:
        rows = _fetch_from_proxy(self.proxy_url)
        if not rows:
            raise RuntimeError(f"[{self.name}] Proxy returned 0 rows. URL: {self.proxy_url}")
        records = []
        for item in rows:
            record = _parse_record(item, self.name)
            if record:
                records.append(record)
        print(f"  [{self.name}] {len(records)} articles fetched")
        return records


class RapidCityJournal(_TownNewsScraper):
    name = "Rapid City Journal"
    slug = "rapid_city_journal"
    tier = "frequent"  # news: every 3 hours
    kind = "news"
    url = "https://rapidcityjournal.com/"
    search_url = "https://rapidcityjournal.com/search"
    collection_string = "news/local*,news/state-and-regional*"
    # Proxy URL (GitHub Actions blocked, data fetched via external proxy)
    proxy_url = "https://8085c7a2-365c-4367-aada-45882f0d7164.s3.us-west-2.amazonaws.com/rcj-latest.json"

    def scrape(self) -> list[dict]:
        rows = _fetch_from_proxy(self.proxy_url)
        if not rows:
            raise RuntimeError(f"[{self.name}] Proxy returned 0 rows. URL: {self.proxy_url}")
        records = []
        for item in rows:
            record = _parse_record(item, self.name)
            if record:
                records.append(record)
        print(f"  [{self.name}] {len(records)} articles fetched")
        return records

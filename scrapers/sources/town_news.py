"""
scrapers/sources/town_news.py

Black Hills Pioneer and Rapid City Journal — both use the TownNews/BLOX CMS
JSON search API with the same query parameters, differing only in base URL and
collection string.

Sends a Slack message for each new article containing the headline (linked),
date, byline, and full article plaintext.
"""

from __future__ import annotations

import re

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from scrapers.base import BaseScraper
from scrapers.slack import send_alert
from scrapers.utils import make_slug

_HEADERS = {"User-Agent": "Mozilla/5.0"}
_BLOCK_TAGS = {"p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "br", "tr"}


def _html_to_text(html_chunks: list[str]) -> str:
    """Join content HTML chunks and return plaintext with paragraph breaks."""
    combined = "\n".join(html_chunks)
    soup = BeautifulSoup(combined, "html.parser")

    # Replace block-level elements with a trailing newline before extracting text
    for tag in soup.find_all(_BLOCK_TAGS):
        tag.append("\n")

    text = soup.get_text(separator="")
    # Collapse runs of blank lines to a single blank line, strip edges
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


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
    resp = requests.get(
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
    full_text = _html_to_text(content_chunks)

    return {
        "url": url,
        "title": title,
        "slug": make_slug(f"{source_label}-{title}"),
        "published": published,
        "byline": byline,
        "description": description,
        "_full_text": full_text,  # used for Slack only, not rendered on site
        "record_type": "news",
        "source_label": source_label,
    }


def _slack_blocks(record: dict) -> list[dict]:
    """Build Block Kit blocks for one article alert."""
    header = (f"*<{record['url']}|{record['title']}>*\n{record['published']}   {record['byline']}").strip()

    blocks: list[dict] = [{"type": "section", "text": {"type": "mrkdwn", "text": header}}]

    # Split full text into ≤2900-char chunks to stay within Slack block limits
    text = record.get("_full_text") or ""
    chunk_size = 2900
    for i in range(0, max(len(text), 1), chunk_size):
        chunk = text[i : i + chunk_size]
        if chunk.strip():
            blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": chunk}})

    return blocks


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

    def run(self) -> list[dict]:
        new_records = super().run()
        for record in new_records:
            # Strip internal field before alerting
            full_text = record.pop("_full_text", "")
            record_with_text = {**record, "_full_text": full_text}
            send_alert(
                text=f"{self.name}: {record['title']}",
                blocks=_slack_blocks(record_with_text),
            )
        return new_records


class BlackHillsPioneer(_TownNewsScraper):
    name = "Black Hills Pioneer"
    slug = "black_hills_pioneer"
    search_url = "https://www.bhpioneer.com/search"
    collection_string = "local_news,state_news"


class RapidCityJournal(_TownNewsScraper):
    name = "Rapid City Journal"
    slug = "rapid_city_journal"
    search_url = "https://rapidcityjournal.com/search"
    collection_string = "news/local*,news/state-and-regional*"

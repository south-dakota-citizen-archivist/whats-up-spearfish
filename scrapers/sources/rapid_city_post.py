"""
scrapers/sources/rapid_city_post.py

Rapid City Post — local news via RSS feed.
https://rapidcitypost.com/feed/
"""

from __future__ import annotations

import feedparser
from dateutil import parser as dateutil_parser

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

FEED_URL = "https://rapidcitypost.com/feed/"


class RapidCityPost(BaseScraper):
    name = "Rapid City Post"
    slug = "rapid_city_post"

    def scrape(self) -> list[dict]:
        feed = feedparser.parse(FEED_URL)
        records = []
        for entry in feed.entries:
            url = entry.get("link", "").strip()
            title = entry.get("title", "").strip()
            if not url or not title:
                continue

            published = ""
            if entry.get("published"):
                try:
                    published = dateutil_parser.parse(entry.published).date().isoformat()
                except (ValueError, TypeError):
                    pass

            byline = entry.get("author", "").strip()

            # Strip HTML from summary/description
            summary = entry.get("summary", "")
            if summary:
                import re

                summary = re.sub(r"<[^>]+>", " ", summary)
                summary = re.sub(r"\s+", " ", summary).strip()

            records.append(
                {
                    "url": url,
                    "title": title,
                    "slug": make_slug(f"rapid-city-post-{title}"),
                    "published": published,
                    "byline": byline,
                    "description": summary,
                    "record_type": "news",
                    "source_label": "Rapid City Post",
                }
            )

        print(f"  [{self.name}] {len(records)} articles fetched")
        return records

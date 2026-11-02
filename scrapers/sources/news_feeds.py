"""
scrapers/sources/news_feeds.py

Regional news RSS feeds.
"""

from __future__ import annotations

import feedparser
from dateutil import parser as dateutil_parser

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

_FEEDS = [
    {
        "url": "https://www.sdnewswatch.org/rss/",
        "source_label": "South Dakota News Watch",
        "key": "SD Newswatch",  # its former label; story ids are built from it, so it stays
    },
    {
        "url": "https://southdakotasearchlight.com/feed/localFeed/",
        "source_label": "South Dakota Searchlight",
        "key": "South Dakota Searchlight",
    },
]


def _parse_feed(url: str, source_label: str, key: str = "") -> list[dict]:
    feed = feedparser.parse(url)
    records = []
    for entry in feed.entries:
        title = entry.get("title", "").strip()
        if not title:
            continue
        link = entry.get("link", "")
        description = entry.get("summary", "").strip()
        published = ""
        for field in ("published_parsed", "updated_parsed"):
            val = entry.get(field)
            if val:
                try:
                    published = (
                        dateutil_parser.parse(entry.get("published") or entry.get("updated") or "").date().isoformat()
                    )
                except (ValueError, TypeError):
                    pass
                break
        byline = (entry.get("author") or "").strip()
        records.append(
            {
                "url": link,
                "title": title,
                "slug": make_slug(f"{key or source_label}-{title}"),
                "published": published,
                "byline": byline,
                "description": description,
                "record_type": "news",
                "source_label": source_label,
            }
        )
    return records


class NewsFeeds(BaseScraper):
    name = "Regional News"
    slug = "news_feeds"
    kind = "news"
    url = "https://www.sdnewswatch.org/"
    dedup_key = "slug"

    def scrape(self) -> list[dict]:
        records = []
        for feed in _FEEDS:
            items = _parse_feed(feed["url"], feed["source_label"], feed["key"])
            print(f"  [{feed['source_label']}] {len(items)} items")
            records.extend(items)
        return records

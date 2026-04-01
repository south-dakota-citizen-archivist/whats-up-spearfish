"""
scrapers/sources/lawrence_county_feeds.py

Lawrence County, SD — Jobs and News Flash RSS feeds.
https://www.lawrence.sd.us/rss.aspx#calendar

Two sources backed by the same CivicEngage RSS endpoint:
  LawrenceCountyJobs      → /RSSFeed.aspx?CommunityJobs=False&ModID=66&CID=All-0
  LawrenceCountyNewsFlash → /RSSFeed.aspx?ModID=1&CID=All-newsflash.xml
"""

import feedparser

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

BASE = "https://www.lawrence.sd.us"


def _parse_feed(url: str, record_type: str, source_label: str) -> list[dict]:
    feed = feedparser.parse(url)
    records = []
    for entry in feed.entries:
        records.append({
            "url": entry.get("link", ""),
            "title": entry.get("title", ""),
            "slug": make_slug(entry.get("title", "")),
            "description": entry.get("summary", ""),
            "published": entry.get("published", ""),
            "record_type": record_type,
            "source_label": source_label,
        })
    return records


class LawrenceCountyJobs(BaseScraper):
    name = "Lawrence County Jobs"
    slug = "lawrence_county_jobs"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        return _parse_feed(
            f"{BASE}/RSSFeed.aspx?CommunityJobs=False&ModID=66&CID=All-0",
            record_type="job",
            source_label="Lawrence County",
        )


class LawrenceCountyNews(BaseScraper):
    name = "Lawrence County News Flash"
    slug = "lawrence_county_news"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        return _parse_feed(
            f"{BASE}/RSSFeed.aspx?ModID=1&CID=All-newsflash.xml",
            record_type="press_release",
            source_label="Lawrence County",
        )

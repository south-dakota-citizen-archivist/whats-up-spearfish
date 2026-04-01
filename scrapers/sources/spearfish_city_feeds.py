"""
scrapers/sources/spearfish_city_feeds.py

City of Spearfish, SD — CivicEngage RSS feeds.
https://www.spearfish.gov/rss.aspx#calendar

Five sources (AgendaCenter RSS omitted — it returns city nav pages, not documents;
real agendas/minutes come from spearfish_city.py via the CivicClerk API):
  SpearfishAlertCenter   — utility/road/parks alerts (ModID=63)
  SpearfishBlog          — city blog posts (ModID=51)
  SpearfishCalendar      — city events calendar (ModID=58)
  SpearfishJobs          — job postings (ModID=66)
  SpearfishNews          — news flash / press releases (ModID=1)
"""

import feedparser

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

BASE = "https://www.spearfish.gov"


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
            "start_dt": entry.get("published", ""),
            "record_type": record_type,
            "source_label": source_label,
        })
    return records


class SpearfishAlertCenter(BaseScraper):
    name = "City of Spearfish Alert Center"
    slug = "spearfish_alert_center"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        return _parse_feed(
            f"{BASE}/RSSFeed.aspx?ModID=63&CID=All-0",
            record_type="alert",
            source_label="City of Spearfish",
        )


class SpearfishBlog(BaseScraper):
    name = "City of Spearfish Blog"
    slug = "spearfish_blog"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        return _parse_feed(
            f"{BASE}/RSSFeed.aspx?ModID=51&CID=All-blog.xml",
            record_type="press_release",
            source_label="City of Spearfish",
        )


class SpearfishCalendar(BaseScraper):
    name = "City of Spearfish Calendar"
    slug = "spearfish_calendar"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        return _parse_feed(
            f"{BASE}/RSSFeed.aspx?ModID=58&CID=All-calendar.xml",
            record_type="event",
            source_label="City of Spearfish",
        )


class SpearfishJobs(BaseScraper):
    name = "City of Spearfish Jobs"
    slug = "spearfish_jobs"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        return _parse_feed(
            f"{BASE}/RSSFeed.aspx?CommunityJobs=False&ModID=66&CID=All-0",
            record_type="job",
            source_label="City of Spearfish",
        )


class SpearfishNews(BaseScraper):
    name = "City of Spearfish News Flash"
    slug = "spearfish_news"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        return _parse_feed(
            f"{BASE}/RSSFeed.aspx?ModID=1&CID=All-newsflash.xml",
            record_type="press_release",
            source_label="City of Spearfish",
        )

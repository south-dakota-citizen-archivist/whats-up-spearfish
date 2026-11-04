"""
tests/test_scraper_news_feeds.py

South Dakota Searchlight and South Dakota News Watch, two newsrooms read from
their RSS feeds by one scraper.
"""

from __future__ import annotations

import feedparser

from scrapers.sources.news_feeds import _FEEDS, _parse_feed

RSS = """<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>
<item><title>Legislature opens</title><link>https://example.com/a</link>
<pubDate>Mon, 02 Nov 2026 08:00:00 -0600</pubDate></item>
</channel></rss>"""


def test_label_and_stable_story_id():
    watch = next(f for f in _FEEDS if "sdnewswatch" in f["url"])
    (story,) = _parse_feed(feedparser.parse(RSS), watch["source_label"], watch["key"])
    assert story["source_label"] == "South Dakota News Watch"
    assert story["slug"] == "sd-newswatch-legislature-opens"  # ids from before the rename still match
    assert story["published"] == "2026-11-02"


def test_pioneer_job_tags_read_as_words():
    from scrapers.sources.bhpioneer_jobs import tidy_category

    assert [tidy_category(t) for t in ("Fulltime", "Parttime", "PART-TIME", "Job", "")] == [
        "Full time", "Part time", "Part time", "", ""]  # fmt: skip

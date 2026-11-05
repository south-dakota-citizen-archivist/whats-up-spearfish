"""
scrapers/sources/sundance_times.py

Sundance Times: local news from sundancetimes.com, from its RSS feed (title, link,
a summary) plus each story's byline from its page.

  https://www.sundancetimes.com/rss     the latest ~40 stories
  /story/YYYY/MM/DD/section/slug/N.html a story; the date is the edition it ran in

The feed's times carry a wrong offset ('16:09:00 +0100' for an afternoon post in
Wyoming), so a story is dated by its edition, from its address, as the paper
dates it on the page. Bylines are read once per story: a story saved with one keeps it.
"""

from __future__ import annotations

import re
import time

from bs4 import BeautifulSoup

from scrapers import net
from scrapers.base import BaseScraper
from scrapers.utils import fetch_feed, make_slug

BASE_URL = "https://www.sundancetimes.com"
FEED_URL = f"{BASE_URL}/rss"
DELAY = 1.0  # seconds between story pages
_DATE_RE = re.compile(r"/story/(\d{4})/(\d{2})/(\d{2})/")

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def _clean(text: str) -> str:
    return " ".join(BeautifulSoup(text or "", "html.parser").get_text(" ").split())


def parse_entry(entry) -> dict | None:
    url = (entry.get("link") or "").strip()
    title = _clean(entry.get("title", ""))
    m = _DATE_RE.search(url)
    if not url or not title or not m:
        return None
    return {
        "url": url,
        "title": title,
        "slug": make_slug(f"sundance-times-{title}"),
        "published": "-".join(m.groups()),
        "byline": "",
        "description": _clean(entry.get("summary", "")),
        "record_type": "news",
        "source_label": "Sundance Times",
    }


def parse_byline(html: str) -> str:
    """The author's name from a story page ('Sarah Pridgeon'), or ''."""
    soup = BeautifulSoup(html, "html.parser")
    a = soup.select_one(".byline_date_comments .author a, .byline_date_comments .author")
    return " ".join(a.get_text(" ").split()) if a else ""


class SundanceTimes(BaseScraper):
    name = "Sundance Times"
    slug = "sundance_times"
    tier = "frequent"  # news: every 3 hours
    url = "https://www.sundancetimes.com"
    kind = "news"

    def scrape(self) -> list[dict]:
        feed = fetch_feed(FEED_URL, headers=_HEADERS)
        records = [r for r in (parse_entry(e) for e in feed.entries) if r]
        saved = {r.get("url"): r.get("byline", "") for r in self.load_existing()}
        for r in records:
            if saved.get(r["url"]):
                r["byline"] = saved[r["url"]]
                continue
            time.sleep(DELAY)
            try:
                resp = net.get(r["url"], headers=_HEADERS, timeout=20)
                resp.raise_for_status()
                r["byline"] = parse_byline(resp.text)
            except Exception as exc:  # noqa: BLE001 — the story still counts without its byline
                print(f"  [{self.name}] no byline for {r['url']}: {exc}")
        print(f"  [{self.name}] {len(records)} articles fetched")
        return records

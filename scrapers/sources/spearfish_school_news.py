"""
scrapers/sources/spearfish_school_news.py

Spearfish School District news (https://www.spearfish.k12.sd.us/news).

Read from Apptegy's public Thrillshare API (news section 547209) rather than
the page, which sits behind a bot check.
"""

from __future__ import annotations

from scrapers import net
from scrapers.base import BaseScraper

API_URL = "https://thrillshare-cmsv2.services.thrillshare.com/api/v2/s/547209/articles"


def parse_article(a: dict) -> dict | None:
    if not a.get("title") or not a.get("link"):
        return None
    return {
        "title": a["title"].strip(),
        "url": a["link"],
        "published": a.get("published_at") or "",
        "description": " ".join((a.get("snippet") or "").split()),
        "image_url": a.get("cover_image") or "",
    }


class SpearfishSchoolNews(BaseScraper):
    name = "Spearfish School District"
    slug = "spearfish_school_news"
    url = "https://www.spearfish.k12.sd.us/news"
    kind = "press_release"
    dedup_key = "url"
    replace = True  # the API always returns the latest articles

    def scrape(self) -> list[dict]:
        resp = net.get(API_URL, params={"locale": "en"})
        resp.raise_for_status()
        return [r for r in map(parse_article, resp.json().get("articles") or []) if r]

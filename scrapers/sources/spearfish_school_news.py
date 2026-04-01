"""
scrapers/sources/spearfish_school_news.py

Spearfish School District news articles.
https://www.spearfish.k12.sd.us/news

Apptegy CMS — SSR'd HTML when fetched without a custom User-Agent.
"""

import requests
from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

BASE_URL = "https://www.spearfish.k12.sd.us"
NEWS_URL = f"{BASE_URL}/news"


class SpearfishSchoolNews(BaseScraper):
    name = "Spearfish School District"
    slug = "spearfish_school_news"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        resp = requests.get(NEWS_URL, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        records = []
        for item in soup.select("div.article-info"):
            title_el = item.select_one(".title a")
            date_el = item.select_one(".article-date")
            desc_el = item.select_one(".content")

            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            url = href if href.startswith("http") else BASE_URL + href

            date_str = date_el.get_text(strip=True) if date_el else ""
            published = ""
            if date_str:
                try:
                    published = dateutil_parser.parse(date_str).date().isoformat()
                except (ValueError, OverflowError):
                    pass

            description = desc_el.get_text(" ", strip=True) if desc_el else ""

            records.append({
                "url": url,
                "title": title,
                "slug": make_slug(title),
                "published": published,
                "description": description,
                "record_type": "press_release",
                "source_label": self.name,
            })

        return records

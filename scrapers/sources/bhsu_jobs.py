"""
scrapers/sources/bhsu_jobs.py

BHSU job postings via the SD Board of Regents YourFuture Atom feed.
https://yourfuture.sdbor.edu/postings/search.atom?...
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

import requests

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

FEED_URL = (
    "https://yourfuture.sdbor.edu/postings/search.atom"
    "?utf8=%E2%9C%93&query=&query_v0_posted_at_date=&435="
    "&query_organizational_tier_1_id%5B%5D=1252&225=&commit=Search"
)
_NS = {"atom": "http://www.w3.org/2005/Atom"}
_TAG_RE = re.compile(r"<[^>]+>")


class BHSUJobs(BaseScraper):
    name = "BHSU"
    slug = "bhsu_jobs"
    dedup_key = "url"
    replace = True

    def scrape(self) -> list[dict]:
        resp = requests.get(FEED_URL, timeout=20)
        resp.raise_for_status()
        root = ET.fromstring(resp.content)

        records = []
        for entry in root.findall("atom:entry", _NS):
            link_el = entry.find("atom:link", _NS)
            url = link_el.get("href", "") if link_el is not None else ""
            title = (entry.findtext("atom:title", namespaces=_NS) or "").strip()
            published = (entry.findtext("atom:published", namespaces=_NS) or "").strip()
            content_html = entry.findtext("atom:content", namespaces=_NS) or ""
            description = re.sub(r"\s+", " ", _TAG_RE.sub(" ", content_html)).strip()

            author_el = entry.find("atom:author", _NS)
            department = ""
            if author_el is not None:
                department = (author_el.findtext("atom:name", namespaces=_NS) or "").strip()

            if not url or not title:
                continue

            records.append({
                "url": url,
                "title": title,
                "slug": make_slug(title),
                "department": department,
                "description": description,
                "published": published,
                "record_type": "job",
                "source_label": self.name,
            })

        return records

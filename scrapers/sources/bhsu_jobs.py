"""
scrapers/sources/bhsu_jobs.py

BHSU job postings via the SD Board of Regents YourFuture Atom feed, with each
posting's page read for what the feed leaves out: the advertised salary and the
closing date ("Open Until Filled" when there isn't one).
https://yourfuture.sdbor.edu/postings/search.atom?...
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

from scrapers import net
from scrapers.base import BaseScraper
from scrapers.utils import make_slug

FEED_URL = (
    "https://yourfuture.sdbor.edu/postings/search.atom"
    "?utf8=%E2%9C%93&query=&query_v0_posted_at_date=&435="
    "&query_organizational_tier_1_id%5B%5D=1252&225=&commit=Search"
)
_NS = {"atom": "http://www.w3.org/2005/Atom"}
_TAG_RE = re.compile(r"<[^>]+>")


def parse_posting_page(page: str) -> dict:
    """{'salary': '$1,076-$1,317 per credit hour', 'closing': '2026-11-30' or 'Open until filled'}"""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(page, "html.parser")
    fields = {}
    for row in soup.find_all("tr"):
        th, td = row.find("th"), row.find("td")
        if th and td:
            fields.setdefault(" ".join(th.get_text(" ").split()), " ".join(td.get_text(" ").split()))
    out = {}
    if salary := fields.get("Advertised Salary"):
        out["salary"] = salary
    closing = fields.get("Closing Date", "")
    if m := re.fullmatch(r"(\d{1,2})/(\d{1,2})/(\d{4})", closing):
        out["closing"] = f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    elif fields.get("Open Until Filled", "").lower().startswith("y"):
        out["closing"] = "Open until filled"
    return out


class BHSUJobs(BaseScraper):
    name = "BHSU"
    slug = "bhsu_jobs"
    url = "https://yourfuture.sdbor.edu/"
    kind = "job"
    min_records = 0
    dedup_key = "url"
    replace = True

    def scrape(self) -> list[dict]:
        resp = net.get(FEED_URL, timeout=20)
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

            records.append(
                {
                    "url": url,
                    "title": title,
                    "slug": make_slug(title),
                    "department": department,
                    "description": description,
                    "published": published,
                    "record_type": "job",
                    "source_label": self.name,
                }
            )

        for r in records:
            try:
                page = net.get(r["url"], timeout=20)
                page.raise_for_status()
                r.update(parse_posting_page(page.text))
            except Exception as exc:  # noqa: BLE001 — the posting still lists without the extras
                print(f"[{self.slug}] couldn't read {r['url']}: {exc}")
        return records

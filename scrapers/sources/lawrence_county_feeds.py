"""
scrapers/sources/lawrence_county_feeds.py

Lawrence County, SD — job openings.
https://lawrence.sd.us/381/Employment-Opportunities

The county posts each opening as a PDF linked from its Employment Opportunities
page ("Job Opening - Custodian (PDF)"). Its CivicEngage jobs module and RSS feed
stay empty, and its News Flash holds only standing pages (a link to the public
notices site, "Notify Me"), so neither is scraped any more.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from scrapers import net
from scrapers.base import BaseScraper
from scrapers.utils import make_slug

JOBS_PAGE = "https://lawrence.sd.us/381/Employment-Opportunities"

_OPENING = re.compile(r"^\s*job\s+opening\s*[-–:]\s*", re.I)
_FILE_TYPE = re.compile(r"\s*\((?:PDF|DOCX?)\)\s*$", re.I)


def parse_jobs_page(page: str, base: str = JOBS_PAGE) -> list[dict]:
    """The 'Job Opening - …' links on the Employment Opportunities page."""
    soup = BeautifulSoup(page, "html.parser")
    area = soup.select_one("#moduleContent") or soup
    records, seen = [], set()
    for a in area.find_all("a", href=True):
        text = " ".join(a.get_text(" ").split())
        if not _OPENING.match(text):
            continue
        url = urljoin(base, a["href"])
        title = _FILE_TYPE.sub("", _OPENING.sub("", text)).strip()
        if not title or url in seen:
            continue
        seen.add(url)
        records.append(
            {
                "url": url,
                "title": title,
                "slug": make_slug(title),
                "department": "Lawrence County",
                "description": "",
                "record_type": "job",
                "source_label": "Lawrence County",
            }
        )
    return records


class LawrenceCountyJobs(BaseScraper):
    name = "Lawrence County Jobs"
    slug = "lawrence_county_jobs"
    kind = "job"
    url = JOBS_PAGE
    min_records = 0
    dedup_key = "url"
    replace = True

    def scrape(self) -> list[dict]:
        resp = net.get(JOBS_PAGE)
        resp.raise_for_status()
        return parse_jobs_page(resp.text)

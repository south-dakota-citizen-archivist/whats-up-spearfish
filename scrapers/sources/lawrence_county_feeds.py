"""
scrapers/sources/lawrence_county_feeds.py

Lawrence County, SD — job openings.
https://lawrence.sd.us/381/Employment-Opportunities

The county posts each opening as a PDF linked from its Employment Opportunities
page ("Job Opening - Custodian (PDF)"). Every notice has the same labeled lines
(Date, Job Title, Department/Office, Closing Date, Starting Pay, Description of
Duties …), read for the posting date, department, pay and closing.

Its CivicEngage jobs module and RSS feed stay empty, and its News Flash holds only
standing pages (a link to the public notices site, "Notify Me"), so neither is
scraped any more.
"""

from __future__ import annotations

import logging
import re
from io import BytesIO
from urllib.parse import urljoin

from bs4 import BeautifulSoup
from dateutil import parser as dateparser

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


# The notice's labels, in the order they appear; a value runs until the next label
NOTICE_LABELS = (
    "Date", "Job Title", "Department/Office", "Closing Date", "Start Date", "Starting Pay", "Work Schedule",
    "Submit Application", "Description of Duties", "Experience/Education", "Additional Information",
)  # fmt: skip
_LABEL_RE = re.compile(r"^(" + "|".join(re.escape(x) for x in NOTICE_LABELS) + r")\b[^:\n]*:\s*", re.M)


def _iso_day(text: str) -> str:
    try:
        return dateparser.parse(re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text)).date().isoformat()
    except (ValueError, OverflowError):
        return ""


def parse_notice(text: str) -> dict:
    """A job opening notice's text → the fields worth showing."""
    fields: dict[str, str] = {}
    marks = list(_LABEL_RE.finditer(text))
    for m, nxt in zip(marks, marks[1:] + [None]):
        value = text[m.end() : nxt.start() if nxt else len(text)]
        value = value.split("Lawrence County is an equal opportunity employer")[0]
        fields.setdefault(m.group(1), " ".join(value.split()))
    out = {}
    if title := fields.get("Job Title"):
        out["title"] = title
    if dept := fields.get("Department/Office"):
        out["department"] = dept
    if posted := _iso_day(fields.get("Date", "")):
        out["published"] = posted
    closing = fields.get("Closing Date", "")
    if re.search(r"fill", closing, re.I):
        out["closing"] = "Open until filled"
    elif closing:
        out["closing"] = _iso_day(closing) or closing
    if pay := fields.get("Starting Pay"):
        out["salary"] = pay
    if duties := fields.get("Description of Duties"):
        out["description"] = duties
    return out


def read_notice(url: str) -> dict:
    import pdfplumber

    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    resp = net.get(url, timeout=30)
    resp.raise_for_status()
    if not resp.content.startswith(b"%PDF"):
        return {}
    with pdfplumber.open(BytesIO(resp.content)) as pdf:
        return parse_notice("\n".join(page.extract_text() or "" for page in pdf.pages))


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
        records = parse_jobs_page(resp.text)
        for r in records:
            try:
                notice = read_notice(r["url"])
            except Exception as exc:  # noqa: BLE001 — still listed by its link text
                print(f"[{self.slug}] couldn't read {r['url']}: {exc}")
                continue
            r.update(notice)
            r["slug"] = make_slug(r["title"])
        return records

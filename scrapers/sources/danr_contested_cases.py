"""
scrapers/sources/danr_contested_cases.py

SD DANR contested cases: permit applications someone has formally challenged,
heard by the Board of Minerals and Environment, the Water Management Board or
the DANR secretary. Kept: cases in western South Dakota, plus general permits
that apply statewide.

Both Caspio tables answer a plain request (no browser):

  - the case list: grouped rows (board, then permit type, then cases)
  - each case's documents, newest first, 100 to a page; the first page is all
    we need for "latest filings"
"""

from __future__ import annotations

import re
import time

from bs4 import BeautifulSoup

from scrapers import dates, net
from scrapers.base import BaseScraper
from scrapers.sources.danr_public_notices import _is_west_river

PAGE_URL = "https://danr.sd.gov/public/ContestedCase.aspx"
LISTING_URL = "https://b4.caspio.com/dp/31cf1000eff3306683ed4c7eac99"
DOCS_URL = "https://c0bkr159.caspio.com/dp/31cf10006288b0620fa04c92be66"
CASE_URL = "https://danr.sd.gov/public/ccdocs.aspx?CCID=CCID{}"
LATEST_DOCS = 3

_HEADERS = {
    "User-Agent": "whats-up-in-spearfish/1.0 (public data aggregator)",
    "Referer": PAGE_URL,
    "Accept": "text/html,application/xhtml+xml",
}
# Legal descriptions west of the Missouri use the Black Hills Meridian, whose
# ranges run east ("T4N-R6E"); east river's run west from the 5th meridian.
_BH_MERIDIAN_RE = re.compile(r"\bT\s?\d{1,2}\s?[NS]\s?[-,]?\s?R\s?\d{1,2}\s?E\b")


def _get(url: str, **params) -> BeautifulSoup:
    resp = net.get(url, params=params or None, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def parse_listing(soup: BeautifulSoup) -> list[dict]:
    """Cases from the grouped list: board and permit type come from the group rows above each case."""
    cases, board, permit_type = [], "", ""
    for tr in soup.find_all("tr", attrs={"data-cb-name": True}):
        name = tr["data-cb-name"]
        if name == "group1":
            board = tr.get_text(" ", strip=True)
        elif name == "group2":
            permit_type = tr.get_text(" ", strip=True)
        elif name == "data":
            cells = tr.find_all("td")
            link = tr.find("a", href=re.compile(r"CCID=CCID\d+", re.I))
            m = re.search(r"CCID=CCID(\d+)", link["href"], re.I) if link else None
            if not m or len(cells) < 5:
                continue
            cases.append(
                {
                    "ccid": m.group(1),
                    "board": re.sub(r"\s+Proceeding$", "", board),
                    "permit_type": permit_type,
                    "title": cells[3].get_text(" ", strip=True),
                    "description": " ".join(cells[4].get_text(" ", strip=True).split()),
                }
            )
    return cases


def is_local(case: dict) -> bool:
    text = f"{case['title']} {case['description']}"
    return _is_west_river(text) or bool(_BH_MERIDIAN_RE.search(text))


def parse_documents(soup: BeautifulSoup) -> list[dict]:
    """Filings on a case's first documents page: title, link and the date DANR added it."""
    table = soup.find("table", class_="cbResultSetListView")
    docs = []
    for tr in table.find_all("tr") if table else []:
        a = tr.find("a", href=True)
        if not a:
            continue
        added = ""
        label = tr.find(class_="cbResultSetListViewDataLabel", string=re.compile("Date Added"))
        if label and (value := label.find_next_sibling("span")):
            parsed = dates.parse(value.get_text(strip=True))
            added = parsed.isoformat() if parsed else ""
        docs.append({"title": a.get_text(" ", strip=True), "url": a["href"], "added": added})
    return docs


class DANRContestedCases(BaseScraper):
    name = "SD DANR contested cases"
    slug = "danr_contested_cases"
    kind = "case"
    url = PAGE_URL
    replace = True
    dedup_key = "ccid"
    min_records = 0  # there may be no West River cases at times
    max_stale_hours = 24 * 3

    def scrape(self) -> list[dict]:
        cases = parse_listing(_get(LISTING_URL))
        if not cases:
            raise RuntimeError("no contested cases could be read from the DANR page")
        out = []
        for case in cases:
            statewide = "general permit" in case["permit_type"].lower()
            if not (statewide or is_local(case)):
                continue
            docs = parse_documents(_get(DOCS_URL, CCID=f"CCID{case['ccid']}"))
            time.sleep(0.5)
            out.append(
                case
                | {
                    "area": "Statewide" if statewide else "",
                    "url": CASE_URL.format(case["ccid"]),
                    "documents": docs[:LATEST_DOCS],
                    "updated": next((d["added"] for d in docs if d["added"]), ""),
                }
            )
        return out

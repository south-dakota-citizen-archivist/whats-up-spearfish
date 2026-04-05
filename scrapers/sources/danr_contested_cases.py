"""
scrapers/sources/danr_contested_cases.py

SD DANR contested cases listing with supporting documents.

The listing page embeds a Caspio table that can be fetched directly with
requests (no browser required).  Each case's documents page requires Playwright
because Caspio uses session cookies to render the docs table.

Not a BaseScraper subclass — run directly or from the daily scrape workflow.

Usage:
    uv run python -c "
    from scrapers.sources.danr_contested_cases import fetch_danr_contested_cases
    fetch_danr_contested_cases()
    "
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "danr_contested_cases.json"
DANR_BASE = "https://danr.sd.gov"
LISTING_URL = "https://b4.caspio.com/dp/31cf1000eff3306683ed4c7eac99"

_HEADERS = {
    "User-Agent": "whats-up-in-spearfish/1.0 (public data aggregator)",
    "Referer": "https://danr.sd.gov/public/ContestedCase.aspx",
    "Accept": "text/html,application/xhtml+xml",
}

# Date pattern in document labels, e.g. "01/15/2026" or "1/5/2026"
_DATE_RE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def _doc_sort_key(doc: dict) -> str:
    """Return ISO sort key from a date found in the doc label; oldest sort first."""
    m = _DATE_RE.search(doc.get("label", ""))
    if m:
        return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
    return "0000-00-00"


def _fetch_listing() -> list[dict]:
    """Fetch the contested cases listing from Caspio and return structured cases."""
    resp = requests.get(LISTING_URL, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    cases: list[dict] = []
    current_board = ""
    current_permit_type = ""

    for tr in soup.find_all("tr", attrs={"data-cb-name": True}):
        cb_name = tr.get("data-cb-name", "")

        if cb_name == "group1":
            current_board = tr.get_text(" ", strip=True)
        elif cb_name == "group2":
            current_permit_type = tr.get_text(" ", strip=True)
        elif cb_name == "data":
            cells = tr.find_all("td")
            if len(cells) < 5:
                continue
            # Cell [2]: link to documents page (contains CCID)
            docs_a = cells[2].find("a", href=True)
            docs_url = docs_a["href"] if docs_a else ""
            ccid_m = re.search(r"CCID=CCID(\d+)", docs_url, re.IGNORECASE)
            ccid = ccid_m.group(1) if ccid_m else ""
            title = cells[3].get_text(" ", strip=True)
            description = cells[4].get_text(" ", strip=True)

            cases.append(
                {
                    "ccid": ccid,
                    "board": current_board,
                    "permit_type": current_permit_type,
                    "title": title,
                    "description": description,
                    "docs_url": docs_url,
                    "documents": [],
                    "total_docs": 0,
                }
            )

    return cases


def _fetch_documents(ccid: str) -> list[dict]:
    """Use Playwright to load the documents page and return the doc list."""
    from playwright.sync_api import sync_playwright

    url = f"https://danr.sd.gov/public/ccdocs.aspx?CCID=CCID{ccid}"
    docs: list[dict] = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(8000)
            html = page.content()
            browser.close()

        soup = BeautifulSoup(html, "html.parser")
        tables = soup.find_all("table")
        if len(tables) < 2:
            print(f"    [CC] CCID{ccid}: only {len(tables)} table(s) found")
            return []
        doc_table = tables[1]
        for tr in doc_table.find_all("tr"):
            a = tr.find("a", href=True)
            if not a:
                continue
            href = a["href"]
            label = a.get_text(" ", strip=True)
            if href and label:
                if href.startswith("/"):
                    href = DANR_BASE + href
                docs.append({"label": label, "url": href})
    except Exception as exc:
        print(f"    [CC] Warning: CCID{ccid} docs failed: {exc}")

    return docs


def fetch_danr_contested_cases() -> None:
    print("[CC] Fetching contested cases listing...")
    cases = _fetch_listing()
    print(f"[CC] {len(cases)} case(s) found")

    for case in cases:
        ccid = case["ccid"]
        if not ccid:
            continue
        print(f"  [CC] Fetching docs for CCID{ccid}: {case['title'][:60]}")
        docs = _fetch_documents(ccid)
        total = len(docs)
        # Sort newest-first by date found in label, then take 5 most recent
        docs.sort(key=_doc_sort_key, reverse=True)
        case["documents"] = docs[:5]
        case["total_docs"] = total
        print(f"    {total} doc(s), showing {len(case['documents'])}")
        time.sleep(1)

    DATA_FILE.write_text(
        json.dumps(
            {"fetched_at": datetime.now(timezone.utc).isoformat(), "cases": cases},
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"[CC] {len(cases)} case(s) → {DATA_FILE.name}")


if __name__ == "__main__":
    fetch_danr_contested_cases()

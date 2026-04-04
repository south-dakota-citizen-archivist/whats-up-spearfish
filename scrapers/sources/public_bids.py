"""
scrapers/sources/public_bids.py

Open public bids for the City of Spearfish and Lawrence County.
Both use CivicPlus/CivicEngage CMS with identical HTML structure.

https://www.spearfish.gov/Bids.aspx?CatID=showStatus&txtSort=Category&showAllBids=on&Status=open
https://www.lawrence.sd.us/Bids.aspx?CatID=showStatus&txtSort=Category&showAllBids=on&Status=open
"""

from __future__ import annotations

import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; SpearfishBulletin/1.0)"}

_SOURCES = [
    {
        "base_url": "https://www.spearfish.gov",
        "list_path": "/Bids.aspx?CatID=showStatus&txtSort=Category&Status=open",
        "source_label": "City of Spearfish",
    },
    {
        "base_url": "https://www.lawrence.sd.us",
        "list_path": "/Bids.aspx?CatID=showStatus&txtSort=Category&Status=open",
        "source_label": "Lawrence County",
    },
]

_DATE_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")


def _closes_iso(closes: str) -> str:
    """Convert 'M/D/YYYY H:MM AM/PM' to ISO string for reliable sorting, or ''."""
    for fmt in ("%m/%d/%Y %I:%M %p", "%m/%d/%Y"):
        try:
            return datetime.strptime(closes.strip(), fmt).isoformat()
        except ValueError:
            continue
    return ""


def _parse_bids(html: str, base_url: str, source_label: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records = []

    for row in soup.select("div.listItemsRow.bid"):
        # Title and URL
        title_a = row.select_one("div.bidTitle a")
        if not title_a:
            continue
        title = title_a.get_text(strip=True)
        rel_url = title_a.get("href", "")
        url = base_url + "/" + rel_url.lstrip("/") if rel_url else base_url

        # Bid number — strong tag "Bid No." followed by text
        bid_no_span = row.select_one("div.bidTitle span > strong")
        bid_no = ""
        if bid_no_span:
            raw = bid_no_span.parent.get_text(strip=True)
            bid_no = raw.replace("Bid No.", "").strip()

        # Status and closing date are in two sibling divs inside .bidStatus
        status_div = row.select_one("div.bidStatus")
        status = ""
        closes = ""
        if status_div:
            child_divs = status_div.find_all("div", recursive=False)
            if len(child_divs) >= 2:
                value_spans = child_divs[1].find_all("span")
                if len(value_spans) >= 1:
                    status = value_spans[0].get_text(strip=True)
                if len(value_spans) >= 2:
                    closes = value_spans[1].get_text(strip=True)

        # Only keep open bids
        if status.lower() not in ("open", "active"):
            continue

        # Description snippet (third span in bidTitle, before "Read on")
        desc_spans = row.select("div.bidTitle > span")
        description = ""
        for span in desc_spans:
            text = span.get_text(" ", strip=True)
            if text and "Read" not in text and "Bid No." not in text and title not in text:
                # Strip trailing "[" from truncated descriptions
                description = re.sub(r"\s*\[\s*$", "", text).strip()
                break

        records.append(
            {
                "url": url,
                "title": title,
                "slug": make_slug(f"{source_label}-{bid_no or title}"),
                "bid_no": bid_no,
                "status": status,
                "closes": closes,
                "closes_iso": _closes_iso(closes),
                "description": description,
                "record_type": "bid",
                "source_label": source_label,
            }
        )

    return records


class PublicBids(BaseScraper):
    name = "Public Bids"
    slug = "public_bids"
    dedup_key = "slug"
    replace = True

    def scrape(self) -> list[dict]:
        records = []
        for src in _SOURCES:
            url = src["base_url"] + src["list_path"]
            resp = requests.get(url, headers=_HEADERS, timeout=20)
            resp.raise_for_status()
            bids = _parse_bids(resp.text, src["base_url"], src["source_label"])
            print(f"  [{src['source_label']}] {len(bids)} open bids")
            records.extend(bids)
        return records

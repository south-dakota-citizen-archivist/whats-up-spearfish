"""
scrapers/sources/spearfish_school_board_docs.py

Spearfish School Board agendas and minutes via Thrillshare CMS API.
https://www.spearfish.k12.sd.us/documents/board-of-education/board-meeting-agendas/25745609
https://www.spearfish.k12.sd.us/documents/board-of-education/board-meeting-minutes/25745856
"""

from __future__ import annotations

import re

import requests
from dateutil import parser as dateutil_parser

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

API_BASE = "https://thrillshare-cmsv2.services.thrillshare.com/api/v2/s/547213/documents"

# Top-level folder IDs on the new site
_ROOTS = {
    "agenda": 25745609,
    "minutes": 25745856,
}

_LABEL_RE = re.compile(r"^[a-z]\.\s+", re.IGNORECASE)  # strip leading "k. " prefixes
# Match a date at the start of the title, e.g. "March 9, 2026"
_DATE_RE = re.compile(r"^([A-Za-z]+ \d{1,2},? \d{4})")


def _clean_title(raw: str) -> str:
    return _LABEL_RE.sub("", raw).strip()


def _parse_date(title: str) -> str:
    """Extract and return an ISO date string from the beginning of the title, or ''."""
    m = _DATE_RE.match(title)
    if not m:
        return ""
    try:
        return dateutil_parser.parse(m.group(1)).date().isoformat()
    except (ValueError, OverflowError):
        return ""


def _get_json(folder_id: int) -> dict:
    r = requests.get(API_BASE, params={"folder_id": folder_id}, timeout=15)
    r.raise_for_status()
    return r.json()


def _fetch_folder(folder_id: int, doc_type: str) -> list[dict]:
    """Recursively fetch all documents from a folder and its subfolders."""
    data = _get_json(folder_id)
    records = []

    # items array has stable permanent URLs; documents array has blob URLs
    for item in data.get("items", []):
        raw_title = (item.get("file_name") or "").strip()
        title = _clean_title(raw_title)
        url = (item.get("url") or "").strip()
        if not title or not url:
            continue

        slug = make_slug(f"spearfish-board-{doc_type}-{title}")
        published = _parse_date(title)

        records.append(
            {
                "url": url,
                "title": title,
                "slug": slug,
                "published": published,
                "asset_type": doc_type,
                "record_type": "document",
                "source_label": "Spearfish School Board",
            }
        )

    # Recurse into subfolders
    for subfolder in data.get("meta", {}).get("folders", []):
        records.extend(_fetch_folder(subfolder["id"], doc_type))

    return records


class SpearfishSchoolBoardDocs(BaseScraper):
    name = "Spearfish School Board"
    slug = "spearfish_school_board_docs"
    dedup_key = "slug"

    def scrape(self) -> list[dict]:
        seen: set[str] = set()
        records = []
        for doc_type, folder_id in _ROOTS.items():
            for record in _fetch_folder(folder_id, doc_type):
                if record["slug"] not in seen:
                    seen.add(record["slug"])
                    records.append(record)
        return records

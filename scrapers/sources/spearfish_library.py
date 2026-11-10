"""
scrapers/sources/spearfish_library.py

Grace Balloch Memorial Library — recently added books via Koha coverflow API.

Each report ID corresponds to a collection/category in the ILS.
Books are fetched as HTML fragments and parsed for title, cover image,
and OPAC detail URL.

The Koha instance is behind Cloudflare. sdfetch starts with plain HTTP (which got the
reports from a laptop in 2026-11) and climbs to curl_cffi and then a stealth browser only
if Cloudflare challenges the request, as it may from a CI runner's address.
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

import sdfetch
from bs4 import BeautifulSoup

from scrapers import net
from scrapers.base import BaseScraper

BASE_URL = "https://spearfish.blackhills.bywatersolutions.com"
API_URL = f"{BASE_URL}/api/v1/contrib/coverflow/reports/{{report_id}}"

# Report IDs for recently-added collections
REPORT_IDS = [260, 261, 281, 282, 373, 1168, 1171, 1348]

_TRAILING_PUNCT_RE = re.compile(r"[\s/:,]+$")

# Amazon answers a missing cover with a 1×1 GIF (43 bytes) instead of an error
_STUB_BYTES = 200
_AMAZON_SIZE_RE = re.compile(r"\.01\.[A-Z]+\.jpg$")


def has_cover(image_url: str) -> bool:
    """Whether a cover image is a real picture. Unreachable counts as yes; the page copes."""
    # the medium Amazon size is enough to tell, at a tenth of the download
    probe = _AMAZON_SIZE_RE.sub(".01.MZZZZZZZ.jpg", image_url)
    try:
        resp = net.get(probe, timeout=15)
    except Exception:  # noqa: BLE001
        return True
    return resp.ok and len(resp.content) > _STUB_BYTES


def drop_missing_covers(records: list[dict]) -> None:
    with ThreadPoolExecutor(max_workers=8) as pool:
        found = list(pool.map(lambda r: has_cover(r["image_url"]) if r["image_url"] else False, records))
    for r, ok in zip(records, found):
        if not ok:
            r["image_url"] = ""


def _parse_html(html: str, report_id: int) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    records = []
    for li in soup.select(".koha-coverflow ul li"):
        a = li.find("a", href=True)
        img = li.find("img")
        p = li.find("p")

        if not a or not p:
            continue

        href = a["href"].strip()
        if not href.startswith("http"):
            href = BASE_URL + href

        raw_title = p.get_text(" ", strip=True)
        title = _TRAILING_PUNCT_RE.sub("", raw_title).strip()
        if not title:
            continue

        image_url = img["src"].strip() if img and img.get("src") else ""
        # Skip placeholder "no image" images
        if "NoImage" in image_url:
            image_url = ""
        elif image_url and not image_url.startswith("http"):
            image_url = BASE_URL + image_url

        records.append(
            {
                "url": href,
                "title": title,
                "image_url": image_url,
                "record_type": "library_book",
                "source_label": "Grace Balloch Memorial Library",
            }
        )

    return records


def _fetch_all_books() -> list[dict]:
    records = []
    seen_urls: set[str] = set()

    # Plain HTTP first; curl_cffi, then a stealth browser, only if Cloudflare challenges
    with sdfetch.Fetcher(max_strategy="stealth", delay=1, timeout=30, raise_errors=False) as f:
        for report_id in REPORT_IDS:
            url = API_URL.format(report_id=report_id)
            try:
                resp = f.request("GET", url)
                if resp.status_code != 200:
                    print(f"[SpearfishLibrary] Warning: report {report_id} returned {resp.status_code}")
                    continue
                html = resp.text
            except Exception as exc:
                print(f"[SpearfishLibrary] Warning: report {report_id} failed: {exc}")
                continue

            for record in _parse_html(html, report_id):
                if record["url"] not in seen_urls:
                    seen_urls.add(record["url"])
                    records.append(record)

    return records


class SpearfishLibrary(BaseScraper):
    name = "Grace Balloch Memorial Library"
    slug = "spearfish_library"
    kind = "library_book"
    url = "https://spearfish.blackhills.bywatersolutions.com"
    browser = True
    dedup_key = "url"
    replace = True

    def scrape(self) -> list[dict]:
        books = _fetch_all_books()
        drop_missing_covers(books)
        return books

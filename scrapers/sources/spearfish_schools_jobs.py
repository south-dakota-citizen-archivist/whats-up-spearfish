"""
scrapers/sources/spearfish_schools_jobs.py

Spearfish School District job postings via the BHSSC AppliTrack/Frontline board.
https://www.applitrack.com/bhssc/onlineapp/default.aspx

Job data is served as document.write() JavaScript from Output.asp per category.
Only Spearfish-location listings are kept.
"""

from __future__ import annotations

import re
import time
import urllib.parse

import requests
from bs4 import BeautifulSoup

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

BASE_URL = "https://www.applitrack.com/bhssc/onlineapp"
LIST_URL = f"{BASE_URL}/default.aspx"
OUTPUT_URL = f"{BASE_URL}/jobpostings/Output.asp"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": LIST_URL,
}

# Matches each document.write('...') call; handles \' inside the string
_DOC_WRITE_RE = re.compile(r"document\.write\('((?:[^'\\]|\\.)*)'\)")
# ul id like p4523_17 → job_id=4523, district_id=17
_UL_ID_RE = re.compile(r"^p(\d+)_(\d+)$")


def _extract_html(js_text: str) -> str:
    """Concatenate all document.write() string payloads into one HTML blob."""
    parts = []
    for m in _DOC_WRITE_RE.finditer(js_text):
        raw = m.group(1)
        raw = raw.replace("\\'", "'").replace('\\"', '"').replace("\\\\", "\\")
        parts.append(raw)
    return "".join(parts)


def _label_text(soup_el) -> str:
    """Return the text of the .normal span that follows a .label span."""
    label = soup_el.find("span", class_="label")
    if label:
        nrm = label.find_next_sibling("span", class_="normal")
        if nrm:
            return nrm.get_text(" ", strip=True)
    return ""


def _parse_posting(ul) -> dict | None:
    """Parse one <ul class='postingsList'> into a record dict, or None to skip."""
    ul_id = ul.get("id", "")
    m = _UL_ID_RE.match(ul_id)
    job_id = m.group(1) if m else ""
    # Title
    title_td = ul.find("td", id="wrapword")
    title = title_td.get_text(strip=True) if title_td else ""
    if not title:
        return None

    # Field rows — each <li> has a .label + .normal pair
    li_map: dict[str, str] = {}
    for li in ul.find_all("li"):
        label_el = li.find("span", class_="label")
        normal_el = li.find("span", class_="normal")
        if label_el and normal_el:
            key = label_el.get_text(strip=True).rstrip(":")
            val = normal_el.get_text(" ", strip=True)
            li_map[key] = val

    location = li_map.get("Location", "")
    district = li_map.get("District", "")
    published = li_map.get("Date Posted", "")
    closing = li_map.get("Closing Date", "")
    position_type = li_map.get("Position Type", "")

    # Filter: Spearfish only
    if "spearfish" not in location.lower() and "spearfish" not in district.lower():
        return None

    # Apply / detail URL
    url = (
        f"{BASE_URL}/_application.aspx"
        f"?posJobCodes={job_id}"
        f"&posFirstChoice={urllib.parse.quote(position_type)}"
    ) if job_id else LIST_URL

    description_parts = []
    if position_type:
        description_parts.append(f"Position type: {position_type}")
    if location:
        description_parts.append(f"Location: {location}")
    if closing:
        description_parts.append(f"Closes: {closing}")
    description = " · ".join(description_parts)

    return {
        "url": url,
        "title": title,
        "slug": make_slug(f"{job_id}-{title}"),
        "location": location,
        "district": district,
        "position_type": position_type,
        "published": published,
        "closing": closing,
        "description": description,
        "record_type": "job",
        "source_label": "Spearfish School District",
    }


def _get_categories(session: requests.Session) -> list[str]:
    resp = session.get(LIST_URL, headers=_HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    cats = []
    for a in soup.select("a[id*='CatLnk']"):
        href = a.get("href", "")
        qs = urllib.parse.parse_qs(urllib.parse.urlparse(href).query)
        cat = qs.get("Category", [None])[0]
        if cat:
            cats.append(cat)
    return cats


def _get_jobs_for_category(session: requests.Session, category: str) -> list[dict]:
    url = f"{OUTPUT_URL}?Category={urllib.parse.quote(category)}"
    resp = session.get(url, headers=_HEADERS, timeout=20)
    resp.raise_for_status()

    html = _extract_html(resp.text)
    if not html:
        return []

    soup = BeautifulSoup(html, "html.parser")
    records = []
    for ul in soup.find_all("ul", class_="postingsList"):
        record = _parse_posting(ul)
        if record:
            records.append(record)
    return records


class SpearfishSchoolsJobs(BaseScraper):
    name = "Spearfish School District"
    slug = "spearfish_schools_jobs"
    dedup_key = "slug"
    replace = True

    def scrape(self) -> list[dict]:
        session = requests.Session()
        categories = _get_categories(session)
        if not categories:
            print(f"[{self.name}] No categories found.")
            return []

        seen_slugs: set[str] = set()
        records = []
        for cat in categories:
            cat_records = _get_jobs_for_category(session, cat)
            for r in cat_records:
                if r["slug"] not in seen_slugs:
                    seen_slugs.add(r["slug"])
                    records.append(r)
            time.sleep(0.5)

        return records

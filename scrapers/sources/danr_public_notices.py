"""
scrapers/sources/danr_public_notices.py

South Dakota DANR public notices, filtered to west river / Black Hills counties.

The DANR page embeds Caspio database tables via <script> tags. No browser needed:

  1. Fetch the static DANR HTML to map AppKey → section heading
  2. For each section, request the table the way Caspio's embed script does
     (/dp/<appkey>?cbqe=<base64 query>); the answer is JavaScript whose
     parseAndLoadDatapage(…) call carries the table HTML as an escaped string
  3. Deadline dates live inside inline <script> tags — extracted via regex
  4. Keep rows whose location / description mentions a west-river county

"""

from __future__ import annotations

import base64
import json
import re
import time

from bs4 import BeautifulSoup

from scrapers import net
from scrapers.base import BaseScraper

DANR_URL = "https://danr.sd.gov/public/default.aspx"

WEST_RIVER = {
    "lawrence",
    "meade",
    "butte",
    "harding",
    "pennington",
    "custer",
    "fall river",
    "bennett",
    "jackson",
    "shannon",
    "oglala lakota",
    "ziebach",
    "dewey",
    "corson",
    "perkins",
    # Common west-river city names as fallback
    "spearfish",
    "deadwood",
    "lead",
    "rapid city",
    "sturgis",
    "belle fourche",
    "hot springs",
    "edgemont",
    "hill city",
}

_APPKEY_RE = re.compile(r"/dp/([0-9a-f]{20,})")
# Date embedded in inline script: var dline=new Date("04/10/2026");
_DLINE_RE = re.compile(r'new Date\("([^"]+)"\)')
# Comment/petition URL embedded in innerHTML assignment
_COMMENT_URL_RE = re.compile(r'href=\\"(https://danr\.sd\.gov/public/comment\.aspx[^"\\]+)\\"')

_HEADERS = {
    "User-Agent": "whats-up-in-spearfish/1.0 (public data aggregator)",
    "Referer": DANR_URL,
    "Accept": "text/html,application/xhtml+xml",
}


_WEST_RIVER_RE = re.compile(r"\b(" + "|".join(sorted(WEST_RIVER, key=len, reverse=True)) + r")\b", re.I)


def _is_west_river(text: str) -> bool:
    # whole words: "lead" is a town, "leading" isn't
    return bool(_WEST_RIVER_RE.search(text))


def _build_section_map() -> list[tuple[str, str, str]]:
    """
    Fetch static HTML and return list of (heading, subdomain, appkey) tuples.
    Preserves document order so notice_type labels match the correct tables.
    """
    resp = net.get(DANR_URL, timeout=20, headers=_HEADERS)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")

    sections: list[tuple[str, str, str]] = []
    for section in soup.find_all("section"):
        heading_el = section.find(["h2", "h3"])
        script = section.find("script", src=True)
        if not heading_el or not script:
            continue
        src = script.get("src", "")
        m = _APPKEY_RE.search(src)
        if not m:
            continue
        # Extract subdomain from the full URL
        subdomain_m = re.match(r"https://([^/]+)/", src)
        subdomain = subdomain_m.group(1) if subdomain_m else "b4.caspio.com"
        heading = re.sub(r"\s+", " ", heading_el.get_text(" ", strip=True))
        sections.append((heading, subdomain, m.group(1)))

    print(f"[DANR] {len(sections)} Caspio section(s) found")
    return sections


_DATAPAGE_RE = re.compile(r"parseAndLoadDatapage\('[^']*',\s*'[^']*',\s*'((?:[^'\\]|\\.)*)'")


def datapage_html(script: str) -> str | None:
    """The table HTML inside Caspio's embed response (a single-quoted JS string)."""
    m = _DATAPAGE_RE.search(script)
    if not m:
        return None
    # JS single-quoted → JSON double-quoted: its escapes (\u003c, \", \n) are JSON's too
    return json.loads('"' + m.group(1).replace("\\'", "'") + '"')


def _fetch_table(subdomain: str, appkey: str) -> BeautifulSoup | None:
    query = (
        f"AppKey={appkey}&js=true&cbEmbDeployWith=new_async_embedjs&cbDatapageAnchorId=dp_anchor_id_1"
        f"&pathname={DANR_URL}&cbScreenWidth=1280&cbEmbQueryStr=&cbParamList="
    )
    url = f"https://{subdomain}/dp/{appkey}?cbqe=" + base64.b64encode(query.encode()).decode()
    try:
        resp = net.get(url, headers=_HEADERS, timeout=30)
        if not resp.ok:
            return None
    except Exception as exc:  # noqa: BLE001
        print(f"  [DANR] Warning: {subdomain}/dp/{appkey}: {exc}")
        return None
    html = datapage_html(resp.text)
    return BeautifulSoup(html, "html.parser") if html else None


def _parse_deadline_cell(cell) -> tuple[str, str]:
    """
    Return (deadline_date, comment_url) from a deadline <td>.
    The date is in an inline <script>: var dline=new Date("04/10/2026");
    The comment URL is also in the script's innerHTML string.
    """
    script = cell.find("script")
    if not script:
        raw = cell.get_text(" ", strip=True)
        deadline = re.sub(r"^[^:]*[Dd]eadline\s*:\s*", "", raw).strip()
        return deadline, ""
    script_text = script.string or ""
    date_m = _DLINE_RE.search(script_text)
    url_m = _COMMENT_URL_RE.search(script_text)
    if date_m:
        deadline = date_m.group(1)
    else:
        # Fallback: strip "Petition Deadline:" / "Comment Deadline:" prefixes from text
        raw = cell.get_text(" ", strip=True)
        deadline = re.sub(r"^[^:]+Deadline\s*:\s*", "", raw).strip()
    comment_url = url_m.group(1).replace("\\\\", "").replace('\\"', '"') if url_m else ""
    return deadline, comment_url


def _parse_table(soup: BeautifulSoup, notice_type: str) -> list[dict]:
    table = soup.find("table", class_="cbResultSetTable")
    if not table:
        return []

    # Column headers
    headers: list[str] = []
    header_row = table.find("tr", class_="cbResultSetTableHeader")
    if header_row:
        headers = [th.get_text(strip=True).rstrip(":") for th in header_row.find_all("th")]

    rows: list[dict] = []
    for tr in table.find_all("tr", class_="cbResultSetDataRow"):
        cells = tr.find_all("td", class_="cbResultSetData")
        if not cells:
            continue

        record: dict = {"notice_type": notice_type, "deadline": "", "comment_url": ""}
        links: list[dict] = []

        for i, cell in enumerate(cells):
            # Strip mobile label span
            label_span = cell.find("span", class_="cbResultSetLabel")
            label_text = label_span.get_text(strip=True) if label_span else ""

            header = (headers[i] if i < len(headers) else label_text.rstrip(":")).lower()

            # Links before we get_text (they'd be lost otherwise)
            for a in cell.find_all("a", href=True):
                href = a["href"]
                text = a.get_text(strip=True)
                if href and text and not href.startswith("javascript"):
                    links.append({"label": text, "url": href})

            # Deadline: date lives in an inline script
            if any(k in header for k in ("deadline", "comment", "petition")):
                deadline, comment_url = _parse_deadline_cell(cell)
                record["deadline"] = deadline
                if comment_url:
                    record["comment_url"] = comment_url
                continue

            # Plain text value (strip label prefix)
            value = cell.get_text(" ", strip=True)
            if label_text and value.startswith(label_text):
                value = value[len(label_text) :].lstrip(":").strip()

            if any(k in header for k in ("facility", "name", "applicant", "business")):
                record["name"] = value
            elif "description" in header:
                record["description"] = value
            elif any(k in header for k in ("location", "county")):
                record["location"] = value
            elif any(k in header for k in ("appl", "permit")) and "no" in header:
                record["application_no"] = value
            elif any(k in header for k in ("source", "water")):
                record["water_source"] = value
            elif "use" in header:
                record["use_type"] = value

        record["links"] = links
        rows.append(record)

    return rows


def _deadline_iso(n: dict) -> str:
    m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", n.get("deadline", "") or "")
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else ""


class DANRPublicNotices(BaseScraper):
    name = "SD DANR public notices (West River)"
    slug = "danr_public_notices"
    kind = "notice"
    url = DANR_URL
    replace = True
    dedup_key = "notice_key"
    min_records = 0  # some weeks there are no West River notices

    def scrape(self) -> list[dict]:
        notices: list[dict] = []
        tables = 0
        for heading, subdomain, appkey in _build_section_map():
            soup = _fetch_table(subdomain, appkey)
            if soup is None:
                continue
            tables += 1
            notices.extend(_parse_table(soup, heading))
            time.sleep(0.3)
        if not tables:
            # zero notices is normal for West River; zero *tables* means the page changed
            raise RuntimeError("no notice tables could be read from the DANR page")
        notices = [
            n
            for n in notices
            if _is_west_river(" ".join(str(n.get(k) or "") for k in ("location", "name", "description")))
        ]

        for n in notices:
            n["title"] = n.get("name") or n.get("description", "")[:120] or n["notice_type"]
            n["url"] = n.get("comment_url") or next((link["url"] for link in n.get("links", [])), DANR_URL)
            n["deadline_iso"] = _deadline_iso(n)
            n["notice_key"] = "|".join(
                [n["notice_type"], n.get("application_no", ""), n["title"], n.get("location", "")]
            )
        notices.sort(key=lambda n: n["deadline_iso"] or "9999")
        return notices

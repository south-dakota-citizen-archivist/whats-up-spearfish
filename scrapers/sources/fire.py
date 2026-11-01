"""
scrapers/sources/fire.py

Fire conditions for the Black Hills:
  - restrictions by jurisdiction from blackhillsfirerestrictions.com
  - active South Dakota wildfires from InciWeb
  - fire danger by zone from the NWS Rapid City Rangeland Fire Danger statement

Each part is fetched independently; one failing doesn't sink the others.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from scrapers import net
from scrapers.base import BaseScraper

RESTRICTIONS_URL = "https://www.blackhillsfirerestrictions.com/"
INCIWEB_URL = "https://inciweb.wildfire.gov/accessible-view"
INCIWEB_BASE = "https://inciweb.wildfire.gov"
NWS_RFD_URL = (
    "https://forecast.weather.gov/product.php?site=UNR&issuedby=UNR&product=RFD&format=TXT&version=1&glossary=0"
)

#: Column order of the restrictions table's icon cells.
RESTRICTION_COLUMNS = ["Campfires", "Smoking", "Charcoal", "Gas grills", "Wood stoves", "Welding", "Fireworks"]

_LEVEL_RE = re.compile(r"\.\.\.(LOW|MODERATE|HIGH|VERY HIGH|EXTREME)\s+FIRE\s+DANGER\.\.\.", re.IGNORECASE)


def _soup(url: str) -> BeautifulSoup:
    resp = net.get(url, timeout=20)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, "html.parser")


def _fmt_acres(raw: str) -> str:
    m = re.search(r"[\d,]+", raw)
    if not m:
        return raw
    return f"{int(m.group().replace(',', '')):,} {raw[m.end() :].strip() or 'acres'}"


def fetch_restrictions() -> list[dict]:
    soup = _soup(RESTRICTIONS_URL)
    table = soup.find("table", attrs={"cellpadding": "0", "cellspacing": "1"})
    rows: list[dict] = []
    if not table:
        return rows
    section = ""
    for tr in table.find_all("tr", recursive=False):
        if sub := tr.find("td", bgcolor="#fcf0c8"):
            section = sub.get_text(strip=True)
            continue
        cells = tr.find_all("td", attrs={"width": "35"})
        if len(cells) != 7 or not (name_td := tr.find("td")):
            continue
        restricted = []
        for col, cell in zip(RESTRICTION_COLUMNS, cells):
            img = cell.find("img")
            stem = str(img.get("src") or "").split("/")[-1].replace(".gif", "") if img else "blank"
            if stem != "blank":
                restricted.append(col)
        more = next((str(a["href"]) for a in tr.find_all("a", href=True) if ".pdf" in str(a["href"]).lower()), "")
        rows.append(
            {
                "name": name_td.get_text(" ", strip=True),
                "section": section,
                "restricted": restricted,
                "more_info_url": more,
            }
        )
    return rows


def fetch_incidents() -> list[dict]:
    soup = _soup(INCIWEB_URL)
    table = soup.find("table", class_="usa-table")
    incidents: list[dict] = []
    if not table:
        return incidents

    def cell(cells, cls):
        return next((c for c in cells if cls in " ".join(c.get("class") or [])), None)

    for tr in table.select("tbody tr"):
        cells = tr.find_all("td")
        state = cell(cells, "views-field-field-state")
        title = cell(cells, "views-field-title")
        if not state or "South Dakota" not in state.get_text() or not title:
            continue
        a = title.find("a")
        href = str(a.get("href") or "") if a else ""
        size = cell(cells, "views-field-field-incident-size")
        kind = cell(cells, "views-field-field-incident-type")
        updated = cell(cells, "views-field-field-last-209-update")
        incidents.append(
            {
                "name": (a or title).get_text(strip=True),
                "type": kind.get_text(strip=True) if kind else "",
                "size": _fmt_acres(size.get_text(strip=True)) if size else "",
                "updated": updated.get_text(strip=True) if updated else "",
                "url": INCIWEB_BASE + href if href.startswith("/") else href,
            }
        )
    return incidents


def fetch_danger() -> dict:
    pre = _soup(NWS_RFD_URL).find("pre")
    text = pre.get_text() if pre else ""
    issued = re.search(r"\d{1,4} [AP]M [A-Z]{3} .+", text)
    zones = []
    for block in text.split("$$"):
        lm = _LEVEL_RE.search(block)
        if not lm:
            continue
        desc = []
        for line in block[lm.end() :].strip().splitlines():
            line = line.strip()
            if not line or line.startswith("The outlook"):
                break
            desc.append(line)
        names, past_codes = [], False
        for line in block.splitlines():
            line = line.strip()
            if re.match(r"^SDZ\d", line):
                past_codes = True
                continue
            if not past_codes:
                continue
            if re.match(r"^\d{3,4} [AP]M", line) or line.startswith("Including"):
                break
            # skip zone-code continuation lines like "074>078-020115-"
            if line and not line.startswith(".") and not re.fullmatch(r"[\d>\-]+", line):
                names.append(line)
        zones.append(
            {
                "name": "".join(names).strip().rstrip("-").replace("-", ", ") or "SD zone",
                "level": lm.group(1).title(),
                "description": " ".join(desc),
            }
        )
    return {"issued": issued.group(0).strip() if issued else "", "zones": zones, "url": NWS_RFD_URL}


class Fire(BaseScraper):
    name = "Fire restrictions, danger & wildfires"
    slug = "fire"
    kind = "fire"
    url = RESTRICTIONS_URL
    tier = "frequent"
    max_stale_hours = 12

    def scrape(self) -> dict:
        out: dict = {"errors": []}
        for key, fn in (("restrictions", fetch_restrictions), ("incidents", fetch_incidents), ("danger", fetch_danger)):
            try:
                out[key] = fn()
            except Exception as exc:  # noqa: BLE001
                out[key] = None
                out["errors"].append(f"{key}: {type(exc).__name__}: {exc}")
        return out

    def is_empty(self, payload: dict) -> bool:
        return all(payload.get(k) is None for k in ("restrictions", "incidents", "danger"))

"""
scrapers/sources/terry_peak.py

Terry Peak Ski Area (near Lead): the snow report, and which lifts and trails are open.

  https://terrypeak.com/the-mountain/weather-snow/   snow report: overnight, 48 and 72 hours,
                                                     season total, base depth
  https://terrypeak.com/the-mountain/trails-lifts/   lift and trail status, trail difficulty,
                                                     and whether a trail is groomed or has snowmaking

Both pages are server-rendered. Status, lift type, difficulty and trail condition are
icons (icon-open.svg, icon-quad.svg, icon-beginner.svg, icon-groomed.svg …), read from
their file names.
"""

from __future__ import annotations

import re

from bs4 import BeautifulSoup

from scrapers import net
from scrapers.base import BaseScraper

SNOW_URL = "https://terrypeak.com/the-mountain/weather-snow/"
TRAILS_URL = "https://terrypeak.com/the-mountain/trails-lifts/"
WEBCAMS_URL = "https://terrypeak.com/the-mountain/live-web-cams/"

SNOW_FIELDS = {"overnight": "overnight", "48 hours": "48h", "72 hours": "72h", "season": "season", "base": "base"}
LIFT_TYPES = {"surface": "surface lift", "triple": "triple chair", "quad": "high-speed quad"}
CONDITIONS = {"groomed": "groomed", "snow": "snowmaking"}


def _icons(node) -> list[str]:
    """Icon names in a node: '…/icons/icon-closed.svg' → 'closed'."""
    return [m.group(1) for img in node.find_all("img") if (m := re.search(r"icon-([a-z-]+)\.svg", img.get("src", "")))]


def _inches(text: str) -> float | None:
    m = re.search(r"(\d+(?:\.\d+)?)", text or "")
    return float(m.group(1)) if m else None


def parse_snow(page: str) -> dict:
    """{'overnight': 1.0, '48h': 1.0, '72h': 1.0, 'season': 1.0, 'base': 0.0} from the snow report."""
    soup = BeautifulSoup(page, "html.parser")
    pairs = []
    report = soup.select_one(".o-snow-report")
    if report:
        # the report itself: '1”' over 'Overnight', then '<strong>1"</strong> Season Snow Accumulation'
        for item in report.select(".o-snow-report__row-item"):
            inches, label = item.select_one(".o-snow-report__inches"), item.select_one(".o-snow-report__text")
            if inches and label:
                pairs.append((label.get_text(" "), inches.get_text()))
            for line in item.find_all("div", recursive=False):
                if strong := line.find("strong"):
                    pairs.append((line.get_text(" ").replace(strong.get_text(), ""), strong.get_text()))
    # every page's sidebar has the short version (overnight, 72 hours, base)
    for item in soup.select(".o-weather-sidebar__snow"):
        label = item.select_one(".o-weather-sidebar__small-text")
        inches = item.select_one(".o-weather-sidebar__snow-inch")
        if label and inches:
            pairs.append((label.get_text(" "), inches.get_text()))
    snow = {}
    for label, inches in pairs:
        label = " ".join(label.split()).lower()
        key = next((v for k, v in SNOW_FIELDS.items() if k in label), None)
        if key and key not in snow and (amount := _inches(inches)) is not None:
            snow[key] = amount
    return snow


def parse_status(page: str) -> dict:
    """Lifts and trails, each with whether it's open."""
    soup = BeautifulSoup(page, "html.parser")
    lifts, trails = [], []
    lift_box = soup.select_one("#liftStatus")
    for row in lift_box.select(".o-status__table-row") if lift_box else []:
        name_col, *rest = row.select(".o-status__table-column")
        icons = _icons(name_col) + [i for col in rest for i in _icons(col)]
        name = " ".join(name_col.get_text(" ").split())
        if name:
            lifts.append(
                {
                    "name": name,
                    "open": "open" in icons,
                    "type": next((LIFT_TYPES[i] for i in icons if i in LIFT_TYPES), ""),
                }
            )
    for row in soup.select(".js-trails-item"):
        name_col, *rest = row.select(".o-status__table-column")
        icons = _icons(name_col)
        condition = [CONDITIONS[i] for col in rest for i in _icons(col) if i in CONDITIONS]
        name = " ".join(name_col.get_text(" ").split())
        if name:
            trails.append(
                {
                    "name": name,
                    "open": "open" in icons,
                    "difficulty": next((i for i in icons if i in ("beginner", "intermediate", "advanced")), ""),
                    "conditions": condition,
                }
            )
    return {"lifts": lifts, "trails": trails}


class TerryPeak(BaseScraper):
    name = "Terry Peak Ski Area"
    slug = "terry_peak"
    kind = "stats"
    url = TRAILS_URL
    tier = "frequent"

    def scrape(self) -> dict:
        status = net.get(TRAILS_URL, timeout=30)
        status.raise_for_status()
        snow = net.get(SNOW_URL, timeout=30)
        snow.raise_for_status()
        return {**parse_status(status.text), "snow": parse_snow(snow.text), "webcams": WEBCAMS_URL}

    def is_empty(self, payload: dict) -> bool:
        return not payload.get("lifts") and not payload.get("trails")

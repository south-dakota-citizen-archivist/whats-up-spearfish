"""
scrapers/sources/bhnf_alerts.py

Black Hills National Forest alerts.

Scrapes https://www.fs.usda.gov/r02/blackhills/alerts and returns records
with record_type="alert" so they appear in the alerts widget alongside
city/county and NWS alerts.

Uses replace=True because the page reflects the current live state —
an alert removed from the page should stop showing on the site.
"""

from __future__ import annotations

import re
from datetime import datetime

from bs4 import BeautifulSoup

from scrapers import net
from scrapers.base import BaseScraper

BASE_URL = "https://www.fs.usda.gov"
ALERTS_URL = f"{BASE_URL}/r02/blackhills/alerts"

_HEADERS = {
    "User-Agent": net.USER_AGENT,
    "Accept": "text/html,application/xhtml+xml",
}

# "Alert Start Date:" label — strip and parse what follows
_DATE_LABEL_RE = re.compile(r"Alert Start Date:\s*(.+)", re.IGNORECASE)


def _parse_date(text: str) -> str:
    """Return ISO date string from 'Month Day, Year' or '' on failure."""
    text = text.strip()
    for fmt in ("%B %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    # Handle single-digit day without zero-padding (strptime handles this already above)
    return ""


class BHNFAlerts(BaseScraper):
    name = "BHNF Alerts"
    slug = "bhnf_alerts"
    url = "https://www.fs.usda.gov/r02/blackhills/alerts"
    kind = "alert"
    tier = "frequent"
    min_records = 0
    replace = True  # Page reflects current live state

    def scrape(self) -> list[dict]:
        resp = net.get(ALERTS_URL, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, "html.parser")

        records: list[dict] = []

        for li in soup.select("li.usa-card.wfs-alert-flag"):
            # Alert type from class list (critical, fire-restriction, caution, information)
            classes = li.get("class", [])
            alert_type = ""
            for cls in classes:
                if cls not in ("usa-card", "usa-card--flag", "wfs-alert-flag"):
                    alert_type = cls
                    break

            # Title and URL
            h3 = li.find("h3")
            if not h3:
                continue
            a = h3.find("a", href=True)
            if not a:
                continue
            title = a.get_text(" ", strip=True)
            href = a["href"]
            url = href if href.startswith("http") else BASE_URL + href

            # Description
            body = li.find("div", class_="usa-card__body")
            description = body.get_text(" ", strip=True) if body else ""

            # Start date and optional forest order from footer
            published = ""
            forest_order = ""
            footer = li.find("footer") or li.find(class_="usa-card__footer")
            if footer:
                footer_text = footer.get_text(" ", strip=True)
                date_m = _DATE_LABEL_RE.search(footer_text)
                if date_m:
                    # The date text may be followed by "Forest Order: ..."
                    raw_date = date_m.group(1).split("Forest Order:")[0].strip()
                    published = _parse_date(raw_date)
                order_m = re.search(r"Forest Order:\s*#?(\S+)", footer_text, re.IGNORECASE)
                if order_m:
                    forest_order = order_m.group(1)

            record: dict = {
                "record_type": "alert",
                "title": title,
                "url": url,
                "description": description,
                "published": published,
                "source_label": "BHNF",
                "alert_type": alert_type,
            }
            if forest_order:
                record["forest_order"] = forest_order

            records.append(record)

        return records

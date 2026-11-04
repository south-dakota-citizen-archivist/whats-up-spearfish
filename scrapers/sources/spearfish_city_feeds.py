"""
scrapers/sources/spearfish_city_feeds.py

City of Spearfish, SD — CivicEngage RSS feeds.
https://www.spearfish.gov/rss.aspx#calendar

Four sources (AgendaCenter RSS omitted — it returns city nav pages, not documents;
real agendas/minutes come from spearfish_city.py via the CivicClerk API):
  SpearfishAlertCenter   — road closures, holiday schedules and other notices, read from
                           the Alert Center page itself (its RSS feed comes back empty
                           while the page still lists alerts)
  SpearfishCalendar      — city events calendar (RSS, ModID=58)
  SpearfishJobs          — openings on the city's job board (Criterion HCM), which the
                           Career Opportunities page embeds; the CivicEngage jobs module
                           and its feed are no longer used
  SpearfishNews          — news flash / press releases (RSS, ModID=1)

The city blog (ModID=51) is empty and no longer scraped.
"""

import re
from datetime import datetime

from bs4 import BeautifulSoup

from scrapers import dates, net
from scrapers.base import BaseScraper
from scrapers.utils import fetch_feed, make_slug

BASE = "https://www.spearfish.gov"
JOBS_API = "https://cityofspearfish.criterionhcm.com/api/jobs/443/1/api/organization/job"
JOBS_PAGE = "https://www.spearfish.gov/161/Career-Opportunities"


def _parse_feed(url: str, record_type: str, source_label: str) -> list[dict]:
    feed = fetch_feed(url)
    records = []
    for entry in feed.entries:
        records.append(
            {
                "url": entry.get("link", ""),
                "title": entry.get("title", ""),
                "slug": make_slug(entry.get("title", "")),
                "description": entry.get("summary", ""),
                "published": entry.get("published", ""),
                "start_dt": entry.get("published", ""),
                "record_type": record_type,
                "source_label": source_label,
            }
        )
    return records


def _calendar_dt(day: str, clock: str = "") -> str:
    """'November 2, 2026' (+ '09:30 AM') → ISO date or naive local datetime string."""
    d = datetime.strptime(day.strip(), "%B %d, %Y")
    if not clock:
        return d.date().isoformat()
    t = datetime.strptime(clock.strip(), "%I:%M %p")
    return d.replace(hour=t.hour, minute=t.minute).isoformat()


def parse_calendar_entry(entry: dict) -> dict:
    """
    CivicEngage calendar RSS: <pubDate> is when the item was posted; the event's
    own dates live in calendarEvent:EventDates / EventTimes (local time).
    """
    days = [x.strip() for x in (entry.get("calendarevent_eventdates") or "").split(" - ") if x.strip()]
    times = [x.strip() for x in (entry.get("calendarevent_eventtimes") or "").split(" - ") if x.strip()]
    all_day = not times or times == ["12:00 AM", "11:59 PM"]
    if all_day:
        start, end = _calendar_dt(days[0]), _calendar_dt(days[-1])
    else:
        start = _calendar_dt(days[0], times[0])
        end = _calendar_dt(days[-1], times[-1]) if len(times) > 1 else ""
    summary = entry.get("summary", "")
    # The feed's location field runs lines together ("625 N 5th StSpearfish, SD");
    # the same address in the summary keeps its line breaks.
    loc = re.search(r"Location:\s*</strong>\s*(?:<br\s*/?>)?(.*?)(?:<br\s*/?>\s*<strong>|$)", summary, re.S | re.I)
    lines = re.split(r"<br\s*/?>", loc.group(1), flags=re.I) if loc else []
    location = ", ".join(x.strip() for x in lines if x.strip())
    if not location:
        location = ", ".join(
            x.strip() for x in re.split(r"<br\s*/?>", entry.get("calendarevent_location", ""), flags=re.I) if x.strip()
        )
    parts = re.split(r"Description:\s*</strong>\s*(?:<br>)?", summary, maxsplit=1)
    description = parts[1] if len(parts) == 2 else ""
    return {
        "url": entry.get("link", ""),
        "title": entry.get("title", ""),
        "slug": make_slug(entry.get("title", "")),
        "description": description,
        "location": location,
        "start_dt": start,
        "end_dt": end if end != start else "",
        "all_day": all_day,
        "record_type": "event",
        "source_label": "City of Spearfish",
    }


def parse_alert_center(page: str) -> list[dict]:
    """Alerts listed on AlertCenter.aspx, under each category heading."""
    soup = BeautifulSoup(page, "html.parser")
    records = []
    for cat in soup.select("div.listing"):
        heading = cat.find("h2")
        for item in cat.select("li.alerts-list"):
            link = item.select_one("h3 a")
            if not link or not link.get("href"):
                continue
            when = item.select_one("span.date")
            stamp = when.get_text(" ", strip=True) if when else ""
            try:
                posted = datetime.strptime(stamp, "%B %d, %Y %I:%M %p" if ":" in stamp else "%B %d, %Y").isoformat()
            except ValueError:
                posted = ""
            full = " ".join(link.get_text(" ").split())
            title = re.sub(r"^City of Spearfish\s*[-–:]?\s*", "", full) or full
            # long alerts are cut short and followed by a "<title> Read On..." line
            paras = [" ".join(p.get_text(" ").split()) for p in item.find_all("p")]
            body = " ".join(x for x in paras if x and not x.endswith("Read On..."))
            href = link["href"]
            records.append(
                {
                    "url": BASE + href if href.startswith("/") else href,
                    "title": title,
                    "slug": make_slug(title),
                    "description": re.sub(r"\.{3,}$", "…", body),
                    "category": heading.get_text(strip=True) if heading else "",
                    "published": posted,
                    "record_type": "alert",
                    "source_label": "City of Spearfish",
                }
            )
    return records


class SpearfishAlertCenter(BaseScraper):
    name = "City of Spearfish Alert Center"
    slug = "spearfish_alert_center"
    kind = "alert"
    url = "https://www.spearfish.gov/AlertCenter.aspx"
    tier = "frequent"
    min_records = 0
    dedup_key = "url"
    replace = True  # the page lists every alert still posted
    naive_tz = dates.MT

    def scrape(self) -> list[dict]:
        resp = net.get(self.url)
        resp.raise_for_status()
        return parse_alert_center(resp.text)


class SpearfishCalendar(BaseScraper):
    name = "City of Spearfish Calendar"
    slug = "spearfish_calendar"
    kind = "event"
    url = "https://www.spearfish.gov/Calendar.aspx"
    category = "community"
    dedup_key = "url"

    naive_tz = dates.MT
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        feed = fetch_feed(f"{BASE}/RSSFeed.aspx?ModID=58&CID=All-calendar.xml")
        return [parse_calendar_entry(e) for e in feed.entries if e.get("calendarevent_eventdates")]


def parse_job(job: dict) -> dict:
    """One opening from the city's job board API."""
    title = " ".join((job.get("title") or "").split())
    department = job.get("department") or job.get("location") or ""
    details = [department, job.get("positionType") or "", job.get("salary") or ""]
    return {
        "url": job.get("jobUrl") or JOBS_PAGE,
        "title": title,
        "slug": make_slug(title),
        "department": department,
        "position_type": job.get("positionType") or "",
        "salary": job.get("salary") or "",
        "published": (job.get("openDate") or "").replace(".", "-"),
        "closing": (job.get("closeDate") or "").replace(".", "-")[:10],
        "description": " · ".join(d for d in details if d),
        "record_type": "job",
        "source_label": "City of Spearfish",
    }


class SpearfishJobs(BaseScraper):
    name = "City of Spearfish Jobs"
    slug = "spearfish_jobs"
    kind = "job"
    url = JOBS_PAGE
    min_records = 0
    dedup_key = "url"
    replace = True

    def scrape(self) -> list[dict]:
        resp = net.get(JOBS_API, params={"isInternal": "false", "page": 1, "start": 0, "limit": 100})
        resp.raise_for_status()
        return [parse_job(j) for j in resp.json().get("result", []) if j.get("title")]


class SpearfishNews(BaseScraper):
    name = "City of Spearfish News Flash"
    slug = "spearfish_news"
    kind = "press_release"
    url = "https://www.spearfish.gov/CivicAlerts.aspx"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        return _parse_feed(
            f"{BASE}/RSSFeed.aspx?ModID=1&CID=All-newsflash.xml",
            record_type="press_release",
            source_label="City of Spearfish",
        )

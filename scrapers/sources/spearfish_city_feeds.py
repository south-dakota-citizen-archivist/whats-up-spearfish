"""
scrapers/sources/spearfish_city_feeds.py

City of Spearfish, SD — CivicEngage RSS feeds.
https://www.spearfish.gov/rss.aspx#calendar

Five sources (AgendaCenter RSS omitted — it returns city nav pages, not documents;
real agendas/minutes come from spearfish_city.py via the CivicClerk API):
  SpearfishAlertCenter   — utility/road/parks alerts (ModID=63)
  SpearfishBlog          — city blog posts (ModID=51)
  SpearfishCalendar      — city events calendar (ModID=58)
  SpearfishJobs          — job postings (ModID=66)
  SpearfishNews          — news flash / press releases (ModID=1)
"""

import re
from datetime import datetime

from scrapers import dates
from scrapers.base import BaseScraper
from scrapers.utils import fetch_feed, make_slug

BASE = "https://www.spearfish.gov"


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


class SpearfishAlertCenter(BaseScraper):
    name = "City of Spearfish Alert Center"
    slug = "spearfish_alert_center"
    kind = "alert"
    url = "https://www.spearfish.gov/AlertCenter.aspx"
    tier = "frequent"
    min_records = 0
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        return _parse_feed(
            f"{BASE}/RSSFeed.aspx?ModID=63&CID=All-0",
            record_type="alert",
            source_label="City of Spearfish",
        )


class SpearfishBlog(BaseScraper):
    name = "City of Spearfish Blog"
    slug = "spearfish_blog"
    kind = "press_release"
    url = "https://www.spearfish.gov/Blog.aspx"
    min_records = 0
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        return _parse_feed(
            f"{BASE}/RSSFeed.aspx?ModID=51&CID=All-blog.xml",
            record_type="press_release",
            source_label="City of Spearfish",
        )


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


class SpearfishJobs(BaseScraper):
    name = "City of Spearfish Jobs"
    slug = "spearfish_jobs"
    kind = "job"
    url = "https://www.spearfish.gov/Jobs.aspx"
    min_records = 0
    dedup_key = "url"
    replace = True

    def scrape(self) -> list[dict]:
        return _parse_feed(
            f"{BASE}/RSSFeed.aspx?CommunityJobs=False&ModID=66&CID=All-0",
            record_type="job",
            source_label="City of Spearfish",
        )


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

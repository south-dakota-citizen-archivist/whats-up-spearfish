"""
scrapers/sources/bhsu_athletics.py

BHSU Yellow Jackets athletics schedule.
https://bhsuathletics.com/calendar

Sidearm Sports platform. Uses the adaptive_components.ashx JSON endpoint
with type=events, sport_id=0 (all sports), and a 90-day lookahead window.

Home games get a link to buy tickets to that game from BHSU's ticket shop
(vivenu), whose page carries its events as data (__NEXT_DATA__): one event per
game day, named like "Women's & Men's Basketball vs Chadron State 12/8" or
"BHSU Football vs. Chadron State - 11/7". A game matches the shop's event on its
day for its sport (and men's/women's, when the name says), and by opponent when
the day has more than one. Season passes are left out.
"""

import json
import re
from datetime import date, timedelta

from scrapers import dates, net
from scrapers.base import BaseScraper
from scrapers.utils import make_slug

API_URL = "https://bhsuathletics.com/services/adaptive_components.ashx"
SOURCE_URL = "https://bhsuathletics.com/calendar"
LOOKAHEAD_DAYS = 90
TICKET_SHOP = "https://black-hills-state-university-lcsj.vivenushop.com/"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)


def shop_events(html: str) -> list[dict]:
    """The ticket shop's single-game events: [{'name', 'date' (Mountain), 'url'}]."""
    m = _NEXT_DATA.search(html)
    if not m:
        return []
    page = json.loads(m.group(1)).get("props", {}).get("pageProps", {}).get("sellerPage", {})
    out = []
    for e in page.get("events") or []:
        if e.get("eventType") != "SINGLE" or not e.get("url") or not e.get("start"):
            continue
        start = dates.parse(e["start"])
        if start:
            out.append(
                {"name": e.get("name", ""), "date": start.date().isoformat(), "url": TICKET_SHOP + "event/" + e["url"]}
            )
    return out


def _gender_fits(sport: str, name: str) -> bool:
    """A men's game fits an event named for men's games (or for neither); likewise women's."""
    name = name.lower()
    names = {g for g in ("women's", "men's") if re.search(rf"\b{g}", name)}
    want = next((g for g in ("women's", "men's") if re.match(rf"{g}\b", sport.lower())), None)
    return not names or not want or want in names


def ticket_url(game: dict, events: list[dict]) -> str:
    """The shop's page for a home game, or '' when it has none."""
    start = dates.parse(game.get("start_dt") or "")
    day = start.date().isoformat() if start else ""
    sport = game.get("sport", "")
    kind = sport.split()[-1].lower() if sport else ""
    picks = [
        e for e in events
        if e["date"] == day and kind and kind in e["name"].lower() and _gender_fits(sport, e["name"])
    ]  # fmt: skip
    if len(picks) > 1:
        opponent = (game.get("opponent") or "").lower()
        picks = [e for e in picks if opponent and opponent in e["name"].lower()]
    return picks[0]["url"] if len(picks) == 1 else ""


class BHSUAthletics(BaseScraper):
    name = "BHSU Athletics"
    slug = "bhsu_athletics"
    kind = "event"
    url = "https://bhsuathletics.com/calendar"
    category = "bhsu sports"
    dedup_key = "game_id"

    def fix(self, record: dict) -> dict:
        # TBA games carry a midnight placeholder time; keep them on their date as all-day.
        if record.get("tbd") or (record.get("time") or "").upper() in ("TBA", "TBD", "ALL DAY"):
            record["start_dt"] = (record.get("start_dt") or "")[:10]
            record["all_day"] = True
        return record

    def scrape(self) -> list[dict]:
        today = date.today()
        resp = net.get(
            API_URL,
            params={
                "type": "events",
                "sport_id": 0,
                "start": today.isoformat(),
                "end": (today + timedelta(days=LOOKAHEAD_DAYS)).isoformat(),
                "count": 500,
                "name": "schedule-calendar",
            },
            headers={
                "User-Agent": "Mozilla/5.0",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": SOURCE_URL,
            },
            timeout=30,
        )
        resp.raise_for_status()
        events = resp.json() or []

        records = []
        for event in events:
            sport = event.get("sport") or {}
            opponent = event.get("opponent") or {}
            schedule = event.get("schedule") or {}
            media = event.get("media") or {}
            facility = event.get("game_facility") or {}

            sport_title = sport.get("title", "")
            opponent_name = opponent.get("name", "")
            home_away = event.get("location_indicator", "")  # H/A/N

            # Build a readable title: "Softball vs MSU Denver" or "at Colorado Mines"
            show_at_vs = sport.get("show_at_vs", True)
            if show_at_vs and opponent_name:
                prefix = "vs" if home_away == "H" else ("at" if home_away == "A" else "vs")
                title = f"{sport_title} {prefix} {opponent_name}"
            else:
                title = f"{sport_title}: {opponent_name}" if opponent_name else sport_title

            tournament = event.get("tournament")
            if tournament:
                title = f"{title} ({tournament})"

            start_dt = event.get("date_utc") or event.get("date", "")
            location = event.get("location", "")
            if facility.get("title"):
                location = facility["title"] + (f", {location}" if location else "")

            records.append(
                {
                    "game_id": event["id"],
                    "url": schedule.get("url") or SOURCE_URL,
                    "title": title,
                    "slug": make_slug(title),
                    "sport": sport_title,
                    "sport_shortname": sport.get("shortname", ""),
                    "opponent": opponent_name,
                    "home_away": home_away,
                    "is_conference": event.get("is_conference", False),
                    "start_dt": start_dt,
                    "time": event.get("time", ""),
                    "tbd": event.get("tbd", False),
                    "location": location,
                    "conference": event.get("conference", ""),
                    "status": event.get("status", ""),
                    "video_url": media.get("video", ""),
                    "stats_url": media.get("stats", ""),
                    "tickets_url": media.get("tickets", ""),
                    "result_team": (event.get("result") or {}).get("team_score"),
                    "result_opp": (event.get("result") or {}).get("opponent_score"),
                    "record_type": "event",
                    "source_label": "BHSU Athletics",
                }
            )

        try:
            resp = net.get(TICKET_SHOP, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
            resp.raise_for_status()
            shop = shop_events(resp.text)
        except Exception as exc:  # noqa: BLE001 — the schedule matters more than the ticket links
            print(f"[{self.slug}] couldn't read the ticket shop: {exc}")
            shop = []
        for r in records:
            if r["home_away"] == "H" and (url := ticket_url(r, shop)):
                r["tickets_url"] = url

        return records

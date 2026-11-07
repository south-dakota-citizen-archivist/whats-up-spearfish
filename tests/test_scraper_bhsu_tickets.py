"""BHSU home games: a link to buy tickets to that game, from the university's ticket shop."""

from __future__ import annotations

import json

from scrapers.sources.bhsu_athletics import TICKET_SHOP, shop_events, ticket_url
from sitegen.events import home_tickets


def _shop(*events) -> str:
    data = {"props": {"pageProps": {"sellerPage": {"events": list(events)}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def _ev(name, start, url, kind="SINGLE"):
    return {"name": name, "start": start, "url": url, "eventType": kind}


SHOP = _shop(
    _ev("Football Season Pass", "2026-09-01T19:00:00.000Z", "football-season-pass-9aozj7", kind="GROUP"),
    _ev("BHSU Football vs. Chadron State - 11/7", "2026-11-07T20:00:00.000Z", "football-chadron-a8o9bc"),
    # 5 PM Mountain on the 3rd is the 4th in UTC
    _ev("Women's & Men's Basketball vs Western Colorado 12/3", "2026-12-04T00:00:00.000Z", "doubleheader-v2ip45"),
    _ev("Women's Basketball vs Nebraska Wesleyan 12/19", "2026-12-19T18:00:00.000Z", "wbb-nwu-k0mg87"),
    _ev("Men's Basketball vs Dickinson State 12/19", "2026-12-19T21:00:00.000Z", "mbb-dsu-x1"),
)


def _game(sport, opponent, start_dt):
    return {"sport": sport, "opponent": opponent, "start_dt": start_dt, "home_away": "H"}


def test_shop_events_leave_out_season_passes_and_use_mountain_dates():
    events = shop_events(SHOP)
    assert [e["date"] for e in events] == ["2026-11-07", "2026-12-03", "2026-12-19", "2026-12-19"]
    assert events[0]["url"] == TICKET_SHOP + "event/football-chadron-a8o9bc"
    assert shop_events("<html>no data</html>") == []


def test_games_match_their_day_sport_and_team():
    events = shop_events(SHOP)
    url = lambda *a: ticket_url(_game(*a), events).rsplit("/", 1)[-1]  # noqa: E731
    assert url("Football", "Chadron State", "2026-11-07T20:00:00Z") == "football-chadron-a8o9bc"
    # a doubleheader: one ticket for both games
    assert url("Women's Basketball", "Western Colorado", "2026-12-04T00:00:00Z") == "doubleheader-v2ip45"
    assert url("Men's Basketball", "Western Colorado", "2026-12-04T02:00:00Z") == "doubleheader-v2ip45"
    # two events that day: the men's game gets the men's ticket
    assert url("Men's Basketball", "Dickinson State", "2026-12-19T21:00:00Z") == "mbb-dsu-x1"
    assert url("Women's Basketball", "Nebraska Wesleyan", "2026-12-19T18:00:00Z") == "wbb-nwu-k0mg87"
    # no event for that sport that day
    assert ticket_url(_game("Women's Volleyball", "Chadron State", "2026-11-07T18:00:00Z"), events) == ""


def test_only_home_games_show_tickets():
    assert home_tickets({"tickets_url": "https://t/1", "home_away": "H"}) == "https://t/1"
    assert home_tickets({"tickets_url": "https://t/2", "home_away": "A"}) == ""
    assert home_tickets({"tickets_url": "https://t/3"}) == "https://t/3"  # sources without home/away
    assert home_tickets({"home_away": "H"}) == ""

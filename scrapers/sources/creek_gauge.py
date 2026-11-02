"""
scrapers/sources/creek_gauge.py

USGS stream gauge for Spearfish Creek at Spearfish (site 06431500): current
flow and gauge height, ~hourly values for the last 7 days and daily means for
the last 30.

From the USGS Water Data API (api.waterdata.usgs.gov, OGC API – Features), which
replaces the legacy waterservices.usgs.gov service. Its answers aren't in time
order and its times are UTC; both are handled here.
"""

from __future__ import annotations

from scrapers import dates, net
from scrapers.base import BaseScraper

SITE = "06431500"
API = "https://api.waterdata.usgs.gov/ogcapi/v0/collections"
FLOW, HEIGHT = "00060", "00065"  # discharge (ft³/s), gauge height (ft)
DAILY_MEAN = "00003"


def _items(collection: str, **params) -> list[dict]:
    """Every feature's properties, following "next" links until the end."""
    url = f"{API}/{collection}/items"
    params = {"monitoring_location_id": f"USGS-{SITE}", "f": "json", "limit": 10000, **params}
    out = []
    while url:
        resp = net.get(url, params=params, headers={"Cache-Control": "no-cache"}, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        out += [f["properties"] for f in data.get("features", [])]
        url = next((link["href"] for link in data.get("links", []) if link.get("rel") == "next"), None)
        params = None  # the next link carries its own query
    return out


def readings(items: list[dict]) -> list[tuple[str, float]]:
    """(time, value) pairs in time order, skipping missing values."""
    pairs = []
    for p in items:
        try:
            pairs.append((p["time"], float(p["value"])))
        except (KeyError, TypeError, ValueError):
            continue
    return sorted(pairs)


def local_time(t: str) -> str:
    return dates.parse(t).astimezone(dates.MT).isoformat()


class CreekGauge(BaseScraper):
    name = "Spearfish Creek gauge (USGS)"
    slug = "creek_gauge"
    kind = "gauge"
    url = f"https://waterdata.usgs.gov/monitoring-location/USGS-{SITE}/"
    tier = "frequent"
    max_stale_hours = 12

    def scrape(self) -> dict:
        flow = readings(_items("continuous", parameter_code=FLOW, time="P7D"))
        height = readings(_items("continuous", parameter_code=HEIGHT, time="P1D"))
        daily = readings(_items("daily", parameter_code=FLOW, statistic_id=DAILY_MEAN, time="P30D"))
        return build_payload(flow, height, daily)

    def is_empty(self, payload: dict) -> bool:
        return not payload.get("current")


def build_payload(flow, height, daily) -> dict:
    current: dict = {}
    if flow:
        t, cfs = flow[-1]
        current = {"cfs": round(cfs), "ft": round(height[-1][1], 2) if height else None, "time": local_time(t)}
    return {
        "current": current,
        # 15-minute readings → about hourly
        "series7d": [{"t": local_time(t), "cfs": round(v)} for t, v in flow[::4]],
        "daily30": [{"date": t[:10], "cfs": round(v)} for t, v in daily],
    }

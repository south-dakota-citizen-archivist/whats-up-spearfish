"""
scrapers/sources/creek_gauge.py

USGS stream gauge for Spearfish Creek at Spearfish (site 06431500): current
flow and gauge height, ~hourly values for the last 7 days and daily means for
the last 30.
"""

from __future__ import annotations

from scrapers import net
from scrapers.base import BaseScraper

SITE = "06431500"
IV_URL = f"https://waterservices.usgs.gov/nwis/iv/?sites={SITE}&parameterCd=00060,00065&period=P7D&format=json"
DV_URL = f"https://waterservices.usgs.gov/nwis/dv/?sites={SITE}&parameterCd=00060&period=P30D&format=json"


def _get(url: str) -> dict:
    resp = net.get(url, headers={"Cache-Control": "no-cache"}, timeout=20)
    resp.raise_for_status()
    return resp.json()


def _values(series: dict | None) -> list[dict]:
    vals = ((series or {}).get("values") or [{}])[0].get("value", [])
    return [v for v in vals if float(v["value"]) > -999]


class CreekGauge(BaseScraper):
    name = "Spearfish Creek gauge (USGS)"
    slug = "creek_gauge"
    kind = "gauge"
    url = f"https://waterdata.usgs.gov/monitoring-location/{SITE}/"
    tier = "frequent"
    max_stale_hours = 12

    def scrape(self) -> dict:
        iv = _get(IV_URL)
        dv = _get(DV_URL)

        iv_ts = iv.get("value", {}).get("timeSeries", [])

        def by_code(code):
            return next((t for t in iv_ts if t["variable"]["variableCode"][0]["value"] == code), None)

        cfs_vals = _values(by_code("00060"))
        ft_vals = _values(by_code("00065"))

        current: dict = {}
        if cfs_vals:
            last = cfs_vals[-1]
            current = {
                "cfs": round(float(last["value"])),
                "ft": round(float(ft_vals[-1]["value"]), 2) if ft_vals else None,
                "time": last["dateTime"],
            }

        # 15-minute data → roughly hourly
        series7d = [{"t": v["dateTime"], "cfs": round(float(v["value"]))} for v in cfs_vals[::4]]

        dv_series = (dv.get("value", {}).get("timeSeries") or [{}])[0]
        daily30 = [{"date": v["dateTime"][:10], "cfs": round(float(v["value"]))} for v in _values(dv_series)]

        return {"current": current, "series7d": series7d, "daily30": daily30}

    def is_empty(self, payload: dict) -> bool:
        return not payload.get("current")

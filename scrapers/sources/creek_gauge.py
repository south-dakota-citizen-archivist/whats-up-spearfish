"""
scrapers/sources/creek_gauge.py

Fetches USGS stream gauge data for Spearfish Creek (site 06431500) and writes
a snapshot to data/creek_gauge.json.

Not a BaseScraper subclass — this scraper is intentionally excluded from the
main scrape run and is invoked directly by the creek-gauge GitHub Action.

Usage:
    uv run python -c "from scrapers.sources.creek_gauge import CreekGaugeScraper; CreekGaugeScraper().run()"
"""

from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "creek_gauge.json"

HEADERS = {"User-Agent": "SpearfishBulletin/1.0"}

IV_URL = (
    "https://waterservices.usgs.gov/nwis/iv/"
    "?sites=06431500&parameterCd=00060,00065&period=P7D&format=json"
)
DV_URL = (
    "https://waterservices.usgs.gov/nwis/dv/"
    "?sites=06431500&parameterCd=00060&period=P30D&format=json"
)


def _get(url: str) -> dict:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


class CreekGaugeScraper:
    name = "Creek Gauge (USGS 06431500)"

    def fetch(self) -> dict:
        """Fetch current + 7-day IV + 30-day DV data. Returns {} on failure."""
        try:
            iv = _get(IV_URL)
            dv = _get(DV_URL)
        except Exception as exc:
            print(f"[{self.name}] Warning: fetch failed: {exc}")
            return {}

        iv_ts = iv.get("value", {}).get("timeSeries", [])
        cfs_series = next(
            (t for t in iv_ts if t["variable"]["variableCode"][0]["value"] == "00060"), None
        )
        ft_series = next(
            (t for t in iv_ts if t["variable"]["variableCode"][0]["value"] == "00065"), None
        )

        cfs_vals = [
            v for v in (cfs_series or {}).get("values", [{}])[0].get("value", [])
            if float(v["value"]) > -999
        ]
        ft_vals = [
            v for v in (ft_series or {}).get("values", [{}])[0].get("value", [])
            if float(v["value"]) > -999
        ]

        current: dict = {}
        if cfs_vals:
            last = cfs_vals[-1]
            current = {
                "cfs":  round(float(last["value"])),
                "ft":   round(float(ft_vals[-1]["value"]), 2) if ft_vals else None,
                "time": last["dateTime"],
            }

        # Downsample to ~hourly (15-min data → every 4th point)
        series7d = [
            {"t": v["dateTime"], "cfs": round(float(v["value"]))}
            for v in cfs_vals[::4]
        ]

        dv_vals = (
            (dv.get("value", {}).get("timeSeries") or [{}])[0]
            .get("values", [{}])[0]
            .get("value", [])
        )
        daily30 = [
            {"date": v["dateTime"][:10], "cfs": round(float(v["value"]))}
            for v in reversed(dv_vals)
            if float(v["value"]) > -999
        ]

        fetched_at = datetime.now(timezone.utc).isoformat()
        return {"current": current, "series7d": series7d, "daily30": daily30, "fetched_at": fetched_at}

    def run(self) -> None:
        data = self.fetch()
        if not data:
            print(f"[{self.name}] No data fetched — leaving existing file unchanged.")
            return
        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        DATA_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        current = data.get("current", {})
        print(
            f"[{self.name}] {current.get('cfs', 'n/a')} cfs, "
            f"{len(data.get('series7d', []))} IV points, "
            f"{len(data.get('daily30', []))} daily values → {DATA_FILE.name}"
        )

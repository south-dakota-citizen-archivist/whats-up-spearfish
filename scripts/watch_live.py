"""
scripts/watch_live.py

Watch a City of Spearfish meeting's live-stream status in CivicClerk, to check the
"is it streaming right now?" signal is real before the site relies on it.

Every 30 seconds it reads the two places the city's portal gets that from:

  Events/{id}        isLive, liveIsCurrentlyStreaming, streamingStatus, liveStartTime, liveEndTime
  EventsMedia/{id}   isLiveStreaming, streamingStatus (the portal's player: 2 = streaming, 1 = paused)

and writes each reading to .cache/live-watch/{id}.jsonl, printing a line whenever
anything changes. It starts reading LEAD minutes before the meeting (waiting until
then if it's early) and stops once the stream has ended and stayed ended for a
while, or after MAX_HOURS.

    uv run python -m scripts.watch_live              # today's city meetings that stream
    uv run python -m scripts.watch_live 2198         # one meeting, by its CivicClerk event id
    uv run python -m scripts.watch_live 2198 --now   # start reading right away

Upcoming (as of Nov 4, 2026): 2198 City Council Study Session, Thu Nov 12, 4:15 PM;
2165 City Council Meeting, Mon Nov 16, 5:30 PM.

CivicClerk's times are Spearfish clock times marked as UTC ('…T16:15:00Z' is 4:15 PM).
Only the status fields are kept, never file or video URLs.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from scrapers import dates, net

API = "https://spearfishsd.api.civicclerk.com/v1"
EVERY = 30  # seconds between readings
LEAD = timedelta(minutes=20)  # start reading this long before the meeting
DONE_AFTER = timedelta(minutes=15)  # stop once the stream has been over this long
MAX_HOURS = 5
OUT = Path(__file__).resolve().parent.parent / ".cache" / "live-watch"

EVENT_FIELDS = ("isLive", "liveIsCurrentlyStreaming", "streamingStatus", "liveStartTime", "liveEndTime", "hasMedia")
MEDIA_FIELDS = ("isLiveStreaming", "streamingStatus")


def _get(path: str) -> dict:
    resp = net.get(f"{API}/{path}", headers={"Accept": "application/json"}, timeout=30)
    resp.raise_for_status()
    return resp.json()


def local(value: str) -> datetime:
    """A CivicClerk time ('2026-11-12T16:15:00Z', really Spearfish clock time) as an aware Mountain datetime."""
    return datetime.fromisoformat(value.rstrip("Z").split("+")[0]).replace(tzinfo=dates.MT)


def reading(event_id: int) -> dict:
    ev, media = _get(f"Events/{event_id}"), _get(f"EventsMedia/{event_id}")
    return {
        **{f"event.{k}": ev.get(k) for k in EVENT_FIELDS},
        **{f"media.{k}": media.get(k) for k in MEDIA_FIELDS},
        "media.has_video": bool(media.get("videoUrl")),
    }


def todays_meetings() -> list[dict]:
    today = dates.today().isoformat()
    events = _get("Events?$orderby=startDateTime desc").get("value", [])
    events += _get("Events?$orderby=startDateTime desc&$skip=15").get("value", [])
    # any with media: a meeting with a Zoom link may stream in CivicClerk too (council meetings do)
    return [e for e in events if e["startDateTime"][:10] == today and e.get("hasMedia")]


def watch(event_id: int, start_now: bool = False) -> None:
    ev = _get(f"Events/{event_id}")
    name, starts = ev.get("eventName", ""), local(ev["startDateTime"])
    print(f"{event_id}: {name}, {starts:%a %b %-d, %-I:%M %p}")
    begin = starts - LEAD
    if not start_now and dates.now() < begin:
        wait = (begin - dates.now()).total_seconds()
        print(f"  waiting until {begin:%-I:%M %p} ({wait / 60:.0f} min)")
        time.sleep(wait)

    OUT.mkdir(parents=True, exist_ok=True)
    log = OUT / f"{event_id}.jsonl"
    print(f"  reading every {EVERY}s → {log}")
    last, ended_at, stop_at = None, None, dates.now() + timedelta(hours=MAX_HOURS)
    while dates.now() < stop_at:
        now = dates.now()
        try:
            r = reading(event_id)
        except Exception as exc:  # noqa: BLE001 — note it and keep watching
            r = {"error": f"{type(exc).__name__}: {exc}"}
        with log.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({"at": now.isoformat(timespec="seconds"), **r}) + "\n")
        if r != last:
            changed = {k: v for k, v in r.items() if not last or last.get(k) != v}
            print(f"  {now:%-I:%M:%S %p}  {changed}", flush=True)
            last = r
        streaming = r.get("media.isLiveStreaming") or r.get("event.liveIsCurrentlyStreaming") or r.get("event.isLive")
        if streaming:
            ended_at = None
        elif (r.get("event.liveEndTime") or "").startswith(starts.strftime("%Y-%m-%d")) and now > starts:
            ended_at = ended_at or now  # the stream has a recorded end today
            if now - ended_at > DONE_AFTER:
                print(f"  stream over (ended {r['event.liveEndTime'][11:16]}); done")
                return
        time.sleep(EVERY)
    print("  stopped after the time limit")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[1], formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "event", nargs="*", type=int, help="CivicClerk event id(s); default: today's streamed city meetings"
    )
    ap.add_argument("--now", action="store_true", help="start reading right away, however early")
    args = ap.parse_args(argv)
    ids = args.event or [e["id"] for e in todays_meetings()]
    if not ids:
        sys.exit("No city meetings streaming in CivicClerk today. Give an event id to watch one.")
    for event_id in sorted(ids, key=lambda i: local(_get(f"Events/{i}")["startDateTime"])):
        watch(event_id, start_now=args.now)


if __name__ == "__main__":
    main()

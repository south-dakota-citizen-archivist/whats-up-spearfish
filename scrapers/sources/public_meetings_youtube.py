"""
scrapers/sources/public_meetings_youtube.py

YouTube videos from Spearfish-area public body channels.
Uses the public YouTube Atom RSS feed — no API key required.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

import requests

from scrapers.base import BaseScraper

SOURCES = [
    {
        "name": "Spearfish School District",
        "handle": "spearfishschooldistrictliv3794",
        "channel_url": "https://www.youtube.com/@spearfishschooldistrictliv3794/streams",
    },
    {
        "name": "Lawrence County",
        "channel_id": "UC2CZKGr9OGrsMcCZkW0_HMA",
        "channel_url": "https://www.youtube.com/channel/UC2CZKGr9OGrsMcCZkW0_HMA",
    },
]

FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt":   "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}


def _resolve_channel_id(handle: str) -> str | None:
    """Extract channel ID from a YouTube @handle page."""
    url = f"https://www.youtube.com/@{handle}"
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
        m = re.search(r'"channelId"\s*:\s*"(UC[^"]+)"', resp.text)
        if not m:
            m = re.search(r'"externalId"\s*:\s*"(UC[^"]+)"', resp.text)
        return m.group(1) if m else None
    except requests.RequestException as exc:
        print(f"[YouTube] Warning: could not resolve @{handle}: {exc}")
        return None


def _fetch_feed(channel_id: str, source_name: str, channel_url: str, n: int = 15) -> list[dict]:
    """Parse the YouTube Atom feed for a channel, return up to n records."""
    url = FEED_URL.format(channel_id=channel_id)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[YouTube] Warning: feed fetch failed for {source_name}: {exc}")
        return []

    try:
        root = ET.fromstring(resp.content)
    except ET.ParseError as exc:
        print(f"[YouTube] Warning: feed parse failed for {source_name}: {exc}")
        return []

    records = []
    for entry in root.findall("atom:entry", _NS)[:n]:
        video_id_el = entry.find("yt:videoId", _NS)
        title_el    = entry.find("atom:title", _NS)
        link_el     = entry.find("atom:link[@rel='alternate']", _NS)
        pub_el      = entry.find("atom:published", _NS)
        media_group = entry.find("media:group", _NS)
        thumb_el    = media_group.find("media:thumbnail", _NS) if media_group is not None else None

        video_id = video_id_el.text if video_id_el is not None else None
        if not video_id:
            continue

        title = (title_el.text or "").strip() if title_el is not None else ""
        if not title:
            continue

        video_url = (
            link_el.get("href")
            if link_el is not None
            else f"https://www.youtube.com/watch?v={video_id}"
        )
        published = (pub_el.text or "")[:10] if pub_el is not None else ""
        thumbnail = thumb_el.get("url", "") if thumb_el is not None else ""

        records.append({
            "url":          video_url,
            "title":        title,
            "published":    published,
            "thumbnail_url": thumbnail,
            "source_label": source_name,
            "channel_url":  channel_url,
            "record_type":  "youtube_video",
        })

    return records


class PublicMeetingsYouTube(BaseScraper):
    name = "Public Meetings (YouTube)"
    slug = "public_meetings_youtube"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        records = []
        for src in SOURCES:
            channel_id = src.get("channel_id")
            if not channel_id:
                channel_id = _resolve_channel_id(src["handle"])
            if not channel_id:
                print(f"[YouTube] Warning: could not resolve channel for {src['name']}")
                continue
            items = _fetch_feed(channel_id, src["name"], src["channel_url"])
            print(f"  [YouTube/{src['name']}] {len(items)} videos")
            records.extend(items)
        return records

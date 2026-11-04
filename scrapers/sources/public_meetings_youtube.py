"""
scrapers/sources/public_meetings_youtube.py

Meeting recordings from Spearfish-area public bodies' YouTube channels, matched to
their meetings by the site (sitegen.pages.add_meeting_videos).

With YOUTUBE_API_KEY in the environment (a free YouTube Data API v3 key, public data
only), every video each channel has ever posted, finished livestreams included: the
channel's uploads playlist, 50 videos a request (1 unit each of the free 10,000 a day).
The key goes in a header, never the URL, so it can't turn up in an error message.

Without a key, the channels' RSS feeds: their latest 15 videos.
"""

from __future__ import annotations

import os
import re
import xml.etree.ElementTree as ET

import requests

from scrapers import net
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
API = "https://www.googleapis.com/youtube/v3"
NOT_VIDEOS = {"Private video", "Deleted video"}  # what a playlist shows for a video since taken down

_NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
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
        resp = net.get(url, headers=_HEADERS, timeout=20)
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
        resp = net.get(url, headers=_HEADERS, timeout=20)
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
        title_el = entry.find("atom:title", _NS)
        link_el = entry.find("atom:link[@rel='alternate']", _NS)
        pub_el = entry.find("atom:published", _NS)
        media_group = entry.find("media:group", _NS)
        thumb_el = media_group.find("media:thumbnail", _NS) if media_group is not None else None

        video_id = video_id_el.text if video_id_el is not None else None
        if not video_id:
            continue

        title = (title_el.text or "").strip() if title_el is not None else ""
        if not title:
            continue

        video_url = link_el.get("href") if link_el is not None else f"https://www.youtube.com/watch?v={video_id}"
        published = (pub_el.text or "")[:10] if pub_el is not None else ""
        thumbnail = thumb_el.get("url", "") if thumb_el is not None else ""

        records.append(
            {
                "url": video_url,
                "title": title,
                "published": published,
                "thumbnail_url": thumbnail,
                "source_label": source_name,
                "channel_url": channel_url,
                "record_type": "youtube_video",
            }
        )

    return records


def _api(path: str, key: str, **params) -> dict:
    resp = net.get(f"{API}/{path}", params=params, headers={"X-Goog-Api-Key": key}, timeout=30)
    if resp.status_code != 200:
        # the API's own message ('quotaExceeded' …), never the request
        try:
            reason = resp.json()["error"]["errors"][0]["reason"]
        except (ValueError, KeyError, IndexError, TypeError):
            reason = ""
        raise RuntimeError(f"YouTube API {path}: HTTP {resp.status_code} {reason}".strip())
    return resp.json()


def uploads_playlist(src: dict, key: str) -> str | None:
    """A channel's playlist of everything it has posted."""
    params = {"id": src["channel_id"]} if src.get("channel_id") else {"forHandle": "@" + src["handle"]}
    items = _api("channels", key, part="contentDetails", **params).get("items") or []
    return items[0]["contentDetails"]["relatedPlaylists"]["uploads"] if items else None


def video_record(item: dict, src: dict) -> dict | None:
    """One playlistItems entry as a record ('Private video' and 'Deleted video' entries: None)."""
    sn, cd = item.get("snippet") or {}, item.get("contentDetails") or {}
    vid = cd.get("videoId") or (sn.get("resourceId") or {}).get("videoId")
    title = (sn.get("title") or "").strip()
    if not vid or not title or title in NOT_VIDEOS:
        return None
    thumbs = sn.get("thumbnails") or {}
    thumb = (thumbs.get("medium") or thumbs.get("high") or thumbs.get("default") or {}).get("url", "")
    return {
        "url": f"https://www.youtube.com/watch?v={vid}",
        "video_id": vid,
        "title": title,
        "description": (sn.get("description") or "").strip(),
        "published": (cd.get("videoPublishedAt") or sn.get("publishedAt") or "")[:10],
        "thumbnail_url": thumb,
        "source_label": src["name"],
        "channel_url": src["channel_url"],
        "record_type": "youtube_video",
    }


def channel_history(src: dict, key: str) -> list[dict]:
    playlist = uploads_playlist(src, key)
    if not playlist:
        raise RuntimeError(f"no YouTube channel found for {src['name']}")
    records, token = [], None
    while True:
        params = {"part": "snippet,contentDetails", "playlistId": playlist, "maxResults": 50}
        page = _api("playlistItems", key, **params, **({"pageToken": token} if token else {}))
        records += [r for item in page.get("items") or [] if (r := video_record(item, src))]
        token = page.get("nextPageToken")
        if not token:
            return records


class PublicMeetingsYouTube(BaseScraper):
    name = "Public Meetings (YouTube)"
    slug = "public_meetings_youtube"
    kind = "youtube_video"
    url = "https://www.youtube.com/@spearfishschooldistrictliv3794/streams"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        key = os.environ.get("YOUTUBE_API_KEY", "").strip()
        # the API gives each channel's whole history, so the list is replaced; the feeds give
        # only the latest videos, so what's already saved is kept
        self.replace = bool(key)
        records = []
        for src in SOURCES:
            if key:
                items = channel_history(src, key)
            else:
                channel_id = src.get("channel_id") or _resolve_channel_id(src["handle"])
                if not channel_id:
                    print(f"[YouTube] Warning: could not resolve channel for {src['name']}")
                    continue
                items = _fetch_feed(channel_id, src["name"], src["channel_url"])
            print(f"  [YouTube/{src['name']}] {len(items)} videos")
            records.extend(items)
        return records

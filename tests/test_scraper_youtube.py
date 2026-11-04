"""Meeting recordings on YouTube: the whole history through the API, or the latest through RSS."""

from __future__ import annotations

import pytest

from scrapers.sources import public_meetings_youtube as yt

SRC = {"name": "Lawrence County", "channel_id": "UC2CZ", "channel_url": "https://www.youtube.com/channel/UC2CZ"}


class Resp:
    def __init__(self, body, status=200):
        self.body, self.status_code = body, status

    def json(self):
        return self.body


def _item(vid, title, when="2026-10-27T20:00:00Z"):
    return {"snippet": {"title": title, "description": "Agenda at …", "publishedAt": "2026-10-30T00:00:00Z",
                        "thumbnails": {"medium": {"url": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg"}}},
            "contentDetails": {"videoId": vid, "videoPublishedAt": when}}  # fmt: skip


def test_whole_history_pages_through_the_uploads_playlist(monkeypatch):
    calls = []

    def fake_get(url, params=None, headers=None, **kw):
        calls.append((url.rsplit("/", 1)[-1], dict(params), headers))
        if url.endswith("/channels"):
            return Resp({"items": [{"contentDetails": {"relatedPlaylists": {"uploads": "UU2CZ"}}}]})
        if params.get("pageToken") is None:
            return Resp({"items": [_item("a", "Commission Meeting - October 27, 2026"), _item("x", "Private video")],
                         "nextPageToken": "p2"})  # fmt: skip
        return Resp({"items": [_item("b", "Planning & Zoning Meeting - October 1, 2026", "2026-10-06T15:00:00Z")]})

    monkeypatch.setattr(yt.net, "get", fake_get)
    records = yt.channel_history(SRC, "SECRET")
    assert [r["url"] for r in records] == ["https://www.youtube.com/watch?v=a", "https://www.youtube.com/watch?v=b"]
    assert records[0]["published"] == "2026-10-27" and records[0]["source_label"] == "Lawrence County"
    assert [c[0] for c in calls] == ["channels", "playlistItems", "playlistItems"]
    assert calls[0][1] == {"part": "contentDetails", "id": "UC2CZ"}
    # the key travels in a header, never in the URL's query
    assert all(c[2] == {"X-Goog-Api-Key": "SECRET"} and "SECRET" not in str(c[1]) for c in calls)


def test_an_api_error_names_the_reason_not_the_request(monkeypatch):
    body = {"error": {"errors": [{"reason": "quotaExceeded"}]}}
    monkeypatch.setattr(yt.net, "get", lambda *a, **kw: Resp(body, status=403))
    with pytest.raises(RuntimeError) as err:
        yt.channel_history(SRC, "SECRET")
    assert "quotaExceeded" in str(err.value) and "SECRET" not in str(err.value)


def test_with_a_key_the_list_is_replaced_without_one_kept(monkeypatch):
    scraper = yt.PublicMeetingsYouTube()
    monkeypatch.setattr(yt, "channel_history", lambda src, key: [])
    monkeypatch.setenv("YOUTUBE_API_KEY", "SECRET")
    scraper.scrape()
    assert scraper.replace is True
    monkeypatch.delenv("YOUTUBE_API_KEY")
    monkeypatch.setattr(yt, "_fetch_feed", lambda *a, **kw: [])
    monkeypatch.setattr(yt, "_resolve_channel_id", lambda handle: "UCx")
    scraper.scrape()
    assert scraper.replace is False

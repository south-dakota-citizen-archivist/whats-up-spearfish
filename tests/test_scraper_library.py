"""
tests/test_scraper_library.py

New books: covers Amazon doesn't actually have (it answers with a 1-pixel GIF)
are dropped, so the site can show only books with real covers.
"""

from __future__ import annotations

from scrapers.sources import spearfish_library as lib


class Resp:
    def __init__(self, size, ok=True):
        self.content = b"x" * size
        self.ok = ok


def test_missing_covers_dropped(monkeypatch):
    asked = []

    def get(url, **kw):
        asked.append(url)
        if "0000000000" in url:
            return Resp(43)  # Amazon's "no image" stub
        if "unreachable" in url:
            raise ConnectionError(url)
        return Resp(6000)

    monkeypatch.setattr(lib.net, "get", get)
    books = [
        {"image_url": "https://images-na.ssl-images-amazon.com/images/P/0767848853.01.LZZZZZZZ.jpg"},
        {"image_url": "https://images-na.ssl-images-amazon.com/images/P/0000000000.01.LZZZZZZZ.jpg"},
        {"image_url": "https://unreachable.example.com/cover.jpg"},
        {"image_url": ""},
    ]
    lib.drop_missing_covers(books)
    assert [bool(b["image_url"]) for b in books] == [True, False, True, False]
    assert all(".MZZZZZZZ." in u for u in asked if "amazon" in u)  # probes the small size

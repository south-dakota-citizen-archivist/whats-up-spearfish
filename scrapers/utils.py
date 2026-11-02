"""
scrapers/utils.py

Shared helpers used by scrapers: HTTP fetching, date parsing, slugification,
and data-directory management.
"""

from __future__ import annotations

import feedparser
from bs4 import BeautifulSoup
from slugify import slugify

from scrapers import net

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
from scrapers.base import DATA_DIR  # noqa: E402,F401

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def fetch_feed(url: str, **kwargs) -> feedparser.FeedParserDict:
    """
    GET an RSS/Atom feed and parse it. Unlike ``feedparser.parse(url)``, which
    turns a timeout or an error page into an empty feed, a failed fetch raises,
    so the source is recorded as failing instead of "ok, 0 items".
    """
    kwargs.setdefault("timeout", 30)
    response = net.get(url, **kwargs)
    response.raise_for_status()
    feed = feedparser.parse(response.content)
    if not feed.get("version") and not feed.entries:  # an HTML error or block page, not RSS/Atom
        raise ValueError(f"not a feed: {url}")
    return feed


def fetch_html(url: str, **kwargs) -> BeautifulSoup:
    """
    GET *url* and return a BeautifulSoup object.

    Any keyword arguments are forwarded to ``net.get()``.  A
    ``timeout`` of 30 seconds is applied by default.
    """
    kwargs.setdefault("timeout", 30)
    response = net.get(url, **kwargs)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------


def make_slug(s: str) -> str:
    """Return a URL-safe slug for *s* using python-slugify."""
    return slugify(s, max_length=80, word_boundary=True)

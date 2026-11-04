"""
scrapers/utils.py

Shared helpers used by scrapers: HTTP fetching, date parsing, slugification,
and data-directory management.
"""

from __future__ import annotations

import re

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


# ── a meeting's start time, from its agenda ─────────────────────────────────

_CLOCK = r"(\d{1,2})(?::(\d{2}))?\s*([AaPp])\.?\s*[Mm]\b\.?"
_AT_CLOCK = re.compile(r"@\s*" + _CLOCK)  # 'Tuesday, October 13, 2026 @ 5:30 PM'
_ANY_CLOCK = re.compile(r"\b" + _CLOCK)


def agenda_start_time(text: str) -> str:
    """
    The start time an agenda's first page gives, as 'HH:MM' (24-hour): the time after '@'
    if there is one ('November 5, 2026 @ 1:30 p.m.'), else the first time near the top.
    """
    m = _AT_CLOCK.search(text or "") or _ANY_CLOCK.search((text or "")[:600])
    if not m:
        return ""
    hour, minute, half = int(m.group(1)), int(m.group(2) or 0), m.group(3).lower()
    if not (1 <= hour <= 12 and minute < 60):
        return ""
    return f"{hour % 12 + (12 if half == 'p' else 0):02d}:{minute:02d}"


_JOIN = re.compile(
    r"https?://(?:[\w-]+\.)*(?:zoom\.us|zoomgov\.com|goto\.com|gotomeeting\.com|teams\.microsoft\.com|teams\.live\.com"
    r"|webex\.com|meet\.google\.com)/[^\s<>()\"']+",
    re.I,
)


def agenda_join_url(text: str) -> str:
    """A link to take part online that an agenda gives ('https://meet.goto.com/lawrencecountypz'), or ''."""
    m = _JOIN.search(text or "")
    return m.group(0).rstrip(".,;") if m else ""


_PHONE = r"(\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})"
_DIAL = re.compile(r"(?:dial|call|phone|by telephone)[^\d+]{0,40}?" + _PHONE, re.I)
_CODE = re.compile(
    r"(?:access code|meeting id|meeting number|passcode|conference id|participant code|pin)"
    r"\s*[:#]?\s*(\d[\d\s-]{2,18}\d)",
    re.I,
)


def agenda_dial_in(text: str) -> dict:
    """A phone number to call in on and its code, as the agenda gives them: {'phone': …, 'code': …}, or {}."""
    m = _DIAL.search(text or "")
    if not m:
        return {}
    code = _CODE.search(text[m.start() : m.end() + 120]) or _CODE.search(text)
    return {"phone": " ".join(m.group(1).split()), "code": " ".join(code.group(1).split()) if code else ""}


def agenda_details(url: str) -> dict:
    """From an agenda PDF online, what its first page says: {'start_time': 'HH:MM', 'join_url': …} ('' if not)."""
    import io

    import pdfplumber

    try:
        resp = net.get(url, timeout=60)
        resp.raise_for_status()
        if not resp.content.startswith(b"%PDF"):
            return {}
        with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
            text = (pdf.pages[0].extract_text() or "") if pdf.pages else ""
    except Exception as exc:  # noqa: BLE001 — the meeting still lists without them
        print(f"[agenda] couldn't read {url}: {exc}")
        return {}
    return {"start_time": agenda_start_time(text), "join_url": agenda_join_url(text), "dial_in": agenda_dial_in(text)}

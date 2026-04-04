"""
scrapers/utils.py

Shared helpers used by scrapers: HTTP fetching, date parsing, slugification,
and data-directory management.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

import requests
from bs4 import BeautifulSoup
from slugify import slugify

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

DATA_DIR = Path(__file__).resolve().parent.parent / "data"

# Common user-agent to avoid trivial blocks.
DEFAULT_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (compatible; SpearfishBulletinBot/1.0; +https://github.com/spearfish-bulletin)")
}

# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


def fetch_html(url: str, **kwargs) -> BeautifulSoup:
    """
    GET *url* and return a BeautifulSoup object.

    Any keyword arguments are forwarded to ``requests.get()``.  A
    ``timeout`` of 30 seconds is applied by default.
    """
    kwargs.setdefault("timeout", 30)
    kwargs.setdefault("headers", DEFAULT_HEADERS)
    response = requests.get(url, **kwargs)
    response.raise_for_status()
    return BeautifulSoup(response.text, "html.parser")


def fetch_json(url: str, **kwargs) -> Any:
    """
    GET *url* and return the parsed JSON body (dict or list).

    Any keyword arguments are forwarded to ``requests.get()``.  A
    ``timeout`` of 30 seconds is applied by default.
    """
    kwargs.setdefault("timeout", 30)
    kwargs.setdefault("headers", DEFAULT_HEADERS)
    response = requests.get(url, **kwargs)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Date parsing
# ---------------------------------------------------------------------------

# Ordered list of formats to try, most-specific first.
_DATE_FORMATS: list[str] = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M:%SZ",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d",
    "%m/%d/%Y %I:%M %p",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y",
    "%B %d, %Y %I:%M %p",
    "%B %d, %Y",
    "%b %d, %Y",
    "%b. %d, %Y",
    "%d %B %Y",
    "%A, %B %d, %Y",
]


def parse_date(s: str | None) -> str | None:
    """
    Try to parse *s* as a date/datetime using common formats.

    Returns an ISO-8601 string (``"YYYY-MM-DD"`` or ``"YYYY-MM-DDTHH:MM:SS"``)
    on success, or ``None`` if the string cannot be parsed.
    """
    if not s:
        return None

    # Normalise whitespace.
    s = re.sub(r"\s+", " ", s.strip())

    for fmt in _DATE_FORMATS:
        try:
            dt = datetime.strptime(s, fmt)
            if dt.hour == 0 and dt.minute == 0 and dt.second == 0:
                return dt.date().isoformat()
            return dt.isoformat()
        except ValueError:
            continue

    return None


# ---------------------------------------------------------------------------
# Slug helper
# ---------------------------------------------------------------------------


def make_slug(s: str) -> str:
    """Return a URL-safe slug for *s* using python-slugify."""
    return slugify(s, max_length=80, word_boundary=True)


# ---------------------------------------------------------------------------
# Filesystem helpers
# ---------------------------------------------------------------------------


def ensure_data_dir() -> Path:
    """Create the data/ directory if it does not already exist."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    return DATA_DIR

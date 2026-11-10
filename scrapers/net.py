"""
scrapers/net.py

Shared HTTP for every scraper, on sdfetch:

- default browser headers (sdfetch.BROWSER_HEADERS)
- retries with backoff, honoring Retry-After on 429/503
- a pause between requests to the same host, shared by every thread
- a curl_cffi fallback when a response isn't the page (sdfetch.Blocked, a RequestException,
  if that fails too)

Responses come back for the caller to check (raise_errors=False). Sources that need a
browser use sdfetch directly (see sources/spearfish_library.py).

Usage:
    from scrapers import net

    resp = net.get(url, params={...})
    resp.raise_for_status()
"""

from __future__ import annotations

import threading

import requests
import sdfetch

CHROME = sdfetch.CHROME
USER_AGENT = sdfetch.USER_AGENT
DEFAULT_HEADERS = {
    **sdfetch.BROWSER_HEADERS,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
}
DEFAULT_TIMEOUT = 30

#: Minimum seconds between requests to the same host.
PER_HOST_DELAY = 0.5

_local = threading.local()


def fetcher() -> sdfetch.Fetcher:
    """This thread's sdfetch Fetcher (a requests.Session isn't thread-safe)."""
    f = getattr(_local, "fetcher", None)
    if f is None:
        f = sdfetch.Fetcher(
            max_strategy="impersonate",
            delay=PER_HOST_DELAY,
            timeout=DEFAULT_TIMEOUT,
            retries=4,
            backoff=2,  # 2s, 4s, 8s
            headers=DEFAULT_HEADERS,
            raise_errors=False,
        )
        _local.fetcher = f
    return f


def session() -> requests.Session:
    """This thread's requests session, with the browser headers (for code that needs one)."""
    return fetcher().session


def request(method: str, url: str, **kwargs):
    return fetcher().request(method, url, **kwargs)


def get(url: str, **kwargs):
    return request("GET", url, **kwargs)


def post(url: str, **kwargs):
    return request("POST", url, **kwargs)

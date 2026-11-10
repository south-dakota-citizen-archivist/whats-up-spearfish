"""
scrapers/net.py

Shared HTTP for every scraper, on sdfetch (south-dakota-citizen-archivist/sd-archive,
packages/sdfetch):

- every request looks like desktop Chrome on a Mac (sdfetch.BROWSER_HEADERS)
- retries with backoff, honoring Retry-After on 429/503
- a pause between requests to the same host, shared by every thread
- block-page detection: a site that blocks plain requests gets curl_cffi, with Chrome's
  TLS fingerprint, before the request fails (sdfetch.Blocked, a RequestException)

Responses come back for the caller to check, as before (raise_errors=False). Ordinary
sources never climb to a browser; a source that needs one uses sdfetch directly (see
sources/spearfish_library.py).

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

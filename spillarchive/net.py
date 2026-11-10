"""HTTP for spillarchive, on sdfetch: Chrome's headers, retries honoring Retry-After, a pause
between requests to a host, and curl_cffi when a server blocks plain requests."""

from __future__ import annotations

import requests
import sdfetch

USER_AGENT = sdfetch.USER_AGENT

_fetcher: sdfetch.Fetcher | None = None


def fetcher() -> sdfetch.Fetcher:
    global _fetcher
    if _fetcher is None:
        _fetcher = sdfetch.Fetcher(max_strategy="impersonate", timeout=60, retries=4, backoff=2, raise_errors=False)
    return _fetcher


def session() -> requests.Session:
    return fetcher().session


def request(method: str, url: str, delay: float = 1.0, **kwargs):
    """A request, at least `delay` seconds after the last one to that host (the state's
    servers are small). The response comes back for the caller to check."""
    f = fetcher()
    f.delay = delay
    return f.request(method, url, **kwargs)

"""
scrapers/net.py

Shared HTTP session for every scraper: browser-like headers, a default
timeout, automatic retries with exponential backoff (honoring Retry-After on
429/503), and a small per-host delay so parallel scrapers don't hammer the
same server.

Usage:
    from scrapers import net

    resp = net.get(url, params={...})
    resp.raise_for_status()
"""

from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Every request looks like desktop Chrome on a Mac: nothing names the site, the org or a bot,
# and nothing goes out as python-requests. Keep CHROME near the current stable release (a
# stale version stands out). Sources use net.USER_AGENT rather than their own.
CHROME = "157"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/{CHROME}.0.0.0 Safari/537.36"
)

DEFAULT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,application/json;q=0.8,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
    "sec-ch-ua": f'"Google Chrome";v="{CHROME}", "Chromium";v="{CHROME}", "Not_A Brand";v="24"',
    "sec-ch-ua-mobile": "?0",
    "sec-ch-ua-platform": '"macOS"',
}

DEFAULT_TIMEOUT = 30

#: Minimum seconds between requests to the same host.
PER_HOST_DELAY = 0.5

_retry = Retry(
    total=4,
    connect=3,
    read=2,
    status=4,
    backoff_factor=2,  # 0s, 2s, 4s, 8s
    status_forcelist=(429, 500, 502, 503, 504),
    allowed_methods=("GET", "HEAD", "POST"),
    respect_retry_after_header=True,
    raise_on_status=False,
)

_local = threading.local()
_host_lock = threading.Lock()
_host_last: dict[str, float] = {}


def session() -> requests.Session:
    """Return this thread's configured session (requests.Session isn't thread-safe)."""
    s = getattr(_local, "session", None)
    if s is None:
        s = requests.Session()
        s.headers.update(DEFAULT_HEADERS)
        adapter = HTTPAdapter(max_retries=_retry)
        s.mount("http://", adapter)
        s.mount("https://", adapter)
        _local.session = s
    return s


def _throttle(url: str) -> None:
    host = urlparse(url).netloc
    with _host_lock:
        wait = _host_last.get(host, 0) + PER_HOST_DELAY - time.monotonic()
        _host_last[host] = max(time.monotonic(), _host_last.get(host, 0) + PER_HOST_DELAY)
    if wait > 0:
        time.sleep(wait)


def request(method: str, url: str, **kwargs) -> requests.Response:
    kwargs.setdefault("timeout", DEFAULT_TIMEOUT)
    _throttle(url)
    return session().request(method, url, **kwargs)


def get(url: str, **kwargs) -> requests.Response:
    return request("GET", url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    return request("POST", url, **kwargs)

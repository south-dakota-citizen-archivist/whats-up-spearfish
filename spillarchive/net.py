"""HTTP for spillarchive: one session, a polite pause between requests, retries."""

from __future__ import annotations

import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

USER_AGENT = "spillarchive (South Dakota spill report archive; https://github.com/south-dakota-citizen-archivist)"

_session: requests.Session | None = None
_last = 0.0


def session() -> requests.Session:
    global _session
    if _session is None:
        s = requests.Session()
        retry = Retry(total=4, backoff_factor=2, status_forcelist=(429, 500, 502, 503, 504),
                      allowed_methods=("GET", "HEAD", "POST"), respect_retry_after_header=True)  # fmt: skip
        s.mount("https://", HTTPAdapter(max_retries=retry))
        s.mount("http://", HTTPAdapter(max_retries=retry))
        s.headers["User-Agent"] = USER_AGENT
        _session = s
    return _session


def request(method: str, url: str, delay: float = 1.0, **kwargs) -> requests.Response:
    """A request, at least `delay` seconds after the last one (the state's servers are small)."""
    global _last
    wait = _last + delay - time.monotonic()
    if wait > 0:
        time.sleep(wait)
    kwargs.setdefault("timeout", 60)
    try:
        return session().request(method, url, **kwargs)
    finally:
        _last = time.monotonic()

"""
tests/test_utils.py

Tests for scrapers/utils.py: make_slug, fetch_html, fetch_feed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
import requests

from scrapers.utils import fetch_html, make_slug


class TestMakeSlug:
    def test_basic(self):
        assert make_slug("Hello World") == "hello-world"

    def test_special_chars_removed(self):
        assert make_slug("Events & Activities!") == "events-activities"

    def test_unicode_transliterated(self):
        assert make_slug("Café") == "cafe"

    def test_numbers_preserved(self):
        assert "2026" in make_slug("Event 2026")

    def test_max_length_respected(self):
        assert len(make_slug("a" * 100)) <= 80

    def test_empty_string(self):
        assert make_slug("") == ""

    def test_source_slug_pattern(self):
        # Common usage: make_slug("SourceName-Title of Article")
        result = make_slug("Black Hills Pioneer-Some Big Story")
        assert len(result) <= 80
        assert "black" in result


class TestFetchHtml:
    def _mock_resp(self, text="<html></html>"):
        resp = MagicMock()
        resp.text = text
        resp.raise_for_status.return_value = None
        return resp

    def test_returns_beautifulsoup(self):
        from bs4 import BeautifulSoup

        with patch("scrapers.utils.net.get", return_value=self._mock_resp()):
            result = fetch_html("http://example.com")
        assert isinstance(result, BeautifulSoup)

    def test_default_timeout_30(self):
        with patch("scrapers.utils.net.get", return_value=self._mock_resp()) as mock_get:
            fetch_html("http://example.com")
        _, kwargs = mock_get.call_args
        assert kwargs.get("timeout") == 30

    def test_caller_can_override_timeout(self):
        with patch("scrapers.utils.net.get", return_value=self._mock_resp()) as mock_get:
            fetch_html("http://example.com", timeout=5)
        _, kwargs = mock_get.call_args
        assert kwargs.get("timeout") == 5

    def test_raises_on_http_error(self):
        resp = MagicMock()
        resp.raise_for_status.side_effect = requests.HTTPError("404")
        with patch("scrapers.utils.net.get", return_value=resp):
            with pytest.raises(requests.HTTPError):
                fetch_html("http://example.com")


def test_fetch_feed_raises_instead_of_returning_an_empty_feed(monkeypatch):
    import pytest

    from scrapers import utils

    class Resp:
        def __init__(self, body, status=200):
            self.content, self.status = body, status

        def raise_for_status(self):
            if self.status >= 400:
                raise RuntimeError(f"HTTP {self.status}")

    rss = b"<?xml version='1.0'?><rss version='2.0'><channel><title>City</title></channel></rss>"
    monkeypatch.setattr(utils.net, "get", lambda url, **kw: Resp(rss))
    assert utils.fetch_feed("https://example.com/rss").entries == []  # a real feed that's just empty: fine

    def timeout(url, **kw):
        raise TimeoutError("connect timeout")

    monkeypatch.setattr(utils.net, "get", timeout)
    with pytest.raises(TimeoutError):
        utils.fetch_feed("https://example.com/rss")
    monkeypatch.setattr(utils.net, "get", lambda url, **kw: Resp(b"<html>Access denied</html>"))
    with pytest.raises(ValueError):
        utils.fetch_feed("https://example.com/rss")

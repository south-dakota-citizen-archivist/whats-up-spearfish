"""
tests/test_scraper_town_news.py

Tests for scrapers/sources/town_news.py: HTML-to-text conversion,
first-paragraph extraction, Slack block building, and record parsing.
"""

from __future__ import annotations

from scrapers.sources.town_news import (
    _first_paragraph,
    _parse_record,
)

# ---------------------------------------------------------------------------
# _first_paragraph
# ---------------------------------------------------------------------------


class TestFirstParagraph:
    def test_returns_first_p_text(self):
        assert _first_paragraph(["<p>First</p><p>Second</p>"]) == "First"

    def test_skips_empty_p(self):
        assert _first_paragraph(["<p></p><p>Not empty</p>"]) == "Not empty"

    def test_searches_across_chunks(self):
        result = _first_paragraph(["<figure>img</figure>", "<p>Article text</p>"])
        assert result == "Article text"

    def test_empty_chunks_returns_empty(self):
        assert _first_paragraph([]) == ""

    def test_no_p_tags_returns_empty(self):
        assert _first_paragraph(["<div>Just a div</div>"]) == ""

    def test_whitespace_only_p_skipped(self):
        result = _first_paragraph(["<p>   </p>", "<p>Real text</p>"])
        assert result == "Real text"


# ---------------------------------------------------------------------------
# _parse_record
# ---------------------------------------------------------------------------


class TestParseRecord:
    def _item(self, **overrides):
        r = {
            "title": "Test Article",
            "url": "http://example.com/story",
            "starttime": {"iso8601": "2026-04-01T10:00:00-06:00"},
            "byline": "By Reporter",
            "content": ["<p>Article body.</p>"],
        }
        r.update(overrides)
        return r

    def test_extracts_title(self):
        assert _parse_record(self._item(), "Src")["title"] == "Test Article"

    def test_extracts_url(self):
        assert _parse_record(self._item(), "Src")["url"] == "http://example.com/story"

    def test_extracts_published_date(self):
        result = _parse_record(self._item(), "Src")
        assert result["published"] == "2026-04-01"

    def test_extracts_byline(self):
        result = _parse_record(self._item(), "Src")
        assert "Reporter" in result["byline"]

    def test_byline_whitespace_collapsed(self):
        result = _parse_record(self._item(byline="By  Jane \nPioneer"), "Src")
        assert "  " not in result["byline"]
        assert "\n" not in result["byline"]

    def test_description_is_first_paragraph(self):
        result = _parse_record(self._item(content=["<p>Lede.</p><p>More.</p>"]), "Src")
        assert result["description"] == "Lede."

    def test_record_type_is_news(self):
        assert _parse_record(self._item(), "Src")["record_type"] == "news"

    def test_source_label_set(self):
        assert _parse_record(self._item(), "My Paper")["source_label"] == "My Paper"

    def test_missing_title_returns_none(self):
        assert _parse_record(self._item(title=""), "Src") is None

    def test_missing_url_returns_none(self):
        assert _parse_record(self._item(url=""), "Src") is None

    def test_missing_starttime_published_empty(self):
        result = _parse_record(self._item(starttime={}), "Src")
        assert result["published"] == ""

    def test_empty_content_list(self):
        result = _parse_record(self._item(content=[]), "Src")
        assert result is not None
        assert result["description"] == ""

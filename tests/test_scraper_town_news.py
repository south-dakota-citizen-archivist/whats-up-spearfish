"""
tests/test_scraper_town_news.py

Tests for scrapers/sources/town_news.py: HTML-to-text conversion,
first-paragraph extraction, Slack block building, and record parsing.
"""

from __future__ import annotations

from scrapers.sources.town_news import (
    _first_paragraph,
    _html_to_text,
    _parse_record,
    _slack_blocks,
)

# ---------------------------------------------------------------------------
# _html_to_text
# ---------------------------------------------------------------------------


class TestHtmlToText:
    def test_basic_paragraph(self):
        result = _html_to_text(["<p>Hello world</p>"])
        assert "Hello world" in result

    def test_multiple_paragraphs(self):
        result = _html_to_text(["<p>First</p><p>Second</p>"])
        assert "First" in result
        assert "Second" in result

    def test_paragraph_break_present(self):
        result = _html_to_text(["<p>A</p><p>B</p>"])
        assert "\n" in result

    def test_tags_stripped(self):
        result = _html_to_text(["<p><strong>Bold</strong> text</p>"])
        assert "<" not in result
        assert "Bold" in result
        assert "text" in result

    def test_br_becomes_newline(self):
        result = _html_to_text(["First<br>Second"])
        assert "\n" in result
        assert "First" in result
        assert "Second" in result

    def test_empty_chunks_returns_empty(self):
        assert _html_to_text([]) == ""

    def test_multiple_blank_lines_collapsed(self):
        chunks = ["<p>A</p>", "<p>B</p>"]
        result = _html_to_text(chunks)
        assert "\n\n\n" not in result

    def test_multiple_chunks_concatenated(self):
        result = _html_to_text(["<p>Part 1</p>", "<p>Part 2</p>"])
        assert "Part 1" in result
        assert "Part 2" in result

    def test_result_stripped(self):
        result = _html_to_text(["   <p>Text</p>   "])
        assert result == result.strip()


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
# _slack_blocks
# ---------------------------------------------------------------------------


class TestSlackBlocks:
    def _record(self, **overrides):
        r = {
            "url": "http://example.com/article",
            "title": "Test Headline",
            "published": "2026-04-01",
            "byline": "By Jane Smith",
            "_full_text": "Short article body.",
        }
        r.update(overrides)
        return r

    def test_first_block_is_section(self):
        blocks = _slack_blocks(self._record())
        assert blocks[0]["type"] == "section"

    def test_header_links_title(self):
        blocks = _slack_blocks(self._record())
        header = blocks[0]["text"]["text"]
        assert "<http://example.com/article|Test Headline>" in header

    def test_header_contains_date(self):
        blocks = _slack_blocks(self._record())
        header = blocks[0]["text"]["text"]
        assert "2026-04-01" in header

    def test_header_contains_byline(self):
        blocks = _slack_blocks(self._record())
        header = blocks[0]["text"]["text"]
        assert "By Jane Smith" in header

    def test_body_text_in_second_block(self):
        blocks = _slack_blocks(self._record(_full_text="The full article text."))
        assert len(blocks) >= 2
        assert "The full article text." in blocks[1]["text"]["text"]

    def test_long_text_chunked_at_2900(self):
        long_text = "x" * 9000
        blocks = _slack_blocks(self._record(_full_text=long_text))
        body_blocks = blocks[1:]
        assert len(body_blocks) > 1
        for b in body_blocks:
            assert len(b["text"]["text"]) <= 2900

    def test_empty_full_text_no_body_block(self):
        blocks = _slack_blocks(self._record(_full_text=""))
        # Only the header block should be present when text is empty
        body_blocks = [b for b in blocks[1:] if b["text"]["text"].strip()]
        assert len(body_blocks) == 0

    def test_all_blocks_have_mrkdwn_type(self):
        blocks = _slack_blocks(self._record())
        for b in blocks:
            assert b["text"]["type"] == "mrkdwn"


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

    def test_full_text_stored(self):
        result = _parse_record(self._item(content=["<p>Full text.</p>"]), "Src")
        assert "_full_text" in result
        assert "Full text." in result["_full_text"]

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

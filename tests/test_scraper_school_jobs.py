"""
tests/test_scraper_school_jobs.py

Tests for scrapers/sources/spearfish_schools_jobs.py:
_extract_html (JS parsing) and _parse_posting (record extraction).
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from scrapers.sources.spearfish_schools_jobs import _extract_html, _parse_posting

# ---------------------------------------------------------------------------
# _extract_html
# ---------------------------------------------------------------------------


class TestExtractHtml:
    def test_basic_write(self):
        assert _extract_html("document.write('hello');") == "hello"

    def test_multiple_writes_concatenated(self):
        js = "document.write('hello ');document.write('world');"
        assert _extract_html(js) == "hello world"

    def test_escaped_single_quote(self):
        js = "document.write('it\\'s fine');"
        assert _extract_html(js) == "it's fine"

    def test_escaped_double_quote(self):
        js = "document.write('say \\\"hello\\\"');"
        assert _extract_html(js) == 'say "hello"'

    def test_escaped_backslash(self):
        js = "document.write('path\\\\file');"
        assert _extract_html(js) == "path\\file"

    def test_no_writes_returns_empty(self):
        assert _extract_html("var x = 1; alert('hi');") == ""

    def test_html_content_preserved(self):
        js = "document.write('<p>Some <strong>text</strong></p>');"
        result = _extract_html(js)
        assert "<p>" in result
        assert "<strong>" in result

    def test_empty_string_returns_empty(self):
        assert _extract_html("") == ""

    def test_interspersed_non_write_code(self):
        js = "var x=1; document.write('A'); x++; document.write('B');"
        assert _extract_html(js) == "AB"


# ---------------------------------------------------------------------------
# _parse_posting
# ---------------------------------------------------------------------------


def _make_ul(
    job_id="4523",
    district_id="17",
    title="Art Teacher",
    location="Spearfish, SD",
    district="Spearfish School District",
    date_posted="04/01/2026",
    closing="05/15/2026",
    position_type="Certified",
):
    html = f"""
    <ul id="p{job_id}_{district_id}">
      <table><tr><td id="wrapword">{title}</td></tr></table>
      <li><span class="label">Location:</span>
          <span class="normal">{location}</span></li>
      <li><span class="label">District:</span>
          <span class="normal">{district}</span></li>
      <li><span class="label">Date Posted:</span>
          <span class="normal">{date_posted}</span></li>
      <li><span class="label">Closing Date:</span>
          <span class="normal">{closing}</span></li>
      <li><span class="label">Position Type:</span>
          <span class="normal">{position_type}</span></li>
    </ul>
    """
    return BeautifulSoup(html, "html.parser").find("ul")


class TestParsePosting:
    # ── Basic extraction ──────────────────────────────────────────────────────

    def test_returns_record(self):
        assert _parse_posting(_make_ul()) is not None

    def test_title(self):
        assert _parse_posting(_make_ul(title="Math Teacher"))["title"] == "Math Teacher"

    def test_location(self):
        assert _parse_posting(_make_ul())["location"] == "Spearfish, SD"

    def test_record_type(self):
        assert _parse_posting(_make_ul())["record_type"] == "job"

    def test_source_label(self):
        assert _parse_posting(_make_ul())["source_label"] == "Spearfish School District"

    def test_url_contains_job_id(self):
        assert "9999" in _parse_posting(_make_ul(job_id="9999"))["url"]

    def test_slug_generated(self):
        result = _parse_posting(_make_ul())
        assert "slug" in result
        assert len(result["slug"]) > 0

    def test_description_built_from_fields(self):
        result = _parse_posting(_make_ul())
        # At least some field data should be in the description
        assert result["description"]

    # ── Location filtering ────────────────────────────────────────────────────

    def test_non_spearfish_location_returns_none(self):
        ul = _make_ul(location="Rapid City, SD", district="Rapid City Schools")
        assert _parse_posting(ul) is None

    def test_spearfish_in_location_case_insensitive(self):
        ul = _make_ul(location="SPEARFISH ELEMENTARY")
        assert _parse_posting(ul) is not None

    def test_spearfish_in_district_is_sufficient(self):
        ul = _make_ul(location="Whitewood, SD", district="Spearfish School District")
        assert _parse_posting(ul) is not None

    def test_neither_field_spearfish_returns_none(self):
        ul = _make_ul(location="Lead, SD", district="Lead-Deadwood School District")
        assert _parse_posting(ul) is None

    # ── Missing / malformed ───────────────────────────────────────────────────

    def test_empty_title_returns_none(self):
        ul = _make_ul(title="")
        assert _parse_posting(ul) is None

    def test_no_ul_id_match_still_processes(self):
        html = """
        <ul id="bad_id">
          <table><tr><td id="wrapword">Teacher</td></tr></table>
          <li><span class="label">Location:</span>
              <span class="normal">Spearfish, SD</span></li>
          <li><span class="label">District:</span>
              <span class="normal">Spearfish School District</span></li>
        </ul>
        """
        ul = BeautifulSoup(html, "html.parser").find("ul")
        result = _parse_posting(ul)
        # job_id will be empty string; record still returned if location matches
        assert result is not None
        assert result["title"] == "Teacher"

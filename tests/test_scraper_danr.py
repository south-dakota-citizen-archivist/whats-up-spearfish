"""
tests/test_scraper_danr.py

Unit tests for scrapers/sources/danr_public_notices.py helpers:
  - _is_west_river()
  - _deadline_sort_key()
  - _parse_deadline_cell() (label-stripping, inline-script parsing)
"""

from __future__ import annotations

from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# _is_west_river
# ---------------------------------------------------------------------------


class TestIsWestRiver:
    def _fn(self, text):
        from scrapers.sources.danr_public_notices import _is_west_river

        return _is_west_river(text)

    # target counties
    def test_lawrence_county(self):
        assert self._fn("Lawrence County") is True

    def test_pennington(self):
        assert self._fn("Pennington") is True

    def test_custer(self):
        assert self._fn("Custer County") is True

    def test_meade(self):
        assert self._fn("Meade County") is True

    def test_fall_river(self):
        assert self._fn("Fall River County") is True

    def test_butte(self):
        assert self._fn("Butte County") is True

    def test_harding(self):
        assert self._fn("Harding") is True

    def test_shannon(self):
        assert self._fn("Shannon County") is True

    def test_oglala_lakota(self):
        assert self._fn("Oglala Lakota County") is True

    def test_ziebach(self):
        assert self._fn("Ziebach County") is True

    # city fallbacks
    def test_rapid_city(self):
        assert self._fn("located in Rapid City") is True

    def test_spearfish(self):
        assert self._fn("Spearfish, SD") is True

    def test_deadwood(self):
        assert self._fn("Deadwood") is True

    def test_sturgis(self):
        assert self._fn("Sturgis") is True

    # east-river: should not match
    def test_minnehaha_false(self):
        assert self._fn("Minnehaha County") is False

    def test_brown_false(self):
        assert self._fn("Brown County") is False

    def test_turner_false(self):
        assert self._fn("Turner County") is False

    def test_empty_false(self):
        assert self._fn("") is False

    def test_case_insensitive(self):
        assert self._fn("PENNINGTON COUNTY") is True
        assert self._fn("lawrence county") is True


# ---------------------------------------------------------------------------
# _deadline_sort_key
# ---------------------------------------------------------------------------


class TestDeadlineSortKey:
    def _fn(self, notice):
        from scrapers.sources.danr_public_notices import _deadline_sort_key

        return _deadline_sort_key(notice)

    def test_mm_dd_yyyy(self):
        assert self._fn({"deadline": "04/23/2026"}) == "2026-04-23"

    def test_single_digit_month_day(self):
        assert self._fn({"deadline": "5/1/2026"}) == "2026-05-01"

    def test_empty_deadline_sorts_last(self):
        assert self._fn({"deadline": ""}) == "9999-99-99"

    def test_missing_deadline_sorts_last(self):
        assert self._fn({}) == "9999-99-99"

    def test_unparseable_sorts_last(self):
        assert self._fn({"deadline": "Unknown"}) == "9999-99-99"

    def test_earlier_date_sorts_before_later(self):
        a = self._fn({"deadline": "03/01/2026"})
        b = self._fn({"deadline": "05/01/2026"})
        assert a < b

    def test_no_deadline_sorts_after_any_date(self):
        dated = self._fn({"deadline": "12/31/2099"})
        none = self._fn({"deadline": ""})
        assert dated < none


# ---------------------------------------------------------------------------
# _parse_deadline_cell — plain text (no <script>)
# ---------------------------------------------------------------------------


class TestParseDeadlineCellPlainText:
    def _fn(self, html):
        from scrapers.sources.danr_public_notices import _parse_deadline_cell

        cell = BeautifulSoup(html, "html.parser")
        return _parse_deadline_cell(cell)

    def test_plain_date_returned(self):
        date, url = self._fn("<td>04/10/2026</td>")
        assert date == "04/10/2026"
        assert url == ""

    def test_petition_deadline_label_stripped(self):
        date, url = self._fn("<td>Petition Deadline:5/1/2026</td>")
        assert date == "5/1/2026"
        assert url == ""

    def test_comment_deadline_label_stripped(self):
        date, url = self._fn("<td>Comment Deadline: 04/23/2026</td>")
        assert date == "04/23/2026"
        assert url == ""

    def test_label_with_spaces_stripped(self):
        date, url = self._fn("<td>Petition Deadline: 05/01/2026</td>")
        assert date == "05/01/2026"


# ---------------------------------------------------------------------------
# _parse_deadline_cell — inline <script> (Caspio pattern)
# ---------------------------------------------------------------------------


class TestParseDeadlineCellScript:
    def _fn(self, html):
        from scrapers.sources.danr_public_notices import _parse_deadline_cell

        cell = BeautifulSoup(html, "html.parser")
        return _parse_deadline_cell(cell)

    def test_extracts_date_from_script(self):
        html = """
        <td>
          <div id="d1"></div>
          <script>
            var dline=new Date("04/10/2026");
            var today = new Date();
            if (dline>today) {
              document.getElementById("d1").innerHTML =
                "<a href=\\"https://danr.sd.gov/public/comment.aspx?d_comment=04/10/2026&name=Test\\">"
                + "04/10/2026</a>";
            }
          </script>
        </td>
        """
        date, url = self._fn(html)
        assert date == "04/10/2026"

    def test_extracts_comment_url_from_script(self):
        html = """
        <td>
          <div id="d1"></div>
          <script>
            var dline=new Date("04/23/2026");
            document.getElementById("d1").innerHTML =
              "<a href=\\"https://danr.sd.gov/public/comment.aspx?d_comment=04/23/2026&name=City+of+Summerset\\">04/23/2026</a>";
          </script>
        </td>
        """
        date, url = self._fn(html)
        assert date == "04/23/2026"
        assert "danr.sd.gov/public/comment.aspx" in url

    def test_no_comment_url_when_absent(self):
        html = """
        <td>
          <script>var dline=new Date("05/01/2026");</script>
        </td>
        """
        date, url = self._fn(html)
        assert date == "05/01/2026"
        assert url == ""

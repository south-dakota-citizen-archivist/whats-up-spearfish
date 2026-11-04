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
# _deadline_iso
# ---------------------------------------------------------------------------


class TestDeadlineIso:
    def _fn(self, notice):
        from scrapers.sources.danr_public_notices import _deadline_iso

        return _deadline_iso(notice)

    def test_mm_dd_yyyy(self):
        assert self._fn({"deadline": "04/23/2026"}) == "2026-04-23"

    def test_single_digit_month_day(self):
        assert self._fn({"deadline": "5/1/2026"}) == "2026-05-01"

    def test_empty_or_missing(self):
        assert self._fn({"deadline": ""}) == ""
        assert self._fn({}) == ""

    def test_unparseable(self):
        assert self._fn({"deadline": "Unknown"}) == ""


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


# ---------------------------------------------------------------------------
# Caspio embed responses and the West River filter (whole scrape)
# ---------------------------------------------------------------------------

_TABLE = (
    '<table class="cbResultSetTable"><thead><tr class="cbResultSetTableHeader">'
    "<th>Business</th><th>Location</th><th>Comment Deadline</th></tr></thead>"
    "<tbody>"
    '<tr class="cbResultSetDataRow"><td class="cbResultSetData">Clint Krambeck</td>'
    '<td class="cbResultSetData">Lawrence</td><td class="cbResultSetData">11/16/2026</td></tr>'
    '<tr class="cbResultSetDataRow"><td class="cbResultSetData">Crenlo Cabs</td>'
    '<td class="cbResultSetData">Watertown</td><td class="cbResultSetData">11/05/2026</td></tr>'
    "</tbody></table>"
)


def _embed(html: str) -> str:
    """What Caspio sends back: JS with the table as an escaped, single-quoted string."""
    escaped = html.replace("<", "\\u003c").replace(">", "\\u003e").replace('"', '\\"').replace("'", "\\'")
    return f"function f(){{}};\r\nnew f_dpLoadObj().parseAndLoadDatapage('dp_anchor_id_1', 'abc', '{escaped}');"


def test_datapage_html_unescapes_the_table():
    from scrapers.sources.danr_public_notices import datapage_html

    assert datapage_html(_embed(_TABLE)) == _TABLE
    assert datapage_html("no datapage here") is None


def test_scrape_keeps_west_river_and_fails_loudly_without_tables(monkeypatch):
    import pytest

    from scrapers.sources import danr_public_notices as danr

    page = (
        '<section><h2>Water Rights</h2><script src="https://b4.caspio.com/dp/31cf1000aaaaaaaaaaaaaaaaaaaa/emb">'
        "</script></section>"
    )

    class Resp:
        def __init__(self, text):
            self.text, self.ok = text, True

        def raise_for_status(self):
            pass

    monkeypatch.setattr(danr.time, "sleep", lambda s: None)
    monkeypatch.setattr(danr.net, "get", lambda url, **kw: Resp(page if url == danr.DANR_URL else _embed(_TABLE)))
    notices = danr.DANRPublicNotices().scrape()
    assert [n["location"] for n in notices] == ["Lawrence"]  # Watertown is East River
    assert notices[0]["notice_type"] == "Water Rights" and notices[0]["deadline_iso"] == "2026-11-16"
    assert notices[0]["title"] == "Clint Krambeck"  # the "Business" column names the applicant

    # the page answers, but no table can be read: that's breakage, not a quiet week
    monkeypatch.setattr(danr.net, "get", lambda url, **kw: Resp(page if url == danr.DANR_URL else "<html></html>"))
    with pytest.raises(RuntimeError):
        danr.DANRPublicNotices().scrape()


# ---------------------------------------------------------------------------
# contested cases (fixtures trimmed from the live Caspio tables)
# ---------------------------------------------------------------------------


def _fixture(name):
    from pathlib import Path

    return BeautifulSoup((Path(__file__).parent / "fixtures" / name).read_text(), "html.parser")


def test_contested_case_listing_groups_and_west_river_filter():
    from scrapers.sources.danr_contested_cases import is_local, parse_listing

    cases = parse_listing(_fixture("danr_contested_cases.html"))
    assert len(cases) == 10
    first = cases[0]
    assert first["ccid"] == "123" and first["board"] == "Board of Minerals and Environment"
    assert first["permit_type"] == "Uranium Exploration Permit"
    assert "  " not in first["description"]
    local = {c["title"] for c in cases if is_local(c)}
    assert "2049-1 Stanley R Goschke" in local  # only a Black Hills legal description (T4N-R6E) places it
    assert "Petition to Modify the Recommended Solid Waste Permit for the Rapid City Landfill" in local
    assert "9008-3 Brian Gilbert" not in local  # Spink County, T115N-R65W
    assert not any("Madison" in t for t in local)


def test_contested_case_documents_newest_first_with_dates():
    from scrapers.sources.danr_contested_cases import parse_documents

    docs = parse_documents(_fixture("danr_contested_case_docs.html"))
    assert len(docs) == 5
    assert docs[0]["added"] == "2026-07-24" and docs[0]["url"].endswith(".pdf")
    assert docs[0]["title"].startswith("Notice of Entry of Order")


def test_contested_cases_scrape_keeps_local_and_statewide(monkeypatch):
    from scrapers.sources import danr_contested_cases as cc

    calls = []

    def get(url, **params):
        calls.append(params.get("CCID"))
        return _fixture("danr_contested_cases.html" if url == cc.LISTING_URL else "danr_contested_case_docs.html")

    monkeypatch.setattr(cc, "_get", get)
    monkeypatch.setattr(cc.time, "sleep", lambda s: None)
    out = cc.DANRContestedCases().scrape()
    titles = [c["title"] for c in out]
    assert "9008-3 Brian Gilbert" not in titles and "8987-3 Vic Utech" not in titles
    cafo = next(c for c in out if c["permit_type"] == "General Permit")
    assert cafo["area"] == "Statewide"
    assert out[0]["url"] == "https://danr.sd.gov/public/ccdocs.aspx?CCID=CCID123"
    assert len(out[0]["documents"]) == cc.LATEST_DOCS and out[0]["updated"] == "2026-07-24"
    assert len(calls) == len(out) + 1  # documents fetched only for the cases kept


def test_west_river_needs_whole_words():
    from scrapers.sources.danr_public_notices import _is_west_river

    assert _is_west_river("four miles northwest of Lead, SD")
    assert not _is_west_river("a leading cause of erosion")


# ---------------------------------------------------------------------------
# spill reports
# ---------------------------------------------------------------------------


def test_spill_report_numbers():
    from scrapers.sources.danr_spills import report_number

    assert report_number(2026.14) == "2026.140"  # the layer drops trailing zeros
    assert report_number(2026.163) == "2026.163"
    assert report_number(2026005.0) is None  # the tank-check series, not spills
    assert report_number(2026.0) is None and report_number(None) is None


def test_spill_scrape(monkeypatch):
    from scrapers.sources import danr_spills as spills

    def feature(id_, **kw):
        attrs = {"id": id_, "site_name": "Fuel Tanker Roll Over", "status": "O", "spill_cat": "Petroleum",
                 "material": "Diesel", "sor_type": "Fuel Truck", "street": "Hwy 18", "city": "Edgemont",
                 "county": "fall river", "resp_party": "Westco"} | kw  # fmt: skip
        return {"attributes": attrs, "geometry": {"x": -103.8123456, "y": 43.3012345}}

    features = [
        feature(2026.162),
        feature(2026.14, site_name="Hydraulic  Line", status="NFA", material="Hydraulic Oil", sor_type="AST"),
        feature(2026.14, site_name="Hydraulic  Line"),  # listed twice
        feature(2026005.0, site_name="Clean ATP - Spearfish DOT"),
        feature(2026.15, material="None", sor_type="UST", spill_cat="Other(See Case File)"),
    ]

    class Resp:
        ok = True
        headers = {"Content-Type": "application/pdf", "Content-Length": "1234"}
        content = b"%PDF-1.7 fake"

        def raise_for_status(self):
            pass

        def json(self):
            return {"features": features}

    def request(method, url, **kw):
        r = Resp()
        if url.endswith("2026.162.pdf"):
            r.ok = False  # not posted yet
        return r

    read = []

    def read_pdf(path, engine, pages):
        read.append(path.name)
        oil = [{"name": "Hydraulic Oil", "quantity": "65", "units": "gallons"}]
        return {"forms": [{"form": "spill report", "method": "fields", "page": 1, "spill_date": "09/03/26",
                           "materials": oil}]}  # fmt: skip

    from spillarchive import extract, files

    monkeypatch.setattr(spills.net, "get", lambda url, params=None, **kw: Resp())
    monkeypatch.setattr(spills.net, "request", request)
    monkeypatch.setattr(files, "lookup", lambda layer_id, delay=1.0: [])  # the state's list lags: guess the file
    monkeypatch.setattr(extract, "read_pdf", read_pdf)
    scraper = spills.DANRSpills()
    out = scraper.scrape()
    # newest first by the spill date its form gives; the rest by number
    assert [r["report_no"] for r in out] == ["2026.150", "2026.140", "2026.162"]
    by_no = {r["report_no"]: r for r in out}
    first, other, line = by_no["2026.162"], by_no["2026.150"], by_no["2026.140"]
    assert first["url"] == spills.MAP_URL and line["url"].endswith("/2026/2026.140.pdf")
    assert first["county"] == "Fall River" and first["status"] == "Open" and first["lat"] == 43.30123
    assert line["title"] == "Hydraulic Line" and line["status"] == "No further action"
    assert line["material"] == "Hydraulic oil" and line["spill_source"] == "Above-ground tank"
    assert other["material"] == "" and other["category"] == "Other" and other["spill_source"] == "Underground tank"
    # what the form says
    assert line["spill_date"] == "2026-09-03"
    assert line["report"]["materials"][0]["quantity"] == "65" and line["report"]["read_from"] == "fields"
    assert line["pdfs"] == [{"url": line["url"], "size": 1234}]

    # an unchanged PDF isn't read again
    read.clear()
    monkeypatch.setattr(scraper, "load_existing", lambda: out)
    again = {r["report_no"]: r for r in scraper.scrape()}
    assert read == [] and again["2026.140"]["spill_date"] == "2026-09-03"


def test_spill_sentence_case_keeps_acronyms():
    from scrapers.sources.danr_spills import sentence_case

    assert sentence_case("Transformer Oil NonPCB") == "Transformer oil NonPCB"
    assert sentence_case("PFAS") == "PFAS" and sentence_case("") == ""

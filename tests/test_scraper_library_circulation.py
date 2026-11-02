"""
tests/test_scraper_library_circulation.py

Monthly library checkouts from the hand-kept Google Sheet.
"""

from __future__ import annotations


class TestIntOrNone:
    def _fn(self, val):
        from scrapers.sources.library_circulation import _int_or_none

        return _int_or_none(val)

    def test_integer_string(self):
        assert self._fn("5539") == 5539

    def test_zero(self):
        assert self._fn("0") == 0

    def test_empty_string(self):
        assert self._fn("") is None

    def test_whitespace_only(self):
        assert self._fn("   ") is None

    def test_whitespace_padded_number(self):
        assert self._fn("  7482  ") == 7482

    def test_non_numeric(self):
        assert self._fn("n/a") is None

    def test_float_string(self):
        # CSV values are always integers for this dataset; floats are invalid
        assert self._fn("5539.0") is None

    def test_negative(self):
        # Loan counts are never negative, but the function should handle it
        assert self._fn("-1") == -1


CSV = """year,month,loans,renewals,overdrive_loans,hoopla_loans,minutes_link
2021,4,6100,900,,,https://example.com/m1
2021,5,,,,,
2022,1,"5,800",,3900,850,https://example.com/m2
2026,4,5596,,3569,,
2026,13,1,,,,
"""


def test_parse_rows():
    from scrapers.sources.library_circulation import parse_rows

    rows = parse_rows(CSV)
    assert [r["month"] for r in rows] == ["2021-04", "2022-01", "2026-04"]  # blank and bad months dropped
    assert rows[1] == {
        "month": "2022-01",
        "loans": 5800,
        "renewals": None,
        "overdrive": 3900,
        "hoopla": 850,
        "minutes": "https://example.com/m2",
    }
    assert rows[2]["hoopla"] is None and rows[2]["minutes"] == ""


def test_scrape_returns_rows(monkeypatch):
    from scrapers.sources import library_circulation as lc

    class Resp:
        text = CSV

        def raise_for_status(self):
            pass

    monkeypatch.setattr(lc.net, "get", lambda url, **kw: Resp())
    s = lc.LibraryCirculation()
    out = s.scrape()
    assert len(out["rows"]) == 3 and not s.is_empty(out)
    assert s.is_empty({"rows": []})

"""
tests/test_scraper_school_board.py

School board documents: the meeting date read from each title (the district's
titles have typos), and grouping them into meetings for the Schools page.
"""

from __future__ import annotations

import pytest

from sitegen.data import Site
from sitegen.pages import board_doc_label, meetings
from tests.test_sitegen import _write


@pytest.mark.parametrize(
    "title, date",
    [
        ("March 9, 2026 School Board Minutes", "2026-03-09"),
        ("October 14,, 2025 School Board Agenda", "2025-10-14"),  # doubled comma
        ("Rescheduled - September 16, 2026 School Board Agenda", "2026-09-16"),  # date not first
        ("August 4 , 2026 Special School Board Meeting Addendum", "2026-08-04"),  # space before the comma
        ("g.. November 13, 2023 School Board Audio Minutes", "2023-11-13"),  # stray outline mark
        ("School Board Policy Manual", ""),
    ],
)
def test_meeting_date_from_title(title, date):
    from scrapers.sources.spearfish_school_board_docs import _clean_title, _parse_date

    assert _parse_date(_clean_title(title)) == date


def test_board_meetings_group_by_date_with_clear_labels(tmp_path):
    docs = [
        {"title": "August 10, 2026 School Board Agenda", "asset_type": "agenda", "date": "2026-08-10"},
        {"title": "August 10, 2026 School Board Addendum", "asset_type": "agenda", "date": "2026-08-10"},
        {"title": "August 10, 2026 School Board Minutes", "asset_type": "minutes", "date": "2026-08-10"},
        {"title": "School Board Policy Manual", "asset_type": "agenda", "date": ""},  # no meeting date
    ]
    for i, d in enumerate(docs):
        d |= {"id": str(i), "kind": "document", "url": f"https://example.com/{i}.pdf"}
    _write(tmp_path, "spearfish_school_board_docs", docs, kind="document")
    board = [m for m in meetings(Site(tmp_path)) if m["body"] == "School Board"]
    assert len(board) == 1 and board[0]["date"] == "2026-08-10"  # the undated document isn't a meeting
    assert [d["label"] for d in board[0]["docs"]] == ["Agenda", "Addendum", "Minutes"]
    assert board_doc_label({"title": "Nov 13 School Board Audio Minutes", "asset_type": "minutes"}) == "Audio minutes"

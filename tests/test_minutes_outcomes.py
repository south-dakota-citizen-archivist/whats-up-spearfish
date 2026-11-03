"""
tests/test_minutes_outcomes.py

The checks that decide whether a model's reading of the minutes is kept.
"""

from __future__ import annotations

import pytest

from scripts.minutes_outcomes import check, in_minutes, norm

MINUTES = """
Bordewyk closed the public hearing at 4:47 pm. Motion was made by Meyer, seconded by Vavruska and passed
unanimously recommending approval of the request by Spring Creek Ranch, LLC for voluntary annex-
ation. Moths moved to continue the item to the next meeting, and the motion died due to lack of a second.
Kean moved, Zwetzig seconded, and all voted to table the request pending additional information.
Davison moved to send the application to City Council with no recommendation, and the motion passed 3-0.
Due to lack of quorum, no action was taken.
"""


def test_quotes_survive_line_breaks_curly_quotes_and_split_words():
    assert norm("annex-\nation") == "annexation"
    assert in_minutes("passed unanimously recommending approval of the request by Spring Creek Ranch, LLC "
                      "for voluntary annexation.", MINUTES)  # fmt: skip
    assert in_minutes("Kean moved, Zwetzig seconded, and all voted to table the request", MINUTES)
    assert not in_minutes("Kean moved, Zwetzig seconded, and all voted to approve the request", MINUTES)
    assert not in_minutes("", MINUTES)
    assert in_minutes('"Kean moved, Zwetzig seconded, and all voted to table the request"', MINUTES)  # wrapped
    assert in_minutes("Kean moved, Zwetzig seconded … to table the request pending additional information", MINUTES)
    assert not in_minutes("Kean moved, Zwetzig seconded … to approve the request without more information", MINUTES)


@pytest.mark.parametrize(
    "outcome, quote, problem",
    [
        ("recommended approval", "Motion was made by Meyer, seconded by Vavruska and passed unanimously "
         "recommending approval of the request", ""),
        ("tabled", "Kean moved, Zwetzig seconded, and all voted to table the request", ""),
        ("forwarded without a recommendation", "Davison moved to send the application to City Council with no "
         "recommendation, and the motion passed 3-0.", ""),
        ("discussed, no vote", "Due to lack of quorum, no action was taken.", ""),
        ("withdrawn", "", ""),
        # made up: not in the minutes
        ("approved", "Meyer moved and all voted to approve the plat.", "quote isn't in the minutes"),
        # in the minutes, but the wrong outcome for what it says
        ("approved", "Kean moved, Zwetzig seconded, and all voted to table the request", "doesn't say"),
        ("postponed", "Moths moved to continue the item to the next meeting, and the motion died due to lack of a "
         "second.", "didn't pass"),
        ("tabled", "Due to lack of quorum, no action was taken.", "isn't a motion"),
        ("passed with flying colors", "Kean moved", "unknown outcome"),
    ],
)  # fmt: skip
def test_check(outcome, quote, problem):
    found = check({"outcome": outcome, "quote": quote}, MINUTES)
    assert (problem in found) if problem else found == ""

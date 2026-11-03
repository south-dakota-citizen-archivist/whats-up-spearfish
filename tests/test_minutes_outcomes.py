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
Bordewyk moved to recommend denial of the requested variance, Wilde seconded the motion. Bordewyk amended the motion
to table the application until the next meeting. Wilde seconded the amended motion, and the motion passed 7-0.
Tysdal moved to approve the sketch plat.
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
        # a motion made, but the quote never says it passed
        ("approved", "Tysdal moved to approve the sketch plat.", "doesn't show the motion passed"),
        # a "no recommendation" motion isn't an approval
        ("recommended approval", "Davison moved to send the application to City Council with no recommendation, and "
         "the motion passed 3-0.", "without a recommendation"),
        # the motion to deny was amended to table it
        ("recommended denial", "Bordewyk moved to recommend denial of the requested variance, Wilde seconded the "
         "motion. Bordewyk amended the motion to table the application until the next meeting. Wilde seconded the "
         "amended motion, and the motion passed 7-0.", "amended"),
        ("tabled", "Bordewyk amended the motion to table the application until the next meeting. Wilde seconded the "
         "amended motion, and the motion passed 7-0.", ""),
    ],
)  # fmt: skip
def test_check(outcome, quote, problem):
    found = check({"outcome": outcome, "quote": quote}, MINUTES)
    assert (problem in found) if problem else found == ""


@pytest.mark.parametrize(
    "quote, outcome",
    [
        ("Vavruska moved, Byrum seconded and all voted to recommend approval.", "recommended approval"),
        ("Motion was made by Meyer, seconded by Vavruska and passed unanimously recommending approval of the request",
         "recommended approval"),
        ("Tysdal moved, Vavruska seconded, and all voted to approve the change of zoning.", "approved"),
        ("Bordewyk moved to recommend denial of the variance request, and the motion passed 3-2.",
         "recommended denial"),
        ("Tysdal moved, Davison seconded, and all voted to continue the public hearing.", "postponed"),
        ("Kean moved, Zwetzig seconded, and all voted to table the request.", "tabled"),
        ("Meyer moved, Vavruska seconded and all voted to set a public hearing for May 17, 2022.",
         "public hearing set"),
        ("Davison moved to send the application to City Council with no recommendation, and the motion passed 3-0.",
         "forwarded without a recommendation"),
        # the motion as amended, not as first made
        ("Bordewyk moved to recommend denial, Wilde seconded the motion. Bordewyk amended the motion to table the "
         "application. Wilde seconded the amended motion, and the motion passed 7-0.", "tabled"),
        # the later motion decides
        ("The motion to recommend approval failed 3-4. Motion was made by Meyer to continue this matter to the next "
         "meeting. Upon vote taken thereon, the motion passed by a vote of 4-2.", "postponed"),
        ("Moths moved to set a public hearing as soon as possible, Byrum seconded the motion. With the motion on the "
         "table, Wilde asked a question. The motion passed 6-0.", "public hearing set"),
        ("Bordewyk moved to recommend approval of the final plat in accordance with the previously approved "
         "preliminary plat. The motion passed 4-1.", "recommended approval"),
        ("Moths moved to continue the item, and the motion died due to lack of a second.", "motion failed"),
    ],
)  # fmt: skip
def test_outcome_from_wording(quote, outcome):
    from scripts.minutes_outcomes import outcome_from_wording

    assert outcome_from_wording(quote) == outcome

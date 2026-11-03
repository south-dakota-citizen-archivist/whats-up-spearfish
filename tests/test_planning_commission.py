"""
tests/test_planning_commission.py

Planning Commission agenda items (CivicClerk): staff report and agenda parsing,
application typing, item selection, and their place on the permits page.
"""

from __future__ import annotations

import json

import pytest

from scrapers.sources.planning_commission import (
    app_type,
    application_items,
    item_record,
    match_agenda,
    parse_agenda_text,
    parse_staff_report_words,
    street_address,
)
from sitegen.data import Site
from sitegen.pages import permit_sites


def _words(rows):
    """[(x0, top, "text with spaces"), …] → pdfplumber-like words (5pt per character)."""
    out = []
    for x, top, text in rows:
        for t in text.split():
            out.append({"x0": x, "x1": x + 5 * len(t), "top": top, "text": t})
            x += 5 * len(t) + 4
    return out


def test_staff_report_header_keeps_right_column_out_of_values():
    words = _words(
        [
            (166, 52, "Spearfish Planning Commission Tuesday, September 1, 2026"),
            (36, 153, "Request:"),
            (153, 153, "Make a recommendation on a variance"),
            (153, 167, "for 1407 Charles Street."),
            (36, 242, "Applicant:"),
            (153, 242, "Andy Van Deest."),
            (36, 262, "Location:"),
            (153, 262, "1407 Charles Street"),
            (36, 281, "Recommendation:"),
            (153, 281, "Staff recommends denial."),
            (153, 295, "Staff recommend setting the hearing"),
            (420, 295, "Lot 2 of Block 2 of the Ruby Ridge"),
            (153, 309, "for September 8th."),
            (420, 309, "Addition to the City of Spearfish"),
            (36, 329, "Public Hearing:"),
            (153, 329, "No"),
            (36, 380, "Project Summary"),
            (36, 400, "Staff continues to feel that a variance is appropriate."),
        ]
    )
    r = parse_staff_report_words(words)
    assert r["request"] == "Make a recommendation on a variance for 1407 Charles Street."
    assert r["applicant"] == "Andy Van Deest."
    assert r["location"] == "1407 Charles Street"
    assert r["recommendation"] == "Staff recommends denial. Staff recommend setting the hearing for September 8th."
    assert r["public_hearing"] == "No"
    assert r["legal_description"] == "Lot 2 of Block 2 of the Ruby Ridge Addition to the City of Spearfish"


def test_map_caption_is_not_a_legal_description():
    words = _words([(36, 100, "Location:"), (153, 100, "2630 Lookout Mountain Road"), (420, 100, "ETJ")])
    r = parse_staff_report_words(words)
    assert r == {"location": "2630 Lookout Mountain Road"}


AGENDA = """
F.   Items for Action - Old Business

     1.   Request:        A variance to reduce the required side-yard setback from 10' to 5' on
                          the west side of 1407 Charles Street.
          Applicant:      Andy Van Deest.
          Location:       1407 Charles Street
          Recommendation: Staff recommends denial of the variance as presented.

G. Items for Action - New Business
     1.   Request:   Voluntary Annexation
          Applicant: Jason Ward on behalf of the Edna Mae Ward
                     Revocable Trust.
          Location:  NW¼NE¼ of Section 33, T7N, R2E
          Action:    Make recommendation to City Council.
H. Adjournment
"""


def test_agenda_blocks():
    blocks = parse_agenda_text(AGENDA)
    assert len(blocks) == 2
    assert blocks[0]["request"].endswith("on the west side of 1407 Charles Street.")
    assert blocks[0]["location"] == "1407 Charles Street"
    assert blocks[1]["applicant"] == "Jason Ward on behalf of the Edna Mae Ward Revocable Trust."
    assert blocks[1]["recommendation"] == "Make recommendation to City Council."
    assert match_agenda("A variance to reduce the required side-yard setback from 10' to 5'", blocks) is blocks[0]
    assert match_agenda("Something else entirely", blocks) == {}


@pytest.mark.parametrize(
    "text, kind",
    [
        ("A variance to reduce the required side-yard setback", "Variance"),
        ("Consider a conditional use permit for an in-home childcare center.", "Conditional use permit"),
        ("Rezone three parcels from Agricultural to R-1", "Rezone"),
        ("Consider a major preliminary plat for Block 2", "Preliminary plat"),
        ("Consider a minor final plat in the ETJ.", "Final plat"),
        ("Consider a sketch plat in the ETJ.", "Plat"),
        ("Voluntary Annexation", "Annexation"),
        ("Consider the creation of TIF District 9", "Tax increment financing district"),
        ("Proposed revisions to Chapter 154: Subdivisions", "Code amendment"),
        ("Elect a Chair and Vice-Chair", "Other"),
        # older agendas
        ("Approve the revised Findings, Project ID: CUP19-001.", "Conditional use permit"),
        ("Provide input on camper/RV parking issues. [PROJECT ID: ORD19-001]", "Code amendment"),
        ("Variance to rear setback; zoning code requires 15 feet.", "Variance"),
        ("Approve a variance for parking requirements", "Variance"),
        ("Zoning Ordinance Text Amendment, Article VI, Section 2, Variances.", "Code amendment"),
        ("Revisions to the uses eligible for a CUP in residential zoning district ordinance text", "Code amendment"),
        ("Approve a DRD Final Plan for phase 1 building at Spearfish Canyon Village", "Planned development"),
        ("Hold a public hearing to adjust the boundary between C-2 and ag zoning", "Rezone"),
        ("Approve a C-1 Redevelopment Incentive Plan", "Downtown redevelopment incentive"),
        ("East Colorado Boulevard Corridor Study", "Area plan or study"),
    ],
)
def test_app_type(text, kind):
    assert app_type(text) == kind


def test_street_address():
    assert street_address("Intersection of E. Grant Street", "a CUP at 446 N Main Street.") == "446 N Main Street"
    assert street_address("1407 Charles Street") == "1407 Charles Street"
    assert street_address("W1/2 of the E1/2 of Section 22, T7N, R2E") == ""


def test_application_items_skip_minutes_and_discussion():
    items = [
        {
            "agendaObjectItemName": "Approve Minutes",
            "childItems": [
                {"id": 1, "agendaObjectItemName": "Approve the minutes from 8/21", "attachmentsList": [{"id": 9}]},
            ],
        },
        {
            "agendaObjectItemName": "Items for Action - Old Business",
            "childItems": [
                {"id": 2, "agendaObjectItemName": "A variance at 1407 Charles Street", "attachmentsList": [{"id": 10}]},
            ],
        },
        {
            "agendaObjectItemName": "Items for Discussion/Informational Presentations",
            "childItems": [
                {
                    "id": 3,
                    "agendaObjectItemName": "Trails presentation",
                    "attachmentsList": [{"id": 11}],
                    "reportsList": [{"id": 5}],
                },
            ],
        },
    ]
    assert [i["id"] for i, _ in application_items(items)] == [2]


def _item():
    return {
        "id": 13020,
        "agendaObjectItemNumber": "2026-655",
        "agendaObjectItemName": "A variance to reduce the side-yard setback at 1407 Charles Street.",
        "reportsList": [
            {"id": 9870, "pdfMediaFullPath": "https://civicclerk.blob.core.windows.net/x.pdf?sig=SECRET&sp=rw"}
        ],
        "attachmentsList": [{"id": 10207, "fileName": "Proposed Addition Sketch ", "isPublished": True}],
    }


def test_item_record_links_to_portal_never_to_signed_urls():
    event = {"id": 2225, "startDateTime": "2026-09-01T16:00:00Z"}
    r = item_record(
        _item(), "Items for Action", event, {"applicant": "Andy Van Deest.", "location": "1407 Charles Street"}
    )
    assert r["app_type"] == "Variance" and r["site"] is True
    assert r["address_key"] == "1407 CHARLES ST"
    assert r["report_url"] == "https://spearfishsd.portal.civicclerk.com/event/2225/files/report/9870"
    assert r["attachments"] == [
        {
            "name": "Proposed Addition Sketch",
            "url": "https://spearfishsd.portal.civicclerk.com/event/2225/files/attachment/10207",
        }
    ]
    assert "SECRET" not in json.dumps(r)


def test_city_wide_items_are_not_sites():
    event = {"id": 1, "startDateTime": "2026-04-07T16:00:00Z"}
    item = {"id": 5, "agendaObjectItemName": "Proposed revisions to Chapter 151: Flood Prevention"}
    r = item_record(item, "Items for Action", event, {"location": "City-wide"})
    assert r["site"] is False and r["location"] == ""


def test_permit_sites_include_planning_items(tmp_path):
    event = {
        "id": 2225,
        "startDateTime": "2026-09-01T16:00:00Z",
        "publishedFiles": [{"type": "Agenda", "fileId": 501}, {"type": "Minutes", "fileId": 502}],
    }
    rec = item_record(
        _item(), "Items for Action", event, {"applicant": "Andy Van Deest.", "location": "1407 Charles Street"}
    )
    desc_only = item_record(
        {"id": 7, "agendaObjectItemName": "Consider a preliminary plat for Peaceful Pines Phase 2."},
        "Items for Action",
        event,
        {"location": "Intersection of St. Onge Road and Highway 14."},
    )
    (tmp_path / "planning_commission.json").write_text(json.dumps({"records": [rec, desc_only]}))
    (tmp_path / "building_permits.json").write_text(
        json.dumps(
            {
                "records": [
                    {"site_address": "1407 CHARLES STREET", "date": "2026-10-01", "construction_type": "Res-Garage"}
                ]
            }
        )
    )
    sites = {s["k"]: s for s in permit_sites(Site(tmp_path))}
    charles = sites["1407 CHARLES ST"]
    assert [r["src"] for r in charles["r"]] == ["permit", "pc"]
    pc = charles["r"][1]
    # only that the place was on the agenda, and the meeting's own documents
    assert pc["t"] == "On the meeting agenda"
    assert pc["docs"] == [
        ["Agenda", "https://spearfishsd.portal.civicclerk.com/event/2225/files/agenda/501"],
        ["Minutes", "https://spearfishsd.portal.civicclerk.com/event/2225/files/agenda/502"],
    ]
    assert pc["u"].endswith("/files/report/9870") and pc["att"][0][0] == "Proposed Addition Sketch"
    assert not {"who", "own", "rec", "legal", "desc", "loc"} & set(pc)  # nothing read from the documents
    pines = sites["LOC INTERSECTION OF ST. ONGE ROAD AND HIGHWAY 14"]
    assert "lat" not in pines and pines["r"][0]["t"] == "On the meeting agenda"


# ── older agendas (backfill, 2016 – July 2025) ───────────────────────────────


def _old_agenda():
    from pathlib import Path

    return (Path(__file__).parent / "fixtures" / "pc_agenda_2016_01_05.txt").read_text()


def test_older_agenda_capital_labels_and_stray_marks():
    from scrapers.sources.planning_commission import parse_agenda_text

    blocks = parse_agenda_text(_old_agenda())
    assert len(blocks) == 2  # the election of officers isn't an application
    zoning, cup = blocks
    assert zoning["request"].startswith("HOLD A PUBLIC HEARING FOR A CHANGE IN ZONING")
    assert zoning["request"].endswith("COMMERCIAL (C-2).")  # wrapped lines joined
    assert zoning["location"].endswith("(See maps attached to the staff report).")
    assert cup["applicant"] == "Jared Capp"  # despite the stray "." before the label
    assert cup["recommendation"].startswith("Set a Public Hearing for January 19, 2016")  # "ACTION (Revised):"


def test_older_agenda_records():
    from scrapers.sources.planning_commission import agenda_block_record, parse_agenda_text

    event = {"id": 1149, "startDateTime": "2016-01-05T00:00:00Z"}
    zoning, cup = (agenda_block_record(b, n, event) for n, b in enumerate(parse_agenda_text(_old_agenda()), 1))
    assert zoning["item_id"] == "1149-1" and zoning["from_agenda_pdf"]
    assert zoning["app_type"] == "Rezone" and cup["app_type"] == "Conditional use permit"
    assert zoning["request"].startswith("Hold a public hearing for a change in zoning from development review")
    assert "(DRD)" in zoning["request"] and "(C-2)" in zoning["request"]
    assert zoning["site"] and zoning["report_url"] == "" and zoning["url"].endswith("/event/1149/files")


@pytest.mark.parametrize(
    "text, expected",
    [
        ("VARIANCE TO FRONT YARD SETBACK", "Variance to front yard setback"),
        ("CONDITIONAL USE FOR A BUSINESS ON US HWY 14", "Conditional use for a business on US HWY 14"),
        ("LOTS 6A-2 & 7C, T6N R2E", "Lots 6A-2 & 7C, T6N R2E"),
        ("Already in Sentence case (DRD)", "Already in Sentence case (DRD)"),
    ],
)
def test_sentence_case(text, expected):
    from scrapers.sources.planning_commission import sentence_case

    assert sentence_case(text) == expected


def test_whole_districts_and_the_meeting_room_are_not_sites():
    from scrapers.sources.planning_commission import agenda_block_record

    event = {"id": 1, "startDateTime": "2022-07-19T00:00:00Z"}
    for location in ("C-1 zoning districts", "City Council Chamber, 625 Fifth Street, Spearfish", "To be determined"):
        rec = agenda_block_record({"request": "Approve a variance for parking", "location": location}, 1, event)
        assert not rec["site"], location
    rec = agenda_block_record({"request": "Approve a variance", "location": "437 N Main St"}, 1, event)
    assert rec["site"] and rec["address"] == "437 N Main St"


def test_agenda_fields_continue_past_a_blank_line_only_mid_sentence():
    from scrapers.sources.planning_commission import parse_agenda_text

    text = """
    F. Items for Action
       1.  Request:  Hold a public hearing and make a recommendation to City Council on the

                     preliminary plat of the Eastside Acres subdivision
           Applicant: Eastside Developers LLC
           Location:  6025 East Colorado Blvd.

                     This paragraph is body text, not part of the location.
    """
    (block,) = parse_agenda_text(text)
    assert block["request"].endswith("on the preliminary plat of the Eastside Acres subdivision")
    assert block["location"] == "6025 East Colorado Blvd."

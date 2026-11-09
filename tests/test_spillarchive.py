"""
tests/test_spillarchive.py

The spill archive tool: report numbers, reading the state's fillable forms (a real
2026 report) and scanned ones (from OCR text), dates, and the one-row summary.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from spillarchive import extract, layer, scanned

FIXTURE = Path(__file__).parent / "fixtures" / "spills" / "2026.148.pdf"


@pytest.mark.parametrize(
    "raw, number",
    [(2026.146, {"number": "2026.146", "year": 2026, "series": "spill"}),
     (93.042, {"number": "1993.042", "year": 1993, "series": "spill"}),
     (2026005.0, {"number": "2026005", "year": 2026, "series": "tank check"}),
     (93047.0, {"number": "93047", "year": 1993, "series": "tank check"}),
     (9999.0, {"number": "9999", "year": None, "series": "placeholder"})],
)  # fmt: skip
def test_report_numbers(raw, number):
    assert layer.number(raw) == number


def test_fillable_spill_report_reads_every_answer():
    result = extract.read_pdf(FIXTURE, engine="none")
    (report,) = [f for f in result["forms"] if f["form"] == "spill report"]
    assert report["method"] == "fields" and report["page"] == 1
    assert report["case_number"] == "2026.148"
    assert (report["reported_date"], report["reported_time"]) == ("9/21/26", "11:40 PM")
    assert report["spill_date"] == "9/18/26"
    assert report["reporter_organization"] == "M.G. Oil Co." and report["reporter_type"] == "Discharger"
    assert report["materials"] == [
        {"name": "Diesel #2 - total released", "quantity": "1400", "units": "gallons"},
        {"name": "Diesel #2 - outside containment", "quantity": "126", "units": "gallons"},
    ]
    assert report["source"] == ["AST"] and report["source_description"] == "bulk AST"
    assert report["regulated_tank_facility"] and report["tank_facility_id"] == "4900052"
    assert report["medium"] == ["Land"] and report["cause"] == ["Operational Error"]
    assert report["cause_description"] == "Overfill - wrong AST filled"
    assert report["response_action"].startswith("Hired AET.")
    assert (report["city"], report["county"]) == ("Sturgis", "Meade")


OCR_2020 = """South Dakota Spill Report Form
Reported: (mm/dd/yy) 05/08/20  Time:  Recorded By:
Reported By: Kevin Goyer
Street or Approx. Location: As Above in B
City: Box Elder  County: Meade  State: SD
Spill Date: (mm/dd/yy) 05/07/20  Spill Time:
Source of Spill: AST UST
Description: equipment issue while fueling - stuck open
ACTIONS Response Action Taken: Stopped fueling activity, applied absorbents
and will pick up absorbents.
Responding Agency: DANR
Comments: COMMENTS Department of Environment and Natural Resources"""


def test_scanned_report_reads_labeled_answers():
    form = scanned.read(OCR_2020)
    assert form["form"] == "spill report"
    assert form["reported_date"] == "05/08/20" and form["spill_date"] == "05/07/20"
    assert form["reported_by"] == "Kevin Goyer" and form["county"] == "Meade"
    assert form["source_description"] == "equipment issue while fueling - stuck open"
    assert form["response_action"] == "Stopped fueling activity, applied absorbents and will pick up absorbents."
    assert "comments" not in form  # only the form's own footer: nothing written


def test_not_a_form():
    assert scanned.read("Patch II 10-0133 2020.042") is None


@pytest.mark.parametrize(
    "value, hint, iso",
    [("9/18/26", 2026, "2026-09-18"), ("09/03/26", 2026, "2026-09-03"), ("9/17/2026", 2026, "2026-09-17"),
     ("08/15/02", 2002, "2002-08-15"), ("12/21/86", 1986, "1986-12-21"), ("Unknown", 2002, ""),
     ("13/40/02", 2002, "")],
)  # fmt: skip
def test_dates(value, hint, iso):
    assert extract.iso_date(value, hint) == iso


def test_summary_prefers_the_exact_reading():
    spill = {"number": "2026.148", "year": 2026}
    url = "https://danr.sd.gov/spillimages/2026/2026.148.pdf"
    readings = {"2026.148.pdf": {"forms": [
        {"form": "spill report", "method": "ocr", "page": 2, "spill_date": "9/1/26"},
        {"form": "spill report", "method": "fields", "page": 1, "spill_date": "9/18/26", "cause": ["Dumping"]},
        {"form": "follow-up", "method": "fields", "page": 3, "cleanup_date": "9/19/2026", "contractor": "AET"},
    ]}}  # fmt: skip
    row = extract.summarize(spill, [url], readings)
    assert row["spill_date"] == "2026-09-18" and row["report"]["read_from"] == "fields"
    assert row["follow_up"]["contractor"] == "AET" and row["pdfs"] == [url]


# blank answers on scanned forms: the next line is the next label, never the answer
BLANK_REPORT = """South Dakota Spill Report Form
Reported By:
Organization Name: OEM  Discharger   Public ✓ State  Local  Federal
A.  REPORTER  Phone:  Email:
Name:
Address:
State: Zip:
Street or Approx. Location:
c  INCIDENT DATE  & LOCATION
Survey Description: 44.1561, -103.09602
City: County: Meade State: Zip:
SNOITCA Response Action Taken:
.K
DEIFITON Responding Agency: DANR Local Discharger Federal EPA Other
"""

BLANK_FOLLOW_UP = """INCIDENT FOLLOW-UP REPORT
NAME/TYPE OF PRODUCT SPILLED:
TOTAL AMOUNT OF PRODUCT SPILLED:  Approximately 40 gallons
SPILL DATE:  DATE CLEANUP OCCURRED:
SPILL LOCATION (physical address, directions, distance to nearest intersection or landmark, etc.):
630 E Summit St, Lead, SD
CONSULTANT / CLEANUP CONTRACTOR (if applicable):
MAILING ADDRESS
CITY/STATE:  TELEPHONE NUMBER:
"""


def test_blank_answers_dont_take_the_next_label():

    report = scanned.read(BLANK_REPORT)
    for key in ("reported_by", "discharger", "response_action"):
        assert key not in report, (key, report.get(key))
    # the street line is blank; the survey's coordinates say where
    assert report["location"] == "44.1561, -103.09602"
    follow = scanned.read(BLANK_FOLLOW_UP)
    assert follow["amount"] == "Approximately 40 gallons"
    for key in ("product", "cleanup_date", "contractor"):
        assert key not in follow, (key, follow.get(key))


def test_old_readings_are_brought_up_to_date_from_their_text():

    saved = {
        "version": 2,
        "pages": [
            {"n": 1, "method": "ocr", "text": BLANK_REPORT},
            {"n": 2, "method": "fields", "form": "spill report"},
        ],
        "forms": [
            {"form": "spill report", "page": 1, "method": "ocr", "reported_by": "Organization Name: OEM"},
            {"form": "spill report", "page": 2, "method": "fields", "discharger": "Westco"},
            {"form": "follow-up", "page": 3, "method": "fields", "contractor": "ERTS"},
        ],
    }
    new = extract.reread(saved)
    assert new["version"] == extract.VERSION
    assert [(f["page"], f["method"]) for f in new["forms"]] == [(1, "ocr"), (2, "fields"), (3, "fields")]
    assert "reported_by" not in new["forms"][0] and new["forms"][1]["discharger"] == "Westco"


def test_pages_are_let_go_as_they_are_read(monkeypatch):
    # pdfplumber keeps a page's contents until it's closed; a 14,000-page case file ran the computer out of memory
    import pdfplumber

    closed, finished = [], []
    close_page, close_pdf = pdfplumber.page.Page.close, pdfplumber.pdf.PDF.close

    def page_close(self):
        if not finished:  # closing the PDF closes its pages too, but by then it's too late to help
            closed.append(self.page_number)
        close_page(self)

    def pdf_close(self):
        finished.append(True)
        close_pdf(self)

    monkeypatch.setattr(pdfplumber.page.Page, "close", page_close)
    monkeypatch.setattr(pdfplumber.pdf.PDF, "close", pdf_close)
    result = extract.read_pdf(FIXTURE, "none")
    assert closed == [p["n"] for p in result["pages"]]

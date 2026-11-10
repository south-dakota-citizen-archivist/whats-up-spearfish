"""
Fillable forms: the state's Spill Report Form and Incident Follow-Up Report, filled
in on a computer, keep every answer in a form field. Field names differ between
versions of the forms and are often mangled ('T me' for Time, 'Spi Date MMDDYY'),
so answers are read by where they sit on the page instead:

  a text field   the printed label just to its left on the same line ("Recorded By:")
  a checked box  the option printed just to its right ("☑ UST"), under the question
                 that starts its row ("Source of Spill:")

and the label's section of the form (A. Reporter … K. Comments) tells apart
questions asked twice (the reporter's City and the spill's City).
"""

from __future__ import annotations

import re

# The generic reading by position lives in sddocs; the spill forms' sections, options and
# keys stay here
from sddocs.forms import key as _key
from sddocs.forms import label_left as _label_left
from sddocs.forms import mid as _mid
from sddocs.forms import option_right as _option_right
from sddocs.forms import same_line as _same_line
from sddocs.forms import section_at as _section
from sddocs.forms import section_starts, upright_words, widgets

# Spill Report Form sections, by the label that opens each (top to bottom)
REPORT_SECTIONS = (
    ("reporter", ("Reported By",)),
    ("discharger", ("Name",)),
    ("incident", ("Spill Date",)),
    ("material", ("Material type",)),
    ("source", ("Source of Spill",)),
    ("medium", ("Medium Affected",)),
    ("cause", ("Reported Cause",)),
    ("damages", ("# of Injuries", "of Injuries")),
    ("response", ("Response Action Taken",)),
    ("notified", ("Responding Agency",)),
    ("comments", ("Comments",)),
)

# Checkbox options, by question; the longest that starts the text right of the box wins
OPTIONS = {
    "reporter_type": ("Discharger", "Public", "State", "Local", "Federal"),
    "material_type": ("Hazardous Substance", "Oil", "Material Unknown", "Other"),
    "units": ("lb.", "bbl.", "gal.", "oth."),
    "source": ("AST", "UST", "Railway", "Transport", "Fixed Facility", "Pipeline", "Highway", "Other"),
    "medium": ("Air", "Land", "Water", "Groundwater", "Within Facilities Only"),
    "cause": ("Transportation Accident", "Operational Error", "Dumping", "Equipment Failure", "Natural Phenomenon",
              "Unknown", "Other"),
    "responding_agency": ("DANR", "Local", "Discharger", "Federal EPA", "Other"),
}  # fmt: skip

UNITS = {"lb.": "lb", "bbl.": "barrels", "gal.": "gallons", "oth.": "other"}


def _section_starts(words) -> list[tuple[str, float]]:
    """Where each of the Spill Report Form's sections begins."""
    return section_starts(words, REPORT_SECTIONS)


def spill_report(page) -> dict:
    """The answers on a Spill Report Form page."""
    words = upright_words(page)
    starts = _section_starts(words)
    filled = widgets(page)
    answers: dict = {"form": "spill report"}
    raw: dict = {}
    materials: dict[int, dict] = {}
    rows: list[float] = []
    for f in sorted(filled, key=lambda f: f["top"]):
        if _section(_mid(f), starts) == "material" and (not rows or f["top"] - rows[-1] > 8):
            rows.append(f["top"])

    def row_of(f) -> int:
        return min(range(len(rows)), key=lambda i: abs(rows[i] - f["top"])) if rows else 0

    for f in sorted(filled, key=lambda f: (f["top"], f["x0"])):
        section = _section(_mid(f), starts) or "header"
        if f["type"] == "text":
            label = _label_left(words, f)
            if section == "material":
                # columns by the box's middle: Material (to ~250), Quantity Spilled, Spilled in Water (from ~366)
                center = (f["x0"] + f["x1"]) / 2
                column = "name" if center < 250 else "quantity" if center < 366 else "in_water"
                materials.setdefault(row_of(f), {})[column] = f["value"]
                continue
            key = f"{section}.{_key(label) or _key(f['name'])}"
            raw[key] = f["value"] if key not in raw else raw[key] + "; " + f["value"]
            continue
        # a checked box
        line = " ".join(w["text"] for w in _same_line(words, f["top"], f["bottom"]))
        if f["x0"] < 100:  # the sideways "As in A/B above" boxes at the left edge
            answers[
                "discharger_same_as_reporter"
                if section in ("discharger", "reporter")
                else "location_same_as_discharger"
            ] = True
        elif "Organization Name" in line:
            answers["reporter_type"] = _option_right(words, f, OPTIONS["reporter_type"])
        elif section == "material" and re.search(r"\b(lb|bbl|gal|oth)\.", line) and f["x0"] > 400:
            unit = _option_right(words, f, OPTIONS["units"])
            materials.setdefault(row_of(f), {})["units"] = UNITS.get(unit, unit)
        elif section == "material" and f["x0"] > 380:
            materials.setdefault(row_of(f), {})["in_water"] = True
        elif section == "material":
            answers.setdefault("material_type", []).append(_option_right(words, f, OPTIONS["material_type"]))
        elif section == "source" and "Regulated Tank" in line:
            answers["regulated_tank_facility"] = True
        elif section in ("source", "medium", "cause"):
            answers.setdefault(section, []).append(_option_right(words, f, OPTIONS[section]))
        elif section == "notified":
            answers.setdefault("responding_agency", []).append(_option_right(words, f, OPTIONS["responding_agency"]))
        else:
            raw.setdefault("checked", []).append(f"{section}: {' '.join(line.split()[:6])}")

    if materials:
        answers["materials"] = [materials[i] for i in sorted(materials)]
    answers.update(_report_summary(raw))
    answers["fields"] = raw
    return answers


def _bare(key: str) -> str:
    """A key without the letters the forms' field names lose ('Act on' for 'Action', 'Spi ed' for
    'Spilled'): the i's and l's, and anything not a letter or digit."""
    return re.sub(r"[il\W_]", "", key.lower())


def _first(raw: dict, *keys: str) -> str:
    for k in keys:
        for name, value in raw.items():
            if _bare(name).startswith(_bare(k)):
                return value
    return ""


def _report_summary(raw: dict) -> dict:
    """The answers people look for, under steady names, from the labeled fields."""
    out = {
        "case_number": _first(raw, "header.case"),
        "reported_date": _first(raw, "header.reported_mm_dd_yy", "header.reported"),
        "reported_time": _first(raw, "header.time"),
        "recorded_by": _first(raw, "header.recorded_by"),
        "reported_by": _first(raw, "reporter.reported_by"),
        "reporter_organization": _first(raw, "reporter.organization_name"),
        "discharger": _first(raw, "discharger.name"),
        "spill_date": _first(raw, "incident.spill_date"),
        "spill_time": _first(raw, "incident.spill_time"),
        "location": _first(raw, "incident.street_or_approx_location", "incident.street"),
        "survey_description": _first(raw, "incident.survey_description"),
        "city": _first(raw, "incident.city"),
        "county": _first(raw, "incident.county"),
        "source_description": _first(raw, "source.description"),
        "tank_facility_id": _first(raw, "source.tank_facility_id", "source.regulated_tank_facility"),
        "waterway_affected": _first(raw, "medium.waterway_affected"),
        "cause_description": _first(raw, "cause.description"),
        "injuries": _first(raw, "damages.of_injuries"),
        "fatalities": _first(raw, "damages.of_fatalities"),
        "response_action": _first(raw, "response.response_action_taken"),
        "agencies_notified": _first(raw, "notified.agencies_notified"),
        "comments": _first(raw, "comments.comments"),
    }
    return {k: v for k, v in out.items() if v}


# Incident Follow-Up Report: its field names are whole questions ("DATE CLEANUP OCCURRED"),
# with _2, _3 … for the same question again in a later part (the property owner, the contractor)
FOLLOW_UP_PARTS = {"": "responsible_party", "_2": "property_owner", "_3": "contractor"}
FOLLOW_UP_KEYS = {
    "danr_case_file": "case_number",
    "nametype_of_product_spilled": "product",
    "name_type_of_product_spilled": "product",
    "total_amount_of_product_spilled": "amount",
    "was_surface_water_or_ground_water_impacted_by_the_spill": "water_impacted",
    "spill_date": "spill_date",
    "date_cleanup_occurred": "cleanup_date",
    "land_use": "land_use",
    "responsible_party": "responsible_party",
    "consultant_cleanup_contractor_if_applicable": "contractor",
    "insurance_provider_if_applicable": "insurance",
    "was_soil_excavated": "soil_excavated",
    "was_spill_contained_to_immediate_area": "contained",
    "response_action_and_additional_work_planned": "response_action",
    "form_completed_by": "completed_by",
    "date": "completed_date",
}


FOLLOW_UP_CONTACT = {"mailing_address": "address", "citystate": "city", "telephone_number": "phone"}


def follow_up(pages) -> dict:
    """The answers on an Incident Follow-Up Report (one or two pages)."""
    answers: dict = {"form": "follow-up"}
    raw: dict = {}
    for page in pages:
        for f in widgets(page):
            name = f["name"]
            if f["type"] == "check":
                words = page.extract_words()
                raw.setdefault("checked", []).append(_option_right(words, f, ()) or name)
                continue
            m = re.match(r"(.*?)(_\d+)?$", name)
            base, part = _key(m.group(1)), m.group(2) or ""
            base = re.sub(r"_?\d+$", "", base) if base.startswith("spill_location") else base
            if base.startswith("spill_location"):
                base = "spill_location"
            elif base.startswith("land_use"):
                base = "land_use"
            raw[f"{base}{part}"] = f["value"]
            key = FOLLOW_UP_KEYS.get(base)
            if base == "spill_location":
                answers["location"] = f["value"]
            elif key and not part:
                answers.setdefault(key, f["value"])
            elif part in FOLLOW_UP_PARTS and base in ("mailing_address", "citystate", "telephone_number"):
                who = FOLLOW_UP_PARTS[part]
                answers.setdefault(f"{who}_{FOLLOW_UP_CONTACT[base]}", f["value"])
    answers["fields"] = raw
    return answers


def form_kind(page) -> str | None:
    """Which form a page is, from its heading; None when it isn't one of them."""
    head = " ".join((page.extract_text() or "").split("\n")[:3]).lower()
    if "spill report form" in head:
        return "spill report"
    if "incident follow-up report" in head or "incident follow up report" in head:
        return "follow-up"
    return None

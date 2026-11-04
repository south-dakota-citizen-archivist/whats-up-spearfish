"""
Scanned forms, read from OCR text. The state's paper forms changed over the years:

  1980s – 1990s   "SD DWNR Oil & Hazardous Spill Report Form": DATE, NAME (the material),
                  AMOUNT SPILLED, mostly filled in by hand
  1990s – 2020    "South Dakota Spill Report Form", typed: "Spill Date: (mm/dd/yy) 08/15/02",
                  "Street or Approx. Location: …", "Name: …", "Description: …"
  2021 on         the same form, filled in on a computer (see forms.py)

OCR can't reliably tell a checked box from an empty one, so only written answers are
read here, and only where a label and its answer come through; everything else is in
the page's full text. Every value read this way is marked as OCR, to be read with care.
"""

from __future__ import annotations

import re

DATE = r"(\d{1,2}\s*[/\-.]\s*\d{1,2}\s*[/\-.]\s*\d{2,4})"
# labels that end an answer that runs over several lines
STOP = re.compile(
    r"^(Responding Agency|Agencies Notified|Comments|Response Action|Reported Cause|Medium Affected|Source of Spill|"
    r"Material Type|# of Injuries|Waterway Affected|Spill Date|Name:|Address:|City:|Phone:)",
    re.I,
)


def kind(text: str) -> str | None:
    head = text[:600].lower()
    if "spill report form" in head and ("oil" in head and "hazardous" in head and "dwnr" in head.replace(" ", "")):
        return "old spill report"
    if "spill report form" in head:
        return "spill report"
    if "follow-up report" in head or "follow up report" in head:
        return "follow-up"
    if "hazardous spill report" in head:
        return "old spill report"
    return None


def _after(text: str, pattern: str, multiline: bool = False) -> str:
    m = re.search(pattern, text, re.I | re.M)
    if not m:
        return ""
    value = m.group(1).strip(" :|_-")
    if multiline:
        more = []
        for line in text[m.end() :].split("\n")[1:6]:
            if not line.strip() or STOP.match(line.strip()):
                break
            more.append(line.strip())
        value = " ".join([value, *more]).strip()
    # an answer ends where the next label on the line begins
    value = re.split(r"\s{2,}[A-Z][\w .#()/]{1,30}:", value)[0]
    return _tidy(value)


# the form's own words that OCR can run into an answer: section titles in the margin, the footer
_NOISE = re.compile(
    r"^(?:\S{1,2}\s+)?(ACTIONS?|COMMENTS?|DAMAGES?|CAUSE|SOURCE|MATERIAL|NOTIFIED|INCIDENT|LOCATION|DATE|REPORTER|MED\.?)\b\s*|"
    r"\s*Department of (Environment|Agriculture) and Natural Resources.*$|\s*Department of Water & Natural.*$",
    re.I,
)
_CHECKBOX_ROW = re.compile(r"□|Quantity Spilled|Spilled in Water|\(Check", re.I)


def _tidy(value: str) -> str:
    """An answer without the form's own words around it; '' if what's left isn't readable."""
    value = " ".join(value.split())
    if re.fullmatch(DATE, value):
        return value
    for _ in range(2):
        value = _NOISE.sub("", value).strip(" :|_-")
    if _CHECKBOX_ROW.search(value):
        return ""
    letters = re.findall(r"[A-Za-z]", value)
    if len(letters) < 4 or re.search(r"[\u3000-\u9fff]", value):  # too little to mean anything, or misread
        return ""
    # mostly fragments ('Ro o d p d tet'): handwriting the OCR couldn't read
    tokens = value.split()
    words = [w for w in tokens if len(re.sub(r"[^A-Za-z]", "", w)) >= 3]
    if not words or (len(tokens) >= 3 and len(words) / len(tokens) < 0.5):
        return ""
    return value[:500]


def _after_section(text: str, section: str, pattern: str, multiline: bool = False) -> str:
    m = re.search(section, text, re.I)
    return _after(text[m.start() :], pattern, multiline) if m else ""


def spill_report(text: str) -> dict:
    """What a typed (1990s – 2020) Spill Report Form says, as far as OCR can tell."""
    out = {
        "form": "spill report",
        "reported_date": _after(text, r"Reported:?\s*(?:\(mm/dd/yy\))?\s*" + DATE),
        "spill_date": _after(text, r"Spill Date:?\s*(?:\(mm/dd/yy\))?\s*" + DATE),
        "reported_by": _after(text, r"Reported By:\s*(.+)$"),
        "discharger": _after_section(text, r"Responsible Party|DISCHARGER", r"^\s*Name:\s*(.+)$"),
        "location": _after(text, r"Street or Approx\.?\s*Location:\s*(.+)$"),
        "material": _after(text, r"Material Type\s*\(Code/Name\):?\s*(.+)$"),
        "source_description": _after_section(text, r"Source of Spill", r"Description:\s*(.+)$"),
        "cause_description": _after_section(text, r"Reported Cause", r"Description:\s*(.+)$"),
        "response_action": _after(text, r"Response Action Taken:\s*(.*)$", multiline=True),
        "comments": _after(text, r"Comments:\s*(.*)$", multiline=True),
    }
    county = re.findall(r"County:\s*([A-Z][A-Za-z ]{2,20}?)(?:\s{2,}|\s+State:|$)", text, re.M)
    if county:
        out["county"] = county[-1].strip()
    return {k: v for k, v in out.items() if v}


def old_spill_report(text: str) -> dict:
    """The 1980s – 1990s Oil & Hazardous Spill Report Form (often handwritten)."""
    out = {
        "form": "spill report",
        "spill_date": _after(text, r"\bDATE\s*" + DATE),
        "material": _after_section(text, r"MATERIAL SPILLED", r"\bNA[MN]E\s+(.+)$"),
        "location": _after(text, r"FACILITY OR SPILL LOCATION\s*(.+)$"),
    }
    return {k: v for k, v in out.items() if v}


def follow_up(text: str) -> dict:
    out = {
        "form": "follow-up",
        "product": _after(text, r"TYPE OF PRODUCT SPILLED:?\s*(.+)$"),
        "amount": _after(text, r"TOTAL AMOUNT OF PRODUCT SPILLED:?\s*(.+)$"),
        "spill_date": _after(text, r"SPILL DATE:?\s*" + DATE),
        "cleanup_date": _after(text, r"DATE CLEANUP OCCURRED:?\s*(.+)$"),
        "responsible_party": _after(text, r"RESPONSIBLE PARTY:?\s*(.+)$"),
        "contractor": _after(text, r"CONSULTANT.{0,40}?CONTRACTOR.{0,20}?:\s*(.+)$"),
        "soil_excavated": _after(text, r"WAS SOIL EXCAVATED\??:?\s*(\w+)"),
    }
    return {k: v for k, v in out.items() if v}


def read(text: str) -> dict | None:
    """The form on a scanned page, if it's one of the state's, with what could be read."""
    k = kind(text)
    if k == "spill report":
        return spill_report(text)
    if k == "old spill report":
        return old_spill_report(text)
    if k == "follow-up":
        return follow_up(text)
    return None

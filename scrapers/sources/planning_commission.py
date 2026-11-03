"""
scrapers/sources/planning_commission.py

Planning applications heard by the Spearfish Planning Commission, from the
city's CivicClerk agendas. With the city's OpenGov portal closed to the public
(2026), these agendas are the public record of new planning applications:
variances, conditional uses, plats, rezones, annexations, design review.

Since August 2025 CivicClerk publishes each agenda item separately, with its
attachments (plans, plats, sketches) and a staff report whose first page is a
fixed template:

    Request:         Make a recommendation on … a variance … for 1407 Charles Street
    Applicant:       Andy Van Deest.
    Location:        1407 Charles Street
    Recommendation:  Staff recommends …
    Public Hearing:  No                       (legal description in a right column)

Each run looks at recent and upcoming meetings (LOOKBACK_DAYS) and reads staff
reports only for items it hasn't parsed yet, or whose meeting is still ahead
(reports can change until then). Records are kept indefinitely.

Links point at the public portal (portal.civicclerk.com/event/…/files/…), never
at the API's file URLs: those are signed, expire within days and carry write
permission.
"""

from __future__ import annotations

import io
import re
from datetime import timedelta

from scrapers import dates, geo, net
from scrapers.base import BaseScraper

API = "https://spearfishsd.api.civicclerk.com/v1"
PORTAL = "https://spearfishsd.portal.civicclerk.com"
HEADERS = {"Accept": "application/json", "User-Agent": "Mozilla/5.0"}
LOOKBACK_DAYS = 120
FIRST_ITEMIZED = "2025-08-01"  # earlier meetings have only agenda/minutes PDFs (see the backfill plan)

# Application types, most specific first. Matched against the item's request text.
APP_TYPES = [
    ("Variance", r"variance"),
    ("Conditional use permit", r"conditional use"),
    (
        "Rezone",
        r"\brezon|zoning (map )?amendment|change (of|in) zoning|zoning (district )?(designation|change)"
        r"|boundary between .{0,60} zoning",
    ),
    ("Preliminary plat", r"preliminary plat"),
    ("Final plat", r"final plat"),
    ("Minor plat", r"minor plat"),
    ("Plat", r"\bplat\b|replat"),
    ("Annexation", r"annex"),
    ("Vacation of right-of-way or easement", r"\bvacat"),
    (
        "Planned development",
        r"planned (unit |residential )?development|\bPUD\b|\bDRD\b|development review district"
        r"|concept(ual)?[ /]+(final )?plan|final plan\b|master plan|phase \w+ .{0,5}final plan",
    ),
    ("Design review", r"design review|site plan|building exterior"),
    ("Tax increment financing district", r"\bTIF\b|tax increment"),
    ("Downtown redevelopment incentive", r"redevelopment incentive"),
    ("Exception to requirements", r"\bexception\b"),
    ("Area plan or study", r"corridor|area study|land use plan"),
    ("Sign", r"\bsign\b"),
    ("Comprehensive plan amendment", r"comprehensive plan"),
    (
        "Code amendment",
        r"ordinance|code amendment|text amendment|amend(ing|ment to)? (the )?(city )?(code|chapter|section)"
        r"|revisions? to (the )?(city )?(code|chapter)|land use code",
    ),
    ("Subdivision", r"subdivision"),
]
# Types that change the rules everywhere rather than at one site
NOT_A_SITE = {"Code amendment", "Comprehensive plan amendment", "Area plan or study"}
# Locations that aren't one place: whole zoning districts, the city, or the meeting room
_NOT_A_PLACE = re.compile(
    r"^(city[- ]?wide|all\b|to be determined)|zoning districts?\.?$|council cham|625 (fifth|5th) st", re.I
)

LABELS = {
    "request": "request",
    "applicant": "applicant",
    "owner": "owner",
    "agent": "agent",
    "location": "location",
    "recommendation": "recommendation",
    "action": "recommendation",
    "public hearing": "public_hearing",
}
_LABEL_RE = re.compile(r"^(%s):?$" % "|".join(re.escape(k) for k in LABELS), re.I)
_LEGAL_RE = re.compile(r"\b(lot|lots|block|tract|section|addition|subdivision|parcel)\b", re.I)
_STREET_RE = re.compile(
    r"\b\d{1,6}\s+(?:[NSEW]\.?\s+)?[A-Z0-9][\w.']*(?:\s+[A-Z][\w.']*){0,3}\s+"
    r"(?:Street|St|Avenue|Ave|Drive|Dr|Road|Rd|Lane|Ln|Boulevard|Blvd|Court|Ct|Circle|Cir|Place|Pl|Way|Parkway|Pkwy"
    r"|Loop|Trail|Highway|Hwy|Terrace)\b\.?(?:\s+[NSEW]\b)?",
)


# Changes to the zoning code's text, whatever part of it they touch (signs, conditional uses…)
_CODE_TEXT = re.compile(
    r"zoning (ordinance )?text|text amendment|\b1[56]\d\.\d{3}\b|appendix a\b|chapter 15[0-9]|"
    r"(sign|zoning) (ordinance|regulations?|code)( update)?\b(?! for)|permitted uses|ordinance (update|text)|"
    r"setback requirements for|zoning setbacks|revised ordinances|parking requirements|energy systems|"
    r"rv parking",
    re.I,
)


# The city's project numbers name the type: [PROJECT ID: CUP19-001]
_PROJECT_TYPES = {
    "CUP": "Conditional use permit",
    "VAR": "Variance",
    "CZN": "Rezone",
    "RZ": "Rezone",
    "DRD": "Planned development",
    "ORD": "Code amendment",
    "ANX": "Annexation",
}
_PROJECT_ID = re.compile(r"\b(%s)\d{2}-\d{3}\b" % "|".join(_PROJECT_TYPES))
# A variance for one site, even when its wording quotes the zoning code it varies from
_SITE_VARIANCE = re.compile(r"^(approve |review )?(a )?variances?\b|\b(a|for a) variance\b", re.I)


def app_type(text: str) -> str:
    text = text or ""
    if m := _PROJECT_ID.search(text):
        return _PROJECT_TYPES[m.group(1)]
    if _SITE_VARIANCE.search(text):
        return "Variance"
    if _CODE_TEXT.search(text):
        return "Code amendment"
    for name, pattern in APP_TYPES:
        if re.search(pattern, text or "", re.I):
            return name
    return "Other"


def street_address(*texts: str) -> str:
    """The first street address ('1407 Charles Street') found in the given texts."""
    for t in texts:
        if m := _STREET_RE.search(t or ""):
            return m.group(0).rstrip(".")
    return ""


# ── staff report ─────────────────────────────────────────────────────────────


def _lines(words: list[dict]) -> list[list[dict]]:
    """Group pdfplumber words into lines (similar top), each sorted left to right."""
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(lines[-1][0]["top"] - w["top"]) < 3:
            lines[-1].append(w)
        else:
            lines.append([w])
    return [sorted(line, key=lambda w: w["x0"]) for line in lines]


def parse_staff_report_words(words: list[dict]) -> dict:
    """
    The header fields of a staff report's first page, from pdfplumber words.

    Labels sit in a left column and values in a middle column; the legal
    description (and sometimes a map caption) can sit in a right column beside
    them, which plain text extraction would interleave with the values. A wide
    horizontal gap on a line marks where the right column starts.
    """
    lines = _lines(words)
    fields: dict[str, list[str]] = {}
    side: list[str] = []
    current = None
    started = False
    value_x = None
    for line in lines:
        first = line[0]
        label = None
        rest = line
        if first["x0"] < 120:
            two = " ".join(w["text"] for w in line[:2]).rstrip(":").lower()
            one = first["text"].rstrip(":").lower()
            if two in LABELS and first["text"].lower() == "public":
                label, rest = two, line[2:]
            elif one in LABELS and first["text"].endswith(":"):
                label, rest = one, line[1:]
            elif started:
                break  # body text begins (e.g. "Project Summary")
        if label:
            current, started = LABELS[label], True
        if not started:
            continue
        if rest and value_x is None:
            value_x = rest[0]["x0"]
        value, extra = [], []
        for i, w in enumerate(rest):
            gap = w["x0"] - rest[i - 1]["x1"] if i else 0
            if extra or gap > 25 or (i == 0 and value_x is not None and w["x0"] > value_x + 150):
                extra.append(w["text"])
            else:
                value.append(w["text"])
        if value and current:
            fields.setdefault(current, []).extend(value)
        if extra:
            side.append(" ".join(extra))
    out = {k: " ".join(v).strip() for k, v in fields.items()}
    legal = " ".join(side).strip()
    if _LEGAL_RE.search(legal):
        out["legal_description"] = legal
    return out


def read_staff_report(url: str) -> dict:
    import pdfplumber

    resp = net.get(url, timeout=60)
    resp.raise_for_status()
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        words = pdf.pages[0].extract_words(keep_blank_chars=False)
    return parse_staff_report_words(words)


def parse_agenda_text(text: str) -> list[dict]:
    """
    Labeled application blocks from an agenda PDF's text:

        1.   Request:        A variance to reduce the required side-yard setback …
             Applicant:      Andy Van Deest.
             Location:       1407 Charles Street
             Recommendation: Staff recommends denial …
    """
    blocks: list[dict] = []
    current: dict | None = None
    key = None
    # older agendas: "ACTION (Revised):", and the odd stray mark before a label
    label_re = re.compile(
        r"^\s*[^\w\s]?\s*(?:\d+\.\s*)?(%s)\s*(?:\([^)]*\))?\s*:\s*(.*)$" % "|".join(re.escape(k) for k in LABELS),
        re.I,
    )
    for raw in text.splitlines():
        line = raw.rstrip()
        if m := label_re.match(line):
            label, value = m.group(1).lower(), m.group(2).strip()
            if label == "request":
                current = {}
                blocks.append(current)
            if current is not None:
                key = LABELS[label]
                current[key] = value
            continue
        stripped = line.strip()
        if not stripped:
            # a blank line ends a field that's finished a sentence; one cut off mid-sentence
            # ("…to City Council on the") continues after it
            if key and current is not None and re.search(r"[.;:)]$", current[key]):
                key = None
            continue
        if current is None:
            continue
        # a new outline entry ("G. Items for Action", "2. Approve …") ends the block
        if re.match(r"^([A-Z]|\d+)\.\s", stripped) and not raw.startswith(" " * 12):
            current, key = None, None
            continue
        if key:
            current[key] = (current[key] + " " + stripped).strip()
    return blocks


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (s or "").lower()).strip()


def read_agenda(file_id: int) -> list[dict]:
    import pdfplumber

    resp = net.get(
        f"{API}/Meetings/GetMeetingFileStream(fileId={file_id},plainText=false)", headers=HEADERS, timeout=60
    )
    resp.raise_for_status()
    with pdfplumber.open(io.BytesIO(resp.content)) as pdf:
        text = "\n".join(page.extract_text(layout=True) or "" for page in pdf.pages)
    return parse_agenda_text(text)


def match_agenda(item_name: str, blocks: list[dict]) -> dict:
    """The agenda block whose request matches an item's name (agendas are generated from the items)."""
    target = _norm(item_name)[:80]
    for b in blocks:
        req = _norm(b.get("request", ""))
        if target and (req.startswith(target[:60]) or target.startswith(req[:60])):
            return b
    return {}


# ── agenda items ─────────────────────────────────────────────────────────────


def application_items(items: list[dict]) -> list[tuple[dict, str]]:
    """(item, section name) for agenda items that are applications, walking the outline."""
    out = []

    def walk(nodes, section):
        for n in nodes:
            name = (n.get("agendaObjectItemName") or "").strip()
            kids = n.get("childItems") or []
            if kids:
                walk(kids, name)
                continue
            if re.search(r"minutes", name, re.I) or re.search(
                r"minutes|discussion|informational|presentation", section, re.I
            ):
                continue
            has_report = bool(n.get("reportsList"))
            in_action = re.search(r"action|hearing|business|consent", section, re.I)
            if has_report or (in_action and n.get("attachmentsList")):
                out.append((n, section))

    walk(items, "")
    return out


_NO_PLACE = re.compile(r"^(n/?a|none|tbd|city[- ]?wide|various)\.?$", re.I)
_DOC_TYPES = ("Agenda", "Agenda Packet", "Minutes")


def meeting_docs(event: dict) -> list[dict]:
    """The meeting's agenda, packet and minutes, as links into the public portal (one file each)."""
    files = {f.get("type"): f["fileId"] for f in event.get("publishedFiles") or [] if f.get("fileId")}
    return [
        {"name": t, "url": f"{PORTAL}/event/{event['id']}/files/agenda/{files[t]}"} for t in _DOC_TYPES if t in files
    ]


def item_record(item: dict, section: str, event: dict, report: dict) -> dict:
    eid = event["id"]
    agenda_text = (item.get("agendaObjectItemName") or "").strip()
    request = report.get("request") or agenda_text
    location = report.get("location", "").strip()
    if _NO_PLACE.match(location):
        location = ""
    # The agenda wording names the application; staff report requests are sometimes generic
    # ("Make a recommendation to City Council."), so classify on the agenda text first.
    kind = app_type(agenda_text)
    if kind == "Other":
        kind = app_type(request)
    address = street_address(location, agenda_text, request)
    reports = item.get("reportsList") or []
    report_url = f"{PORTAL}/event/{eid}/files/report/{reports[0]['id']}" if reports else ""
    return {
        "item_id": item["id"],
        "item_number": item.get("agendaObjectItemNumber") or "",
        "event_id": eid,
        "meeting_date": event["startDateTime"],
        "meeting_url": f"{PORTAL}/event/{eid}/files",
        "meeting_docs": meeting_docs(event),
        "section": section,
        "app_type": kind,
        "site": kind not in NOT_A_SITE and bool(address or location) and not _NOT_A_PLACE.search(location),
        "title": f"{kind} — {location or address}" if (location or address) else kind,
        "agenda_text": agenda_text,
        "request": request,
        "applicant": report.get("applicant", ""),
        "owner": report.get("owner", ""),
        "location": location,
        "address": address,
        "address_key": geo.normalize_address(address),
        "recommendation": report.get("recommendation", ""),
        "public_hearing": report.get("public_hearing", ""),
        "legal_description": report.get("legal_description", ""),
        "report_url": report_url,
        "url": report_url or f"{PORTAL}/event/{eid}/files",
        "attachments": [
            {"name": (a.get("fileName") or "").strip(), "url": f"{PORTAL}/event/{eid}/files/attachment/{a['id']}"}
            for a in item.get("attachmentsList") or []
            if a.get("isPublished", True)
        ],
    }


# ── before itemized agendas (2016 – July 2025) ───────────────────────────────
#
# Older meetings have only an agenda PDF (some years a combined packet), whose
# applications use the same Request / Applicant / Location / Action labels. The
# one-time backfill (scripts/backfill_planning_commission.py) reads them with
# parse_agenda_text and turns each block into a record here.

_ACRONYM_RE = re.compile(
    r"\(([A-Z0-9][A-Z0-9-]*)\)|\b([A-Z]{1,3}-?\d+[A-Z]?|[A-Z]*\d[A-Z\d-]*|TIF|DRD|PUD|CUP|LLC|ROW|SD|US|HWY)\b"
)


def sentence_case(text: str) -> str:
    """'CHANGE IN ZONING FROM AGRICULTURE (AG) TO C-2' → 'Change in zoning from agriculture (AG) to C-2'.
    Text that isn't shouting is left alone."""
    letters = [c for c in text if c.isalpha()]
    if not letters or sum(c.isupper() for c in letters) / len(letters) < 0.8:
        return text
    out = list(text.lower())
    for m in _ACRONYM_RE.finditer(text):  # acronyms and lot numbers keep their capitals
        out[m.start() : m.end()] = text[m.start() : m.end()]
    return "".join(out[:1]).upper() + "".join(out[1:])


_STAFF_LINK_RE = re.compile(r"\s*click here to view (the )?staff report\.?", re.I)
_TRAILING_NOTICE_RE = re.compile(r"\s*ADA Compliance:.*$", re.I | re.S)


def agenda_block_record(block: dict, n: int, event: dict) -> dict:
    """A record like an itemized one, from the n-th labeled block of an older meeting's agenda."""
    block = {k: _TRAILING_NOTICE_RE.sub("", _STAFF_LINK_RE.sub("", sentence_case(v))).strip() for k, v in block.items()}
    item = {"id": f"{event['id']}-{n}", "agendaObjectItemName": block.get("request", "")}
    rec = item_record(item, "", event, block)
    rec["from_agenda_pdf"] = True
    return rec


class PlanningCommission(BaseScraper):
    name = "Spearfish Planning Commission applications"
    slug = "planning_commission"
    kind = "planning_item"
    url = f"{PORTAL}/"
    dedup_key = "item_id"
    min_records = 0  # a quiet stretch with no applications is normal
    max_stale_hours = 24 * 7

    #: Set to FIRST_ITEMIZED for a full backfill (python -m scrapers --only planning_commission after editing)
    since: str = ""

    def events(self) -> list[dict]:
        since = self.since or (dates.today() - timedelta(days=LOOKBACK_DAYS)).isoformat()
        flt = f"contains(eventName,'Planning Commission') and startDateTime gt {since}T00:00:00Z"
        out, skip = [], 0
        while True:
            resp = net.get(
                f"{API}/Events",
                params={"$filter": flt, "$orderby": "startDateTime asc", "$skip": skip},
                headers=HEADERS,
            )
            resp.raise_for_status()
            page = resp.json().get("value") or []
            if not page:
                return out
            out += [e for e in page if (e.get("agendaId") or 0) > 0 and "cancel" not in e.get("eventName", "").lower()]
            skip += len(page)

    def scrape(self) -> list[dict]:
        done = {r["item_id"]: r for r in self.load_existing() if r.get("applicant") or r.get("location")}
        today = dates.today().isoformat()
        records = []
        for event in self.events():
            resp = net.get(f"{API}/Meetings/{event['agendaId']}", headers=HEADERS)
            resp.raise_for_status()
            upcoming = event["startDateTime"][:10] >= today
            agenda = None  # read lazily, only if an item has no staff report
            for item, section in application_items(resp.json().get("items") or []):
                prev = done.get(item["id"])
                report = {}
                if prev and not upcoming:
                    report = {
                        k: prev.get(k, "")
                        for k in (
                            "request",
                            "applicant",
                            "owner",
                            "location",
                            "recommendation",
                            "public_hearing",
                            "legal_description",
                        )
                    }
                elif reports := item.get("reportsList"):
                    # The signed file URL is used once, here, and never stored.
                    if url := reports[0].get("pdfMediaFullPath"):
                        try:
                            report = read_staff_report(url)
                        except Exception as exc:  # noqa: BLE001
                            print(f"[{self.slug}] couldn't read staff report for item {item['id']}: {exc}")
                if not report.get("location") and not report.get("applicant"):
                    if agenda is None:
                        agenda = []
                        fid = next(
                            (f["fileId"] for f in event.get("publishedFiles") or [] if f.get("type") == "Agenda"), None
                        )
                        if fid:
                            try:
                                agenda = read_agenda(fid)
                            except Exception as exc:  # noqa: BLE001
                                print(f"[{self.slug}] couldn't read agenda for event {event['id']}: {exc}")
                    report = {**match_agenda(item.get("agendaObjectItemName") or "", agenda), **report}
                rec = item_record(item, section, event, report)
                if rec["app_type"] == "Other" and not (rec["location"] or rec["address"]):
                    continue  # elections, bylaws, appointments: not applications
                records.append(rec)
        coords = geo.geocode(r["address"] for r in records if r["address"])
        for r in records:
            if c := coords.get(r["address_key"]):
                r["lat"], r["lon"] = c
        return records

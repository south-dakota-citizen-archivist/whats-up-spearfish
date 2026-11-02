"""
scrapers/address.py

Address standardization: the one place street addresses are parsed and
turned into keys for matching records across sources (city permits, OpenGov,
Planning Commission agendas, county parcels).

Parsing is usaddress (a probabilistic US address parser); abbreviations follow
USPS Publication 28 via usaddress-scourgify's tables. A thin layer around them
handles what local records throw at it:

- several addresses in one field: "2545 & 2555 CLEAR SPRING RD"
- tags glued to the street: "540 32ND ST-GA OFFICE", "20189 US HWY 85-CAMPGROUND"
- SAINT/ST in street names: "6845 SAINT ONGE RD" = "6845 ST ONGE RD"
- text that isn't an address at all ("Intersection of …"), which is rejected

Two keys per address:

- key():   number + direction + street + type, with the direction moved to the
           front, so "515 27TH ST N" and "515 N 27TH ST" match ("515 N 27TH ST")
- loose(): the same without any direction. The city and county disagree on
           directions ("1440 N MAIN ST" vs "1440 MAIN ST"), so callers fall back
           to it only when it identifies a single place.

Units ("UNIT 3", "STE B", "#4") are kept separately and left out of both keys:
a unit belongs to its building's site.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import usaddress
from scourgify.address_constants import DIRECTIONAL_REPLACEMENTS, STREET_TYPE_ABBREVIATIONS

DIRECTIONS = {"N", "S", "E", "W", "NE", "NW", "SE", "SW"}
_DIRS = {**DIRECTIONAL_REPLACEMENTS, **{d: d for d in DIRECTIONS}}
_TYPES = {k.upper(): v.upper() for k, v in STREET_TYPE_ABBREVIATIONS.items()}
_CITY_TAIL = re.compile(r",?\s*\b(SPEARFISH|SPEARISH|LEAD|DEADWOOD|WHITEWOOD|BELLE FOURCHE)\b.*$")
_STATE_TAIL = re.compile(r",?\s*\bSD\b\.?\s*(\d{5}(-\d{4})?)?\s*$")
_GLUED_TAG = re.compile(r"(?<=[A-Z0-9])-(?=[A-Z]{2,})")  # "ST-GA OFFICE" → "ST GA OFFICE"
_UNIT_WORDS = {"UNIT", "STE", "SUITE", "APT", "BLDG", "LOT", "SPACE", "TRLR", "RM", "#"}


@dataclass(frozen=True)
class Address:
    number: str
    street: str  # street name, e.g. "MAIN", "27TH", "ST ONGE", "US HWY 85"
    type: str = ""  # USPS street type, e.g. "ST", "DR"
    direction: str = ""  # pre- or post-directional, e.g. "N"
    unit: str = ""

    def key(self) -> str:
        return " ".join(x for x in (self.number, self.direction, self.street, self.type) if x)

    def loose(self) -> str:
        return " ".join(x for x in (self.number, self.street, self.type) if x)


def _clean(text: str) -> str:
    s = " ".join((text or "").upper().replace("\n", " ").split())
    s = _STATE_TAIL.sub("", s)
    s = _CITY_TAIL.sub("", s)
    s = _GLUED_TAG.sub(" ", s)
    s = re.sub(r"[^\w\s#&/-]", " ", s)  # periods, commas
    s = re.sub(r"\bSAINT\b", "ST", s)
    return " ".join(s.split())


def _split_multiple(s: str) -> list[str]:
    """'2545 & 2555 CLEAR SPRING RD' → ['2545 CLEAR SPRING RD', '2555 CLEAR SPRING RD']."""
    m = re.match(r"^(\d+[A-Z]?)\s*(?:&|AND|/)\s*(\d+[A-Z]?)\s+(.+)$", s)
    if m:
        return [f"{m.group(1)} {m.group(3)}", f"{m.group(2)} {m.group(3)}"]
    return [s]


def _abbrev_type(word: str) -> str:
    return _TYPES.get(word, word)


def _parse_one(s: str) -> Address | None:
    try:
        tags, _ = usaddress.tag(s)
    except usaddress.RepeatedLabelError:
        return None
    number = tags.get("AddressNumber", "")
    if not re.fullmatch(r"\d+[A-Z]?(-\d+)?", number or ""):
        return None
    pre_type = tags.get("StreetNamePreType", "")
    name = tags.get("StreetName", "")
    # usaddress reads "US HWY 85-CAMPGROUND" as a pre-type plus a glued name; keep the route number only
    if pre_type:
        name = f"{_abbrev_type(pre_type)} {re.match(r'[A-Z0-9]+', name).group(0) if name else ''}".strip()
    if not name:
        return None
    post_type = _abbrev_type(tags.get("StreetNamePostType", ""))
    pre_dir = _DIRS.get(tags.get("StreetNamePreDirectional", ""), "")
    post_dir = _DIRS.get(tags.get("StreetNamePostDirectional", ""), "")
    # "540 32ND ST GA OFFICE": usaddress files "ST GA OFFICE" as a place name; recover the street type
    if not post_type and (place := tags.get("PlaceName", "")):
        first = place.split()[0]
        if first in _TYPES:
            post_type = _abbrev_type(first)
    # A name ending in a street type word ("CLEAR SPRING RD" mis-tagged) gets split back out
    words = name.split()
    if not post_type and not pre_type and len(words) > 1 and words[-1] in _TYPES:
        name, post_type = " ".join(words[:-1]), _abbrev_type(words[-1])
    unit = " ".join(x for x in (tags.get("OccupancyType", ""), tags.get("OccupancyIdentifier", "")) if x)
    if not unit and post_type and (extra := tags.get("OccupancyIdentifier", "")):
        unit = extra
    return Address(number=number, street=name, type=post_type, direction=pre_dir or post_dir, unit=unit)


@lru_cache(maxsize=50_000)
def parse(text: str) -> tuple[Address, ...]:
    """Every street address in a field (usually one); () if there isn't one."""
    s = _clean(text)
    if not s or not re.match(r"^\d", s):
        return ()
    out = []
    for part in _split_multiple(s):
        if a := _parse_one(part):
            out.append(a)
    return tuple(out)


def key(text: str) -> str:
    """Matching key for the first address in text ('' if none)."""
    parsed = parse(text)
    return parsed[0].key() if parsed else ""


def loose(text: str) -> str:
    parsed = parse(text)
    return parsed[0].loose() if parsed else ""


def keys(text: str) -> list[str]:
    """Keys for every address in text (a permit can cover '3813 & 3815 Rock Ridge')."""
    return [a.key() for a in parse(text)]

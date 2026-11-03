"""
sitegen/parcels.py

Lawrence County parcels as the canonical "site" for the permits page. Records
from every source (city building permits, the OpenGov archive, Planning
Commission agendas) are linked to a parcel, most reliable first:

1. standardized street address, exactly
2. the same address without street directions, when only one parcel has it
   (the city writes "1440 N MAIN ST" where the county has "1440 MAIN ST")
3. lot / block / subdivision, parsed from agenda locations and legal descriptions
   ("Lot 2 of Block 2 of the Ruby Ridge Addition")
4. the record's own coordinates inside a parcel outline (only for coordinates
   that came from a parcel-based system, not street-interpolated geocodes)

Matching runs only inside scripts/import_parcels.py, on this laptop, against
a local county parcel snapshot. What it writes, and what the site
build reads, is parcel_links.json (see ParcelLinks below). Without it, the
permits page groups by address as before.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

from scrapers import address

BEACON = (
    "https://beacon.schneidercorp.com/Application.aspx?AppID=1225&LayerID=37418&PageTypeID=4&PageID=14291&KeyValue="
)

_SUB_WORDS = re.compile(r"\b(THE|OF|TO|CITY|SPEARFISH|LAWRENCE|COUNTY|SOUTH|DAKOTA|SD)\b")
_SUB_KIND = {"S/D": "SUBDIVISION", "SUB": "SUBDIVISION", "ADDN": "ADDITION", "ADD": "ADDITION"}
_KIND = r"(?:ADDITION|SUBDIVISION|S/D|ESTATES|ADDN|TOWN)"
# a list or range of lots: "1R", "9, 10, 11 & 12", "2 through 6", "1-8"
# a lot ID looks like 12, 1R, 6A-2, AB, DP-1 or G1 — never a word like "McGuigan" after a comma
_LOT_ID = r"(?:\d[\w-]*|[A-Z]{1,2}(?:-?\d[\w-]*)?)\b"
_LOTS = r"(?P<lots>" + _LOT_ID + r"(?:\s*(?:,|&|AND|THROUGH|THRU|TO)\s*(?:LOTS?\s+)?" + _LOT_ID + r")*)"
# "Lot 1R, Block 4 – McGuigan Ranch Addition", "Lot 2 of Block 2 of the Ruby Ridge Addition",
# "Lot AB of Otis subdivision", "Lot 8 of Lot 1R of Blk 3 of Della Vecchia Addition"
_LOT_RE = re.compile(
    r"\b(?:LOTS?|TRACTS?)\s+" + _LOTS + r"(?:\s+OF\s+LOT\s+[\w-]+)?(?:\s*,|\s+OF)?"
    r"(?:\s+(?:BLOCK|BLK)\.?\s+(?P<blk>[\w-]+))?(?:\s*,|\s+OF)?"
    r"(?:\s+TRACT\s+(?P<tract>[\w-]+))?[\s,–—-]*(?:OF\s+)?(?:THE\s+)?"
    r"(?P<sub>[A-Z][A-Z' ]*?\s" + _KIND + r")\b",
    re.I,
)
# subdivision first, as the county writes it: "Original Town Lots 9, 10, 11 & 12 Blk 65"
_SUB_FIRST_RE = re.compile(
    r"(?P<sub>\b[A-Z][A-Z' ]*?\s" + _KIND + r")[\s,]+(?:LOTS?|TRACTS?)\s+" + _LOTS
    + r"(?:\s+OF\s+LOT\s+[\w-]+)?(?:\s*,?\s*(?:BLOCK|BLK)\.?\s+(?P<blk>[\w-]+))?",
    re.I,
)  # fmt: skip


def subdivision_key(name: str) -> str:
    """'The Ruby Ridge Addition to the City of Spearfish', 'RUBY RIDGE ADDITION' → 'RUBY RIDGE ADDITION';
    the county's "THOMSON'S ADDITION", "DELLA VECCHIA ADDITION TIF #4" and "ORIGINAL TOWN SPEARFISH E 65'"
    → 'THOMSON ADDITION', 'DELLA VECCHIA ADDITION', 'ORIGINAL TOWN'."""
    s = (name or "").upper().replace("’", "'")
    s = re.sub(r"'S\b", "", s).replace("'", "")
    s = re.sub(r"\bTIF\s*#?\s*\d+\b", " ", s)
    s = " ".join(_SUB_KIND.get(w, w) for w in s.split())
    s = re.split(r"\bTO THE\b|,", s)[0]
    if m := re.search(r"\b(ADDITION|SUBDIVISION|ESTATES|TOWN)\b", s):
        s = s[: m.end()]  # the county appends parts of lots: "… E 65' OF"
    # lead-ins swept up from the sentence, and the county's "REVISED GOLDEN BELT ADDITION"
    s = re.sub(r"^(AND\s+)?(DEDICATED\s+)?(PUBLIC\s+)?(RIGHT[\s-]*(OF[\s-]*)?WAY\s+(OF\s+)?)?(REVISED\s+)?", "", s)
    words = _SUB_WORDS.sub(" ", s).split()
    for n in range(1, len(words) // 2 + 1):  # "CENTENNIAL VISTA CENTENNIAL VISTA SUBDIVISION"
        if words[:n] == words[n : 2 * n]:
            words = words[n:]
            break
    return " ".join(words)


def _expand(lots: str) -> list[str]:
    """'9, 10, 11 & 12' → [9, 10, 11, 12]; '2 through 6' and '1-8' → each lot in the range; '6A-2' stays."""
    out = []
    parts = re.split(r"\s*(?:,|&|\bAND\b)\s*(?:LOTS?\s+)?", lots.upper())
    for p in parts:
        m = re.fullmatch(r"(\d+)\s*(?:-|THROUGH|THRU|TO)\s*(\d+)", p.strip())
        if m and int(m.group(1)) < int(m.group(2)) <= int(m.group(1)) + 60:
            out += [str(n) for n in range(int(m.group(1)), int(m.group(2)) + 1)]
        elif p.strip():
            out.append(p.strip().split()[0])
    return out


def parse_lots(text: str) -> list[tuple[str, str, str, str]]:
    """Every (subdivision key, lot, block, tract) a description names, first one first."""
    text = re.sub(r"\b(?:LOT\s+)?TR\.\s?(?=[A-Z0-9])", "TRACT ", " ".join((text or "").split()), flags=re.I)
    out = []
    for rx in (_LOT_RE, _SUB_FIRST_RE):
        for m in rx.finditer(text):
            sub = subdivision_key(m.group("sub"))
            tract = (m.groupdict().get("tract") or "").upper()
            out += [(sub, lot, (m.group("blk") or "").upper(), tract) for lot in _expand(m.group("lots"))]
    return out


# a lot or tract and its block, whatever the subdivision is called ("Lot 3C, Block 14 of The Reserve …")
_LOT_ONLY_RE = re.compile(
    r"\b(?:LOTS?|TRACTS?)\s+" + _LOTS + r"(?:\s+OF\s+LOT\s+[\w-]+)?(?:\s*,|\s+OF)?"
    r"(?:\s+(?:BLOCK|BLK)\.?\s+(?P<blk>[\w-]+))?",
    re.I,
)
# "W1/2 NE1/4 NW1/4, Section 24, T6N, R2E" → ("W1/2 NE1/4 NW1/4", "24-006-02"), as the county writes them
_ALIQUOT = r"(?:[NSEW]{1,2}\s?1/[24](?:\s+OF(?:\s+THE)?)?\s?)+"
_SECTION_RE = re.compile(
    r"(?P<q>" + _ALIQUOT + r")[\s,]*(?:OF\s+)?(?:THE\s+)?SECTION\s+(?P<sec>\d{1,2})[\s,]*"
    r"(?:TOWNSHIP\s+)?T?\s?(?P<t>\d{1,2})\s?N(?:ORTH)?[\s,-]*(?:RANGE\s+)?R?\s?(?P<r>\d{1,2})\s?E",
    re.I,
)


_KIND_WORDS = {"ADDITION", "SUBDIVISION", "ESTATES", "TOWN"}
_NOT_A_NAME = re.compile(r"\d/\d|\bGOVT\b|\bTRACT\b|\bLOTS?\b")


def _fractions(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").upper().replace("½", "1/2").replace("¼", "1/4"))


def parse_section(text: str) -> tuple[str, str] | None:
    """The quarter-section description and the county's section-township-range code, if the text has them."""
    t = _fractions(text)
    t = re.sub(r"([NSEW])\s?(1/[24])", r"\1\2", t)
    m = _SECTION_RE.search(t)
    if not m:
        return None
    quarter = " ".join(re.findall(r"[NSEW]{1,2}1/[24]", m.group("q")))
    return quarter, f"{int(m.group('sec')):02d}-{int(m.group('t')):03d}-{int(m.group('r')):02d}"


def parse_lot(text: str) -> tuple[str, str, str, str] | None:
    """The first (subdivision key, lot, block, tract) in free text, if it names a platted lot."""
    lots = parse_lots(text)
    return lots[0] if lots else None


class Parcels:
    def __init__(self, records: list[dict]):
        self.by_id = {r["parcel_id"]: r for r in records}
        self.exact: dict[str, list[str]] = defaultdict(list)
        self.loose: dict[str, set[str]] = defaultdict(set)
        self.lots: dict[tuple, list[str]] = defaultdict(list)
        self.lots_any_block: dict[tuple, set[str]] = defaultdict(set)  # (subdivision, lot)
        self.lots_by_word: dict[tuple, set[str]] = defaultdict(set)  # (subdivision's first word, lot)
        for r in records:
            for k in r.get("keys") or []:
                self.exact[k].append(r["parcel_id"])
            for a in address.parse(r.get("situs", "")):
                self.loose[a.loose()].add(r["parcel_id"])
            if r.get("legal_sub") and r.get("legal_lot"):
                sub = subdivision_key(r["legal_sub"])
                lot = r["legal_lot"].upper()
                self.lots[(sub, lot, (r.get("legal_blk") or "").upper())].append(r["parcel_id"])
                self.lots_any_block[(sub, lot)].add(r["parcel_id"])
                self.lots_by_word[(sub.split()[0] if sub else "", lot)].add(r["parcel_id"])
        # subdivision names worth looking for in free text: two real words or more, not "W1/2" or "GOVT"
        self.sub_names = sorted(
            {k for k, *_ in self.lots if len(k.split()) >= 2 and not _NOT_A_NAME.search(k)},
            key=len,
            reverse=True,
        )
        self.sections: dict[str, list[tuple[str, str]]] = defaultdict(list)  # "24-006-02" → [(legal, id)]
        for r in records:
            if r.get("str"):
                self.sections[r["str"]].append((_fractions(r.get("legal", "")), r["parcel_id"]))
        self._tree = None
        self._tree_ids: list[str] = []

    def __bool__(self) -> bool:
        return bool(self.by_id)

    def by_address(self, text: str) -> str | None:
        parsed = address.parse(text or "")
        for a in parsed:
            if ids := self.exact.get(a.key()):
                return min(ids)  # condo units share an address: any one stands for the site
        for a in parsed:
            if len(ids := self.loose.get(a.loose(), ())) == 1:
                return next(iter(ids))
        return None

    def by_lot(self, *texts: str) -> str | None:
        """The parcel of the first lot named (of any listed) that the county has."""
        for t in texts:
            for sub, number, block, tract in parse_lots(t):
                ids = self.lots.get((sub, number, block)) or (self.lots.get((sub, number, "")) if not block else None)
                # A lot not yet carved out of its tract (the application may be the plat creating it)
                if not ids and tract:
                    ids = self.lots.get((sub, tract, ""))
                # No block given ("Lot 6, Della Vecchia Addition"): fine if only one block has that lot
                if not ids and not block and len(found := self.lots_any_block.get((sub, number), ())) == 1:
                    ids = list(found)
                # A distinctive lot ("18H-1") in a subdivision the agenda names a little differently
                # ("Sandstone Addition" for SANDSTONE HILLS ADDITION): the county's name must hold every
                # word of the agenda's, and it must be the only such lot
                if not ids and sub and re.search(r"\d", number) and re.search(r"[A-Z]", number):
                    words = set(sub.split()) - _KIND_WORDS
                    found = {
                        pid
                        for pid in self.lots_by_word.get((sub.split()[0], number), ())
                        if words <= set(subdivision_key(self.by_id[pid].get("legal_sub", "")).split())
                    }
                    ids = list(found) if len(found) == 1 else None
                if ids:
                    return min(ids)
        return None

    def by_named_lot(self, *texts: str) -> str | None:
        """A lot and block in a subdivision the county knows by name, however the text words the rest."""
        for t in texts:
            if not t or parse_lots(t):
                continue  # the text names its subdivision outright; by_lot has already tried it
            words = " " + " ".join(subdivision_key(" ".join(t.split())).split()) + " " if t else ""
            norm = " " + " ".join(_SUB_WORDS.sub(" ", re.sub(r"'S\b|'", "", (t or "").upper())).split()) + " "
            sub = next((n for n in self.sub_names if f" {n} " in norm or f" {n} " in words), None)
            if not sub:
                continue
            for m in _LOT_ONLY_RE.finditer(" ".join(t.split())):
                block = (m.group("blk") or "").upper()
                for number in _expand(m.group("lots")):
                    ids = self.lots.get((sub, number, block)) or (
                        list(self.lots_any_block.get((sub, number), ())) if not block else None
                    )
                    if ids and len(set(ids)) == 1 or (ids and block):
                        return min(ids)
        return None

    def by_section(self, *texts: str) -> str | None:
        """The one parcel in a section whose legal description starts with the same quarter."""
        for t in texts:
            if not (sec := parse_section(t)):
                continue
            quarter, code = sec
            # the parcel is that quarter exactly, not a smaller piece of it ("E1/2 SE1/4" isn't "E1/2")
            exact = re.escape(quarter) + r"(?!\s*(?:OF\s+(?:THE\s+)?)?[NSEW]{1,2}\s?1/[24])"
            found = {pid for legal, pid in self.sections.get(code, ()) if re.match(exact, legal)}
            if len(found) == 1:
                return found.pop()
        return None

    def by_point(self, lat, lon) -> str | None:
        if lat is None or lon is None or not self.by_id:
            return None
        import shapely
        from shapely.geometry import Point, Polygon

        if self._tree is None:
            polys = []
            for pid, r in self.by_id.items():
                for ring in r.get("outline") or []:
                    if len(ring) >= 4:
                        polys.append(Polygon(ring))
                        self._tree_ids.append(pid)
            self._tree = shapely.STRtree(polys)
        hits = self._tree.query(Point(float(lon), float(lat)), predicate="within")
        return self._tree_ids[int(hits[0])] if len(hits) else None

    def match(self, address_text: str = "", lat=None, lon=None, lot_texts: tuple[str, ...] = ()) -> str | None:
        return self.by_address(address_text) or self.by_lot(*lot_texts) or self.by_point(lat, lon)


# ── links: the only parcel data that leaves this laptop ──────────────────────
#
# scripts/import_parcels.py links records to parcels locally (with the full
# parcel table in memory) and writes parcel_links.json: which parcel each
# record belongs to, plus details for those parcels only. The raw parcel table
# is never written out.


def record_key(src: str, r: dict) -> str:
    """Stable ID of a record across sources: app:<OpenGov id>, permit:<number|month>, pc:<agenda item id>."""
    if src == "app":
        return f"app:{r.get('id')}"
    if src == "permit":
        return f"permit:{r.get('permit_key') or r.get('id')}"
    return f"pc:{r.get('item_id')}"


def link_records(parcels: Parcels, archive: list[dict], permits: list[dict], agenda: list[dict]) -> dict[str, str]:
    """record_key → parcel ID for every record that can be placed on a parcel."""
    links = {}
    for r in archive:
        if r.get("site") and (pid := parcels.match(r.get("address", ""), r.get("lat"), r.get("lon"))):
            links[record_key("app", r)] = pid
    for r in permits:
        if pid := parcels.by_address(r.get("site_address", "")):
            links[record_key("permit", r)] = pid
    for r in agenda:
        if not r.get("site"):
            continue
        lots = (r.get("location", ""), r.get("legal_description", ""), r.get("agenda_text", ""), r.get("request", ""))
        if pid := (
            parcels.by_address(r.get("address", ""))
            or parcels.by_lot(*lots)
            or parcels.by_named_lot(*lots)
            or parcels.by_section(*lots)
        ):
            links[record_key("pc", r)] = pid
    return links


LINKED_FIELDS = ("situs", "keys", "owner", "acres", "plat", "lat", "lon", "outline")


class ParcelLinks:
    """parcel_links.json, as the site build uses it."""

    def __init__(self, links: dict[str, str], parcels: dict[str, dict]):
        self.links = links
        self.by_id = parcels
        self.exact = {k: pid for pid, p in sorted(parcels.items(), reverse=True) for k in p.get("keys") or []}

    @classmethod
    def load(cls, data_dir: Path) -> ParcelLinks:
        try:
            env = json.loads((data_dir / "parcel_links.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return cls({}, {})
        return cls(env.get("links") or {}, env.get("parcels") or {})

    def __bool__(self) -> bool:
        return bool(self.by_id)

    def pid(self, key: str, address_text: str = "") -> str | None:
        """The record's linked parcel; failing that (a record newer than the last import), an exact
        address match among parcels that already have records."""
        if pid := self.links.get(key):
            return pid
        for a in address.parse(address_text or ""):
            if pid := self.exact.get(a.key()):
                return pid
        return None

    def site_fields(self, pid: str) -> dict:
        """What the permits page shows about a parcel (the outline is shipped separately)."""
        r = self.by_id[pid]
        out = {"pid": pid, "lat": r.get("lat"), "lon": r.get("lon"), "own": r.get("owner"), "ac": r.get("acres")}
        if r.get("plat"):
            out["plat"] = r["plat"]
        return {k: v for k, v in out.items() if v not in (None, "")}

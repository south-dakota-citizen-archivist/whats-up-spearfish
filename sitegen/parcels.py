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
# "Lot 1R, Block 4 – McGuigan Ranch Addition", "Lot 2 of Block 2 of the Ruby Ridge Addition",
# "Lot AB of Otis subdivision"
_LOT_RE = re.compile(
    r"\bLOTS?\s+(?P<lot>[\w-]+)(?:\s+(?:THROUGH|THRU|TO|AND|&)\s+[\w-]+)?(?:\s*,|\s+OF)?"
    r"(?:\s+(?:BLOCK|BLK)\s+(?P<blk>[\w-]+))?(?:\s*,|\s+OF)?"
    r"(?:\s+TRACT\s+(?P<tract>[\w-]+))?[\s,–—-]*(?:OF\s+)?(?:THE\s+)?"
    r"(?P<sub>[A-Z][A-Z' ]*?\s(?:ADDITION|SUBDIVISION|S/D|ESTATES|ADDN))\b",
    re.I,
)


def subdivision_key(name: str) -> str:
    """'The Ruby Ridge Addition to the City of Spearfish' and 'RUBY RIDGE ADDITION' → 'RUBY RIDGE ADDITION'."""
    s = " ".join(_SUB_KIND.get(w, w) for w in (name or "").upper().replace("’", "'").split())
    s = re.split(r"\bTO THE\b|,", s)[0]
    return " ".join(_SUB_WORDS.sub(" ", s).split())


def parse_lot(text: str) -> tuple[str, str, str, str] | None:
    """(subdivision key, lot, block, tract) from free text, if it names a platted lot."""
    m = _LOT_RE.search(" ".join((text or "").split()))
    if not m:
        return None
    sub = subdivision_key(m.group("sub"))
    return sub, m.group("lot").upper(), (m.group("blk") or "").upper(), (m.group("tract") or "").upper()


class Parcels:
    def __init__(self, records: list[dict]):
        self.by_id = {r["parcel_id"]: r for r in records}
        self.exact: dict[str, list[str]] = defaultdict(list)
        self.loose: dict[str, set[str]] = defaultdict(set)
        self.lots: dict[tuple, list[str]] = defaultdict(list)
        for r in records:
            for k in r.get("keys") or []:
                self.exact[k].append(r["parcel_id"])
            for a in address.parse(r.get("situs", "")):
                self.loose[a.loose()].add(r["parcel_id"])
            if r.get("legal_sub") and r.get("legal_lot"):
                sub = subdivision_key(r["legal_sub"])
                self.lots[(sub, r["legal_lot"].upper(), (r.get("legal_blk") or "").upper())].append(r["parcel_id"])
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
        for t in texts:
            if not (lot := parse_lot(t)):
                continue
            sub, number, block, tract = lot
            ids = self.lots.get((sub, number, block)) or (self.lots.get((sub, number, "")) if not block else None)
            # A lot not yet carved out of its tract (the application may be the plat creating it)
            if not ids and tract:
                ids = self.lots.get((sub, tract, ""))
            if ids:
                return min(ids)
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
        lots = (r.get("location", ""), r.get("legal_description", ""), r.get("agenda_text", ""))
        if pid := parcels.by_address(r.get("address", "")) or parcels.by_lot(*lots):
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

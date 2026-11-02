"""
scripts/import_parcels.py

Match permits, OpenGov applications and Planning Commission items to county
parcel data, from a GeoParquet parcel snapshot on this machine. The snapshot's
location comes from --snapshot or WUS_PARCEL_SNAPSHOT (a file, or a folder
whose newest .parquet is used). Without one, the import is skipped and the
site keeps the last links.

    WUS_PARCEL_SNAPSHOT=/path/to/parcels uv run python -m scripts.import_parcels

The parcel table stays in memory and is never written out. The output,
data/parcel_links.json, holds only which parcel each record belongs to and,
for those parcels alone, their address, owner name, acres, plat, position and
a simplified outline. Mailing addresses are never read. Publish it like any
data-branch change:

    git -C data add parcel_links.json && git -C data commit --no-verify -m "data: parcel links" && git -C data push
"""

from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path

from scrapers import address, base, geo

SIMPLIFY = 0.00002  # degrees, about 2 m: plenty for outlining a lot on a city map

KEEP = ["PARCEL_ID", "SITUS", "LEGAL", "PLAT", "S_T_R", "Acres", "CLASS", "CURRENT_OW", "Owner2"]

_LEGAL_RE = re.compile(
    r"^(?P<sub>.+?)\s+(?:LOTS?|TRACT|TR)\s+(?P<lot>[\w.-]+)(?:\s+REV\.?)?(?:.*?\bBLK\s+(?P<blk>[\w-]+))?", re.I
)


def find_snapshot(location: str | Path | None = None) -> Path | None:
    """The snapshot file: the given path, or the newest .parquet in it if it's a folder."""
    location = location or os.environ.get("WUS_PARCEL_SNAPSHOT")
    if not location:
        return None
    path = Path(location).expanduser()
    if path.is_file():
        return path
    files = sorted(path.glob("*.parquet"), key=lambda p: p.stat().st_mtime) if path.is_dir() else []
    return files[-1] if files else None


def _blank(v) -> bool:
    return v is None or str(v).strip() in ("", "0")


def parse_legal(legal: str) -> dict:
    """'MCGUIGAN RANCH ADDITION LOT 1R BLK 4 PLAT 2013-01671' → subdivision, lot, block."""
    m = _LEGAL_RE.match(" ".join((legal or "").upper().split()))
    if not m:
        return {}
    sub = re.sub(r"\bS/D\b", "SUBDIVISION", m.group("sub")).strip(" ,")
    return {k: v for k, v in {"sub": sub, "lot": m.group("lot"), "blk": m.group("blk")}.items() if v}


def read_snapshot(path: Path) -> list[dict]:
    """Spearfish-area parcels from a GeoParquet snapshot, one record per parcel ID."""
    import pyarrow.parquet as pq
    import shapely
    from shapely.ops import unary_union

    table = pq.read_table(path, columns=[*KEEP, "geometry"])
    rows = table.to_pylist()
    geoms = shapely.from_wkb([r["geometry"] for r in rows])

    by_id: dict[str, list] = defaultdict(list)
    for row, g in zip(rows, geoms):
        if _blank(row["PARCEL_ID"]) or g is None or g.is_empty:
            continue
        c = g.centroid
        if geo.in_spearfish(c.y, c.x):
            by_id[row["PARCEL_ID"].strip()].append((row, g))

    out = []
    for pid, parts in by_id.items():
        row = parts[0][0]
        shape = unary_union([g for _, g in parts]) if len(parts) > 1 else parts[0][1]
        simple = shape.simplify(SIMPLIFY, preserve_topology=True)
        center = shape.representative_point()  # always inside, unlike a centroid of an L-shaped lot
        situs = "" if _blank(row["SITUS"]) else " ".join(row["SITUS"].split())
        owners = [o.strip() for o in (row["CURRENT_OW"], row["Owner2"]) if not _blank(o)]
        rec = {
            "parcel_id": pid,
            "situs": situs,
            "keys": address.keys(situs),
            "legal": "" if _blank(row["LEGAL"]) else " ".join(row["LEGAL"].split()),
            "plat": "" if _blank(row["PLAT"]) else row["PLAT"].strip(),
            "str": "" if _blank(row["S_T_R"]) or row["S_T_R"].strip() == "--" else row["S_T_R"].strip(),
            "acres": row["Acres"] or None,
            "class": "" if _blank(row["CLASS"]) else row["CLASS"].strip(),
            "owner": " & ".join(dict.fromkeys(owners)),
            "lat": round(center.y, 6),
            "lon": round(center.x, 6),
            "outline": _rings(simple),
        }
        rec.update({f"legal_{k}": v for k, v in parse_legal(rec["legal"]).items()})
        out.append(rec)
    return sorted(out, key=lambda r: r["parcel_id"])


def _rings(shape) -> list:
    """Polygon(s) as [[[lon, lat], …], …] exterior rings, rounded to ~1 m."""
    polys = getattr(shape, "geoms", [shape])
    return [[[round(x, 5), round(y, 5)] for x, y in p.exterior.coords] for p in polys if p.geom_type == "Polygon"]


def main(argv: list[str] | None = None) -> int:
    from sitegen.parcels import LINKED_FIELDS, Parcels, link_records

    ap = argparse.ArgumentParser(prog="python -m scripts.import_parcels")
    ap.add_argument("--snapshot", help="parcel snapshot file or folder (default: $WUS_PARCEL_SNAPSHOT)")
    args = ap.parse_args(argv)

    snapshot = find_snapshot(args.snapshot)
    if not snapshot:
        print(
            "[parcels] no parcel snapshot available (set --snapshot or WUS_PARCEL_SNAPSHOT); skipping the parcel import"
        )
        return 0
    try:
        table = read_snapshot(snapshot)
    except ImportError as exc:
        print(f"[parcels] {exc}; skipping the parcel import")
        return 0

    data = base.DATA_DIR

    def records(name: str) -> list[dict]:
        try:
            return json.loads((data / name).read_text(encoding="utf-8")).get("records") or []
        except (OSError, json.JSONDecodeError):
            return []

    archive = records("archive/planning_index.json")
    permits = records("building_permits.json")
    agenda = records("planning_commission.json")
    if not archive or not agenda:
        # most likely a stale local data/ folder rather than the data branch
        print(
            f"[parcels] {data} has no planning archive or Planning Commission records; point WUS_DATA_DIR "
            "at a checkout of the data branch. Nothing written."
        )
        return 1
    links = link_records(Parcels(table), archive, permits, agenda)
    used = set(links.values())
    parcels = {
        p["parcel_id"]: {k: p[k] for k in LINKED_FIELDS if p.get(k) not in (None, "", [])}
        for p in table
        if p["parcel_id"] in used
    }

    as_of = datetime.fromtimestamp(snapshot.stat().st_mtime, UTC)
    out = {
        "meta": {
            "as_of": as_of.isoformat(),
            "linked_records": len(links),
            "records": {"app": len(archive), "permit": len(permits), "pc": len(agenda)},
        },
        "links": dict(sorted(links.items())),
        "parcels": dict(sorted(parcels.items())),
    }
    dest = data / "parcel_links.json"
    tmp = dest.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    tmp.replace(dest)
    print(
        f"[parcels] linked {len(links):,} records to {len(parcels):,} parcels (snapshot of {as_of:%Y-%m-%d}) → {dest}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

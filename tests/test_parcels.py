"""
tests/test_parcels.py

County parcels as the canonical site: the parcel snapshot import
(scripts/import_parcels.py) and record-to-parcel linking (sitegen/parcels.py).
"""

from __future__ import annotations

import json
import os

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import shapely
from shapely.geometry import box

from scripts import import_parcels
from sitegen.data import Site
from sitegen.pages import permit_sites
from sitegen.parcels import ParcelLinks, Parcels, link_records, parse_lot


def _parcel(pid, situs="", legal="", lon=-103.86, lat=44.49, **kw):
    from scrapers import address

    rec = {
        "parcel_id": pid,
        "situs": situs,
        "keys": address.keys(situs),
        "legal": legal,
        "lat": lat,
        "lon": lon,
        "outline": [
            [
                [lon - 0.001, lat - 0.001],
                [lon + 0.001, lat - 0.001],
                [lon + 0.001, lat + 0.001],
                [lon - 0.001, lat + 0.001],
                [lon - 0.001, lat - 0.001],
            ]
        ],
        **kw,
    }
    rec.update({f"legal_{k}": v for k, v in import_parcels.parse_legal(legal).items()})
    return rec


@pytest.fixture
def parcels():
    return Parcels(
        [
            _parcel(
                "A",
                "440 HERITAGE DR, SPEARFISH, SD 57783",
                "GREEN ACRES ADDITION TRACT A PLAT 1976-01053",
                owner="S & S HOSPITALITY INC",
            ),
            _parcel("B", "1440 MAIN ST, SPEARFISH, SD 57783", lon=-103.85),
            _parcel("C", "200 OAK ST", lon=-103.84),
            _parcel("D", "200 N OAK ST", lon=-103.83),
            _parcel("E", "", "MCGUIGAN RANCH ADDITION LOT 1R BLK 4 PLAT 2013-01671", lon=-103.82),
            _parcel("F", "", "FALSE BOTTOM ADDITION TRACT R PLAT 2017-05844", lon=-103.81),
        ]
    )


def test_by_address_exact_and_loose(parcels):
    assert parcels.by_address("440 Heritage Drive") == "A"
    assert parcels.by_address("1440 N MAIN ST") == "B"  # county left out the direction
    assert parcels.by_address("200 S OAK ST") is None  # two parcels without the direction: ambiguous
    assert parcels.by_address("Intersection of Main and Oak") is None


def test_by_lot(parcels):
    assert parcels.by_lot("Lot 1R, Block 4 – McGuigan Ranch Addition") == "E"
    assert parcels.by_lot("Lot 5 of Tract R, False Bottom Addition") == "F"  # lot not yet carved out
    assert parcels.by_lot("Lot 9, Block 9 – Nowhere Addition") is None


def test_by_point(parcels):
    assert parcels.by_point(44.49, -103.8402) == "C"
    assert parcels.by_point(44.0, -103.0) is None


def test_parse_lot_variants():
    assert parse_lot("Lot 2 of Block 2 of the Ruby Ridge Addition to the City of Spearfish") == (
        "RUBY RIDGE ADDITION",
        "2",
        "2",
        "",
    )
    assert parse_lot("preliminary plat of Lots 2 through 6 of Tract R, False Bottom Addition") == (
        "FALSE BOTTOM ADDITION",
        "2",
        "",
        "R",
    )
    assert parse_lot("Lot AB of Otis subdivision") == ("OTIS SUBDIVISION", "AB", "", "")
    assert parse_lot("1407 Charles Street") is None


def test_permit_sites_group_by_parcel(tmp_path, parcels):
    archive = [
        {
            "id": 1,
            "site": True,
            "no": "SP-25-16",
            "type": "Sketch Plat",
            "submitted": "2025-06-25",
            "address": "440 HERITAGE DR, SPEARFISH, SD 57783",
        },
    ]
    permits = [
        {
            "site_address": "440 Heritage Drive",
            "date": "2022-05-01",
            "construction_type": "Comm-Roof",
            "permit_number": "220127",
            "permit_key": "220127|2022-05",
        },
        {
            "site_address": "1440 N Main Street",
            "date": "2026-09-01",
            "construction_type": "Res-Deck",
            "permit_key": "x|2026-09",
        },
        {
            "site_address": "999 Nowhere Ln",
            "date": "2026-09-01",
            "construction_type": "Res-Deck",
            "permit_key": "y|2026-09",
        },
    ]
    links = link_records(parcels, archive, permits, [])
    assert links == {"app:1": "A", "permit:220127|2022-05": "A", "permit:x|2026-09": "B"}

    # what the import publishes: links, plus details for linked parcels only
    linked = ParcelLinks(links, {pid: parcels.by_id[pid] for pid in set(links.values())})
    assert set(linked.by_id) == {"A", "B"}

    (tmp_path / "archive").mkdir()
    (tmp_path / "archive" / "planning_index.json").write_text(json.dumps({"meta": {}, "records": archive}))
    newer = {
        "site_address": "440 HERITAGE DR",
        "date": "2026-10-01",
        "construction_type": "Res-Shed",
        "permit_key": "new|2026-10",
    }
    (tmp_path / "building_permits.json").write_text(json.dumps({"records": [*permits, newer]}))
    sites = {s["k"]: s for s in permit_sites(Site(tmp_path), linked)}
    heritage = sites["P A"]
    # the October permit came after the import, but its address matches a linked parcel
    assert [r.get("no") or r["t"] for r in heritage["r"]] == ["Residential shed", "SP-25-16", "220127"]
    assert heritage["own"] == "S & S HOSPITALITY INC" and heritage["lat"] == 44.49
    assert "P B" in sites
    assert "999 NOWHERE LN" in sites and "pid" not in sites["999 NOWHERE LN"]  # unlinked: grouped by address


# ── import from a parcel snapshot ────────────────────────────────────────────


def _snapshot(path, rows):
    cols = {k: [r.get(k) for r in rows] for k in [*import_parcels.KEEP, "MAIL_ADD"]}
    cols["geometry"] = [shapely.to_wkb(r["geom"]) for r in rows]
    pq.write_table(pa.table(cols), path)


def test_import_keeps_spearfish_drops_mailing_address(tmp_path, monkeypatch):
    folder = tmp_path / "snapshots"
    folder.mkdir()
    row = {
        "PARCEL_ID": "05100-00602-000-01",
        "SITUS": "2688 CARMELO CT, SPEARFISH, SD",
        "LEGAL": "WESTERN SLOPE ESTATES LOT 1 PLAT 2021-06979",
        "PLAT": "2021-6979",
        "S_T_R": "05-006-02",
        "Acres": 2.041,
        "CLASS": "C",
        "CURRENT_OW": "HEITING, COREY",
        "Owner2": "HEITING, BARBARA",
        "MAIL_ADD": "2120 BLUE BELL LOOP SPEARFISH",
        "geom": box(-103.87, 44.48, -103.869, 44.481),
    }
    far = {
        **row,
        "PARCEL_ID": "99999-00000-000-00",
        "geom": box(-103.5, 44.3, -103.499, 44.301),
    }  # Lead, outside the area
    _snapshot(folder / "older.parquet", [row])
    _snapshot(folder / "newer.parquet", [row, far])
    os.utime(folder / "older.parquet", (1_700_000_000, 1_700_000_000))
    assert import_parcels.find_snapshot(folder).name == "newer.parquet"
    assert import_parcels.find_snapshot(folder / "older.parquet").name == "older.parquet"

    monkeypatch.setenv("WUS_PARCEL_SNAPSHOT", str(folder))
    data = tmp_path / "data"
    monkeypatch.setattr("scrapers.base.DATA_DIR", data)
    data.mkdir()
    (data / "building_permits.json").write_text(
        json.dumps(
            {
                "records": [
                    {"site_address": "2688 Carmelo Court", "permit_key": "26-1|2026-09"},
                ]
            }
        )
    )
    (data / "archive").mkdir()
    (data / "archive" / "planning_index.json").write_text(json.dumps({"records": [{"id": 1, "type": "Variance"}]}))
    (data / "planning_commission.json").write_text(json.dumps({"records": [{"item_id": 1, "title": "Variance"}]}))
    assert import_parcels.main([]) == 0
    assert not (data / "parcels.json").exists()  # the parcel table itself is never written
    text = (data / "parcel_links.json").read_text()
    out = json.loads(text)
    assert out["links"] == {"permit:26-1|2026-09": "05100-00602-000-01"}
    assert list(out["parcels"]) == ["05100-00602-000-01"]  # only linked parcels; Lead's is left out
    p = out["parcels"]["05100-00602-000-01"]
    assert p["owner"] == "HEITING, COREY & HEITING, BARBARA" and p["keys"] == ["2688 CARMELO CT"]
    assert "BLUE BELL" not in text and "WESTERN SLOPE" not in text  # no mailing address; no legal text


def test_import_skips_without_snapshot(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("WUS_PARCEL_SNAPSHOT", raising=False)
    monkeypatch.setattr("scrapers.base.DATA_DIR", tmp_path)
    assert import_parcels.main([]) == 0
    assert "skipping" in capsys.readouterr().out
    assert not (tmp_path / "parcel_links.json").exists()
    assert import_parcels.find_snapshot(tmp_path / "missing") is None


def test_import_refuses_a_data_folder_without_planning_records(tmp_path, monkeypatch, capsys):
    """A stale local data/ (no archive, no agenda records) would link almost nothing and look fine."""
    snapshot = tmp_path / "parcels.parquet"
    _snapshot(snapshot, [{"PARCEL_ID": "1", "SITUS": "", "LEGAL": "", "PLAT": "", "S_T_R": "", "Acres": 1,
                          "CLASS": "", "CURRENT_OW": "", "Owner2": "", "MAIL_ADD": "",
                          "geom": box(-103.87, 44.48, -103.869, 44.481)}])  # fmt: skip
    data = tmp_path / "data"
    data.mkdir()
    (data / "building_permits.json").write_text(json.dumps({"records": [{"site_address": "1 Main St"}]}))
    monkeypatch.setattr("scrapers.base.DATA_DIR", data)
    assert import_parcels.main(["--snapshot", str(snapshot)]) == 1
    assert "WUS_DATA_DIR" in capsys.readouterr().out
    assert not (data / "parcel_links.json").exists()

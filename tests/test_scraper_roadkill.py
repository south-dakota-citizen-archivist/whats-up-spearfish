"""Roadkill: SD DOT's wildlife carcass pickups, and how the site shows them."""

from __future__ import annotations

import json
from datetime import date, timedelta

from scrapers.sources import roadkill
from sitegen.data import Site
from sitegen.pages import road_name, roadkill_context

# 2026-10-31 noon Mountain, as the layer stores a pickup's day
OCT31 = 1793469600000


def _feature(oid=72532, **attrs):
    base = {
        "objectid": oid, "globalid": "abc", "Date": OCT31, "Species": "White-tailed Deer", "Sex": "Male",
        "Present": "Yes", "Highway": "N/A", "Comments": "East 53rd ", "Contractor": "Chris Moeller",
        "PCN": "Game Fish and Parks", "Latitude": 44.043221, "Longitude": -103.2, "CreationDate": OCT31,
        "Creator": "", "EditDate": OCT31, "Editor": "", "parentglobalid": None,
    }  # fmt: skip
    return {"attributes": {**base, **attrs}, "geometry": {"x": -103.131212, "y": 44.043221}}


def test_parse_feature_keeps_every_field():
    rec = roadkill.parse_feature(_feature())
    assert rec["date"] == "2026-10-31" and rec["date_raw"].startswith("2026-10-31T12:00:00-06:00")
    assert rec["species"] == "White-tailed Deer" and rec["sex"] == "Male" and rec["present"] == "Yes"
    assert rec["highway"] == "" and rec["highway_raw"] == "N/A"  # 'N/A' is no road
    assert rec["comments"] == "East 53rd" and rec["contractor"] == "Chris Moeller"
    assert rec["pcn"] == "Game Fish and Parks"
    assert (rec["lat"], rec["lon"]) == (44.043221, -103.131212)
    assert rec["gps_lon"] == -103.2 and "gps_lat" not in rec  # the form's GPS, only where it differs
    assert rec["photos"] == []


def test_photos_attach_to_their_pickups():
    recs = {1: roadkill.parse_feature(_feature(1)), 2: roadkill.parse_feature(_feature(2))}
    roadkill.add_photos(recs, [
        {"parentObjectId": 1, "attachmentInfos": [{"id": 9, "name": "Picture1.jpg", "contentType": "image/jpeg",
                                                   "size": 100, "keywords": "Picture1"}]},
        {"parentObjectId": 99, "attachmentInfos": [{"id": 10}]},  # not one of ours
    ])  # fmt: skip
    assert [p["id"] for p in recs[1]["photos"]] == [9] and recs[2]["photos"] == []
    assert roadkill.photo_url(recs[1], recs[1]["photos"][0], 320).endswith("/1/attachments/9?w=320")


def test_a_short_read_is_a_failure():
    scraper = roadkill.Roadkill()
    assert scraper.is_empty({"records": [{}] * 10})
    assert not scraper.is_empty({"records": [{}] * 5000})


def test_road_names():
    assert road_name("I90") == "I-90"
    assert road_name("85") == "Highway 85"
    assert road_name("14A") == "Highway 14A"
    assert road_name("90WF") == "90WF"
    assert road_name("") == ""


def test_context_counts_and_gallery(tmp_path):
    today = date(2026, 11, 4)

    def rec(oid, days_ago, species="White-tailed Deer", photo=True, **kw):
        return {"objectid": oid, "date": (today - timedelta(days=days_ago)).isoformat(), "species": species,
                "sex": "Female", "highway": "85", "comments": "", "lat": 44.5, "lon": -103.9,
                "photos": [{"id": oid * 10, "type": "image/jpeg"}] if photo else [], **kw}  # fmt: skip

    records = [
        rec(1, 1),
        rec(2, 3, "Mule Deer"),
        rec(3, 10, "Small Animal"),
        rec(4, 12, "Small Animal", photo=False),
        rec(5, 20, "Elk"),
        rec(6, 40),
        rec(7, 2, "No Pick-Up"),  # a crew visit with nothing to pick up
    ]
    (tmp_path / "roadkill.json").write_text(json.dumps(
        {"slug": "roadkill", "kind": "stats", "fetched_at": "2026-11-04T06:00:00-07:00",
         "data": {"layer": "https://example.com/layer/0", "records": records}}))  # fmt: skip
    ctx = roadkill_context(Site(tmp_path), today, photos=3)
    assert ctx["count"] == 6 and ctx["past_month"] == 5 and ctx["past_week"] == 2
    assert [(s["label"], s["count"], s["icon"]) for s in ctx["species"]] == [
        ("small animals", 2, "small"),
        ("white-tailed deer", 1, "whitetail"),
        ("mule deer", 1, "muledeer"),
        ("elk", 1, "elk"),
    ]
    first = ctx["photos"][0]
    assert len(ctx["photos"]) == 3 and first["species"] == "White-tailed deer" and first["road"] == "Highway 85"
    assert first["thumb"] == "https://example.com/layer/0/1/attachments/10?w=400"
    assert "mlat=44.5" in first["map"] and first["when"] == "Nov 3, 2026"

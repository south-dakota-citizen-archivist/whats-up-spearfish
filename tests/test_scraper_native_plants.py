"""
tests/test_scraper_native_plants.py

Native plant of the day: the iNaturalist list of Black Hills natives, and the
daily pick that works through all of them.
"""

from __future__ import annotations

from datetime import date, timedelta

from scrapers.sources import native_plants_spotlight as plants


def test_summary_is_two_plain_sentences():
    html = (
        "<b>Apocynum androsaemifolium</b> , the <i>spreading dogbane</i> , is a flowering plant. "
        "It grows in dry woods. It is toxic to livestock."
    )
    assert (
        plants.summary(html)
        == "Apocynum androsaemifolium, the spreading dogbane, is a flowering plant. It grows in dry woods."
    )
    assert plants.summary("") == ""


def test_plant_record_needs_a_photo():
    taxon = {
        "id": 49975,
        "name": "Cornus canadensis",
        "preferred_common_name": "Canadian bunchberry",
        "wikipedia_summary": "<b>Cornus canadensis</b> is a dogwood. More text.",
        "wikipedia_url": "https://en.wikipedia.org/wiki/Cornus_canadensis",
        "default_photo": {
            "medium_url": "https://static.inaturalist.org/photos/1/medium.jpg",
            "attribution": "(c) Kelly",
        },
    }
    rec = plants.plant_record(taxon, 42)
    assert rec["title"] == "Canadian bunchberry" and rec["scientific_name"] == "Cornus canadensis"
    assert rec["url"] == "https://www.inaturalist.org/taxa/49975" and rec["photo_credit"] == "(c) Kelly"
    assert rec["sightings"] == 42
    assert plants.plant_record({**taxon, "default_photo": None}, 42) is None


def test_scrape_keeps_regular_sightings_only(monkeypatch):
    calls = []

    def fake_get(path, **params):
        calls.append(path)
        if path.startswith("observations/species_counts"):
            assert params["native"] == "true" and params["place_id"] == plants.PLACES
            return {
                "total_results": 2,
                "results": [{"taxon": {"id": 1}, "count": 12}, {"taxon": {"id": 2}, "count": 2}],
            }
        return {
            "results": [
                {"id": 1, "name": "Pinus ponderosa", "preferred_common_name": "ponderosa pine",
                 "default_photo": {"medium_url": "u", "attribution": "a"}, "wikipedia_summary": "A pine."}
            ]
        }  # fmt: skip

    monkeypatch.setattr(plants, "_get", fake_get)
    out = plants.NativePlantSpotlight().scrape()
    assert [p["title"] for p in out] == ["Ponderosa pine"]
    assert calls == ["observations/species_counts", "taxa/1"]  # the 2-sighting plant isn't looked up


def test_plant_of_the_day_cycles_through_every_plant(tmp_path):
    from sitegen.data import Site
    from sitegen.pages import plant_of_the_day
    from tests.test_sitegen import _write

    records = [
        {"id": f"p{i}", "kind": "plant", "taxon_id": i, "title": f"Plant {i}", "url": f"u{i}", "summary": "s"}
        for i in range(10)
    ] + [{"id": "x", "kind": "plant", "taxon_id": 99, "title": "No summary", "url": "ux", "summary": ""}]
    _write(tmp_path, "native_plants_spotlight", records, kind="plant")
    site = Site(tmp_path)
    start = date(2026, 11, 2)
    picks = [plant_of_the_day(site, start + timedelta(days=d))["taxon_id"] for d in range(10)]
    assert sorted(picks) == list(range(10))  # ten days, ten different plants
    assert plant_of_the_day(site, start) == plant_of_the_day(site, start)  # the same all day
    assert picks != sorted(picks)  # shuffled, so relatives (adjacent ids) don't run back to back

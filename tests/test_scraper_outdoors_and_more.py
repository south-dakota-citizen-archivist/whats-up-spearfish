"""
tests/test_scraper_outdoors_and_more.py

Whole-scrape tests (network faked) for the creek gauge, eBird, the humane
society, Leone's and Sawyer: what each source sends back, and what we keep.
"""

from __future__ import annotations

import json

import pytest
from bs4 import BeautifulSoup


class Resp:
    def __init__(self, data=None, text="", ok=True):
        self._data, self.text, self.ok = data, text, ok

    def json(self):
        return self._data

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("HTTP error")


# ── creek gauge (USGS Water Data API) ────────────────────────────────────────


def _feature(t, v, **kw):
    return {"properties": {"time": t, "value": v, **kw}}


def test_creek_gauge_sorts_skips_gaps_follows_pages_and_uses_local_time(monkeypatch):
    from scrapers.sources import creek_gauge as cg

    pages = {
        # continuous flow, out of order, split across two pages, one missing value
        ("continuous", cg.FLOW, None): {
            "features": [_feature(f"2026-11-02T18:{m:02d}:00+00:00", "37.0") for m in (45, 15, 30)]
            + [_feature("2026-11-02T18:00:00+00:00", None)],
            "links": [{"rel": "next", "href": "NEXT"}],
        },
        "NEXT": {"features": [_feature("2026-11-02T19:00:00+00:00", "37.3")], "links": []},
        ("continuous", cg.HEIGHT, None): {"features": [_feature("2026-11-02T19:00:00+00:00", "4.83")], "links": []},
        ("daily", cg.FLOW, cg.DAILY_MEAN): {
            "features": [_feature("2026-11-01", "35.4"), _feature("2026-10-31", "35.0")],
            "links": [],
        },
    }
    seen = []

    def get(url, params=None, **kw):
        seen.append(url)
        if url == "NEXT":
            return Resp(pages["NEXT"])
        collection = url.rsplit("/", 2)[-2]
        assert params["monitoring_location_id"] == "USGS-06431500"
        return Resp(pages[(collection, params["parameter_code"], params.get("statistic_id"))])

    monkeypatch.setattr(cg.net, "get", get)
    out = cg.CreekGauge().scrape()
    assert out["current"] == {"cfs": 37, "ft": 4.83, "time": "2026-11-02T12:00:00-07:00"}  # 19:00 UTC, in Spearfish
    assert [p["t"] for p in out["series7d"]] == ["2026-11-02T11:15:00-07:00"]  # every 4th of 4 sorted readings
    assert out["daily30"] == [{"date": "2026-10-31", "cfs": 35}, {"date": "2026-11-01", "cfs": 35}]
    assert "NEXT" in seen  # followed the "next" link
    assert cg.CreekGauge().is_empty({"current": {}})


# ── eBird ────────────────────────────────────────────────────────────────────


def test_ebird_sightings_with_one_photo_lookup_per_species(monkeypatch):
    from scrapers.sources import ebird

    sightings = [
        {"subId": "S1", "speciesCode": "bkbmag1", "comName": "Black-billed Magpie", "sciName": "Pica hudsonia",
         "obsDt": "2026-11-01 08:30", "howMany": 3, "locName": "Spearfish City Park", "lat": 44.49, "lng": -103.86},
        {"subId": "S2", "speciesCode": "bkbmag1", "comName": "Black-billed Magpie", "sciName": "Pica hudsonia",
         "obsDt": "2026-11-02 09:00", "howMany": 1, "locName": "Lookout Mountain"},
        {"subId": "S3", "speciesCode": "amedip", "comName": "American Dipper", "sciName": "Cinclus mexicanus",
         "obsDt": "2026-11-02 10:00"},
    ]  # fmt: skip
    inat_calls = []

    def get(url, params=None, headers=None, **kw):
        if "ebird" in url:
            assert headers["X-eBirdApiToken"] == "k" and params["dist"] == ebird.RADIUS_KM
            return Resp(sightings)
        inat_calls.append(params["q"])
        if params["q"] == "Cinclus mexicanus":
            return Resp({"results": []})  # no photo found
        return Resp({"results": [{"name": "Pica hudsonia", "default_photo": {"square_url": "https://x/square.jpg"}}]})

    monkeypatch.setenv("EBIRD_API_KEY", "k")
    monkeypatch.setattr(ebird.net, "get", get)
    monkeypatch.setattr(ebird.time, "sleep", lambda s: None)
    out = ebird.EBird().scrape()
    assert inat_calls == ["Pica hudsonia", "Cinclus mexicanus"]  # once per species
    assert [o["obs_key"] for o in out] == ["S1:bkbmag1", "S2:bkbmag1", "S3:amedip"]
    assert out[0]["photo_url"] == "https://x/square.jpg" and out[2]["photo_url"] == ""
    assert out[0]["url"] == "https://ebird.org/checklist/S1" and out[0]["count"] == 3


def test_ebird_needs_its_key(monkeypatch):
    from scrapers.sources import ebird

    monkeypatch.delenv("EBIRD_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        ebird.EBird().scrape()


# ── Western Hills Humane Society ─────────────────────────────────────────────


def _pets_page(items):
    ctx = json.dumps({"userItems": items}).replace('"', "&quot;")
    return f'<ul data-controller="UserItemsListSimple" data-current-context="{ctx}"></ul>'


def test_humane_society_pets(monkeypatch):
    from scrapers.sources import whhs_adoptable as whhs

    cats = [
        {"title": "Domino", "description": "<p>Sweet &amp; shy.</p><p>Loves   naps.</p>",
         "image": {"assetUrl": "https://images.squarespace-cdn.com/domino.jpg"}},
        {"title": "  ", "description": "no name, skipped"},
    ]  # fmt: skip
    dogs = [{"title": "Sunny", "description": "", "image": {}}]

    def get(url, **kw):
        return Resp(text=_pets_page(cats if url.endswith("/cats") else dogs))

    monkeypatch.setattr(whhs.net, "get", get)
    out = whhs.WHHSAdoptable().scrape()
    assert [(p["title"], p["species"]) for p in out] == [("Domino", "cat"), ("Sunny", "dog")]
    assert out[0]["description"] == "Sweet & shy.\nLoves naps."
    assert out[0]["image_url"].endswith("domino.jpg?format=500w") and out[1]["image_url"] == ""
    assert out[0]["slug"] == "cat-domino"


def test_humane_society_page_without_list(monkeypatch):
    from scrapers.sources import whhs_adoptable as whhs

    monkeypatch.setattr(whhs.net, "get", lambda url, **kw: Resp(text="<html>Maintenance</html>"))
    assert whhs.WHHSAdoptable().scrape() == []


# ── Leone's Creamery ─────────────────────────────────────────────────────────


def test_leones_flavors_with_details(monkeypatch):
    from scrapers.sources import leones_creamery as leones

    listing = """
      <a class="spearfish-flavors_features-list_item" href="/flavor-detail/blueberry">
        <img src="https://leonescreamery.com/b.jpg" alt="Blueberry"><h3>Blueberry Goat Cheese</h3></a>
      <a class="spearfish-flavors_features-list_item" href="/flavor-detail/blueberry"><h3>Duplicate</h3></a>
      <a class="spearfish-flavors_features-list_item" href="/flavor-detail/sweet-cream">
        <img src="s.jpg" alt="Sweet Cream"></a>
      <a class="spearfish-flavors_features-list_item" href="/flavor-detail/broken"><h4>Broken Page</h4></a>
    """
    detail = '<p class="text-size-medium">Tangy and sweet.</p><p class="text-size-medium">Gluten-free: Yes</p>'

    def fetch(url, **kw):
        if url.endswith("/broken"):
            raise ConnectionError("timeout")
        return BeautifulSoup(listing if url == leones.SOURCE_URL else detail, "html.parser")

    monkeypatch.setattr(leones, "fetch_html", fetch)
    out = leones.LeonesCreamery().scrape()
    assert [f["title"] for f in out] == ["Blueberry Goat Cheese", "Sweet Cream", "Broken Page"]  # no duplicate
    assert out[0]["url"] == "https://leonescreamery.com/flavor-detail/blueberry"
    assert out[0]["description"] == "Tangy and sweet." and out[0]["gluten_free"] is True
    assert "description" not in out[2]  # a detail page that fails keeps the flavor, minus details


# ── Sawyer Brewing (labels read by OCR) ──────────────────────────────────────


def test_sawyer_reads_beer_sections_only(monkeypatch):
    from scrapers.sources import sawyer_brewing as sawyer

    def block(inner):
        return f'<div class="sqs-block-website-component">{inner}</div>'

    page = "".join(
        [
            block("Hop Heads"),
            block('<img src="https://images.squarespace-cdn.com/ipa.png?format=750w">'),
            block('<img src="https://images.squarespace-cdn.com/smudged.png">'),  # OCR can't read it
            block('<img src="https://images.squarespace-cdn.com/known.png">'),  # OCR fails; the lookup knows it
            block("Wine"),
            block('<img src="https://images.squarespace-cdn.com/merlot.png">'),  # not a beer section
        ]
    )
    labels = {"ipa.png": "Cadillac Couch Mexican Lager\n\nCrisp, with lime.\n\nABV 4.8%", "smudged.png": "x"}

    def ocr(url):
        name = url.rsplit("/", 1)[-1]
        if name == "known.png":
            raise OSError("tesseract crashed")
        return labels[name]

    monkeypatch.setattr(sawyer, "fetch_html", lambda url, **kw: BeautifulSoup(page, "html.parser"))
    monkeypatch.setattr(sawyer, "ocr_label", ocr)
    monkeypatch.setattr(
        sawyer, "_load_lookup", lambda: {"known.png": {"title": "Blood Orange Blonde Ale", "abv": "5%"}}
    )
    out = sawyer.SawyerBrewing().scrape()
    assert [(b["title"], b["category"]) for b in out] == [
        ("Cadillac Couch Mexican Lager", "Hop Heads"),
        ("Blood Orange Blonde Ale", "Hop Heads"),
    ]
    assert out[0]["abv"] == "4.8%" and out[0]["image_url"] == "https://images.squarespace-cdn.com/ipa.png"

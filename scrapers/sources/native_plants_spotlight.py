"""
scrapers/sources/native_plants_spotlight.py

Plants native to the Black Hills, for a "native plant of the day."

From iNaturalist: every plant species with research-grade sightings in the
Black Hills (the National Forest plus the EPA ecoregions of the Core Highlands,
Foothills and Plateau) that iNaturalist counts as native there, with a photo,
a short Wikipedia summary and the photo's credit (the photos are Creative
Commons licensed and need it). The list changes slowly; the site picks one
plant per day from it (sitegen.pages.plant_of_the_day).
"""

from __future__ import annotations

import re
import time

from scrapers import net
from scrapers.base import BaseScraper

API = "https://api.inaturalist.org/v1"
#: Black Hills National Forest; Black Hills Core Highlands, Foothills and Plateau ecoregions
PLACES = "133194,137084,145898,136545"
MIN_SIGHTINGS = 5  # leave out one-off records
_HEADERS = {"User-Agent": "whats-up-spearfish (https://github.com/south-dakota-citizen-archivist/whats-up-spearfish)"}


def _get(path: str, **params) -> dict:
    resp = net.get(f"{API}/{path}", params=params, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    time.sleep(1)  # iNaturalist asks for no more than about one request a second
    return resp.json()


def summary(html: str, sentences: int = 2) -> str:
    """The first couple of sentences of a Wikipedia summary, as plain text."""
    text = " ".join(re.sub(r"<[^>]+>", " ", html or "").split())
    text = re.sub(r"\s+([,.;:)])", r"\1", re.sub(r"\(\s+", "(", text))  # spaces left where tags were
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z])", text)
    return " ".join(parts[:sentences])


def plant_record(taxon: dict, sightings: int) -> dict | None:
    photo = taxon.get("default_photo") or {}
    if not photo.get("medium_url"):
        return None  # the spotlight is a picture first
    common = taxon.get("preferred_common_name") or ""
    return {
        "taxon_id": taxon["id"],
        "title": common[:1].upper() + common[1:] if common else taxon["name"],
        "scientific_name": taxon["name"],
        "summary": summary(taxon.get("wikipedia_summary") or ""),
        "image_url": photo["medium_url"],
        "photo_credit": photo.get("attribution") or "",
        "url": f"https://www.inaturalist.org/taxa/{taxon['id']}",
        "wikipedia_url": taxon.get("wikipedia_url") or "",
        "sightings": sightings,
    }


class NativePlantSpotlight(BaseScraper):
    name = "Native plants of the Black Hills"
    slug = "native_plants_spotlight"
    kind = "plant"
    url = "https://www.inaturalist.org/places/black-hills-national-forest-us"
    dedup_key = "taxon_id"
    replace = True
    max_stale_hours = 24 * 7

    def scrape(self) -> list[dict]:
        counts: dict[int, int] = {}
        page = 1
        while True:
            data = _get(
                "observations/species_counts",
                place_id=PLACES,
                iconic_taxa="Plantae",
                rank="species",
                quality_grade="research",
                native="true",
                per_page=500,
                page=page,
            )
            for r in data["results"]:
                if r["count"] >= MIN_SIGHTINGS:
                    counts[r["taxon"]["id"]] = r["count"]
            if page * 500 >= data["total_results"] or not data["results"]:
                break
            page += 1

        # full taxon records (with the Wikipedia summary), 30 at a time
        plants = []
        ids = sorted(counts)
        for i in range(0, len(ids), 30):
            for taxon in _get("taxa/" + ",".join(map(str, ids[i : i + 30])))["results"]:
                if rec := plant_record(taxon, counts.get(taxon["id"], 0)):
                    plants.append(rec)
        return plants

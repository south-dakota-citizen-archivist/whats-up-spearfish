"""
scrapers/sources/spearfish_school_lunch.py

Spearfish school lunch and breakfast menus via HealthePro/NutriSlice API.

One SchoolMenuScraper subclass per menu. Each emits record_type="school_menu"
so the build can separate them from calendar events.
"""

from __future__ import annotations

import json
import re
from datetime import date, timedelta

import requests

from scrapers.base import BaseScraper
from scrapers.utils import make_slug

_HTML_TAG_RE = re.compile(r"<[^>]+>")

ORG_ID = 524
_OVERWRITES_URL = "https://menus.healthepro.com/api/organizations/{org}/menus/{menu}/year/{year}/month/{month}/date_overwrites"
_RECIPES_URL = "https://menus.healthepro.com/api/organizations/{org}/menus/{menu}/start_date/{start}/end_date/{end}/recipes/"

_HEADERS = {"User-Agent": "Mozilla/5.0"}


def _fetch_month_overwrites(org: int, menu: int, year: int, month: int) -> list[dict]:
    url = _OVERWRITES_URL.format(org=org, menu=menu, year=year, month=month)
    resp = requests.get(url, headers=_HEADERS, timeout=15)
    resp.raise_for_status()
    return resp.json().get("data", [])


def _fetch_recipes(org: int, menu: int, start: str, end: str) -> dict[int, dict]:
    url = _RECIPES_URL.format(org=org, menu=menu, start=start, end=end)
    resp = requests.get(url, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    lookup: dict[int, dict] = {}
    for r in resp.json().get("data", []):
        rid = r.get("id")
        if not rid:
            continue
        nutr = r.get("nutrients") or {}
        lookup[rid] = {
            "name": (r.get("name") or "").lstrip("* ").strip(),
            "description": r.get("content") or "",
            "ingredients": r.get("ingredients") or "",
            "image_url": (r.get("image_path") or "").split("?")[0],
            "serving_size": _HTML_TAG_RE.sub("", nutr.get("serving_size", "")),
            "is_entree": bool((r.get("category") or {}).get("entree")),
            "category_name": (r.get("category") or {}).get("category", ""),
            "nutrition": _parse_nutrition(nutr),
        }
    return lookup


def _parse_nutrition(nutr: dict) -> dict:
    fields = [
        ("calories", "calories_kcal"),
        ("fat_g", "total_fat_grams"),
        ("sat_fat_g", "saturated_fat_grams"),
        ("carbs_g", "carbohydrates_grams"),
        ("fiber_g", "fiber_grams"),
        ("protein_g", "protein_grams"),
        ("sodium_mg", "sodium_milligrams"),
    ]
    result = {}
    for key, api_key in fields:
        raw = str(nutr.get(api_key) or "").rstrip("*").strip()
        try:
            val = float(raw)
        except ValueError:
            continue
        if val > 0:
            result[key] = round(val, 1) if val < 10 else round(val)
    return result


def _parse_day(entry: dict, recipe_lookup: dict[int, dict], record_slug_prefix: str,
               source_url: str, source_label: str) -> dict | None:
    day_str = entry.get("day", "")
    try:
        setting = json.loads(entry["setting"])
    except (KeyError, json.JSONDecodeError):
        return None

    items = setting.get("current_display", [])
    recipe_names = [i["name"] for i in items if i.get("type") == "recipe"]
    if any("no school" in n.lower() for n in recipe_names) or not recipe_names:
        return None

    current_category = ""
    menu_items: list[dict] = []
    for item in items:
        if item.get("type") == "category":
            current_category = item["name"]
            continue
        if item.get("type") != "recipe":
            continue

        rid = item.get("item")
        is_entree_by_name = str(item.get("name", "")).startswith("*")
        name_clean = str(item.get("name", "")).lstrip("* ").strip()

        if isinstance(rid, int) and rid in recipe_lookup:
            info = recipe_lookup[rid]
            menu_items.append({
                "id": rid,
                "name": info["name"] or name_clean,
                "category": current_category,
                "is_entree": info["is_entree"] or is_entree_by_name,
                "description": info["description"],
                "ingredients": info["ingredients"],
                "image_url": info["image_url"],
                "serving_size": info["serving_size"],
                "nutrition": info["nutrition"],
            })
        else:
            menu_items.append({
                "id": None,
                "name": name_clean,
                "category": current_category,
                "is_entree": is_entree_by_name,
                "description": "",
                "ingredients": "",
                "image_url": "",
                "serving_size": "",
                "nutrition": {},
            })

    if not menu_items:
        return None

    entrees = [m["name"] for m in menu_items if m["is_entree"]]
    display = entrees[:3] if entrees else [m["name"] for m in menu_items[:3]]
    title = ", ".join(display)
    if len(entrees) > 3 or (not entrees and len(menu_items) > 3):
        title += "…"

    sides = [m["name"] for m in menu_items if not m["is_entree"]]
    description = "With: " + ", ".join(sides) if sides else ""

    return {
        "url": source_url,
        "title": title,
        "slug": make_slug(f"{record_slug_prefix}-{day_str}"),
        "start_dt": day_str,
        "description": description,
        "menu_items": menu_items,
        "record_type": "school_menu",
        "source_label": source_label,
    }


class SchoolMenuScraper(BaseScraper):
    """Base class for HealthePro/NutriSlice school menu scrapers."""
    dedup_key = "slug"
    menu_id: int = 0
    source_url: str = ""

    def scrape(self) -> list[dict]:
        today = date.today()
        next_month_start = today.replace(day=1) + timedelta(days=32)

        start = today.replace(day=1).isoformat()
        end_next = (next_month_start.replace(day=1) + timedelta(days=32)).replace(day=1) - timedelta(days=1)
        recipe_lookup = _fetch_recipes(ORG_ID, self.menu_id, start, end_next.isoformat())

        months = [(today.year, today.month), (next_month_start.year, next_month_start.month)]
        records = []
        seen: set[str] = set()
        for year, month in months:
            for entry in _fetch_month_overwrites(ORG_ID, self.menu_id, year, month):
                record = _parse_day(entry, recipe_lookup, self.slug, self.source_url, self.name)
                if record and record["slug"] not in seen:
                    seen.add(record["slug"])
                    records.append(record)
        return records


# ── Lunch menus ────────────────────────────────────────────────────────────────

class SpearfishHSLunch(SchoolMenuScraper):
    name = "High School Lunch"
    slug = "spearfish_hs_lunch"
    menu_id = 100124
    source_url = "https://menus.healthepro.com/organizations/524/sites/4520/menus/100124"


class SpearfishMSLunch(SchoolMenuScraper):
    name = "Middle School Lunch"
    slug = "spearfish_ms_lunch"
    menu_id = 100125
    source_url = "https://menus.healthepro.com/organizations/524/sites/4521/menus/100125"


class SpearfishElemK2Lunch(SchoolMenuScraper):
    name = "Elementary K-2 Lunch"
    slug = "spearfish_elem_k2_lunch"
    menu_id = 119106
    source_url = "https://menus.healthepro.com/organizations/524/sites/4523/menus/119106"


class SpearfishElem35Lunch(SchoolMenuScraper):
    name = "Elementary 3-5 Lunch"
    slug = "spearfish_elem_35_lunch"
    menu_id = 100127
    source_url = "https://menus.healthepro.com/organizations/524/sites/4523/menus/100127"


# ── Breakfast menus ────────────────────────────────────────────────────────────

class SpearfishElemBreakfast(SchoolMenuScraper):
    name = "Elementary Breakfast"
    slug = "spearfish_elem_breakfast"
    menu_id = 100128
    source_url = "https://menus.healthepro.com/organizations/524/sites/4519/menus/100128"


class SpearfishMSHSBreakfast(SchoolMenuScraper):
    name = "MS/HS Breakfast"
    slug = "spearfish_mshs_breakfast"
    menu_id = 100126
    source_url = "https://menus.healthepro.com/organizations/524/sites/4520/menus/100126"

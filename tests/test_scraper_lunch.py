"""
tests/test_scraper_lunch.py

Tests for scrapers/sources/spearfish_school_lunch.py:
_parse_nutrition and _parse_day (pure logic, no HTTP).
"""

from __future__ import annotations

import json

from scrapers.sources.spearfish_school_lunch import _parse_day, _parse_nutrition

# ---------------------------------------------------------------------------
# _parse_nutrition
# ---------------------------------------------------------------------------

class TestParseNutrition:
    def test_extracts_calories(self):
        assert _parse_nutrition({"calories_kcal": "500"})["calories"] == 500

    def test_extracts_protein(self):
        assert _parse_nutrition({"protein_grams": "25"})["protein_g"] == 25

    def test_extracts_all_fields(self):
        nutr = {
            "calories_kcal": "600",
            "total_fat_grams": "20",
            "saturated_fat_grams": "5",
            "carbohydrates_grams": "80",
            "fiber_grams": "3",
            "protein_grams": "25",
            "sodium_milligrams": "800",
        }
        result = _parse_nutrition(nutr)
        assert set(result.keys()) == {"calories", "fat_g", "sat_fat_g", "carbs_g",
                                       "fiber_g", "protein_g", "sodium_mg"}

    def test_strips_star_suffix(self):
        result = _parse_nutrition({"calories_kcal": "450*", "protein_grams": "18*"})
        assert result["calories"] == 450
        assert result["protein_g"] == 18

    def test_excludes_zero_values(self):
        result = _parse_nutrition({"calories_kcal": "0", "protein_grams": "20"})
        assert "calories" not in result
        assert result["protein_g"] == 20

    def test_skips_non_numeric(self):
        result = _parse_nutrition({"calories_kcal": "N/A", "protein_grams": "15"})
        assert "calories" not in result
        assert result["protein_g"] == 15

    def test_rounds_large_values_to_int(self):
        result = _parse_nutrition({"calories_kcal": "523.7"})
        assert result["calories"] == 524
        assert isinstance(result["calories"], int)

    def test_keeps_decimal_for_small_values(self):
        result = _parse_nutrition({"fiber_grams": "2.5"})
        assert result["fiber_g"] == 2.5

    def test_empty_dict_returns_empty(self):
        assert _parse_nutrition({}) == {}

    def test_empty_string_value_skipped(self):
        result = _parse_nutrition({"calories_kcal": "", "protein_grams": "20"})
        assert "calories" not in result


# ---------------------------------------------------------------------------
# _parse_day
# ---------------------------------------------------------------------------

class TestParseDay:
    _LOOKUP = {
        1: {
            "name": "Cheeseburger",
            "description": "Classic burger",
            "ingredients": "Beef, bun",
            "image_url": "",
            "serving_size": "1 each",
            "is_entree": True,
            "category_name": "Entree",
            "nutrition": {"calories": 450},
        },
        2: {
            "name": "Apple Slices",
            "description": "",
            "ingredients": "Apples",
            "image_url": "",
            "serving_size": "0.5 cup",
            "is_entree": False,
            "category_name": "Fruit",
            "nutrition": {"calories": 50},
        },
    }

    def _entry(self, day="2026-04-01", items=None):
        if items is None:
            items = [
                {"type": "category", "name": "Entree"},
                {"type": "recipe", "item": 1, "name": "*Cheeseburger"},
                {"type": "recipe", "item": 2, "name": "Apple Slices"},
            ]
        return {"day": day, "setting": json.dumps({"current_display": items})}

    def _call(self, entry=None, lookup=None):
        return _parse_day(
            entry or self._entry(),
            lookup if lookup is not None else self._LOOKUP,
            "test_slug",
            "http://example.com",
            "Test School",
        )

    # ── Basic extraction ──────────────────────────────────────────────────────

    def test_returns_record(self):
        assert self._call() is not None

    def test_record_type(self):
        assert self._call()["record_type"] == "school_menu"

    def test_start_dt_is_day_string(self):
        assert self._call()["start_dt"] == "2026-04-01"

    def test_source_label(self):
        assert self._call()["source_label"] == "Test School"

    def test_entree_in_title(self):
        assert "Cheeseburger" in self._call()["title"]

    def test_side_in_description(self):
        assert "Apple Slices" in self._call()["description"]

    def test_menu_items_list(self):
        result = self._call()
        assert len(result["menu_items"]) == 2

    def test_menu_item_names(self):
        names = [m["name"] for m in self._call()["menu_items"]]
        assert "Cheeseburger" in names
        assert "Apple Slices" in names

    # ── No-school filtering ───────────────────────────────────────────────────

    def test_no_school_returns_none(self):
        entry = self._entry(items=[{"type": "recipe", "item": None, "name": "No School"}])
        assert self._call(entry=entry) is None

    def test_no_school_case_insensitive(self):
        entry = self._entry(items=[{"type": "recipe", "item": None, "name": "NO SCHOOL DAY"}])
        assert self._call(entry=entry) is None

    def test_empty_recipe_list_returns_none(self):
        entry = self._entry(items=[{"type": "category", "name": "Entree"}])
        assert self._call(entry=entry) is None

    # ── Invalid input ─────────────────────────────────────────────────────────

    def test_invalid_setting_json_returns_none(self):
        entry = {"day": "2026-04-01", "setting": "not json{"}
        assert self._call(entry=entry) is None

    def test_missing_setting_key_returns_none(self):
        entry = {"day": "2026-04-01"}
        assert self._call(entry=entry) is None

    # ── Unknown recipe id falls back to item name ─────────────────────────────

    def test_unknown_recipe_id_uses_item_name(self):
        entry = self._entry(items=[{"type": "recipe", "item": 999, "name": "Mystery Food"}])
        result = self._call(entry=entry, lookup={})
        assert result is not None
        assert "Mystery Food" in result["title"]

    # ── Entree detection via asterisk ─────────────────────────────────────────

    def test_star_prefix_marks_as_entree(self):
        items = [{"type": "recipe", "item": 999, "name": "*Star Entree"}]
        entry = self._entry(items=items)
        result = self._call(entry=entry, lookup={})
        assert result is not None
        entrees = [m for m in result["menu_items"] if m["is_entree"]]
        assert len(entrees) == 1

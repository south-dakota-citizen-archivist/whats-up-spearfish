"""
tests/test_build_new.py

Tests for build.py functionality added since the original test suite:
  - intcomma filter
  - load_danr_notices() deadline normalization and past-flagging
  - load_bhnf_projects() past-flag logic
  - load_circulation() y-tick generation
"""

from __future__ import annotations

import datetime
import json
from pathlib import Path
from unittest.mock import patch

import pytest

_TODAY = datetime.date(2026, 4, 4)


# ---------------------------------------------------------------------------
# intcomma filter
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def jinja_env():
    import build

    with patch("build.TODAY", _TODAY):
        return build.make_env()


class TestIntcomma:
    def test_thousands(self, jinja_env):
        f = jinja_env.filters["intcomma"]
        assert f(1000) == "1,000"

    def test_zero(self, jinja_env):
        f = jinja_env.filters["intcomma"]
        assert f(0) == "0"

    def test_large(self, jinja_env):
        f = jinja_env.filters["intcomma"]
        assert f(9482) == "9,482"

    def test_string_int(self, jinja_env):
        f = jinja_env.filters["intcomma"]
        assert f("5539") == "5,539"

    def test_none_returns_none_string(self, jinja_env):
        f = jinja_env.filters["intcomma"]
        assert f(None) == "None"

    def test_non_numeric_string_returned_as_is(self, jinja_env):
        f = jinja_env.filters["intcomma"]
        assert f("n/a") == "n/a"


# ---------------------------------------------------------------------------
# load_danr_notices() — deadline ISO normalization and past-flagging
# ---------------------------------------------------------------------------


class TestLoadDanrNotices:
    def _call(self, notices, today=_TODAY):
        import tempfile

        import build

        data = {"fetched_at": "2026-04-04T00:00:00+00:00", "notices": notices}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            tmp = Path(f.name)

        with patch("build.TODAY", today), patch("build.DATA_DIR", tmp.parent):
            # Temporarily rename so load_danr_notices picks it up
            target = tmp.parent / "danr_public_notices.json"
            tmp.rename(target)
            result = build.load_danr_notices()
            target.unlink(missing_ok=True)
        return result

    def test_future_deadline_not_past(self):
        notices = [{"deadline": "05/01/2026", "location": "Lawrence County"}]
        result = self._call(notices)
        assert result[0]["deadline_past"] is False

    def test_past_deadline_flagged(self):
        notices = [{"deadline": "03/01/2026", "location": "Pennington"}]
        result = self._call(notices)
        assert result[0]["deadline_past"] is True

    def test_today_deadline_not_past(self):
        notices = [{"deadline": "04/04/2026", "location": "Meade County"}]
        result = self._call(notices)
        assert result[0]["deadline_past"] is False

    def test_iso_set_correctly(self):
        notices = [{"deadline": "04/23/2026", "location": "Custer County"}]
        result = self._call(notices)
        assert result[0]["deadline_iso"] == "2026-04-23"

    def test_unparseable_deadline_not_past(self):
        notices = [{"deadline": "Unknown", "location": "Pennington"}]
        result = self._call(notices)
        assert result[0]["deadline_past"] is False
        assert result[0]["deadline_iso"] == ""

    def test_empty_deadline(self):
        notices = [{"deadline": "", "location": "Lawrence County"}]
        result = self._call(notices)
        assert result[0]["deadline_past"] is False

    def test_empty_notices_returns_empty(self):
        assert self._call([]) == []


# ---------------------------------------------------------------------------
# load_bhnf_projects() — comment_period_past flag
# ---------------------------------------------------------------------------


class TestLoadBhnfProjects:
    def _call(self, projects, today=_TODAY):
        import tempfile

        import build

        data = {"fetched_at": "2026-04-04T00:00:00+00:00", "projects": projects}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            tmp = Path(f.name)

        with patch("build.TODAY", today), patch("build.DATA_DIR", tmp.parent):
            target = tmp.parent / "bhnf_projects.json"
            tmp.rename(target)
            result = build.load_bhnf_projects()
            target.unlink(missing_ok=True)
        return result

    def _base_project(self, **kwargs):
        p = {
            "project_id": "1",
            "title": "Test Project",
            "status": "In Progress",
            "district": "Northern Hills Ranger District",
            "purpose": "Recreation Management",
            "description": "",
            "milestones": [],
            "comment_period_date": None,
            "comment_period_sort": "9999-99",
            "location_summary": "",
            "counties": [],
            "contact": {},
            "last_updated": "",
        }
        p.update(kwargs)
        return p

    def test_only_in_progress_returned(self):
        projects = [
            self._base_project(status="In Progress"),
            self._base_project(status="Completed"),
            self._base_project(status="Cancelled"),
        ]
        result = self._call(projects)
        assert len(result) == 1

    def test_future_comment_period_not_past(self):
        p = self._base_project(
            comment_period_date="06/2026 (Estimated)",
            comment_period_sort="2026-06",
        )
        result = self._call([p])
        assert result[0]["comment_period_past"] is False

    def test_past_comment_period_flagged(self):
        p = self._base_project(
            comment_period_date="02/2026 (Estimated)",
            comment_period_sort="2026-02",
        )
        result = self._call([p])
        assert result[0]["comment_period_past"] is True

    def test_current_month_not_past(self):
        p = self._base_project(
            comment_period_date="04/2026 (Estimated)",
            comment_period_sort="2026-04",
        )
        result = self._call([p])
        assert result[0]["comment_period_past"] is False

    def test_no_comment_period_not_past(self):
        p = self._base_project(comment_period_date=None, comment_period_sort="9999-99")
        result = self._call([p])
        assert result[0]["comment_period_past"] is False

    def test_empty_projects_returns_empty(self):
        assert self._call([]) == []


# ---------------------------------------------------------------------------
# load_circulation() — y-tick generation
# ---------------------------------------------------------------------------


class TestLoadCirculationYTicks:
    def _make_rows(self, loans_per_month):
        """Build minimal row list with given physical loan counts."""
        rows = []
        year, month = 2022, 1
        for loans in loans_per_month:
            rows.append(
                {
                    "year": year,
                    "month": month,
                    "month_name": "Jan",
                    "loans": loans,
                    "renewals": None,
                    "overdrive_loans": None,
                    "hoopla_loans": None,
                    "minutes_link": None,
                }
            )
            month += 1
            if month > 12:
                month = 1
                year += 1
        return rows

    def _call(self, rows):
        import tempfile

        import build

        data = {"fetched_at": "2026-04-04T00:00:00+00:00", "rows": rows}
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(data, f)
            tmp = Path(f.name)

        with patch("build.TODAY", _TODAY), patch("build.DATA_DIR", tmp.parent):
            target = tmp.parent / "library_circulation.json"
            tmp.rename(target)
            result = build.load_circulation()
            target.unlink(missing_ok=True)
        return result

    def test_y_ticks_present(self):
        rows = self._make_rows([7000] * 3)
        result = self._call(rows)
        assert "y_ticks" in result["chart"]

    def test_y_ticks_all_below_max(self):
        loans = [8000, 6000, 7500]
        rows = self._make_rows(loans)
        result = self._call(rows)
        max_loan = max(loans) * 1.05
        for tick in result["chart"]["y_ticks"]:
            assert tick["value"] < max_loan

    def test_y_tick_labels_end_in_k(self):
        rows = self._make_rows([9000] * 3)
        result = self._call(rows)
        for tick in result["chart"]["y_ticks"]:
            assert tick["label"].endswith("k")

    def test_step_5000_for_large_data(self):
        # max > 12000 → step 5000
        rows = self._make_rows([13000, 12000, 14000])
        result = self._call(rows)
        values = [t["value"] for t in result["chart"]["y_ticks"]]
        assert all(v % 5000 == 0 for v in values)

    def test_step_2500_for_small_data(self):
        # max ≤ 12000 → step 2500
        rows = self._make_rows([6000, 5000, 7000])
        result = self._call(rows)
        values = [t["value"] for t in result["chart"]["y_ticks"]]
        assert all(v % 2500 == 0 for v in values)

    def test_y_ticks_have_y_coordinate(self):
        rows = self._make_rows([7000] * 3)
        result = self._call(rows)
        for tick in result["chart"]["y_ticks"]:
            assert "y" in tick
            assert 0 <= tick["y"] <= 90  # within CHART_H

    def test_no_chart_for_single_row(self):
        rows = self._make_rows([7000])
        result = self._call(rows)
        assert result["chart"] is None

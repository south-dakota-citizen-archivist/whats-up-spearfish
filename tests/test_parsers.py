"""
tests/test_parsers.py

Parsers for sources rewritten in the refactor, plus the README generator.
"""

from __future__ import annotations

from scrapers.sources.lawrence_county import parse_entry
from scrapers.sources.spearfish_city_feeds import parse_calendar_entry
from scripts.build_readme import END, START, render


class TestCityCalendar:
    def _entry(self, dates, times, summary=""):
        return {
            "title": "Toddler Story Time",
            "link": "https://www.spearfish.gov/Calendar.aspx?EID=1",
            "summary": summary,
            "published": "Tue, 01 Sep 2026 13:45:11 -0700",  # posting date — must be ignored
            "calendarevent_eventdates": dates,
            "calendarevent_eventtimes": times,
            "calendarevent_location": "Spearfish, SD 57783",
        }

    def test_timed_event_uses_event_dates_not_pubdate(self):
        r = parse_calendar_entry(self._entry("November 3, 2026", "09:30 AM - 10:15 AM"))
        assert r["start_dt"] == "2026-11-03T09:30:00"
        assert r["end_dt"] == "2026-11-03T10:15:00"
        assert r["all_day"] is False

    def test_multiday_all_day(self):
        r = parse_calendar_entry(self._entry("October 29, 2026 - November 1, 2026", "12:00 AM - 11:59 PM"))
        assert r["start_dt"] == "2026-10-29"
        assert r["end_dt"] == "2026-11-01"
        assert r["all_day"] is True

    def test_description_after_label(self):
        summary = "<strong>Event dates:</strong> x<br><strong>Description:</strong><br>Early literacy fun."
        assert (
            parse_calendar_entry(self._entry("November 3, 2026", "", summary))["description"] == "Early literacy fun."
        )

    def test_no_description_section(self):
        summary = "<strong>Event date:</strong> November 3, 2026<br><strong>Event Time: </strong>05:30 PM"
        assert parse_calendar_entry(self._entry("November 3, 2026", "", summary))["description"] == ""


class TestLawrenceCounty:
    def test_meeting_date_and_title_cleanup(self):
        r = parse_entry(
            {
                "title": "Lawrence County Planning & Zoning Regular Meeting Info - November 5, 2026 All applications "
                "and handouts are directly linked within the agenda. Questions? planning@lawrence.sd.us.",
                "link": "https://www.lawrence.sd.us/AgendaCenter/PreviousVersions/1361",
                "published": "Tue, 27 Oct 2026 08:12:10 -0700",
                "summary": "",
            }
        )
        assert r["meeting_date"] == "November 5, 2026"
        assert r["title"] == "Lawrence County Planning & Zoning Regular Meeting Info - November 5, 2026"

    def test_minutes_flag(self):
        r = parse_entry({"title": "x", "link": "l", "summary": "Update: Minutes added or updated"})
        assert r["updated_note"] == "minutes"


class TestReadme:
    def test_replaces_between_markers(self):
        out = render(f"# Title\n\n{START}\nold\n{END}\n\nfooter\n", "TABLE")
        assert "TABLE" in out and "old" not in out and out.endswith("footer\n")

    def test_appends_when_markers_missing(self):
        assert render("# Title\n", "TABLE").rstrip().endswith(END)


class TestSchoolApis:
    def test_event(self):
        from scrapers.sources.spearfish_schools import parse_event

        r = parse_event(
            {
                "id": 1,
                "title": "Early Release",
                "start_at": "2026-11-04T13:00:00.000-07:00",
                "end_at": "2026-11-04T13:30:00.000-07:00",
                "all_day": False,
                "venue": "HS",
                "city_state": "",
            }
        )
        assert r["start_dt"].startswith("2026-11-04T13:00") and r["location"] == "HS"
        allday = parse_event(
            {"id": 2, "title": "No School", "start_at": "2026-11-26T00:00:00.000-07:00", "all_day": True}
        )
        assert allday["start_dt"] == "2026-11-26"
        assert parse_event({"id": 3, "title": ""}) is None

    def test_article(self):
        from scrapers.sources.spearfish_school_news import parse_article

        r = parse_article(
            {
                "title": " Tiny Home ",
                "link": "https://x/article/1",
                "published_at": "2026-10-28T13:44:34-06:00",
                "snippet": "  Open   house ",
            }
        )
        assert r == {
            "title": "Tiny Home",
            "url": "https://x/article/1",
            "published": "2026-10-28T13:44:34-06:00",
            "description": "Open house",
            "image_url": "",
        }

    def test_nutrition_facts(self):
        from scrapers.sources.spearfish_school_lunch import nutrition_facts

        rows = nutrition_facts(
            {
                "calories_kcal": "504.000*",
                "saturated_fat_grams": "3.25",
                "calcium": "27.4",
                "calcium_measurement": "mg",
                "iron": "x",
            }
        )
        assert rows == [["Calories", "504", False], ["Saturated fat", "3.2 g", True], ["Calcium", "27 mg", False]]

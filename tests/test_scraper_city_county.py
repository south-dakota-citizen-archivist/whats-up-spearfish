"""
tests/test_scraper_city_county.py

City and county listings read from pages and APIs rather than their (empty) RSS
feeds: the city's Alert Center, the city job board and the county's job openings
page.
"""

from __future__ import annotations

from scrapers.sources.lawrence_county_feeds import parse_jobs_page
from scrapers.sources.spearfish_city_feeds import parse_alert_center, parse_job

ALERT_CENTER = """
<div id="AlertCenterContent">
 <div class="listing listingCollapse divCat_15">
  <div><h2 class="active">Road Closures</h2><span class="numAlerts">2  Alerts</span></div>
  <div><ol class="alerts-list no-bullets">
   <li id="alertItem" class="alerts-list"><div class="alert on first">
    <span id="alertDate_72" class="date">September 24, 2026 2:30 PM</span>
    <h3><a href="/AlertCenter.aspx?AID=City-of-Spearfish-Downtown-Street-Closur-72">City of Spearfish - Downtown
      Street Closure</a></h3>
    <p>Main Street is scheduled to be temporarily closed from Jackson Boulevard through Grant Street.... </p>
    <p>City of Spearfish - Downtown Street Closure Read On...</p>
   </div></li>
   <li id="alertItem" class="alerts-list"><div class="alert on">
    <span class="date">September 3, 2025</span>
    <h3><a href="/AlertCenter.aspx?AID=City-of-Spearfish-Labor-Day-Closures-33">City of Spearfish Labor Day
      Closures</a></h3>
    <p>City Hall Offices will be closed on Monday.</p><p></p>
   </div></li>
  </ol></div>
 </div>
</div>
"""


def test_alert_center_reads_each_alert_with_its_category_and_time():
    closure, labor_day = parse_alert_center(ALERT_CENTER)
    assert closure["title"] == "Downtown Street Closure"  # the city's name prefix is dropped
    assert closure["category"] == "Road Closures"
    assert closure["published"] == "2026-09-24T14:30:00"
    assert (
        closure["url"] == "https://www.spearfish.gov/AlertCenter.aspx?AID=City-of-Spearfish-Downtown-Street-Closur-72"
    )
    assert closure["description"].startswith("Main Street is scheduled")
    assert labor_day["title"] == "Labor Day Closures"
    assert labor_day["published"] == "2025-09-03T00:00:00"


def test_alert_center_with_no_alerts():
    assert parse_alert_center("<div id='AlertCenterContent'><p>No alerts.</p></div>") == []


def test_city_job_from_the_job_board():
    job = parse_job(
        {
            "title": "Police Officer ~Sign-on-Bonus $6,000",
            "salary": "Hiring range: $32.84 - $38.08",
            "openDate": "2025.10.16",
            "closeDate": None,
            "department": "Police",
            "location": "Police Department",
            "positionType": "FT Employee",
            "jobUrl": "https://cityofspearfish.sagehcm.com/jobs/443/1/#330",
        }
    )
    assert job["published"] == "2025-10-16"
    assert job["closing"] == ""
    assert job["department"] == "Police"
    assert job["url"].endswith("#330")
    assert job["description"] == "Police • FT Employee • Hiring range: $32.84 - $38.08"


COUNTY_JOBS = """
<div id="moduleContent">
 <h1>Employment Opportunities</h1>
 <ul>
  <li><a href="/DocumentCenter/View/2188/Job-Opening---Correctional-Officer-I-Part-Time-PDF">Job Opening -
    Correctional Officer I (Part Time) (PDF)</a></li>
  <li><a href="/DocumentCenter/View/2309/Job-Opening---Custodian-PDF">Job Opening - Custodian (PDF)</a></li>
 </ul>
 <h2>Additional Documents</h2>
 <a href="/DocumentCenter/View/375/Lawrence-County-Employment-Application-PDF">Lawrence County Employment
   Application (PDF)</a>
</div>
"""


def test_county_jobs_are_the_job_opening_links():
    jobs = parse_jobs_page(COUNTY_JOBS)
    assert [j["title"] for j in jobs] == ["Correctional Officer I (Part Time)", "Custodian"]
    assert jobs[1]["url"] == "https://lawrence.sd.us/DocumentCenter/View/2309/Job-Opening---Custodian-PDF"


def test_bhsu_posting_page_gives_salary_and_closing():
    from scrapers.sources.bhsu_jobs import parse_posting_page

    def page(closing, open_until):
        return (f"<table><tr><th>Posting Date</th><td>05/14/2025</td></tr>"
                f"<tr><th>Closing Date</th><td>{closing}</td></tr>"
                f"<tr><th>Open Until Filled</th><td>{open_until}</td></tr>"
                "<tr><th>Advertised Salary</th><td>$1,076-$1,317 per credit hour</td></tr></table>")  # fmt: skip

    assert parse_posting_page(page("", "Yes")) == {"salary": "$1,076-$1,317 per credit hour",
                                                   "closing": "Open until filled"}  # fmt: skip
    assert parse_posting_page(page("11/30/2026", "No"))["closing"] == "2026-11-30"
    assert parse_posting_page("<table></table>") == {}


NOTICE = """LAWRENCE COUNTY JOB OPENING NOTICE
Date: November 11th, 2025
Job Title: Correctional Officer I (Part-Time)
Department/Office: Sheriff’s Office
Closing Date: When Position is Filled
Start Date: To be set
Starting Pay: $24.08 to $26.61 DOE
Work Schedule: Hours will vary, including nights, weekends and holidays.
Submit Application/ Chief Deputy Patrick D. Johnson
Résumé to: Lawrence County Sheriff’s Office
Description of Duties: Processes Inmates, Conducts Work Release Program, Controls
Inmate Movement, and Provides Routine Medical Care to
Prisoners.
Experience/Education: Corrections Experience Desired.
Lawrence County is an equal opportunity employer."""


def test_county_job_notice():
    from scrapers.sources.lawrence_county_feeds import parse_notice

    notice = parse_notice(NOTICE)
    assert notice == {
        "title": "Correctional Officer I (Part-Time)",
        "department": "Sheriff’s Office",
        "published": "2025-11-11",
        "closing": "Open until filled",
        "salary": "$24.08 to $26.61 DOE",
        "description": "Processes Inmates, Conducts Work Release Program, Controls Inmate Movement, and Provides "
        "Routine Medical Care to Prisoners.",
    }
    dated = parse_notice(NOTICE.replace("When Position is Filled", "December 1, 2026"))
    assert dated["closing"] == "2026-12-01"


# ── city meetings: where each agenda item starts in the video ───────────────


def test_video_bookmarks_become_agenda_item_chapters():
    from scrapers.sources.spearfish_city import chapters_from

    marks = [
        {"id": 3, "markerTitle": "3.A. Hold a public hearing", "markerTimeStart": 714, "sortorder": 4, "parentId": 2},
        {"id": 1, "markerTitle": "1. Call to Order", "markerTimeStart": 677, "sortorder": 1, "parentId": -1},
        {"id": 2, "markerTitle": "3.  Action Items", "markerTimeStart": 711, "sortorder": 3, "parentId": -1,
         "additionalBookmarks": [{"id": 9, "markerTitle": "Motion", "markerTimeStart": 712}]},
        {"id": 4, "markerTitle": "", "markerTimeStart": 800, "sortorder": 5},  # untitled: skipped
    ]  # fmt: skip
    assert chapters_from(marks) == [
        {"id": 1, "t": 677, "title": "1. Call to Order", "sub": False},
        {"id": 2, "t": 711, "title": "3. Action Items", "sub": False},
        {"id": 9, "t": 712, "title": "Motion", "sub": True},
        {"id": 3, "t": 714, "title": "3.A. Hold a public hearing", "sub": True},
    ]


def test_city_paging_stops_at_meetings_older_than_the_site_keeps(monkeypatch):
    from datetime import date, timedelta

    from scrapers.sources import spearfish_city

    today = date(2026, 11, 4)
    monkeypatch.setattr(spearfish_city.dates, "today", lambda: today)

    def event(i, days_ago):
        return {"id": i, "eventName": "City Council", "startDateTime": f"{today - timedelta(days=days_ago)}T18:00:00Z",
                "hasMedia": False, "publishedFiles": [{"fileId": i, "type": "Agenda", "name": "Agenda"}]}  # fmt: skip

    pages = {0: [event(i, i * 5) for i in range(15)], 15: [event(100 + i, 200 + i) for i in range(15)],
             30: [event(200 + i, 400 + i) for i in range(15)]}  # fmt: skip
    asked = []

    class Resp:
        def __init__(self, body):
            self.body = body

        def raise_for_status(self):
            pass

        def json(self):
            return self.body

    def fake_get(url, params=None, **kw):
        asked.append(params["$skip"])
        return Resp({"value": pages.get(params["$skip"], [])})

    monkeypatch.setattr(spearfish_city.net, "get", fake_get)
    scraper = spearfish_city.SpearfishCity()
    monkeypatch.setattr(scraper, "load_existing", lambda: [])
    records = scraper.scrape()
    assert asked == [0, 15]  # the second page is all older than the window: no third page
    assert {r["event_id"] for r in records} == set(range(15))


def test_a_zoom_link_is_a_way_to_join_not_a_recording():
    from scrapers.sources.spearfish_city import SpearfishCity

    event = {"id": 3407, "eventName": "Art in Public Places Advisory Board Meeting",
             "startDateTime": "2026-11-04T16:00:00Z", "hasMedia": True, "mediaStreamPath": "",
             "mediaSourcePathMp4": "", "externalMediaUrl": "https://us02web.zoom.us/j/83682178231",
             "publishedFiles": [{"fileId": 1, "type": "Agenda", "name": "Agenda"}]}  # fmt: skip
    rec = SpearfishCity()._event_to_records(event)[0]
    assert rec["join_url"] == "https://us02web.zoom.us/j/83682178231"
    assert rec["media_url"] == "" and rec["media_page"] == "" and rec["chapters"] == []


def test_start_time_from_an_agendas_first_page():
    from scrapers.utils import agenda_start_time

    assert agenda_start_time("REGULAR MEETING AGENDA | Tuesday, October 13, 2026 @ 5:30 PM District Office") == "17:30"
    assert agenda_start_time("November 5, 2026 @ 1:30 p.m.\nPlanning & Zoning Regular Meeting Agenda") == "13:30"
    assert (
        agenda_start_time("LAWRENCE COUNTY SEARCH & RESCUE\n11276 Black Forest Rd.\n7:00 PM November 2, 2026")
        == "19:00"
    )
    assert agenda_start_time("Proposed agendas ... 9:00 AM") == "09:00"
    assert agenda_start_time("Wednesday @ 12 PM") == "12:00" and agenda_start_time("12:15 a.m.") == "00:15"
    assert agenda_start_time("No time on this page") == ""


def test_county_agenda_file_and_details_only_for_upcoming_meetings(monkeypatch):
    from datetime import date

    from scrapers.sources import lawrence_county

    rec = {"url": "https://www.lawrence.sd.us/AgendaCenter/PreviousVersions/1361", "meeting_date": "November 5, 2026"}
    assert (
        lawrence_county.agenda_pdf_url(rec) == "https://www.lawrence.sd.us/AgendaCenter/ViewFile/Agenda/_11052026-1361"
    )

    monkeypatch.setattr(lawrence_county.dates, "today", lambda: date(2026, 11, 4))
    read = []
    found = {"start_time": "13:30", "join_url": "https://meet.goto.com/lawrencecountypz"}
    monkeypatch.setattr(lawrence_county, "agenda_details", lambda url: read.append(url) or found)
    old = {"url": "https://x/PreviousVersions/1300", "meeting_date": "October 1, 2026"}
    saved = {"url": "https://x/PreviousVersions/1362", "meeting_date": "November 9, 2026"}
    records = [dict(rec), old, saved]
    lawrence_county.add_agenda_details(records, {saved["url"]: {"start_time": "09:00", "join_url": ""}})
    assert (records[0]["start_time"], records[0]["join_url"]) == ("13:30", "https://meet.goto.com/lawrencecountypz")
    assert "start_time" not in records[1] and records[2]["start_time"] == "09:00"
    assert len(read) == 1  # the new upcoming one only: past meetings skipped, saved details reused


def test_join_link_from_an_agenda():
    from scrapers.utils import agenda_join_url

    text = "Join the meeting from your computer, tablet or Smartphone: https://meet.goto.com/lawrencecountypz\nDial in"
    assert agenda_join_url(text) == "https://meet.goto.com/lawrencecountypz"
    assert agenda_join_url("Zoom: https://us02web.zoom.us/j/83682178231.") == "https://us02web.zoom.us/j/83682178231"
    assert agenda_join_url("Website: www.lawrence.sd.us") == ""


def test_dial_in_from_an_agenda():
    from scrapers.utils import agenda_dial_in

    text = "Join: https://meet.goto.com/lawrencecountypz\nDial in Option: 1-646-749-3122 with Access Code 973-687-509\n"
    assert agenda_dial_in(text) == {"phone": "1-646-749-3122", "code": "973-687-509"}
    assert agenda_dial_in("Call (605) 555-0100 for accommodations") == {"phone": "(605) 555-0100", "code": ""}
    assert agenda_dial_in("No phone here") == {}


def test_city_times_are_spearfish_clock_times():
    from scrapers.sources.spearfish_city import local_time

    # the city's 4:15 PM special session, as its calendar gives it
    assert local_time("2026-10-14T16:15:00Z") == "2026-10-14T16:15:00-06:00"  # daylight time
    assert local_time("2026-11-04T16:00:00Z") == "2026-11-04T16:00:00-07:00"  # standard time
    assert local_time("") == "" and local_time("not a date") == "not a date"

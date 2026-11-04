"""
tests/test_scraper_city_county.py

City and county listings read from pages and APIs rather than their (empty) RSS
feeds: the city's Alert Center, the city job board, the county's job openings
page, and the Matthews Opera House events API.
"""

from __future__ import annotations

from scrapers.sources.lawrence_county_feeds import parse_jobs_page
from scrapers.sources.matthews_opera_house import parse_event
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


def test_matthews_event_from_the_calendar_api():
    event = parse_event(
        {
            "status": "publish",
            "title": "Play Some Petty",
            "url": "https://www.matthewsopera.com/event/play-some-petty-2026/",
            "start_date": "2026-11-06 19:00:00",
            "end_date": "2026-11-06 21:30:00",
            "all_day": False,
            "excerpt": "<p>The Biscuit Lifters play a Tom Petty tribute &amp; more.</p>",
            "description": "<div>a much longer page</div>",
            "image": {"url": "https://www.matthewsopera.com/wp-content/uploads/petty.jpg"},
            "venue": {"venue": "The Matthews Opera House &#8211; Theatre"},
            "cost": "$25 – $40",
        }
    )
    assert event["start_dt"] == "2026-11-06T19:00:00"  # the venue's local clock; the scraper reads it as Mountain
    assert event["end_dt"] == "2026-11-06T21:30:00"
    assert event["description"] == "The Biscuit Lifters play a Tom Petty tribute & more."
    assert event["location"] == "The Matthews Opera House – Theatre"
    assert event["cost"] == "$25 – $40"


def test_matthews_skips_cancelled_and_all_day_events_keep_their_dates():
    assert parse_event({"title": "CANCELLED: Gala", "url": "u", "start_date": "2026-12-01"}) is None
    assert parse_event({"status": "draft", "title": "Gala", "url": "u", "start_date": "2026-12-01"}) is None
    fest = parse_event(
        {"title": "Art Fest", "url": "u", "all_day": True, "start_date": "2026-12-05 00:00:00",
         "end_date": "2026-12-06 23:59:59"}
    )  # fmt: skip
    assert (fest["start_dt"], fest["end_dt"], fest["all_day"]) == ("2026-12-05", "2026-12-06", True)


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

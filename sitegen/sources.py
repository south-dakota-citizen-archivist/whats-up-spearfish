"""
sitegen/sources.py

Everything a reader sees about where information comes from lives here:

- CREDIT: how a source's items are credited around the site ("City of Spearfish"
  rather than "City of Spearfish News Flash"). Applied when the data is loaded.
- DIRECTORY: the plain-language "Where this comes from" page, grouped by topic
  and organization.

Scraper names, slugs and health details are for maintainers and stay out of the
pages. Every enabled scraper must appear in DIRECTORY (tests enforce this).
"""

from __future__ import annotations

from dataclasses import dataclass

CITY = "City of Spearfish"
COUNTY = "Lawrence County"
DISTRICT = "Spearfish School District"
BHSU = "Black Hills State University"
FOREST = "Black Hills National Forest"

CREDIT = {
    "spearfish_calendar": CITY,
    "spearfish_news": CITY,
    "spearfish_blog": CITY,
    "spearfish_alert_center": CITY,
    "spearfish_jobs": CITY,
    "spearfish_city": CITY,
    "public_bids": CITY,
    "building_permits": CITY,
    "planning_commission": CITY,
    "lawrence_county": COUNTY,
    "lawrence_county_news": COUNTY,
    "lawrence_county_jobs": COUNTY,
    "spearfish_schools": DISTRICT,
    "spearfish_school_news": DISTRICT,
    "spearfish_school_board_docs": DISTRICT,
    "spearfish_schools_jobs": DISTRICT,
    "spearfish_sports": "Spearfish High School sports",
    "spearfish_ms_sports": "Spearfish Middle School sports",
    "bhsu_calendar": BHSU,
    "bhsu_jobs": BHSU,
    "bhsu_athletics": "BHSU Yellow Jackets",
    "bhnf": FOREST,
    "bhnf_alerts": FOREST,
    "bhnf_projects": FOREST,
    "spearfish_chamber": "Spearfish Chamber of Commerce",
    "bhpioneer_jobs": "Black Hills Pioneer classifieds",
    "creek_gauge": "U.S. Geological Survey",
    "ebird": "eBird",
    "danr_public_notices": "SD Dept. of Agriculture & Natural Resources",
}


@dataclass(frozen=True)
class Item:
    what: str  # what this site shows from it, in plain words
    slugs: tuple[str, ...] = ()  # scrapers behind it; none = shown live in your browser or a saved copy
    note: str = ""  # replaces the "updated …" line, e.g. for live or saved-copy items
    needs: str = ""  # for a source with several parts: the data key this item depends on


@dataclass(frozen=True)
class Org:
    name: str
    url: str
    items: tuple[Item, ...]


def _i(what: str, *slugs: str, note: str = "", needs: str = "") -> Item:
    return Item(what, slugs, note, needs)


DIRECTORY: list[tuple[str, list[Org]]] = [
    (
        "Local government",
        [
            Org(
                CITY,
                "https://www.spearfish.gov/",
                (
                    _i("Community events calendar", "spearfish_calendar"),
                    _i("News and announcements", "spearfish_news", "spearfish_blog"),
                    _i("Emergency and service alerts", "spearfish_alert_center"),
                    _i("Meeting agendas, minutes and video", "spearfish_city"),
                    _i("Monthly building permit reports", "building_permits"),
                    _i("Planning Commission applications and staff reports", "planning_commission"),
                    _i(
                        "Planning and permit applications, 2012 to July 2026",
                        note="No longer posted online; we kept a copy",
                    ),
                    _i("Bids", "public_bids"),
                    _i("Job openings", "spearfish_jobs"),
                ),
            ),
            Org(
                COUNTY,
                "https://www.lawrence.sd.us/",
                (
                    _i(
                        "Property lines, owners and parcel records",
                        note="Updated from time to time",
                    ),
                    _i("Meeting agendas", "lawrence_county"),
                    _i("News", "lawrence_county_news"),
                    _i("Job openings", "lawrence_county_jobs"),
                ),
            ),
            Org(
                "Public meeting video",
                "https://www.youtube.com/@spearfishschooldistrictliv3794/streams",
                (_i("Recordings of city, county and school board meetings", "public_meetings_youtube"),),
            ),
            Org(
                "SD Dept. of Agriculture & Natural Resources",
                "https://danr.sd.gov/public/default.aspx",
                (_i("Public notices for western South Dakota", "danr_public_notices"),),
            ),
        ],
    ),
    (
        "Schools",
        [
            Org(
                DISTRICT,
                "https://www.spearfish.k12.sd.us/",
                (
                    _i(
                        "Breakfast and lunch menus",
                        "spearfish_elem_breakfast",
                        "spearfish_elem_k2_lunch",
                        "spearfish_elem_35_lunch",
                        "spearfish_mshs_breakfast",
                        "spearfish_ms_lunch",
                        "spearfish_hs_lunch",
                    ),
                    _i("District calendar", "spearfish_schools"),
                    _i("District news", "spearfish_school_news"),
                    _i("School board agendas", "spearfish_school_board_docs"),
                    _i("Job openings", "spearfish_schools_jobs"),
                ),
            ),
            Org(
                "Spartan athletics",
                "https://gobound.com/sd/schools/spearfish",
                (_i("High school and middle school game schedules", "spearfish_sports", "spearfish_ms_sports"),),
            ),
            Org(
                BHSU,
                "https://bhsu.edu/",
                (
                    _i("Campus calendar", "bhsu_calendar"),
                    _i("Yellow Jackets game schedules", "bhsu_athletics"),
                    _i("Job openings", "bhsu_jobs"),
                ),
            ),
        ],
    ),
    (
        "Around town",
        [
            Org(
                "Spearfish Chamber of Commerce",
                "https://www.spearfishchamber.org/",
                (_i("Community events calendar", "spearfish_chamber"),),
            ),
            Org(
                "Matthews Opera House",
                "https://www.matthewsopera.com/",
                (_i("Shows and events", "matthews_opera_house"),),
            ),
            Org(
                "Spearfish Sasquatch", "https://www.spearfishsasquatch.com/", (_i("Home games", "spearfish_sasquatch"),)
            ),
            Org(
                "Grace Balloch Memorial Library",
                "https://spearfish.blackhills.bywatersolutions.com",
                (_i("New books and movies", "spearfish_library"),),
            ),
            Org(
                "Western Hills Humane Society",
                "https://www.westernhillshumanesociety.com/",
                (_i("Pets up for adoption", "whhs_adoptable"),),
            ),
        ],
    ),
    (
        "Outdoors",
        [
            Org(
                "National Weather Service",
                "https://www.weather.gov/unr/",
                (_i("Fire danger", "fire", needs="danger"),),
            ),
            Org(
                "InciWeb",
                "https://inciweb.wildfire.gov/",
                (_i("Active South Dakota wildfires", "fire", needs="incidents"),),
            ),
            Org(
                "U.S. Geological Survey",
                "https://waterdata.usgs.gov/monitoring-location/06431500/",
                (_i("Spearfish Creek water flow", "creek_gauge"),),
            ),
            Org(
                FOREST,
                "https://www.fs.usda.gov/r02/blackhills",
                (
                    _i("Alerts and closures", "bhnf_alerts"),
                    _i("News", "bhnf"),
                    _i("Projects open for public comment", "bhnf_projects"),
                ),
            ),
            Org("eBird", "https://ebird.org/region/US-SD-081", (_i("Bird sightings in Lawrence County", "ebird"),)),
        ],
    ),
    (
        "Food and drink",
        [
            Org("Crow Peak Brewing", "https://crowpeakbrewing.com/", (_i("Tap list", "crow_peak_brewing"),)),
            Org(
                "Spearfish Brewing Company", "https://www.spearfishbrewing.com/", (_i("Tap list", "spearfish_brewing"),)
            ),
            Org("Sawyer Brewing Co.", "https://www.sawyerbrewingco.com/", (_i("Tap list", "sawyer_brewing"),)),
            Org("Killian's", "https://untappd.com", (_i("Tap list", "killians"),)),
            Org("Redwater Kitchen", "https://untappd.com", (_i("Tap list", "redwater_kitchen"),)),
            Org(
                "The Clubhouse",
                "https://clubhouseofspearfish.com/food-and-drink/",
                (_i("Tap list", "clubhouse_spearfish"),),
            ),
            Org(
                "Leone's Creamery", "https://leonescreamery.com/flavors", (_i("Ice cream flavors", "leones_creamery"),)
            ),
        ],
    ),
    (
        "News",
        [
            Org(
                "Black Hills Pioneer",
                "https://www.bhpioneer.com/",
                (_i("Local news", "black_hills_pioneer"), _i("Job listings", "bhpioneer_jobs")),
            ),
            Org("Rapid City Journal", "https://rapidcityjournal.com/", (_i("Regional news", "rapid_city_journal"),)),
            Org("SDPB", "https://www.sdpb.org/news", (_i("Statewide news", "sdpb_news"),)),
            Org(
                "South Dakota Searchlight and SD News Watch",
                "https://southdakotasearchlight.com/",
                (_i("Statewide news", "news_feeds"),),
            ),
            Org("Sundance Times", "https://www.sundancetimes.com", (_i("Northeast Wyoming news", "sundance_times"),)),
            Org(
                "Custer County Chronicle",
                "https://custercountychronicle.com",
                (_i("Southern Hills news", "custer_county_chronicle"),),
            ),
        ],
    ),
]


def directory_slugs() -> set[str]:
    return {s for _, orgs in DIRECTORY for o in orgs for i in o.items for s in i.slugs}

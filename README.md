# What's up, Spearfish?

A static site that collects what's happening in and around Spearfish, S.D. and the
Northern Black Hills — a unified events calendar, school menus, creek flow, bird
sightings, public meetings, permits, tap lists and more — rebuilt several times a
day from public sources.

**Live:** https://south-dakota-citizen-archivist.github.io/whats-up-spearfish/
· **Source health:** [`_health.json` on the data branch](https://github.com/south-dakota-citizen-archivist/whats-up-spearfish/blob/data/_health.json)

## How it works

```
scrapers (GitHub Actions, scheduled)  →  data branch (JSON snapshots)  →  sitegen  →  GitHub Pages
```

- **`scrapers/`** — one class per source in `scrapers/sources/`. The runner
  (`python -m scrapers`) runs them in parallel, normalizes every record
  (`scrapers/schema.py`), and writes `data/<slug>.json` plus `data/_health.json`.
  A source that errors or comes back empty never overwrites its last good data.
- **`data` branch** — scraped data lives on its own branch, so `main` history is
  code only. Files are snapshots: news, documents and events are pruned to a
  rolling window (see `KINDS` in `scrapers/schema.py`), not archived forever.
  Two exceptions are kept in full: building permits from the city's monthly
  reports (2013–), and `archive/` — every planning/permit record collected from
  the city's OpenGov portal (2012–July 2026) before the city turned off public
  access. That archive is rebuilt only by `scripts/build_planning_archive.py`.
  New applications come from Planning Commission agendas instead
  (`planning_commission`, CivicClerk, itemized since August 2025: staff report
  fields, attachments), also kept in full. To re-backfill, set
  `PlanningCommission.since = FIRST_ITEMIZED` for one run.
- **`sitegen/`** — renders `site/templates/` with Jinja into `_site/`: separate
  pages for Today, Events, Schools, Outdoors, On tap, Civic, Permits ("What's
  being built here?" — permits and applications by address, search or your
  location), News, Jobs, Community and Sources, plus `events.json`, `calendar.ics` and `events.xml`.
  Tailwind is compiled with `pytailwindcss`; Alpine.js is vendored in
  `site/static/vendor/`. No Node toolchain.
- **Audience** — the site is written for people who live here, not for
  developers: plain language, no error codes, no source chatter on content pages.
  How sources are named to readers, and the "Where this comes from" page, both
  live in `sitegen/sources.py`. Technical health stays in `_health.json`, the
  workflow run summary and the "Scraper health" issue.
- **Workflows** — `.github/workflows/scrape.yml` runs the daily tier each morning
  and the `frequent` tier (creek gauge, fire, alerts) every three hours, commits
  to the `data` branch, builds and deploys. `ci.yml` lints and tests pull requests.
  Sources failing three runs in a row are listed in a "Scraper health" issue.

## Running locally

```sh
uv sync --group dev
uv run playwright install chromium            # only needed for browser sources

# get the current data (a worktree of the data branch at data/)
git fetch origin data && git worktree add data data

uv run python -m scrapers --list               # registry
uv run python -m scrapers --only creek_gauge   # run some sources
uv run python -m scrapers                      # run everything enabled
uv run python -m sitegen                       # build _site/
python -m http.server -d _site 8000

uv run pytest && uv run ruff check .
```

Set `WUS_DATA_DIR=/some/dir` to scrape into a scratch directory instead of `data/`.
eBird needs `EBIRD_API_KEY` (a repo secret in Actions).

## Adding a source

1. Add a module to `scrapers/sources/` with a `BaseScraper` subclass: set `name`,
   `slug`, `kind` (see `KINDS` in `scrapers/schema.py`), `url`, and implement
   `scrape()` returning a list of dicts with at least `title` and `url` (events
   also need `start_dt`). Use `scrapers.net.get()` for HTTP.
2. Set `replace = True` if each scrape is the complete current state (tap lists,
   job boards); leave it `False` for feeds that only show the latest items.
3. Set `naive_tz = dates.MT` if the source's timestamps are local time without an
   offset (the default assumes UTC), `min_records = 0` if it can legitimately be
   empty, and `category` for events (`community`, `arts`, `sports`, …).
4. Run it with `uv run python -m scrapers --only <slug>` and check the output.
5. Show it on a page in `sitegen/pages.py` + `site/templates/pages/`.
6. Add it to `DIRECTORY` in `sitegen/sources.py` (what readers get from it, in
   plain words) and, if its name isn't how locals know it, to `CREDIT`. A test
   fails if an enabled source is missing from the directory.

Set `enabled = False` to put a source on ice without deleting it.

## Sources

<!-- sources:start -->
| Source | Slug | Kind | Notes |
|---|---|---|---|
| [Western Hills Humane Society](https://www.westernhillshumanesociety.com/) | `whhs_adoptable` | adoptable | full snapshot |
| [BHNF Alerts](https://www.fs.usda.gov/r02/blackhills/alerts) | `bhnf_alerts` | alert | frequent tier, full snapshot |
| [City of Spearfish Alert Center](https://www.spearfish.gov/AlertCenter.aspx) | `spearfish_alert_center` | alert | frequent tier |
| [Crow Peak Brewing](https://crowpeakbrewing.com/) | `crow_peak_brewing` | beer | full snapshot |
| [Killian's](https://untappd.com) | `killians` | beer | full snapshot |
| [Redwater Kitchen](https://untappd.com) | `redwater_kitchen` | beer | full snapshot |
| [Sawyer Brewing Co.](https://www.sawyerbrewingco.com/menu) | `sawyer_brewing` | beer | full snapshot |
| [Spearfish Brewing Company](https://www.spearfishbrewing.com/beers/) | `spearfish_brewing` | beer | full snapshot |
| [Public Bids](https://www.spearfish.gov/Bids.aspx) | `public_bids` | bid | full snapshot |
| [Spearfish building permit reports](https://www.cityofspearfish.com/Archive.aspx?AMID=37) | `building_permits` | building_permit |  |
| [City of Spearfish](https://spearfishsd.portal.civicclerk.com/) | `spearfish_city` | document |  |
| [Lawrence County Agenda Center](https://www.lawrence.sd.us/AgendaCenter) | `lawrence_county` | document |  |
| [Spearfish School Board](https://www.spearfish.k12.sd.us/documents/board-of-education/board-meeting-agendas/25745609) | `spearfish_school_board_docs` | document |  |
| [BHSU Athletics](https://bhsuathletics.com/calendar) | `bhsu_athletics` | event |  |
| [BHSU Campus Calendar](https://bhsu.edu/campus-calendar.html) | `bhsu_calendar` | event |  |
| [City of Spearfish Calendar](https://www.spearfish.gov/Calendar.aspx) | `spearfish_calendar` | event |  |
| [Matthews Opera House](https://www.matthewsopera.com/events/) | `matthews_opera_house` | event |  |
| [Spearfish Chamber](https://business.spearfishchamber.org/events/calendar/) | `spearfish_chamber` | event |  |
| [Spearfish HS Sports](https://gobound.com/sd/schools/spearfish) | `spearfish_sports` | event |  |
| [Spearfish MS Sports](https://gobound.com/sd/schools/spearfishmiddleschool) | `spearfish_ms_sports` | event |  |
| [Spearfish Sasquatch](https://www.spearfishsasquatch.com) | `spearfish_sasquatch` | event |  |
| [Spearfish School District](https://www.spearfish.k12.sd.us/events) | `spearfish_schools` | event |  |
| [Fire danger & wildfires](https://www.weather.gov/unr/) | `fire` | fire | frequent tier |
| [Leone's Creamery](https://leonescreamery.com/flavors) | `leones_creamery` | flavor | full snapshot |
| [Spearfish Creek gauge (USGS)](https://waterdata.usgs.gov/monitoring-location/06431500/) | `creek_gauge` | gauge | frequent tier |
| [BHSU](https://yourfuture.sdbor.edu/) | `bhsu_jobs` | job | full snapshot |
| [Black Hills Pioneer](https://www.bhpioneer.com/classifieds/job/) | `bhpioneer_jobs` | job | full snapshot |
| [City of Spearfish Jobs](https://www.spearfish.gov/Jobs.aspx) | `spearfish_jobs` | job | full snapshot |
| [Lawrence County Jobs](https://www.lawrence.sd.us/Jobs.aspx) | `lawrence_county_jobs` | job | full snapshot |
| [Spearfish School District](https://www.applitrack.com/bhssc/onlineapp/default.aspx) | `spearfish_schools_jobs` | job | full snapshot |
| [Grace Balloch Memorial Library](https://spearfish.blackhills.bywatersolutions.com) | `spearfish_library` | library_book | needs browser, full snapshot |
| [Black Hills Pioneer](https://www.bhpioneer.com/) | `black_hills_pioneer` | news |  |
| [Custer County Chronicle](https://custercountychronicle.com) | `custer_county_chronicle` | news |  |
| [Rapid City Journal](https://rapidcityjournal.com/) | `rapid_city_journal` | news |  |
| [Regional News](https://www.sdnewswatch.org/) | `news_feeds` | news |  |
| [SDPB](https://www.sdpb.org/news) | `sdpb_news` | news | needs browser |
| [Sundance Times](https://www.sundancetimes.com) | `sundance_times` | news |  |
| [SD DANR public notices (West River)](https://danr.sd.gov/public/default.aspx) | `danr_public_notices` | notice | full snapshot |
| [Spearfish Planning Commission applications](https://spearfishsd.portal.civicclerk.com/) | `planning_commission` | planning_item |  |
| [Black Hills National Forest](https://www.fs.usda.gov/r02/blackhills/newsroom/releases) | `bhnf` | press_release |  |
| [City of Spearfish Blog](https://www.spearfish.gov/Blog.aspx) | `spearfish_blog` | press_release |  |
| [City of Spearfish News Flash](https://www.spearfish.gov/CivicAlerts.aspx) | `spearfish_news` | press_release |  |
| [Lawrence County News Flash](https://www.lawrence.sd.us/CivicAlerts.aspx) | `lawrence_county_news` | press_release |  |
| [Spearfish School District](https://www.spearfish.k12.sd.us/news) | `spearfish_school_news` | press_release | full snapshot |
| [Black Hills National Forest projects](https://www.fs.usda.gov/r02/blackhills/projects) | `bhnf_projects` | project | full snapshot |
| [Elementary 3-5 Lunch](https://menus.healthepro.com/organizations/524/sites/4523/menus/124131) | `spearfish_elem_35_lunch` | school_menu |  |
| [Elementary Breakfast](https://menus.healthepro.com/organizations/524/sites/4519/menus/124134) | `spearfish_elem_breakfast` | school_menu |  |
| [Elementary K-2 Lunch](https://menus.healthepro.com/organizations/524/sites/4523/menus/124132) | `spearfish_elem_k2_lunch` | school_menu |  |
| [High School Lunch](https://menus.healthepro.com/organizations/524/sites/4520/menus/124137) | `spearfish_hs_lunch` | school_menu |  |
| [Middle School Lunch](https://menus.healthepro.com/organizations/524/sites/4521/menus/124136) | `spearfish_ms_lunch` | school_menu |  |
| [MS/HS Breakfast](https://menus.healthepro.com/organizations/524/sites/4520/menus/124135) | `spearfish_mshs_breakfast` | school_menu |  |
| [eBird recent sightings](https://ebird.org/region/US-SD-081) | `ebird` | sighting | full snapshot |
| [Public Meetings (YouTube)](https://www.youtube.com/@spearfishschooldistrictliv3794/streams) | `public_meetings_youtube` | youtube_video |  |
| [The Clubhouse](https://untappd.com/v/the-clubhouse-of-spearfish/9898973) | `clubhouse_spearfish` | beer | 🧊 on ice, full snapshot |
| SD DANR contested cases | `danr_contested_cases` | notice | 🧊 on ice |
| SD DANR spill reports | `danr_spills` | notice | 🧊 on ice |
| [Spearfish planning & permits (OpenGov)](https://spearfishsd.portal.opengov.com/) | `planning_zoning` | permit | 🧊 on ice, full snapshot |
| Native plant spotlight | `native_plants_spotlight` | plant | 🧊 on ice |
| Wildlife carcass pickups (SD DOT) | `roadkill` | sighting | 🧊 on ice |
| Library circulation stats | `library_circulation` | stats | 🧊 on ice |
<!-- sources:end -->

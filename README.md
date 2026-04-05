# What's up, Spearfish?

A static website that aggregates events, public documents, beers on tap, and other
things happening in Spearfish, SD. It runs as a static site, rebuilt a few times a
day from scrapers that collect public data across the web.

Source code: [https://github.com/south-dakota-citizen-archivist/whats-up-spearfish](https://github.com/south-dakota-citizen-archivist/whats-up-spearfish)

_Updated: April 4, 2026_

---

## Data sources

| Source | Slug | Record types | Count |
|---|---|---|---:|
| Bhca Calendar | `bhca_calendar` | `event` | 70 |
| BHNF Alerts | `bhnf_alerts` | `alert` | 24 |
| BHSU | `bhsu_jobs` | `job` | 11 |
| BHSU Athletics | `bhsu_athletics` | `event` | 86 |
| BHSU Campus Calendar | `bhsu_calendar` | `event` | 48 |
| Black Hills National Forest | `bhnf` | `event`, `press_release` | 5 |
| Black Hills National Forest (public projects) | `bhnf_projects` | — | 48 |
| Black Hills Pioneer | `bhpioneer_jobs` | `job` | 12 |
| Black Hills Pioneer | `black_hills_pioneer` | `news` | 132 |
| Black Hills Wildflowers | `black_hills_wildflowers` | — | 5 |
| City of Spearfish | `spearfish_city` | `document` | 2,093 |
| City of Spearfish Alert Center | `spearfish_alert_center` | `alert` | 3 |
| City of Spearfish Blog | `spearfish_blog` | — | 0 |
| City of Spearfish Calendar | `spearfish_calendar` | `event` | 33 |
| City of Spearfish Jobs | `spearfish_jobs` | — | 0 |
| City of Spearfish News Flash | `spearfish_news` | `press_release` | 4 |
| Crow Peak Brewing | `crow_peak_brewing` | `beer` | 16 |
| eBird (recent sightings) | `ebird` | — | 50 |
| Elementary 3-5 Lunch | `spearfish_elem_35_lunch` | `school_menu` | 40 |
| Elementary Breakfast | `spearfish_elem_breakfast` | `school_menu` | 40 |
| Elementary K-2 Lunch | `spearfish_elem_k2_lunch` | `school_menu` | 40 |
| Grace Balloch Memorial Library | `spearfish_library` | — | 0 |
| Grace Balloch Memorial Library (circulation) | `library_circulation` | — | 124 |
| High School Lunch | `spearfish_hs_lunch` | `school_menu` | 40 |
| Inaturalist Plant Cache | `inaturalist_plant_cache` | — | 317 |
| Killian's | `killians` | `beer` | 17 |
| Lawrence County | `lawrence_county` | `document` | 46 |
| Lawrence County Jobs | `lawrence_county_jobs` | — | 0 |
| Lawrence County News Flash | `lawrence_county_news` | — | 0 |
| Leone's Creamery | `leones_creamery` | `flavor` | 8 |
| Matthews Opera House | `matthews_opera_house` | `event` | 27 |
| Middle School Lunch | `spearfish_ms_lunch` | `school_menu` | 40 |
| MS/HS Breakfast | `spearfish_mshs_breakfast` | `school_menu` | 40 |
| Public Bids | `public_bids` | `bid` | 2 |
| Public Meetings (YouTube) | `public_meetings_youtube` | `youtube_video` | 30 |
| Rapid City Journal | `rapid_city_journal` | `news` | 141 |
| Redwater Kitchen | `redwater_kitchen` | `beer` | 12 |
| Regional News | `news_feeds` | `news` | 128 |
| Sawyer Brewing Co. | `sawyer_brewing` | `beer` | 17 |
| SD Dept. of Agriculture & Natural Resources (contested cases) | `danr_contested_cases` | — | 10 |
| SD Dept. of Agriculture & Natural Resources (public notices) | `danr_public_notices` | — | 8 |
| Sd Flowering Plants | `sd_flowering_plants` | — | 5 |
| Sd Living Landscapes | `sd_living_landscapes` | — | 5 |
| SDPB | `sdpb_news` | `news` | 10 |
| Spearfish Agenda Center | `spearfish_agenda_center` | — | 0 |
| Spearfish Brewing Company | `spearfish_brewing` | `beer` | 14 |
| Spearfish Chamber | `spearfish_chamber` | `event` | 91 |
| Spearfish HS Sports | `spearfish_sports` | `event` | 1,281 |
| Spearfish MS Sports | `spearfish_ms_sports` | `event` | 187 |
| Spearfish Sasquatch | `spearfish_sasquatch` | `event` | 32 |
| Spearfish School Board | `spearfish_school_board_docs` | `document` | 115 |
| Spearfish School District | `spearfish_school_news` | `press_release` | 3 |
| Spearfish School District | `spearfish_schools` | `event` | 20 |
| Spearfish School District | `spearfish_schools_jobs` | `job` | 9 |
| The Clubhouse | `clubhouse_spearfish` | `beer` | 8 |
| USDA PLANTS Database (Black Hills full pull) | `plants_native_black_hills` | — | 24,984 |
| USDA PLANTS Database (Native Plant Spotlight) | `native_plants_spotlight` | — | 317 |
| USGS Stream Gauge — Spearfish Creek (06431500) | `creek_gauge` | — | 4 |
| Western Hills Humane Society | `whhs_adoptable` | `adoptable` | 35 |

---

## Adding a new scraper

1. Create a new Python module inside `scrapers/sources/`, e.g.
   `scrapers/sources/city_council.py`.

2. Subclass `BaseScraper` and implement `scrape()`:

   ```python
   from scrapers.base import BaseScraper

   class CityCouncilScraper(BaseScraper):
       name = "City Council Meetings"
       slug = "city_council"

       def scrape(self) -> list[dict]:
           # fetch + parse remote data, return list of dicts
           return []
   ```

3. That's it — `uv run python -m scrapers` will discover and run it automatically.

**Common record fields:**

| Field | Description |
|---|---|
| `title` | Display title (required) |
| `url` | Link to the original source page |
| `record_type` | Controls which widget the record appears in |
| `start_dt` | ISO date/datetime string — marks the record as an event |
| `end_dt` | ISO date/datetime — optional event end time |
| `date` | Fallback date for documents/news |
| `location` | Human-readable location string |
| `description` | Free-text body |
| `doc_type` | Document category badge (e.g. `"Agenda"`, `"Permit"`) |

---

## How to run locally

```bash
# 1. Clone the repo
git clone https://github.com/south-dakota-citizen-archivist/whats-up-spearfish.git
cd whats-up-in-spearfish

# 2. Install dependencies (uv creates .venv automatically)
uv sync

# 3. Run scrapers (populates data/*.json)
uv run python -m scrapers

# 4. Build the site (outputs to _site/)
uv run python build.py

# 5. Preview locally
uv run python -m http.server 8000 --directory _site
# Open http://localhost:8000
```

---

## GitHub Actions setup

The workflow runs scrapers + build automatically. If you want Slack notifications,
add these secrets under **Settings → Secrets and variables → Actions**:

| Secret | Description |
|---|---|
| `SLACK_BOT_TOKEN` | Slack bot token (starts with `xoxb-`) |
| `SLACK_CHANNEL_ID` | Channel ID to post scrape summaries to |

Both are optional — the pipeline runs fine without them.

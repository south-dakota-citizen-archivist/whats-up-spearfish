# What's up in Spearfish?

_Built with Claude_

A static website that aggregates events, public documents, beers on tap and other things happening in Spearfish, SD.

---

## Adding a new scraper

1. Create a new Python module inside `scrapers/sources/`, e.g.
   `scrapers/sources/city_council.py`.

2. Subclass `BaseScraper` and implement `scrape()`:

   ```python
   from scrapers.base import BaseScraper
   from scrapers.utils import fetch_html, parse_date, make_slug

   class CityCouncilScraper(BaseScraper):
       name = "City Council Meetings"
       slug = "city-council"

       def scrape(self) -> list[dict]:
           soup = fetch_html("https://example.gov/council/meetings")
           records = []
           for row in soup.select("table.meetings tbody tr"):
               cells = row.find_all("td")
               if len(cells) < 3:
                   continue
               title = cells[0].get_text(strip=True)
               url = cells[0].find("a", href=True)
               records.append({
                   "title": title,
                   "url": url["href"] if url else "",
                   "start_dt": parse_date(cells[1].get_text(strip=True)),
                   "location": cells[2].get_text(strip=True),
                   "slug": make_slug(title),
                   "record_type": "event",
               })
           return records
   ```

3. That's it. `python -m scrapers` will discover and run it automatically.

**Record fields recognised by the site builder:**

| Field | Description |
|---|---|
| `title` | Display title (required) |
| `url` | Link to the original source page |
| `slug` | URL-safe identifier (auto-generated from title if absent) |
| `record_type` | `"event"` or `"document"` — controls which list the record appears in |
| `start_dt` | ISO date/datetime string — marks the record as an event |
| `end_dt` | ISO date/datetime — optional event end time |
| `date` | Fallback date field for documents |
| `location` | Human-readable location string |
| `lat` / `lon` | Decimal coordinates — enables map pin |
| `description` | Free-text body |
| `doc_type` | Document category badge (e.g. "Agenda", "Permit") |

---

## How to run locally

```bash
# 1. Clone the repo
git clone https://github.com/your-org/spearfish-bulletin.git
cd spearfish-bulletin

# 2. Install dependencies (uv creates .venv automatically)
uv sync

# 3. Copy env template (optional — only needed for Slack alerts)
cp .env.example .env
# Edit .env with your Slack credentials

# 4. Run scrapers (populates data/*.json)
uv run python -m scrapers

# 5. Build the site (outputs to _site/)
uv run python build.py

# 6. Generate calendar + RSS feeds
uv run python calendar_feed.py

# 7. Preview locally
uv run python -m http.server 8000 --directory _site
# Open http://localhost:8000
```

---

## GitHub Actions setup

### Secrets required

Go to **Settings → Secrets and variables → Actions** in your repository and add:

| Secret | Description |
|---|---|
| `SLACK_BOT_TOKEN` | Slack bot token (starts with `xoxb-`) |
| `SLACK_CHANNEL_ID` | Channel ID to post scrape summaries to |

Both secrets are optional — the pipeline runs fine without them; Slack alerts are simply skipped.

"""
scripts/build_readme.py

Regenerates README.md with an updated date and a data-sources table.
Run directly (uv run python scripts/build_readme.py) or via pre-commit hook.
"""

from __future__ import annotations

import importlib
import inspect
import json
import pkgutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# Ensure the repo root (parent of this script's directory) is on sys.path so
# that the local `scrapers` package is importable regardless of cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import scrapers.sources  # noqa: E402 — must come after sys.path fix
from scrapers.base import BaseScraper  # noqa: E402

REPO_ROOT = _REPO_ROOT
DATA_DIR = REPO_ROOT / "data"
README = REPO_ROOT / "README.md"

GITHUB_URL = "https://github.com/south-dakota-citizen-archivist/whats-up-in-spearfish"

# ---------------------------------------------------------------------------
# Scraper discovery: slug → human name
# ---------------------------------------------------------------------------

def _discover_scrapers() -> dict[str, str]:
    """Walk scrapers.sources and return {slug: name} for every BaseScraper subclass."""
    slug_to_name: dict[str, str] = {}
    for finder, module_name, _ in pkgutil.walk_packages(
        scrapers.sources.__path__, prefix="scrapers.sources."
    ):
        try:
            mod = importlib.import_module(module_name)
        except Exception:
            continue
        for _, obj in inspect.getmembers(mod, inspect.isclass):
            if (
                issubclass(obj, BaseScraper)
                and obj is not BaseScraper
                and hasattr(obj, "slug")
                and hasattr(obj, "name")
            ):
                slug_to_name[obj.slug] = obj.name
    return slug_to_name


# ---------------------------------------------------------------------------
# Data file stats: slug → {count, record_types}
# ---------------------------------------------------------------------------

def _data_stats() -> dict[str, dict]:
    stats: dict[str, dict] = {}
    for path in DATA_DIR.glob("*.json"):
        slug = path.stem
        try:
            records: list[dict] = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            records = []
        types = sorted({r.get("record_type", "") for r in records if isinstance(r, dict)} - {""})
        stats[slug] = {"count": len(records), "types": types}
    return stats


# ---------------------------------------------------------------------------
# README template
# ---------------------------------------------------------------------------

def _build_readme(slug_to_name: dict[str, str], stats: dict[str, dict]) -> str:
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%B %-d, %Y")

    # Build rows: include every slug that has a name OR has data
    all_slugs = sorted(set(slug_to_name) | set(stats))
    rows: list[tuple[str, str, str, int]] = []
    for slug in all_slugs:
        s = stats.get(slug, {})
        count = s.get("count", 0)
        types = s.get("types", [])
        name = slug_to_name.get(slug, slug.replace("_", " ").title())
        type_str = ", ".join(f"`{t}`" for t in types) if types else "—"
        rows.append((name, slug, type_str, count))

    # Sort by name
    rows.sort(key=lambda r: r[0].lower())

    # Build markdown table
    header = "| Source | Slug | Record types | Count |"
    sep    = "|---|---|---|---:|"
    table_lines = [header, sep]
    for name, slug, type_str, count in rows:
        table_lines.append(f"| {name} | `{slug}` | {type_str} | {count:,} |")
    table = "\n".join(table_lines)

    return f"""\
# What's up in Spearfish?

A static website that aggregates events, public documents, beers on tap, and other
things happening in Spearfish, SD. It runs as a static site, rebuilt a few times a
day from scrapers that collect public data across the web.

Source code: [{GITHUB_URL}]({GITHUB_URL})

_Last updated: {date_str}_

---

## Data sources

{table}

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
git clone {GITHUB_URL}.git
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
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    slug_to_name = _discover_scrapers()
    stats = _data_stats()
    content = _build_readme(slug_to_name, stats)
    README.write_text(content, encoding="utf-8")
    print(f"README.md written ({len(content):,} bytes, {content.count(chr(10))} lines)")


if __name__ == "__main__":
    main()

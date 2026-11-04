"""
scripts/rebuild_building_permits.py

Re-reads every archived monthly permit report (DATA_DIR/permit_reports/*.pdf)
and replaces building_permits.json with the result. The regular scrape only
re-reads the newest few months, so run this after a change to the parser
(scrapers/permit_reports.py) to carry the fix back through 2013. First-seen
dates are kept for permits already on file.

    WUS_DATA_DIR=../whats-up-data uv run python -m scripts.rebuild_building_permits
"""

from __future__ import annotations

import sys

from scrapers.sources import building_permits as bp


def main() -> int:
    if not bp.reports_dir().exists():
        print(f"no permit reports in {bp.reports_dir()}", file=sys.stderr)
        return 1
    bp.RECENT_MONTHS = 10_000  # every report on the city's list
    scraper = bp.BuildingPermits()
    scraper.replace = True  # drop records the parser no longer produces
    result = scraper.run()
    print(f"{result.count} permits from every report ({result.new} not on file before)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

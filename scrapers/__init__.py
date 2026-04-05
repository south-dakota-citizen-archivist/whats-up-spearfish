"""
scrapers/__init__.py

Entry point for running all scrapers. Discovers BaseScraper subclasses in
scrapers/sources/, runs each one in parallel, and sends a Slack summary if new records
were found.

Usage:
    python -m scrapers
"""

import importlib
import inspect
import pkgutil
from concurrent.futures import ThreadPoolExecutor, as_completed

from dotenv import load_dotenv

from scrapers.base import BaseScraper
from scrapers.slack import send_alert

load_dotenv()


def _discover_scrapers():
    """Import every module under scrapers/sources/ and return all
    concrete BaseScraper subclasses found."""
    import scrapers.sources as sources_pkg

    subclasses = []
    pkg_path = sources_pkg.__path__
    pkg_name = sources_pkg.__name__

    for finder, module_name, is_pkg in pkgutil.walk_packages(pkg_path, prefix=pkg_name + "."):
        module = importlib.import_module(module_name)
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseScraper)
                and obj is not BaseScraper
                and obj.__module__ == module.__name__
                and obj.__dict__.get("name")  # skip abstract intermediary bases
            ):
                subclasses.append(obj)

    return subclasses


def run_all():
    """Instantiate and run every discovered scraper in parallel, then alert on new records."""
    scraper_classes = _discover_scrapers()

    if not scraper_classes:
        print("No scrapers found in scrapers/sources/. Nothing to do.")
        return

    total_new = 0
    summary_lines = []
    max_workers = min(len(scraper_classes), 6)  # Cap at 6 parallel threads

    def _run_scraper(cls):
        """Run a single scraper and return (name, count, error)."""
        scraper = cls()
        try:
            new_records = scraper.run()
            count = len(new_records)
            return (scraper.name, count, None)
        except Exception as exc:
            return (scraper.name, 0, exc)

    print(f"Running {len(scraper_classes)} scraper(s) in parallel (max_workers={max_workers})...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_run_scraper, cls): cls.__name__ for cls in scraper_classes}

        for future in as_completed(futures):
            name, count, error = future.result()
            total_new += count

            if error:
                msg = f"{name}: ERROR - {error}"
                print(f"  {msg}")
                summary_lines.append(msg)
            else:
                status = f"{name}: {count} new record(s)"
                print(f"  {status}")
                summary_lines.append(status)

    print(f"\nDone. {total_new} total new record(s) across {len(scraper_classes)} scraper(s).")

    if total_new > 0:
        alert_text = ":newspaper: *Spearfish Bulletin* — scrape complete.\n" + "\n".join(
            f"• {line}" for line in summary_lines
        )
        send_alert(alert_text)


if __name__ == "__main__":
    run_all()

"""
scrapers/runner.py

Discovers sources, runs them in parallel with per-source isolation, and
records the outcome of every run in ``{DATA_DIR}/_health.json``:

    {
      "updated": "...",
      "sources": {
        "<slug>": {
          "name", "kind", "url", "tier", "enabled",
          "status": "ok" | "empty" | "error" | "disabled",
          "last_run", "last_success", "count", "new", "dropped",
          "error", "failures"            # consecutive failed runs
        }
      }
    }

A failing source never touches its data file, so the site keeps showing the
last good data while the status page flags it.
"""

from __future__ import annotations

import argparse
import importlib
import inspect
import json
import os
import pkgutil
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout

from dotenv import load_dotenv

from scrapers import base, dates
from scrapers.base import BaseScraper, ScrapeEmpty

SOURCE_TIMEOUT = 600  # seconds per source


def discover() -> list[type[BaseScraper]]:
    """Every concrete BaseScraper subclass under scrapers/sources/, sorted by slug."""
    import scrapers.sources as pkg

    found: dict[str, type[BaseScraper]] = {}
    for info in pkgutil.walk_packages(pkg.__path__, prefix=pkg.__name__ + "."):
        module = importlib.import_module(info.name)
        for _name, obj in inspect.getmembers(module, inspect.isclass):
            if (
                issubclass(obj, BaseScraper)
                and obj.__module__ == module.__name__
                and not inspect.isabstract(obj)
                and obj.__dict__.get("slug")
            ):
                if obj.slug in found:
                    raise RuntimeError(f"duplicate source slug {obj.slug!r}")
                found[obj.slug] = obj
    return [found[k] for k in sorted(found)]


def health_file():
    return base.DATA_DIR / "_health.json"


def load_health() -> dict:
    try:
        return json.loads(health_file().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"sources": {}}


def save_health(health: dict) -> None:
    health["updated"] = dates.now().isoformat(timespec="seconds")
    health_file().parent.mkdir(parents=True, exist_ok=True)
    health_file().write_text(json.dumps(health, indent=1, sort_keys=True), encoding="utf-8")


def _run_one(cls: type[BaseScraper]) -> dict:
    started = time.monotonic()
    try:
        result = cls().run()
        return {"status": "ok", "count": result.count, "new": result.new, "dropped": result.dropped}
    except ScrapeEmpty as exc:
        return {"status": "empty", "error": str(exc)}
    except Exception as exc:  # noqa: BLE001 — isolate every source
        tb = traceback.format_exc(limit=4)
        print(f"[{cls.slug}] ERROR {exc!r}\n{tb}", file=sys.stderr)
        return {"status": "error", "error": f"{type(exc).__name__}: {exc}"[:500]}
    finally:
        print(f"[{cls.slug}] finished in {time.monotonic() - started:.1f}s")


def select(classes, *, tier: str | None, only: list[str] | None, browser: bool | None):
    out = []
    for cls in classes:
        if only:
            if cls.slug in only:
                out.append(cls)
            continue
        if tier and cls.tier != tier:
            continue
        if browser is not None and cls.browser != browser:
            continue
        out.append(cls)
    return out


def run(*, tier: str | None = None, only: list[str] | None = None, browser: bool | None = None, workers: int = 6):
    load_dotenv()
    classes = discover()
    health = load_health()
    sources = health.setdefault("sources", {})
    now = dates.now().isoformat(timespec="seconds")

    # Registry metadata for every source, including ones not run this time.
    for cls in classes:
        entry = sources.setdefault(cls.slug, {})
        entry.update(
            name=cls.name,
            kind=cls.kind,
            url=cls.url,
            tier=cls.tier,
            enabled=cls.enabled,
            max_stale_hours=cls.max_stale_hours,
        )
        if not cls.enabled:
            entry["status"] = "disabled"
    known = {cls.slug for cls in classes}
    for slug in list(sources):
        if slug not in known:
            del sources[slug]

    todo = [c for c in select(classes, tier=tier, only=only, browser=browser) if c.enabled or only]
    print(f"Running {len(todo)} source(s): {', '.join(c.slug for c in todo)}")

    pool = ThreadPoolExecutor(max_workers=workers)
    futures = {cls: pool.submit(_run_one, cls) for cls in todo}
    for cls, fut in futures.items():
        try:
            outcome = fut.result(timeout=SOURCE_TIMEOUT)
        except FutureTimeout:
            outcome = {"status": "error", "error": f"timed out after {SOURCE_TIMEOUT}s"}
        entry = sources[cls.slug]
        entry["last_run"] = now
        entry["status"] = outcome["status"]
        if outcome["status"] == "ok":
            entry.update(last_success=now, failures=0, error="", **{k: outcome[k] for k in ("count", "new", "dropped")})
        else:
            entry["failures"] = entry.get("failures", 0) + 1
            entry["error"] = outcome.get("error", "")
    pool.shutdown(wait=False, cancel_futures=True)

    save_health(health)
    write_summary(health, [c.slug for c in todo])
    return health


def write_summary(health: dict, ran: list[str]) -> None:
    rows = []
    icons = {"ok": "✅", "empty": "⚠️", "error": "❌", "disabled": "🧊"}
    for slug in ran:
        e = health["sources"][slug]
        detail = e.get("error") or f"{e.get('count', 0)} records ({e.get('new', 0)} new)"
        rows.append(f"| {icons.get(e['status'], '')} | `{slug}` | {e['status']} | {e.get('failures', 0)} | {detail} |")
    bad = [s for s in ran if health["sources"][s]["status"] != "ok"]
    text = (
        f"### Scrape: {len(ran) - len(bad)}/{len(ran)} ok\n\n"
        "| | source | status | consecutive failures | detail |\n|---|---|---|---|---|\n" + "\n".join(rows) + "\n"
    )
    print(text)
    if path := os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m scrapers", description="Run scrapers and record health.")
    ap.add_argument("--tier", choices=["daily", "frequent"], help="only sources in this tier")
    ap.add_argument("--only", help="comma-separated slugs to run (runs even if disabled)")
    browser = ap.add_mutually_exclusive_group()
    browser.add_argument("--browser", dest="browser", action="store_true", default=None, help="only Playwright sources")
    browser.add_argument("--no-browser", dest="browser", action="store_false", help="skip Playwright sources")
    ap.add_argument("--list", action="store_true", help="list sources and exit")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args(argv)

    if args.list:
        for cls in discover():
            flags = " ".join(
                f for f, on in (("off", not cls.enabled), ("browser", cls.browser), (cls.tier, True)) if on
            )
            print(f"{cls.slug:30} {cls.kind:15} {flags}")
        return

    run(
        tier=args.tier,
        only=args.only.split(",") if args.only else None,
        browser=args.browser,
        workers=args.workers,
    )

"""
scrapers/base.py

Base class for every source. Subclass it, set the class attributes, and
implement ``scrape()``:

    class SpearfishBrewing(BaseScraper):
        name = "Spearfish Brewing Company"
        slug = "spearfish_brewing"
        kind = "beer"
        url = "https://www.spearfishbrewing.com/beers/"
        replace = True

        def scrape(self) -> list[dict]:
            ...

``scrape()`` returns a list of record dicts, or (for "object" sources like the
creek gauge) a single dict. The runner (scrapers/runner.py) calls ``run()``,
which normalizes, merges/prunes, guards against empty results and writes
``{DATA_DIR}/{slug}.json`` as an envelope:

    {"slug", "name", "kind", "url", "fetched_at", "count", "records": [...]}
    {"slug", "name", "kind", "url", "fetched_at", "data": {...}}   # object sources
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

from scrapers import dates, livedata, schema

# WUS_DATA_DIR if set (the GitHub workflow's checkout), else the local copy of the live data (scrapers/livedata.py)
DATA_DIR = livedata.data_dir()


class ScrapeEmpty(Exception):
    """Raised by run() when a scrape returns fewer records than ``min_records``."""


@dataclass
class RunResult:
    count: int = 0
    new: int = 0
    dropped: int = 0
    notes: list[str] = field(default_factory=list)


class BaseScraper(ABC):
    #: Human-readable source name.
    name: str = ""
    #: File stem and registry key.
    slug: str = ""
    #: Default record kind (see scrapers/schema.py KINDS). A record's own
    #: ``record_type`` wins, so one source can emit several kinds.
    kind: str = "other"
    #: Human-facing page for the source (shown on the status page).
    url: str = ""
    #: Event category used by the unified calendar (sports, arts, community, …).
    category: str = ""
    #: Scheduling tier: "daily" or "frequent".
    tier: str = "daily"
    #: Disabled sources are skipped by the runner (code kept, "on ice").
    enabled: bool = True
    #: Needs a Playwright browser.
    browser: bool = False
    #: True: each scrape is the full current state (tap lists, job boards).
    #: False: merge with previously saved records, then prune by kind window.
    replace: bool = False
    #: Field used to recognise the same record across runs.
    dedup_key: str = "url"
    #: How to interpret timestamps that carry no UTC offset.
    naive_tz = dates.UTC
    #: Fewer records than this is treated as a failed scrape (previous data kept).
    #: Set 0 for sources that can legitimately be empty (alerts, job boards).
    min_records: int = 1
    #: Status page flags the source once its last success is older than this.
    max_stale_hours: int = 48

    def __init__(self, name: str | None = None, slug: str | None = None):
        if name:
            self.name = name
        if slug:
            self.slug = slug
        if not self.name:
            raise ValueError(f"{self.__class__.__name__} must define a 'name' attribute or pass name= to __init__.")
        if not self.slug:
            raise ValueError(f"{self.__class__.__name__} must define a 'slug' attribute or pass slug= to __init__.")
        self.data_file: Path = DATA_DIR / f"{self.slug}.json"

    # ------------------------------------------------------------------
    # Interface
    # ------------------------------------------------------------------

    @abstractmethod
    def scrape(self) -> list[dict] | dict:
        """Fetch and parse remote data."""

    def fix(self, record: dict) -> dict:
        """Source-specific cleanup applied to each raw record before normalization."""
        return record

    def is_empty(self, payload: dict) -> bool:
        """For object sources: whether a scraped payload is unusable."""
        return not payload

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def load_envelope(self) -> dict:
        """Load the saved envelope (tolerates the legacy bare-list format)."""
        if not self.data_file.exists():
            return {}
        try:
            raw = json.loads(self.data_file.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[{self.slug}] Warning: could not load {self.data_file}: {exc}")
            return {}
        if isinstance(raw, list):
            return {"records": raw}
        if isinstance(raw, dict) and ("records" in raw or "data" in raw):
            return raw
        return {}

    def load_existing(self) -> list[dict]:
        records = self.load_envelope().get("records")
        return records if isinstance(records, list) else []

    def save(self, records: list[dict] | None = None, data: dict | None = None) -> None:
        envelope = {
            "slug": self.slug,
            "name": self.name,
            "kind": self.kind,
            "url": self.url,
            "fetched_at": dates.now().isoformat(timespec="seconds"),
        }
        if data is not None:
            envelope["data"] = data
        else:
            envelope["count"] = len(records or [])
            envelope["records"] = records or []
        self.data_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.data_file.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(envelope, indent=1, ensure_ascii=False, default=str), encoding="utf-8")
        tmp.replace(self.data_file)

    # ------------------------------------------------------------------
    # Run
    # ------------------------------------------------------------------

    def normalize(self, raw: list[dict]) -> tuple[list[dict], int]:
        out, dropped = [], 0
        for r in raw:
            if not isinstance(r, dict):
                dropped += 1
                continue
            r = self.fix(r)
            if r is None:
                dropped += 1
                continue
            rec = schema.normalize(
                r,
                kind=schema.kind_of(r, self.kind),
                source=self.slug,
                source_label=self.name,
                dedup_key=self.dedup_key,
                naive_tz=self.naive_tz,
                category=self.category,
            )
            if rec is None:
                dropped += 1
            else:
                out.append(rec)
        return out, dropped

    def run(self) -> RunResult:
        """
        Scrape, normalize, merge/prune and save. Raises on failure — including
        ScrapeEmpty when too few records come back — leaving the previously
        saved file untouched.
        """
        payload = self.scrape()

        if isinstance(payload, dict):
            if self.is_empty(payload):
                raise ScrapeEmpty("scrape returned no usable data")
            self.save(data=payload)
            return RunResult(count=1, new=0)

        fresh, dropped = self.normalize(payload or [])
        today = dates.today()
        stamp = today.isoformat()

        if len(fresh) < self.min_records:
            detail = f" ({dropped} invalid)" if dropped else ""
            raise ScrapeEmpty(f"{len(fresh)} record(s) returned, expected at least {self.min_records}{detail}")

        existing = self.load_existing()
        first_seen = {r.get(self.dedup_key): r.get("_first_seen") for r in existing if r.get(self.dedup_key)}

        # Dedupe within the fresh batch, stamping first-seen dates.
        merged: dict = {}
        for r in fresh:
            key = r.get(self.dedup_key) or r["id"]
            r["_first_seen"] = first_seen.get(key) or stamp
            merged[key] = r
        new_count = sum(1 for k in merged if k not in first_seen)

        if not self.replace:
            # Keep previously seen records the source no longer lists (feeds only
            # show the latest N), unless they've aged out of the kind's window.
            for r in existing:
                key = r.get(self.dedup_key) or r.get("id")
                if key and key not in merged:
                    merged[key] = r

        records = list(merged.values())
        if not self.replace:
            cutoff = today - timedelta(days=schema.KINDS.get(self.kind, schema.DEFAULT_KIND).window_days)
            records = [r for r in records if not schema.is_expired(r, r.get("kind", self.kind), today, cutoff)]

        records.sort(key=lambda r: r.get("start") or r.get("published") or r.get("date") or "")
        self.save(records)
        return RunResult(count=len(records), new=new_count, dropped=dropped)

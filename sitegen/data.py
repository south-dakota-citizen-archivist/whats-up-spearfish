"""
sitegen/data.py

Loads the scraper output (envelopes + _health.json) from the data directory.
"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from scrapers import dates
from sitegen.sources import CREDIT

#: Data-branch files that aren't scraper output (see scripts/import_parcels.py)
NOT_SOURCES = {"parcel_links.json"}

_ENTITY = re.compile(r"&(#\d+|#x[0-9a-fA-F]+|[A-Za-z]{2,8});")


def decoded(value):
    """
    Text as written: sources hand over HTML entities ('10&#39;x12&#39;', 'Pete &amp; Gretchen')
    in fields that are plain text, and the pages escape text themselves, so the entities would
    show as typed. Decoded throughout (twice, for text encoded twice: '&amp;#39;').
    """
    if isinstance(value, str):
        for _ in range(2):
            if not _ENTITY.search(value):
                break
            value = html.unescape(value)
        return value
    if isinstance(value, list):
        return [decoded(v) for v in value]
    if isinstance(value, dict):
        return {k: decoded(v) for k, v in value.items()}
    return value


def read_json(path: Path):
    """A data file, its text decoded (see decoded())."""
    return decoded(json.loads(path.read_text(encoding="utf-8")))


@dataclass
class Source:
    slug: str
    name: str = ""
    kind: str = ""
    url: str = ""
    fetched_at: datetime | None = None
    records: list[dict] = field(default_factory=list)
    data: dict | None = None
    health: dict = field(default_factory=dict)

    @property
    def label(self) -> str:
        """How readers know this source ("City of Spearfish", not "City of Spearfish News Flash")."""
        return CREDIT.get(self.slug) or self.name or self.slug.replace("_", " ").title()

    @property
    def enabled(self) -> bool:
        return self.health.get("enabled", True)

    @property
    def status(self) -> str:
        if not self.enabled:
            return "disabled"
        last = self.health.get("status")
        if last in ("error", "empty"):
            return last
        if self.stale:
            return "stale" if self.fetched_at else "missing"
        return last or "ok"

    @property
    def stale(self) -> bool:
        """Data older than the source's freshness threshold."""
        if not self.fetched_at:
            return True
        hours = self.health.get("max_stale_hours", 48)
        return dates.now() - self.fetched_at > timedelta(hours=hours)


class Site:
    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
        try:
            self.health = json.loads((data_dir / "_health.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            self.health = {"sources": {}}
        self.sources: dict[str, Source] = {}

        for slug, h in self.health.get("sources", {}).items():
            self.sources[slug] = Source(
                slug=slug, name=h.get("name", slug), kind=h.get("kind", ""), url=h.get("url", ""), health=h
            )

        for path in sorted(data_dir.glob("*.json")):
            if path.name.startswith("_") or path.name in NOT_SOURCES:
                continue
            try:
                env = read_json(path)
            except (OSError, json.JSONDecodeError) as exc:
                print(f"[sitegen] Warning: could not read {path.name}: {exc}")
                continue
            if not isinstance(env, dict) or not ("records" in env or "data" in env):
                print(f"[sitegen] Warning: {path.name} is not an envelope; skipping")
                continue
            src = self.sources.setdefault(path.stem, Source(slug=path.stem))
            if not src.enabled:
                continue
            src.name = src.name or env.get("name", path.stem)
            src.kind = src.kind or env.get("kind", "")
            src.url = src.url or env.get("url", "")
            src.fetched_at = dates.parse(env.get("fetched_at")) if env.get("fetched_at") else None
            src.records = env.get("records") or []
            if path.stem in CREDIT:
                for r in src.records:
                    r["source_label"] = CREDIT[path.stem]
            src.data = env.get("data")

    def get(self, slug: str) -> Source:
        return self.sources.get(slug) or Source(slug=slug)

    def records(self, kind: str | None = None, slugs: list[str] | None = None) -> list[dict]:
        out = []
        for slug, src in self.sources.items():
            if slugs is not None and slug not in slugs:
                continue
            for r in src.records:
                if kind is None or r.get("kind") == kind:
                    out.append(r)
        return out

    def by_kind(self, kind: str) -> list[Source]:
        return [s for s in self.sources.values() if s.kind == kind and s.enabled]

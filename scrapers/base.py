"""
scrapers/base.py

Abstract base class for all Spearfish Bulletin scrapers.
"""

import json
from abc import ABC, abstractmethod
from pathlib import Path

DATA_DIR = Path(__file__).resolve().parent.parent / "data"


class BaseScraper(ABC):
    """
    Subclass this, set a ``name`` and ``slug`` class attribute (or pass them
    to ``__init__``), and implement ``scrape()``.

    The dedup key used when merging new records with existing ones defaults to
    ``"url"``.  Override ``dedup_key`` on the subclass if your records use a
    different unique field.
    """

    dedup_key: str = "url"

    #: Set to True on scrapers where the full current state is authoritative —
    #: e.g. tap lists, flavor boards.  run() will replace stored records with
    #: whatever scrape() returns rather than merging.
    replace: bool = False

    def __init__(self, name: str = None, slug: str = None):
        # Allow name/slug to be set as class attributes OR passed at init time.
        if name:
            self.name = name
        if slug:
            self.slug = slug

        if not hasattr(self, "name") or not self.name:
            raise ValueError(f"{self.__class__.__name__} must define a 'name' attribute or pass name= to __init__.")
        if not hasattr(self, "slug") or not self.slug:
            raise ValueError(f"{self.__class__.__name__} must define a 'slug' attribute or pass slug= to __init__.")

        self.data_file: Path = DATA_DIR / f"{self.slug}.json"

    # ------------------------------------------------------------------
    # Abstract interface
    # ------------------------------------------------------------------

    @abstractmethod
    def scrape(self) -> list[dict]:
        """
        Fetch and parse remote data.

        Returns a list of dicts representing records.  Each record *should*
        contain at least the dedup_key field (default: ``"url"``).
        """
        ...

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def load_existing(self) -> list[dict]:
        """Load previously saved records from data/{slug}.json, or []."""
        if not self.data_file.exists():
            return []
        try:
            with self.data_file.open("r", encoding="utf-8") as fh:
                return json.load(fh)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[{self.name}] Warning: could not load {self.data_file}: {exc}")
            return []

    def save(self, records: list[dict]) -> None:
        """Write *records* to data/{slug}.json as pretty-printed JSON."""
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with self.data_file.open("w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2, ensure_ascii=False, default=str)

    # ------------------------------------------------------------------
    # Run logic
    # ------------------------------------------------------------------

    def run(self) -> list[dict]:
        """
        Orchestrate a full scrape cycle.

        When ``replace`` is True (tap lists, flavor boards, library holdings):
          - Save fresh records directly; return all of them as "new".

        Otherwise (default merge behaviour):
          1. Load existing records.
          2. Call ``scrape()`` to get fresh records.
          3. Merge: existing records take precedence on dedup_key collisions.
          4. Save the merged list.
          5. Return only the *new* records (those not previously seen).
        """
        fresh = self.scrape()

        if self.replace:
            self.save(fresh)
            print(f"[{self.name}] replaced → {len(fresh)} record(s) saved to {self.data_file.name}")
            return fresh

        existing = self.load_existing()

        # Build a lookup of existing records by dedup key.
        existing_keys: set = {r.get(self.dedup_key) for r in existing if r.get(self.dedup_key)}

        new_records = [r for r in fresh if r.get(self.dedup_key) not in existing_keys]

        merged = existing + new_records
        self.save(merged)
        print(
            f"[{self.name}] {len(new_records)} new / {len(existing)} existing "
            f"→ {len(merged)} total saved to {self.data_file.name}"
        )
        return new_records

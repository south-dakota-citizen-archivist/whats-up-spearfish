"""
scrapers/civic.py

Base class for scrapers backed by the civic-scraper library
(https://civic-scraper.readthedocs.io/en/latest/).

Supports all six platforms civic-scraper knows about:
  CivicPlusSite, CivicClerkSite, GranicusSite,
  LegistarSite, PrimeGovSite, DigitalTowPathSite

Usage — subclass CivicScraperBase and set class attributes:

    from scrapers.civic import CivicScraperBase
    from civic_scraper.platforms import CivicPlusSite

    class SpearfishCityCouncil(CivicScraperBase):
        name = "Spearfish City Council Agendas"
        slug = "spearfish_city_council"
        site_class = CivicPlusSite
        site_url = "https://sd-spearfish.civicplus.com/AgendaCenter"
        # optional:
        # asset_list = ["agenda", "minutes"]
        # start_date = "2024-01-01"   # defaults to 90 days ago
        # end_date = None             # defaults to today

Each Asset from civic-scraper is converted to a normalized dict and saved
via the standard BaseScraper persistence layer.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import TYPE_CHECKING

from scrapers.base import BaseScraper

if TYPE_CHECKING:
    from civic_scraper.base.asset import AssetCollection


class CivicScraperBase(BaseScraper):
    """
    Subclass this to add a civic-scraper-backed source.

    Required class attributes
    -------------------------
    site_class : one of the *Site classes from civic_scraper.platforms
    site_url   : base URL for the government's meeting portal

    Optional class attributes
    -------------------------
    asset_list  : list of asset type strings to filter, e.g. ["agenda", "minutes"]
                  None means all supported types.
    start_date  : "YYYY-MM-DD" string; defaults to 90 days ago
    end_date    : "YYYY-MM-DD" string; defaults to today
    download    : bool — whether to download the actual files (default False)
    file_size   : max file size in MB to download (only used when download=True)
    cache_dir   : path string for civic-scraper cache; defaults to data/civic_cache/
    """

    site_class = None
    site_url: str = ""
    asset_list: list[str] | None = None
    start_date: str | None = None
    end_date: str | None = None
    download: bool = False
    file_size: int | None = None
    cache_dir: str | None = None

    # dedup on civic-scraper's meeting_id + asset_type composite
    dedup_key: str = "asset_id"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.site_class is None:
            raise ValueError(
                f"{self.__class__.__name__} must set site_class to a "
                "civic_scraper.platforms.*Site class."
            )
        if not self.site_url:
            raise ValueError(
                f"{self.__class__.__name__} must set site_url."
            )

    def _build_site(self):
        from civic_scraper.base.cache import Cache

        cache_path = self.cache_dir or str(
            (self.data_file.parent / "civic_cache").resolve()
        )
        return self.site_class(self.site_url, cache=Cache(cache_path))

    def _default_start_date(self) -> str:
        return (date.today() - timedelta(days=90)).isoformat()

    def _default_end_date(self) -> str:
        return date.today().isoformat()

    def scrape(self) -> list[dict]:
        import inspect

        site = self._build_site()
        supported = inspect.signature(site.scrape).parameters

        kwargs: dict = {"download": self.download}
        if "start_date" in supported:
            kwargs["start_date"] = self.start_date or self._default_start_date()
        if "end_date" in supported:
            kwargs["end_date"] = self.end_date or self._default_end_date()
        if "asset_list" in supported and self.asset_list is not None:
            kwargs["asset_list"] = self.asset_list
        if "file_size" in supported and self.file_size is not None:
            kwargs["file_size"] = self.file_size

        assets: AssetCollection = site.scrape(**kwargs)
        return [self._asset_to_dict(a) for a in assets]

    def _asset_to_dict(self, asset) -> dict:
        """Convert a civic-scraper Asset to a plain dict for JSON storage."""
        # Build a stable composite ID so dedup works across runs.
        meeting_id = getattr(asset, "meeting_id", "") or ""
        asset_type = getattr(asset, "asset_type", "") or ""
        asset_id = f"{meeting_id}__{asset_type}" if meeting_id else ""

        meeting_date = getattr(asset, "meeting_date", None)
        meeting_time = getattr(asset, "meeting_time", None)

        # Combine date + time into an ISO datetime string when both are present.
        start_dt = None
        if meeting_date:
            start_dt = str(meeting_date)
            if meeting_time:
                start_dt = f"{meeting_date}T{meeting_time}"

        return {
            "asset_id": asset_id,
            "url": getattr(asset, "url", ""),
            "title": getattr(asset, "asset_name", ""),
            "asset_type": asset_type,
            "committee": getattr(asset, "committee_name", ""),
            "place": getattr(asset, "place", ""),
            "state": getattr(asset, "state_or_province", ""),
            "meeting_id": meeting_id,
            "meeting_date": str(meeting_date) if meeting_date else None,
            "meeting_time": str(meeting_time) if meeting_time else None,
            "start_dt": start_dt,
            "content_type": getattr(asset, "content_type", ""),
            "content_length": getattr(asset, "content_length", None),
            "scraped_by": getattr(asset, "scraped_by", ""),
            # record_type drives the build.py classifier ("document" vs "event")
            "record_type": "document",
            "source_label": self.name,
        }

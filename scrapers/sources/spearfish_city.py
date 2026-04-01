"""
scrapers/sources/spearfish_city.py

City of Spearfish, SD — meeting events, agendas, minutes, and packets
via the CivicClerk OData API.

Portal:  https://spearfishsd.portal.civicclerk.com/
API:     https://spearfishsd.api.civicclerk.com/v1/
"""

import requests

from scrapers.base import BaseScraper

API_BASE = "https://spearfishsd.api.civicclerk.com/v1"
PORTAL_BASE = "https://spearfishsd.portal.civicclerk.com"
# The API ignores $top and always returns 15 results per page.
PAGE_SIZE = 15


class SpearfishCity(BaseScraper):
    name = "City of Spearfish"
    slug = "spearfish_city"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        records = []
        skip = 0

        while True:
            params = {
                "$skip": skip,
                "$orderby": "startDateTime desc",
            }
            resp = requests.get(
                f"{API_BASE}/Events",
                params=params,
                headers={"Accept": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            events = data.get("value", [])
            if not events:
                break

            for event in events:
                records.extend(self._event_to_records(event))

            if len(events) < PAGE_SIZE:
                break
            skip += PAGE_SIZE

        return records

    def _event_to_records(self, event: dict) -> list[dict]:
        """
        Yield one record per published file (agenda, minutes, packet, etc.)
        attached to a meeting event, plus the event itself if it has no files.
        """
        event_id = event["id"]
        portal_url = f"{PORTAL_BASE}/event/{event_id}"
        start_dt = event.get("startDateTime") or event.get("eventDate")

        location = event.get("eventLocation") or {}
        address_parts = filter(None, [
            location.get("address1"),
            location.get("address2"),
            location.get("city"),
            location.get("state"),
            location.get("zipCode"),
        ])
        location_str = ", ".join(address_parts)

        base = {
            "event_id": event_id,
            "event_name": event.get("eventName", ""),
            "category": event.get("eventCategoryName") or event.get("categoryName", ""),
            "start_dt": start_dt,
            "location": location_str,
            "portal_url": portal_url,
            "has_media": event.get("hasMedia", False),
            "media_url": event.get("mediaStreamPath") or event.get("mediaSourcePathMp4") or "",
            "record_type": "document",
            "source_label": "City of Spearfish",
        }

        published_files = event.get("publishedFiles") or []
        if not published_files:
            # No documents published yet — skip; nothing useful to show.
            return []

        records = []
        for f in published_files:
            relative_url = f.get("url", "")
            file_url = (
                f"{PORTAL_BASE}/{relative_url}" if relative_url else portal_url
            )
            records.append({
                **base,
                # Use file_url as the primary dedup URL so each file is a
                # distinct record; portal_url links back to the meeting page.
                "url": file_url,
                "title": f.get("name") or event.get("agendaName") or event.get("eventName", ""),
                "doc_type": f.get("type", ""),
                "file_url": file_url,
            })

        return records

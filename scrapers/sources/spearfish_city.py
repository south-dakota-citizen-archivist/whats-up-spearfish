"""
scrapers/sources/spearfish_city.py

City of Spearfish, SD — meeting events, agendas, minutes, and packets
via the CivicClerk OData API.

Portal:  https://spearfishsd.portal.civicclerk.com/
API:     https://spearfishsd.api.civicclerk.com/v1/
"""

from datetime import timedelta

from scrapers import dates, net, schema
from scrapers.base import BaseScraper

API_BASE = "https://spearfishsd.api.civicclerk.com/v1"
PORTAL_BASE = "https://spearfishsd.portal.civicclerk.com"
# The API ignores $top and always returns 15 results per page.
PAGE_SIZE = 15


class SpearfishCity(BaseScraper):
    _saved_chapters: dict = {}

    name = "City of Spearfish"
    slug = "spearfish_city"
    kind = "document"
    url = "https://spearfishsd.portal.civicclerk.com/"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        self._saved_chapters = {r.get("event_id"): r["chapters"] for r in self.load_existing() if r.get("chapters")}
        records = []
        skip = 0
        # newest first, so paging stops at meetings older than the site keeps (the API would
        # otherwise hand over every meeting the city has ever posted, each run)
        cutoff = (dates.today() - timedelta(days=schema.KINDS[self.kind].window_days + 7)).isoformat()

        while True:
            params = {
                "$skip": skip,
                "$orderby": "startDateTime desc",
            }
            resp = net.get(
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

            older = 0
            for event in events:
                if (event.get("startDateTime") or event.get("eventDate") or "")[:10] < cutoff:
                    older += 1
                    continue
                records.extend(self._event_to_records(event))

            if len(events) < PAGE_SIZE or older == len(events):
                break
            skip += PAGE_SIZE

        return records

    def _chapters(self, event_id: int) -> list[dict]:
        """
        Where each agenda item starts in the meeting's video (the clerk's bookmarks), from the
        endpoint the portal's video page uses. Saved ones are reused; a video's bookmarks are
        added once, after the meeting.
        """
        if saved := self._saved_chapters.get(event_id):
            return saved
        try:
            resp = net.get(f"{API_BASE}/EventsMedia/{event_id}", headers={"Accept": "application/json"}, timeout=30)
            resp.raise_for_status()
            marks = resp.json().get("eventBookmarks") or []
        except Exception as exc:  # noqa: BLE001 — the meeting still lists without them
            print(f"[{self.slug}] no video bookmarks for event {event_id}: {exc}")
            return []
        return chapters_from(marks)

    def _event_to_records(self, event: dict) -> list[dict]:
        """
        Yield one record per published file (agenda, minutes, packet, etc.)
        attached to a meeting event, plus the event itself if it has no files.
        """
        event_id = event["id"]
        portal_url = f"{PORTAL_BASE}/event/{event_id}"
        start_dt = event.get("startDateTime") or event.get("eventDate")

        location = event.get("eventLocation") or {}
        address_parts = filter(
            None,
            [
                location.get("address1"),
                location.get("address2"),
                location.get("city"),
                location.get("state"),
                location.get("zipCode"),
            ],
        )
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
            # the portal's player, with the agenda beside the video
            "media_page": f"{portal_url}/media" if event.get("hasMedia") else "",
            "chapters": self._chapters(event_id) if event.get("hasMedia") else [],
            "record_type": "document",
            "source_label": "City of Spearfish",
        }

        published_files = event.get("publishedFiles") or []
        if not published_files:
            # No documents published yet — skip; nothing useful to show.
            return []

        records = []
        for f in published_files:
            file_id = f.get("fileId")
            file_type = (f.get("type") or "agenda").lower().replace(" ", "-")
            file_url = f"{PORTAL_BASE}/event/{event_id}/files/{file_type}/{file_id}" if file_id else portal_url
            records.append(
                {
                    **base,
                    "url": file_url,
                    "title": f.get("name") or event.get("agendaName") or event.get("eventName", ""),
                    "doc_type": f.get("type", ""),
                    "file_url": file_url,
                }
            )

        return records


def chapters_from(marks: list[dict]) -> list[dict]:
    """The clerk's bookmarks as [{id, t (seconds), title, sub (an item under another)}], in agenda order."""
    out = []
    for m in sorted(marks, key=lambda m: m.get("sortorder") or 0):
        # a bookmark can carry more under it (additionalBookmarks), as the portal shows them
        for b, sub in [(m, (m.get("parentId") or -1) != -1)] + [(a, True) for a in m.get("additionalBookmarks") or []]:
            t, title = b.get("markerTimeStart"), " ".join((b.get("markerTitle") or b.get("markerText") or "").split())
            if isinstance(t, (int, float)) and title:
                out.append({"id": b.get("id"), "t": int(t), "title": title, "sub": sub})
    return out

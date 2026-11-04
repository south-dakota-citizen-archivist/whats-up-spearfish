"""
Which PDFs the state has on file for a spill, asked the way its map does when a spill
is clicked (one spill at a time, a pause between requests). A spill can have several:
the report itself and later filings (2026.146.pdf, 1985.075A.pdf …).
"""

from __future__ import annotations

from . import net

FILES_API = "https://apps.sd.gov/NR42InteractiveMap/api/Map/GetSpillsPDF"


def lookup(layer_id: float, delay: float = 1.0) -> list[str]:
    """The URLs of every PDF on file for one spill (the map's own request)."""
    query = f"Select * From NR42EnvEvents.dbo.GISpdf where id1 = {float(layer_id)!r}"
    resp = net.request("POST", FILES_API, delay=delay, headers={"query": query})
    resp.raise_for_status()
    urls = []
    for row in resp.json() or []:
        url = (row.get("URL") or "").strip().replace("denr.sd.gov", "danr.sd.gov").replace("http://", "https://")
        if url and url not in urls:
            urls.append(url)
    return urls

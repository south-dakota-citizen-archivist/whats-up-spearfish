"""
tests/test_scraper_fire.py

Fire conditions: which InciWeb fires count as active South Dakota wildfires
(not fully contained, updated within the month), and fire danger zones from the
National Weather Service statement.
"""

from __future__ import annotations

import pytest

from scrapers.sources import fire


class FakeResponse:
    def __init__(self, text):
        self.text = text

    def raise_for_status(self):
        pass


def _row(name, state="South Dakota", size="444 Acres", updated="2 days ago", href=None):
    href = href or "/incident-information/" + name.split()[0].lower()
    return f"""
    <tr>
      <td class="views-field views-field-title"><a href="{href}">{name}</a></td>
      <td class="views-field views-field-field-incident-type">Wildfire</td>
      <td class="views-field views-field-field-state">{state}</td>
      <td class="views-field views-field-field-incident-size">{size}</td>
      <td class="views-field views-field-field-last-209-update">{updated}</td>
    </tr>"""


INCIDENTS = f"""<table class="usa-table"><tbody>
  {_row("Lookout Fire - SDSDS", size="1234")}
  {_row("Contained Fire - SDBHF")}
  {_row("Old Fire - SDBHF", updated="2 months ago")}
  {_row("Teton Fire - WYBTF", state="Wyoming")}
  {_row("Quiet Fire - SDBHF")}
</tbody></table>"""


def _incident_page(percent):
    return f"<table><tr><th>Percent of Perimeter Contained</th><td>{percent}%</td></tr></table>"


@pytest.fixture
def inciweb(monkeypatch):
    fetched = []
    pages = {
        fire.INCIWEB_URL: INCIDENTS,
        f"{fire.INCIWEB_BASE}/incident-information/lookout": _incident_page(35),
        f"{fire.INCIWEB_BASE}/incident-information/contained": _incident_page(100),
        f"{fire.INCIWEB_BASE}/incident-information/quiet": "<p>No containment listed</p>",
    }

    def get(url, **kw):
        fetched.append(url)
        if url not in pages:
            raise ConnectionError(url)
        return FakeResponse(pages[url])

    monkeypatch.setattr(fire.net, "get", get)
    return fetched


def test_only_active_south_dakota_fires(inciweb):
    incidents = fire.fetch_incidents()
    assert [i["name"] for i in incidents] == ["Lookout Fire", "Quiet Fire"]  # agency code dropped
    lookout, quiet = incidents
    assert lookout["contained"] == 35 and lookout["size"] == "1,234 acres"
    assert lookout["url"] == f"{fire.INCIWEB_BASE}/incident-information/lookout"
    assert quiet["contained"] is None and quiet["size"] == "444 Acres"
    # a fire without an update in a month isn't looked up at all
    assert not any("/old" in u for u in inciweb)


def test_unreachable_incident_page_means_unknown_containment(inciweb):
    assert fire.containment(f"{fire.INCIWEB_BASE}/incident-information/missing") is None


RFD = """
<pre>
Rangeland Fire Danger Statement
National Weather Service Rapid City SD
144 AM MST Mon Nov 2 2026

SDZ001-002-012>014-025>027-
030115-
Harding-Northern Perkins-Butte-
Northern Foothills-Rapid City-
Including the cities of Buffalo, Spearfish
144 AM MST Mon Nov 2 2026 /244 AM CST Mon Nov 2 2026/

...LOW FIRE DANGER...

The grassland fire danger index will reach the low category this
afternoon.

The outlook for Tuesday afternoon, The grassland fire danger
index will reach the low category to high category.

$$

SDZ250-
030115-
Western Fall River-
144 AM MST Mon Nov 2 2026

...VERY HIGH FIRE DANGER...

Fires will start easily and spread rapidly.

$$
</pre>
"""


def test_fire_danger_zones(monkeypatch):
    monkeypatch.setattr(fire.net, "get", lambda url, **kw: FakeResponse(RFD))
    danger = fire.fetch_danger()
    assert danger["issued"] == "144 AM MST Mon Nov 2 2026"
    assert danger["zones"] == [
        {
            "name": "Harding, Northern Perkins, Butte, Northern Foothills, Rapid City",
            "level": "Low",
            "description": "The grassland fire danger index will reach the low category this afternoon.",
        },
        {
            "name": "Western Fall River",
            "level": "Very High",
            "description": "Fires will start easily and spread rapidly.",
        },
    ]


def test_one_part_failing_keeps_the_other(monkeypatch):
    monkeypatch.setattr(fire, "fetch_incidents", lambda: (_ for _ in ()).throw(TimeoutError("inciweb down")))
    monkeypatch.setattr(fire, "fetch_danger", lambda: {"issued": "x", "zones": [], "url": ""})
    out = fire.Fire().scrape()
    assert out["incidents"] is None and out["danger"]["issued"] == "x"
    assert out["errors"] == ["incidents: TimeoutError: inciweb down"]
    assert not fire.Fire().is_empty(out)

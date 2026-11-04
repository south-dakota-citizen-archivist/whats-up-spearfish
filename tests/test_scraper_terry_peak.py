"""
tests/test_scraper_terry_peak.py

Terry Peak's snow report and lift and trail status, read from the icons and
numbers on its pages.
"""

from __future__ import annotations

from scrapers.sources.terry_peak import parse_snow, parse_status

ICON = "https://terrypeak.com/wp-content/themes/terrypeak/dist/img/icons/icon-{}.svg"

SNOW = """
<section class="slice o-snow-report"><div class="o-snow-report__row">
  <div class="o-snow-report__row-item"><div class="o-snow-report__inches">3&rdquo;</div>
    <div class="o-snow-report__text">Overnight</div></div>
  <div class="o-snow-report__row-item"><div class="o-snow-report__inches">5&rdquo;</div>
    <div class="o-snow-report__text">48 Hours</div></div>
  <div class="o-snow-report__row-item"><div class="o-snow-report__inches">7&rdquo;</div>
    <div class="o-snow-report__text">72 Hours</div></div>
  <div class="o-snow-report__row-item">
    <div class="mb-1"><strong>41&quot;</strong> Season Snow Accumulation</div>
    <div class=""><strong>18&quot;</strong> Base Depth</div></div>
</div></section>
<div class="o-weather-sidebar__snow"><div class="o-weather-sidebar__snow-inch">9&rdquo;</div>
  <span class="o-weather-sidebar__small-text">Overnight</span></div>
"""


def _row(name, *icons, condition=()):
    imgs = "".join(f'<img src="{ICON.format(i)}">' for i in icons)
    cond = "".join(f'<img src="{ICON.format(i)}">' for i in condition)
    return (f'<div class="o-status__table-row js-trails-item"><div class="o-status__table-column">{imgs}'
            f'<span class="o-status__table-column-text"> {name} </span></div>'
            f'<div class="o-status__table-column">{cond}</div></div>')  # fmt: skip


STATUS = f"""
<div id="liftStatus"><div class="o-status__table">
  <div class="o-status__table-row"><div class="o-status__table-column"><img src="{ICON.format("open")}">
    <span class="o-status__table-column-text"> Stewart Lift</span></div>
    <div class="o-status__table-column"><img src="{ICON.format("triple")}"></div></div>
  <div class="o-status__table-row"><div class="o-status__table-column"><img src="{ICON.format("closed")}">
    <span class="o-status__table-column-text">Kussy Express</span></div>
    <div class="o-status__table-column"><img src="{ICON.format("quad")}"></div></div>
</div></div>
<div class="js-trails-container">
  {_row("Stewart Slope", "open", "beginner", condition=("groomed", "snow"))}
  {_row("Holy Terror", "closed", "advanced")}
</div>
"""


def test_snow_report_takes_the_full_report_first():
    assert parse_snow(SNOW) == {"overnight": 3.0, "48h": 5.0, "72h": 7.0, "season": 41.0, "base": 18.0}


def test_lifts_and_trails():
    status = parse_status(STATUS)
    assert status["lifts"] == [
        {"name": "Stewart Lift", "open": True, "type": "triple chair"},
        {"name": "Kussy Express", "open": False, "type": "high-speed quad"},
    ]
    assert status["trails"] == [
        {"name": "Stewart Slope", "open": True, "difficulty": "beginner", "conditions": ["groomed", "snowmaking"]},
        {"name": "Holy Terror", "open": False, "difficulty": "advanced", "conditions": []},
    ]

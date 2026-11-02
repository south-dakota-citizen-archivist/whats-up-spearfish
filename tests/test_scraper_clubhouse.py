"""
tests/test_scraper_clubhouse.py

The Clubhouse's draft list, from its own menu page (an Elementor price list).
"""

from __future__ import annotations

from bs4 import BeautifulSoup

from scrapers.sources.clubhouse_spearfish import MENU_URL, parse_drafts


def _item(title, desc):
    return f"""<li><a class="elementor-price-list-item" href="#"><div class="elementor-price-list-text">
      <div class="elementor-price-list-header"><span class="elementor-price-list-title">{title}</span></div>
      <p class="elementor-price-list-description">{desc}</p></div></a></li>"""


PAGE = f"""
<h2>Starters</h2>
<ul class="elementor-price-list">{_item("Cheese Curds", "Crispy outside, gooey inside")}</ul>
<h2 class="elementor-heading-title">Draft Beers</h2>
<p>Draft Beers are seasonal and vary from time to time.</p>
<ul class="elementor-price-list">
  {_item("Just Boots", "Blood orange ale, a fruity seasonal draft.<br/>- The Clubhouse of Spearfish")}
  {_item("Copper Midge Amber Lager", "Glowing copper color, toasted malt.<br/>- Spearfish Brewing Co.")}
  {_item("Mystery Pour", "")}
</ul>
<h2>Premium Beer</h2>
<ul class="elementor-price-list">{_item("Blue Moon", "")}</ul>
"""


def test_drafts_only_with_brewery_split_out():
    beers = parse_drafts(BeautifulSoup(PAGE, "html.parser"))
    assert [b["title"] for b in beers] == ["Just Boots", "Copper Midge Amber Lager", "Mystery Pour"]
    copper = beers[1]
    assert copper["brewery"] == "Spearfish Brewing Co."
    assert copper["description"] == "Glowing copper color, toasted malt."
    assert copper["slug"] == "copper-midge-amber-lager" and copper["url"] == MENU_URL
    assert beers[0]["brewery"] == ""  # the house beer
    assert beers[2]["description"] == "" and beers[2]["brewery"] == ""


def test_no_draft_list_means_nothing():
    assert parse_drafts(BeautifulSoup("<h2>Starters</h2><ul class='elementor-price-list'></ul>", "html.parser")) == []

"""
scrapers/sources/lawrence_county.py

Lawrence County, SD — meeting agendas and minutes via CivicPlus AgendaCenter.
https://www.lawrence.sd.us/AgendaCenter
"""

from civic_scraper.platforms import CivicPlusSite

from scrapers.civic import CivicScraperBase


class LawrenceCounty(CivicScraperBase):
    name = "Lawrence County"
    slug = "lawrence_county"
    site_class = CivicPlusSite
    site_url = "https://www.lawrence.sd.us/AgendaCenter"
    asset_list = ["agenda", "minutes", "agenda_packet"]

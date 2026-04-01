"""
scrapers/sources/example_civicplus.py

EXAMPLE — rename this file and update the class attributes to add a real
CivicPlus AgendaCenter source.  Delete this file once you have a real one.

NOTE: CivicClerkSite from civic-scraper only works with the older
*.civicclerk.com portals.  The newer *.portal.civicclerk.com portals have
an OData API; model new sources on spearfish_city.py instead.

Other platform classes available from civic_scraper.platforms:
  CivicPlusSite, GranicusSite, LegistarSite, PrimeGovSite, DigitalTowPathSite
"""

# from civic_scraper.platforms import CivicPlusSite
# from scrapers.civic import CivicScraperBase
#
#
# class ExampleCivicPlus(CivicScraperBase):
#     name = "Example City Council"
#     slug = "example_city_council"
#     site_class = CivicPlusSite
#     site_url = "https://sd-example.civicplus.com/AgendaCenter"
#     asset_list = ["agenda", "minutes"]

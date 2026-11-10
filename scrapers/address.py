"""
scrapers/address.py

Street addresses: the one place they're parsed and turned into keys for matching records
across sources (city permits, OpenGov, Planning Commission agendas, county parcels). The
parsing is sdplaces.address (usaddress, with USPS abbreviations), which handles what local
records throw at it: several addresses in one field, tags glued to the street, SAINT/ST,
text that isn't an address.

Two keys per address:

- key():   number + direction + street + type, with the direction moved to the front, so
           "515 27TH ST N" and "515 N 27TH ST" match ("515 N 27TH ST")
- loose(): the same without any direction. The city and county disagree on directions
           ("1440 N MAIN ST" vs "1440 MAIN ST"), so callers fall back to it only when it
           identifies a single place.

Units ("UNIT 3", "STE B", "#4", a bare number after the street type) are kept separately and
left out of both keys: a unit belongs to its building's site.
"""

from sdplaces.address import Address, key, keys, loose, parse

__all__ = ["Address", "key", "keys", "loose", "parse"]

"""
scrapers/sources/sawyer_brewing.py

Sawyer Brewing Co., Spearfish SD — beers currently on tap.
https://www.sawyerbrewingco.com/menu

The menu page (Squarespace) renders beer names as graphical text inside
can-label images. We walk the page to collect image URLs per category,
then enrich each with data from sawyer_brewing.json (title, description,
ABV, prices, notes), keyed by image URL.
"""

import json
from pathlib import Path

from scrapers.base import BaseScraper
from scrapers.slack import send_alert
from scrapers.utils import fetch_html, make_slug

SOURCE_URL = "https://www.sawyerbrewingco.com/menu"

BEER_CATEGORIES = {"Light & Easy", "Hop Heads", "Sour Power", "Dark Side"}
STOP_CATEGORIES = {"Wine", "Non- Alcoholic Options", "Non-Alcoholic Options", "Location"}

_LOOKUP_FILE = Path(__file__).parent / "sawyer_brewing.json"


def _load_lookup() -> dict[str, dict]:
    """Load sawyer_brewing.json keyed by image filename (no path or query params)."""
    try:
        entries = json.loads(_LOOKUP_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return {e["img_url"].split("?")[0].rsplit("/", 1)[-1]: e for e in entries if e.get("img_url")}


class SawyerBrewing(BaseScraper):
    name = "Sawyer Brewing Co."
    slug = "sawyer_brewing"
    dedup_key = "image_url"
    replace = True

    def scrape(self) -> list[dict]:
        soup = fetch_html(SOURCE_URL)
        lookup = _load_lookup()
        records = []
        current_category = None
        unmatched = []

        for block in soup.select(".sqs-block-website-component"):
            text = block.get_text(strip=True)

            if text in BEER_CATEGORIES:
                current_category = text
                continue
            if text in STOP_CATEGORIES or any(text.startswith(s) for s in STOP_CATEGORIES):
                current_category = None
                continue

            if current_category is None:
                continue

            img = block.find("img", src=lambda s: s and "squarespace-cdn.com" in s)
            if not img:
                continue

            image_url = img.get("src", "").strip().split("?")[0]
            filename = image_url.rsplit("/", 1)[-1]
            info = lookup.get(filename, {})

            if not info:
                unmatched.append(image_url)

            title = info.get("title") or filename
            description = info.get("description") or ""
            abv = info.get("abv") or ""
            notes = info.get("notes") or ""
            prices = info.get("prices") or []

            records.append({
                "url": SOURCE_URL,
                "image_url": image_url,
                "title": title,
                "slug": make_slug(title),
                "category": current_category,
                "description": description,
                "abv": abv,
                "notes": notes,
                "prices": prices,
                "record_type": "beer",
                "source_label": "Sawyer Brewing Co.",
            })

        if unmatched:
            lines = "\n".join(f"• `{u.rsplit('/', 1)[-1]}`" for u in unmatched)
            send_alert(
                text=f"Sawyer Brewing: {len(unmatched)} beer(s) not in sawyer_brewing.json — add entries to get names/descriptions.",  # noqa: E501
                blocks=[{
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": (
                            f":beer: *Sawyer Brewing* — {len(unmatched)} unrecognised image(s) found on the menu.\n"
                            f"Add entries to `scrapers/sources/sawyer_brewing.json` for:\n{lines}"
                        ),
                    },
                }],
            )

        return records

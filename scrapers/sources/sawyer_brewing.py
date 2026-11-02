"""
scrapers/sources/sawyer_brewing.py

Sawyer Brewing Co., Spearfish SD — beers currently on tap.
https://www.sawyerbrewingco.com/menu

The menu page (Squarespace) has no beer text at all: each beer is an image
with the can on the left and the name, description, ABV and prices printed on
the right. We walk the page to collect image URLs per category and read each
label's text with Tesseract OCR. sawyer_brewing.json (hand-entered, keyed by
image filename) is the fallback when OCR isn't available or can't read a label.
"""

from __future__ import annotations

import io
import json
import re
import shutil
import subprocess
from pathlib import Path

from scrapers import net
from scrapers.base import BaseScraper
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


_PRICE_RE = re.compile(r"\$\s*(\d+(?:\.\d\d)?)\s*(\d+)\s*(?:oz|o2|02)", re.I)


def ocr_label(image_url: str) -> str:
    """Text from the right-hand (printed) part of a beer label image; "" if OCR isn't possible."""
    if not shutil.which("tesseract"):
        return ""
    from PIL import Image

    resp = net.get(image_url, params={"format": "1000w"})
    resp.raise_for_status()
    im = Image.open(io.BytesIO(resp.content)).convert("L")
    w, h = im.size
    # the can artwork fills the left ~37%; enlarging helps Tesseract with the small type
    im = im.crop((int(w * 0.37), 0, w, h))
    im = im.resize((im.width * 2, im.height * 2))
    buf = io.BytesIO()
    im.save(buf, "PNG")
    out = subprocess.run(
        ["tesseract", "stdin", "stdout", "--psm", "6"], input=buf.getvalue(), capture_output=True, timeout=60
    )
    return out.stdout.decode("utf-8", "replace")


def parse_label(text: str) -> dict:
    """'The Show Must Go On IPA / This small batch… / ABV 5.7% / $3.00 5 oz/ …' → title, description, abv, prices."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        return {}
    out: dict = {"title": lines[0].replace("¢", "•"), "description": "", "abv": "", "prices": []}
    desc = []
    for ln in lines[1:]:
        if m := re.match(r"ABV\s*([\d.]+)\s*%", ln, re.I):
            out["abv"] = f"{m.group(1)}%"
        elif "$" in ln:
            out["prices"] = [{"price": float(p), "ounces": int(oz)} for p, oz in _PRICE_RE.findall(ln)]
        elif not out["abv"]:
            desc.append(ln)
    out["description"] = " ".join(desc)
    return out


class SawyerBrewing(BaseScraper):
    name = "Sawyer Brewing Co."
    slug = "sawyer_brewing"
    kind = "beer"
    url = "https://www.sawyerbrewingco.com/menu"
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
            try:
                info = parse_label(ocr_label(image_url))
            except Exception as exc:  # noqa: BLE001
                print(f"[{self.slug}] OCR failed for {filename}: {exc}")
                info = {}
            if len(info.get("title", "")) < 3:
                info = lookup.get(filename, {})
            if not info:
                unmatched.append(image_url)
                continue  # an unreadable label isn't worth showing as a file name

            title = info.get("title")
            description = info.get("description") or ""
            abv = info.get("abv") or ""
            notes = info.get("notes") or ""
            prices = info.get("prices") or []

            records.append(
                {
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
                }
            )

        if unmatched:
            names = ", ".join(u.rsplit("/", 1)[-1] for u in unmatched)
            print(f"[{self.slug}] Warning: couldn't read {len(unmatched)} label(s): {names}")

        return records

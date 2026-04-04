"""
scrapers/sources/sdpb_news.py

South Dakota Public Broadcasting — local news.
https://www.sdpb.org/news

The news listing page is JS-rendered (NPR CMS), so we use a playwright
stealth browser to collect article URLs, then fetch each article page
with requests to extract schema.org NewsArticle ld+json (server-rendered).

Sends a Slack alert for each new article.
"""

from __future__ import annotations

import html
import json
import re

import requests
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from scrapers.base import BaseScraper
from scrapers.slack import send_alert
from scrapers.utils import make_slug

BASE_URL = "https://www.sdpb.org"
NEWS_URL = f"{BASE_URL}/news"

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
}
_WHITESPACE_RE = re.compile(r"\s+")
_LDJSON_RE = re.compile(r'type="application/ld\+json">(.*?)</script>', re.DOTALL)


def _fetch_article_urls() -> list[str]:
    """Render the news listing page and return unique article URLs."""
    with Stealth().use_sync(sync_playwright()) as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(NEWS_URL, timeout=30000, wait_until="networkidle")
        page.wait_for_timeout(2000)
        hrefs = page.eval_on_selector_all("a[href]", "els => [...new Set(els.map(e => e.href))]")
        browser.close()

    return [
        u
        for u in hrefs
        if re.search(r"sdpb\.org/.+/\d{4}-\d{2}-\d{2}/", u) and "/podcast/" not in u and "/schedule" not in u
    ]


def _parse_article(url: str) -> dict | None:
    """Fetch an article page and extract fields from its NewsArticle ld+json."""
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=20)
        resp.raise_for_status()
    except requests.RequestException as exc:
        print(f"[SDPB] Warning: could not fetch {url}: {exc}")
        return None

    blocks = _LDJSON_RE.findall(resp.text)
    article = None
    description = ""

    for raw in blocks:
        try:
            d = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        if d.get("@type") == "NewsArticle":
            article = d
        elif d.get("@type") == "ListenAction" and d.get("description"):
            # description lives in the ListenAction block
            description = html.unescape(d["description"]).strip()

    if not article:
        return None

    title = html.unescape((article.get("headline") or "")).strip()
    if not title:
        return None

    published = ""
    raw_date = article.get("datePublished") or ""
    if raw_date:
        published = raw_date[:10]  # YYYY-MM-DD

    authors = article.get("author") or []
    if isinstance(authors, dict):
        authors = [authors]
    byline_parts = [a.get("name", "") for a in authors if a.get("name")]
    byline = "By " + ", ".join(byline_parts) if byline_parts else ""
    byline = _WHITESPACE_RE.sub(" ", byline).strip()

    image_url = ""
    img = article.get("image") or {}
    if isinstance(img, dict):
        image_url = img.get("url", "")
    elif isinstance(img, str):
        image_url = img

    return {
        "url": url,
        "title": title,
        "slug": make_slug(f"sdpb-{title}"),
        "published": published,
        "byline": byline,
        "description": description,
        "image_url": image_url,
        "record_type": "news",
        "source_label": "SDPB",
    }


def _slack_blocks(record: dict) -> list[dict]:
    header = (f"*<{record['url']}|{record['title']}>*\n{record['published']}   {record['byline']}").strip()
    blocks = [{"type": "section", "text": {"type": "mrkdwn", "text": header}}]
    desc = record.get("description", "")
    if desc:
        blocks.append({"type": "section", "text": {"type": "mrkdwn", "text": desc}})
    return blocks


class SDPBNews(BaseScraper):
    name = "SDPB"
    slug = "sdpb_news"
    dedup_key = "url"

    def scrape(self) -> list[dict]:
        urls = _fetch_article_urls()
        print(f"  [SDPB] {len(urls)} article URLs found")
        records = []
        for url in urls:
            record = _parse_article(url)
            if record:
                records.append(record)
        print(f"  [SDPB] {len(records)} articles parsed")
        return records

    def run(self) -> list[dict]:
        new_records = super().run()
        for record in new_records:
            send_alert(
                text=f"SDPB: {record['title']}",
                blocks=_slack_blocks(record),
            )
        return new_records

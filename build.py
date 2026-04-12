"""
build.py

Static-site builder for Spearfish Bulletin.

Single-page dashboard: loads all JSON from data/, groups records by
record_type, filters events to future-only, renders one index.html.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from dateutil import parser as dateutil_parser
from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
TEMPLATES_DIR = ROOT / "site" / "templates"
STATIC_DIR = ROOT / "site" / "static"
OUTPUT_DIR = ROOT / "_site"

MT = ZoneInfo("America/Denver")
NOW = datetime.now(tz=MT)
TODAY = NOW.date()

_DATE_ONLY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _to_mountain(value: str | None) -> datetime | None:
    """
    Parse any date/datetime string and return an aware Mountain Time datetime.

    Strategy:
      - Date-only strings (YYYY-MM-DD) → treat as a Mountain Time calendar
        date at midnight; no UTC shift applied.
      - Timezone-aware strings → convert directly to MT.
      - Naive strings with a time component → assume UTC, then convert to MT.
        (Most API sources — iCal, OData, Sidearm — store times as UTC.)
    """
    if not value:
        return None
    try:
        if _DATE_ONLY_RE.match(value):
            d = date.fromisoformat(value)
            return datetime(d.year, d.month, d.day, tzinfo=MT)
        tzinfos = {
            "MDT": -6 * 3600,
            "MST": -7 * 3600,
            "CDT": -5 * 3600,
            "CST": -6 * 3600,
            "EDT": -4 * 3600,
            "EST": -5 * 3600,
            "PDT": -7 * 3600,
            "PST": -8 * 3600,
        }
        dt = dateutil_parser.parse(value, tzinfos=tzinfos)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(MT)
    except (ValueError, TypeError, OverflowError):
        return None


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def load_data() -> dict[str, list[dict]]:
    data: dict[str, list[dict]] = {}
    # Files handled separately (non-list JSON)
    _skip = {
        "creek_gauge",
        "native_plants_spotlight",
        "plants_native_black_hills",
        "inaturalist_plant_cache",
        "ebird",
        "library_circulation",
        "bhnf_projects",
        "danr_public_notices",
        "danr_contested_cases",
        "planning_zoning",
        "building_permits",
        "roadkill",
        "danr_spills",
    }

    for json_file in sorted(DATA_DIR.glob("*.json")):
        slug = json_file.stem
        if slug in _skip:
            continue
        try:
            with json_file.open("r", encoding="utf-8") as fh:
                records = json.load(fh)
            if isinstance(records, list):
                data[slug] = records
            else:
                print(f"[build] Warning: {json_file.name} is not a list; skipping.")
        except (json.JSONDecodeError, OSError) as exc:
            print(f"[build] Warning: could not read {json_file.name}: {exc}")
    return data


def _parse_dt(value: str | None) -> date | None:
    """Parse any date/datetime string to a Mountain Time date, or return None."""
    dt = _to_mountain(value)
    return dt.date() if dt else None


def _sort_dt(record: dict) -> str:
    """Return a sortable ISO datetime string (normalized to Mountain Time)."""
    for field in ("start_dt", "date", "published", "updated"):
        val = record.get(field)
        if val:
            dt = _to_mountain(val)
            if dt:
                return dt.isoformat()
            return str(val)
    return ""


def group_records(data: dict[str, list[dict]]) -> dict[str, list[dict]]:
    """
    Flatten all source records, attach _source slug, and group by record_type.

    Events are filtered to only those on or after today, sorted ascending.
    All other groups are sorted descending (newest first).

    Returns a dict of record_type → list[dict].
    """
    groups: dict[str, list[dict]] = {}

    for slug, records in data.items():
        for record in records:
            enriched = {**record, "_source": slug}
            rtype = record.get("record_type", "other")
            groups.setdefault(rtype, []).append(enriched)

    # Events + school menus: future-only, ascending
    for rtype in ("event", "school_menu"):
        if rtype not in groups:
            continue
        future = []
        for r in groups[rtype]:
            dt = _parse_dt(r.get("start_dt") or r.get("date"))
            if dt is None or dt >= TODAY:
                future.append(r)
        future.sort(key=_sort_dt)
        groups[rtype] = future

    # Alerts: last 7 days
    if "alert" in groups:
        _alert_cutoff = TODAY - timedelta(days=7)
        groups["alert"] = [
            r
            for r in groups["alert"]
            if (dt := _parse_dt(r.get("published") or r.get("date"))) is None
            or (dt.date() if isinstance(dt, datetime) else dt) >= _alert_cutoff
        ]

    # Documents, news, press releases: last 30 days or future
    _CUTOFF = TODAY - timedelta(days=30)
    for rtype in ("document", "news", "press_release"):
        if rtype not in groups:
            continue
        groups[rtype] = [
            r
            for r in groups[rtype]
            if (dt := _parse_dt(r.get("date") or r.get("start_dt") or r.get("published"))) is None
            or (dt.date() if isinstance(dt, datetime) else dt) >= _CUTOFF
        ]

    # Everything else: descending
    for rtype, records in groups.items():
        if rtype not in ("event", "school_menu"):
            records.sort(key=_sort_dt, reverse=True)

    return groups


# ---------------------------------------------------------------------------
# Jinja2 environment
# ---------------------------------------------------------------------------


def make_env() -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
    )

    def format_date(value: str | None, fmt: str = "%B %-d, %Y") -> str:
        dt = _to_mountain(value)
        return dt.strftime(fmt) if dt else str(value or "")

    def format_datetime(value: str | None) -> str:
        """Return '6:30 PM' or '6 PM' (MT) — strips :00, empty for date-only or midnight."""
        if not value or _DATE_ONLY_RE.match(value):
            return ""
        dt = _to_mountain(value)
        if dt and (dt.hour or dt.minute):
            fmt = "%-I %p" if dt.minute == 0 else "%-I:%M %p"
            return dt.strftime(fmt)
        return ""

    def format_day(value: str | None) -> str:
        """Return 'Mon, Apr 7' (MT) from any date/datetime string."""
        dt = _to_mountain(value)
        return dt.strftime("%a, %b %-d") if dt else str(value or "")

    def is_today(value: str | None) -> bool:
        d = _parse_dt(value)
        return d == TODAY if d else False

    def is_this_week(value: str | None) -> bool:
        d = _parse_dt(value)
        if not d:
            return False
        delta = (d - TODAY).days
        return 0 <= delta <= 6

    def stable_id(value: str) -> str:
        """Return a short stable hex ID for a string (used as localStorage keys)."""
        import hashlib

        return hashlib.sha1(value.encode()).hexdigest()[:12]

    def intcomma(value) -> str:
        """Format an integer with thousands comma separators."""
        try:
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return str(value)

    env.filters["format_date"] = format_date
    env.filters["format_datetime"] = format_datetime
    env.filters["format_day"] = format_day
    env.filters["stable_id"] = stable_id
    env.filters["intcomma"] = intcomma
    env.tests["today"] = is_today
    env.tests["this_week"] = is_this_week
    return env


# ---------------------------------------------------------------------------
# Rendering helper
# ---------------------------------------------------------------------------


def render(env: Environment, template_name: str, dest: Path, **ctx) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    template = env.get_template(template_name)
    html = template.render(**ctx)
    dest.write_text(html, encoding="utf-8")
    print(f"[build] Wrote {dest.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Main build
# ---------------------------------------------------------------------------


def fetch_fire_danger() -> dict:
    """
    Fetch fire danger zone ratings from two sources:

    1. GPC SharePoint PDF ("Current Fire Danger") — 6 zones split into
       Black Hills (Northern/Central/Southern) and Prairie (Northern/Central/Southern).
       Publicly accessible via share link; playwright stealth bypasses Cloudflare.

    2. NWS Rangeland Fire Danger Statement (RFD) — free-text product from
       NWS Rapid City covering SD zones. We extract zone name + danger level.

    Returns:
        {
          "zones": [{"name": str, "area": str, "counties": str, "level": str}, ...],
          "nws_zones": [{"name": str, "level": str, "description": str}, ...],
          "nws_issued": str,   # e.g. "149 AM MDT Wed Apr 1 2026"
          "pdf_date": str,     # e.g. "Wednesday, April 1, 2026"
          "sharepoint_url": str,
        }
    """
    import re
    import subprocess
    import tempfile

    from playwright.sync_api import sync_playwright
    from playwright_stealth import Stealth

    SHAREPOINT_URL = (
        "https://firenet365.sharepoint.com/:b:/s/GPC_Internal/EcX4qKVYUyZPsNs1rmcGAREBrSWzZDEWMa1E-xa83UcBSw?e=JdYXPn"
    )
    DOWNLOAD_URL = (
        "https://firenet365.sharepoint.com/sites/GPC_Internal/_layouts/15/"
        "download.aspx?UniqueId=a5a8f8c5-5358-4f26-b0db-35ae67060111&Translate=false"
    )
    NWS_RFD_URL = (
        "https://forecast.weather.gov/product.php?site=UNR&issuedby=UNR&product=RFD&format=TXT&version=1&glossary=0"
    )

    zones: list[dict] = []
    pdf_date = ""

    # ── 1. GPC SharePoint PDF ────────────────────────────────────────────────
    try:
        with Stealth().use_sync(sync_playwright()) as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()
            page.goto(SHAREPOINT_URL, timeout=30000, wait_until="networkidle")
            page.wait_for_timeout(1500)
            response = context.request.get(DOWNLOAD_URL)
            if response.status == 200:
                pdf_bytes = response.body()
                with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                    tf.write(pdf_bytes)
                    tmp_path = tf.name
                result = subprocess.run(
                    ["pdftotext", "-layout", tmp_path, "-"],
                    capture_output=True,
                    text=True,
                )
                if result.returncode == 0:
                    text = result.stdout
                    # Extract date: "Wednesday, April 1, 2026"
                    date_m = re.search(
                        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
                        r",\s+\w+\s+\d+,\s+\d{4}",
                        text,
                    )
                    pdf_date = date_m.group(0) if date_m else ""

                    # Parse zone blocks — each zone is 3 lines:
                    #   Zone name\n(counties)\n\n   Level
                    # The PDF layout groups Black Hills (3 zones) and Prairie (3 zones).
                    # We extract named zones with their level using the level keyword
                    # as an anchor.
                    # The PDF uses a 3-column fixed-width layout per row:
                    #   col <80  = Black Hills level
                    #   col 80-170 = Prairie left-county level
                    #   col >170 = Prairie right-county level
                    # Three rows: Northern, Central, Southern.
                    level_re = re.compile(
                        r"\b(Extreme|Very High|High|Moderate|Low|No Data)\b",
                        re.IGNORECASE,
                    )
                    # Identify "level lines": lines whose non-space content is only
                    # danger-level keywords.
                    lines = text.splitlines()
                    level_lines = []
                    for line in lines:
                        stripped = level_re.sub("", line).strip()
                        if level_re.search(line) and stripped == "":
                            # Extract (col, level) pairs
                            row = [(m.start(), m.group(1).title()) for m in level_re.finditer(line)]
                            if row:
                                level_lines.append(row)
                    # We expect 3 data rows (Northern, Central, Southern).
                    # Drop any legend/example rows (those with only 1-2 values
                    # and short line length — legend rows have "No Data" etc.)
                    data_rows = [r for r in level_lines if len(r) == 3]

                    row_defs = [
                        # (bh_name, bh_counties, pr_left_name, pr_left_counties, pr_right_name, pr_right_counties)
                        ("Northern Hills", "Lawrence Co.", "Northern", "Lawrence Co.", "Northern", "Butte Co."),
                        ("Central Hills", "Pennington & Meade", "Central", "Pennington Co.", "Central", "Meade Co."),
                        (
                            "Southern Hills",
                            "Custer & Fall River",
                            "Southern",
                            "Custer Co.",
                            "Southern",
                            "Fall River Co.",
                        ),  # noqa: E501
                    ]
                    for i, row in enumerate(data_rows[:3]):
                        if i >= len(row_defs):
                            break
                        bh_name, bh_co, prl_name, prl_co, prr_name, prr_co = row_defs[i]
                        # Sort by column position
                        row_sorted = sorted(row, key=lambda x: x[0])
                        bh_level = row_sorted[0][1] if len(row_sorted) > 0 else "No Data"
                        prl_level = row_sorted[1][1] if len(row_sorted) > 1 else "No Data"
                        prr_level = row_sorted[2][1] if len(row_sorted) > 2 else "No Data"
                        zones.append({"name": bh_name, "area": "Black Hills", "counties": bh_co, "level": bh_level})
                        zones.append({"name": prl_name, "area": "Prairie", "counties": prl_co, "level": prl_level})
                        zones.append({"name": prr_name, "area": "Prairie", "counties": prr_co, "level": prr_level})
            browser.close()
    except Exception as exc:
        print(f"[build] Warning: could not fetch GPC fire danger PDF: {exc}")

    # ── 2. NWS Rangeland Fire Danger Statement ───────────────────────────────
    nws_zones: list[dict] = []
    nws_issued = ""
    try:
        import urllib.request
        from html.parser import HTMLParser

        class _PreExtractor(HTMLParser):
            def __init__(self):
                super().__init__()
                self._in = False
                self.text = []

            def handle_starttag(self, tag, attrs):
                if tag == "pre":
                    self._in = True

            def handle_endtag(self, tag):
                if tag == "pre":
                    self._in = False

            def handle_data(self, data):
                if self._in:
                    self.text.append(data)

        req = urllib.request.Request(NWS_RFD_URL, headers={"User-Agent": "SpearfishBulletin/1.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
        extractor = _PreExtractor()
        extractor.feed(raw)
        rfd_text = "".join(extractor.text)

        # Issued time: e.g. "149 AM MDT Wed Apr 1 2026"
        issued_m = re.search(r"\d{1,4} [AP]M [A-Z]{3} .+", rfd_text)
        nws_issued = issued_m.group(0).strip() if issued_m else ""

        # Split on "$$" separators into zone blocks
        blocks = re.split(r"\$\$", rfd_text)
        level_kw = re.compile(
            r"\.\.\.(LOW|MODERATE|HIGH|VERY HIGH|EXTREME)\s+FIRE\s+DANGER\.\.\.",
            re.IGNORECASE,
        )
        # Zone name line: the descriptive text after the SDZ code line
        # e.g. "Harding-Butte-Northern Meade Co Plains-..."
        for block in blocks:
            lm = level_kw.search(block)
            if not lm:
                continue
            level = lm.group(1).title()
            # Grab the description paragraph after the level header
            after = block[lm.end() :].strip()
            desc_lines = []
            for line in after.splitlines():
                line = line.strip()
                if not line or line.startswith("The outlook"):
                    break
                desc_lines.append(line)
            description = " ".join(desc_lines)
            # Get zone name from the line listing counties
            # It's the human-readable line between the SDZ code line and the date line
            # Zone name: the human-readable county list line (after SDZ codes,
            # before "Including the cities of" and before the date line).
            # It looks like: "Harding-Butte-Northern Meade Co Plains-..."
            name_lines = []
            past_sdz = False
            for line in block.splitlines():
                line = line.strip()
                if re.match(r"^SDZ\d", line):
                    past_sdz = True
                    continue
                if not past_sdz:
                    continue
                if re.match(r"^\d{3,4} [AP]M", line):
                    break
                if line.startswith("Including"):
                    break
                if line and not line.startswith("."):
                    name_lines.append(line)
            zone_name = " ".join(name_lines).strip().rstrip("-").strip() if name_lines else "SD Zone"
            nws_zones.append(
                {
                    "name": zone_name,
                    "level": level,
                    "description": description,
                }
            )
    except Exception as exc:
        print(f"[build] Warning: could not fetch NWS RFD: {exc}")

    print(f"[build] Fire danger: {len(zones)} GPC zones, {len(nws_zones)} NWS zones, pdf_date={pdf_date!r}")
    return {
        "zones": zones,
        "nws_zones": nws_zones,
        "nws_issued": nws_issued,
        "pdf_date": pdf_date,
        "sharepoint_url": SHAREPOINT_URL,
    }


def _fmt_acres(raw: str) -> str:
    """'1234 Acres' or '1,234 acres' → '1,234 acres'."""
    m = re.search(r"[\d,]+", raw)
    if not m:
        return raw
    num = int(m.group().replace(",", ""))
    unit = raw[m.end() :].strip() or "acres"
    return f"{num:,} {unit}"


def fetch_fire_data() -> dict:
    """
    Fetch fire restriction and wildfire data at build time.
    - All rows from blackhillsfirerestrictions.com (grouped by section)
    - Active wildfire incidents in South Dakota from InciWeb accessible view

    Restriction table columns (by position, matching the site's image header):
      0=campfires, 1=smoking, 2=charcoal, 3=gas_grills, 4=wood_stove, 5=welding, 6=fireworks

    Returns {"rows": [...], "incidents": [...], "source_url": str} or partial on failure.
    """
    import urllib.request

    from bs4 import BeautifulSoup

    BHNF_URL = "https://www.blackhillsfirerestrictions.com/"
    INCIWEB_URL = "https://inciweb.wildfire.gov/accessible-view"
    INCIWEB_BASE = "https://inciweb.wildfire.gov"
    HEADERS = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }

    def _get(url):
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read().decode("utf-8", errors="replace")

    rows: list[dict] = []
    try:
        html = _get(BHNF_URL)
        soup = BeautifulSoup(html, "html.parser")
        # The restriction data lives in the inner table with cellspacing="1"
        inner_table = soup.find("table", attrs={"cellpadding": "0", "cellspacing": "1"})
        if inner_table:
            current_section = ""
            for tr in inner_table.find_all("tr", recursive=False):
                # Subsection header: td with bgcolor="#fcf0c8"
                sub_td = tr.find("td", bgcolor="#fcf0c8")
                if sub_td:
                    current_section = sub_td.get_text(strip=True)
                    continue

                # Data row: must have exactly 7 td[width="35"] icon cells
                icon_cells = tr.find_all("td", attrs={"width": "35"})
                if len(icon_cells) != 7:
                    continue

                # Name: text of the first <td> (strip leading whitespace/nbsp)
                name_td = tr.find("td")
                if not name_td:
                    continue
                name = name_td.get_text(" ", strip=True).strip()

                # 7 restriction columns — True = restricted (non-blank gif)
                cols = []
                for cell in icon_cells:
                    img = cell.find("img")
                    src = str(img.get("src") or "") if img else ""
                    stem = src.split("/")[-1].replace(".gif", "")
                    cols.append(stem != "blank")

                # "More info" PDF link (optional)
                more_info_url = ""
                for a_tag in tr.find_all("a", href=True):
                    href_val = str(a_tag.get("href") or "")
                    if ".pdf" in href_val.lower():
                        more_info_url = href_val
                        break

                rows.append(
                    {
                        "name": name,
                        "section": current_section,
                        "cols": cols,
                        "any_restricted": any(cols),
                        "more_info_url": more_info_url,
                    }
                )
    except Exception as exc:
        print(f"[build] Warning: could not fetch fire restrictions: {exc}")

    incidents = []
    try:
        html = _get(INCIWEB_URL)
        soup = BeautifulSoup(html, "html.parser")
        table = soup.find("table", class_="usa-table")
        if table:
            for tr in table.select("tbody tr"):
                cells = tr.find_all("td")

                def _cls(tag) -> str:
                    return " ".join(tag.get("class") or [])

                state_td = next((c for c in cells if "views-field-field-state" in _cls(c)), None)
                if not state_td or "South Dakota" not in state_td.get_text():
                    continue
                title_td = next((c for c in cells if "views-field-title" in _cls(c)), None)
                type_td = next((c for c in cells if "views-field-field-incident-type" in _cls(c)), None)
                size_td = next((c for c in cells if "views-field-field-incident-size" in _cls(c)), None)
                updated_td = next((c for c in cells if "views-field-field-last-209-update" in _cls(c)), None)
                if not title_td:
                    continue
                a = title_td.find("a")
                name = a.get_text(strip=True) if a else title_td.get_text(strip=True)
                href = str(a.get("href") or "") if a else ""
                url = INCIWEB_BASE + href if href.startswith("/") else href
                incidents.append(
                    {
                        "name": name,
                        "type": type_td.get_text(strip=True) if type_td else "",
                        "size": _fmt_acres(size_td.get_text(strip=True) if size_td else ""),
                        "updated": updated_td.get_text(strip=True) if updated_td else "",
                        "url": url,
                    }
                )
    except Exception as exc:
        print(f"[build] Warning: could not fetch InciWeb data: {exc}")

    # ── Fire danger zones (GPC SharePoint PDF + NWS RFD) ────────────────────
    danger = fetch_fire_danger()

    return {"rows": rows, "incidents": incidents, "source_url": BHNF_URL, "danger": danger}


def load_plant_spotlight() -> dict:
    """Pick today's native plant spotlight deterministically from the curated list."""
    spotlight_file = DATA_DIR / "native_plants_spotlight.json"
    if not spotlight_file.exists():
        print("[build] Warning: data/native_plants_spotlight.json not found — plant widget will be empty")
        return {}
    try:
        plants = json.loads(spotlight_file.read_text(encoding="utf-8"))
        if not plants:
            return {}
        # Deterministic daily rotation: day-of-year mod len gives stable plant per day
        day_index = TODAY.timetuple().tm_yday
        plant = plants[day_index % len(plants)]
        print(
            f"[build] Plant spotlight: {plant.get('common_name')} ({plant.get('symbol')}) "
            f"— {len(plants)} in pool, index {day_index % len(plants)}"
        )

        # Merge iNaturalist enrichment if available
        inat_cache_file = DATA_DIR / "inaturalist_plant_cache.json"
        if inat_cache_file.exists():
            try:
                inat_cache = json.loads(inat_cache_file.read_text(encoding="utf-8"))
                inat = inat_cache.get(plant.get("symbol") or "")
                if inat:
                    plant["inat"] = inat
                    count = inat.get("nearby_obs_count", 0)
                    print(f"[build]   iNat: taxon={inat.get('taxon_id')}, nearby={count}")
            except Exception:
                pass

        return plant
    except Exception as exc:
        print(f"[build] Warning: could not load native_plants_spotlight.json: {exc}")
        return {}


def load_ebird() -> list[dict]:
    """Load recent eBird sightings from data/ebird.json."""
    ebird_file = DATA_DIR / "ebird.json"
    if not ebird_file.exists():
        return []
    try:
        data = json.loads(ebird_file.read_text(encoding="utf-8"))
        obs = data.get("observations") or []
        print(f"[build] eBird: {len(obs)} recent sightings")
        return obs
    except Exception as exc:
        print(f"[build] Warning: could not load ebird.json: {exc}")
        return []


def load_danr_notices() -> list[dict]:
    """Load DANR public notices."""
    path = DATA_DIR / "danr_public_notices.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[build] Warning: could not load danr_public_notices.json: {exc}")
        return []
    notices = raw.get("notices") or []

    # Mark whether each deadline is past (for display styling)
    today_str = TODAY.isoformat()
    for n in notices:
        d = n.get("deadline", "") or ""
        m = re.match(r"(\d{1,2})/(\d{1,2})/(\d{4})", d)
        if m:
            iso = f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}"
            n["deadline_past"] = iso < today_str
            n["deadline_iso"] = iso
        else:
            n["deadline_past"] = False
            n["deadline_iso"] = ""

    notices.sort(key=lambda n: n.get("deadline_iso") or "", reverse=True)
    print(f"[build] DANR notices: {len(notices)}")
    return notices


def load_danr_contested_cases() -> list[dict]:
    """Load DANR contested cases with their supporting documents."""
    path = DATA_DIR / "danr_contested_cases.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[build] Warning: could not load danr_contested_cases.json: {exc}")
        return []
    cases = raw.get("cases") or []
    print(f"[build] DANR contested cases: {len(cases)}")
    return cases


def load_danr_spills() -> dict:
    """Load DANR spill reports first seen within the past 30 days."""
    path = DATA_DIR / "danr_spills.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[build] Warning: could not load danr_spills.json: {exc}")
        return {}
    cutoff = (date.today() - timedelta(days=30)).isoformat()
    all_records = raw.get("new_records") or []
    records = [r for r in all_records if (r.get("first_seen") or "") >= cutoff]
    print(f"[build] DANR spills: {len(records)} record(s) in past 30 days (of {len(all_records)} total)")
    return {
        "records": records,
        "lookback_days": 30,
        "total_bh_sites": raw.get("total_bh_sites", 0),
    }


def load_bhnf_projects() -> list[dict]:
    """Load BHNF public projects, returning only in-progress ones with a past flag."""
    path = DATA_DIR / "bhnf_projects.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[build] Warning: could not load bhnf_projects.json: {exc}")
        return []

    today_str = TODAY.strftime("%Y-%m")  # YYYY-MM for month comparison

    projects = []
    for p in raw.get("projects") or []:
        if p.get("status") != "In Progress":
            continue
        # Mark whether the comment period date is in the past
        cs = p.get("comment_period_sort", "9999-99")
        p["comment_period_past"] = bool(cs and cs != "9999-99" and cs[:7] < today_str)
        projects.append(p)

    print(f"[build] BHNF projects: {len(projects)} in-progress")
    return projects


def load_circulation() -> dict:
    """Load library circulation data and pre-compute SVG chart paths."""
    circ_file = DATA_DIR / "library_circulation.json"
    if not circ_file.exists():
        return {}
    try:
        raw = json.loads(circ_file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[build] Warning: could not load library_circulation.json: {exc}")
        return {}

    rows = raw.get("rows", [])
    if not rows:
        return {}

    # Rows with physical loan data (for chart x-positions)
    chart_rows = [r for r in rows if r.get("loans") is not None]
    n = len(chart_rows)
    if n < 2:
        return {"rows": rows, "recent": list(reversed(rows[-24:])), "chart": None}

    # Y-axis max with 5% headroom
    max_val = (
        max((r.get("loans") or 0) + (r.get("overdrive_loans") or 0) + (r.get("hoopla_loans") or 0) for r in chart_rows)
        * 1.05
    )
    max_val = max(max_val, 1)

    CHART_W, CHART_H = 500, 160

    pts_phys: list[tuple[float, float]] = []
    pts_od: list[tuple[float, float]] = []
    pts_total: list[tuple[float, float]] = []

    for i, r in enumerate(chart_rows):
        x = round((i / (n - 1)) * CHART_W, 1)
        phys = r.get("loans") or 0
        od = r.get("overdrive_loans") or 0
        hoopla = r.get("hoopla_loans") or 0
        pts_phys.append((x, round(CHART_H - (phys / max_val) * CHART_H, 1)))
        pts_od.append((x, round(CHART_H - ((phys + od) / max_val) * CHART_H, 1)))
        pts_total.append((x, round(CHART_H - ((phys + od + hoopla) / max_val) * CHART_H, 1)))

    def area_path(top: list, bottom: list | None = None) -> str:
        if not top:
            return ""
        base = [(top[-1][0], CHART_H), (top[0][0], CHART_H)] if bottom is None else list(reversed(bottom))
        pts = top + base
        return "M " + " L ".join(f"{x},{y}" for x, y in pts) + " Z"

    has_od = any(r.get("overdrive_loans") for r in chart_rows)
    has_hoopla = any(r.get("hoopla_loans") for r in chart_rows)

    # Year tick marks (January of each year; label even years only)
    year_ticks = []
    seen_years: set[int] = set()
    for i, r in enumerate(chart_rows):
        yr = r["year"]
        if r["month"] == 1 and yr not in seen_years:
            seen_years.add(yr)
            x = round((i / (n - 1)) * CHART_W, 1)
            year_ticks.append({"x": x, "year": yr, "label": str(yr) if yr % 2 == 0 else ""})

    # Y-axis ticks at nice round numbers within the data range
    # Pick a step size that gives 3-4 ticks: try 2500, 5000
    step = 5000 if max_val > 12000 else 2500
    y_ticks = []
    tick_val = step
    while tick_val < max_val:
        y_px = round(CHART_H - (tick_val / max_val) * CHART_H, 1)
        y_ticks.append({"value": tick_val, "label": f"{tick_val // 1000}k", "y": y_px})
        tick_val += step

    # COVID annotation (April 2020)
    covid_x = None
    for i, r in enumerate(chart_rows):
        if r["year"] == 2020 and r["month"] == 4:
            covid_x = round((i / (n - 1)) * CHART_W, 1)
            break

    # All months for table (newest first), skip rows with no numeric data
    recent_rows = [r for r in rows if r.get("loans") is not None or r.get("overdrive_loans") is not None]
    recent = list(reversed(recent_rows))

    print(f"[build] Library circulation: {len(rows)} months, {n} chart points, {len(recent)} in table")

    return {
        "rows": rows,
        "recent": recent,
        "chart": {
            "width": CHART_W,
            "height": CHART_H,
            "path_phys": area_path(pts_phys),
            "path_od": area_path(pts_od, pts_phys) if has_od else "",
            "path_hoopla": area_path(pts_total, pts_od) if has_hoopla else "",
            "year_ticks": year_ticks,
            "y_ticks": y_ticks,
            "covid_x": covid_x,
        },
    }


def load_building_permits() -> dict:
    """Load building permit records and pre-compute SVG bar chart from data/building_permits.json."""
    path = DATA_DIR / "building_permits.json"
    if not path.exists():
        print("[build] Warning: data/building_permits.json not found — building permits widget will be empty")
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[build] Warning: could not load building_permits.json: {exc}")
        return {}

    records = raw.get("records") or []
    month_urls: dict[str, str] = raw.get("month_urls") or {}

    # Enrich each record with its source PDF URL
    archive_base = "https://www.cityofspearfish.com/Archive.aspx?AMID=37"
    for r in records:
        key = f"{r.get('year', '')}-{str(r.get('month', '')).zfill(2)}"
        r["source_url"] = month_urls.get(key, archive_base)

    # Stack order (bottom → top): demolition, mechanical, alterations, new_construction
    STACK_CATS = ["demolition", "mechanical", "alterations", "new_construction"]
    CAT_COLORS = {
        "new_construction": "#f97316",
        "alterations": "#14b8a6",
        "mechanical": "#16a34a",
        "demolition": "#dc2626",
    }

    # Per-year totals, broken down by category
    year_data: dict[str, dict] = {}
    for r in records:
        yr = str(r.get("year", ""))
        if not yr:
            continue
        if yr not in year_data:
            year_data[yr] = {"total": 0.0, "count": 0, "by_cat": {c: 0.0 for c in STACK_CATS}}
        cost = r.get("cost_approximate") or 0
        year_data[yr]["total"] += cost
        year_data[yr]["count"] += 1
        cat = r.get("category", "alterations")
        if cat in year_data[yr]["by_cat"]:
            year_data[yr]["by_cat"][cat] += cost
        else:
            year_data[yr]["by_cat"]["alterations"] += cost  # catch-all

    years_sorted = sorted(year_data.keys())

    # ── SVG stacked bar chart ─────────────────────────────────────────────────
    CHART_W, CHART_H = 480, 130
    PAD_L = 36  # left margin for y-axis labels
    PAD_B = 14  # bottom margin for year labels
    inner_h = CHART_H - PAD_B
    inner_w = CHART_W - PAD_L - 4

    chart: dict | None = None
    n = len(years_sorted)
    if n >= 2:
        totals = [year_data[yr]["total"] for yr in years_sorted]
        max_val = max(totals) * 1.05 if max(totals) > 0 else 1.0

        bar_slot = inner_w / n
        bar_w = max(3, int(bar_slot * 0.72))

        bars = []
        for i, yr in enumerate(years_sorted):
            d = year_data[yr]
            x = PAD_L + round(i * bar_slot + (bar_slot - bar_w) / 2)

            # Build stacked segments bottom-to-top
            segments = []
            cumulative = 0.0
            for cat in STACK_CATS:
                val = d["by_cat"].get(cat, 0.0)
                if val <= 0:
                    continue
                seg_h = max(1, round((val / max_val) * inner_h))
                seg_y = inner_h - round(((cumulative + val) / max_val) * inner_h)
                segments.append(
                    {
                        "category": cat,
                        "color": CAT_COLORS[cat],
                        "total": round(val),
                        "y": seg_y,
                        "h": seg_h,
                    }
                )
                cumulative += val

            bars.append(
                {
                    "year": yr,
                    "total": round(d["total"]),
                    "count": d["count"],
                    "x": x,
                    "w": bar_w,
                    "segments": segments,
                }
            )

        # Y-axis tick marks
        mv = max(totals)
        step = 50_000_000 if mv > 200_000_000 else 25_000_000 if mv > 75_000_000 else 10_000_000
        y_ticks = []
        v = step
        while v < max_val:
            y_px = round(inner_h - (v / max_val) * inner_h)
            y_ticks.append({"value": v, "label": f"${v // 1_000_000}M", "y": y_px})
            v += step

        chart = {
            "width": CHART_W,
            "height": CHART_H,
            "pad_left": PAD_L,
            "inner_h": inner_h,
            "bars": bars,
            "y_ticks": y_ticks,
            "cat_colors": CAT_COLORS,
        }

    # year_series for JS (used by hover tooltip) — include per-cat breakdown
    year_series = [
        {
            "year": yr,
            "total": round(year_data[yr]["total"]),
            "count": year_data[yr]["count"],
            "by_cat": {c: round(year_data[yr]["by_cat"].get(c, 0)) for c in STACK_CATS},
        }
        for yr in years_sorted
    ]

    print(f"[build] Building permits: {len(records)} records, {n} years, {len(month_urls)} source URLs")
    return {"records": records, "chart": chart, "year_series": year_series}


def load_roadkill() -> dict:
    """Load roadkill records from data/roadkill.json."""
    path = DATA_DIR / "roadkill.json"
    if not path.exists():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[build] Warning: could not load roadkill.json: {exc}")
        return {}
    records = raw.get("records") or []
    lookback = raw.get("lookback_days", 30)
    from collections import Counter

    species_counts = Counter(r["species"] for r in records).most_common()
    print(f"[build] Roadkill: {len(records)} pickups in last {lookback} days (BH bbox)")
    return {"records": records, "lookback_days": lookback, "species_counts": species_counts}


def load_planning_zoning() -> list[dict]:
    """Load planning and zoning records from data/planning_zoning.json."""
    path = DATA_DIR / "planning_zoning.json"
    if not path.exists():
        return []
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[build] Warning: could not load planning_zoning.json: {exc}")
        return []
    records = [r for r in (raw.get("records") or []) if r.get("record_no")]
    print(f"[build] Planning & zoning: {len(records)} record(s) (with permit numbers)")
    return records


def load_creek_data() -> dict:
    """Read creek gauge snapshot from data/creek_gauge.json (written by the creek-gauge scraper)."""
    creek_file = DATA_DIR / "creek_gauge.json"
    if not creek_file.exists():
        print("[build] Warning: data/creek_gauge.json not found — creek widget will be empty")
        return {}
    try:
        return json.loads(creek_file.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[build] Warning: could not read creek_gauge.json: {exc}")
        return {}


def build() -> None:
    build_date = NOW

    if OUTPUT_DIR.exists():
        shutil.rmtree(OUTPUT_DIR)
    OUTPUT_DIR.mkdir(parents=True)

    data = load_data()
    groups = group_records(data)

    source_count = len(data)
    total_records = sum(len(v) for v in groups.values())

    # Compile Tailwind before rendering so CSS can be inlined
    css_in = ROOT / "site" / "static" / "css" / "input.css"
    css_tmp = OUTPUT_DIR / "_tailwind.css"
    result = subprocess.run(
        [sys.executable, "-m", "pytailwindcss", "-i", str(css_in), "-o", str(css_tmp), "--minify"],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"[build] Tailwind error:\n{result.stderr}")
        raise SystemExit(1)
    inline_css = css_tmp.read_text(encoding="utf-8")
    css_tmp.unlink()
    print(f"[build] Compiled Tailwind CSS ({len(inline_css) // 1024} KB, inlining)")

    # Parallelize loading of independent data sources using ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {
            executor.submit(load_plant_spotlight): "plant_spotlight",
            executor.submit(load_ebird): "ebird_observations",
            executor.submit(load_danr_notices): "danr_notices",
            executor.submit(load_danr_contested_cases): "danr_contested_cases",
            executor.submit(load_bhnf_projects): "bhnf_projects",
            executor.submit(load_circulation): "library_circulation",
            executor.submit(load_creek_data): "creek_data",
            executor.submit(fetch_fire_data): "fire_data",
            executor.submit(load_planning_zoning): "planning_records",
            executor.submit(load_building_permits): "building_permits",
            executor.submit(load_roadkill): "roadkill",
            executor.submit(load_danr_spills): "danr_spills",
        }

        data_results = {}
        for future in as_completed(futures):
            key = futures[future]
            try:
                data_results[key] = future.result()
            except Exception as exc:
                print(f"[build] Error loading {key}: {exc}")
                data_results[key] = {} if key not in ("ebird_observations", "planning_records") else []
                if key == "building_permits":
                    data_results[key] = {}

    plant_spotlight = data_results.get("plant_spotlight", {})
    ebird_observations = data_results.get("ebird_observations", [])
    danr_notices = data_results.get("danr_notices", [])
    danr_contested_cases = data_results.get("danr_contested_cases", [])
    bhnf_projects = data_results.get("bhnf_projects", [])
    library_circulation = data_results.get("library_circulation", {})
    creek_data = data_results.get("creek_data", {})
    fire_data = data_results.get("fire_data", {})
    planning_records = data_results.get("planning_records", [])
    building_permits = data_results.get("building_permits", {})
    roadkill = data_results.get("roadkill", {})
    danr_spills = data_results.get("danr_spills", {})

    # Enrich building permit records with ViewpointCloud portal URLs where permit numbers match
    if planning_records and building_permits.get("records"):
        portal_by_record_no = {
            r["record_no"]: r["portal_url"] for r in planning_records if r.get("record_no") and r.get("portal_url")
        }  # noqa
        matched = 0
        for r in building_permits["records"]:
            pno = r.get("permit_number", "")
            if pno and pno in portal_by_record_no:
                r["portal_url"] = portal_by_record_no[pno]
                matched += 1
        if matched:
            print(f"[build] Matched {matched} building permits to ViewpointCloud portal URLs")

    fire_rows = fire_data.get("rows", [])
    print(
        f"[build] Creek gauge: {creek_data.get('current', {}).get('cfs', 'n/a')} cfs, "
        f"{len(creek_data.get('series7d', []))} IV points, "
        f"{len(creek_data.get('daily30', []))} daily values"
    )
    print(
        f"[build] Fire: {len(fire_rows)} restriction row(s), "
        f"{sum(1 for r in fire_rows if r.get('any_restricted'))} with restrictions, "
        f"{len(fire_data.get('incidents', []))} SD wildfire(s), "
        f"{len(fire_data.get('danger', {}).get('zones', []))} danger zones"
    )

    env = make_env()

    ctx = {
        "build_date": build_date,
        "today": TODAY.isoformat(),
        "groups": groups,
        "source_count": source_count,
        "total_records": total_records,
        "inline_css": inline_css,
        "fire": fire_data,
        "plant_spotlight": plant_spotlight,
        "ebird_observations": ebird_observations,
        "danr_notices": danr_notices,
        "danr_contested_cases": danr_contested_cases,
        "bhnf_projects": bhnf_projects,
        "library_circulation": library_circulation,
        "planning_records": planning_records,
        "building_permits": building_permits,
        "roadkill": roadkill,
        "danr_spills": danr_spills,
    }

    # Single-page dashboard
    render(env, "index.html", OUTPUT_DIR / "index.html", **ctx)

    # 404
    render(env, "404.html", OUTPUT_DIR / "404.html", **ctx)

    # Static assets
    if STATIC_DIR.exists():
        shutil.copytree(STATIC_DIR, OUTPUT_DIR / "static")
        print("[build] Copied static/ → _site/static/")

    # Creek gauge data — served as /data/creek_gauge.json for the JS widget
    creek_src = DATA_DIR / "creek_gauge.json"
    if creek_src.exists():
        data_out = OUTPUT_DIR / "data"
        data_out.mkdir(exist_ok=True)
        shutil.copy(creek_src, data_out / "creek_gauge.json")
        print("[build] Copied creek_gauge.json → _site/data/creek_gauge.json")

    (OUTPUT_DIR / ".nojekyll").touch()
    print("[build] Created _site/.nojekyll")

    print(f"\n[build] Done. {total_records} record(s) across {source_count} source(s).")
    for rtype, records in sorted(groups.items()):
        print(f"  {rtype}: {len(records)}")


if __name__ == "__main__":
    build()

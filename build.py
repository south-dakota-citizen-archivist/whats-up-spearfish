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
from datetime import date, datetime, timezone
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
TODAY = datetime.now(tz=MT).date()

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
        dt = dateutil_parser.parse(value)
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
    for json_file in sorted(DATA_DIR.glob("*.json")):
        slug = json_file.stem
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

    # Everything else: descending
    for rtype, records in groups.items():
        if rtype != "event":
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
        "https://firenet365.sharepoint.com/:b:/s/GPC_Internal/"
        "EcX4qKVYUyZPsNs1rmcGAREBrSWzZDEWMa1E-xa83UcBSw?e=JdYXPn"
    )
    DOWNLOAD_URL = (
        "https://firenet365.sharepoint.com/sites/GPC_Internal/_layouts/15/"
        "download.aspx?UniqueId=a5a8f8c5-5358-4f26-b0db-35ae67060111&Translate=false"
    )
    NWS_RFD_URL = (
        "https://forecast.weather.gov/product.php"
        "?site=UNR&issuedby=UNR&product=RFD&format=TXT&version=1&glossary=0"
    )

    DANGER_LEVELS = {"low", "moderate", "high", "very high", "extreme", "no data"}

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
                    capture_output=True, text=True,
                )
                if result.returncode == 0:
                    text = result.stdout
                    # Extract date: "Wednesday, April 1, 2026"
                    date_m = re.search(
                        r"(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)"
                        r",\s+\w+\s+\d+,\s+\d{4}", text
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
                            row = [(m.start(), m.group(1).title())
                                   for m in level_re.finditer(line)]
                            if row:
                                level_lines.append(row)
                    # We expect 3 data rows (Northern, Central, Southern).
                    # Drop any legend/example rows (those with only 1-2 values
                    # and short line length — legend rows have "No Data" etc.)
                    data_rows = [r for r in level_lines if len(r) == 3]

                    row_defs = [
                        # (bh_name, bh_counties, pr_left_name, pr_left_counties, pr_right_name, pr_right_counties)
                        ("Northern Hills", "Lawrence Co.", "Northern", "Lawrence Co.", "Northern", "Butte Co."),
                        ("Central Hills",  "Pennington & Meade", "Central", "Pennington Co.", "Central", "Meade Co."),
                        ("Southern Hills", "Custer & Fall River", "Southern", "Custer Co.", "Southern", "Fall River Co."),
                    ]
                    for i, row in enumerate(data_rows[:3]):
                        if i >= len(row_defs):
                            break
                        bh_name, bh_co, prl_name, prl_co, prr_name, prr_co = row_defs[i]
                        # Sort by column position
                        row_sorted = sorted(row, key=lambda x: x[0])
                        bh_level  = row_sorted[0][1] if len(row_sorted) > 0 else "No Data"
                        prl_level = row_sorted[1][1] if len(row_sorted) > 1 else "No Data"
                        prr_level = row_sorted[2][1] if len(row_sorted) > 2 else "No Data"
                        zones.append({"name": bh_name,  "area": "Black Hills", "counties": bh_co,  "level": bh_level})
                        zones.append({"name": prl_name, "area": "Prairie",     "counties": prl_co, "level": prl_level})
                        zones.append({"name": prr_name, "area": "Prairie",     "counties": prr_co, "level": prr_level})
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
                if tag == "pre": self._in = True
            def handle_endtag(self, tag):
                if tag == "pre": self._in = False
            def handle_data(self, data):
                if self._in: self.text.append(data)

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
            after = block[lm.end():].strip()
            desc_lines = []
            for line in after.splitlines():
                line = line.strip()
                if not line or line.startswith("The outlook"):
                    break
                desc_lines.append(line)
            description = " ".join(desc_lines)
            # Get zone name from the line listing counties
            # It's the human-readable line between the SDZ code line and the date line
            county_re = re.compile(r"^[A-Z][a-zA-Z\s/&\-]+-\s*$|^[A-Z][a-zA-Z\s/&\-]+Co\b", re.MULTILINE)
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
            nws_zones.append({
                "name": zone_name,
                "level": level,
                "description": description,
            })
    except Exception as exc:
        print(f"[build] Warning: could not fetch NWS RFD: {exc}")

    print(
        f"[build] Fire danger: {len(zones)} GPC zones, "
        f"{len(nws_zones)} NWS zones, pdf_date={pdf_date!r}"
    )
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
    unit = raw[m.end():].strip() or "acres"
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

                rows.append({
                    "name": name,
                    "section": current_section,
                    "cols": cols,
                    "any_restricted": any(cols),
                    "more_info_url": more_info_url,
                })
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

                state_td = next(
                    (c for c in cells if "views-field-field-state" in _cls(c)), None
                )
                if not state_td or "South Dakota" not in state_td.get_text():
                    continue
                title_td = next(
                    (c for c in cells if "views-field-title" in _cls(c)), None
                )
                type_td = next(
                    (c for c in cells if "views-field-field-incident-type" in _cls(c)), None
                )
                size_td = next(
                    (c for c in cells if "views-field-field-incident-size" in _cls(c)), None
                )
                updated_td = next(
                    (c for c in cells if "views-field-field-last-209-update" in _cls(c)), None
                )
                if not title_td:
                    continue
                a = title_td.find("a")
                name = a.get_text(strip=True) if a else title_td.get_text(strip=True)
                href = str(a.get("href") or "") if a else ""
                url = INCIWEB_BASE + href if href.startswith("/") else href
                incidents.append({
                    "name": name,
                    "type": type_td.get_text(strip=True) if type_td else "",
                    "size": _fmt_acres(size_td.get_text(strip=True) if size_td else ""),
                    "updated": updated_td.get_text(strip=True) if updated_td else "",
                    "url": url,
                })
    except Exception as exc:
        print(f"[build] Warning: could not fetch InciWeb data: {exc}")

    # ── Fire danger zones (GPC SharePoint PDF + NWS RFD) ────────────────────
    danger = fetch_fire_danger()

    return {"rows": rows, "incidents": incidents, "source_url": BHNF_URL, "danger": danger}


def fetch_creek_data() -> dict:
    """
    Fetch USGS stream gauge data for Spearfish Creek (site 06431500).
    Returns a dict with 'current', 'series7d', and 'daily30' keys,
    or an empty dict on failure.
    """
    import urllib.request

    HEADERS = {"User-Agent": "SpearfishBulletin/1.0"}

    def _get(url):
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read())

    try:
        iv = _get(
            "https://waterservices.usgs.gov/nwis/iv/"
            "?sites=06431500&parameterCd=00060,00065&period=P7D&format=json"
        )
        dv = _get(
            "https://waterservices.usgs.gov/nwis/dv/"
            "?sites=06431500&parameterCd=00060&period=P30D&format=json"
        )
    except Exception as exc:
        print(f"[build] Warning: could not fetch creek data: {exc}")
        return {}

    iv_ts = iv.get("value", {}).get("timeSeries", [])
    cfs_series = next((t for t in iv_ts if t["variable"]["variableCode"][0]["value"] == "00060"), None)
    ft_series  = next((t for t in iv_ts if t["variable"]["variableCode"][0]["value"] == "00065"), None)

    cfs_vals = [v for v in (cfs_series or {}).get("values", [{}])[0].get("value", []) if float(v["value"]) > -999]
    ft_vals  = [v for v in (ft_series  or {}).get("values", [{}])[0].get("value", []) if float(v["value"]) > -999]

    current = {}
    if cfs_vals:
        last = cfs_vals[-1]
        current = {
            "cfs":  round(float(last["value"])),
            "ft":   round(float(ft_vals[-1]["value"]), 2) if ft_vals else None,
            "time": last["dateTime"],
        }

    # Downsample to ~hourly (15-min data → every 4th point)
    series7d = [
        {"t": v["dateTime"], "cfs": round(float(v["value"]))}
        for v in cfs_vals[::4]
    ]

    dv_vals = (dv.get("value", {}).get("timeSeries") or [{}])[0].get("values", [{}])[0].get("value", [])
    daily30 = [
        {"date": v["dateTime"][:10], "cfs": round(float(v["value"]))}
        for v in reversed(dv_vals)
        if float(v["value"]) > -999
    ]

    return {"current": current, "series7d": series7d, "daily30": daily30}


def build() -> None:
    build_date = date.today()

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
        [sys.executable, "-m", "pytailwindcss",
         "-i", str(css_in), "-o", str(css_tmp), "--minify"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"[build] Tailwind error:\n{result.stderr}")
        raise SystemExit(1)
    inline_css = css_tmp.read_text(encoding="utf-8")
    css_tmp.unlink()
    print(f"[build] Compiled Tailwind CSS ({len(inline_css) // 1024} KB, inlining)")

    creek_data = fetch_creek_data()
    print(f"[build] Creek gauge: {creek_data.get('current', {}).get('cfs', 'n/a')} cfs, "
          f"{len(creek_data.get('series7d', []))} IV points, "
          f"{len(creek_data.get('daily30', []))} daily values")

    fire_data = fetch_fire_data()
    fire_rows = fire_data.get("rows", [])
    print(f"[build] Fire: {len(fire_rows)} restriction row(s), "
          f"{sum(1 for r in fire_rows if r.get('any_restricted'))} with restrictions, "
          f"{len(fire_data.get('incidents', []))} SD wildfire(s), "
          f"{len(fire_data.get('danger', {}).get('zones', []))} danger zones")

    env = make_env()

    ctx = {
        "build_date": build_date,
        "today": TODAY.isoformat(),
        "groups": groups,
        "source_count": source_count,
        "total_records": total_records,
        "inline_css": inline_css,
        "creek": creek_data,
        "fire": fire_data,
    }

    # Single-page dashboard
    render(env, "index.html", OUTPUT_DIR / "index.html", **ctx)

    # 404
    render(env, "404.html", OUTPUT_DIR / "404.html", **ctx)

    # Static assets
    if STATIC_DIR.exists():
        shutil.copytree(STATIC_DIR, OUTPUT_DIR / "static")
        print("[build] Copied static/ → _site/static/")

    (OUTPUT_DIR / ".nojekyll").touch()
    print("[build] Created _site/.nojekyll")

    print(f"\n[build] Done. {total_records} record(s) across {source_count} source(s).")
    for rtype, records in sorted(groups.items()):
        print(f"  {rtype}: {len(records)}")


if __name__ == "__main__":
    build()

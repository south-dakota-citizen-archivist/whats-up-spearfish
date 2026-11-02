"""
scripts/backfill_planning_commission.py

One-time backfill of Planning Commission applications from 2016 to July 2025,
before CivicClerk itemized its agendas, into planning_commission.json.

Each meeting's agenda PDF (or, without one, the first pages of its packet) lists
applications in labeled blocks: Request / Applicant / Location / Action. A few
2016 "agendas" are only a cover page linking to the real agenda on the city's old
AgendaCenter, which still answers at spearfish.gov; those links are followed.

As a check, each agenda's count of "Request:" labels must equal the number of
blocks read; meetings where they differ are listed for a look.

    uv run python -m scripts.backfill_planning_commission [--cache DIR]

Itemized records (August 2025 on) are left as they are.
"""

from __future__ import annotations

import argparse
import io
import logging
import re
from pathlib import Path

from scrapers import geo, net
from scrapers.sources import planning_commission as pc

_REQUEST_LABEL = re.compile(r"^[^\w\n]*(?:\d+\.\s*)?REQUEST\b[^:\n]{0,20}:", re.I | re.M)
_OLD_AGENDA_CENTER = re.compile(r"^https?://[^/]*spearfish[^/]*/AgendaCenter/ViewFile/", re.I)
PACKET_PAGES = 10  # a packet without a separate agenda starts with it


def _download(url: str, cache: Path | None, name: str, **kw) -> bytes:
    path = cache / name if cache else None
    if path and path.exists():
        return path.read_bytes()
    resp = net.get(url, timeout=120, **kw)
    resp.raise_for_status()
    if path:
        path.write_bytes(resp.content)
    return resp.content


# The agenda ends with adjournment or the accessibility notice; staff reports bound in after
# it repeat the labels in a table layout that reads as garbled extra items.
_AGENDA_END = re.compile(r"adjourn|auxiliary aids", re.I)


def pdf_text(content: bytes, pages: int | None = None) -> tuple[str, list[str]]:
    """Layout-preserving text of a PDF's agenda pages, and their link targets."""
    import pdfplumber

    with pdfplumber.open(io.BytesIO(content)) as pdf:
        texts, links = [], []
        for page in pdf.pages[:pages] if pages else pdf.pages:
            texts.append(page.extract_text(layout=True) or "")
            links += [h["uri"] for h in page.hyperlinks if h.get("uri")]
            if _AGENDA_END.search(texts[-1]):
                break
    return "\n".join(texts), links


def meeting_text(event: dict, cache: Path | None) -> str:
    files = {f.get("type"): f["fileId"] for f in event.get("publishedFiles") or []}
    file_id, pages = (files["Agenda"], None) if "Agenda" in files else (files.get("Agenda Packet"), PACKET_PAGES)
    if not file_id:
        return ""
    content = _download(
        f"{pc.API}/Meetings/GetMeetingFileStream(fileId={file_id},plainText=false)",
        cache,
        f"{event['id']}-{file_id}.pdf",
        headers=pc.HEADERS,
    )
    text, links = pdf_text(content, pages)
    if not _REQUEST_LABEL.search(text):
        # a cover page: the agenda itself is linked on the old AgendaCenter
        for i, link in enumerate(u for u in links if _OLD_AGENDA_CENTER.match(u)):
            url = re.sub(r"^https?://[^/]+", "https://www.spearfish.gov", link)
            try:
                text += "\n" + pdf_text(_download(url, cache, f"{event['id']}-linked-{i}.pdf"))[0]
            except Exception as exc:  # noqa: BLE001
                print(f"  {event['startDateTime'][:10]}: couldn't read linked {url}: {exc}")
    return text


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scripts.backfill_planning_commission")
    ap.add_argument("--cache", type=Path, help="keep downloaded PDFs here (re-runs skip the downloads)")
    ap.add_argument("--since", default="2016-01-01")
    args = ap.parse_args(argv)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)  # font warnings from old PDFs
    if args.cache:
        args.cache.mkdir(parents=True, exist_ok=True)

    scraper = pc.PlanningCommission()
    scraper.since = args.since
    events = [e for e in scraper.events() if e["startDateTime"][:10] < pc.FIRST_ITEMIZED]
    print(f"[backfill] {len(events)} meetings from {args.since} to {pc.FIRST_ITEMIZED}")

    records, seen, flagged = [], set(), []
    for event in events:
        day = event["startDateTime"][:10]
        try:
            text = meeting_text(event, args.cache)
        except Exception as exc:  # noqa: BLE001
            flagged.append(f"{day} (event {event['id']}): couldn't read the agenda: {exc}")
            continue
        blocks = pc.parse_agenda_text(text)
        labels = len(_REQUEST_LABEL.findall(text))
        if labels != len(blocks):
            flagged.append(f"{day} (event {event['id']}): {labels} Request labels, {len(blocks)} read")
        for n, block in enumerate(blocks, 1):
            rec = pc.agenda_block_record(block, n, event)
            # the same agenda is sometimes posted twice (revised, or as a packet too)
            key = (day, pc._norm(rec["request"])[:60], pc._norm(rec["location"])[:30])
            if key in seen or (rec["app_type"] == "Other" and not (rec["location"] or rec["address"])):
                continue
            seen.add(key)
            records.append(rec)

    coords = geo.geocode(r["address"] for r in records if r["address"])
    for r in records:
        if c := coords.get(r["address_key"]):
            r["lat"], r["lon"] = c

    fresh, dropped = scraper.normalize(records)
    for r in fresh:
        r["_first_seen"] = r["meeting_date"][:10]  # not "new": these are history
    existing = [r for r in scraper.load_existing() if not r.get("from_agenda_pdf")]
    merged = {r["item_id"]: r for r in fresh} | {r["item_id"]: r for r in existing}
    out = sorted(merged.values(), key=lambda r: r.get("meeting_date", ""))
    scraper.save(out)

    print(f"[backfill] {len(fresh)} applications from agendas ({dropped} invalid); {len(out)} records in all")
    print(f"[backfill] mapped: {sum(1 for r in fresh if r.get('lat'))} of {sum(1 for r in fresh if r['site'])}")
    for f in flagged:
        print(f"  check: {f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

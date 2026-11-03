"""
scripts/minutes_outcomes.py

What the Planning Commission did with each application on its agendas, read
from that meeting's minutes by a local language model (LM Studio or Ollama, both
of which serve the OpenAI chat API), one application at a time.

The model answers in a fixed shape (outcome, vote, conditions) and must copy the
deciding motion word for word into `quote`. Code then checks the answer before
keeping it:

  - the quote really is in the minutes (ignoring line breaks, curly quotes and
    words split across lines)
  - it's a motion ("moved", "motion", "seconded"), unless the item had no vote
  - its wording fits the outcome ("approved" needs "approv…", "tabled" needs
    "table", a motion that died or failed isn't an approval…)

Answers that fail stay out of the data and are listed for a look.

Minutes PDFs and the model's answers are cached in .cache/planning/ (git-ignored),
so an interrupted run picks up where it stopped.

    # score a model on the hand-labeled sample
    uv run python -m scripts.minutes_outcomes --model qwen/qwen3.5-9b --eval scripts/minutes_gold.json
    # every application with minutes, merged into $WUS_DATA_DIR/planning_commission.json
    uv run python -m scripts.minutes_outcomes --model qwen/qwen3.5-9b --write
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from difflib import SequenceMatcher
from pathlib import Path

from scrapers import base, net
from scrapers.sources import planning_commission as pc

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "planning"
PROMPT_VERSION = 2

OUTCOMES = [
    "approved",
    "recommended approval",
    "recommended denial",
    "denied",
    "motion failed",
    "tabled",
    "postponed",
    "public hearing set",
    "forwarded without a recommendation",
    "discussed, no vote",
    "withdrawn",
    "not in these minutes",
]
NO_MOTION = {"discussed, no vote", "withdrawn", "not in these minutes"}

SCHEMA = {
    "type": "object",
    "properties": {
        "outcome": {"type": "string", "enum": OUTCOMES},
        "vote": {"type": "string", "maxLength": 12, "pattern": "^(|unanimous|[0-9]{1,2}-[0-9]{1,2})$"},
        "conditions": {"type": "string", "maxLength": 300},
        "quote": {"type": "string", "maxLength": 700},
    },
    "required": ["outcome", "vote", "conditions", "quote"],
    "additionalProperties": False,
}

SYSTEM = (
    "You read the minutes of the Spearfish, South Dakota, Planning Commission and report what the commission "
    "did with one agenda item. Answer only from the minutes."
)
QUESTION = """Minutes of the {date} meeting:
<minutes>
{minutes}
</minutes>

Agenda item{number}:
Request: {request}
Applicant: {applicant}
Location: {location}

What did the commission do on this agenda item?
- If several motions were made on it, report the last one that passed; if none passed, the last one voted on.
  A motion amended before the vote counts as amended (a motion to deny, amended to table, was a tabling).
- "recommended …" is for a recommendation to the City Council; "approved"/"denied" for the commission's own decision.
- "public hearing set" is for a motion that only sets a hearing date.
- Fields:
  outcome: one of the listed choices.
  vote: only the tally, like "5-0" or "unanimous"; empty if the minutes don't say.
  conditions: any conditions or stipulations attached, in a few words; empty if none.
  quote: the deciding motion and the sentence saying how the vote went, copied word for word from the minutes.
- If the minutes don't mention this item, answer "not in these minutes" with an empty quote."""


# ── minutes ──────────────────────────────────────────────────────────────────


def minutes_files() -> dict[str, int]:
    """Event id → the file id of its posted minutes, for every Planning Commission meeting."""
    scraper = pc.PlanningCommission()
    scraper.since = "2016-01-01"
    out = {}
    for e in scraper.events():
        for f in e.get("publishedFiles") or []:
            if f.get("type") == "Minutes":
                out[str(e["id"])] = f["fileId"]
    return out


def minutes_text(event_id: str, file_id: int) -> str:
    import pdfplumber

    pdf_path = CACHE / f"minutes-{event_id}-{file_id}.pdf"
    if not pdf_path.exists():
        resp = net.get(
            f"{pc.API}/Meetings/GetMeetingFileStream(fileId={file_id},plainText=false)", headers=pc.HEADERS, timeout=120
        )
        resp.raise_for_status()
        pdf_path.write_bytes(resp.content)
    with pdfplumber.open(pdf_path) as pdf:
        text = "\n".join(p.extract_text() or "" for p in pdf.pages)
    # running page footers ("Page 1 of 3 1/15/2016 2:45 PM") break sentences apart
    text = re.sub(r"Page \d+ of \d+(\s+\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M)?", " ", text)
    return text


# ── checking an answer ───────────────────────────────────────────────────────


def norm(text: str) -> str:
    text = (text or "").replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = re.sub(r"[–—]", "-", text)
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)  # a word split across lines
    return " ".join(text.split()).lower()


def in_minutes(quote: str, minutes: str) -> bool:
    """The quote appears in the minutes: exactly once normalized, or nearly (a stray character or two).
    Quotation marks around it are ignored, and a quote shortened with "…" must match piece by piece."""
    q, m = re.sub(r"[\"'}\]*/\\n\s]+$", "", norm(quote)).strip(" \"'"), norm(minutes)
    pieces = [p.strip(" \"'") for p in re.split(r"\.\.\.|\u2026", q)]
    if len(pieces) > 1:
        return all(in_minutes(p, minutes) for p in pieces if len(p) >= 20) and any(len(p) >= 20 for p in pieces)
    if not q:
        return False
    if q in m:
        return True
    # near match: the best window of the same length, from the quote's first few words
    for start in [i.start() for i in re.finditer(re.escape(q[:25]), m)] or []:
        if SequenceMatcher(None, q, m[start : start + len(q) + 10]).ratio() >= 0.95:
            return True
    return False


_FITS = {
    "approved": r"approv",
    "recommended approval": r"approv|recommend",
    "recommended denial": r"den(y|ial)",
    "denied": r"den(y|ied|ial)",
    "motion failed": r"fail|died|lack of a second|nay|opposed",
    "tabled": r"\btabl",
    "postponed": r"postpon|continu|defer|delay",
    "public hearing set": r"hearing",
    "forwarded without a recommendation": r"(no|without( a)?) recommendation",
}
_DID_NOT_PASS = re.compile(r"died|lack of a second|\bfailed\b", re.I)
# the quote has to show the motion passed, not just that it was made
_PASSED = re.compile(
    r"\bpassed\b|\bcarried\b|all (present )?voted|unanimous|voted (aye|in favor)|\b\d{1,2}-\d{1,2}\b", re.I
)
_AMENDED_TO = re.compile(r"amended (the|his|her|their)? ?motion to (table|postpone|continue|defer)", re.I)


# What a motion did, from its own wording; when a quote holds several motions, the latest one decides.
_WORDING = [
    ("forwarded without a recommendation", r"(no|without( a)?) recommendation"),
    ("recommended denial", r"recommend\w*\s+(the\s+)?denial|recommend\w*\s+(that\s+.{0,40})?den(y|ial)\w*"),
    ("recommended approval", r"recommend\w*\s+(\w+\s+){0,3}approv\w*"),
    ("tabled", r"\btabl(e|ed|ing)\b"),
    ("postponed", r"\b(continu\w*|postpon\w*|defer\w*)\b"),
    ("public hearing set", r"\bset\w*\s+(\w+\s+){0,3}(public\s+)?hearing"),
    ("denied", r"\bden(y|ied|ial)\b"),
    ("approved", r"\bapprov\w*"),
]


def outcome_from_wording(quote: str) -> str:
    """The outcome a quoted motion's own words state (the model only has to find the right motion)."""
    if _AMENDED_TO.search(quote):
        return "tabled" if re.search(r"tabl", _AMENDED_TO.search(quote).group(0), re.I) else "postponed"
    q = re.sub(
        r"\bapproval of (the )?minutes\b|\b(motion )?on the table\b|\b(previously|already) approved\b",
        "",
        quote,
        flags=re.I,
    )
    spans: list[tuple[int, int, str]] = []
    for name, pattern in _WORDING:
        for m in re.finditer(pattern, q, re.I):
            # a match inside an earlier (more specific) pattern's span is part of that phrase:
            # the "approval" in "recommend approval"
            if not any(a <= m.start() and m.end() <= b for a, b, _ in spans):
                spans.append((m.start(), m.end(), name))
    which = max(spans)[2] if spans else ""
    # "recommend approval of a variance and set the Board of Adjustment hearing": the recommendation is the outcome
    names = {name for _, _, name in spans}
    if which == "public hearing set" and names & {"recommended approval", "recommended denial"}:
        which = max(sp for sp in spans if sp[2] in ("recommended approval", "recommended denial"))[2]
    if which and _DID_NOT_PASS.search(q) and not re.search(r"passed|carried|all (present )?voted", q, re.I):
        return "motion failed"
    return which


def vote_from_quote(quote: str) -> str:
    """The tally the quote states ("4-1"), or "unanimous" when everyone voted for it; never the model's guess."""
    if m := re.search(r"\b(\d{1,2})\s?-\s?(\d{1,2})\b", quote):
        return f"{m.group(1)}-{m.group(2)}"
    if re.search(r"unanimous|all (present )?voted|all voted in favor", quote, re.I):
        return "unanimous"
    return ""


def settle(answer: dict) -> dict:
    """The model finds and quotes the deciding motion; the outcome and the vote are what that quote says."""
    if answer.get("outcome") in NO_MOTION:
        return answer
    quote = answer.get("quote", "")
    return answer | {"outcome": outcome_from_wording(quote) or answer.get("outcome"), "vote": vote_from_quote(quote)}


_STOP = set(
    """approve approval request hearing public city spearfish council commission planning lots block
tract section with from that this their there which within located location applicant action make
recommendation recommend consider plat final preliminary sketch zoning change district""".split()
)
_HEADING = re.compile(r"(?:^|\s)\d{1,2}\.\s+(?:request:?\s*)?(?=[a-z])")


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]{4,}", norm(text)) if w not in _STOP}


def belongs(rec: dict, siblings: list[dict], quote: str, minutes: str) -> str:
    """Why the quote may be about another item at the same meeting, or "" if it's this one's.

    The part of the minutes from the nearest numbered heading before the quote down to the quote has to
    share more of this item's words (request, location, applicant) than any other item's of that meeting."""
    m, q = norm(minutes), norm(quote).strip(" \"'")
    pos = m.find(q[:60])
    if pos < 0:
        return "can't tell which item the quote is under"
    heads = [h.start() for h in _HEADING.finditer(m, 0, pos)]
    section = _words(m[heads[-1] if heads else 0 : pos + len(q)])

    def score(r):
        w = _words(" ".join(r.get(k) or "" for k in ("request", "agenda_text", "location", "applicant")))
        return len(w & section) / max(len(w), 1)

    mine = score(rec)
    others = [score(r) for r in siblings if r is not rec and r.get("item_id") != rec.get("item_id")]
    if others and max(others) > mine:
        return "quote seems to be about another item at that meeting"
    return ""


def check(answer: dict, minutes: str) -> str:
    """Why an answer can't be trusted, or "" if it holds up."""
    outcome, quote = answer.get("outcome"), answer.get("quote", "")
    if outcome not in OUTCOMES:
        return f"unknown outcome {outcome!r}"
    if outcome in NO_MOTION:
        return "" if not quote or in_minutes(quote, minutes) else "quote isn't in the minutes"
    if not in_minutes(quote, minutes):
        return "quote isn't in the minutes"
    if not re.search(r"\bmov(ed|es|e)\b|\bmotion\b|second", quote, re.I):
        return "quote isn't a motion"
    if re.search(r"\bminutes of\b|approve the (agenda|minutes)|\badjourn", quote, re.I):
        return "quote is about the minutes or agenda, not an item"
    if not re.search(_FITS[outcome], quote, re.I):
        return f"quote doesn't say {outcome!r}"
    if outcome != "motion failed" and _DID_NOT_PASS.search(quote) and not re.search(r"passed|carried", quote, re.I):
        return "quote says the motion didn't pass"
    if outcome != "motion failed" and not _PASSED.search(quote):
        return "quote doesn't show the motion passed"
    if outcome != "forwarded without a recommendation" and re.search(r"(no|without( a)?) recommendation", quote, re.I):
        return "quote says it went on without a recommendation"
    if outcome not in ("tabled", "postponed") and _AMENDED_TO.search(quote):
        return "quote says the motion was amended to table or postpone it"
    return ""


# ── asking the model ─────────────────────────────────────────────────────────


def ask(endpoint: str, model: str, minutes: str, rec: dict) -> dict:
    n = re.fullmatch(r"\d+-(\d+)", str(rec.get("item_id", "")))  # backfilled items: "{event}-{position}"
    question = QUESTION.format(
        number=f" (item {n.group(1)} on the agenda)" if n else "",
        date=rec["meeting_date"][:10],
        minutes=minutes.strip(),
        request=rec.get("request") or rec.get("agenda_text", ""),
        applicant=rec.get("applicant") or "(not given)",
        location=rec.get("location") or rec.get("address") or "(not given)",
    )
    resp = net.post(
        f"{endpoint}/chat/completions",
        json={
            "model": model,
            "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": question}],
            "temperature": 0,
            "max_tokens": 600,
            "reasoning_effort": "none",  # thinking models otherwise answer in their reasoning, not the reply
            "response_format": {"type": "json_schema", "json_schema": {"name": "outcome", "schema": SCHEMA}},
        },
        timeout=600,
    )
    resp.raise_for_status()
    content = resp.json()["choices"][0]["message"]["content"] or ""
    content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
    return json.loads(content)


def ask_twice(endpoint: str, model: str, minutes: str, rec: dict) -> dict:
    """Small models sometimes break their JSON; one more try usually fixes it."""
    try:
        return ask(endpoint, model, minutes, rec)
    except json.JSONDecodeError:
        return ask(endpoint, model, minutes, rec)


def answers_file(model: str) -> Path:
    return CACHE / f"answers-{re.sub(r'[^a-z0-9.]+', '-', model.lower())}-v{PROMPT_VERSION}.jsonl"


def load_answers(model: str) -> dict:
    path = answers_file(model)
    if not path.exists():
        return {}
    return {a["item_id"]: a for a in map(json.loads, path.read_text().splitlines()) if a.get("item_id")}


# ── run ──────────────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scripts.minutes_outcomes")
    ap.add_argument("--model", default="qwen/qwen3.5-9b")
    ap.add_argument(
        "--endpoint", default="http://localhost:1234/v1", help="LM Studio; Ollama: http://localhost:11434/v1"
    )
    ap.add_argument("--eval", type=Path, help="hand-labeled answers to score against (only those items are asked)")
    ap.add_argument("--limit", type=int, help="ask at most this many new questions")
    ap.add_argument("--download-only", action="store_true", help="fetch the minutes PDFs and stop")
    ap.add_argument("--write", action="store_true", help="merge checked outcomes into planning_commission.json")
    args = ap.parse_args(argv)
    logging.getLogger("pdfminer").setLevel(logging.ERROR)
    CACHE.mkdir(parents=True, exist_ok=True)

    scraper = pc.PlanningCommission()
    records = [r for r in scraper.load_existing() if r.get("event_id")]
    files = minutes_files()
    gold = json.loads(args.eval.read_text()) if args.eval else None
    todo = [r for r in records if str(r["event_id"]) in files and (gold is None or str(r["item_id"]) in gold)]
    print(f"[outcomes] {len(todo)} applications with minutes (of {len(records)})")
    by_event: dict[str, list[dict]] = {}
    for r in records:
        by_event.setdefault(str(r["event_id"]), []).append(r)

    texts: dict[str, str] = {}
    for r in todo:
        eid = str(r["event_id"])
        if eid not in texts:
            texts[eid] = minutes_text(eid, files[eid])
    if args.download_only:
        print(f"[outcomes] minutes for {len(texts)} meetings cached in {CACHE}")
        return 0

    answers = load_answers(args.model)
    asked = 0
    with answers_file(args.model).open("a") as out:
        for r in todo:
            key = str(r["item_id"])
            if key in answers:
                continue
            if args.limit is not None and asked >= args.limit:
                break
            t0 = time.time()
            try:
                a = ask_twice(args.endpoint, args.model, texts[str(r["event_id"])], r)
            except Exception as exc:  # noqa: BLE001
                print(f"  {key}: no answer ({exc})")
                continue
            a = settle(a)
            problem = (
                check(a, texts[str(r["event_id"])])
                or (
                    a["outcome"] not in NO_MOTION
                    and belongs(r, by_event[str(r["event_id"])], a["quote"], texts[str(r["event_id"])])
                )
                or ""
            )
            a = {"item_id": key, **a, "problem": problem, "seconds": round(time.time() - t0)}
            answers[key] = a
            out.write(json.dumps(a) + "\n")
            out.flush()
            asked += 1
            print(f"  {key} {r['meeting_date'][:10]} {a['outcome']}{' — ' + a['problem'] if a['problem'] else ''}")

    # checks are re-run on cached answers, so a better check doesn't need the model again
    done = []
    for r in todo:
        if a := answers.get(str(r["item_id"])):
            a = settle(a)
            minutes = texts[str(r["event_id"])]
            problem = check(a, minutes) or (
                a["outcome"] not in NO_MOTION and belongs(r, by_event[str(r["event_id"])], a["quote"], minutes)
            )
            done.append(a | {"problem": problem or ""})
    trusted = [a for a in done if not a["problem"]]
    print(f"[outcomes] {len(done)} answered, {len(trusted)} checked out, {len(done) - len(trusted)} set aside")

    if gold is not None:

        def simple(o):  # labels made before conditions moved to their own field
            return o.replace(" with conditions", "")

        def ok(a, lenient=False):
            g = gold[a["item_id"]]
            also = {simple(x) for x in g.get("also", [])}
            return a["outcome"] == simple(g["outcome"]) or (lenient and a["outcome"] in also)

        strict = sum(1 for a in trusted if ok(a))
        lenient = sum(1 for a in trusted if ok(a, True))
        print(
            f"[eval] {len(gold)} labeled: kept {len(trusted)}, of which right {strict} (strict) / {lenient} "
            f"(lenient); set aside {len(done) - len(trusted)}; unanswered {len(gold) - len(done)}"
        )
        for a in done:
            if not ok(a, True) or a["problem"]:
                tag = "set aside" if a["problem"] else "WRONG, kept"
                print(
                    f"  {tag} {a['item_id']}: said {a['outcome']!r}, label {gold[a['item_id']]['outcome']!r}"
                    f"{' — ' + a['problem'] if a['problem'] else ''}"
                )

    if args.write:
        by_id = {a["item_id"]: a for a in trusted if a["outcome"] != "not in these minutes"}
        out_records = []
        for r in scraper.load_existing():
            a = by_id.get(str(r.get("item_id")))
            if a:
                r |= {
                    "outcome": a["outcome"],
                    "outcome_vote": a["vote"],
                    "outcome_conditions": a["conditions"],
                    "outcome_quote": " ".join(a["quote"].split()),
                }
            out_records.append(r)
        scraper.save(out_records)
        print(f"[outcomes] wrote {len(by_id)} outcomes to {base.DATA_DIR / 'planning_commission.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

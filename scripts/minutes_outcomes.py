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
PROMPT_VERSION = 1

OUTCOMES = [
    "approved",
    "approved with conditions",
    "recommended approval",
    "recommended approval with conditions",
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
        "vote": {"type": "string", "description": "e.g. 5-0, 4-1, unanimous; empty if not stated"},
        "conditions": {"type": "string", "description": "conditions attached to the decision, or empty"},
        "quote": {"type": "string", "description": "the deciding motion and its result, copied word for word"},
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

Agenda item:
Request: {request}
Applicant: {applicant}
Location: {location}

What did the commission do on this agenda item?
- If several motions were made on it, report the last one that passed; if none passed, the last one voted on.
- "recommended …" is for a recommendation to the City Council; "approved"/"denied" for the commission's own decision.
- "public hearing set" is for a motion that only sets a hearing date.
- Copy the deciding motion and the sentence saying how the vote went, word for word, into quote.
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
    q, m = norm(quote).strip(" \"'"), norm(minutes)
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
    "approved with conditions": r"approv",
    "recommended approval": r"approv|recommend",
    "recommended approval with conditions": r"approv|recommend",
    "recommended denial": r"den(y|ial)",
    "denied": r"den(y|ied|ial)",
    "motion failed": r"fail|died|lack of a second|nay|opposed",
    "tabled": r"\btabl",
    "postponed": r"postpon|continu|defer|delay",
    "public hearing set": r"hearing",
    "forwarded without a recommendation": r"(no|without( a)?) recommendation",
}
_DID_NOT_PASS = re.compile(r"died|lack of a second|motion failed|failed to pass", re.I)


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
    if not re.search(_FITS[outcome], quote, re.I):
        return f"quote doesn't say {outcome!r}"
    if outcome != "motion failed" and _DID_NOT_PASS.search(quote) and not re.search(r"passed|carried", quote, re.I):
        return "quote says the motion didn't pass"
    return ""


# ── asking the model ─────────────────────────────────────────────────────────


def ask(endpoint: str, model: str, minutes: str, rec: dict) -> dict:
    question = QUESTION.format(
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
                a = ask(args.endpoint, args.model, texts[str(r["event_id"])], r)
            except Exception as exc:  # noqa: BLE001
                print(f"  {key}: no answer ({exc})")
                continue
            problem = check(a, texts[str(r["event_id"])])
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
            done.append(a | {"problem": check(a, texts[str(r["event_id"])])})
    trusted = [a for a in done if not a["problem"]]
    print(f"[outcomes] {len(done)} answered, {len(trusted)} checked out, {len(done) - len(trusted)} set aside")

    if gold is not None:

        def ok(a, lenient=False):
            g = gold[a["item_id"]]
            return a["outcome"] == g["outcome"] or (lenient and a["outcome"] in g.get("also", []))

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

"""
python -m spillarchive [steps …] --out DIR [--counties …]

Steps, in order (each resumes where it stopped; with none named, all run):
  index     the state's list of spills in the counties
  files     which PDFs are on file for each spill
  download  the PDFs
  extract   what the PDFs say (form fields, text, OCR)
  build     spills.json and spills.csv
"""

from __future__ import annotations

import argparse
import sys
import time

from . import files, layer
from .store import Archive

STEPS = ("index", "files", "download", "extract", "build")


def step_index(arc: Archive, args) -> None:
    spills = layer.fetch(args.counties, delay=args.delay)
    arc.write(
        "index.json", {"counties": list(args.counties), "fetched": time.strftime("%Y-%m-%dT%H:%M:%S"), "spills": spills}
    )
    print(f"[index] {len(spills)} spills in {', '.join(args.counties)}")


def step_files(arc: Archive, args) -> None:
    spills = arc.read("index.json", {}).get("spills", [])
    known = arc.read("files.json", {})
    todo = [s for s in spills if s["number"] not in known or args.refresh]
    print(f"[files] {len(todo)} of {len(spills)} spills to look up")
    for i, s in enumerate(todo, 1):
        try:
            known[s["number"]] = files.lookup(s["layer_id"], delay=args.delay)
        except Exception as exc:  # noqa: BLE001 — try again next run
            print(f"[files] {s['number']}: {exc}", file=sys.stderr)
            continue
        if i % 25 == 0 or i == len(todo):
            arc.write("files.json", known)
            print(f"[files] {i}/{len(todo)}", flush=True)
    arc.write("files.json", known)


def step_download(arc: Archive, args) -> None:
    from . import net

    spills = {s["number"]: s for s in arc.read("index.json", {}).get("spills", [])}
    known = arc.read("files.json", {})
    todo = [
        (n, u) for n, urls in known.items() for u in urls if not arc.pdf_path(u, spills.get(n, {}).get("year")).exists()
    ]
    print(f"[download] {len(todo)} PDFs to get")
    got = 0
    for i, (n, url) in enumerate(todo, 1):
        dest = arc.pdf_path(url, spills.get(n, {}).get("year"))
        try:
            resp = net.request("GET", url, delay=args.delay, timeout=180)
        except Exception as exc:  # noqa: BLE001
            print(f"[download] {url}: {exc}", file=sys.stderr)
            continue
        if resp.status_code == 404:
            print(f"[download] {url}: not there (404)", file=sys.stderr)
            continue
        if not resp.ok or not resp.content.startswith(b"%PDF"):
            print(f"[download] {url}: {resp.status_code}, not a PDF", file=sys.stderr)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(".part")
        tmp.write_bytes(resp.content)
        tmp.replace(dest)
        got += 1
        if i % 25 == 0:
            print(f"[download] {i}/{len(todo)}", flush=True)
    print(f"[download] got {got}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m spillarchive", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)  # fmt: skip
    ap.add_argument("steps", nargs="*", help=f"steps to run: {', '.join(STEPS)} (default: all)")
    ap.add_argument("--out", required=True, help="the archive folder")
    ap.add_argument("--counties", nargs="+", default=list(layer.BLACK_HILLS))
    ap.add_argument("--delay", type=float, default=1.0, help="seconds between requests to the state (default 1)")
    ap.add_argument("--refresh", action="store_true", help="look up files again for spills already looked up")
    ap.add_argument("--ocr", choices=("rapidocr", "textra", "none"), default="rapidocr", help="OCR engine for scans")
    ap.add_argument("--ocr-pages", default="4", help="scanned pages to OCR per PDF, or 'all' (default 4)")
    ap.add_argument("--workers", type=int, default=2, help="PDFs read at once (default 2)")
    args = ap.parse_args(argv)
    steps = args.steps or list(STEPS)
    if bad := [s for s in steps if s not in STEPS]:
        ap.error(f"unknown step(s): {', '.join(bad)}")
    arc = Archive(args.out)
    for name in STEPS:
        if name in steps:
            if name in ("extract", "build"):
                from . import extract

                getattr(extract, f"step_{name}")(arc, args)
            else:
                globals()[f"step_{name}"](arc, args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

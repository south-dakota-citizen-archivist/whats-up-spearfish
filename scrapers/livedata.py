"""
scrapers/livedata.py

Where the data lives when you run things on your own machine: a copy of this
repo's `data` branch (the live data the site is built from), kept in
.cache/data and brought up to date from GitHub before each local scrape or
build. There's no other default: a stale local copy is never used quietly.

Naming a folder (WUS_DATA_DIR=…, or sitegen's --data) uses that folder as is;
that's how the GitHub workflow runs, on its own checkout of the data branch.

If a local scrape has left changes in the copy, they're kept and the update is
skipped, with a note saying so; `python -m sitegen --fresh` discards them.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache" / "data"
BRANCH = "data"


def data_dir() -> Path:
    """The folder named in WUS_DATA_DIR, else the local copy of the live data."""
    named = os.environ.get("WUS_DATA_DIR")
    return Path(named) if named else CACHE


def _git(*args: str, cwd: Path = ROOT) -> str:
    env = {**os.environ, "TZ": "America/Denver"}  # times read in Spearfish time
    return subprocess.run(["git", *args], cwd=cwd, env=env, check=True, capture_output=True, text=True).stdout.strip()


def _as_of(path: Path) -> str:
    try:
        return _git("log", "-1", "--format=%cd", "--date=format-local:%b %-d at %-I:%M %p", cwd=path)
    except (subprocess.CalledProcessError, OSError):
        return "an unknown time"


def refresh(path: Path = CACHE, discard_local: bool = False) -> Path:
    """Bring the local copy up to date with the live data branch (cloning it the first time)."""
    try:
        if not (path / ".git").exists():
            remote = _git("remote", "get-url", "origin")
            path.parent.mkdir(parents=True, exist_ok=True)
            print(f"[data] downloading the live data (the {BRANCH} branch) into {path.relative_to(ROOT)} …")
            _git("clone", "--quiet", "--depth", "1", "--single-branch", "--branch", BRANCH, remote, str(path))
        else:
            _git("fetch", "--quiet", "--depth", "1", "origin", BRANCH, cwd=path)
            if _git("status", "--porcelain", cwd=path) and not discard_local:
                print(
                    f"[data] keeping your local scrape results in {path.relative_to(ROOT)}: the rest is live data "
                    f"from {_as_of(path)}. To start from the latest live data instead: python -m sitegen --fresh"
                )
                return path
            _git("reset", "--quiet", "--hard", "FETCH_HEAD", cwd=path)
            _git("clean", "--quiet", "-fd", cwd=path)
        print(f"[data] live data as of {_as_of(path)}")
    except (subprocess.CalledProcessError, OSError) as exc:
        detail = getattr(exc, "stderr", "") or exc
        if not (path / ".git").exists():
            raise SystemExit(f"[data] couldn't download the live data: {detail}") from exc
        reason = str(detail).strip()
        print(f"[data] WARNING: couldn't update the live data ({reason}); using the copy from {_as_of(path)}")
    return path

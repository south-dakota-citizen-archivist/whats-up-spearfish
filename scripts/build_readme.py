"""
scripts/build_readme.py

Regenerates the source list in README.md (between the sources:start/end
markers) from the scraper registry, so the README never drifts from the code.

Usage: uv run python scripts/build_readme.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scrapers.runner import discover  # noqa: E402

README = REPO_ROOT / "README.md"
START, END = "<!-- sources:start -->", "<!-- sources:end -->"


def sources_table(classes) -> str:
    rows = ["| Source | Slug | Kind | Notes |", "|---|---|---|---|"]
    for cls in sorted(classes, key=lambda c: (not c.enabled, c.kind, c.name.lower())):
        name = f"[{cls.name}]({cls.url})" if cls.url else cls.name
        notes = []
        if not cls.enabled:
            notes.append("🧊 on ice")
        if cls.browser:
            notes.append("needs browser")
        if cls.tier != "daily":
            notes.append(f"{cls.tier} tier")
        if cls.replace:
            notes.append("full snapshot")
        rows.append(f"| {name} | `{cls.slug}` | {cls.kind} | {', '.join(notes)} |")
    return "\n".join(rows)


def render(readme: str, table: str) -> str:
    block = f"{START}\n{table}\n{END}"
    if START in readme and END in readme:
        return re.sub(re.escape(START) + r".*?" + re.escape(END), lambda _: block, readme, flags=re.S)
    return readme.rstrip() + "\n\n## Sources\n\n" + block + "\n"


def main() -> None:
    readme = README.read_text(encoding="utf-8") if README.exists() else "# What's up, Spearfish?\n"
    README.write_text(render(readme, sources_table(discover())), encoding="utf-8")
    print(f"README.md sources table updated ({README.stat().st_size:,} bytes)")


if __name__ == "__main__":
    main()

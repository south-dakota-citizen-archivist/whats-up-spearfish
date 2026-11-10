"""
scripts/health_issue.py

Keeps one GitHub issue titled "Scraper health" in sync with data/_health.json:
opens/updates it while any enabled source has failed THRESHOLD runs in a row,
closes it (with a comment) once everything recovers.

Runs in Actions with GITHUB_TOKEN and GITHUB_REPOSITORY set; does nothing otherwise.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scrapers import net  # noqa: E402

TITLE = "Scraper health"
THRESHOLD = 3
HEALTH_JSON = "https://github.com/south-dakota-citizen-archivist/whats-up-spearfish/blob/data/_health.json"


def failing(health: dict) -> list[tuple[str, dict]]:
    return sorted(
        (slug, s)
        for slug, s in health.get("sources", {}).items()
        if s.get("enabled", True) and s.get("status") in ("error", "empty") and s.get("failures", 0) >= THRESHOLD
    )


def body(rows: list[tuple[str, dict]]) -> str:
    lines = [
        f"These sources have failed {THRESHOLD}+ runs in a row. The site keeps showing their last good data.",
        "",
        "| Source | Failures | Last success | Error |",
        "|---|---|---|---|",
    ]
    for slug, s in rows:
        err = (s.get("error") or "").replace("|", "\\|").replace("\n", " ")[:200]
        lines.append(
            f"| `{slug}` ({s.get('name', '')}) | {s.get('failures')} | {s.get('last_success') or 'never'} | {err} |"
        )
    lines += ["", f"Full details: {HEALTH_JSON}", "", "_Updated automatically by the scrape workflow._"]
    return "\n".join(lines)


def main(health_path: str = "data/_health.json") -> None:
    token, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        print("GITHUB_TOKEN/GITHUB_REPOSITORY not set; skipping")
        return
    health = json.loads(Path(health_path).read_text(encoding="utf-8"))
    rows = failing(health)

    api = f"https://api.github.com/repos/{repo}"
    s = requests.Session()
    s.headers.update(
        {"User-Agent": net.USER_AGENT, "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"}
    )
    open_issues = s.get(f"{api}/issues", params={"state": "open", "per_page": 100}, timeout=30).json()
    issue = next((i for i in open_issues if i.get("title") == TITLE and "pull_request" not in i), None)

    if rows:
        if issue:
            s.patch(f"{api}/issues/{issue['number']}", json={"body": body(rows)}, timeout=30).raise_for_status()
            print(f"Updated issue #{issue['number']} ({len(rows)} failing)")
        else:
            r = s.post(f"{api}/issues", json={"title": TITLE, "body": body(rows)}, timeout=30)
            r.raise_for_status()
            print(f"Opened issue #{r.json()['number']} ({len(rows)} failing)")
    elif issue:
        s.post(f"{api}/issues/{issue['number']}/comments", json={"body": "All sources recovered. 🎉"}, timeout=30)
        s.patch(f"{api}/issues/{issue['number']}", json={"state": "closed"}, timeout=30).raise_for_status()
        print(f"Closed issue #{issue['number']}")
    else:
        print("All sources healthy")


if __name__ == "__main__":
    main(*sys.argv[1:])

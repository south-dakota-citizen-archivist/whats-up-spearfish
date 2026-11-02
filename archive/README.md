# Spearfish planning & permit records archive

Every record collected from the City of Spearfish's OpenGov (ViewpointCloud) permitting
portal, consolidated 2026-11-01. The city disabled public access to the portal in
2026 (`publicPortalEnabled: false`, `allowPublicRecordSearch: false`), so nothing newer
than 2026-07-27 is available from it.

- `planning_records.jsonl.gz` — 9,761 records, one JSON object per line.
  9,223 have full detail (record, every form answer, locations, attachments,
  multi-entry items, documents) from raw API dumps made 2025; 538 more are
  summary-only (type, status, dates, address, coordinates, applicant) from the daily
  snapshots this project committed through 2026.
- `planning_index.json` — one flattened row per record, used by the site's
  "What's being built?" page.

Built by `scripts/build_planning_archive.py` on the main branch.

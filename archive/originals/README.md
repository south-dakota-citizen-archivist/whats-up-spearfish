# Originals

Source data from earlier versions of this project and its one-time collection runs, kept here
because this is the only place it survives. The site doesn't read these files. Unpack with
`tar -xJf <file>`.

| File | What it is |
|---|---|
| `planning_portal_raw.tar.xz` | Every file downloaded from the city's OpenGov planning portal before it closed: 73,759 JSON files covering 9,223 records, in `records/{id}/`. `superseded/` holds 28 earlier versions of files that changed between the two downloads; `code/` has the download scripts. `../planning_records.jsonl.gz` is the cleaned version of this. |
| `building_permits_original.tar.xz` | The first building permit project: the hand-checked combined CSV (5,441 rows), 153 monthly CSVs, and its scripts. The PDFs it was made from are in `permit_reports/`. |
| `spill_archive_results.tar.xz` | The Black Hills spill archive: one row per spill (`spills.json`, `spills.csv`), plus the state's spill index and file list. |
| `spill_readings.tar.xz` | What was read from each of the 4,822 spill PDFs: every form found, and the text of scanned pages. Text from pages that already had a text layer is left out; the PDFs are on the state's site. |
| `planning_minutes_readings.tar.xz` | Planning Commission outcomes read from meeting minutes by a language model (`planning_decisions.csv`), and its working files. Never hand-checked. |

Anything shaped like a Social Security number is replaced with `XXX-XX-XXXX`.

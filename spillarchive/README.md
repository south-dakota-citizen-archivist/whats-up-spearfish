# spillarchive

A complete local archive of South Dakota spill reports for a set of counties (the
Black Hills by default): the state's list of spills, every PDF on file for each,
and what their forms say. It reads the state's fillable forms exactly, and older
scanned forms with OCR.

It's self-contained: it doesn't import anything from the site it lives beside, so the
folder can move to its own project as is.

## Where the data comes from

- **The list of spills:** the public layer behind DANR's
  [Tanks and Spills Map](https://apps.sd.gov/NR42InteractiveMap/), on the state's
  ArcGIS server. For the six Black Hills counties it holds about 3,300 reports going
  back to 1972, with steady numbers from the late 1980s.
- **Which PDFs each spill has:** asked of the map's own lookup, one spill at a time,
  as the map does when someone clicks a spill. A spill can have several files, e.g.
  `1985.075A.pdf`. The files live at `danr.sd.gov/spillimages/{year}/{number}.pdf`.
- **Spill numbers:** `YEAR.SEQUENCE` (`2026.146`), or before 2000 a two-digit year
  (`93.042`, filed as `1993.042`). Tank-removal checks have their own series
  (`2026005`; before 2000, `93047`), and a few placeholder numbers (`9999`) are on
  the layer too. All are kept, each marked with its series.

## What the PDFs are

Each PDF is a spill's whole case file: the report form, follow-up reports, letters,
photos and lab results.

- **About 2021 on:** the Spill Report Form and Incident Follow-Up Report are
  fillable PDFs filled in on a computer, and every answer is read exactly from the
  form fields (`forms.py`). The field names are unreliable ('T me' for Time), so
  answers are matched by where they sit on the page: a text field takes the printed
  label to its left, and a checked box the option to its right.
- **Before that:** scans. These are OCR'd (`ocr.py`) and read for labeled answers
  (`scanned.py`). Typed forms from the 1990s to 2020 come through well. Handwritten
  forms from the 1980s and 1990s come through roughly. Every value read this way is
  marked `read_from: ocr`.

## OCR

- **`rapidocr`** (the default): PaddleOCR's models on ONNX Runtime. It's free,
  installs with pip, needs no system packages and runs on any CPU, including GitHub
  Actions.
- **`textra`**: Apple's Vision OCR via [textra](https://github.com/freedmand/textra),
  on macOS only.

OCR takes a couple of seconds a page, and case files run to hundreds of pages, so by
default only the first pages are read until the report form turns up (`--ocr-pages 4`).
`--ocr-pages all` reads everything, for full-text search. That takes a long time, but
it resumes where it stopped.

## Use

```sh
pip install requests pdfplumber rapidocr onnxruntime    # or: uv sync

python -m spillarchive --out ~/spill-archive                       # everything, Black Hills
python -m spillarchive index files --out ~/spill-archive           # just the lists
python -m spillarchive extract build --out ~/spill-archive --workers 6
python -m spillarchive --out ~/sd-spills --counties Minnehaha Lincoln
```

Every step picks up where the last run stopped.

## What's in the archive folder

| | |
|---|---|
| `index.json` | every spill in the counties, as the state's layer lists it |
| `files.json` | spill number → the URLs of its PDFs |
| `pdfs/YYYY/*.pdf` | the PDFs |
| `extracted/*.pdf.json` | per PDF: each page's text (and how it was read) and the forms found |
| `spills.json` | one record per spill: the layer's fields, its PDFs, and `report` / `follow_up` with the forms' answers |
| `spills.csv` | the same, flat, for a spreadsheet |

Dates in `spills.json` (`spill_date`, `reported_date`) are ISO. The forms' own answers
are kept as written.

"""
The archive on disk (every step reads and writes here, and picks up where it left off):

  index.json          every spill on the state's layer for the chosen counties
  files.json          spill number → the PDFs on file for it (from the state's map)
  pdfs/YYYY/*.pdf     the PDFs themselves
  extracted/*.json    what each PDF says: form fields, page text, OCR
  spills.json, .csv   one row per spill, everything merged
"""

from __future__ import annotations

import json
import os
from pathlib import Path


class Archive:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, *parts) -> Path:
        return self.root.joinpath(*parts)

    def read(self, name: str, default):
        p = self.path(name)
        return json.loads(p.read_text(encoding="utf-8")) if p.exists() else default

    def write(self, name: str, data) -> None:
        p = self.path(name)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)

    def pdf_path(self, url: str, year) -> Path:
        name = url.rsplit("/", 1)[-1]
        return self.path("pdfs", str(year or "unknown"), name)

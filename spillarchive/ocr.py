"""
OCR for scanned pages, with a choice of engine:

  rapidocr  PaddleOCR's models on ONNX Runtime (pip install rapidocr onnxruntime): free,
            no system packages, runs on any CPU, including GitHub Actions. The default.
  textra    Apple's Vision text recognition via the textra command (macOS only;
            https://github.com/freedmand/textra).

Both give lines of text with their place on the page, in PDF points from the top left.
"""

from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

SCALE = 200 / 72  # render pages at 200 dpi

_rapid = None


def available(engine: str) -> bool:
    if engine == "textra":
        return shutil.which("textra") is not None
    if engine == "rapidocr":
        try:
            import rapidocr  # noqa: F401

            return True
        except ImportError:
            return False
    return False


def render(pdf_path: Path, index: int):
    """One page as an image."""
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf_path))
    try:
        return doc[index].render(scale=SCALE).to_pil()
    finally:
        doc.close()


def _rapidocr(image) -> list[dict]:
    global _rapid
    if _rapid is None:
        logging.getLogger("RapidOCR").setLevel(logging.ERROR)
        from rapidocr import RapidOCR

        _rapid = RapidOCR(params={"Global.log_level": "error"})
    result = _rapid(image)
    if not result.txts:
        return []
    out = []
    for text, score, box in zip(result.txts, result.scores, result.boxes):
        xs, ys = [p[0] for p in box], [p[1] for p in box]
        out.append({"text": text, "conf": round(float(score), 3), "x0": min(xs) / SCALE, "x1": max(xs) / SCALE,
                    "top": min(ys) / SCALE, "bottom": max(ys) / SCALE})  # fmt: skip
    return out


def _textra(image) -> list[dict]:
    with tempfile.TemporaryDirectory() as tmp:
        png, out = Path(tmp) / "page.png", Path(tmp) / "page.json"
        image.save(png)
        subprocess.run(["textra", "-s", str(png), "-p", str(out)], check=True, capture_output=True)
        data = json.loads(out.read_text())
    w, h = image.size
    lines = []
    for obs in data.get("observations", data if isinstance(data, list) else []):
        box = obs.get("bounds") or obs.get("boundingBox") or {}
        # textra gives normalized coordinates with the origin at the bottom left
        x, y = box.get("x", 0) * w, (1 - box.get("y", 0) - box.get("height", 0)) * h
        lines.append({"text": obs.get("text", ""), "conf": obs.get("confidence"), "x0": x / SCALE,
                      "x1": (x + box.get("width", 0) * w) / SCALE, "top": y / SCALE,
                      "bottom": (y + box.get("height", 0) * h) / SCALE})  # fmt: skip
    return lines


def page_lines(pdf_path: Path, index: int, engine: str = "rapidocr") -> list[dict]:
    """The text on one scanned page, as positioned pieces."""
    image = render(pdf_path, index)
    return _textra(image) if engine == "textra" else _rapidocr(image)


def as_text(pieces: list[dict]) -> str:
    """Positioned pieces as plain lines, top to bottom and left to right."""
    rows: list[list[dict]] = []
    for p in sorted(pieces, key=lambda p: ((p["top"] + p["bottom"]) / 2, p["x0"])):
        mid = (p["top"] + p["bottom"]) / 2
        if rows and abs((rows[-1][0]["top"] + rows[-1][0]["bottom"]) / 2 - mid) < 5:
            rows[-1].append(p)
        else:
            rows.append([p])
    return "\n".join("  ".join(p["text"] for p in sorted(r, key=lambda p: p["x0"])) for r in rows)

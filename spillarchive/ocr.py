"""
OCR for scanned pages, from sddocs (south-dakota-citizen-archivist/sd-archive,
packages/sddocs): rapidocr by default, and textra, tesseract, or Apple Vision and LiveText
where they're installed. Pieces are positioned in PDF points from the top left.
"""

from __future__ import annotations

from sddocs.ocr import SCALE, available, render
from sddocs.ocr import as_text as _as_text
from sddocs.ocr import page_pieces as page_lines

__all__ = ["SCALE", "as_text", "available", "page_lines", "render"]


def as_text(pieces: list[dict]) -> str:
    """Pieces as lines, every two pieces on a line joined by two spaces: the scanned-form
    reader (scanned.py) ends an answer at two spaces."""
    return _as_text(pieces, spacing="  ")

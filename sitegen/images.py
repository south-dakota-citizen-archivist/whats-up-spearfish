"""
sitegen/images.py

Thumbnail-sized versions of the third-party photos the site shows. Sources link
full-size images (a pet photo can be 900 KB) that we show at 64–200 pixels, so
for hosts that publish smaller sizes we ask for one. When the smaller size is a
guess (WordPress), the original rides along as a fallback; base.html swaps it in
if the thumbnail fails to load.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from markupsafe import Markup

#: Squarespace serves these widths when asked with ?format=<n>w
_SQUARESPACE_WIDTHS = (100, 300, 500, 750, 1000, 1500, 2500)

_AMAZON_COVER = re.compile(r"(/images/P/[0-9X]{10}\.01\.)[^/]*?(\.jpe?g)$", re.I)
_WP_UPLOAD = re.compile(r"(/wp-content/uploads/.+?)(-\d+x\d+)?(\.(?:jpe?g|png|webp))$", re.I)


def thumb(url: str, width: int) -> tuple[str, bool]:
    """A version of *url* at least *width* pixels wide where the host offers one.

    Returns (url, guessed): guessed means the size may not exist, so keep the
    original as a fallback.
    """
    if not url:
        return url, False
    parts = urlsplit(url)
    host = parts.netloc.lower()

    if host == "images.squarespace-cdn.com":
        size = next((w for w in _SQUARESPACE_WIDTHS if w >= width), _SQUARESPACE_WIDTHS[-1])
        query = [(k, v) for k, v in parse_qsl(parts.query) if k != "format"] + [("format", f"{size}w")]
        return urlunsplit(parts._replace(query=urlencode(query))), False

    if host.endswith("images-amazon.com"):
        m = _AMAZON_COVER.search(parts.path)
        if m:
            path = _AMAZON_COVER.sub(rf"\g<1>_SX{width}_SCLZZZZZZZ_\g<2>", parts.path)
            return urlunsplit(parts._replace(path=path)), False

    if host.endswith("ytimg.com") and parts.path.endswith("/hqdefault.jpg") and width <= 320:
        # 320×180 and no letterbox bars, unlike the 480×360 "hq" frame
        return urlunsplit(parts._replace(path=parts.path.replace("/hqdefault.jpg", "/mqdefault.jpg"))), False

    if width <= 300:
        m = _WP_UPLOAD.search(parts.path)
        if m:
            # WordPress keeps a 150×150 square crop of every upload, usually
            path = _WP_UPLOAD.sub(r"\g<1>-150x150\g<3>", parts.path)
            return urlunsplit(parts._replace(path=path)), True

    return url, False


def thumb_attrs(url: str, width: int) -> Markup:
    """src="…" for an <img>, plus data-fallback="<original>" when the size is a guess."""
    small, guessed = thumb(url, width)
    if guessed and small != url:
        return Markup('src="{}" data-fallback="{}"').format(small, url)
    return Markup('src="{}"').format(small)

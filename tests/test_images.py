"""
tests/test_images.py

Thumbnail-sized photo URLs (sitegen/images.py).
"""

from __future__ import annotations

from sitegen.images import thumb, thumb_attrs

SQ = "https://images.squarespace-cdn.com/content/v1/abc/def/Domino+Cuuuute.jpg"


def test_squarespace_asks_for_the_smallest_width_that_covers_it():
    assert thumb(SQ, 300) == (SQ + "?format=300w", False)
    assert thumb(SQ, 320)[0].endswith("?format=500w")
    assert thumb(SQ + "?format=1500w", 150)[0] == SQ + "?format=300w"  # replaces the source's own size


def test_amazon_cover_at_width():
    url = "https://images-na.ssl-images-amazon.com/images/P/0767848853.01.LZZZZZZZ.jpg"
    assert thumb(url, 250) == (
        "https://images-na.ssl-images-amazon.com/images/P/0767848853.01._SX250_SCLZZZZZZZ_.jpg",
        False,
    )


def test_inaturalist_size_by_width():
    sq = "https://static.inaturalist.org/photos/178968933/square.jpg"
    assert thumb(sq, 240) == ("https://static.inaturalist.org/photos/178968933/small.jpg", False)
    assert thumb(sq, 300)[0].endswith("/medium.jpg")
    assert thumb("https://inaturalist-open-data.s3.amazonaws.com/photos/1/square.jpeg", 60)[0].endswith("/square.jpeg")


def test_youtube_medium_frame():
    assert thumb("https://i2.ytimg.com/vi/abc/hqdefault.jpg", 320) == (
        "https://i2.ytimg.com/vi/abc/mqdefault.jpg",
        False,
    )


def test_wordpress_square_crop_is_a_guess_with_fallback():
    for url in [
        "https://crowpeakbrewing.com/wp-content/uploads/2026/02/1.png",
        "https://www.spearfishbrewing.com/wp-content/uploads/2025/08/IMG_2559-768x1024.jpg",
    ]:
        small, guessed = thumb(url, 150)
        assert guessed and small.rsplit("/", 1)[1].split("-150x150")[0] in url
        assert small.endswith(("-150x150.png", "-150x150.jpg"))
    attrs = str(thumb_attrs("https://crowpeakbrewing.com/wp-content/uploads/2026/02/1.png", 150))
    assert attrs == (
        'src="https://crowpeakbrewing.com/wp-content/uploads/2026/02/1-150x150.png" '
        'data-fallback="https://crowpeakbrewing.com/wp-content/uploads/2026/02/1.png"'
    )
    assert not thumb("https://crowpeakbrewing.com/wp-content/uploads/2026/02/1.png", 800)[1]  # big: keep original


def test_other_hosts_untouched():
    url = "https://leonescreamery.com/images/uploads/cropped/SweetCream.jpg"
    assert thumb(url, 300) == (url, False)
    assert str(thumb_attrs(url, 300)) == f'src="{url}"'
    assert thumb("", 300) == ("", False)

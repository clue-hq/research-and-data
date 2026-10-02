"""Font container normalization (option A, 2026-09-02).

The invariant these pin: a font asset's primary bytes are always a single sfnt face. WOFF and
WOFF2 are lossless wrappers; decoding one yields the same tables, deterministically.
"""

from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pytest
from fontTools.ttLib import TTFont

from lumen_api.font_containers import (
    SFNT_MIME,
    WEB_CONTAINERS,
    DecodedFont,
    FontContainerError,
    decode_note,
    decode_web_font,
    encode_woff2,
    sfnt_filename,
    sniff_font_container,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
INTER = REPO_ROOT / "fonts" / "Inter-Regular.ttf"
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


def as_flavor(data: bytes, flavor: str) -> bytes:
    font = TTFont(BytesIO(data), recalcTimestamp=False, recalcBBoxes=False)
    font.flavor = flavor
    out = BytesIO()
    font.save(out)
    return out.getvalue()


def glyph_order(data: bytes) -> list[str]:
    return TTFont(BytesIO(data)).getGlyphOrder()


@pytest.fixture(scope="module")
def inter_ttf() -> bytes:
    return INTER.read_bytes()


@pytest.fixture(scope="module")
def inter_woff2(inter_ttf: bytes) -> bytes:
    return as_flavor(inter_ttf, "woff2")


@pytest.fixture(scope="module")
def inter_woff(inter_ttf: bytes) -> bytes:
    return as_flavor(inter_ttf, "woff")


def test_sniff_recognizes_every_container_and_nothing_else(
    inter_ttf: bytes, inter_woff2: bytes, inter_woff: bytes
) -> None:
    assert sniff_font_container(inter_ttf) == "ttf"
    assert sniff_font_container(inter_woff2) == "woff2"
    assert sniff_font_container(inter_woff) == "woff"
    assert sniff_font_container(b"OTTO" + b"\x00" * 12) == "otf"
    assert sniff_font_container(b"true" + b"\x00" * 12) == "ttf"
    assert sniff_font_container(TINY_PNG) is None
    assert sniff_font_container(b"") is None
    assert WEB_CONTAINERS == ("woff2", "woff")
    assert SFNT_MIME == {"ttf": "font/ttf", "otf": "font/otf"}


def test_decode_woff2_yields_the_same_ttf_tables(inter_ttf: bytes, inter_woff2: bytes) -> None:
    decoded = decode_web_font(inter_woff2)
    assert isinstance(decoded, DecodedFont)
    assert decoded.container == "ttf"
    assert decoded.mime_type == "font/ttf"
    assert decoded.source_container == "woff2"
    assert decoded.source_sha256 == hashlib.sha256(inter_woff2).hexdigest()
    assert decoded.data[:4] == b"\x00\x01\x00\x00"
    source = TTFont(BytesIO(inter_ttf))
    result = TTFont(BytesIO(decoded.data))
    assert result["head"].unitsPerEm == source["head"].unitsPerEm
    assert result.getGlyphOrder() == source.getGlyphOrder()
    assert result["OS/2"].fsType == source["OS/2"].fsType
    assert result["hhea"].ascent == source["hhea"].ascent


def test_decode_woff1_yields_ttf(inter_ttf: bytes, inter_woff: bytes) -> None:
    decoded = decode_web_font(inter_woff)
    assert decoded is not None
    assert decoded.source_container == "woff"
    assert decoded.container == "ttf"
    assert glyph_order(decoded.data) == glyph_order(inter_ttf)


def test_decode_is_deterministic(inter_woff2: bytes) -> None:
    first = decode_web_font(inter_woff2)
    second = decode_web_font(inter_woff2)
    assert first is not None and second is not None
    assert first.data == second.data


def test_sfnt_and_non_font_bytes_pass_through_as_none(inter_ttf: bytes) -> None:
    assert decode_web_font(inter_ttf) is None
    assert decode_web_font(b"OTTO" + b"\x00" * 12) is None
    assert decode_web_font(TINY_PNG) is None
    assert decode_web_font(b"") is None


def test_corrupt_web_font_raises() -> None:
    with pytest.raises(FontContainerError):
        decode_web_font(b"wOF2" + b"\x00" * 96)
    with pytest.raises(FontContainerError):
        decode_web_font(b"wOFF" + b"\x11" * 96)


def test_encode_woff2_round_trips_and_is_identity_for_woff2(
    inter_ttf: bytes, inter_woff2: bytes
) -> None:
    encoded = encode_woff2(inter_ttf)
    assert encoded[:4] == b"wOF2"
    assert len(encoded) < len(inter_ttf)
    assert encode_woff2(encoded) is encoded
    back = decode_web_font(encoded)
    assert back is not None
    assert glyph_order(back.data) == glyph_order(inter_ttf)
    assert encode_woff2(inter_ttf) == encoded  # deterministic


def test_encode_woff2_refuses_non_font_bytes() -> None:
    with pytest.raises(FontContainerError):
        encode_woff2(TINY_PNG)
    with pytest.raises(FontContainerError):
        encode_woff2(b"wOFF" + b"\x11" * 96)


def test_sfnt_filename_swaps_only_web_extensions() -> None:
    assert sfnt_filename("season_mix_vf-s.p.100nk5~lg13~z.woff2", "ttf") == (
        "season_mix_vf-s.p.100nk5~lg13~z.ttf"
    )
    assert sfnt_filename("Brand.WOFF", "otf") == "Brand.otf"
    assert sfnt_filename("Brand.ttf", "ttf") == "Brand.ttf"
    assert sfnt_filename("no-extension", "ttf") == "no-extension"
    assert sfnt_filename(None, "ttf") is None
    assert sfnt_filename("", "ttf") == ""


def test_decode_note_names_source_and_target(inter_woff2: bytes) -> None:
    decoded = decode_web_font(inter_woff2)
    assert decoded is not None
    note = decode_note(decoded)
    assert note.startswith("font container decoded at ingestion: woff2 -> ttf")
    assert decoded.source_sha256 in note

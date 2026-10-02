"""A tiny variable TTF built in memory (no licensed bytes in the repo): one axis ``wght``,
two masters (a thin and a heavy stem on the glyph ``I``). Enough for fontTools' instancer and
for the OS/2 checks the ingestion tests make."""

from __future__ import annotations

from io import BytesIO

from fontTools.designspaceLib import AxisDescriptor, DesignSpaceDocument, SourceDescriptor
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.varLib import build as build_variable


def _master(family: str, stem: int) -> TTFont:
    fb = FontBuilder(1000, isTTF=True)
    fb.setupGlyphOrder([".notdef", "space", "I"])
    fb.setupCharacterMap({0x20: "space", 0x49: "I"})
    pen = TTGlyphPen(None)
    pen.moveTo((100, 0))
    pen.lineTo((100 + stem, 0))
    pen.lineTo((100 + stem, 700))
    pen.lineTo((100, 700))
    pen.closePath()
    empty = TTGlyphPen(None).glyph()
    fb.setupGlyf({".notdef": empty, "space": empty, "I": pen.glyph()})
    fb.setupHorizontalMetrics({".notdef": (500, 0), "space": (250, 0), "I": (200 + stem, 100)})
    fb.setupHorizontalHeader(ascent=800, descent=-200)
    fb.setupNameTable({"familyName": family, "styleName": "Regular"})
    fb.setupOS2(
        sTypoAscender=800,
        sTypoDescender=-200,
        usWinAscent=800,
        usWinDescent=200,
        usWeightClass=400,
        achVendID="TEST",
    )
    fb.setupPost()
    return fb.font


def build_variable_font(family: str = "Synthetic VF", wght: tuple[int, int] = (300, 900)) -> bytes:
    doc = DesignSpaceDocument()
    axis = AxisDescriptor()
    axis.name, axis.tag = "Weight", "wght"
    axis.minimum, axis.default, axis.maximum = wght[0], wght[0], wght[1]
    doc.addAxis(axis)
    for location, stem in ((wght[0], 60), (wght[1], 200)):
        source = SourceDescriptor()
        source.font = _master(family, stem)
        source.location = {"Weight": location}
        doc.addSource(source)
    font, _model, _masters = build_variable(doc)
    out = BytesIO()
    font.save(out)
    return out.getvalue()


def as_woff2(data: bytes) -> bytes:
    font = TTFont(BytesIO(data), recalcTimestamp=False, recalcBBoxes=False)
    font.flavor = "woff2"
    out = BytesIO()
    font.save(out)
    return out.getvalue()

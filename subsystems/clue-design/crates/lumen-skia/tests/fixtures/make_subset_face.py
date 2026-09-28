#!/usr/bin/env python3
"""Regenerate `subset-face.ttf`, the per-glyph-fallback test fixture.

`subset-face.ttf` is Inter-Regular subset to ONLY digits, ASCII letters, and
space, then renamed to the family "SubsetFace". It deliberately LACKS the
solidus "/", multiplication sign "×", and em dash "—" — the exact glyph
gaps a real subsetted brand webfont (e.g. Aeonik TRIAL) exhibits. Loaded
alongside the bundled Inter, it exercises per-glyph font fallback: those three
characters must shape from Inter, not render as tofu (LUMS0103).

Run from the repo root:  .venv/bin/python
crates/lumen-skia/tests/fixtures/make_subset_face.py
"""
from pathlib import Path
from fontTools import subset
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[4]
SRC = ROOT / "fonts" / "Inter-Regular.ttf"
OUT = Path(__file__).resolve().parent / "subset-face.ttf"

KEEP = [0x20] + list(range(0x30, 0x3A)) + list(range(0x41, 0x5B)) + list(range(0x61, 0x7B))

options = subset.Options()
options.name_IDs = ['*']
options.glyph_names = True
font = subset.load_font(str(SRC), options)
subsetter = subset.Subsetter(options=options)
subsetter.populate(unicodes=KEEP)
subsetter.subset(font)

name = font["name"]
for rec in name.names:
    text = rec.toUnicode()
    if "Inter" in text:
        rec.string = text.replace("Inter", "SubsetFace")
# Ensure the primary family names are unambiguous.
name.setName("SubsetFace", 1, 3, 1, 0x409)
name.setName("Regular", 2, 3, 1, 0x409)
name.setName("SubsetFace", 4, 3, 1, 0x409)
name.setName("SubsetFace-Regular", 6, 3, 1, 0x409)
name.setName("SubsetFace", 16, 3, 1, 0x409)
name.setName("Regular", 17, 3, 1, 0x409)

subset.save_font(font, str(OUT), options)
print(f"wrote {OUT} ({OUT.stat().st_size} bytes)")

check = TTFont(str(OUT))
cmap = check.getBestCmap()
for ch in ("/", "×", "—"):
    assert ord(ch) not in cmap, f"{ch!r} unexpectedly present"
for ch in "0123456789ABCabc":
    assert ord(ch) in cmap, f"{ch!r} unexpectedly absent"
print("verified: symbols dropped, alphanumerics kept, family =", check["name"].getDebugName(1))

# Same family, different coverage: only the bold face supplies this private-use
# character. Its visible outline is the existing A, not proprietary font data.
bold = TTFont(OUT)
bold["OS/2"].usWeightClass = 700
bold["OS/2"].fsSelection = (bold["OS/2"].fsSelection & ~0x40) | 0x20
bold["head"].macStyle |= 1
for table in bold["cmap"].tables:
    if table.isUnicode():
        table.cmap[0xE123] = table.cmap[ord("A")]
for name_id, value in [(2, "Bold"), (4, "SubsetFace Bold"), (6, "SubsetFace-Bold"), (17, "Bold")]:
    bold["name"].setName(value, name_id, 3, 1, 0x409)
bold.save(OUT.with_name("subset-face-bold.ttf"))

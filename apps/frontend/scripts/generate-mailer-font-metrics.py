"""Regenerate local preview advances from the bundled OFL TrueType fonts.

No font service or dependency is needed. These fonts expose Unicode cmap format 4.
The frontend uses an extra measurement margin; printer calibration stays separate.
"""
import json
from pathlib import Path
from struct import unpack_from

root = Path(__file__).resolve().parent.parent
profiles = {}
for family, filename in [("Clue Handwritten", "caveat.ttf"), ("Clue Handprint", "patrick-hand.ttf")]:
    data = (root / "public/direct-mail" / filename).read_bytes()
    def u16(offset): return unpack_from(">H", data, offset)[0]
    def i16(offset): return unpack_from(">h", data, offset)[0]
    def u32(offset): return unpack_from(">I", data, offset)[0]
    tables = {data[o:o+4].decode(): u32(o+8) for o in range(12, 12+16*u16(4), 16)}
    cmap = tables["cmap"]
    subtables = [cmap+u32(o+4) for o in range(cmap+4, cmap+4+8*u16(cmap+2), 8)]
    sub = next(offset for offset in subtables if u16(offset) == 4)
    count = u16(sub+6)//2
    def glyph_id(code):
        for index in range(count):
            end, start = u16(sub+14+2*index), u16(sub+16+2*count+2*index)
            if start <= code <= end:
                delta = i16(sub+16+4*count+2*index)
                address = sub+16+6*count+2*index
                offset = u16(address)
                if not offset: return (code+delta) % 65536
                glyph = u16(address+offset+2*(code-start))
                return (glyph+delta) % 65536 if glyph else 0
        return 0
    units, metrics = u16(tables["head"]+18), u16(tables["hhea"]+34)
    advances = {}
    for code in [*range(32, 592), *range(8192, 8304)]:
        glyph = glyph_id(code)
        if glyph:
            advances[chr(code)] = round(u16(tables["hmtx"]+4*min(glyph, metrics-1))/units, 5)
    profiles[family] = advances
(root / "src/features/direct-mail/model/handwriting-metrics.json").write_text(json.dumps(profiles, ensure_ascii=False, indent=2)+"\n")

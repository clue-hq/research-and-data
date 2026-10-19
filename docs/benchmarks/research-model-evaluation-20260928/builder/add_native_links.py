"""Native hyperlink fallback: artifact-tool HYPERLINK evaluates to not implemented.

All workbook values, styles and calculations are authored by artifact-tool.
This only adds standard external hyperlink relationships to the exported XLSX.
"""

import json
from pathlib import Path
import xml.etree.ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

out = Path(__file__).resolve().parents[3] / "outputs" / "research-model-evaluation-20260928"
book = out / "research-model-comparison.xlsx"
links = json.loads((out / "native-hyperlinks.json").read_text())
M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
P = "http://schemas.openxmlformats.org/package/2006/relationships"
ET.register_namespace("", M)
ET.register_namespace("r", R)
with ZipFile(book) as z:
    files = {n: z.read(n) for n in z.namelist()}
wb = ET.fromstring(files["xl/workbook.xml"])
rels = ET.fromstring(files["xl/_rels/workbook.xml.rels"])
targets = {x.attrib["Id"]: x.attrib["Target"] for x in rels}
sheetpaths = {}
for s in wb.find(f"{{{M}}}sheets"):
    target = targets[s.attrib[f"{{{R}}}id"]]
    sheetpaths[s.attrib["name"]] = target.lstrip("/") if target.startswith("/") else "xl/" + target
for name, sp in sheetpaths.items():
    sl = [x for x in links if x["sheet"] == name]
    if not sl:
        continue
    xml = ET.fromstring(files[sp])
    hs = ET.Element(f"{{{M}}}hyperlinks")
    rp = str(Path(sp).parent / "_rels" / (Path(sp).name + ".rels"))
    rr = ET.fromstring(files[rp]) if rp in files else ET.Element(f"{{{P}}}Relationships")
    for i, l in enumerate(sl, 1):
        rid = f"NativeLink{i}"
        ET.SubElement(
            rr,
            f"{{{P}}}Relationship",
            {"Id": rid, "Type": R + "/hyperlink", "Target": l["target"], "TargetMode": "External"},
        )
        ET.SubElement(hs, f"{{{M}}}hyperlink", {"ref": l["cell"], f"{{{R}}}id": rid})
    # OOXML requires hyperlinks after validations/conditional formats and before
    # print options, page margins/setup, drawings and tableParts.
    later = {
        "printOptions",
        "pageMargins",
        "pageSetup",
        "headerFooter",
        "rowBreaks",
        "colBreaks",
        "customProperties",
        "cellWatches",
        "ignoredErrors",
        "smartTags",
        "drawing",
        "legacyDrawing",
        "legacyDrawingHF",
        "picture",
        "oleObjects",
        "controls",
        "webPublishItems",
        "tableParts",
        "extLst",
    }
    ix = next((i for i, c in enumerate(xml) if c.tag.split("}")[-1] in later), len(xml))
    xml.insert(ix, hs)
    files[sp] = ET.tostring(xml, encoding="utf-8", xml_declaration=True)
    files[rp] = ET.tostring(rr, encoding="utf-8", xml_declaration=True)
tmp = book.with_suffix(".tmp")
with ZipFile(tmp, "w", ZIP_DEFLATED) as z:
    for n, b in files.items():
        z.writestr(n, b)
tmp.replace(book)
with ZipFile(book) as z:
    assert z.testzip() is None
    found = sum(
        len(ET.fromstring(z.read(sp)).findall(f"{{{M}}}hyperlinks/{{{M}}}hyperlink"))
        for sp in sheetpaths.values()
    )
    assert found == len(links), (found, len(links))
print(json.dumps({"native_hyperlinks": found, "xlsx_zip_integrity": "ok"}))

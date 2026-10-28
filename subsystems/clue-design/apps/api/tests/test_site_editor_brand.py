"""The brand the site editor is sent (site loading, 2026-10-29).

The editor's brand carried every released section of the workspace — 113 sections, 24.6 MB on the
lane — when a page uses a handful, and each section's CSS is the whole page stylesheet scoped
under that section's own class, so the same rules travelled once per section (21.5 MB of CSS).

* ``editor_site_brand`` keeps only the sections the site's pages and shell place. The editor has
  no way to add a section itself (the agent places them, and a load that shows one the brand lacks
  reads the brand again), and the assets — the captured images of every section — stay whole.
* ``pack_clone_css`` sends each distinct top-level CSS block once, with the section's own class
  stood in by a marker; ``unpack_clone_css`` (and the editor's own reader) puts every section's CSS
  back exactly, byte for byte.

The agent's catalog, the save check, publish and the thumbnail are not affected: they still use the
full brand from ``site_brand_loader``.
"""

from __future__ import annotations

import copy

from lumen_api.site_brand import (
    CLONE_CLASS_MARK,
    editor_site_brand,
    pack_clone_css,
    split_css_blocks,
    unpack_clone_css,
)


def _clone(fragment_id: str, css: str) -> dict:
    wrapper = f"lumen-frag-{fragment_id.removeprefix('frag_')}"
    return {
        "id": fragment_id, "label": fragment_id, "wrapper_class": wrapper,
        "html": f"<p>{fragment_id}</p>", "css": css.replace("WRAP", wrapper), "slots": {},
    }


IMAGE = "/asset-store/" + "a" * 64


def _brand(*clones: dict) -> dict:
    return {
        "slug": "s", "kit": {}, "fonts": [], "libraryFonts": [],
        "assets": {IMAGE: {"kind": "captured_image", "file": IMAGE}},
        "clones": {clone["id"]: clone for clone in clones},
    }


SHARED = (
    "@supports (x:y) { .WRAP *:not(:where(ls-h)) {--a:0;--b:1} }"
    ".WRAP .hero { padding: 64px }\n"
    "@media (min-width: 40rem) { .WRAP .hero { padding: 96px } .WRAP .cta { color: red } }"
)


def test_css_blocks_split_at_the_top_level_and_join_back_exactly() -> None:
    css = (
        '/* a } comment { */ .a { content: "}{" } '
        "@media (x) { .b { c: d } .e { f: g } } "
        "@import url(x.css); "
        ".h { background: url('a}b.png') } "
        ".tail { unclosed"
    )
    assert split_css_blocks(css) == [
        '/* a } comment { */ .a { content: "}{" }',
        " @media (x) { .b { c: d } .e { f: g } }",
        " @import url(x.css);",
        " .h { background: url('a}b.png') }",
        " .tail { unclosed",
    ]


def test_packed_css_is_sent_once_and_every_section_gets_its_own_back_exactly() -> None:
    a = _clone("frag_" + "1" * 16, SHARED)
    b = _clone("frag_" + "2" * 16, SHARED + ".WRAP .only-b { x: y }")
    brand = _brand(a, b)
    original = copy.deepcopy(brand)

    wire = pack_clone_css(brand)

    assert brand == original, "packing never changes the brand it is given"
    assert all("css" not in clone for clone in wire["brand"]["clones"].values())
    shared_once = len(split_css_blocks(SHARED)) + 1
    assert len(wire["css_rules"]) == shared_once, "shared blocks are sent once"
    assert all(CLONE_CLASS_MARK in rule or "WRAP" not in rule for rule in wire["css_rules"])
    assert unpack_clone_css(wire) == original


def test_a_section_whose_css_already_holds_the_marker_travels_as_it_is() -> None:
    odd = _clone("frag_" + "3" * 16, ".WRAP { content: '" + CLONE_CLASS_MARK + "' }")
    wire = pack_clone_css(_brand(odd))
    assert wire["brand"]["clones"][odd["id"]]["css"] == odd["css"]
    assert unpack_clone_css(wire) == _brand(odd)


def test_the_editor_is_sent_only_the_sections_the_site_places() -> None:
    used_page = _clone("frag_" + "a" * 16, SHARED)
    used_header = _clone("frag_" + "b" * 16, SHARED)
    unused = _clone("frag_" + "c" * 16, SHARED)
    brand = _brand(used_page, used_header, unused)
    site = {
        "pages": {"/": {"content": [
            {"type": "ClonedSection", "props": {"id": "s1", "fragmentId": used_page["id"]}},
            {"type": "ClonedSection", "props": {"id": "s2", "fragmentId": "frag_" + "d" * 16}},
            {"type": "CtaBand", "props": {"id": "s3"}},
        ]}},
        "shell": {
            "header": {
                "type": "ClonedSection", "props": {"id": "header", "fragmentId": used_header["id"]},
            },
            "footer": {"type": "SiteFooter", "props": {"id": "footer"}},
        },
    }

    trimmed = editor_site_brand(brand, site)

    assert set(trimmed["clones"]) == {used_page["id"], used_header["id"]}
    assert trimmed["assets"] == brand["assets"], "every captured image stays offered"
    assert set(brand["clones"]) == {used_page["id"], used_header["id"], unused["id"]}

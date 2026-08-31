"""D-F3 — what a whole cloned section may be gestured into (clone-fidelity F3.2).

The founder ruling is Option A, *top-level reordering only*: a whole fragment (hero, testimonial,
proof band) can be moved up or down the page, and it can NEVER be manually resized, be a drop
target for ordinary nodes, be internally re-laid-out, or be detached into editable nested
elements. The ruling names its own mechanics — ``Fragment`` joins ``movable_kinds`` and stays out
of ``resizable_kinds``/``parent_kinds`` — so this file pins exactly those three allowlists plus
the leaf-ness they rest on, from the ONE function the bridge script is built out of.

Pure: :func:`lumen_api.web_bridge._bridge_page_capabilities` is a function of the WebDoc, so a
test of *which nodes are offered which gesture* does not need a document, a database or a render.
The four assertions are deliberately in one place — "movable but not resizable and not a parent"
is a single ruling, and splitting it across files is how one half of it quietly gets reverted.
"""

from __future__ import annotations

from typing import Any

from lumen_api.web_bridge import _bridge_page_capabilities, render_bridge_script

FRAGMENT_ID = "frag_" + "ab" * 8


def _page_with_a_pinned_clone() -> dict[str, Any]:
    """The shape a pinned cloned section actually occupies: wrapper section + fragment leaf.

    `insert_cloned_section`/`recreate_cloned_page` build exactly this pair (LUMW0011: the page
    root holds sections and nothing else, and a fragment node is a LEAF), so the fixture is the
    production shape rather than a fragment floating at the root.
    """
    return {
        "pages": [
            {
                "id": "home",
                "root": "root",
                "nodes": {
                    "root": {"id": "root", "kind": "container", "children": ["sec_clone", "sec_b"]},
                    "sec_clone": {
                        "id": "sec_clone",
                        "kind": "section",
                        "children": ["frg_hero"],
                    },
                    "frg_hero": {
                        "id": "frg_hero",
                        "kind": "fragment",
                        "fragment_id": FRAGMENT_ID,
                    },
                    "sec_b": {"id": "sec_b", "kind": "section", "children": ["txt_a"]},
                    "txt_a": {"id": "txt_a", "kind": "text"},
                },
            }
        ]
    }


def test_a_whole_cloned_section_can_be_moved_but_never_resized_or_dropped_into() -> None:
    movable, drop_parents, resizable, root_id = _bridge_page_capabilities(
        _page_with_a_pinned_clone(), "home"
    )
    assert root_id == "root"
    # (1) movable — the whole ruling's positive half.
    assert "frg_hero" in movable
    # (2) never resizable: a cloned band's proportions are the clone.
    assert "frg_hero" not in resizable
    # (3) never a drop target: an ordinary node dropped inside would be an internal edit.
    assert "frg_hero" not in drop_parents
    # (4) the neighbours are unaffected — this is one kind joining one allowlist, not a rewrite.
    assert "sec_clone" in movable and "sec_clone" in drop_parents
    assert "txt_a" in resizable


def test_the_bridge_script_carries_the_fragment_in_exactly_one_of_its_three_sets() -> None:
    """The allowlists reach the iframe as three baked-in JS sets; the ruling is about which."""
    script = render_bridge_script("nonce-df3-0001", _page_with_a_pinned_clone(), "home")
    movable = script.split("var MOVABLE_NODE_IDS = new Set(", 1)[1].split(");", 1)[0]
    drop = script.split("var DROP_PARENT_NODE_IDS = new Set(", 1)[1].split(");", 1)[0]
    resize = script.split("var RESIZABLE_NODE_IDS = new Set(", 1)[1].split(");", 1)[0]
    assert "frg_hero" in movable
    assert "frg_hero" not in drop
    assert "frg_hero" not in resize

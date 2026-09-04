"""Slice 2 / Task 5: the bridge names every element and posts `annotate` addresses.

The hover chip must be able to name a band without a round trip, so the render bakes
the display name of every node on the page into the script — in the SAME order the
layers panel and the agent's TURN TARGET line use (`main._web_node_label`, ruling
R-A5). The script's half of the contract (the `annotate` message out, the
`annotations` badge message in) is asserted at the source level: the template is one
string, so its protocol words are checkable without a browser.
"""

from __future__ import annotations

from lumen_api.web_bridge import _bridge_node_names, render_bridge_script

FRAG = "frag_" + "ab" * 8


def _doc():
    return {
        "pages": [
            {
                "id": "home",
                "root": "root",
                "nodes": {
                    "root": {
                        "id": "root",
                        "kind": "container",
                        "children": ["sec_a", "sec_b"],
                    },
                    "sec_a": {"id": "sec_a", "kind": "section", "children": ["frg_a"]},
                    "frg_a": {"id": "frg_a", "kind": "fragment", "fragment_id": FRAG},
                    "sec_b": {
                        "id": "sec_b",
                        "kind": "section",
                        "name": "Proof",
                        "children": ["txt"],
                    },
                    "txt": {
                        "id": "txt",
                        "kind": "text",
                        "content": "<p>135+ currencies</p>",
                    },
                },
            }
        ]
    }


def test_node_names_follow_the_shared_order():
    names = _bridge_node_names(
        _doc(), "home", {FRAG: {"label": "Stripe hero", "section_role": "hero"}}
    )
    assert names == {
        # A node with nothing cheap to say falls back to its kind rather than
        # dropping out of the map — a chip reading "Container" beats one reading
        # the raw tag name "div".
        "root": "Container",
        "sec_a": "Hero — Stripe hero",
        "frg_a": "Hero — Stripe hero",
        "sec_b": "Proof",
        "txt": "135+ currencies",
    }


def test_script_carries_names_and_the_annotate_protocol():
    script = render_bridge_script("nonce-12345678", _doc(), "home", fragment_meta={})
    assert '"txt":"135+ currencies"' in script
    assert '"annotate"' in script and '"annotations"' in script
    assert "lumen-hover-label" in script and "lumen-annotation-badge" in script
    # The placeholder is fully substituted — no unrendered token survives.
    assert "__LUMEN_NODE_NAMES__" not in script
    # A registry the document's pin is not in is named honestly, never guessed.
    assert '"frg_a":"Cloned section"' in script


def test_names_are_escaped_so_a_label_can_never_close_the_script():
    doc = _doc()
    doc["pages"][0]["nodes"]["sec_b"]["name"] = "</script><img src=x>"
    script = render_bridge_script("nonce-12345678", doc, "home", fragment_meta={})
    assert "</script>" not in script
    assert "\\u003c/script\\u003e" in script


def test_an_unknown_page_yields_no_names_rather_than_the_wrong_page_s():
    assert _bridge_node_names(_doc(), "pricing", {}) == {}
    assert _bridge_node_names(None, "home", None) == {}

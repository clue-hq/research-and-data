"""Slice 2 / Task 5: the bridge names every element and posts `annotate` addresses.

The hover chip must be able to name a band without a round trip, so the render bakes
the display name of every node on the page into the script — in the SAME order the
layers panel and the agent's TURN TARGET line use (`main._web_node_label`, ruling
R-A5). The script's half of the contract (the `annotate` message out, the
`annotations` badge message in) is asserted at the source level: the template is one
string, so its protocol words are checkable without a browser.
"""

from __future__ import annotations

from lumen_api.web_bridge import (
    _bridge_node_names,
    _bridge_text_overrides,
    render_bridge_script,
)

FRAG = "frag_" + "ab" * 8

OVERRIDE = {
    "text": "Better economics",
    "bold": True,
    "italic": False,
    "underline": False,
    "size": 1,
}


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
                    "frg_a": {
                        "id": "frg_a",
                        "kind": "fragment",
                        "fragment_id": FRAG,
                        "text_overrides": {":nth-child(1)": dict(OVERRIDE)},
                    },
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


def test_only_a_clone_root_gets_a_structural_path():
    """Spec 3.1: vocabulary nodes have `path` absent.

    `data-fragment-root` — stamped by the engine on every clone wrapper in editor mode —
    is the whole truth about "am I inside somebody else's markup", and must be the ONLY
    test. An earlier draft ALSO pathed any id-less element under any owner, which caught
    a `<strong>` inside a vocabulary text node's rich-text markup and a plain child of a
    section or container. Those are not inside a clone, so the path travelled downstream
    and would be resolved against a fragment HTML that does not exist. Asserted at the
    source level because the branch lives in the injected script, not in Python.
    """
    script = render_bridge_script("nonce-12345678", _doc(), "home", fragment_meta={})
    assert 'var isFragment = owner.hasAttribute("data-fragment-root");' in script
    assert "var path = isFragment ? elementPath(el, owner) : null;" in script
    # The retired clause, in the exact shape it had. Its absence is the fix.
    assert '!el.hasAttribute("data-node-id")' not in script


# --- Slice 3 / Task 15: the clone text-edit gesture -------------------------------


def test_text_overrides_are_baked_in_for_the_rendered_page():
    """R-A6: an element that ALREADY carries an override must open its editor showing
    that override's marks, size and words — not the DOM's.

    The DOM is not the source of truth for an overridden element: the engine renders the
    override's text inside `strong > em > u` wrappers, so reading marks back out of the
    markup would be a second, divergent parser. The render bakes the canonical map in
    instead, exactly as it bakes the node names.
    """
    assert _bridge_text_overrides(_doc(), "home") == {
        "frg_a": {":nth-child(1)": OVERRIDE}
    }


def test_a_page_without_overrides_or_an_unknown_page_bakes_an_empty_map():
    doc = _doc()
    doc["pages"][0]["nodes"]["frg_a"].pop("text_overrides")
    assert _bridge_text_overrides(doc, "home") == {}
    # Same posture as `_bridge_node_names`: an unknown page yields nothing rather than
    # another page's overrides, which would open the editor on the wrong words.
    assert _bridge_text_overrides(_doc(), "pricing") == {}
    assert _bridge_text_overrides(None, "home") == {}


def test_an_empty_override_map_on_a_pin_is_omitted_rather_than_carried():
    doc = _doc()
    doc["pages"][0]["nodes"]["frg_a"]["text_overrides"] = {}
    assert _bridge_text_overrides(doc, "home") == {}


def test_script_carries_the_clone_text_edit_protocol():
    script = render_bridge_script("nonce-12345678", _doc(), "home", fragment_meta={})
    # The two messages out and the one message in.
    assert '"clone-text-commit"' in script
    assert '"clone-text-cancel"' in script
    assert '"edit-text"' in script
    # The in-frame editor itself: a constrained plain-text field plus its toolbar.
    assert "lumen-clone-toolbar" in script
    assert "contenteditable" in script
    assert "beginCloneEditing" in script
    # The placeholder is fully substituted — no unrendered token survives.
    assert "__LUMEN_TEXT_OVERRIDES__" not in script
    assert '"frg_a":{":nth-child(1)":{' in script
    assert '"text":"Better economics"' in script


def test_override_text_is_escaped_so_a_retyped_headline_can_never_close_the_script():
    doc = _doc()
    doc["pages"][0]["nodes"]["frg_a"]["text_overrides"][":nth-child(1)"]["text"] = (
        "</script><img src=x>"
    )
    script = render_bridge_script("nonce-12345678", doc, "home", fragment_meta={})
    assert "</script>" not in script
    assert "\\u003c/script\\u003e" in script

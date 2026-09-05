"""The agent turn's page-awareness (F5 multi-page, task 7).

Until F5 the turn side of the design API spelled "the page" as the literal string ``"home"``:
the fragment package it handed the runtime resolved only the home page's pins, and the TURN
TARGET brief line looked the user's selection up in the home page's node map. A document with a
second page therefore lost both — a cloned band on ``/pricing`` came back as the engine's
placeholder in the agent's own screenshots, and a selection made on ``/pricing`` read as "that
element no longer exists in the page".

These tests are PURE: they exercise the two walks over a hand-built WebDoc, no client, no
database, no storage.
"""

from __future__ import annotations


def test_all_fragment_ids_unions_pages_in_order():
    from lumen_api.fragments.render import web_doc_all_fragment_ids

    doc = {
        "pages": [
            {
                "id": "home",
                "root": "r1",
                "nodes": {
                    "r1": {"id": "r1", "kind": "container", "children": ["f1"]},
                    "f1": {
                        "id": "f1",
                        "kind": "fragment",
                        "fragment_id": "frag_a",
                        "children": [],
                    },
                },
            },
            {
                "id": "pricing",
                "root": "r2",
                "nodes": {
                    "r2": {"id": "r2", "kind": "container", "children": ["f2", "f3"]},
                    "f2": {
                        "id": "f2",
                        "kind": "fragment",
                        "fragment_id": "frag_b",
                        "children": [],
                    },
                    "f3": {
                        "id": "f3",
                        "kind": "fragment",
                        "fragment_id": "frag_a",
                        "children": [],
                    },
                },
            },
        ]
    }
    assert web_doc_all_fragment_ids(doc) == ["frag_a", "frag_b"]


def test_turn_targets_are_found_on_any_page():
    from lumen_api.main import _describe_web_turn_targets

    doc = {
        "pages": [
            {
                "id": "home",
                "root": "r1",
                "nodes": {"r1": {"id": "r1", "kind": "container", "children": []}},
            },
            {
                "id": "pricing",
                "root": "r2",
                "nodes": {
                    "r2": {"id": "r2", "kind": "container", "children": ["s"]},
                    "s": {"id": "s", "kind": "section", "children": ["t"]},
                    "t": {"id": "t", "kind": "text", "children": []},
                },
            },
        ]
    }
    text = _describe_web_turn_targets(doc, ["t"])
    assert "pricing" in text and "t" in text


def test_turn_target_names_a_clone_like_the_frontend_does():
    """R-A5: the agent's TURN TARGET line names a node with the same order the shell's
    layers panel uses (`displayNameForNode`), so a human and the agent say the same words
    about the same band. The fragment's name is the registry's role + label."""
    from lumen_api.main import _describe_web_turn_targets

    frag = "frag_" + "ab" * 8
    doc = {
        "pages": [
            {
                "id": "home",
                "root": "r",
                "nodes": {
                    "r": {"id": "r", "kind": "container", "children": ["s"]},
                    "s": {"id": "s", "kind": "section", "children": ["f"]},
                    "f": {"id": "f", "kind": "fragment", "fragment_id": frag},
                },
            }
        ]
    }
    meta = {frag: {"label": "Stripe homepage hero", "section_role": "hero"}}
    text = _describe_web_turn_targets(doc, ["f"], fragment_meta=meta)
    assert 'fragment "Hero — Stripe homepage hero"' in text


def test_a_section_wrapping_one_clone_inherits_its_name_and_an_unknown_pin_is_generic():
    """The other two halves of the shared order: a section whose only child is a fragment
    reads as that fragment, and a pin the registry does not hold (unreleased, or another
    workspace's) is named honestly rather than guessed at."""
    from lumen_api.main import _describe_web_turn_targets

    doc = {
        "pages": [
            {
                "id": "home",
                "root": "r",
                "nodes": {
                    "r": {"id": "r", "kind": "container", "children": ["s", "s2"]},
                    "s": {"id": "s", "kind": "section", "children": ["f"]},
                    "f": {"id": "f", "kind": "fragment", "fragment_id": "frag_known"},
                    "s2": {"id": "s2", "kind": "section", "children": ["f2"]},
                    "f2": {"id": "f2", "kind": "fragment", "fragment_id": "frag_gone"},
                },
            }
        ]
    }
    meta = {
        "frag_known": {"label": "Pricing table", "section_role": None},
        "frag_gone": {"label": None, "section_role": None},
    }
    text = _describe_web_turn_targets(doc, ["s", "s2"], fragment_meta=meta)
    assert 'section "Pricing table"' in text
    assert 'section "Cloned section"' in text


def test_annotations_are_numbered_and_resolved_against_the_clone():
    """R-A2: a marketer's note about one element inside a cloned band reaches the agent as a
    numbered ANNOTATION line that NAMES that element — resolved against the clone's real
    stored HTML, not guessed at from the path string.

    The two notes here are the two outcomes: a path the artifact still has (named, with the
    words it currently reads) and one it does not (said so, out loud, with the fallback the
    rest of this brief uses). The numbers come from the human's own "1." / "2." prefixes.
    """
    from lumen_api.main import _describe_web_turn_targets

    frag = "frag_" + "ab" * 8
    doc = {
        "pages": [
            {
                "id": "home",
                "root": "r",
                "nodes": {
                    "r": {"id": "r", "kind": "container", "children": ["s"]},
                    "s": {"id": "s", "kind": "section", "children": ["f"]},
                    "f": {"id": "f", "kind": "fragment", "fragment_id": frag},
                },
            }
        ]
    }
    html = '<section><h2 data-lumen-slot="headline">Card economics</h2></section>'
    text = _describe_web_turn_targets(
        doc,
        ["f"],
        fragment_meta={frag: {"label": "Stripe hero", "section_role": "hero"}},
        target_notes=[
            {
                "target": "f",
                "path": ":nth-child(1) > :nth-child(1)",
                "note": "1. Make this shorter",
            },
            {"target": "f", "path": ":nth-child(7)", "note": "2. Bolder"},
        ],
        read_source=lambda fid: {"html": html},
    )
    assert 'ANNOTATION 1: on fragment "Hero — Stripe hero"' in text
    assert (
        "element `h2 · headline` at path `:nth-child(1) > :nth-child(1)` "
        'reading "Card economics"'
    ) in text
    assert '"1. Make this shorter"' in text
    assert "ANNOTATION 2" in text and "no longer resolves" in text
    # An annotated target does NOT also get the un-annotated TURN TARGET line: the
    # annotation already says which node, which page and which section.
    assert "TURN TARGET" not in text


def test_an_unannotated_target_keeps_its_turn_target_line_beside_the_annotations():
    """Mixed selections stay honest: the node the human wrote about reads as an ANNOTATION,
    the one they only selected keeps the line it has always had, byte for byte."""
    from lumen_api.main import _describe_web_turn_targets

    doc = {
        "pages": [
            {
                "id": "home",
                "root": "r",
                "nodes": {
                    "r": {"id": "r", "kind": "container", "children": ["s", "s2"]},
                    "s": {"id": "s", "kind": "section", "children": []},
                    "s2": {"id": "s2", "kind": "section", "children": []},
                },
            }
        ]
    }
    text = _describe_web_turn_targets(
        doc,
        ["s", "s2"],
        target_notes=[{"target": "s2", "path": None, "note": "Warmer, please"}],
    )
    assert "TURN TARGET: the user selected `s`" in text
    assert "TURN TARGET: the user selected `s2`" not in text
    # No leading "N." in the note → the 1-based submission order numbers it.
    assert 'ANNOTATION 1: on section (page `home`, section `s2`) — "Warmer, please"' in text


def test_a_note_on_a_vanished_node_says_so_instead_of_inventing_a_section():
    from lumen_api.main import _describe_web_turn_targets

    doc = {"pages": [{"id": "home", "root": "r", "nodes": {"r": {"id": "r", "kind": "container"}}}]}
    text = _describe_web_turn_targets(
        doc, ["gone"], target_notes=[{"target": "gone", "path": None, "note": "3. Drop it"}]
    )
    assert "ANNOTATION 3" in text
    assert "no longer exists in the page" in text
    assert '"3. Drop it"' in text


def test_an_annotation_path_is_counted_over_the_markup_the_browser_actually_saw():
    """Slice 3: the path rides in from the BROWSER, which measured it against the RENDERED
    clone — and a slot bound `{"visible": false}` drops its whole element from that render.
    Counted naively over the stored artifact the same address lands one element early (here:
    on the badge nobody can see instead of the headline the marketer wrote about), and the
    agent is told the wrong words. The node's own hidden slot keys are what reconcile the
    two walks."""
    from lumen_api.main import _describe_web_turn_targets

    frag = "frag_" + "cd" * 8
    doc = {
        "pages": [
            {
                "id": "home",
                "root": "r",
                "nodes": {
                    "r": {"id": "r", "kind": "container", "children": ["s"]},
                    "s": {"id": "s", "kind": "section", "children": ["f"]},
                    "f": {
                        "id": "f",
                        "kind": "fragment",
                        "fragment_id": frag,
                        "slots": {"badge": {"visible": False}},
                    },
                },
            }
        ]
    }
    html = (
        "<section>"
        '<span data-lumen-slot="badge">New</span>'
        "<h2>Card economics</h2>"
        "</section>"
    )
    text = _describe_web_turn_targets(
        doc,
        ["f"],
        fragment_meta={frag: {"label": "Stripe hero", "section_role": "hero"}},
        target_notes=[
            {
                "target": "f",
                "path": ":nth-child(1) > :nth-child(1)",
                "note": "1. Make this shorter",
            }
        ],
        read_source=lambda fid: {"html": html},
    )
    assert 'element `h2` at path `:nth-child(1) > :nth-child(1)` reading "Card economics"' in text
    assert "New" not in text

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

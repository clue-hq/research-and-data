"""Resolving the bridge's structural path against a clone's stored HTML (spec §3.1).

An annotation made inside a cloned band names its element by POSITION, because nothing in
there carries an id of its own — the markup is the harvested artifact's. The bridge builds
that address from the clone's wrapper down (`elementPath` in ``web_bridge.py``, measured from
the element the engine stamps ``data-fragment-root`` on). These tests pin the server-side
mirror of that same walk: 1-based, element children only, and ``None`` — never a guess —
when the path is malformed or points at something the artifact no longer has.

The ORIGIN matters and is the subtle part: the engine renders a clone as
``<div class="lumen-fragment …" data-node-id=… data-fragment-root>`` + the artifact's stored
HTML verbatim. So the wrapper's element children ARE the stored HTML's top-level elements,
and a path's first step names one of those — here, the ``<section>``.
"""

from __future__ import annotations

from lumen_api.fragments.paths import resolve_structural_path

HTML = (
    '<section><div><h2 data-lumen-slot="headline">Card <em>economics</em></h2>'
    "<p>Body</p></div><img src=\"x\"></section>"
)


def test_a_path_resolves_to_tag_text_and_slot():
    assert resolve_structural_path(HTML, ":nth-child(1) > :nth-child(1) > :nth-child(1)") == {
        "tag": "h2",
        "text": "Card economics",
        "slot": "headline",
    }
    assert resolve_structural_path(HTML, ":nth-child(1) > :nth-child(1) > :nth-child(2)") == {
        "tag": "p",
        "text": "Body",
        "slot": None,
    }
    assert resolve_structural_path(HTML, ":nth-child(1) > :nth-child(2)") == {
        "tag": "img",
        "text": "",
        "slot": None,
    }
    assert resolve_structural_path(HTML, ":nth-child(1)") == {
        "tag": "section",
        "text": "Card economics Body",
        "slot": None,
    }


def test_a_dead_or_malformed_path_is_none():
    assert resolve_structural_path(HTML, ":nth-child(9)") is None
    assert resolve_structural_path(HTML, ":nth-child(1) > :nth-child(9)") is None
    assert resolve_structural_path(HTML, "div > h2") is None
    assert resolve_structural_path(HTML, ":nth-child(0)") is None
    assert resolve_structural_path(HTML, "") is None
    assert resolve_structural_path(HTML, None) is None
    assert resolve_structural_path("", ":nth-child(1)") is None

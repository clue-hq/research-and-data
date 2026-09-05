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


# --------------------------------------------------------------------------- #
# The hidden-slot mirror
# --------------------------------------------------------------------------- #

HIDDEN_HTML = '<section><span data-lumen-slot="badge">New</span><h2>Title</h2></section>'


def test_a_hidden_slot_is_not_counted_when_the_walk_is_told_which_slots_are_hidden():
    """The path the browser measured was measured against the RENDERED markup, and a
    `Visible(false)` slot value drops its whole element from that render (the engine's slot
    pass). So the same address counted over the STORED artifact is off by one per hidden
    sibling before the target — which is how a note on the headline resolved to the badge
    nobody can see. Told which slots the node hides, the walk skips them exactly the way the
    render does."""
    assert resolve_structural_path(
        HIDDEN_HTML, ":nth-child(1) > :nth-child(1)", hidden_slot_keys={"badge"}
    ) == {"tag": "h2", "text": "Title", "slot": None}
    # Without the hidden set — an unpersonalized clone — the very same path is the badge.
    assert resolve_structural_path(HIDDEN_HTML, ":nth-child(1) > :nth-child(1)") == {
        "tag": "span",
        "text": "New",
        "slot": "badge",
    }


def test_a_hidden_element_is_not_descended_into_either():
    """A hidden element is not on the page at all, so nothing inside it is addressable:
    the walk must not count it AND must not be able to land within it."""
    html = (
        '<section><div data-lumen-slot="badge"><b>Inner</b></div><h2>Title</h2></section>'
    )
    assert (
        resolve_structural_path(
            html, ":nth-child(1) > :nth-child(1) > :nth-child(1)", hidden_slot_keys={"badge"}
        )
        is None
    )

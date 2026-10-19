"""Rendering a cloned section, on both preview paths (clone-fidelity F1.3).

Task 6 made a fragment safe and gave it durable custody. This file pins what happens when a
document that pins one is turned into HTML: the API resolves the artifact, the engine emits its
markup in flow under the ONE wrapper class both languages agree on, and the artifact's scoped CSS
lands in the head where a compiled utility still outranks it.

Two preview paths exist and a fragment must render on BOTH — the editor render route and the
agent's in-loop `render_web_preview`. A section that appears in the editor and vanishes from the
agent's screenshot (or the reverse) is the exact failure this file's dual coverage exists to
prevent.

DB-backed where the registry is involved (the artifact really is read out of custody), pure where
the helper is pure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from clue_storage import FsStorage
from fastapi.testclient import TestClient

from conftest import make_client

from lumen_api.design_store import HybridRepository
from lumen_api.fragments import (
    create_web_fragment,
    fragment_wrapper_class,
    set_web_fragment_status,
)
from lumen_api.fragments.slots import SlotSpec
from lumen_api.fragments.render import (
    build_fragment_render_package,
    css_class_names,
    fragment_collision_diagnostics,
    fragment_css_sheet,
    fragment_render_map,
    web_doc_class_tokens,
    web_doc_fragment_ids,
)
from lumen_api.main import create_app

SENTINEL = "Care, on your terms"
HTML = (
    f'<section class="clone-hero"><h1 class="clone-head">{SENTINEL}</h1>'
    '<a class="clone-cta" href="https://insight.example/demo">Book a demo</a></section>'
)
CSS = ".clone-hero { padding: 64px } .clone-head { color: #123456 }"
SOURCE_URL = "https://insight.example/"

#: A 64-hex digest standing in for bytes F0 already rehosted.
CLONE_DIGEST = "11" * 32
SLOTTED_HTML = (
    f'<section class="clone-hero"><h1 class="clone-head">{SENTINEL}</h1>'
    f'<img class="clone-logo" src="/asset-store/{CLONE_DIGEST}" alt="Clone Co">'
    '<a class="clone-cta" href="https://insight.example/demo">Book a demo</a></section>'
)
SLOT_SPECS = (
    SlotSpec(selector="h1.clone-head", key="headline", kind="text"),
    SlotSpec(selector="img.clone-logo", key="logo", kind="image"),
    SlotSpec(selector="a.clone-cta", key="cta", kind="href"),
)


@pytest.fixture()
def client(tmp_path: Path, design_storage: FsStorage) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache", storage=design_storage))


def _mint(workspace_id: str, storage: FsStorage, *, html: str = HTML, css: str = CSS):
    """Mint one fragment AND release it, so a document may pin it.

    The release is not decoration. F2.2 added the status half of the document-write reference
    gate: ingestion mints every cloned section ``draft`` and a human releases it by approving the
    brand kit it came from, so a NEW pin of a draft is refused. These render tests are about what
    a released section LOOKS like on a page, which means they have to start from one — the same
    correction ``test_web_fragments.py::_pinnable`` made for the gate suite. The status rules
    themselves — the kit-approval cascade and every arm of the reference gate — are pinned in
    ``test_ingestion_fragment_pipeline.py`` ("the human gate" / "the reference gate"), and the
    row-level lifecycle flag in ``test_web_fragments.py``.
    """
    row, artifact = create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=html,
        css=css,
        rehosted={},
        source_url=SOURCE_URL,
        section_role="hero",
    )
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=row["fragment_id"], status="approved"
    )
    return artifact


def _fragment_node(node_id: str, fragment_id: str, classes: str = "w-full py-12") -> dict[str, Any]:
    return {
        "id": node_id,
        "kind": "fragment",
        "fragment_id": fragment_id,
        "classes": classes,
    }


def _web_doc(document_id: str, *nodes: dict[str, Any], root_classes: str = "") -> dict[str, Any]:
    node_map = {
        "root": {
            "id": "root",
            "kind": "container",
            "classes": root_classes,
            "children": [node["id"] for node in nodes],
        }
    }
    for node in nodes:
        node_map[node["id"]] = node
    return {
        "schema_version": 1,
        "id": document_id,
        "title": "Fragment fixture",
        "pages": [
            {
                "id": "home",
                "name": "Home",
                "route": "/",
                "root": "root",
                "nodes": node_map,
            }
        ],
        "assets": {},
        "custom_css": "",
    }


# --------------------------------------------------------------------------- #
# The pure helpers: which artifacts a page needs, and what collides
# --------------------------------------------------------------------------- #


def test_the_walk_finds_every_reachable_fragment_once_and_no_orphan() -> None:
    doc = _web_doc(
        "doc_walk",
        _fragment_node("n1", "frag_" + "ab" * 8),
        _fragment_node("n2", "frag_" + "ab" * 8),
        _fragment_node("n3", "frag_" + "cd" * 8),
    )
    # An orphan is in the node map but off the tree: it is not on the page, so
    # resolving its artifact would splice CSS for a section nobody can see.
    doc["pages"][0]["nodes"]["orphan"] = _fragment_node("orphan", "frag_" + "ef" * 8)
    assert web_doc_fragment_ids(doc, "home") == ["frag_" + "ab" * 8, "frag_" + "cd" * 8]
    assert web_doc_fragment_ids(doc, "no-such-page") == web_doc_fragment_ids(doc, "home")
    assert web_doc_fragment_ids({"pages": []}, "home") == []


def test_a_document_with_no_fragments_needs_nothing_resolved() -> None:
    doc = _web_doc("doc_plain", {"id": "n1", "kind": "container", "classes": "", "children": []})
    assert web_doc_fragment_ids(doc, "home") == []


def test_class_scans_read_both_sides_of_the_collision() -> None:
    assert css_class_names(".lumen-frag-aa .clone-hero > .clone-head:hover { color: red }") == {
        "lumen-frag-aa",
        "clone-hero",
        "clone-head",
    }
    doc = _web_doc(
        "doc_classes",
        _fragment_node("n1", "frag_" + "ab" * 8, classes="clone-hero py-12"),
        root_classes="bg-light",
    )
    assert web_doc_class_tokens(doc, "home") == {"bg-light", "clone-hero", "py-12"}


def test_a_fragment_class_that_is_also_a_live_utility_is_reported_not_refused() -> None:
    """The ledgered cascade risk: compiled utilities land after fragment CSS, so a cloned class
    that is ALSO a class the document authors gets overruled. Scoping shields the ordinary case;
    this diagnostic names the case it cannot shield."""
    fragment_id = "frag_" + "ab" * 8
    wrapper = fragment_wrapper_class(fragment_id)
    package = {
        "schema_version": 1,
        "fragments": {
            fragment_id: {
                "html": HTML,
                "css": f".{wrapper} .clone-hero {{ padding: 64px }}",
            }
        },
        "missing": [],
    }
    clean = _web_doc("doc_ok", _fragment_node("n1", fragment_id, classes="w-full"))
    assert fragment_collision_diagnostics(package, clean, "home") == []

    colliding = _web_doc("doc_clash", _fragment_node("n1", fragment_id, classes="clone-hero"))
    diagnostics = fragment_collision_diagnostics(package, colliding, "home")
    assert len(diagnostics) == 1
    assert diagnostics[0]["code"] == "fragment.class_collision"
    assert diagnostics[0]["severity"] == "warning"
    assert "clone-hero" in diagnostics[0]["message"]
    assert fragment_id in diagnostics[0]["message"]
    # The wrapper class is ours and is on the wrapper by construction; reporting
    # it as a collision would be noise on every single fragment.
    wrapper_clash = _web_doc("doc_wrap", _fragment_node("n1", fragment_id, classes=wrapper))
    assert fragment_collision_diagnostics(package, wrapper_clash, "home") == []


# --------------------------------------------------------------------------- #
# Resolution out of durable custody
# --------------------------------------------------------------------------- #


def test_the_package_reads_each_artifact_once_and_keeps_it_identifiable(
    workspace_id: str, design_storage: FsStorage
) -> None:
    first = _mint(workspace_id, design_storage)
    second = _mint(workspace_id, design_storage, css=CSS.replace("64px", "80px"))
    doc = _web_doc(
        "doc_pkg",
        _fragment_node("n1", first.fragment_id),
        _fragment_node("n2", second.fragment_id),
        _fragment_node("n3", first.fragment_id),
    )
    package = build_fragment_render_package(
        design_storage, workspace_id=workspace_id, web_doc=doc, page_id="home"
    )
    assert set(package["fragments"]) == {first.fragment_id, second.fragment_id}
    assert package["missing"] == []
    assert package["fragments"][first.fragment_id]["html"] == first.payload["html"]

    ids = web_doc_fragment_ids(doc, "home")
    # The map the engine gets carries markup and nothing else — CSS goes to the
    # head through the theme, never into a node.
    render_map = fragment_render_map(package, ids)
    assert set(render_map) == {first.fragment_id, second.fragment_id}
    # Markup plus the slot KINDS the engine cannot know on its own (F1.4) —
    # and still no CSS.
    assert set(render_map[first.fragment_id]) == {"html", "slot_kinds"}

    sheet = fragment_css_sheet(package, ids)
    # Per-fragment identity survives concatenation: a rule in the head can be
    # traced back to the artifact it came from.
    assert f"/* fragment {first.fragment_id} */" in sheet
    assert f"/* fragment {second.fragment_id} */" in sheet
    assert first.payload["css"] in sheet
    assert second.payload["css"] in sheet
    # Deterministic: same page, same bytes.
    assert fragment_css_sheet(package, ids) == sheet


def test_the_render_map_carries_each_slots_kind(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """The engine never sees a slot manifest — it is API-side — but it cannot substitute without
    the kinds: an href and a paragraph both ride the node's ``text`` tag, so the kind is the only
    thing that says which one a value is. F1.4 threads them alongside the markup."""
    _row, artifact = create_web_fragment(
        design_storage,
        workspace_id=workspace_id,
        html=SLOTTED_HTML,
        css=CSS,
        rehosted={},
        source_url=SOURCE_URL,
        section_role="hero",
        slots=SLOT_SPECS,
    )
    doc = _web_doc("doc_kinds", _fragment_node("n1", artifact.fragment_id))
    package = build_fragment_render_package(
        design_storage, workspace_id=workspace_id, web_doc=doc, page_id="home"
    )
    entry = package["fragments"][artifact.fragment_id]
    assert entry["slot_kinds"] == {"headline": "text", "logo": "image", "cta": "href"}

    render_map = fragment_render_map(package, web_doc_fragment_ids(doc, "home"))
    assert render_map[artifact.fragment_id]["slot_kinds"] == entry["slot_kinds"]


def test_an_unresolvable_pin_is_named_not_guessed(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """The F1.2 gate deliberately keeps a document with a dead pin loadable, so resolution has to
    survive one."""
    artifact = _mint(workspace_id, design_storage)
    unknown = "frag_" + "99" * 8
    doc = _web_doc(
        "doc_missing",
        _fragment_node("n1", artifact.fragment_id),
        _fragment_node("n2", unknown),
    )
    package = build_fragment_render_package(
        design_storage, workspace_id=workspace_id, web_doc=doc, page_id="home"
    )
    assert set(package["fragments"]) == {artifact.fragment_id}
    assert package["missing"] == [unknown]


def test_another_workspaces_fragment_is_unresolvable_here(
    workspace_id: str, design_storage: FsStorage
) -> None:
    other = f"{workspace_id}_owner"
    artifact = _mint(other, design_storage)
    doc = _web_doc("doc_cross", _fragment_node("n1", artifact.fragment_id))
    package = build_fragment_render_package(
        design_storage, workspace_id=workspace_id, web_doc=doc, page_id="home"
    )
    assert package["fragments"] == {}
    assert package["missing"] == [artifact.fragment_id]


# --------------------------------------------------------------------------- #
# Preview path 1: the editor render route
# --------------------------------------------------------------------------- #


def _render(client: TestClient, document_id: str, **params: Any) -> dict[str, Any]:
    response = client.get(f"/documents/{document_id}/web/render", params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_editor_render_route_renders_the_artifact_in_flow(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    artifact = _mint(workspace_id, design_storage)
    store = HybridRepository(workspace_id=workspace_id)
    store.create_document(
        _web_doc("doc_editor", _fragment_node("n1", artifact.fragment_id)), doc_kind="web"
    )

    rendered = _render(client, "doc_editor")
    html = rendered["html"]

    # The cross-language agreement, in one assertion chain: the class the render
    # emits IS the class the Python helper mints IS a class the stored CSS
    # actually declares. A re-spelling anywhere renders the section unstyled.
    wrapper = fragment_wrapper_class(artifact.fragment_id)
    assert f'<div class="lumen-fragment {wrapper} w-full py-12"' in html
    assert f".{wrapper} " in artifact.payload["css"]
    # The artifact's markup, verbatim.
    assert SENTINEL in html
    assert 'class="clone-hero"' in html
    # Its scoped CSS, in the head, before the body it styles.
    css_at = html.index(f".{wrapper} .clone-hero")
    assert css_at < html.index("</head>")
    assert not rendered["diagnostics"], rendered["diagnostics"]


def test_the_editor_route_degrades_to_a_placeholder_on_a_dead_pin(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    from sqlalchemy import text

    from lumen_api.design_store import DesignStoreBridge

    artifact = _mint(workspace_id, design_storage)
    store = HybridRepository(workspace_id=workspace_id)
    store.create_document(
        _web_doc("doc_dead", _fragment_node("n1", artifact.fragment_id)), doc_kind="web"
    )
    DesignStoreBridge(workspace_id)._run(
        lambda conn: conn.execute(
            text("DELETE FROM design_web_fragment WHERE fragment_id = :f AND workspace_id = :w"),
            {"f": artifact.fragment_id, "w": workspace_id},
        )
    )

    rendered = _render(client, "doc_dead")
    assert 'data-fragment-placeholder="true"' in rendered["html"]
    assert SENTINEL not in rendered["html"]
    codes = [diagnostic["code"] for diagnostic in rendered["diagnostics"]]
    assert "LUMW0412" in codes


def test_the_editor_route_reports_a_class_collision_without_refusing_the_render(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    artifact = _mint(workspace_id, design_storage)
    store = HybridRepository(workspace_id=workspace_id)
    store.create_document(
        _web_doc(
            "doc_collide",
            _fragment_node("n1", artifact.fragment_id, classes="clone-hero w-full"),
        ),
        doc_kind="web",
    )
    rendered = _render(client, "doc_collide")
    assert SENTINEL in rendered["html"]
    collisions = [
        diagnostic
        for diagnostic in rendered["diagnostics"]
        if diagnostic["code"] == "fragment.class_collision"
    ]
    assert len(collisions) == 1
    assert "clone-hero" in collisions[0]["message"]


def test_the_selection_bridge_tolerates_a_fragment_node(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    """The other Python surface that enumerates node kinds.

    `render_bridge_script` builds the editor's movable/droppable/resizable id lists from a kind
    allowlist, and what this file pins is that a page carrying a fragment still renders WITH the
    bridge on it.

    **Amended by F3.2.** The gestures a fragment is offered were "none of them" while Phase F3
    had not ruled; founder ruling D-F3 (Option A, top-level reordering only) since put it in the
    movable list and left it out of the other two. That is one line here and a whole file over in
    `test_fragment_mobility.py`, which owns the ruling's four assertions — this one keeps its own
    subject, which is that the script survives the node at all.
    """
    artifact = _mint(workspace_id, design_storage)
    store = HybridRepository(workspace_id=workspace_id)
    store.create_document(
        _web_doc(
            "doc_bridge",
            {"id": "sec_a", "kind": "section", "classes": "", "children": ["n1"]},
            _fragment_node("n1", artifact.fragment_id),
        ),
        doc_kind="web",
    )
    rendered = _render(client, "doc_bridge", bridge=1, nonce="f1-3-bridge-1")
    assert SENTINEL in rendered["html"]

    from lumen_api.web_bridge import _bridge_page_capabilities

    document = store.require_document("doc_bridge")
    movable, drop_parents, resizable, root_id = _bridge_page_capabilities(
        document["scene"], "home"
    )
    assert root_id == "root"
    assert "sec_a" in movable, "the section is still gesture-capable"
    # D-F3: the whole band moves up and down the page, and does nothing else.
    assert "n1" in movable
    assert "n1" not in resizable
    assert "n1" not in drop_parents


# --------------------------------------------------------------------------- #
# Preview path 2: the agent turn's composition
# --------------------------------------------------------------------------- #


def test_the_web_turn_hands_the_agent_runtime_the_resolved_package(
    tmp_path: Path,
    workspace_id: str,
    design_storage: FsStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The agent's preview must see the same artifacts the editor's does.

    A web turn is leased fleet work with no HTTP request and no database handle of its own, so
    the API resolves at composition and the package rides the runtime config by value — exactly
    as `asset_library` does. The agent-side half of this seam is pinned in the runtime's own
    suite (`tests/test_web_fragment_preview.py`).
    """
    import lumen_agent.harness_web as harness_web
    import lumen_agent.llm as agent_llm

    from lumen_api import main as main_mod

    artifact = _mint(workspace_id, design_storage)
    captured: dict[str, Any] = {}

    def _fake_turn(
        *,
        prompt,
        config,
        initial_web_doc,
        event_sink,
        checkpointer,
        thread_id,
        cancel_requested=None,
        callbacks=None,
    ):
        captured["config"] = config
        return {
            "status": "applied",
            "outcome": "completed",
            "summary": "stubbed",
            "web_doc": initial_web_doc,
            "operations": [],
        }

    monkeypatch.setattr(harness_web, "run_deepagent_web_turn", _fake_turn)
    monkeypatch.setattr(agent_llm, "assert_model_supports_image_input", lambda *a, **k: None)

    class _Blobs:
        workspace_id = None
        storage = design_storage

    blobs = _Blobs()
    blobs.workspace_id = workspace_id

    response = main_mod.run_web_agent_turn(
        {"scene": _web_doc("doc_turn", _fragment_node("n1", artifact.fragment_id))},
        "Refresh the hero copy",
        None,
        Path(__file__).resolve().parents[3],
        workspace_id=workspace_id,
        blobs=blobs,
        engine_cache_root=tmp_path / "engine-cache",
    )
    assert response["status"] == "applied", response
    package = captured["config"].fragment_render_package
    assert set(package["fragments"]) == {artifact.fragment_id}
    assert package["fragments"][artifact.fragment_id]["html"] == artifact.payload["html"]
    assert package["missing"] == []


def test_a_web_turn_on_a_fragmentless_document_carries_no_package(
    tmp_path: Path,
    workspace_id: str,
    design_storage: FsStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import lumen_agent.harness_web as harness_web
    import lumen_agent.llm as agent_llm

    from lumen_api import main as main_mod

    captured: dict[str, Any] = {}

    def _fake_turn(
        *,
        prompt,
        config,
        initial_web_doc,
        event_sink,
        checkpointer,
        thread_id,
        cancel_requested=None,
        callbacks=None,
    ):
        captured["config"] = config
        return {
            "status": "applied",
            "outcome": "completed",
            "summary": "stubbed",
            "web_doc": initial_web_doc,
            "operations": [],
        }

    monkeypatch.setattr(harness_web, "run_deepagent_web_turn", _fake_turn)
    monkeypatch.setattr(agent_llm, "assert_model_supports_image_input", lambda *a, **k: None)

    class _Blobs:
        workspace_id = None
        storage = design_storage

    blobs = _Blobs()
    blobs.workspace_id = workspace_id

    main_mod.run_web_agent_turn(
        {"scene": _web_doc("doc_turn_plain", {"id": "n1", "kind": "container", "classes": ""})},
        "Refresh the hero copy",
        None,
        Path(__file__).resolve().parents[3],
        workspace_id=workspace_id,
        blobs=blobs,
        engine_cache_root=tmp_path / "engine-cache",
    )
    assert captured["config"].fragment_render_package is None


def test_a_document_with_no_fragments_renders_exactly_as_before(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    store = HybridRepository(workspace_id=workspace_id)
    store.create_document(
        _web_doc("doc_none", {"id": "n1", "kind": "container", "classes": "", "children": []}),
        doc_kind="web",
    )
    rendered = _render(client, "doc_none")
    # Host CSS may name the isolation boundary; only real body wrappers mark pins.
    from selectolax.lexbor import LexborHTMLParser

    tree = LexborHTMLParser(rendered["html"])
    assert tree.css("body [data-lumen-fragment], body .lumen-fragment") == []
    assert "/* lumen-fragment css */" not in rendered["html"]


# --------------------------------------------------------------------------- #
# The artifact's OWN bytes, on a preview path (phase fix wave, FIX 1)
# --------------------------------------------------------------------------- #

#: What an artifact's markup and CSS actually carry: a ROOT-RELATIVE reference to the one public
#: byte route. Root-relative is correct in durable custody — the artifact must not bake in an
#: origin it cannot know — and it is exactly what makes rebasing at render time necessary.
OWNED_DIGEST = "ab" * 32
OWNED_HTML = (
    f'<section class="clone-hero"><img class="clone-art" src="/asset-store/{OWNED_DIGEST}" alt="">'
    f"<h1 class=\"clone-head\">{SENTINEL}</h1></section>"
)
OWNED_CSS = f".clone-hero {{ background-image: url(/asset-store/{OWNED_DIGEST}) }}"


def _owned_package(fragment_id: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "fragments": {
            fragment_id: {
                "html": OWNED_HTML,
                "css": f".{fragment_wrapper_class(fragment_id)} {OWNED_CSS[1:]}",
                "slot_kinds": {},
                "asset_digests": [OWNED_DIGEST],
            }
        },
        "missing": [],
    }


def test_an_artifacts_own_asset_reference_is_rebased_onto_the_render_origin() -> None:
    """The class the acceptance walk caught in pixels.

    A SLOT-bound asset resolves through `doc.assets` and the engine's `asset_base_url`, so it
    always worked. The artifact's OWN imagery does not go through the engine at all — the
    markup is emitted verbatim — so its root-relative `/asset-store/<digest>` reached a preview
    that has no origin to resolve it against (Playwright `set_content`, the editor's srcDoc) and
    404'd. Every image inside a cloned section was broken, in exactly the preview a reviewer
    judges, while the one asset kind anybody tested rendered fine.

    Rebasing belongs HERE, at the API layer, and not in the engine arm: the export renders with
    `asset_base_url="assets"`, so an engine-side rebase would emit `assets/<digest>` and the
    zip's `/asset-store/<digest>` rewrite would silently no-op — orphaned bytes and broken paths
    in the deliverable.
    """
    fragment_id = "frag_" + "cd" * 8
    package = _owned_package(fragment_id)
    base = "http://testserver/asset-store"

    rebased = fragment_render_map(package, [fragment_id], asset_base_url=base)
    assert f'src="{base}/{OWNED_DIGEST}"' in rebased[fragment_id]["html"]
    assert "/asset-store/" not in rebased[fragment_id]["html"].replace(base, "")

    sheet = fragment_css_sheet(package, [fragment_id], asset_base_url=base)
    assert f"url({base}/{OWNED_DIGEST})" in sheet


def test_delivery_keeps_the_root_relative_reference_untouched() -> None:
    """No base, no rewrite — byte-identical to what the artifact stored.

    The export and publish builds depend on this: publish serves that exact route, and the
    export REWRITES the prefix to a relative zip path afterwards. A rebase here would break
    both.
    """
    fragment_id = "frag_" + "cd" * 8
    package = _owned_package(fragment_id)

    assert (
        fragment_render_map(package, [fragment_id])[fragment_id]["html"] == OWNED_HTML
    )
    assert f"url(/asset-store/{OWNED_DIGEST})" in fragment_css_sheet(package, [fragment_id])
    # An already-correct base is a no-op rather than a doubling.
    assert (
        fragment_render_map(package, [fragment_id], asset_base_url="/asset-store")[fragment_id][
            "html"
        ]
        == OWNED_HTML
    )


def test_the_editor_route_serves_an_artifacts_own_image_from_this_requests_origin(
    client: TestClient, workspace_id: str, design_storage: FsStorage
) -> None:
    artifact = _mint(workspace_id, design_storage, html=OWNED_HTML, css=OWNED_CSS)
    store = HybridRepository(workspace_id=workspace_id)
    store.create_document(
        _web_doc("doc_owned", _fragment_node("n1", artifact.fragment_id)), doc_kind="web"
    )

    html = _render(client, "doc_owned")["html"]

    # The markup's own <img>…
    assert f'src="http://testserver/asset-store/{OWNED_DIGEST}"' in html
    # …and the CSS background, in the spelling the scoper really stores (it quotes its urls).
    assert f'url("http://testserver/asset-store/{OWNED_DIGEST}")' in html
    # Nothing root-relative survives on this path, in either place.
    assert f'src="/asset-store/{OWNED_DIGEST}"' not in html
    assert f'url("/asset-store/{OWNED_DIGEST}")' not in html


def test_an_annotation_inside_a_clone_names_the_element_from_the_real_stored_html(
    tmp_path: Path,
    workspace_id: str,
    design_storage: FsStorage,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """R-A2, end to end against a REAL minted artifact.

    A marketer points at the headline inside a cloned band and types a note. The path they
    produced is measured from the clone's rendered WRAPPER (the `data-fragment-root` div the
    engine emits), whose element children are exactly this artifact's top-level elements — so
    `:nth-child(1)` is the `<section>` and `:nth-child(1) > :nth-child(1)` is the `<h1>`. The
    brief must come back naming that `h1` and quoting what it currently says, which is only
    possible by reading the stored HTML out of durable custody here.

    This is the test that would catch an off-by-one in the resolution origin: resolving one
    level too deep would land on nothing and the line would say "no longer resolves".
    """
    import lumen_agent.harness_web as harness_web
    import lumen_agent.llm as agent_llm

    from lumen_api import main as main_mod

    artifact = _mint(workspace_id, design_storage)
    captured: dict[str, Any] = {}

    def _fake_turn(
        *,
        prompt,
        config,
        initial_web_doc,
        event_sink,
        checkpointer,
        thread_id,
        cancel_requested=None,
        callbacks=None,
    ):
        captured["prompt"] = prompt
        captured["config"] = config
        return {
            "status": "applied",
            "outcome": "completed",
            "summary": "stubbed",
            "web_doc": initial_web_doc,
            "operations": [],
        }

    monkeypatch.setattr(harness_web, "run_deepagent_web_turn", _fake_turn)
    monkeypatch.setattr(agent_llm, "assert_model_supports_image_input", lambda *a, **k: None)

    class _Blobs:
        workspace_id = None
        storage = design_storage

    blobs = _Blobs()
    blobs.workspace_id = workspace_id

    notes = [
        {
            "target": "n1",
            "path": ":nth-child(1) > :nth-child(1)",
            "note": "1. Make this shorter",
        },
        {"target": "n1", "path": ":nth-child(1) > :nth-child(9)", "note": "2. Bolder"},
    ]
    main_mod.run_web_agent_turn(
        {"scene": _web_doc("doc_annotated", _fragment_node("n1", artifact.fragment_id))},
        "Tighten the hero",
        None,
        Path(__file__).resolve().parents[3],
        target_node_ids=["n1"],
        target_notes=notes,
        workspace_id=workspace_id,
        blobs=blobs,
        engine_cache_root=tmp_path / "engine-cache",
    )

    prompt = captured["prompt"]
    assert (
        "ANNOTATION 1: on fragment " in prompt
    ), prompt
    assert (
        "element `h1` at path `:nth-child(1) > :nth-child(1)` "
        f'reading "{SENTINEL}"'
    ) in prompt, prompt
    assert '"1. Make this shorter"' in prompt
    # The second note points at a child the artifact does not have; it is SAID, not guessed at.
    assert "ANNOTATION 2" in prompt and "no longer resolves in this section" in prompt
    # The runtime gets the same facts by value, in the same submission order.
    assert captured["config"].turn_target_notes == notes

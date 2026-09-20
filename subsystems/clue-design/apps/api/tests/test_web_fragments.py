"""The fragment registry and the document-write reference gate (clone-fidelity F1.2).

Where ``test_web_fragment_artifact.py`` pins what a fragment IS, this file pins where it LIVES:
one immutable content-addressed payload in the design blob namespace, one row in
``design_web_fragment``, and a gate on the document write path that refuses a node pinned to a
fragment this workspace does not hold.

DB-backed (the row store is Postgres), with the suite's per-test workspace + disposable
``FsStorage``, exactly like the neighbouring ingestion and component suites.
"""

from __future__ import annotations

import hashlib
from typing import Any

import pytest
from clue_storage import FsStorage

from lumen_api.database import FragmentReferenceError, NotFoundError
from lumen_api.design_store import DesignBlobStore, DesignStoreBridge, HybridRepository
from lumen_api.fragments import (
    WEB_FRAGMENT_SOURCE_KEY,
    FragmentRefused,
    SlotSpec,
    attach_web_fragment_preview,
    create_web_fragment,
    fragment_wrapper_class,
    list_web_fragment_lineage,
    list_web_fragments,
    read_web_fragment,
    set_web_fragment_status,
    web_fragment_exists,
)

HTML = (
    '<section class="hero"><h1 class="head">Care, on your terms</h1>'
    '<a class="cta" href="https://insight.example/demo">Book a demo</a></section>'
)
CSS = ".hero { padding: 64px } .head { color: #123456 }"
PNG = b"\x89PNG\r\n\x1a\nfake-preview-bytes"
SOURCE_URL = "https://insight.example/"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _create(
    workspace_id: str,
    storage: FsStorage,
    *,
    html: str = HTML,
    css: str = CSS,
    section_role: str = "hero",
    preview: bytes | None = PNG,
    **kwargs: Any,
):
    return create_web_fragment(
        storage,
        workspace_id=workspace_id,
        html=html,
        css=css,
        rehosted={},
        source_url=SOURCE_URL,
        section_role=section_role,
        preview=preview,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# The registry: one row, one payload blob, and a round trip
# --------------------------------------------------------------------------- #


def test_creating_a_fragment_writes_one_row_two_blobs_and_round_trips(
    workspace_id: str, design_storage: FsStorage
) -> None:
    row, artifact = _create(
        workspace_id,
        design_storage,
        label="Insight hero",
        slots=(SlotSpec(selector=".head", key="headline", kind="text"),),
        provenance={"job_id": "job_1", "page_index": 0},
    )

    assert row["fragment_id"] == artifact.fragment_id
    assert row["workspace_id"] == workspace_id
    assert row["section_role"] == "hero"
    assert row["label"] == "Insight hero"
    assert row["source_url"] == SOURCE_URL
    assert row["status"] == "draft"
    assert row["payload_digest"] == _sha(artifact.payload_bytes)
    assert row["preview_digest"] == _sha(PNG)
    # The caller's provenance survives verbatim, and the creation seam stamps what was actually
    # STORED beside it — the producer cannot know that, because the css is scoped under an id
    # derived from the artifact it is still building (F2 wave W8).
    assert row["provenance"]["job_id"] == "job_1"
    assert row["provenance"]["page_index"] == 0
    assert set(row["provenance"]["payload"]) == {"bytes", "css_bytes", "html_bytes"}
    assert row["provenance"]["payload"]["bytes"] > 0

    blobs = DesignBlobStore(design_storage, workspace_id)
    assert blobs.exists(row["payload_digest"])
    assert blobs.exists(row["preview_digest"])

    loaded = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=artifact.fragment_id
    )
    assert loaded.html == artifact.payload["html"]
    assert f".{fragment_wrapper_class(artifact.fragment_id)} .hero" in loaded.css
    assert loaded.slot_manifest["headline"] == {
        "kind": "text",
        "fallback": "Care, on your terms",
    }
    assert loaded.row["fragment_id"] == artifact.fragment_id


def test_re_minting_the_same_section_converges_on_one_row_and_one_blob(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """Content addressing IS the dedup: a second harvest of an unchanged section is free."""
    first_row, first = _create(workspace_id, design_storage, label="first")
    second_row, second = _create(workspace_id, design_storage, label="second")

    assert first.fragment_id == second.fragment_id
    assert first.payload_bytes == second.payload_bytes
    assert len(list_web_fragments(workspace_id=workspace_id)) == 1
    # First writer wins the provenance/label; the row was never updated.
    assert second_row["label"] == "first"
    assert second_row["created_at"] == first_row["created_at"]


def test_a_re_mint_converges_on_a_row_whose_preview_was_attached_afterwards(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """The payload/row ``preview_digest`` divergence, pinned rather than merely disclosed (M-14).

    ``preview_digest`` is inside the artifact's IDENTITY bytes and inside the payload, so a
    picture attached later leaves the immutable payload saying ``null`` while the row carries a
    digest. That is deliberate — the payload is a record of what was minted, and a photograph
    taken afterwards is not part of what was minted — and it is inert only because the re-mint
    path passes ``preview=None`` and converges with ``ON CONFLICT DO NOTHING``.

    Nothing tested that. A future writer that upserted ``preview_digest`` on conflict would break
    the immutability trigger and re-ingest at once, with every existing test still green. This is
    the test that would go red.
    """
    row, artifact = _create(workspace_id, design_storage, preview=None)
    assert row["preview_digest"] is None

    attached = attach_web_fragment_preview(
        design_storage,
        workspace_id=workspace_id,
        fragment_id=artifact.fragment_id,
        preview=PNG,
        preview_basis="isolation_render",
    )
    assert attached["preview_digest"] == _sha(PNG)

    # Re-harvesting the SAME section: same bytes in, same content address out.
    again_row, again = _create(workspace_id, design_storage, preview=None)

    assert again.fragment_id == artifact.fragment_id
    assert len(list_web_fragments(workspace_id=workspace_id)) == 1
    # The attached picture survived the convergence…
    assert again_row["preview_digest"] == _sha(PNG)
    assert again_row["preview_basis"] == "isolation_render"
    # …and the payload still records what was MINTED, which had no picture. Re-deriving the id
    # from the row's digest would therefore not reproduce `fragment_id`, and that is the
    # documented shape, not a bug: the identity is the mint's, the photograph is later.
    assert again.payload["preview_digest"] is None
    loaded = read_web_fragment(
        design_storage, workspace_id=workspace_id, fragment_id=artifact.fragment_id
    )
    assert loaded.payload["preview_digest"] is None
    assert loaded.row["preview_digest"] == _sha(PNG)


def test_a_changed_section_is_a_different_fragment(
    workspace_id: str, design_storage: FsStorage
) -> None:
    _, first = _create(workspace_id, design_storage)
    _, second = _create(workspace_id, design_storage, css=CSS.replace("64px", "80px"))
    assert first.fragment_id != second.fragment_id
    assert len(list_web_fragments(workspace_id=workspace_id)) == 2


def test_reading_another_workspaces_fragment_is_refused(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """Fail-closed matters MORE here: the id is a global content address, so a neighbour who
    cloned the same public section legitimately holds the same id."""
    _, artifact = _create(workspace_id, design_storage)
    with pytest.raises(NotFoundError):
        read_web_fragment(
            design_storage,
            workspace_id=f"{workspace_id}_other",
            fragment_id=artifact.fragment_id,
        )
    assert not web_fragment_exists(
        workspace_id=f"{workspace_id}_other", fragment_id=artifact.fragment_id
    )
    assert web_fragment_exists(workspace_id=workspace_id, fragment_id=artifact.fragment_id)


def test_two_workspaces_can_hold_the_same_content_addressed_fragment(
    workspace_id: str, design_storage: FsStorage
) -> None:
    other = f"{workspace_id}_two"
    _, mine = _create(workspace_id, design_storage)
    _, theirs = _create(other, design_storage)
    assert mine.fragment_id == theirs.fragment_id
    assert len(list_web_fragments(workspace_id=workspace_id)) == 1
    assert len(list_web_fragments(workspace_id=other)) == 1


def test_the_status_flag_moves_and_nothing_else_can(
    workspace_id: str, design_storage: FsStorage
) -> None:
    from sqlalchemy import text

    row, artifact = _create(workspace_id, design_storage)
    assert row["status"] == "draft"

    approved = set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=artifact.fragment_id, status="approved"
    )
    assert approved["status"] == "approved"
    assert approved["payload_digest"] == row["payload_digest"]

    with pytest.raises(ValueError):
        set_web_fragment_status(
            workspace_id=workspace_id, fragment_id=artifact.fragment_id, status="blessed"
        )

    # The payload pointer is immutable BY TRIGGER, not by this module's good manners.
    with pytest.raises(Exception) as excinfo:
        DesignStoreBridge(workspace_id)._run(
            lambda conn: conn.execute(
                text(
                    "UPDATE design_web_fragment SET payload_digest = :d "
                    "WHERE fragment_id = :f AND workspace_id = :w"
                ),
                {"d": "0" * 64, "f": artifact.fragment_id, "w": workspace_id},
            )
        )
    assert "immutable" in str(excinfo.value)


def test_listing_narrows_by_role_and_status(
    workspace_id: str, design_storage: FsStorage
) -> None:
    _, hero = _create(workspace_id, design_storage, section_role="hero")
    _, footer = _create(
        workspace_id, design_storage, section_role="footer", html=HTML.replace("hero", "foot")
    )
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=hero.fragment_id, status="approved"
    )

    roles = [r["fragment_id"] for r in list_web_fragments(workspace_id=workspace_id, section_role="footer")]
    assert roles == [footer.fragment_id]
    approved = [
        r["fragment_id"] for r in list_web_fragments(workspace_id=workspace_id, status="approved")
    ]
    assert approved == [hero.fragment_id]


def test_the_fragment_source_key_is_its_own(
    workspace_id: str, design_storage: FsStorage
) -> None:
    from clue_design.storage import design_storage_key
    from clue_storage.artifacts import get_artifact

    row, _artifact = _create(workspace_id, design_storage)
    record = DesignStoreBridge(workspace_id)._run(
        lambda conn: get_artifact(conn, design_storage_key(workspace_id, row["payload_digest"]))
    )
    assert record is not None
    assert record.source_key == WEB_FRAGMENT_SOURCE_KEY == "design_web_fragment"


def test_a_refused_fragment_writes_neither_row_nor_blob(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """The primitives run before any I/O, so a refusal costs an exception and nothing else."""
    with pytest.raises(FragmentRefused):
        _create(
            workspace_id,
            design_storage,
            html='<section><img src="https://cdn.example/never-rehosted.png"></section>',
        )
    assert list_web_fragments(workspace_id=workspace_id) == []


# --------------------------------------------------------------------------- #
# The lineage read: one family, through the derived_from index
# --------------------------------------------------------------------------- #


def _repair_of(
    workspace_id: str, design_storage: FsStorage, parent: dict, sentinel: str
) -> dict:
    row, _artifact = _create(
        workspace_id,
        design_storage,
        html=f'<section class="hero"><h1 class="head">{sentinel}</h1></section>',
        derived_from=parent["fragment_id"],
        derived_reason="dead_height",
    )
    return row


def test_the_lineage_read_returns_the_whole_family_from_any_member(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """Ancestors AND descendants, whichever end you ask from — the resolver needs both halves."""
    original, _ = _create(workspace_id, design_storage)
    repair = _repair_of(workspace_id, design_storage, original, "Repair one")
    grandchild = _repair_of(workspace_id, design_storage, repair, "Repair two")
    sibling = _repair_of(workspace_id, design_storage, original, "Repair three")
    family = {
        original["fragment_id"],
        repair["fragment_id"],
        grandchild["fragment_id"],
        sibling["fragment_id"],
    }

    for member in family:
        read = list_web_fragment_lineage(workspace_id=workspace_id, fragment_id=member)
        assert {row["fragment_id"] for row in read} == family, member


def test_the_lineage_read_never_reaches_into_an_unrelated_family(
    workspace_id: str, design_storage: FsStorage
) -> None:
    original, _ = _create(workspace_id, design_storage)
    repair = _repair_of(workspace_id, design_storage, original, "Repair one")
    # Different bytes, so a different content address — a fragment id is the content, and the
    # section role is not part of it.
    stranger, _ = _create(
        workspace_id,
        design_storage,
        html='<section class="foot"><p class="fine">Unrelated</p></section>',
        css=".foot { padding: 8px }",
        section_role="footer",
    )

    read = list_web_fragment_lineage(
        workspace_id=workspace_id, fragment_id=original["fragment_id"]
    )

    assert {row["fragment_id"] for row in read} == {
        original["fragment_id"],
        repair["fragment_id"],
    }
    assert stranger["fragment_id"] not in {row["fragment_id"] for row in read}


def test_the_lineage_read_filters_no_status(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """Ruling R-X1 walks links of ANY status; a filtered read would re-decide it at the database."""
    original, _ = _create(workspace_id, design_storage)
    repair = _repair_of(workspace_id, design_storage, original, "Repair one")
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=repair["fragment_id"], status="approved"
    )
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=repair["fragment_id"], status="deprecated"
    )
    grandchild = _repair_of(workspace_id, design_storage, repair, "Repair two")

    read = list_web_fragment_lineage(
        workspace_id=workspace_id, fragment_id=grandchild["fragment_id"]
    )

    assert {row["status"] for row in read} == {"draft", "deprecated"}
    assert original["fragment_id"] in {row["fragment_id"] for row in read}


def test_the_lineage_read_answers_nothing_for_an_id_this_workspace_does_not_hold(
    workspace_id: str, design_storage: FsStorage
) -> None:
    _create(workspace_id, design_storage)
    assert list_web_fragment_lineage(
        workspace_id=workspace_id, fragment_id="frag_" + "0" * 16
    ) == []


def test_half_a_source_kit_reference_is_refused(
    workspace_id: str, design_storage: FsStorage
) -> None:
    with pytest.raises(FragmentRefused) as excinfo:
        _create(workspace_id, design_storage, source_kit_id="kit_1")
    assert excinfo.value.code == "fragment.source_kit_incomplete"


def test_a_cross_workspace_source_kit_cannot_be_named(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """Tenancy is structural: the kit link is a composite FK through the kit's workspace anchor."""
    with pytest.raises(Exception) as excinfo:
        _create(workspace_id, design_storage, source_kit_id="kit_nope", source_kit_version=1)
    assert "design_web_fragment_kit_fk" in str(excinfo.value)


# --------------------------------------------------------------------------- #
# The reference-integrity gate on document writes
# --------------------------------------------------------------------------- #


def _web_doc(document_id: str, *nodes: dict[str, Any]) -> dict[str, Any]:
    node_map = {"root": {"id": "root", "kind": "container", "children": [n["id"] for n in nodes]}}
    for node in nodes:
        node_map[node["id"]] = node
    return {
        "schema_version": 1,
        "id": document_id,
        "title": "T",
        "pages": [{"id": "page_1", "name": "Home", "route": "/", "root": "root", "nodes": node_map}],
        "assets": {},
        "custom_css": "",
    }


def _fragment_node(node_id: str, fragment_id: str) -> dict[str, Any]:
    return {"id": node_id, "kind": "fragment", "fragment_id": fragment_id}


def _pinnable(workspace_id: str, storage: FsStorage, **kwargs: Any):
    """A fragment a document may actually pin: minted, then approved.

    F2.2 gave the gate its second half — a NEW pin requires ``approved``, because minting mints
    drafts and a human releases them by approving the brand kit they were cloned into. The tests
    below are about the RESOLUTION half (does this workspace hold it?), so they say the quiet part
    out loud here rather than each carrying an approval line. ``test_ingestion_fragment_pipeline``
    owns the status half.
    """
    row, artifact = _create(workspace_id, storage, **kwargs)
    set_web_fragment_status(
        workspace_id=workspace_id, fragment_id=artifact.fragment_id, status="approved"
    )
    return row, artifact


def test_a_new_fragment_node_pinned_to_an_unknown_id_is_refused(
    workspace_id: str, design_storage: FsStorage
) -> None:
    store = HybridRepository(workspace_id=workspace_id)
    unknown = "frag_" + "ab" * 8
    with pytest.raises(FragmentReferenceError) as excinfo:
        store.create_document(_web_doc("doc_f1", _fragment_node("n1", unknown)), doc_kind="web")
    assert excinfo.value.code == "fragment.unresolved"
    assert excinfo.value.fragment_id == unknown
    assert excinfo.value.node_id == "n1"


def test_a_new_fragment_node_pinned_to_a_registered_id_is_allowed(
    workspace_id: str, design_storage: FsStorage
) -> None:
    _row, artifact = _pinnable(workspace_id, design_storage)
    store = HybridRepository(workspace_id=workspace_id)
    document = store.create_document(
        _web_doc("doc_f2", _fragment_node("n1", artifact.fragment_id)), doc_kind="web"
    )
    assert document["id"] == "doc_f2"


def test_a_fragment_registered_to_another_workspace_is_refused(
    workspace_id: str, design_storage: FsStorage
) -> None:
    other = f"{workspace_id}_owner"
    _row, artifact = _create(other, design_storage)
    store = HybridRepository(workspace_id=workspace_id)
    with pytest.raises(FragmentReferenceError) as excinfo:
        store.create_document(
            _web_doc("doc_f3", _fragment_node("n1", artifact.fragment_id)), doc_kind="web"
        )
    assert excinfo.value.code == "fragment.unresolved"


def test_an_existing_missing_pin_stays_loadable_and_editable(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """An unrelated edit must never become impossible because registry data went missing.

    Mirrors the custom-component gate's own promise exactly: only NEW or RE-POINTED pins resolve.
    """
    from sqlalchemy import text

    _row, artifact = _pinnable(workspace_id, design_storage)
    store = HybridRepository(workspace_id=workspace_id)
    before = store.create_document(
        _web_doc("doc_f4", _fragment_node("n1", artifact.fragment_id)), doc_kind="web"
    )

    DesignStoreBridge(workspace_id)._run(
        lambda conn: conn.execute(
            text("DELETE FROM design_web_fragment WHERE fragment_id = :f AND workspace_id = :w"),
            {"f": artifact.fragment_id, "w": workspace_id},
        )
    )

    # The pin is now unresolvable, but it was already there: retitling the page still works.
    after = dict(_web_doc("doc_f4", _fragment_node("n1", artifact.fragment_id)))
    after["title"] = "Retitled"
    updated = store.update_web_document(
        "doc_f4",
        after,
        intent="retitle",
        checkpoint_label=None,
        operations=[],
        inverse_operations=None,
    )
    assert updated["current_version"] > before["current_version"]

    # Adding a SECOND node on the same dead pin is a new reference, and is refused.
    with pytest.raises(FragmentReferenceError):
        store.update_web_document(
            "doc_f4",
            _web_doc(
                "doc_f4",
                _fragment_node("n1", artifact.fragment_id),
                _fragment_node("n2", artifact.fragment_id),
            ),
            intent="duplicate",
            checkpoint_label=None,
            operations=[],
            inverse_operations=None,
        )


def test_re_pointing_an_existing_node_at_an_unknown_fragment_is_refused(
    workspace_id: str, design_storage: FsStorage
) -> None:
    _row, artifact = _pinnable(workspace_id, design_storage)
    store = HybridRepository(workspace_id=workspace_id)
    store.create_document(
        _web_doc("doc_f5", _fragment_node("n1", artifact.fragment_id)), doc_kind="web"
    )
    with pytest.raises(FragmentReferenceError) as excinfo:
        store.update_web_document(
            "doc_f5",
            _web_doc("doc_f5", _fragment_node("n1", "frag_" + "cd" * 8)),
            intent="repoint",
            checkpoint_label=None,
            operations=[],
            inverse_operations=None,
        )
    assert excinfo.value.node_id == "n1"


def test_a_web_template_is_gated_too(workspace_id: str, design_storage: FsStorage) -> None:
    store = HybridRepository(workspace_id=workspace_id)
    with pytest.raises(FragmentReferenceError):
        store.create_web_template(_web_doc("tpl_f1", _fragment_node("n1", "frag_" + "ef" * 8)))


def test_a_document_with_no_fragment_nodes_touches_the_registry_not_at_all(
    workspace_id: str, design_storage: FsStorage
) -> None:
    store = HybridRepository(workspace_id=workspace_id)
    document = store.create_document(
        _web_doc("doc_f6", {"id": "n1", "kind": "container", "children": []}), doc_kind="web"
    )
    assert document["id"] == "doc_f6"


def test_duplicate_fragment_cannot_attach_a_foreign_kit(
    workspace_id: str, design_storage: FsStorage
) -> None:
    """ON CONFLICT must not skip tenancy checks on a new capture association."""
    row, _ = _create(workspace_id, design_storage)
    with pytest.raises(Exception) as excinfo:
        _create(workspace_id, design_storage, source_kit_id="foreign_kit", source_kit_version=1)
    assert "design_web_fragment_kit_binding_kit_fk" in str(excinfo.value)
    after = next(
        r
        for r in list_web_fragments(workspace_id=workspace_id)
        if r["fragment_id"] == row["fragment_id"]
    )
    assert after["source_kit_bindings"] == []

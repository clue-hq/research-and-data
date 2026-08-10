"""Part II slice D6 Round B — the documents/history/web/turn plane, behaviourally.

Three claims, each proved rather than asserted in a docstring:

1. **The scene CAS is closed at the DATABASE, not at the handler** (R-D6-B1). The routes'
   ``require_base_version`` pre-check reads the version *before* the engine round-trip; the
   tests below bypass it entirely (they invoke the tool directly) and show that a second writer
   whose base version has moved is refused by ``clue_design.documents``' row-locked CAS. Before
   D6 the facade silently dropped ``expected_base_version`` and this write landed, clobbering
   the interleaved edit with no trace.
2. **A DOMAIN-keyed create replays; it does not duplicate.** The same ``Idempotency-Key`` + the
   same body returns the first outcome (``replayed=True``) and leaves exactly one row; a NEW
   operation against the same caller-supplied id is refused, not silently applied twice.
3. **The website-turn worker's persist is the governed write.** The turn envelope's frozen
   ``base_version`` reaches the same tool the /web/operations route uses, and a document that
   moved while the turn ran yields the turn's ``conflicted`` result instead of a clobber.
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any

import pytest
from clue_db import create_engine
from clue_toolbelt import PreconditionFailed
from fastapi.testclient import TestClient
from sqlalchemy import text

from conftest import make_client
from lumen_api.database import WebDocumentVersionConflict
from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app
from test_api import create_document, minimal_scene
from test_web_turns import (
    create_web_document,
    ingest_content,
    install_operations,
    wait_for_run,
)


@pytest.fixture()
def app(tmp_path: Path, design_storage) -> Any:
    return create_app(tmp_path / "engine-cache", storage=design_storage)


@pytest.fixture()
def client(app: Any) -> TestClient:
    return make_client(app)


def workspace() -> str:
    return os.environ["LUMEN_DEV_WORKSPACE_ID"]


def invoke(app: Any, name: str, body: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
    result = app.state.design_tools.invoke(
        name, body, workspace_id=workspace(), **kwargs
    )
    return {"references": dict(result.references), "replayed": result.replayed}


def query(sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    async def run() -> list[dict[str, Any]]:
        engine = create_engine()
        try:
            async with engine.connect() as conn:
                rows = (await conn.execute(text(sql), params)).mappings().all()
                return [dict(row) for row in rows]
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _text_edit(scene: dict[str, Any], content: str) -> dict[str, Any]:
    """A trivially valid operation batch. The ENGINE round-trip is the route's (R-D6-B4), so a
    tool-level test supplies the post-engine scene and the operations directly."""
    return {"kind": "set_text", "node_id": "node_contact_name", "content": content}


# --- 1. the scene CAS, at the database -------------------------------------------------------


def test_the_scene_cas_refuses_a_writer_whose_base_version_moved(
    app: Any, client: TestClient
) -> None:
    """Two writers, one 409 — proved BELOW the handler pre-check.

    Both invocations go straight to the tool with the base version writer A read, so
    ``require_base_version`` never runs. Writer B lands first; writer A's write is then refused
    by the DAL's ``_check_cas`` inside the write transaction, which is the only place that can
    see an edit that landed during the (unmodelled, hundreds-of-ms) engine round-trip.
    """
    document = create_document(client)
    document_id = document["id"]
    base_version = document["current_version"]
    scene = client.get(f"/documents/{document_id}").json()["scene"]

    # Writer B: the concurrent edit that lands while writer A is in the engine.
    landed = invoke(
        app,
        "design_apply_operations",
        {
            "document_id": document_id,
            "scene": scene,
            "operations": [_text_edit(scene, "WRITER_B")],
            "source": "editor",
            "actor_kind": "human",
            "expected_base_version": base_version,
        },
    )
    assert landed["references"]["current_version"] == base_version + 1

    # Writer A: same base version, now stale. Pre-D6 this landed and erased writer B.
    with pytest.raises(WebDocumentVersionConflict) as conflict:
        invoke(
            app,
            "design_apply_operations",
            {
                "document_id": document_id,
                "scene": scene,
                "operations": [_text_edit(scene, "WRITER_A")],
                "source": "editor",
                "actor_kind": "human",
                "expected_base_version": base_version,
            },
        )
    assert conflict.value.expected == base_version
    assert conflict.value.current == base_version + 1

    reread = HybridRepository(workspace()).require_document(document_id)
    assert reread["current_version"] == base_version + 1, (
        "the refused writer must not have advanced the document"
    )
    envelopes = query(
        "SELECT batch_id FROM design_edit_envelope WHERE document_id = :d "
        "AND workspace_id = :w",
        {"d": document_id, "w": workspace()},
    )
    assert len(envelopes) == 1, "a CAS-refused write appends no history envelope"


def test_the_route_still_answers_a_stale_base_version_with_its_documented_409(
    client: TestClient,
) -> None:
    """The handler pre-check and the DAL CAS are ONE contract — same body either way."""
    document = create_document(client)
    stale = client.post(
        f"/documents/{document['id']}/operations",
        json={
            "operations": [{"kind": "set_text", "node_id": "node_contact_name", "content": "x"}],
            "base_version": document["current_version"] + 7,
        },
    )
    assert stale.status_code == 409, stale.text
    assert stale.json()["detail"]["code"] == "edits.base_version_mismatch"
    assert stale.json()["detail"]["current_version"] == document["current_version"]


def test_undo_carries_the_version_it_read_into_the_write(
    app: Any, client: TestClient
) -> None:
    """Undo is a read-then-write loop; D6 makes the interleaving a 409 rather than silence."""
    document = create_document(client)
    document_id = document["id"]
    scene = client.get(f"/documents/{document_id}").json()["scene"]
    invoke(
        app,
        "design_apply_operations",
        {
            "document_id": document_id,
            "scene": scene,
            "operations": [_text_edit(scene, "BEFORE_UNDO")],
            "source": "editor",
            "actor_kind": "human",
            "expected_base_version": document["current_version"],
        },
    )
    batch_id = HybridRepository(workspace()).list_envelopes(
        document_id, limit=1, newest_first=True
    )[0]["batch_id"]

    # A concurrent writer moves the document out from under an undo that already read it.
    current = HybridRepository(workspace()).require_document(document_id)
    with pytest.raises(WebDocumentVersionConflict):
        invoke(
            app,
            "design_undo_document",
            {
                "document_id": document_id,
                "scene": current["scene"],
                "operations": [_text_edit(current["scene"], "UNDONE")],
                "envelope": {"intent": "undo:stale", "reverts_batch_id": batch_id},
                "expected_base_version": current["current_version"] - 1,
            },
        )
    # And with the version it actually read, the same undo lands.
    landed = invoke(
        app,
        "design_undo_document",
        {
            "document_id": document_id,
            "scene": current["scene"],
            "operations": [_text_edit(current["scene"], "UNDONE")],
            "envelope": {"intent": "undo:live", "reverts_batch_id": batch_id},
            "expected_base_version": current["current_version"],
        },
    )
    assert landed["references"]["current_version"] == current["current_version"] + 1


# --- 2. DOMAIN-keyed replay ------------------------------------------------------------------


def test_a_keyed_snapshot_replays_instead_of_creating_a_second_row(
    app: Any, client: TestClient
) -> None:
    """Same snapshot id + same body + same key ⇒ replayed, one row (R-D6-B3)."""
    document = create_document(client)
    body = {
        "document_id": document["id"],
        "snapshot_id": "snap_governed",
        "reason": "governance",
    }
    first = invoke(app, "design_create_snapshot", body, idempotency_key="k-snap")
    assert first["replayed"] is False
    assert first["references"]["snapshot_id"] == "snap_governed"

    second = invoke(app, "design_create_snapshot", body, idempotency_key="k-snap")
    assert second["replayed"] is True
    assert second["references"] == first["references"]

    rows = query(
        "SELECT snapshot_id FROM design_snapshot WHERE document_id = :d AND workspace_id = :w",
        {"d": document["id"], "w": workspace()},
    )
    assert [row["snapshot_id"] for row in rows] == ["snap_governed"], (
        "a replayed snapshot must not append a second row"
    )


def test_a_new_operation_against_a_taken_snapshot_id_is_refused_not_duplicated(
    app: Any, client: TestClient
) -> None:
    """The DOMAIN key's real guarantee: an UNKEYED re-run refuses instead of writing."""
    document = create_document(client)
    body = {
        "document_id": document["id"],
        "snapshot_id": "snap_domain",
        "reason": "first",
    }
    invoke(app, "design_create_snapshot", body)
    with pytest.raises(PreconditionFailed) as refused:
        invoke(app, "design_create_snapshot", {**body, "reason": "second"})
    assert refused.value.reason_codes == ("design_snapshot_exists",)

    rows = query(
        "SELECT reason FROM design_snapshot WHERE document_id = :d AND workspace_id = :w",
        {"d": document["id"], "w": workspace()},
    )
    assert [row["reason"] for row in rows] == ["first"]


def test_a_taken_document_id_is_a_typed_refusal_not_a_500(client: TestClient) -> None:
    """POST /documents with a duplicate caller-supplied id: a 409 that writes nothing.

    Pre-D6 this reached the store and surfaced as the generic 500 ``database.error``.
    """
    scene = minimal_scene()
    scene["meta"]["id"] = "doc_governed_dupe"
    first = client.post(
        "/documents",
        json={"title": "Governed", "document_id": "doc_governed_dupe", "scene": scene},
    )
    assert first.status_code == 200, first.text
    again = client.post(
        "/documents",
        json={"title": "Governed again", "document_id": "doc_governed_dupe", "scene": scene},
    )
    assert again.status_code == 409, again.text
    assert again.json()["detail"]["code"] == "document.exists"
    assert again.json()["detail"]["resource_id"] == "doc_governed_dupe"
    rows = query(
        "SELECT id FROM design_document WHERE id = :d AND workspace_id = :w",
        {"d": "doc_governed_dupe", "w": workspace()},
    )
    assert len(rows) == 1, "the refused create wrote nothing"


# --- 3. the website-turn worker's persist ----------------------------------------------------

def test_the_web_turn_worker_persists_through_the_governed_tool(
    client: TestClient,
) -> None:
    """Envelope -> tool core -> journal, with ``actor='agent'`` on the invocation (REQ-20).

    The worker's own operation-replay verification is untouched and still runs BEFORE the tool:
    it is a precondition on trusting the agent's own history, it needs the engine, and it stays
    loud. What D6 moves is only the durable write behind it.
    """
    document = create_web_document(client)
    content_doc = ingest_content(client, document["id"])

    def stub(doc, prompt, model, root):
        return {
            "schema_version": 1,
            "status": "applied",
            "web_doc": content_doc,
            "operations": install_operations(doc["scene"], content_doc),
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    offered = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Build a landing page", "base_version": 0},
    )
    assert offered.status_code == 200, offered.text
    run = wait_for_run(client, offered.json()["run_id"])
    assert run["status"] == "succeeded", run

    body = client.get(f"/documents/{document['id']}").json()
    assert body["current_version"] == 1

    # Both halves of the turn are governed: the ENQUEUE (actor human, the requesting operator)
    # and the PERSIST (actor agent, the worker acting on the turn's behalf). `execution
    # .started_by` carries the ToolContext actor, which is the REQ-20 parity claim.
    nodes = query(
        """
        SELECT n.tool_name, e.started_by
        FROM execution_node n
        JOIN execution e ON e.id = n.execution_id
        WHERE e.workspace_id = :w AND n.tool_name LIKE 'design_%'
        """,
        {"w": workspace()},
    )
    by_tool = {row["tool_name"]: row for row in nodes}
    assert by_tool["design_start_web_turn"]["started_by"] == "human"
    assert by_tool["design_apply_web_operations"]["started_by"] == "agent"
    completed = query(
        """
        SELECT ev.event_type
        FROM execution_event ev
        JOIN execution e ON e.id = ev.execution_id
        JOIN execution_node n ON n.execution_id = e.id
        WHERE e.workspace_id = :w AND n.tool_name = 'design_apply_web_operations'
          AND ev.event_type = 'node.completed'
        """,
        {"w": workspace()},
    )
    assert completed, "the worker's persist is a durably completed journal node"


def test_the_web_turn_persist_honours_the_envelopes_base_version(
    client: TestClient,
) -> None:
    """A turn that took minutes cannot clobber a human edit made while it ran.

    The worker's persist runs against the envelope's FROZEN ``base_version``; the tool threads
    it into the same row-locked CAS every other design write now uses, so the conflict surfaces
    as the turn's documented ``conflicted`` result rather than a silent overwrite.
    """
    document = create_web_document(client)
    content_doc = ingest_content(client, document["id"])
    operations_holder: dict[str, list] = {}

    def stub(doc, prompt, model, root):
        operations_holder["ops"] = install_operations(doc["scene"], content_doc)
        # The human edit lands WHILE the turn is running.
        landed = client.post(
            f"/documents/{document['id']}/web/operations",
            json={
                "operations": operations_holder["ops"],
                "base_version": 0,
            },
        )
        assert landed.status_code == 200, landed.text
        return {
            "schema_version": 1,
            "status": "applied",
            "web_doc": content_doc,
            "operations": operations_holder["ops"],
            "doc_kind": "web",
        }

    client.app.state.web_turn_runner = stub
    offered = client.post(
        f"/documents/{document['id']}/web/turns",
        json={"prompt": "Build a landing page", "base_version": 0},
    )
    assert offered.status_code == 200, offered.text
    run = wait_for_run(client, offered.json()["run_id"])

    assert run["status"] == "failed", run
    assert run["result"]["status"] == "conflicted", run["result"]
    body = client.get(f"/documents/{document['id']}").json()
    assert body["current_version"] == 1, (
        "the human edit survives; the stale turn wrote nothing"
    )

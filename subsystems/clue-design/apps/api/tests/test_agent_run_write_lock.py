"""Rung A Task 1 — a document refuses MANUAL writes while a design agent run is driving it.

THE RULE (founder, scene live-streaming): while a design run is in progress on a document, manual
editing of that document is forbidden. The frontend half (a disabled canvas) is a later task; this
file pins the BACKEND half, which is the one that has to be true even when the frontend is stale,
mid-deploy, or simply a second tab nobody remembered was open.

The manual scene-write routes refuse with **409 `document.agent_run_active`**, naming the run that
holds the document so the caller can say which run to watch (or cancel):

* ``PUT  /documents/{id}/scene``
* ``POST /documents/{id}/operations``
* ``POST /documents/{id}/undo``
* ``POST /documents/{id}/redo``
* ``POST /documents/{id}/edits`` — the inspector's structured edit
* ``POST /documents/{id}/revert`` — N composed undos back to a checkpoint

The last two arrived one round later (controller ruling, 2026-09-02): the platform editor posts to
both (`structuredEdits.ts`, `documentStore.ts`), so leaving them open would have left the rule
true of four doors and false of two.

And the line the lock must NOT cross: the agent's OWN writes. A leg turn commits through the
internal governed tool path (``_LegSceneCommitter`` → ``design_apply_operations``), never through
these routes — so a lock that reached the tool would deadlock every run against itself. The last
test drives the real committer while its own run is ``running`` and proves the write lands.

The seeded run is a REAL leg run: the frozen ``DesignTurnEnvelope`` the platform's design leg
writes onto ``design_agent_run.payload`` (``design_leg_wiring._envelope``), stamped ``running`` by
the same CAS the fleet worker claims with.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from py_lumen_config import settings

from clue_design import runs as design_runs
from clue_design.envelopes import DesignTurnEnvelope

from conftest import make_client, unique_run_id

from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"

LEG_BRIEF = "Build the Harbor & Sage launch ad: bold headline, product shot, booking CTA."


@pytest.fixture(autouse=True)
def _no_embedded_fleet_worker(monkeypatch: pytest.MonkeyPatch) -> None:
    """This module seeds its run rows directly; it never offers work to the queue.

    The app's embedded worker leases by KIND from a SHARED queue table, so it drains whatever
    ``design_job`` rows happen to be sitting in the database — including a developer stack's real,
    minutes-long design turns, which then run inside this test process and stall it (observed:
    21 queued jobs on the dev database). Nothing here wants a worker, so nothing here starts one.
    Same fixture, same reason, as ``test_ad_assets_advertiser_resolution._no_embedded_worker``.
    """
    monkeypatch.setattr(settings, "lumen_embedded_fleet_worker", False, raising=False)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    return make_client(create_app(tmp_path / "engine-cache"))


def minimal_scene() -> dict:
    return json.loads(MINIMAL_SCENE_PATH.read_text())


def create_document(client: TestClient, title: str = "Hospital Letter") -> dict:
    """One scene document with an id of its own.

    The fixture scene names itself (``meta.id = doc_demo``) and the create route honours that
    name, so two documents built from the same fixture would be ONE row — which would quietly
    turn the per-document test below into a test of nothing.
    """
    scene = minimal_scene()
    scene["meta"]["id"] = f"doc_{uuid4().hex[:12]}"
    response = client.post("/documents", json={"title": title, "scene": scene})
    assert response.status_code == 200, response.text
    return response.json()["document"]


def title_operation(title: str) -> dict:
    return {
        "kind": "update_document",
        "patch": {
            "title": {"kind": "set", "value": title},
            "artifact_type": {"kind": "unchanged"},
            "medium": {"kind": "unchanged"},
            "brand_kit": {"kind": "unchanged"},
        },
    }


def stored_scene(client: TestClient, document_id: str) -> dict:
    return client.get(f"/documents/{document_id}").json()["scene"]


def start_leg_run(store: HybridRepository, document_id: str) -> str:
    """Seed ONE running scene-leg run bound to ``document_id`` and return its run id.

    Shaped like the real thing on both halves. The payload is the frozen ``DesignTurnEnvelope``
    the platform's design leg freezes onto the run row (``design_leg_wiring._envelope``) — a leg
    block, a delegation bundle, and the turn request — because the lock reads the run's own record
    of which document it is driving. The status move is the fleet worker's CAS
    (``claim_run_for_execution``), because a run is born ``queued`` and only the claiming worker
    stamps it ``running``, which is the state the lock is about.
    """
    run_id = unique_run_id("write_lock")
    envelope = DesignTurnEnvelope(
        kind="agent_turn",
        work_id=design_runs.work_id_for_run(run_id),
        workspace_id=store.workspace_id,
        run_id=run_id,
        checkpoint_thread_id=run_id,
        document_id=document_id,
        config={
            "request": {
                "prompt": "Make the headline two lines.",
                "scene": {},
                "document_id": document_id,
            },
            "delegation_bundle": {"brief": LEG_BRIEF},
            "history": [],
            "leg": {"leg_id": "leg-write-lock", "document_base_version": 0},
        },
    ).model_dump(mode="json")
    store.create_run(run_id, document_id, kind="agent_turn", payload=envelope)
    # Reaching into `_bridge` is deliberate: queued -> running is the FLEET WORKER's CAS and the
    # design app exposes no method for it, so the test performs that exact call rather than
    # inventing a status write of its own.
    claimed = store._bridge._run(
        lambda conn: design_runs.claim_run_for_execution(
            conn,
            work_id=design_runs.work_id_for_run(run_id),
            worker_id="worker_write_lock_test",
            lease_generation=1,
        )
    )
    assert claimed is not None and claimed["status"] == "running"
    return run_id


def finish_run(store: HybridRepository, run_id: str) -> None:
    """End the run exactly as the worker does — the terminal result and its marker event."""
    store.complete_run(run_id, "succeeded", {"status": "applied"}, "result", {"status": "applied"})
    assert store.require_run(run_id)["status"] == "succeeded"


def assert_locked(response, run_id: str) -> None:
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == {
        "code": "document.agent_run_active",
        "run_id": run_id,
    }


def build_undo_and_redo_history(client: TestClient, document_id: str) -> None:
    """Leave BOTH stacks non-empty, so undo/redo can only refuse because of the lock.

    Two applied batches, then one undo: the undo stack still holds the first batch and the redo
    stack holds the second. Without this a locked undo/redo would be indistinguishable from
    ``history.nothing_to_undo``.
    """
    for title in ("Human One", "Human Two"):
        applied = client.post(
            f"/documents/{document_id}/operations",
            json={"operations": [title_operation(title)]},
        )
        assert applied.status_code == 200, applied.text
    undone = client.post(f"/documents/{document_id}/undo")
    assert undone.status_code == 200, undone.text


#: The checkpoint label ``build_revertible_history`` anchors, and ``/revert`` composes back to.
REVERT_CHECKPOINT = "good state"


def build_revertible_history(client: TestClient, document_id: str) -> None:
    """A labelled checkpoint with a later batch on top of it — what ``/revert`` needs to compose.

    Without the batch above the anchor there is nothing to undo back to it, and a locked revert
    would be indistinguishable from a revert that had no work.
    """
    anchored = client.post(
        f"/documents/{document_id}/operations",
        json={
            "operations": [title_operation("Anchored")],
            "checkpoint": REVERT_CHECKPOINT,
        },
    )
    assert anchored.status_code == 200, anchored.text
    drift = client.post(
        f"/documents/{document_id}/operations",
        json={"operations": [title_operation("Drift")]},
    )
    assert drift.status_code == 200, drift.text


def structured_edit_request() -> dict:
    """The inspector's own shape: one node's text, set through the structured-edit route."""
    return {
        "edit": {
            "kind": "modify",
            "target": {"kind": "node", "id": "node_contact_name"},
            "patch": {
                "kind": "node",
                "value": {"text": {"content": {"kind": "set", "value": "Human repair"}}},
            },
        }
    }


# --- the lock ---------------------------------------------------------------------------------


def test_applying_operations_is_refused_while_a_design_run_holds_the_document(
    client: TestClient,
) -> None:
    document = create_document(client)
    store = HybridRepository()
    run_id = start_leg_run(store, document["id"])

    response = client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("Human Title")]},
    )

    assert_locked(response, run_id)
    # The refusal WROTE NOTHING: the document is still where the agent left it.
    assert store.require_document(document["id"])["current_version"] == 0


def test_replacing_the_scene_is_refused_while_a_design_run_holds_the_document(
    client: TestClient,
) -> None:
    document = create_document(client)
    store = HybridRepository()
    run_id = start_leg_run(store, document["id"])
    scene = stored_scene(client, document["id"])
    scene["meta"]["title"] = "Human Replacement"

    response = client.put(f"/documents/{document['id']}/scene", json={"scene": scene})

    assert_locked(response, run_id)
    assert store.require_document(document["id"])["scene"]["meta"]["title"] == "Hospital Letter"


def test_undo_is_refused_while_a_design_run_holds_the_document(client: TestClient) -> None:
    document = create_document(client)
    build_undo_and_redo_history(client, document["id"])
    store = HybridRepository()
    run_id = start_leg_run(store, document["id"])
    version_before = store.require_document(document["id"])["current_version"]

    assert_locked(client.post(f"/documents/{document['id']}/undo"), run_id)

    assert store.require_document(document["id"])["current_version"] == version_before


def test_redo_is_refused_while_a_design_run_holds_the_document(client: TestClient) -> None:
    document = create_document(client)
    build_undo_and_redo_history(client, document["id"])
    store = HybridRepository()
    run_id = start_leg_run(store, document["id"])
    version_before = store.require_document(document["id"])["current_version"]

    assert_locked(client.post(f"/documents/{document['id']}/redo"), run_id)

    assert store.require_document(document["id"])["current_version"] == version_before


def test_a_structured_edit_is_refused_while_a_design_run_holds_the_document(
    client: TestClient,
) -> None:
    """The inspector's write path. It is the one a human reaches for WITHOUT thinking of it as
    an edit batch — rename a layer, retype a headline — so leaving it open would have left the
    rule true of the canvas and false of the panel beside it."""

    document = create_document(client)
    store = HybridRepository()
    run_id = start_leg_run(store, document["id"])

    assert_locked(
        client.post(f"/documents/{document['id']}/edits", json=structured_edit_request()),
        run_id,
    )
    assert store.require_document(document["id"])["current_version"] == 0

    finish_run(store, run_id)

    edited = client.post(
        f"/documents/{document['id']}/edits", json=structured_edit_request()
    )
    assert edited.status_code == 200, edited.text


def test_reverting_to_a_checkpoint_is_refused_while_a_design_run_holds_the_document(
    client: TestClient,
) -> None:
    """Revert is N undos composed, so it rewinds the agent's own committed checkpoints too —
    the most destructive of the manual paths, and the last one that was still open."""

    document = create_document(client)
    build_revertible_history(client, document["id"])
    store = HybridRepository()
    run_id = start_leg_run(store, document["id"])
    version_before = store.require_document(document["id"])["current_version"]

    assert_locked(
        client.post(
            f"/documents/{document['id']}/revert",
            params={"checkpoint": REVERT_CHECKPOINT},
        ),
        run_id,
    )
    assert store.require_document(document["id"])["current_version"] == version_before
    assert store.require_document(document["id"])["title"] == "Drift"

    finish_run(store, run_id)

    reverted = client.post(
        f"/documents/{document['id']}/revert", params={"checkpoint": REVERT_CHECKPOINT}
    )
    assert reverted.status_code == 200, reverted.text
    assert store.require_document(document["id"])["title"] == "Anchored"


# --- the lock LIFTS ---------------------------------------------------------------------------


def test_writes_succeed_again_once_the_run_is_terminal(client: TestClient) -> None:
    """The lock is a state, not a scar: a finished run leaves the document editable.

    The four canvas/history routes in one place; ``/edits`` and ``/revert`` assert their own lift
    beside their own refusal, because each needs a history the others do not.
    """

    document = create_document(client)
    build_undo_and_redo_history(client, document["id"])
    store = HybridRepository()
    run_id = start_leg_run(store, document["id"])
    # The lock was really armed on THIS document, so nothing below can pass vacuously.
    assert_locked(
        client.post(
            f"/documents/{document['id']}/operations",
            json={"operations": [title_operation("Too Early")]},
        ),
        run_id,
    )

    finish_run(store, run_id)

    applied = client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("Human Again")]},
    )
    assert applied.status_code == 200, applied.text
    scene = stored_scene(client, document["id"])
    scene["meta"]["title"] = "Human Replacement"
    replaced = client.put(f"/documents/{document['id']}/scene", json={"scene": scene})
    assert replaced.status_code == 200, replaced.text
    undone = client.post(f"/documents/{document['id']}/undo")
    assert undone.status_code == 200, undone.text
    redone = client.post(f"/documents/{document['id']}/redo")
    assert redone.status_code == 200, redone.text


# --- the lock is PER DOCUMENT ------------------------------------------------------------------


def test_a_run_on_another_document_does_not_lock_this_one(client: TestClient) -> None:
    """One busy artifact never freezes the workspace — the same tenant, two documents."""

    locked_document = create_document(client, title="Busy Ad")
    free_document = create_document(client, title="Free Ad")
    store = HybridRepository()
    run_id = start_leg_run(store, locked_document["id"])

    free = client.post(
        f"/documents/{free_document['id']}/operations",
        json={"operations": [title_operation("Human Title")]},
    )
    assert free.status_code == 200, free.text
    assert store.require_document(free_document["id"])["current_version"] == 1
    # ...and the busy one is still busy, so the pass above is not a lock that never armed.
    assert_locked(
        client.post(
            f"/documents/{locked_document['id']}/operations",
            json={"operations": [title_operation("Human Title")]},
        ),
        run_id,
    )


# --- the line the lock must not cross ----------------------------------------------------------


def test_the_running_agents_own_committer_still_writes_the_document(client: TestClient) -> None:
    """THE regression this test exists for: the lock must not lock the agent out of its own work.

    A leg turn's durable writes — every P0.4 mid-run checkpoint and the final commit — go through
    ``_LegSceneCommitter``, i.e. the governed ``design_apply_operations`` TOOL, not the HTTP route.
    This drives that real committer while its own run is ``running``, exactly as
    ``execute_agent_turn_job`` builds it.
    """

    from lumen_api.fleet_handler import DesignTurnHost
    from lumen_api.main import _LegSceneCommitter
    from lumen_api.toolbelt.wiring import DesignRunSubject

    document = create_document(client)
    store = HybridRepository()
    run_id = start_leg_run(store, document["id"])
    state = client.app.state
    committer = _LegSceneCommitter(
        doc=store.require_document(document["id"]),
        document_id=document["id"],
        host=DesignTurnHost(
            core=state.core,
            storage=state.storage,
            engine_cache_root=state.engine_cache_root,
        ),
        store=store,
        run_subject=DesignRunSubject(run_id=run_id),
        workspace_id=store.workspace_id,
        run_id=run_id,
        intent="Make the headline two lines.",
    )

    delta = [title_operation("Agent Title")]
    committer.commit(delta, committer.replay(delta), "Design turn (in progress)")

    stored = store.require_document(document["id"])
    assert stored["current_version"] == 1
    assert stored["scene"]["meta"]["title"] == "Agent Title"
    # The human is still locked out while that same run keeps going.
    assert_locked(
        client.post(
            f"/documents/{document['id']}/operations",
            json={"operations": [title_operation("Human Title")]},
        ),
        run_id,
    )

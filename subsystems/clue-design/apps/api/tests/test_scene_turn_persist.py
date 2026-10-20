"""genad Task 5 — a LEG scene turn persists its applied proposal under CAS.

The genweb ruling ("the executor owns the persist", `execute_web_turn_job`) extended to the
scene path. Until this landed, a chat-born ad turn returned a proposal nobody committed: the
editor's own route committed it when a human was watching, and a leg turn's proposal simply
evaporated, so the gallery never moved.

The rule is LEG-ONLY and gated at every step. A direct editor turn (`POST /agent/turns`,
`POST /agent/turn-preview`) carries no `leg` block, keeps proposing, and its result envelope
stays byte-identical — the editor still owns that commit through `/documents/{id}/operations`
(P3.7's layering rule).

These drive the REAL `execute_agent_turn_job` through the `app.state.agent_turn_runner` test
seam, exactly as `test_web_turns.py`'s leg section drives the web executor.
"""

from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from conftest import make_blob_store, make_client

from lumen_api.design_store import HybridRepository
from lumen_api.main import create_app


REPO_ROOT = Path(__file__).resolve().parents[3]
MINIMAL_SCENE_PATH = REPO_ROOT / "crates/lumen-core/fixtures/minimal_scene.json"
GENERATED_RASTER_ASSET_PATH = (
    REPO_ROOT / "crates/lumen-core/fixtures/assets/generated_raster_asset.json"
)


@pytest.fixture()
def client(tmp_path: Path) -> TestClient:
    app = create_app(tmp_path / "engine-cache")
    return make_client(app)


def minimal_scene() -> dict:
    return json.loads(MINIMAL_SCENE_PATH.read_text())


def create_document(client: TestClient, scene: dict | None = None) -> dict:
    response = client.post(
        "/documents", json={"title": "Hospital Letter", "scene": scene or minimal_scene()}
    )
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


def unreplayable_operation() -> dict:
    """An insert under a page that does not exist — the engine refuses it, so the executor
    must refuse to commit rather than trust the agent's own history."""
    return {
        "kind": "insert_node",
        "parent": {"kind": "page", "id": "missing_page"},
        "index": 0,
        "node": {
            "id": "node_orphan",
            "name": None,
            "kind": {"kind": "rect"},
            "transform": {
                "x": 0.0,
                "y": 0.0,
                "rotation": 0.0,
                "skew_x": 0.0,
                "skew_y": 0.0,
                "flip_x": False,
                "flip_y": False,
            },
            "size": {
                "width": {"kind": "fixed", "value": 10.0},
                "height": {"kind": "fixed", "value": 10.0},
            },
            "children": [],
            "fills": [],
            "strokes": [],
            "corner": {
                "top_left": 0.0,
                "top_right": 0.0,
                "bottom_right": 0.0,
                "bottom_left": 0.0,
            },
            "opacity": 1.0,
            "visible": True,
            "locked": False,
            "constraints": None,
            "layout": None,
            "text": None,
            "image": None,
            "effects": [],
            "slot_id": None,
            "metadata": {},
        },
    }


def _turn_host(client: TestClient, stub):
    """The embedded worker's turn host, built from `app.state` the way `create_app` does."""
    from lumen_api.fleet_handler import DesignTurnHost

    state = client.app.state
    return DesignTurnHost(
        agent_turn_runner=stub,
        core=state.core,
        storage=state.storage,
        engine_cache_root=state.engine_cache_root,
    )


def _scene_envelope(document_id: str, workspace_id: str, config: dict):
    from clue_design.envelopes import DesignTurnEnvelope

    run_id = f"run_{uuid4().hex[:12]}"
    # Executions pin metadata on their durable run, just as fleet-offered turns do.
    HybridRepository(workspace_id).create_run(run_id, None)
    return DesignTurnEnvelope(
        kind="agent_turn",
        work_id=uuid4(),
        workspace_id=workspace_id,
        run_id=run_id,
        checkpoint_thread_id=run_id,
        document_id=document_id,
        config=config,
    )


def proposing_runner(operations: list, received: dict | None = None):
    """A stub trio: proposes `operations` and applies nothing itself."""

    def stub(payload, root):
        if received is not None:
            received["payload"] = payload
        return {
            "schema_version": 1,
            "status": "proposed",
            "summary": "Agent proposed a document title update.",
            "run_id": "run_stub_scene",
            "trace_dir": ".lumen-runs/run_stub_scene",
            "preview_paths": [],
            "dsl_blocks": ["# doc title"],
            "operations": operations,
            "diagnostics": [],
            "artifacts": [],
        }

    return stub


LEG_BRIEF = "Build the Harbor & Sage launch ad: bold headline, product shot, booking CTA."


def _assert_conflict_is_legible(response: dict, *, moved_from: int, moved_to: int) -> None:
    """A conflict a human can act on: both versions named, and the reassurance that their own
    edit survived.

    Asserted on BOTH prose slots, because the two candidate reader keys differ: `summary` is
    the design editor's run-panel key, `stop_reason` the platform scene summarizer's
    (`_assistant_summary`, design_leg_wiring). NEITHER renders a conflict today — the builder
    is leg-only and a conflicted turn is a `failed` run that `_fail_turn` short-circuits with
    no assistant message — so this pins the durable result payload, ready for whichever surface
    the genad founder item on conflict routing hands it to. `failed_agent_turn_response` leaves
    `stop_reason` None, so a conflict built naively from it is contentless by construction.
    """

    for field in ("summary", "stop_reason"):
        text = response[field]
        assert isinstance(text, str) and text.strip(), f"{field} is empty"
        assert f"version {moved_from}" in text, f"{field} does not name the base version"
        assert f"version {moved_to}" in text, f"{field} does not name the current version"
        assert "preserved" in text, f"{field} does not say the human's edit survived"


def _leg_config(document: dict, base_version: int, prompt: str = "Go ahead.") -> dict:
    return {
        "request": {
            "prompt": prompt,
            "scene": document.get("scene") or minimal_scene(),
            "document_id": document["id"],
        },
        "delegation_bundle": {"brief": LEG_BRIEF},
        "history": [{"role": "user", "text": "Warmer."}],
        "leg": {"leg_id": "leg-1", "document_base_version": base_version},
    }


# --- (a) the happy path ------------------------------------------------------


def test_a_leg_scene_turn_commits_its_proposal_and_reports_the_new_version(
    client: TestClient,
) -> None:
    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()
    assert document["current_version"] == 0
    received: dict = {}

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([title_operation("Agent Title")], received)),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert response["status"] == "proposed"
    # The document ADVANCED: one version, the op's effect in the stored scene.
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 1
    assert stored["scene"]["meta"]["title"] == "Agent Title"
    # ...and the result carries it, so the platform's projection can pin the new version.
    assert response["current_version"] == 1
    # The runtime still ran on the composed leg prompt (P3.7/G9 unchanged).
    assert LEG_BRIEF in received["payload"].prompt


def test_platform_leg_envelope_resolves_reference_ids_when_manifest_key_is_absent(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Platform envelopes freeze ids in request; a missing by-value manifest is unresolved.

    Regression for the silent-inert bridge: ``dict.get`` previously turned a missing
    ``config.reference_assets`` into explicit ``None``, which told the runner this turn had no
    references and skipped the existing resolver completely.
    """

    import lumen_api.main as main

    document = create_document(client)
    store = HybridRepository()
    config = _leg_config(document, 0)
    config["request"]["reference_asset_ids"] = ["asset_reference_one"]
    received: dict[str, object] = {}

    def run_preview(payload, _root, **kwargs):
        received["ids"] = list(payload.reference_asset_ids)
        received["unresolved"] = (
            kwargs["resolved_reference_assets"] is main._REFERENCES_UNRESOLVED
        )
        return proposing_runner([title_operation("Referenced")])(payload, _root)

    monkeypatch.setattr(main, "run_agent_turn_preview", run_preview)
    status, response, _, _ = main.execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, config),
        store=store,
        host=_turn_host(client, None),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert received == {"ids": ["asset_reference_one"], "unresolved": True}


def test_a_leg_scene_turns_commit_is_labelled_with_the_users_message(
    client: TestClient,
) -> None:
    """The composed prompt is for the RUNTIME. The durable edit envelope's `intent` is a
    human-facing label, so it stays the user's own words — never the rendered brief block
    (the G9 rule, web twin at `test_web_turns.py`)."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(
            document["id"],
            store.workspace_id,
            _leg_config(document, 0, prompt="Make the headline two lines."),
        ),
        store=store,
        host=_turn_host(client, proposing_runner([title_operation("Two Lines")])),
        event_sink=None,
    )
    assert status == "succeeded", response

    envelopes = store.list_envelopes(document["id"])
    assert len(envelopes) == 1
    assert envelopes[0]["intent"] == "Make the headline two lines."


# --- (b) the CAS loss --------------------------------------------------------


def _drive_leg_turn(
    client: TestClient,
    document: dict,
    *,
    base_version: int,
    operations: list,
    prompt: str = "Go ahead.",
    received: dict | None = None,
):
    """One leg turn through the REAL executor, RECORDED on a run row the way the fleet worker
    records it (create → execute → complete).

    The recording is load-bearing for session continuity: "the version this session last wrote"
    is read off the newest succeeded run's stamped ``current_version``, so a turn nobody
    completed leaves no trace for the next turn to notice drift against.
    """

    from lumen_api.main import execute_agent_turn_job

    store = HybridRepository()
    envelope = _scene_envelope(
        document["id"], store.workspace_id, _leg_config(document, base_version, prompt=prompt)
    )
    store.create_run(envelope.run_id, document["id"], kind="agent_turn", payload={})
    status, response, event_type, event_data = execute_agent_turn_job(
        envelope,
        store=store,
        host=_turn_host(client, proposing_runner(operations, received)),
        event_sink=None,
    )
    store.complete_run(envelope.run_id, status, response, event_type, event_data)
    return status, response, event_type, event_data


def test_a_leg_scene_turn_on_a_moved_document_notes_the_drift_and_runs_anyway(
    client: TestClient,
) -> None:
    """Session continuity (2026-09-18) replaces the pre-run conflict.

    The session IS the document, so "the document moved since my last turn" is the normal
    condition of a second turn, not a terminal failure: the executor re-reads the document,
    tells the continued session what changed as DATA, and commits against the version it
    actually read. The frozen envelope base is no longer the CAS base — the write-time CAS
    (the test below) is what still protects a human edit that lands mid-run.
    """

    document = create_document(client)
    # Turn one: the agent commits, stamping `current_version` on its succeeded run — that stamp
    # is what makes "the version I last wrote" readable at all.
    status, response, _, _ = _drive_leg_turn(
        client, document, base_version=0, operations=[title_operation("Agent Title")]
    )
    assert (status, response["current_version"]) == ("succeeded", 1)

    # The human edit between turns: the document is now at version 2, the envelope still pins 0.
    applied = client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("Human Title")], "intent": "human moved the logo"},
    )
    assert applied.status_code == 200, applied.text

    received: dict = {}
    status, response, _, _ = _drive_leg_turn(
        client,
        document,
        base_version=0,
        operations=[title_operation("Agent Title 2")],
        received=received,
    )

    assert status == "succeeded", response
    prompt = received["payload"].prompt
    assert "DOCUMENT CHANGED SINCE YOUR LAST TURN" in prompt
    assert "human moved the logo" in prompt
    # It designed from the document's CURRENT scene, and committed on top of the human's edit
    # rather than clobbering it or refusing.
    assert received["payload"].scene["meta"]["title"] == "Human Title"
    store = HybridRepository()
    stored = store.require_document(document["id"])
    assert (stored["current_version"], response["current_version"]) == (3, 3)
    assert stored["scene"]["meta"]["title"] == "Agent Title 2"


def test_a_leg_scene_turn_on_a_document_no_agent_has_written_gets_no_drift_note(
    client: TestClient,
) -> None:
    """Drift is measured against the SESSION's own last write. With no prior agent run there
    is no "since your last turn" to speak of, so a moved document is simply the document."""

    document = create_document(client)
    applied = client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("Human Title")], "intent": "human moved the logo"},
    )
    assert applied.status_code == 200, applied.text

    received: dict = {}
    status, response, _, _ = _drive_leg_turn(
        client,
        document,
        base_version=0,
        operations=[title_operation("Agent Title")],
        received=received,
    )

    assert status == "succeeded", response
    assert "DOCUMENT CHANGED SINCE YOUR LAST TURN" not in received["payload"].prompt
    assert response["current_version"] == 2


def test_a_direct_editor_turn_joins_no_session_even_on_a_document_the_agent_wrote(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ruling T6-1: the session is a LEG-turn concept.

    A direct editor turn (``POST /agent/turns``) pins a document but carries no ``leg`` block, and
    the route threads it on its own run id — so it must keep its per-run runtime folder, join no
    session, and hear nothing about drift. Proven on the hardest case: a document THIS workspace's
    agent wrote and a human then moved, which is exactly when a leg turn would be told.
    """

    import lumen_api.main as main

    document = create_document(client)
    # A leg turn writes (and is recorded), then a human moves the document: drift now exists.
    status, response, _, _ = _drive_leg_turn(
        client, document, base_version=0, operations=[title_operation("Agent Title")]
    )
    assert (status, response["current_version"]) == ("succeeded", 1)
    applied = client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("Human Title")], "intent": "human moved the logo"},
    )
    assert applied.status_code == 200, applied.text

    store = HybridRepository()
    captured: dict = {}

    def run_preview(payload, _root, **kwargs):
        captured["session_id"] = kwargs.get("session_id")
        captured["run_id"] = kwargs.get("run_id")
        captured["prompt"] = payload.prompt
        return proposing_runner([])(payload, _root)

    monkeypatch.setattr(main, "run_agent_turn_preview", run_preview)
    status, response, _, _ = main.execute_agent_turn_job(
        _scene_envelope(
            document["id"],
            store.workspace_id,
            {
                "request": {
                    "prompt": "Repair the headline",
                    "scene": minimal_scene(),
                    "document_id": document["id"],
                }
            },
        ),
        store=store,
        host=_turn_host(client, None),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert captured["session_id"] is None
    assert captured["run_id"] is None
    # Byte-identical: the human's own words, no drift note, no leg blocks.
    assert captured["prompt"] == "Repair the headline"


class _StoreWithNoReadableHistory(HybridRepository):
    """A store whose DOCUMENT reads work and whose session-history read does not."""

    def latest_agent_written_version(self, document_id):  # type: ignore[override]
        raise RuntimeError("the history read failed")


def test_an_unreadable_session_history_costs_a_paragraph_not_the_turn(
    client: TestClient,
) -> None:
    """The drift note is advisory context. A turn that cannot read what moved still designs from
    the document it CAN read — the alternative is killing paid work over a paragraph."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = _StoreWithNoReadableHistory()
    received: dict = {}

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([title_operation("Agent Title")], received)),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert "DOCUMENT CHANGED SINCE YOUR LAST TURN" not in received["payload"].prompt
    assert response["current_version"] == 1


def test_the_scene_the_trio_designs_from_comes_from_the_document(client: TestClient) -> None:
    """The envelope's scene was frozen when the leg was dispatched; the document is truth."""

    document = create_document(client)
    applied = client.post(
        f"/documents/{document['id']}/operations",
        json={"operations": [title_operation("Fresh")]},
    )
    assert applied.status_code == 200, applied.text

    received: dict = {}
    store = HybridRepository()
    config = _leg_config(document, 0)
    # Deliberately stale, the way a queued leg envelope is.
    config["request"]["scene"]["meta"]["title"] = "Stale"

    from lumen_api.main import execute_agent_turn_job

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, config),
        store=store,
        host=_turn_host(client, proposing_runner([title_operation("Agent Title")], received)),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert received["payload"].scene["meta"]["title"] == "Fresh"
    # ...and the CAS base is the version actually read, not the envelope's frozen 0.
    assert response["current_version"] == 2


def test_a_leg_scene_turn_runs_inside_the_documents_session(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The runtime is told which session this turn belongs to, and which run it is — the
    session id continues the document's thread, the run id makes a RETRIED run resumable."""

    import lumen_api.main as main

    from clue_design.sessions import design_session_id

    document = create_document(client)
    store = HybridRepository()
    captured: dict = {}

    def run_preview(payload, _root, **kwargs):
        captured["session_id"] = kwargs.get("session_id")
        captured["run_id"] = kwargs.get("run_id")
        return proposing_runner([])(payload, _root)

    monkeypatch.setattr(main, "run_agent_turn_preview", run_preview)
    envelope = _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0))
    status, response, _, _ = main.execute_agent_turn_job(
        envelope, store=store, host=_turn_host(client, None), event_sink=None
    )

    assert status == "succeeded", response
    assert captured["session_id"] == design_session_id(store.workspace_id, document["id"])
    assert captured["run_id"] == envelope.run_id


def test_a_leg_scene_turn_that_loses_the_race_mid_run_conflicts_at_the_write(
    client: TestClient,
) -> None:
    """The window the early check CANNOT close: the human edit lands WHILE the trio runs.

    Simulated deterministically by editing from inside the stub runner — which executes at
    exactly that point — so the governed write's `expected_base_version` is the only thing left
    standing between the agent and a clobber. It holds, and the loss is terminal-honest."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()

    def racing_stub(payload, root):
        edit = client.post(
            f"/documents/{document['id']}/operations",
            json={"operations": [title_operation("Human Title")]},
        )
        assert edit.status_code == 200, edit.text
        return proposing_runner([title_operation("Agent Title")])(payload, root)

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, racing_stub),
        event_sink=None,
    )

    assert status == "failed"
    assert response["status"] == "conflicted"
    assert (response["base_version"], response["current_version"]) == (0, 1)
    # The late (CAS-race) conflict is exactly as legible as the early one — same builder, so a
    # marketer cannot tell which of the two windows they lost, and does not need to.
    _assert_conflict_is_legible(response, moved_from=0, moved_to=1)
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 1
    assert stored["scene"]["meta"]["title"] == "Human Title"


# --- (c) the non-leg layering guarantee --------------------------------------


def test_a_non_leg_scene_turn_persists_nothing_and_stays_byte_identical(
    client: TestClient,
) -> None:
    """P3.7's layering rule, proven by equality: a direct editor turn has no `leg` block, so
    its result envelope is EXACTLY the runner's — every new behaviour gates on that block."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()
    operations = [title_operation("Agent Title")]
    # The expected envelope is snapshotted from a DEEP COPY, before the run. The stub hands the
    # executor the very list object this test holds, so an expected envelope built from that
    # same list afterwards would AGREE with an in-place mutation instead of catching it — and
    # "byte-identical" is exactly the claim being made here.
    expected = proposing_runner(deepcopy(operations))(None, None)

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(
            document["id"],
            store.workspace_id,
            {
                "request": {
                    "prompt": "Repair the headline",
                    "scene": minimal_scene(),
                    "document_id": document["id"],
                }
            },
        ),
        store=store,
        host=_turn_host(client, proposing_runner(operations)),
        event_sink=None,
    )

    assert (status, kind, marker) == ("succeeded", "result", {"status": "proposed"})
    # Byte-identical: the runner's own envelope, no `current_version` grafted on. The one
    # addition every executor makes is lane 3 slice 5's `model_calls` receipts key, which is
    # present on EVERY terminal return — empty here, because the stub runner spends nothing.
    assert response == {**expected, "model_calls": []}
    assert "current_version" not in response
    # Nothing was committed — the editor still owns that commit.
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"]["meta"]["title"] == "Hospital Letter"
    assert store.list_envelopes(document["id"]) == []


def test_a_leg_turn_without_a_pinned_document_persists_nothing(
    client: TestClient,
) -> None:
    """A legacy (AD4.R-era) leg pins no document, so its envelope carries no
    `document_base_version`. That reads as preview-only — never a fabricated version zero,
    which would clobber whatever sits at the head."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()
    config = _leg_config(document, 0)
    del config["leg"]["document_base_version"]

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, config),
        store=store,
        host=_turn_host(client, proposing_runner([title_operation("Agent Title")])),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert "current_version" not in response
    assert store.require_document(document["id"])["current_version"] == 0


# --- (d) the empty proposal --------------------------------------------------


def test_a_leg_scene_turn_with_no_operations_persists_nothing_and_still_succeeds(
    client: TestClient,
) -> None:
    """A pure clarification is a real, successful outcome with nothing to commit."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([])),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert response["status"] == "proposed"
    assert "current_version" not in response
    assert store.require_document(document["id"])["current_version"] == 0
    assert store.list_envelopes(document["id"]) == []


# --- (d2) the post-persist re-read ------------------------------------------


class _StoreThatBreaksAfterTheWrite(HybridRepository):
    """A store whose reads work until the governed write has already committed.

    The re-read that stamps `current_version` onto the result runs AFTER the durable write.
    Anything that fails there is reporting on a turn that already happened, so it must not be
    allowed to turn a committed turn into `agent_runtime.failed` — the marketer would be told
    nothing was saved while their ad sits changed in the gallery.
    """

    def __init__(self) -> None:
        super().__init__()
        self.reads = 0

    def require_document(self, document_id):  # type: ignore[override]
        self.reads += 1
        # 1 = the executor's early CAS check, 2 = the post-persist re-read.
        if self.reads >= 2:
            raise RuntimeError("transient read failure after the commit")
        return super().require_document(document_id)


def test_a_committed_leg_scene_turn_survives_a_failing_post_persist_re_read(
    client: TestClient,
) -> None:
    """The write landed; only the version lookup after it failed. The turn stays a success."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = _StoreThatBreaksAfterTheWrite()

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([title_operation("Agent Title")])),
        event_sink=None,
    )

    # NOT `agent_runtime.failed`: the proposal is still the proposal it was.
    assert (status, kind) == ("succeeded", "result"), response
    assert response["status"] == "proposed"
    assert marker == {"status": "proposed"}
    assert response.get("diagnostics") == []
    # The version could not be read, so it is honestly absent rather than guessed at.
    assert "current_version" not in response
    # ...and the write really did land: the document advanced, once.
    verified = HybridRepository().require_document(document["id"])
    assert verified["current_version"] == 1
    assert verified["scene"]["meta"]["title"] == "Agent Title"
    assert store.reads == 2


# --- (e) the replay refusal --------------------------------------------------


def test_a_leg_scene_turn_whose_operations_do_not_replay_fails_honestly(
    client: TestClient,
) -> None:
    """The agent's operation history is a CLAIM until the engine reproduces it here. An op
    naming a node/page that does not exist is a refusal, not a write."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([unreplayable_operation()])),
        event_sink=None,
    )

    assert status == "failed"
    assert response["status"] == "failed"
    assert response["diagnostics"][0]["code"] == "agent_turn.operations_replay_failed"
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"]["meta"]["title"] == "Hospital Letter"
    assert store.list_envelopes(document["id"]) == []


# --- (f) genad walk F1: the empty-artboard steering block --------------------
#
# A chat-born ad document is BORN with one empty artboard page (the leg-open birth mints
# `new_scene` + one `add_page` at the resolved format). The author model's from-scratch habit
# is to open a turn with a top-level `page ...` block — which cannot work here: the page id
# already exists, so a page line that parses is refused by the engine (`page <id> already
# exists`) and one that does not parse leaves its indented elements parentless (LUMD0402).
# Five live runs thrashed the repair loop that way and died upstream. A LEG turn on an
# all-empty-paged scene therefore carries a deterministic document-state block naming the real
# page and quoting the `#page:<page_id>` fill form the engine genuinely accepts.

AD_PAGE_ID = "page_acbaa276202a57e4"


def empty_ad_scene(
    page_id: str = AD_PAGE_ID, width: float = 1200.0, height: float = 1200.0
) -> dict:
    """The newborn ad's scene: ONE artboard page at the ad format, zero children."""

    scene = minimal_scene()
    scene["pages"] = {
        page_id: {
            "id": page_id,
            "name": "Square",
            "size": {
                "width": width,
                "height": height,
                "unit": "pt",
                "preset": "custom",
                "orientation": "landscape" if width > height else "portrait",
                "source": {"width": width, "height": height, "unit": "px"},
                "output": {"raster": {"width_px": int(width), "height_px": int(height)}},
            },
            "children": [],
            "bleed": None,
            "safe_area": None,
            "background": [],
        }
    }
    scene["nodes"] = {}
    scene["slots"] = {}
    return scene


def _prompt_seen_by_the_runner(client: TestClient, config: dict) -> str:
    """Drive the REAL executor and return the prompt the trio was actually handed."""

    from lumen_api.main import execute_agent_turn_job

    store = HybridRepository()
    received: dict = {}
    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(config["request"]["document_id"], store.workspace_id, config),
        store=store,
        host=_turn_host(client, proposing_runner([], received)),
        event_sink=None,
    )
    assert status == "succeeded", response
    return received["payload"].prompt


def test_a_leg_turn_on_an_all_empty_scene_is_steered_to_fill_the_birth_page(
    client: TestClient,
) -> None:
    from lumen_api.main import execute_agent_turn_job  # noqa: F401  (import parity)

    # The newborn ad's scene is the DOCUMENT's scene, not only the envelope's: since session
    # continuity (2026-09-18) the executor designs from what the document holds.
    document = create_document(client, empty_ad_scene())
    config = _leg_config(document, 0, prompt="Go ahead.")
    config["request"]["scene"] = empty_ad_scene()

    prompt = _prompt_seen_by_the_runner(client, config)

    # The block is there, and it names the REAL page and the REAL dimensions — read off the
    # scene, never hardcoded (a wrong id would send the author at a page that does not exist).
    assert "DOCUMENT STATE" in prompt
    assert AD_PAGE_ID in prompt
    assert "1200×1200" in prompt
    # ...and it quotes the fill form the engine accepts, on the page that exists.
    assert f"#page:{AD_PAGE_ID}" in prompt
    # The leg's own context still rides the same prompt (P3.7/G9 unchanged).
    assert LEG_BRIEF in prompt
    assert "Go ahead." in prompt


def test_the_steering_block_reads_the_page_id_and_size_off_the_scene(
    client: TestClient,
) -> None:
    """A second document, a different id and format: the block moves with the scene."""

    document = create_document(client, empty_ad_scene("page_deadbeefdeadbeef", 1080.0, 1920.0))
    config = _leg_config(document, 0)
    config["request"]["scene"] = empty_ad_scene("page_deadbeefdeadbeef", 1080.0, 1920.0)

    prompt = _prompt_seen_by_the_runner(client, config)

    assert "#page:page_deadbeefdeadbeef" in prompt
    assert "1080×1920" in prompt
    assert AD_PAGE_ID not in prompt
    assert "1200×1200" not in prompt


def test_a_leg_turn_on_a_content_bearing_scene_gets_no_steering_block(
    client: TestClient,
) -> None:
    """The pre-genad shape — every scene leg until now pinned a document with content. Its
    prompt must stay byte-identical to what P3.7 composes."""

    from clue_design.leg_context import SCENE_ASSIGNMENT_LABEL, render_leg_turn_prompt

    document = create_document(client)
    config = _leg_config(document, 0, prompt="Warmer, please.")
    # `minimal_scene()` has a page WITH a child.
    assert config["request"]["scene"]["pages"]["page_a4"]["children"]

    prompt = _prompt_seen_by_the_runner(client, config)

    assert prompt == render_leg_turn_prompt(
        bundle=config["delegation_bundle"],
        history=config["history"],
        prompt="Warmer, please.",
        brief_label=SCENE_ASSIGNMENT_LABEL,
    )
    assert "DOCUMENT STATE" not in prompt


def test_a_leg_turn_on_a_scene_with_no_pages_gets_no_steering_block(
    client: TestClient,
) -> None:
    """A page-less scene is the genuine from-scratch case: `page ...` is the CORRECT move
    there, so the block must not appear and talk the author out of it."""

    from clue_design.leg_context import SCENE_ASSIGNMENT_LABEL, render_leg_turn_prompt

    document = create_document(client)
    config = _leg_config(document, 0)
    scene = empty_ad_scene()
    scene["pages"] = {}
    config["request"]["scene"] = scene

    prompt = _prompt_seen_by_the_runner(client, config)

    assert prompt == render_leg_turn_prompt(
        bundle=config["delegation_bundle"],
        history=config["history"],
        prompt="Go ahead.",
        brief_label=SCENE_ASSIGNMENT_LABEL,
    )
    assert "DOCUMENT STATE" not in prompt


def test_a_direct_editor_turn_is_untouched_even_on_an_empty_scene(
    client: TestClient,
) -> None:
    """The MVP editor's direct-turn contract (P3.7 layering): no leg block, no composition —
    the prompt reaching the trio is the human's own words, byte for byte."""

    document = create_document(client)
    config = {
        "request": {
            "prompt": "Fill this page with a launch ad.",
            "scene": empty_ad_scene(),
            "document_id": document["id"],
        }
    }

    prompt = _prompt_seen_by_the_runner(client, config)

    assert prompt == "Fill this page with a launch ad."


def _quoted_dsl_example(prompt: str) -> str:
    """The DSL block the steering note quotes, dedented back to column 0."""

    lines = prompt.splitlines()
    start = next(index for index, line in enumerate(lines) if line.startswith("    #page:"))
    block: list[str] = []
    for line in lines[start:]:
        if not line.strip():
            break
        assert line.startswith("    "), line
        block.append(line[4:])
    return "\n".join(block) + "\n"


def test_the_dsl_the_steering_block_quotes_actually_compiles_against_the_empty_page(
    client: TestClient,
) -> None:
    """The whole point of the block is that its DSL is a form the ENGINE accepts. A wrong form
    here would make the defect worse, so the quoted example is compiled against the same
    newborn scene the note was built from: it must apply cleanly, attach its subtree to the
    EXISTING page, and leave the page's stored size untouched.

    (The bare `#page:<page_id>` form the engine's own LUMD0402 hint suggests does NOT do this —
    `is_modification_line` needs two tokens, so a lone `#…` line is a comment and its children
    are orphaned. That is why the quoted line restates the page's name.)
    """

    scene = empty_ad_scene()
    document = create_document(client, scene)
    config = _leg_config(document, 0)
    config["request"]["scene"] = scene

    prompt = _prompt_seen_by_the_runner(client, config)
    source = _quoted_dsl_example(prompt)
    assert source.startswith(f'#page:{AD_PAGE_ID} name("Square")')

    result = client.app.state.core.compile_dsl_into_scene(scene, source)
    compile_output = result["dsl"]["compile_output"]
    assert compile_output["halted_at"] is None, compile_output["diagnostics"]
    assert [
        diagnostic
        for diagnostic in compile_output["diagnostics"]
        if diagnostic["diagnostic"]["severity"] == "error"
    ] == []
    assert result["dsl"]["operation_error"] is None
    compiled_page = result["scene"]["pages"][AD_PAGE_ID]
    assert compiled_page["children"] == ["ad_root"], "the subtree must attach to the EXISTING page"
    assert compiled_page["size"] == scene["pages"][AD_PAGE_ID]["size"], "the page must not move"


# --- (g) genad2 Task 3: the >=1-page success gate ----------------------------
#
# The zero-page birth (genad2 ruling 1) moved page authorship to the design agent:
# `open_design_leg@4` mints a scene document with NO pages at all, and the trio authors the page
# in a later turn at the size the user's own words imply. That makes "the turn produced nothing"
# newly indistinguishable from "the turn produced a design" at the persist seam — an empty or
# meta-only proposal on a page-less newborn used to come back a cheerful success while the
# gallery had nothing to open. A LEG turn whose APPLIED result still has zero pages is therefore
# refused honestly: no write, a typed `agent_turn.pageless_result` failure, the document exactly
# as it was.

PAGELESS_SUMMARY = (
    "Design finished without creating a page — nothing was saved; "
    "send another message to try again."
)


def create_pageless_document(client: TestClient) -> dict:
    """A document born the way `open_design_leg@4` births one: the engine's own `new_scene`,
    no page minted by anybody.

    Returned as the STORED row (not the creation DTO, which carries no scene) so `_leg_config`
    hands the turn the page-less scene the document really has.
    """

    response = client.post("/documents", json={"title": "Harbor & Sage Launch Ad"})
    assert response.status_code == 200, response.text
    document = HybridRepository().require_document(response.json()["document"]["id"])
    assert document["scene"]["pages"] == {}, "the birth scene must be page-less"
    assert document["current_version"] == 0
    return document


def add_page_operation(page_id: str = AD_PAGE_ID) -> dict:
    """The page the design agent is now the one to author."""

    return {"kind": "add_page", "page": empty_ad_scene(page_id)["pages"][page_id]}


def remove_page_operation(page_id: str) -> dict:
    """The other way a turn can end page-less: it deletes the page that was there."""

    return {"kind": "remove_page", "page_id": page_id}


def _assert_pageless_refusal(response: dict) -> None:
    assert response["status"] == "failed"
    assert response["operations"] == []
    assert response["diagnostics"][0]["code"] == "agent_turn.pageless_result"
    # The sentence a marketer reads names the fact — no page was made, nothing was saved, and
    # what to do next. "Design turn failed." would be true and useless. Asserted on BOTH prose
    # slots for the reason `_assert_conflict_is_legible` gives: `summary` is the design editor's
    # run-panel key, `stop_reason` the platform scene summarizer's, and the failure builder
    # leaves the latter None unless it is set deliberately.
    assert response["summary"] == PAGELESS_SUMMARY
    assert response["stop_reason"] == PAGELESS_SUMMARY


def test_a_leg_scene_turn_that_authors_the_first_page_commits_it(
    client: TestClient,
) -> None:
    """(a) The happy zero-page path: the agent authors the page, so the gate lets it through and
    the newborn advances to a document with something in it."""

    from lumen_api.main import execute_agent_turn_job

    document = create_pageless_document(client)
    store = HybridRepository()

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([add_page_operation()])),
        event_sink=None,
    )

    assert status == "succeeded", response
    assert response["status"] == "proposed"
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 1
    assert list(stored["scene"]["pages"]) == [AD_PAGE_ID]
    assert response["current_version"] == 1
    assert len(store.list_envelopes(document["id"])) == 1


def test_a_leg_scene_turn_that_makes_no_page_is_refused_instead_of_committed(
    client: TestClient,
) -> None:
    """(b) The operations replay cleanly — they just do not amount to a design. Committing them
    would advance the version and report success over a document with nothing to open."""

    from lumen_api.main import execute_agent_turn_job

    document = create_pageless_document(client)
    store = HybridRepository()

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([title_operation("Agent Title")])),
        event_sink=None,
    )

    assert (status, kind) == ("failed", "result")
    assert marker == {"status": "failed"}
    _assert_pageless_refusal(response)
    # No write at all: not the version, not the title the meta-only op carried, not an envelope.
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"]["pages"] == {}
    assert stored["scene"]["meta"]["title"] == "Harbor & Sage Launch Ad"
    assert store.list_envelopes(document["id"]) == []


def test_a_leg_scene_turn_proposing_nothing_on_a_pageless_document_is_refused(
    client: TestClient,
) -> None:
    """(c) The empty-proposal shape never reaches the replay, so the gate has to be repeated over
    the STORED scene. On a page-less newborn a contentless proposal is not a clarification — it
    is a generation that produced nothing, and saying "proposed" would be a fake success."""

    from lumen_api.main import execute_agent_turn_job

    document = create_pageless_document(client)
    store = HybridRepository()

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([])),
        event_sink=None,
    )

    assert (status, kind) == ("failed", "result")
    assert marker == {"status": "failed"}
    _assert_pageless_refusal(response)
    assert "current_version" not in response
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"]["pages"] == {}
    assert store.list_envelopes(document["id"]) == []


def test_a_leg_scene_turn_proposing_nothing_on_a_content_bearing_document_still_succeeds(
    client: TestClient,
) -> None:
    """(d) The regression pin. A pure clarification on a document that HAS a page is the same
    real, successful outcome it always was — byte-identical to the runner's own envelope. The
    gate reads the pages, never "did this turn commit anything"."""

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()
    # `minimal_scene()` — the scene this document was created from, and the one `_leg_config`
    # hands the turn — has a page WITH a child.
    assert store.require_document(document["id"])["scene"]["pages"]["page_a4"]["children"]

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([])),
        event_sink=None,
    )

    assert (status, kind, marker) == ("succeeded", "result", {"status": "proposed"})
    # Plus the executor's `model_calls` receipts key — see the (a) byte-identity pin.
    assert response == {**proposing_runner([])(None, None), "model_calls": []}
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert store.list_envelopes(document["id"]) == []


def test_a_leg_turn_that_deletes_the_only_page_is_refused_and_the_document_survives(
    client: TestClient,
) -> None:
    """(f) The other way into the refusal, and the one the prose does NOT describe.

    Every case above starts page-less and never gets a page. This one starts with REAL content
    and the turn deletes it: `remove_page` on the only page leaves an empty scene, which the
    engine refuses exactly as it refuses a newborn that authored nothing. The behaviour is the
    right one — a "successful" turn that erased the artifact would be the worst possible commit,
    and the document is left byte-untouched — but it is worth pinning precisely BECAUSE the
    refusal's own sentence ("Design finished without creating a page") misdescribes it. If a
    later lane wants deletion to read differently, this test is where that decision has to be
    made deliberately rather than discovered in production.
    """

    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()
    before = store.require_document(document["id"])
    assert list(before["scene"]["pages"]) == ["page_a4"], "the fixture must have exactly one page"

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([remove_page_operation("page_a4")])),
        event_sink=None,
    )

    assert (status, kind) == ("failed", "result")
    assert marker == {"status": "failed"}
    _assert_pageless_refusal(response)
    # The engine's own text rides the detail (Task-7 sweep) instead of being dropped, the way
    # the replay refusal beside it has always forwarded `error.message`.
    assert response["diagnostics"][0]["hint"] == (
        "The turn's result contains no page, so there would be nothing to show; "
        "the design was not saved and the document is unchanged. "
        "The engine reported: operation batch produced an invalid scene"
    )
    # Nothing was written — the page, its children, and the version are all exactly as they were.
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"] == before["scene"]
    assert store.list_envelopes(document["id"]) == []


def test_an_unreplayable_turn_on_a_pageless_document_still_reports_the_replay_failure(
    client: TestClient,
) -> None:
    """The gate must not swallow its neighbour's code. A page-less document is exactly where the
    two refusals could be confused, so the engine's own precedence is pinned: an operation that
    cannot apply at all fails BEFORE the scene is validated, so it is still an unreplayable
    history — `agent_turn.pageless_result` is reserved for operations that applied and simply did
    not amount to a page."""

    from lumen_api.main import execute_agent_turn_job

    document = create_pageless_document(client)
    store = HybridRepository()

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, proposing_runner([unreplayable_operation()])),
        event_sink=None,
    )

    assert status == "failed"
    assert response["diagnostics"][0]["code"] == "agent_turn.operations_replay_failed"
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert store.list_envelopes(document["id"]) == []


class _AcceptingPagelessCore:
    """An engine that ACCEPTS the replay and hands back a page-less scene.

    The real engine refuses that scene itself (`LUMV0100`, `validate_scene`), so on the operations
    half of the gate its `CoreError` is what fires today and the post-replay page check never runs
    against it. That is exactly why the check is worth pinning separately: the contract is "what
    would be WRITTEN must have a page", read off the applied scene — not "the engine happened to
    complain". This stub is the only way to reach it, and it is what holds the line if the engine
    ever admits a page-less scene.
    """

    def __init__(self) -> None:
        self.calls = 0

    def apply_operations(self, scene: dict, operations: list) -> dict:
        self.calls += 1
        return {
            "scene": {**scene, "pages": {}},
            "diagnostics": [],
            "edit": {"inverse_operations": []},
        }


def test_a_leg_turn_whose_applied_scene_has_no_page_is_refused_even_if_the_engine_allows_it(
    client: TestClient,
) -> None:
    """(b, the gate itself) The operations replayed clean — no exception, no error diagnostic —
    and still produced nothing to look at. The refusal is the same one, and nothing is written."""

    from lumen_api.fleet_handler import DesignTurnHost
    from lumen_api.main import execute_agent_turn_job

    document = create_pageless_document(client)
    store = HybridRepository()
    core = _AcceptingPagelessCore()
    state = client.app.state

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=DesignTurnHost(
            agent_turn_runner=proposing_runner([add_page_operation()]),
            core=core,
            storage=state.storage,
            engine_cache_root=state.engine_cache_root,
        ),
        event_sink=None,
    )

    # The proposal DID carry a page-adding operation, so a gate reading the stored scene or the
    # operation list would have let this through: only the applied scene tells the truth.
    assert core.calls == 1
    assert (status, kind) == ("failed", "result")
    assert marker == {"status": "failed"}
    _assert_pageless_refusal(response)
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"]["pages"] == {}
    assert store.list_envelopes(document["id"]) == []


def test_a_non_leg_turn_on_a_pageless_document_stays_byte_identical(
    client: TestClient,
) -> None:
    """(e) P3.7's layering rule against the new gate: the editor's own direct turn carries no
    `leg` block, so it proposes exactly what the runner returned — the SAME operations that are
    refused one test above — and the editor's route still owns the commit."""

    from lumen_api.main import execute_agent_turn_job

    document = create_pageless_document(client)
    store = HybridRepository()
    operations = [title_operation("Agent Title")]
    # Snapshotted from a deep copy BEFORE the run, for the reason the (a) byte-identity pin
    # gives: the stub and this test share one list object, so a post-run expectation built from
    # it cannot tell "unchanged" from "mutated in place".
    expected = proposing_runner(deepcopy(operations))(None, None)

    status, response, kind, marker = execute_agent_turn_job(
        _scene_envelope(
            document["id"],
            store.workspace_id,
            {
                "request": {
                    "prompt": "Fill this document with a launch ad.",
                    "scene": document["scene"],
                    "document_id": document["id"],
                }
            },
        ),
        store=store,
        host=_turn_host(client, proposing_runner(operations)),
        event_sink=None,
    )

    assert (status, kind, marker) == ("succeeded", "result", {"status": "proposed"})
    # Plus the executor's `model_calls` receipts key — see the (a) byte-identity pin.
    assert response == {**expected, "model_calls": []}
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 0
    assert stored["scene"]["pages"] == {}
    assert store.list_envelopes(document["id"]) == []


# --- (h) genad2 walk: generated-asset custody at the leg persist seam ---------
#
# The live defect this section pins (walk of 2026-08-23, doc `doc_9e93c1e0…` v101): a chat-born
# ad's GENERATED hero image rendered in every server-side export (which bakes straight out of the
# engine cache) and 404'd on the editor canvas, which resolves pixels through
# `GET /asset-store/{digest}` — i.e. through DURABLE custody. The persist path's D4 backstop is
# what is supposed to make those two agree.
#
# What the walk's forensics actually showed, because it is not what anyone guessed: the backstop
# RAN and SUCCEEDED. Both of that scene's generated digests got live `artifact` rows, stamped
# `design_asset`, in the same second the leg run finished. The 404 came from the OTHER half of
# custody — the bytes those rows point at were not in the tree the serving process reads. The
# unhealable part, which is the defect these tests own, is that the backstop's skip probe was
# `exists`: a ROW probe ("no blob I/O"). Once a row exists no later persist re-puts the bytes,
# so a divergence that the engine cache could have repaired on the very next turn instead
# survives every turn, forever.


@pytest.fixture()
def custody_client(tmp_path: Path, design_storage) -> TestClient:
    """A leg-persist client whose blob backend is a tmp `FsStorage` this test can reach into.

    Reaching into it is the point: the live failure was bytes that were durably registered
    against ONE backend tree and read back from ANOTHER, and the only way to reproduce
    "the artifact row says custody, the backend has no bytes" is to delete a blob behind the
    store's back.
    """
    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    return make_client(app)


def _workspace_cache_dir(client: TestClient) -> Path:
    return Path(client.app.state.engine_cache_root) / os.environ["LUMEN_DEV_WORKSPACE_ID"]


#: A 1x1 PNG (the spec's smallest valid one) standing in for a trio-generated hero image.
TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010806000000"
    "1f15c4890000000d49444154789c626001000000ffff03000006000557"
    "bfabd40000000049454e44ae426082"
)


def unique_png() -> bytes:
    """A PNG whose digest no other row in the shared dev database can hold.

    Deliberate, and it cost an hour to learn: `/asset-store/{digest}` is workspace-UNSCOPED and
    scans a BOUNDED candidate list of live `artifact` rows for the content hash, skipping any
    whose bytes the backend cannot produce. `TINY_PNG` is a suite-wide fixture, so on a shared
    dev database its hash already has hundreds of rows from long-deleted tmp workspaces — the
    scan exhausts its budget on those corpses and 404s even when THIS test's custody is perfect.
    Bytes after IEND are legal trailing data, so the file stays a valid PNG.
    """
    return TINY_PNG + uuid4().bytes


def generated_asset_record(client: TestClient, asset_id: str, data: bytes) -> dict:
    """The record shape a trio image-generation tool leaves in the proposed scene.

    Copied from the live walk's `asset_img_run_6fa7_1`: bytes ONLY in the engine's per-workspace
    materialization cache, and a `local-store` location whose `opaque_ref` is the engine's own
    `sha256/{ab}/{digest}` relative path — never a `clue-storage` key, because nothing on the
    runtime tool's path re-points it.
    """
    digest = hashlib.sha256(data).hexdigest()
    from lumen_api.asset_custody import write_cache_blob

    write_cache_blob(_workspace_cache_dir(client), digest, data)
    record = json.loads(GENERATED_RASTER_ASSET_PATH.read_text())
    record["id"] = asset_id
    record["label"] = "hero_wave_ribbons"
    record["media"]["digest"] = {"algorithm": "sha256", "value": digest}
    record["media"]["location"] = {
        "provider": "local-store",
        "opaque_ref": f"sha256/{digest[:2]}/{digest}",
        "url": None,
    }
    record["media"]["mime_type"] = "image/png"
    record["media"]["byte_length"] = len(data)
    return record


def upsert_asset_operation(record: dict) -> dict:
    return {"kind": "upsert_asset", "asset": record}


def _durable_blob_path(client: TestClient, digest: str) -> Path:
    """Where this test's `FsStorage` physically holds one design blob."""
    from clue_design.storage import design_storage_key

    root = Path(client.app.state.storage._root)  # the tmp tree the fixture built
    return root.joinpath(
        *design_storage_key(os.environ["LUMEN_DEV_WORKSPACE_ID"], digest).split("/")
    )


def _artifact_row_count(digest: str) -> int:
    """How many live `artifact` rows THIS workspace holds for the digest — the idempotency
    assertion (scoped to the workspace, because the dev database is shared)."""
    from sqlalchemy import text

    from lumen_api.design_store import DesignStoreBridge

    workspace_id = os.environ["LUMEN_DEV_WORKSPACE_ID"]

    async def _count(conn):
        result = await conn.execute(
            text(
                "SELECT count(*) FROM artifact "
                "WHERE content_sha256 = :sha AND workspace_id = :ws "
                "AND erased_at IS NULL AND purged_at IS NULL"
            ),
            {"sha": digest, "ws": workspace_id},
        )
        return int(result.scalar_one())

    return DesignStoreBridge(workspace_id)._run(_count)


def _run_leg_turn(client: TestClient, document: dict, operations: list) -> dict:
    from lumen_api.main import execute_agent_turn_job

    store = HybridRepository()
    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(
            document["id"],
            store.workspace_id,
            _leg_config(document, document["current_version"]),
        ),
        store=store,
        host=_turn_host(client, proposing_runner(operations)),
        event_sink=None,
    )
    assert status == "succeeded", response
    assert response["status"] == "proposed", response
    return response


def test_fresh_generation_bytes_are_durable_before_the_canvas_can_first_load_it(
    custody_client: TestClient,
) -> None:
    """(h1) Fresh-generation ordering: the canvas must see what the exporter sees.

    A leg turn generates imagery mid-run; those bytes live only in the engine's wipeable cache
    until the persist seam claims them. The completed run is the earliest point at which the
    browser can fetch the committed document and schedule its first canvas paint. At that point
    `/asset-store/{digest}` — the exact route its image cache will resolve — must already serve
    the bytes, with the engine cache gone.
    """
    from lumen_api.asset_custody import cache_blob_path

    pixels = unique_png()
    document = create_document(custody_client)
    record = generated_asset_record(custody_client, "asset_img_run_test_1", pixels)
    digest = record["media"]["digest"]["value"]
    assert not make_blob_store(custody_client.app).exists(digest), "precondition: cache-only"

    _run_leg_turn(custody_client, document, [upsert_asset_operation(record)])

    # Custody is BYTES, not a row: destroy the cache before simulating the
    # canvas's first document fetch. The scene may not become observable while
    # its image is still cache-only.
    cache_blob_path(_workspace_cache_dir(custody_client), digest).unlink()
    first_load = custody_client.get(f"/documents/{document['id']}")
    assert first_load.status_code == 200, first_load.text
    first_scene_asset = first_load.json()["scene"]["assets"][record["id"]]
    assert first_scene_asset["media"]["digest"]["value"] == digest

    served = custody_client.get(f"/asset-store/{digest}")
    assert served.status_code == 200, served.text
    assert served.content == pixels


def test_a_leg_persist_heals_a_scene_asset_whose_durable_bytes_are_gone(
    custody_client: TestClient,
) -> None:
    """(h2) THE live defect, and the healing contract.

    The walk's broken banner is exactly this state: a LIVE `artifact` row for the digest (the
    fleet worker's persist wrote one) and NO readable bytes in the backend the design API holds
    — because the two processes resolved the relative `CLUE_STORAGE_FS_ROOT` default against
    different working directories, so the row and the blob landed in different trees.

    The backstop's skip probe was row-only (`design_bytes_exist`, "no blob I/O"), so once a row
    existed no later persist could ever restore the bytes: the banner stayed broken forever.
    Custody is a claim about BYTES, so the probe must be about bytes — and then the next chat
    iteration on the broken ad heals it.
    """
    pixels = unique_png()
    document = create_document(custody_client)
    record = generated_asset_record(custody_client, "asset_img_run_test_2", pixels)
    digest = record["media"]["digest"]["value"]

    _run_leg_turn(custody_client, document, [upsert_asset_operation(record)])
    blob = _durable_blob_path(custody_client, digest)
    assert blob.is_file(), "precondition: the first persist gave custody"

    # The split-root shape: the row survives (it is in the shared database), the bytes do not
    # (they went to another process's tree).
    blob.unlink()
    assert make_blob_store(custody_client.app).exists(digest), "the row still claims custody"
    assert custody_client.get(f"/asset-store/{digest}").status_code == 404
    # ...and the cache still holds them, which is why healing is possible at all: the engine
    # cache root is anchored to the design tree, so BOTH processes always agreed on it.

    # The next iteration turn on the same document — the marketer asking for one more change.
    document = HybridRepository().require_document(document["id"])
    _run_leg_turn(custody_client, document, [title_operation("Warmer headline")])

    served = custody_client.get(f"/asset-store/{digest}")
    assert served.status_code == 200, served.text
    assert served.content == pixels


def test_a_leg_persist_over_complete_custody_does_not_duplicate_it(
    custody_client: TestClient,
) -> None:
    """(h3) Idempotent: re-persisting a scene whose assets are already durable is a no-op."""
    pixels = unique_png()
    document = create_document(custody_client)
    record = generated_asset_record(custody_client, "asset_img_run_test_3", pixels)
    digest = record["media"]["digest"]["value"]

    _run_leg_turn(custody_client, document, [upsert_asset_operation(record)])
    assert _artifact_row_count(digest) == 1
    blob = _durable_blob_path(custody_client, digest)
    stat_before = blob.stat().st_mtime_ns

    document = HybridRepository().require_document(document["id"])
    _run_leg_turn(custody_client, document, [title_operation("Second pass")])

    assert _artifact_row_count(digest) == 1, "custody must not be re-minted"
    assert blob.stat().st_mtime_ns == stat_before, "the blob must not be re-put"
    assert custody_client.get(f"/asset-store/{digest}").content == pixels


# --- (i) P0.4 checkpoint commits ---------------------------------------------
#
# `subsystems/clue-design/docs/deepagent-fast-loop-v1-spec.md` §4 P0.4. Before these, a leg turn
# wrote ONCE, at finalize — so the 2026-08-24 run that spent 20m42s producing a valid,
# reviewer-accepted scene and then hit an OpenRouter 403 on its last call discarded all of it and
# left the document at version 0 ("Nothing was saved"). Now each verified authoring round commits
# as it lands.
#
# The runtime half of the seam is `LumenDesignTools.checkpoint_scene`, fired from `render_preview`
# (orchestrator-only, once per round). Here it is driven through the same test seam the rest of
# this file uses: a stub trio that calls the checkpoint sink the way the runtime does — handing it
# the FULL operation ledger so far, once per round.


def checkpointing_runner(
    rounds: list[list],
    *,
    outcome: str = "proposed",
    observed: list | None = None,
):
    """A stub trio that checkpoints once per round, exactly as the runtime's round-verification
    seam does: the sink always receives the whole ledger to date, never just the new tail.

    ``outcome="failed"`` is the quota-403-at-finalize shape — rounds landed, the run then died
    without ever proposing anything.
    """

    def stub(payload, root, scene_checkpoint=None):
        ledger: list = []
        for operations in rounds:
            ledger.extend(operations)
            if scene_checkpoint is not None:
                scene_checkpoint(
                    list(ledger), {"reason": "render_preview", "preflight_clean": True}
                )
            if observed is not None:
                # Read the document back mid-run — this is what proves a checkpoint is durable
                # BEFORE the turn ends, rather than a buffered write that lands at finalize.
                observed.append(HybridRepository().require_document(payload.document_id))
        if outcome == "failed":
            return {
                "schema_version": 1,
                "status": "failed",
                "summary": "The model provider refused the finalize call (quota).",
                "run_id": "run_stub_scene",
                "trace_dir": ".lumen-runs/run_stub_scene",
                "preview_paths": [],
                "dsl_blocks": [],
                "operations": [],
                "diagnostics": [],
                "artifacts": [],
            }
        return {
            "schema_version": 1,
            "status": "proposed",
            "summary": "Agent proposed a design.",
            "run_id": "run_stub_scene",
            "trace_dir": ".lumen-runs/run_stub_scene",
            "preview_paths": [],
            "dsl_blocks": ["# design"],
            "operations": ledger,
            "diagnostics": [],
            "artifacts": [],
        }

    return stub


def test_an_accepted_round_persists_a_document_version_mid_run(
    client: TestClient,
) -> None:
    """(i1) The core promise: a round that lands is durable while the turn is still running.

    Two rounds, one operation each. The document must ALREADY be at version 1 when the second
    round begins — not at 0 with everything buffered for finalize.
    """
    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()
    assert document["current_version"] == 0
    observed: list = []

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(
            client,
            checkpointing_runner(
                [[title_operation("Round one")], [title_operation("Round two")]],
                observed=observed,
            ),
        ),
        event_sink=None,
    )

    assert status == "succeeded", response
    # MID-RUN: each round's commit was visible to a separate read before the next one ran.
    assert [snapshot["current_version"] for snapshot in observed] == [1, 2]
    assert observed[0]["scene"]["meta"]["title"] == "Round one"
    # ...and the turn still ends exactly where an un-checkpointed one would: base + len(ops).
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 2
    assert stored["scene"]["meta"]["title"] == "Round two"
    assert response["current_version"] == 2


def test_checkpoints_reach_the_same_head_as_one_finalize_write(
    client: TestClient,
) -> None:
    """(i2) Checkpoints are strictly ADDITIVE: same destination, same scene, more history.

    The same three operations, once checkpointed round-by-round and once written whole at
    finalize (the pre-P0.4 shape, which a two-argument stub still takes). The heads must agree.
    """
    from lumen_api.main import execute_agent_turn_job

    operations = [
        title_operation("One"),
        title_operation("Two"),
        title_operation("Three"),
    ]

    def fresh_document(document_id: str) -> dict:
        scene = minimal_scene()
        scene["meta"]["id"] = document_id
        response = client.post("/documents", json={"title": "Ad", "scene": scene})
        assert response.status_code == 200, response.text
        return response.json()["document"]

    store = HybridRepository()
    checkpointed = fresh_document("doc_checkpointed")
    execute_agent_turn_job(
        _scene_envelope(
            checkpointed["id"], store.workspace_id, _leg_config(checkpointed, 0)
        ),
        store=store,
        host=_turn_host(client, checkpointing_runner([[op] for op in operations])),
        event_sink=None,
    )

    at_once = fresh_document("doc_at_once")
    execute_agent_turn_job(
        _scene_envelope(at_once["id"], store.workspace_id, _leg_config(at_once, 0)),
        store=store,
        # A plain two-argument stub is never offered the sink, so this run is byte-for-byte the
        # pre-P0.4 save-on-finalize path.
        host=_turn_host(client, proposing_runner(operations)),
        event_sink=None,
    )

    left = store.require_document(checkpointed["id"])
    right = store.require_document(at_once["id"])
    assert left["current_version"] == right["current_version"] == 3
    assert left["scene"]["meta"]["title"] == right["scene"]["meta"]["title"] == "Three"
    # The one intended difference: the undo history records three landings instead of one.
    assert len(store.list_envelopes(checkpointed["id"])) == 3
    assert len(store.list_envelopes(at_once["id"])) == 1


def test_retokenized_text_matches_runtime_after_checkpoint_save_and_preflight(
    client: TestClient,
) -> None:
    """Same-token rebinding retains the accepted size across the real persist seam."""
    from lumen_agent.retokenize import build_retokenize_operations
    from lumen_api.main import execute_agent_turn_job

    core = client.app.state.core
    kit = core.platform_default_brand_kit()
    for name, entry in kit["tokens"]["typography"].items():
        style = entry["value"]["default"]
        if style.get("kind") == "style":
            style.update(
                font_family="Inter",
                font_weight=400,
                font_size=51.0 if name == "type.display" else 16.0,
            )
    sizes = []
    for checkpointed in (False, True):
        seed = core.new_scene(f"doc_token_replay_{checkpointed}", "Typography replay")
        unresolved = core.compile_dsl_into_scene(seed, '''page square size(1080,1080,px)
  artboard fr s(fill,fill) fill($surface.page)
    headline text "One clear idea" s(900,hug) style($type.display) font_size($type.size.7xl) fill($text.primary)
''')["scene"]
        # Establish the isolated test tenant through the normal API before
        # preflight loads the tenant's optional font-library cache.
        response = client.post("/documents", json={"title": "Typography replay", "scene": unresolved})
        assert response.status_code == 200, response.text
        document = response.json()["document"]
        store = HybridRepository()
        runtime = core.preflight_scene(unresolved, kit)
        assert not runtime["preflight"]["has_errors"]
        assert runtime["scene"]["nodes"]["headline"]["kind"]["font_size"] == 80.0
        operations = build_retokenize_operations(runtime["scene"], kit)
        assert len(operations) >= 2, "exercise incremental checkpoint tails"
        runtime_final = core.preflight_scene(
            core.apply_operations(runtime["scene"], operations)["scene"], kit
        )
        assert not runtime_final["preflight"]["has_errors"]
        runner = (
            checkpointing_runner([operations[:1], operations[1:]])
            if checkpointed else proposing_runner(operations)
        )
        status, response, _, _ = execute_agent_turn_job(
            _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
            store=store,
            host=_turn_host(client, runner),
            event_sink=None,
        )
        assert status == "succeeded", response
        saved = store.require_document(document["id"])
        assert saved["current_version"] == len(operations)
        assert saved["scene"]["nodes"]["headline"]["kind"]["font_size_token"] == "type.size.7xl"
        preflight = core.preflight_scene(saved["scene"], kit)
        assert not preflight["preflight"]["has_errors"]
        assert (
            preflight["scene"]["nodes"]["headline"]["kind"]
            == runtime_final["scene"]["nodes"]["headline"]["kind"]
        )
        sizes.append(preflight["scene"]["nodes"]["headline"]["kind"]["font_size"])
    assert sizes == [80.0, 80.0]


def test_a_run_that_fails_after_an_accepted_round_leaves_that_round_as_the_head(
    client: TestClient,
) -> None:
    """(i3) The 2026-08-24 failure, replayed: the run dies at finalize having produced real work.

    Pre-P0.4 the document stayed at version 0 and the marketer was told nothing was saved. Now the
    accepted round IS the head, and the failure result names the version it left behind.
    """
    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(
            client,
            checkpointing_runner(
                [[title_operation("Accepted round")]], outcome="failed"
            ),
        ),
        event_sink=None,
    )

    assert status == "failed", response
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 1, "the accepted round must survive the failed run"
    assert stored["scene"]["meta"]["title"] == "Accepted round"
    assert response["current_version"] == 1, "a failed-but-saved turn must say what it saved"


def test_a_redrive_after_a_checkpoint_continues_from_the_version_it_saved(
    client: TestClient,
) -> None:
    """(i4) Replay semantics, restated by session continuity (2026-09-18).

    Until this slice a redrive that found the document moved had to GUESS whether the mover was
    a human or its own checkpoint, and refused either way (``agent_turn.interrupted_after_
    checkpoint``, read off the durable run-event mark). It no longer has to: the turn re-reads
    the document, so the scene it designs from and the version it CAS's on are already the ones
    its earlier attempt left behind. The redrive simply carries on from there — and it still
    never accuses a human of an edit nobody made.
    """
    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()
    envelope = _scene_envelope(
        document["id"], store.workspace_id, _leg_config(document, 0)
    )
    # A real run row, so the checkpoint's durable mark can be emitted onto its event stream.
    store.create_run(envelope.run_id, document["id"])

    first_status, _, _, _ = execute_agent_turn_job(
        envelope,
        store=store,
        host=_turn_host(
            client,
            checkpointing_runner([[title_operation("Saved round")]], outcome="failed"),
        ),
        event_sink=None,
    )
    assert first_status == "failed"
    assert store.require_document(document["id"])["current_version"] == 1

    # The takeover: the SAME envelope, its frozen base of 0 now irrelevant, driven again.
    status, response, _, _ = execute_agent_turn_job(
        envelope,
        store=store,
        host=_turn_host(
            client,
            checkpointing_runner([[title_operation("Redrive round")]]),
        ),
        event_sink=None,
    )

    assert status == "succeeded", response
    # It started from the version its own checkpoint left and advanced it by its own one write —
    # the first attempt's work is neither lost nor applied twice.
    stored = store.require_document(document["id"])
    assert stored["current_version"] == 2
    assert stored["scene"]["meta"]["title"] == "Redrive round"
    assert len(store.list_envelopes(document["id"])) == 2
    assert "preserved" not in (response.get("summary") or "")


def test_a_human_edit_during_a_checkpointed_run_still_conflicts_at_the_next_write(
    client: TestClient,
) -> None:
    """(i5) The CAS is not weakened by checkpointing. A human edit landing between two rounds
    fences the second round's checkpoint (dropped, best-effort) and then the finalize write
    (conflicted) — the human's version stands, and nothing of theirs is overwritten.
    """
    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()

    def racing_stub(payload, root, scene_checkpoint=None):
        ledger = [title_operation("Round one")]
        scene_checkpoint(list(ledger), {"reason": "render_preview"})
        # The human edits between rounds, straight through the editor's own route.
        raced = client.post(
            f"/documents/{document['id']}/operations",
            json={"operations": [title_operation("Human wins")], "base_version": 1},
        )
        assert raced.status_code == 200, raced.text
        ledger.append(title_operation("Round two"))
        scene_checkpoint(list(ledger), {"reason": "render_preview"})
        return {
            "schema_version": 1,
            "status": "proposed",
            "summary": "Agent proposed a design.",
            "run_id": "run_stub_scene",
            "trace_dir": ".lumen-runs/run_stub_scene",
            "preview_paths": [],
            "dsl_blocks": ["# design"],
            "operations": ledger,
            "diagnostics": [],
            "artifacts": [],
        }

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, racing_stub),
        event_sink=None,
    )

    assert status == "failed", response
    assert response["status"] == "conflicted"
    stored = store.require_document(document["id"])
    assert stored["scene"]["meta"]["title"] == "Human wins"
    assert stored["current_version"] == 2


# --- (d) the session folder travels ------------------------------------------


@pytest.mark.parametrize("scene_skill_bundle", ["legacy", "candidate"])
def test_a_leg_scene_turn_stores_its_session_folder_and_names_the_manifest(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scene_skill_bundle: str,
) -> None:
    """Session continuity (2026-09-18), Task 8: the session folder is not the worker's.

    A session's memory lives in a folder on whichever worker ran its last turn, and fleet work is
    not sticky — so at turn end the agent-visible ``workspace/`` tree is registered as
    content-addressed blobs and the manifest's DIGEST is stamped on the run result. That stamp is
    the only durable pointer the next turn has, so this drives the REAL
    ``run_agent_turn_preview`` (no ``agent_turn_runner`` override) with only the runtime's own
    model call stubbed, and reads the manifest back the way the restore path will:
    ``read_blob(sha)``.

    BOTH skill bundles, because the CANDIDATE bundle re-roots the whole runtime at
    ``<trace_dir>/scene-candidate`` — that rebase is exactly what
    ``harness.effective_runtime_config`` exists to keep in one place, and a test that knew the
    folder by a hand-built path would pass under one bundle and lie under the other (the lane's
    own ``.env`` sets ``candidate``). The fake below therefore resolves the folder the way the
    real ``create_design_deepagent`` does, through that same helper.
    """

    from dataclasses import replace as dataclass_replace

    import lumen_agent.config as agent_config
    import lumen_agent.harness as agent_harness
    import lumen_agent.llm as agent_llm
    from lumen_api.main import execute_agent_turn_job

    from clue_design.sessions import design_session_id

    document = create_document(client)
    store = HybridRepository()

    # The runtime's workspace root is redirected into tmp_path so the turn's session folder is
    # this test's, not the checkout's `.deepagent-workspace`.
    base_config = dataclass_replace(
        agent_config.AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "agent-workspace",
        scene_skill_bundle=scene_skill_bundle,
    )
    monkeypatch.setattr(
        agent_config.AgentRuntimeConfig,
        "from_env",
        classmethod(lambda _cls, _root=None: base_config),
    )
    # The multimodal preflight is a live model-catalogue call; the loop itself never runs here.
    monkeypatch.setattr(agent_llm, "assert_model_supports_image_input", lambda *a, **k: None)

    class _Tools:
        def __init__(self, turn_dir: Path) -> None:
            self.turn_dir = turn_dir
            self.scene = minimal_scene()

    seen: dict = {}

    def fake_turn(_prompt, config, **_kwargs):
        """Stand in for the trio: leave one file in the session workspace and stop.

        The REAL harness rebases the config inside ``create_design_deepagent`` before it touches
        any path, so the fake has to rebase too — otherwise it writes to a folder the snapshot
        (correctly) does not look in, and the test fails for a reason that is purely its own.
        """
        session_dir = agent_harness.effective_runtime_config(config).session_dir()
        seen["session_dir"] = session_dir
        (session_dir / "workspace").mkdir(parents=True, exist_ok=True)
        (session_dir / "workspace" / "brief.md").write_text("the brief", encoding="utf-8")
        turn_dir = session_dir / "turns" / str(config.run_id)
        turn_dir.mkdir(parents=True, exist_ok=True)
        return (
            {
                "outcome": "clarification_requested",
                "summary": "One question first.",
                "run_id": config.run_id,
                "clarification": {"questions": ["Which headline?"]},
            },
            _Tools(turn_dir),
        )

    monkeypatch.setattr(agent_harness, "run_deepagent_turn", fake_turn)

    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=_turn_host(client, None),
        event_sink=None,
    )

    assert status == "succeeded", response
    # Named through the same helper the harness and the snapshot both use, so the expectation
    # cannot drift from the rule — under `candidate` this is the `scene-candidate` sub-root.
    expected_root = agent_harness.effective_runtime_config(base_config).trace_dir
    assert seen["session_dir"] == (
        expected_root / "sessions" / design_session_id(store.workspace_id, document["id"])
    )
    sha = response["session_manifest_sha256"]
    assert isinstance(sha, str) and len(sha) == 64
    media_type, data = make_blob_store(client.app).read_blob(sha)
    assert media_type == "application/json"
    manifest = json.loads(data)
    assert manifest["schema_version"] == 1
    # The agent-visible workspace travelled; the turn's own outputs did not.
    assert set(manifest["files"]) == {"workspace/brief.md"}
    entry = manifest["files"]["workspace/brief.md"]
    assert entry["sha256"] == hashlib.sha256(b"the brief").hexdigest()
    # ...and the bytes are really in custody, which is what makes the restore possible.
    assert make_blob_store(client.app).read(entry["sha256"]) == b"the brief"


# --- (e) the platform's reads reach the runtime -------------------------------


def test_a_leg_turn_hands_the_platform_reads_to_the_runtime_and_a_direct_turn_does_not(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Design note 2026-09-19: a LEG turn's runtime config carries the platform's reads.

    The reads are a capability the PLATFORM composes (the account's research through the
    governed tools, the seller's pinned knowledge) and hands the design host as a factory; the
    design side never opens the platform database, so the only proof that matters is that the
    resolved object arrives on ``AgentRuntimeConfig`` — by value, for a leg turn, and for
    nothing else. A direct editor turn has no ``leg`` block, so the factory is never called and
    the runtime sees ``None``: same config as before this note.

    Drives the REAL ``run_agent_turn_preview`` (no ``agent_turn_runner`` override) with only the
    runtime's model call stubbed, exactly as the session-folder test above does — the config is
    assembled inside that function, so an executor-level capture would prove nothing.
    """

    from dataclasses import replace as dataclass_replace

    import lumen_agent.config as agent_config
    import lumen_agent.harness as agent_harness
    import lumen_agent.llm as agent_llm
    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()

    base_config = dataclass_replace(
        agent_config.AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "agent-workspace",
    )
    monkeypatch.setattr(
        agent_config.AgentRuntimeConfig,
        "from_env",
        classmethod(lambda _cls, _root=None: base_config),
    )
    monkeypatch.setattr(agent_llm, "assert_model_supports_image_input", lambda *a, **k: None)

    class _Tools:
        def __init__(self, turn_dir: Path) -> None:
            self.turn_dir = turn_dir
            self.scene = minimal_scene()

    seen: list = []

    def fake_turn(_prompt, config, **_kwargs):
        seen.append(config.platform_reads)
        turn_dir = tmp_path / "turns" / str(config.run_id)
        turn_dir.mkdir(parents=True, exist_ok=True)
        return (
            {
                "outcome": "clarification_requested",
                "summary": "One question first.",
                "run_id": config.run_id,
                "clarification": {"questions": ["Which headline?"]},
            },
            _Tools(turn_dir),
        )

    monkeypatch.setattr(agent_harness, "run_deepagent_turn", fake_turn)

    sentinel = object()
    calls: list = []

    def factory(envelope):
        calls.append(envelope.run_id)
        return sentinel if "leg" in envelope.config else None

    host = dataclass_replace(_turn_host(client, None), platform_reads_factory=factory)

    leg = _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0))
    status, response, _, _ = execute_agent_turn_job(leg, store=store, host=host, event_sink=None)
    assert status == "succeeded", response

    direct = _scene_envelope(
        document["id"],
        store.workspace_id,
        {
            "request": {
                "prompt": "Repair the headline",
                "scene": minimal_scene(),
                "document_id": document["id"],
            }
        },
    )
    status, response, _, _ = execute_agent_turn_job(direct, store=store, host=host, event_sink=None)
    assert status == "succeeded", response

    assert seen == [sentinel, None]
    # ...and the factory was asked ONCE, for the leg turn only: a direct turn does not even
    # reach the platform to be told "no".
    assert calls == [leg.run_id]


def test_a_leg_turn_whose_platform_reads_cannot_be_composed_still_designs(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reads are a capability, not a precondition (design note 2026-09-19).

    A scoped-preference failure refuses the turn, because a queued preference pin is the
    human's explicit selection and serving it unauthorized would be worse than not running.
    These reads are the opposite: nothing about them was chosen turn-by-turn, so a turn that
    cannot compose them designs from the brief exactly as it did before the note.
    """

    from dataclasses import replace as dataclass_replace

    import lumen_agent.config as agent_config
    import lumen_agent.harness as agent_harness
    import lumen_agent.llm as agent_llm
    from lumen_api.main import execute_agent_turn_job

    document = create_document(client)
    store = HybridRepository()

    base_config = dataclass_replace(
        agent_config.AgentRuntimeConfig.from_env(REPO_ROOT),
        trace_dir=tmp_path / "agent-workspace",
    )
    monkeypatch.setattr(
        agent_config.AgentRuntimeConfig,
        "from_env",
        classmethod(lambda _cls, _root=None: base_config),
    )
    monkeypatch.setattr(agent_llm, "assert_model_supports_image_input", lambda *a, **k: None)

    class _Tools:
        def __init__(self, turn_dir: Path) -> None:
            self.turn_dir = turn_dir
            self.scene = minimal_scene()

    seen: list = []

    def fake_turn(_prompt, config, **_kwargs):
        seen.append(config.platform_reads)
        turn_dir = tmp_path / "turns" / str(config.run_id)
        turn_dir.mkdir(parents=True, exist_ok=True)
        return (
            {
                "outcome": "clarification_requested",
                "summary": "One question first.",
                "run_id": config.run_id,
                "clarification": {"questions": ["Which headline?"]},
            },
            _Tools(turn_dir),
        )

    monkeypatch.setattr(agent_harness, "run_deepagent_turn", fake_turn)

    def exploding_factory(_envelope):
        raise RuntimeError("the platform loop is gone")

    host = dataclass_replace(_turn_host(client, None), platform_reads_factory=exploding_factory)
    status, response, _, _ = execute_agent_turn_job(
        _scene_envelope(document["id"], store.workspace_id, _leg_config(document, 0)),
        store=store,
        host=host,
        event_sink=None,
    )

    assert status == "succeeded", response
    assert seen == [None]

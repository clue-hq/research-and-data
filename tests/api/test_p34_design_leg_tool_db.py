"""P3.4 acceptance — ``open_design_leg``, the delegation entry (PD-part3 §1-D1/§2.3).

The head-of-abm's one way to hand the thread to the design deepagent: it validates the
D5 pins (document CAS guard; fail-closed brand-kit pin), builds the §2.3 delegation
bundle as one canonical-JSON artifact under a hard byte cap, and opens the durable
``design_leg`` row that the ingestion routing rule reads. The addressing discipline is
the ``open_directive_confirmation_gate`` precedent: everything of authority is *derived*
from the durable presenting turn (``source_turn_ref``), never accepted from the model.

All writes run in rolled-back transactions against the session-migrated DB. genweb slice 2
promoted the tool to @2 (a document-less open BIRTHS its web document); the birth itself is
covered by ``test_genweb_leg_document_birth_db.py``, and what this module still owns is the
@1 discipline that survived it unchanged — derived authority, the pins, the cap, the guard.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_submission import (
    get_submission,
    insert_submission,
    submissions_for_thread,
    turn_id_for_submission,
)
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.conversation_capture import persist_user_turn
from clue_api.design_leg_tools import (
    DESIGN_DELEGATION_BUNDLE_MAX_BYTES,
    DESIGN_DELEGATION_BUNDLE_MEDIA_TYPE,
    OpenDesignLegTool,
    design_leg_ref,
)
from clue_api.turn_action import derive_turn_action_ref
from clue_core import new_operation_id
from clue_design import legs as design_legs
from clue_design.documents import create_document
from clue_storage import FsStorage
from clue_toolbelt import (
    PreconditionFailed,
    ToolContext,
    ToolRegistry,
    invoke_tool,
)
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    conn_session_factory,
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

USER_ID = "usr_p34_leg"
NOW_UTC = datetime(2026, 8, 14, 12, 0, tzinfo=UTC)


async def _seed_conversation(
    conn: AsyncConnection,
    *,
    storage_root: Path,
    label: str,
    with_submission: bool = True,
) -> dict[str, Any]:
    """One workspace, project, thread, and a durable presenting head-of-abm turn."""

    workspace_id = f"ws_p34_{label}_{uuid4().hex[:10]}"
    project = await seed_project(conn, workspace_id, name=f"P3.4 {label}")
    await seed_principal(
        conn,
        workspace_id=workspace_id,
        user_id=USER_ID,
        membership_id=f"wsm_p34_{workspace_id}",
    )
    thread_id = f"thr_p34_{label}_{uuid4().hex[:8]}"
    await conn.execute(
        text("INSERT INTO agent_thread (id, workspace_id, project_id) VALUES (:id, :ws, :project)"),
        {"id": thread_id, "ws": workspace_id, "project": project.project_id},
    )
    conn_factory = conn_session_factory(conn)
    artifacts = DurableAgentArtifactStore(
        storage=FsStorage(storage_root / "artifacts"),
        conn_factory=conn_factory,
    )
    turn_id = uuid5(NAMESPACE_URL, f"p34:{label}:presenting-turn")
    captured = await persist_user_turn(
        conn,
        artifacts=artifacts,
        workspace_id=workspace_id,
        brand_id=project.brand_id,
        product_id=project.product_id,
        project_id=project.project_id,
        turn_id=turn_id,
        message="Please design the launch artboard for this account.",
    )
    if with_submission:
        await insert_submission(
            conn,
            turn_id=turn_id,
            workspace_id=workspace_id,
            project_id=project.project_id,
            thread_id=thread_id,
            submitted_by_user_id=USER_ID,
            submitted_via_membership_id=f"wsm_p34_{workspace_id}",
            onboarding_input_id=captured.onboarding_input_id,
            message_artifact_key=captured.artifact_ref.artifact_key,
            message_sha256=captured.artifact_ref.sha256,
            idempotency_key=f"p34-{label}-presenting",
        )
    manifest = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=json.dumps({"resources": []}).encode(),
        media_type="application/json",
    )
    execution_id = uuid5(NAMESPACE_URL, f"p34:{label}:execution")
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
            " pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
        ),
        {
            "id": execution_id,
            "workspace": workspace_id,
            "project": project.project_id,
            "hash": "0" * 64,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, "
            " resource_manifest_sha256, retention_class, requested_at, "
            " submitted_by_user_id, submitted_via_membership_id) "
            "VALUES (:id, :execution, :workspace, :project, :thread, :actor_id, "
            " 'head_of_abm', 'root-p34', 'head-of-abm', 'v24', :sha, :key, :sha256, "
            " :sha256, 'test', :requested_at, :user, :membership)"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "workspace": workspace_id,
            "project": project.project_id,
            "thread": thread_id,
            "actor_id": USER_ID,
            "sha": "0" * 64,
            "key": manifest.artifact_key,
            "sha256": manifest.sha256,
            "requested_at": NOW_UTC,
            "user": USER_ID,
            "membership": f"wsm_p34_{workspace_id}",
        },
    )
    return {
        "workspace_id": workspace_id,
        "project_id": project.project_id,
        "thread_id": thread_id,
        "turn_id": turn_id,
        "execution_id": execution_id,
        "conn_factory": conn_factory,
        "storage": FsStorage(storage_root / "artifacts"),
    }


async def _seed_design_targets(conn: AsyncConnection, *, workspace_id: str) -> dict[str, Any]:
    document = await create_document(
        conn,
        workspace_id=workspace_id,
        scene={"meta": {"id": f"doc_p34_{uuid4().hex[:8]}", "title": "Leg target"}},
    )
    # Two versioned kit rows so the pin can name a version that is not the latest.
    for version in (1, 2):
        await conn.execute(
            text(
                "INSERT INTO design_brand_kit "
                "(brand_kit_id, version, workspace_id, name, source, brand_kit_json, "
                " brand_summary_json, diagnostics_json) "
                "VALUES (:kit, :version, :ws, 'Acme kit', 'manual', "
                " CAST('{}' AS jsonb), CAST('{}' AS jsonb), CAST('[]' AS jsonb))"
            ),
            {"kit": "kit_p34", "version": version, "ws": workspace_id},
        )
    return {"document": document, "brand_kit_id": "kit_p34"}


def _registry(seeds: dict[str, Any]) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        OpenDesignLegTool(
            conn_factory=seeds["conn_factory"],
            storage=seeds["storage"],
        ),
        make_default=True,
    )
    return registry


def _context(seeds: dict[str, Any]) -> ToolContext:
    return ToolContext(
        workspace_id=seeds["workspace_id"],
        actor="agent",
        conn_factory=seeds["conn_factory"],
        operation_id=new_operation_id(),
    )


_CLAIM_REF = {
    "claim_id": str(uuid5(NAMESPACE_URL, "p34:claim")),
    "field_key": "account.operational_pain",
    "kind": "account_context",
}


def test_open_design_leg_opens_the_leg_and_persists_the_bundle(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The full delegation entry: pins validated, bundle persisted, leg row open, replay."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="open")
            targets = await _seed_design_targets(conn, workspace_id=seeds["workspace_id"])
            registry = _registry(seeds)
            result = await invoke_tool(
                registry,
                "open_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(seeds["turn_id"]),
                    "brief": "A launch-day artboard for the Acme account.",
                    "document_id": targets["document"]["id"],
                    "brand_kit_id": targets["brand_kit_id"],
                    "brand_kit_version": 2,
                    "claim_refs": (_CLAIM_REF,),
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )
            refs = result.references
            assert refs["created"] is True
            assert refs["thread_id"] == seeds["thread_id"]
            assert refs["leg_ref"] == design_leg_ref(refs["leg_id"])

            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=refs["leg_id"]
            )
            assert leg["state"] == "open_awaiting_user"
            assert leg["thread_id"] == seeds["thread_id"]
            assert leg["parent_execution_id"] == str(seeds["execution_id"])
            assert leg["opened_by_turn_id"] == str(seeds["turn_id"])
            assert leg["brand_kit_id"] == targets["brand_kit_id"]
            assert leg["brand_kit_version"] == 2
            assert leg["document_id"] == targets["document"]["id"]
            # A fresh document's CAS counter is 0 and the guard pins exactly that.
            assert leg["document_version_guard"] == 0

            # The bundle artifact: canonical JSON, §2.3 schema v1, inside the byte cap.
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT storage_key, media_type, size_bytes FROM artifact "
                            "WHERE storage_key = :key AND workspace_id = :ws"
                        ),
                        {"key": leg["bundle_artifact_ref"], "ws": seeds["workspace_id"]},
                    )
                )
                .mappings()
                .one()
            )
            assert row["media_type"] == DESIGN_DELEGATION_BUNDLE_MEDIA_TYPE
            assert int(row["size_bytes"]) <= DESIGN_DELEGATION_BUNDLE_MAX_BYTES
            bundle = json.loads(await seeds["storage"].get(leg["bundle_artifact_ref"]))
            assert bundle["schema_version"] == "1"
            assert bundle["bundle_kind"] == "design_delegation"
            assert bundle["workspace_id"] == seeds["workspace_id"]
            assert bundle["leg_id"] == refs["leg_id"]
            assert bundle["brief"] == "A launch-day artboard for the Acme account."
            assert bundle["brand_kit"] == {"brand_kit_id": "kit_p34", "version": 2}
            assert bundle["target_document"] == {
                "document_id": targets["document"]["id"],
                "version_guard": 0,
            }
            assert bundle["claim_refs"][0]["claim_id"] == _CLAIM_REF["claim_id"]
            assert bundle["binding_set_ref"] is None
            assert bundle["template_revision_ref"] is None
            assert bundle["turn_contract"] == {
                "proposal_flow": "propose_accept_reject",
                "clarification_rounds": 1,
            }

            # Spec 2026-09-20 §2.3: opening the leg queued its FIRST design turn, derived
            # from the user's own opening message — nobody has to say "go".
            first_turn_id = turn_id_for_submission(
                workspace_id=seeds["workspace_id"],
                thread_id=seeds["thread_id"],
                idempotency_key=f"design-leg-first-turn:{refs['leg_id']}:{seeds['turn_id']}",
            )
            first = await get_submission(
                conn, workspace_id=seeds["workspace_id"], turn_id=first_turn_id
            )
            assert first is not None
            assert first.derivation == "design_leg_first_turn"
            assert first.derived_from_turn_id == seeds["turn_id"]
            opening = await get_submission(
                conn, workspace_id=seeds["workspace_id"], turn_id=seeds["turn_id"]
            )
            assert opening is not None
            assert (first.message_artifact_key, first.message_sha256) == (
                opening.message_artifact_key,
                opening.message_sha256,
            )
            assert first.thread_id == seeds["thread_id"]

            # Replay: the same presenting turn opens the same leg, never a second one.
            replay = await invoke_tool(
                registry,
                "open_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(seeds["turn_id"]),
                    "brief": "A launch-day artboard for the Acme account.",
                    "document_id": targets["document"]["id"],
                    "brand_kit_id": targets["brand_kit_id"],
                    "brand_kit_version": 2,
                    "claim_refs": (_CLAIM_REF,),
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )
            assert replay.references["leg_id"] == refs["leg_id"]
            assert replay.references["created"] is False
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM design_leg WHERE thread_id = :thread"),
                    {"thread": seeds["thread_id"]},
                )
            ).scalar_one()
            assert int(count) == 1
            # The replayed open queued nothing new: one derived first turn per leg.
            derived = [
                row
                for row in await submissions_for_thread(
                    conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
                )
                if row.derivation == "design_leg_first_turn"
            ]
            assert [row.turn_id for row in derived] == [first_turn_id]

    run_async(scenario())


def test_open_design_leg_from_a_turn_with_no_submission_queues_nothing(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """A machine-originated opening turn has no captured message, so there is nothing to
    derive a first design turn FROM: the leg opens and waits for the user, exactly as before."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(
                conn, storage_root=tmp_path, label="nosub", with_submission=False
            )
            targets = await _seed_design_targets(conn, workspace_id=seeds["workspace_id"])
            result = await invoke_tool(
                _registry(seeds),
                "open_design_leg",
                {
                    "source_turn_ref": derive_turn_action_ref(seeds["turn_id"]),
                    "brief": "A launch-day artboard for the Acme account.",
                    "document_id": targets["document"]["id"],
                },
                _context(seeds),
                idempotency_ttl_s=60,
            )
            assert result.references["created"] is True
            leg = await design_legs.get_leg(
                conn, workspace_id=seeds["workspace_id"], leg_id=result.references["leg_id"]
            )
            assert leg["state"] == "open_awaiting_user"
            submissions = await submissions_for_thread(
                conn, workspace_id=seeds["workspace_id"], thread_id=seeds["thread_id"]
            )
            assert [row for row in submissions if row.derivation is not None] == []

    run_async(scenario())


def test_open_design_leg_with_no_document_must_say_what_to_create(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """@2 closed §2.1's hole: a leg that names no document CREATES one, so it has to say what.

    Until genweb slice 2 this call opened a pinless leg — a design session with nothing to
    design on, which is exactly the blocker (B2) that made "make me a landing page" land
    nowhere. The pin-free shape is therefore gone: the brand pin stays optional, but a
    document-less open now declares ``doc_kind``. The successful birth path (and its
    twin-proofing, brand stamp and gallery derivation) lives in
    ``test_genweb_leg_document_birth_db.py``.
    """

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="nopins")
            with pytest.raises(PreconditionFailed) as failure:
                await invoke_tool(
                    _registry(seeds),
                    "open_design_leg",
                    {
                        "source_turn_ref": derive_turn_action_ref(seeds["turn_id"]),
                        "brief": "Start a fresh design from the brief alone.",
                    },
                    _context(seeds),
                    idempotency_ttl_s=60,
                )
            assert "design_leg_doc_kind_required" in str(failure.value)
            assert (
                await design_legs.get_open_leg_for_thread(
                    conn,
                    workspace_id=seeds["workspace_id"],
                    thread_id=seeds["thread_id"],
                )
                is None
            )

    run_async(scenario())


def test_open_design_leg_refuses_a_stale_document_pin(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """The D5 CAS guard: an expected version that is not current is an honest refusal."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="stale")
            targets = await _seed_design_targets(conn, workspace_id=seeds["workspace_id"])
            with pytest.raises(PreconditionFailed) as failure:
                await invoke_tool(
                    _registry(seeds),
                    "open_design_leg",
                    {
                        "source_turn_ref": derive_turn_action_ref(seeds["turn_id"]),
                        "brief": "Edit the launch artboard.",
                        "document_id": targets["document"]["id"],
                        "expected_document_version": 7,
                    },
                    _context(seeds),
                    idempotency_ttl_s=60,
                )
            assert "design_document_pin_stale" in str(failure.value)
            assert (
                await design_legs.get_open_leg_for_thread(
                    conn,
                    workspace_id=seeds["workspace_id"],
                    thread_id=seeds["thread_id"],
                )
                is None
            )

    run_async(scenario())


def test_open_design_leg_brand_pin_is_fail_closed(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """D5: a brand pin must name an existing (id, version); half a pin is refused too."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="brand")
            registry = _registry(seeds)
            with pytest.raises(PreconditionFailed) as missing:
                await invoke_tool(
                    registry,
                    "open_design_leg",
                    {
                        "source_turn_ref": derive_turn_action_ref(seeds["turn_id"]),
                        "brief": "Design with the pinned kit.",
                        "doc_kind": "web",
                        "artifacts": [{"title": "Design with the pinned kit"}],
                        "brand_kit_id": "kit_that_does_not_exist",
                        "brand_kit_version": 1,
                    },
                    _context(seeds),
                    idempotency_ttl_s=60,
                )
            assert "brand_kit_pin_not_found" in str(missing.value)
            with pytest.raises(PreconditionFailed) as half:
                await invoke_tool(
                    registry,
                    "open_design_leg",
                    {
                        "source_turn_ref": derive_turn_action_ref(seeds["turn_id"]),
                        "brief": "Design with the pinned kit.",
                        "doc_kind": "web",
                        "artifacts": [{"title": "Design with the pinned kit"}],
                        "brand_kit_id": "kit_p34",
                    },
                    _context(seeds),
                    idempotency_ttl_s=60,
                )
            assert "brand_kit_pin_incomplete" in str(half.value)

    run_async(scenario())


def test_open_design_leg_refuses_a_second_open_leg_on_the_thread(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """D4's invariant, answered at the tool: one open leg per thread, refused not raced."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="second")
            await design_legs.open_leg(
                conn,
                workspace_id=seeds["workspace_id"],
                thread_id=seeds["thread_id"],
                parent_execution_id=seeds["execution_id"],
            )
            with pytest.raises(PreconditionFailed) as failure:
                await invoke_tool(
                    _registry(seeds),
                    "open_design_leg",
                    {
                        "source_turn_ref": derive_turn_action_ref(seeds["turn_id"]),
                        "brief": "Open a second leg.",
                        "doc_kind": "web",
                        "artifacts": [{"title": "Open a second leg"}],
                    },
                    _context(seeds),
                    idempotency_ttl_s=60,
                )
            assert "design_leg_already_open" in str(failure.value)

    run_async(scenario())


def test_open_design_leg_enforces_the_bundle_byte_cap(
    tmp_path: Path,
    migrated_db: bool,  # noqa: F811
) -> None:
    """§2.3's day-one size policy: an oversized bundle fails the build loudly."""

    if not migrated_db:
        pytest.skip("database not reachable")

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeds = await _seed_conversation(conn, storage_root=tmp_path, label="cap")
            oversized_refs = tuple(
                {
                    "claim_id": str(uuid5(NAMESPACE_URL, f"p34:cap:{index}")),
                    "field_key": "account.operational_pain",
                    "kind": "account_context",
                    "support_claim_ids": [
                        str(uuid5(NAMESPACE_URL, f"p34:cap:{index}:support:{support}"))
                        for support in range(6)
                    ],
                }
                for index in range(120)
            )
            with pytest.raises(PreconditionFailed) as failure:
                await invoke_tool(
                    _registry(seeds),
                    "open_design_leg",
                    {
                        "source_turn_ref": derive_turn_action_ref(seeds["turn_id"]),
                        "brief": "x" * 8_000,
                        "doc_kind": "web",
                        "artifacts": [{"title": "An oversized delegation"}],
                        "claim_refs": oversized_refs,
                    },
                    _context(seeds),
                    idempotency_ttl_s=60,
                )
            assert "design_bundle_too_large" in str(failure.value)
            assert (
                await design_legs.get_open_leg_for_thread(
                    conn,
                    workspace_id=seeds["workspace_id"],
                    thread_id=seeds["thread_id"],
                )
                is None
            )

    run_async(scenario())


def test_the_leg_tools_refuse_where_no_design_runtime_is_composed() -> None:
    """The deployment thread-wedge guard (adversarial-review fix): with chat on and the
    design runtime off, ``open_design_leg`` used to be live — and a leg opened there wedged
    its thread permanently (unconditional routing, fail-loud lane, no reaper: every escape
    hatch rides the same switch). The tools stay registered (the C6 audit is exact set
    equality) but refuse BEFORE any durable write, with no database touched at all."""

    import asyncio

    from clue_api.design_leg_tools import _LegRefused, build_design_leg_tools
    from clue_core import new_operation_id
    from clue_toolbelt import ToolContext

    def _boom() -> None:
        raise AssertionError("the runtime gate must refuse before any DB connection opens")

    ctx = ToolContext(
        workspace_id="ws_wedge_guard",
        actor="agent",
        conn_factory=_boom,  # type: ignore[arg-type]
        operation_id=new_operation_id(),
    )
    open_tool, finish_tool = build_design_leg_tools(
        conn_factory=_boom,  # type: ignore[arg-type]
        storage=None,
        enabled=False,
    )

    async def scenario() -> None:
        for tool, args in (
            (
                open_tool,
                {
                    "source_turn_ref": "turn-action:00000000-0000-4000-8000-000000000000",
                    "brief": "wedge probe",
                },
            ),
            (
                finish_tool,
                {
                    "source_turn_ref": "turn-action:00000000-0000-4000-8000-000000000000",
                    "reason": "abandoned",
                    "summary": "wedge probe",
                },
            ),
        ):
            failures = await tool.preconditions(tool.input_model.model_validate(args), ctx)
            assert [f.reason_code for f in failures] == ["design_leg_runtime_not_configured"]
            try:
                await tool.invoke(tool.input_model.model_validate(args), ctx)
            except _LegRefused as refusal:
                assert refusal.reason_code == "design_leg_runtime_not_configured"
            else:  # pragma: no cover - the refusal is the contract
                raise AssertionError("invoke must refuse on a design-disabled deployment")

    asyncio.run(scenario())

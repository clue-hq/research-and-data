"""Lane D slice D1: turn-derived identity and the canonical ``turn-action:<turn_id>`` receipt.

What this suite pins (charter `docs/specs/FI-lane-D-production-chat-and-launch.md` §3-P2, slice D1;
identity law `docs/specs/FI-lane-B-authenticated-principal-contract.md` §2/§7):

* **the §1.4 blocker is gone** — ``draft_account_research_directive@2`` declares
  ``user_instruction``/``source_turn_ref`` as turn authority, and the extended ``CapturedTurn`` now
  serves both, so the tool is reachable through the agent seam. The values are the turn's exact
  bytes and the derived receipt; a plan that proposes either is refused;
* **the receipt is derived, never accepted** — the ref has exactly one canonical spelling, resolves
  only inside its own workspace, only for the principal who submitted the turn, only when the human
  capture still agrees with the turn's artifact, and only when the turn carries an internal
  submitter. Every other case is a typed refusal (Lane B ruling 10, deny by default);
* **a confirming turn is the receipt** — ``confirm_account_research_directive@2`` persists
  ``confirmed_by``/``confirming_action_ref`` equal to the *ambient* values, and neither is a field a
  caller or the model can author.

DB-backed tests follow the ``tests/api`` conventions: a per-branch ``CLUE_DATABASE_URL``, one
rollback-only transaction per scenario, and a skip when no database is reachable. They also need
Lane D slice D0's ``agent_turn.submitted_by_user_id`` / ``submitted_via_membership_id`` columns.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import AgentTurnRequest, ArtifactRef
from clue_agents.contracts import AgentConstitution, ExecutionId
from clue_api.agent_execution_wiring import _trusted_tool_arguments
from clue_api.agent_runtime_wiring import _with_trusted_runtime
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.research_directive_tools import (
    ConfirmAccountResearchDirectiveInputV2,
    DraftAccountResearchDirectiveInput,
    build_research_directive_tools,
)
from clue_api.trial.discovery_fixture import BRAND_ID, PRODUCT_ID, PROJECT_ID, WORKSPACE_ID
from clue_api.turn_action import (
    ACTOR_MISMATCH,
    CAPTURE_NOT_FOUND,
    REF_MALFORMED,
    SUBMITTER_MISSING,
    TURN_NOT_FOUND,
    ResolvedTurnAction,
    TurnActionUnresolvable,
    derive_turn_action_ref,
    parse_turn_action_ref,
    resolve_turn_action,
)
from clue_api.turn_binding import CapturedTurn, CapturedTurnBinder, trusted_turn_fields
from clue_config import MemoryCaps
from clue_core import (
    OnboardingInputId,
    OnboardingInputKind,
    ResearchDirectiveId,
    new_operation_id,
)
from clue_memory import WriteSeam
from clue_research.directives import research_directive_draft_request_sha256
from clue_research.stage0 import submit_onboarding_input
from clue_spine import Project
from clue_storage import FsStorage
from clue_toolbelt import PreconditionFailed, ToolContext, ToolRegistry, invoke_tool
from tests._identity import seed_principal
from tests._workspace import seed_project
from tests.agents.conftest import artifact, constitution, domain_ref
from tests.api.test_account_deep_fixture_a1 import _pages
from tests.api.test_account_research_directive_a2 import _body
from tests.db.conftest import run_async
from tests.memory.conftest import add_judge, make_settings
from tests.profiling.conftest import conn_session_factory
from tests.stage0.conftest import rollback_conn

pytestmark = pytest.mark.usefixtures("require_profiling_db")

TTL = 60.0
NOW_UTC = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)

#: The user's own words. They are the *turn bytes*, so the directive's ``user_instruction`` is not a
#: retyped copy: it is what the human actually sent, served from the turn's artifact.
INSTRUCTION = (
    "Research the two selected accounts for administrative coordination friction, and do not "
    "assert anything you cannot lock to account-level evidence."
)

USER_ID = "usr_lane_d1_principal"
MEMBERSHIP_ID = "wsm_lane_d1_principal"
OTHER_USER_ID = "usr_lane_d1_bystander"


# --- the ref format -------------------------------------------------------------------------


def test_the_action_ref_has_exactly_one_canonical_spelling() -> None:
    """Minting and parsing are inverses, and the only accepted grammar is the canonical one."""

    turn_id = uuid4()
    ref = derive_turn_action_ref(turn_id)

    assert ref == f"turn-action:{turn_id}"
    assert parse_turn_action_ref(ref) == turn_id
    # The string form a durable row hands back mints the identical ref.
    assert derive_turn_action_ref(str(turn_id)) == ref


@pytest.mark.parametrize(
    "candidate",
    [
        pytest.param("", id="empty"),
        pytest.param("turn-action:", id="prefix-only"),
        pytest.param("00000000-0000-4000-8000-000000000001", id="bare-uuid"),
        pytest.param("human-turn:deep-direction-confirm-1", id="legacy-freetext-ref"),
        pytest.param("agent-turn:00000000-0000-4000-8000-000000000001", id="wrong-prefix"),
        pytest.param("turn-action:not-a-uuid", id="not-a-uuid"),
        pytest.param("turn-action:00000000-0000-4000-8000-000000000001 ", id="trailing-space"),
        pytest.param("turn-action:00000000000040008000000000000001", id="dashless"),
        pytest.param("turn-action:{00000000-0000-4000-8000-000000000001}", id="braced"),
        pytest.param("turn-action:urn:uuid:00000000-0000-4000-8000-000000000001", id="urn"),
        pytest.param("turn-action:00000000-0000-4000-8000-000000000001?scope=all", id="query"),
        pytest.param("TURN-ACTION:00000000-0000-4000-8000-000000000001", id="upper-prefix"),
        pytest.param("turn-action:00000000-0000-4000-8000-00000000000A", id="upper-uuid"),
    ],
)
def test_a_reference_that_is_not_exactly_a_turn_action_is_refused(candidate: str) -> None:
    """No client-extensible grammar: one action has one name, or it has none."""

    with pytest.raises(TurnActionUnresolvable) as refused:
        parse_turn_action_ref(candidate)
    assert refused.value.reason_code == REF_MALFORMED


# --- the blocker fix (no database needed) ------------------------------------------------------


def _binding(turn_id: UUID, *, answer: str = INSTRUCTION) -> CapturedTurn:
    return CapturedTurn(
        onboarding_input_id="00000000-0000-0000-0000-00000000beef",
        artifact_key=f"{WORKSPACE_ID}/{'0' * 64}",
        sha256="0" * 64,
        byte_count=len(answer.encode()),
        answer=answer,
        turn_id=str(turn_id),
        user_instruction=answer,
        source_turn_ref=derive_turn_action_ref(turn_id),
    )


def test_the_directive_tools_turn_fields_are_servable_from_the_binding() -> None:
    """The §1.4 blocker: both declared fields exist on ``CapturedTurn``, so the seam can serve them.

    Before D1 neither was a binding field, so ``value_for`` raised ``unbindable_field`` and every
    agent-planned call of ``draft_account_research_directive@2`` died at validation.
    """

    turn_id = uuid5(NAMESPACE_URL, "lane-d1:blocker")
    declared = trusted_turn_fields(DraftAccountResearchDirectiveInput)
    assert set(declared) == {"user_instruction", "source_turn_ref"}

    binding = _binding(turn_id)
    assert [binding.value_for(field) for field in declared] == [
        INSTRUCTION,
        f"turn-action:{turn_id}",
    ]


def test_a_plan_cannot_author_the_users_instruction_or_the_receipt() -> None:
    """Both directions of the PC-C8 rule: stripped from the model schema, and refused in a plan."""

    args_schema = _with_trusted_runtime(
        DraftAccountResearchDirectiveInput,
        name="DraftAccountResearchDirectiveInputAgentRuntime",
    )
    assert set(trusted_turn_fields(args_schema)) == set()
    for smuggled in ("user_instruction", "source_turn_ref", "project_id"):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            args_schema.model_validate({smuggled: "forged", "runtime": None})

    turn_id = uuid5(NAMESPACE_URL, "lane-d1:plan-arguments")
    for smuggled in ("user_instruction", "source_turn_ref"):
        with pytest.raises(ValueError, match="plan arguments carry trusted turn authority"):
            _trusted_tool_arguments(
                arguments={smuggled: "forged"},
                input_model=DraftAccountResearchDirectiveInput,
                constitution=_constitution(),
                captured_turn=_binding(turn_id),
            )


def test_the_confirmation_tool_has_no_caller_authored_receipt_at_all() -> None:
    """``confirm@2`` deleted the fields; ambient authority is not something a body may carry."""

    assert set(ConfirmAccountResearchDirectiveInputV2.model_fields) == {
        "directive_id",
        "expected_sha256",
    }
    for smuggled in ("confirmed_by", "confirming_turn_ref", "action_ref", "actor_id"):
        with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
            ConfirmAccountResearchDirectiveInputV2.model_validate(
                {
                    "directive_id": str(uuid4()),
                    "expected_sha256": "0" * 64,
                    smuggled: "forged",
                }
            )


# --- fixture: one durable human turn -----------------------------------------------------------


def _constitution(
    *,
    workspace_id: str = WORKSPACE_ID,
    project_id: str = PROJECT_ID,
    execution_id: ExecutionId | None = None,
) -> AgentConstitution:
    return constitution(
        workspace_id=workspace_id,
        project_id=project_id,
        brand_id=BRAND_ID,
        product_id=PRODUCT_ID,
        client_entity_id="00000000-0000-0000-0000-0000000000a2",
        actor_id=USER_ID,
        execution_id=execution_id or ExecutionId(uuid4()),
        project_card_ref=artifact("project-card.json", workspace_id=workspace_id),
        budget_envelope_ref=artifact("budget.json", workspace_id=workspace_id),
        resource_manifest_ref=artifact("resource-manifest.json", workspace_id=workspace_id),
        focus_refs=(domain_ref("account-1", workspace_id=workspace_id),),
    )


def _seeded(project: Project) -> dict[str, str | None]:
    """Scope a turn to a bare seeded project (no product, no ICP) — the negatives need no more."""

    return {
        "workspace_id": project.workspace_id,
        "project_id": project.project_id,
        "brand_id": project.brand_id,
        "product_id": None,
    }


@dataclass(frozen=True, slots=True)
class _HumanTurn:
    turn_id: UUID
    action_ref: str
    message_ref: ArtifactRef
    onboarding_input_id: UUID | None
    thread_id: str
    execution_id: UUID

    def request(self, *, project_id: str = PROJECT_ID) -> AgentTurnRequest:
        return AgentTurnRequest(
            turn_id=self.turn_id,
            thread_id=self.thread_id,
            constitution=_constitution(
                project_id=project_id,
                execution_id=ExecutionId(self.execution_id),
            ),
            user_message_artifact_ref=self.message_ref,
            requested_at=NOW_UTC,
        )


async def _persist_human_turn(
    conn: AsyncConnection,
    *,
    artifacts: DurableAgentArtifactStore,
    label: str,
    workspace_id: str = WORKSPACE_ID,
    project_id: str = PROJECT_ID,
    brand_id: str = BRAND_ID,
    product_id: str | None = PRODUCT_ID,
    message: str = INSTRUCTION,
    submitted_by_user_id: str | None = USER_ID,
    submitted_via_membership_id: str | None = MEMBERSHIP_ID,
    capture: bool = True,
) -> _HumanTurn:
    """Persist the durable trail a real human turn leaves, submitter columns included.

    The submitter stamp is a *fixture* stamp: the production route that writes it is Lane D D2's
    (and its principal is Lane B's). D1 owns what the platform does with an already-persisted turn,
    so the fixture writes the row the same shape D2 will.
    """

    # Lane D's B1 join made the submitter columns real foreign keys onto platform_user /
    # workspace_membership, so a claimed submitter must exist before the turn cites it.
    if submitted_by_user_id is not None:
        await seed_principal(
            conn,
            workspace_id=workspace_id,
            user_id=submitted_by_user_id,
            membership_id=submitted_via_membership_id,
        )
    message_ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=message.encode(),
        media_type="text/plain",
    )
    onboarding_input_id: UUID | None = None
    if capture:
        captured = await submit_onboarding_input(
            conn,
            workspace_id=workspace_id,
            brand_id=brand_id,
            product_id=product_id,
            project_id=project_id,
            kind=OnboardingInputKind.USER_TURN,
            artifact_key=message_ref.artifact_key,
            content_sha256=message_ref.sha256,
            actor="human",
            onboarding_input_id=OnboardingInputId(uuid5(NAMESPACE_URL, f"lane-d1:{label}:input")),
        )
        onboarding_input_id = captured.onboarding_input_id
    manifest_ref = await artifacts.persist_body(
        workspace_id=workspace_id,
        data=json.dumps({"resources": []}).encode(),
        media_type="application/json",
    )
    turn_id = uuid5(NAMESPACE_URL, f"lane-d1:{label}:turn")
    execution_id = uuid5(NAMESPACE_URL, f"lane-d1:{label}:execution")
    thread_id = f"thread-{label}"
    await conn.execute(
        text(
            "INSERT INTO execution "
            "(id, workspace_id, project_id, started_by, parameter_manifest_hash, "
            " pin_manifest_hash) "
            "VALUES (:id, :workspace, :project, 'human', :hash, :hash) "
            "ON CONFLICT (id) DO NOTHING"
        ),
        {
            "id": execution_id,
            "workspace": workspace_id,
            "project": project_id,
            "hash": "0" * 64,
        },
    )
    # D0's ``agent_turn_thread_fk`` (NOT VALID) requires the thread shell to exist for new writes.
    # The fixture provisions it itself rather than depending on any one caller's provisioning path.
    await conn.execute(
        text(
            "INSERT INTO agent_thread (id, workspace_id, project_id) "
            "VALUES (:id, :workspace, :project) ON CONFLICT (id) DO NOTHING"
        ),
        {"id": thread_id, "workspace": workspace_id, "project": project_id},
    )
    await conn.execute(
        text(
            "INSERT INTO agent_turn "
            "(id, execution_id, workspace_id, project_id, thread_id, actor_id, role, "
            " workspace_root_id, profile_name, profile_version, profile_sha256, "
            " resource_manifest_key, resource_manifest_artifact_sha256, resource_manifest_sha256, "
            " retention_class, requested_at, submitted_by_user_id, submitted_via_membership_id) "
            "VALUES (:id, :execution, :workspace, :project, :thread, :actor_id, 'head_of_abm', "
            " :root, 'head-of-abm', 'v22', :sha, :manifest_key, :manifest_sha, :manifest_sha, "
            " 'test', :requested_at, :submitted_by, :submitted_via)"
        ),
        {
            "id": turn_id,
            "execution": execution_id,
            "workspace": workspace_id,
            "project": project_id,
            "thread": thread_id,
            "actor_id": submitted_by_user_id or "agent:unauthenticated",
            "root": f"root-{label}",
            "sha": "0" * 64,
            "manifest_key": manifest_ref.artifact_key,
            "manifest_sha": manifest_ref.sha256,
            "requested_at": NOW_UTC,
            "submitted_by": submitted_by_user_id,
            "submitted_via": submitted_via_membership_id,
        },
    )
    await conn.execute(
        text(
            "INSERT INTO agent_artifact_ref "
            "(id, turn_id, workspace_id, owner_kind, owner_id, ref_role, ordinal, "
            " artifact_key, artifact_sha256, retention_class) "
            "VALUES (:id, :turn, :workspace, 'turn', :turn, 'user_message', 0, :key, :sha, 'test')"
        ),
        {
            "id": uuid5(NAMESPACE_URL, f"lane-d1:{label}:user-message-ref"),
            "turn": turn_id,
            "workspace": workspace_id,
            "key": message_ref.artifact_key,
            "sha": message_ref.sha256,
        },
    )
    return _HumanTurn(
        turn_id=turn_id,
        action_ref=derive_turn_action_ref(turn_id),
        message_ref=message_ref,
        onboarding_input_id=onboarding_input_id,
        thread_id=thread_id,
        execution_id=execution_id,
    )


# --- resolution: the adversarial matrix --------------------------------------------------------


def test_a_human_turn_resolves_to_one_deterministic_receipt(tmp_path: Path) -> None:
    """Resolution proves the turn, its capture, and its submitter — and mutates nothing."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, WORKSPACE_ID, name="Lane D1")
            cf = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "artifacts"),
                conn_factory=cf,
            )
            turn = await _persist_human_turn(
                conn,
                artifacts=artifacts,
                label="resolve",
                **_seeded(project),
            )

            resolved = await resolve_turn_action(
                turn.action_ref,
                workspace_id=WORKSPACE_ID,
                actor_id=USER_ID,
                conn_factory=cf,
            )
            assert resolved == ResolvedTurnAction(
                action_ref=turn.action_ref,
                turn_id=str(turn.turn_id),
                workspace_id=WORKSPACE_ID,
                submitted_by_user_id=USER_ID,
                submitted_via_membership_id=MEMBERSHIP_ID,
                onboarding_input_id=str(turn.onboarding_input_id),
                sha256=turn.message_ref.sha256,
            )
            # Replay-safe: a receipt is evidence, not a state transition.
            assert (
                await resolve_turn_action(
                    turn.action_ref,
                    workspace_id=WORKSPACE_ID,
                    actor_id=USER_ID,
                    conn_factory=cf,
                )
                == resolved
            )

    run_async(scenario())


def test_a_receipt_never_crosses_a_workspace_or_an_actor(tmp_path: Path) -> None:
    """Deny by default: another workspace's principal, and another user, both get nothing."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, WORKSPACE_ID, name="Lane D1")
            other = await seed_project(conn, "ws-lane-d1-other", name="Lane D1 elsewhere")
            cf = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "artifacts"),
                conn_factory=cf,
            )
            turn = await _persist_human_turn(
                conn,
                artifacts=artifacts,
                label="scope",
                **_seeded(project),
            )

            with pytest.raises(TurnActionUnresolvable) as foreign:
                await resolve_turn_action(
                    turn.action_ref,
                    workspace_id=other.workspace_id,
                    actor_id=USER_ID,
                    conn_factory=cf,
                )
            # Not "forbidden": in another workspace the turn simply does not exist.
            assert foreign.value.reason_code == TURN_NOT_FOUND

            with pytest.raises(TurnActionUnresolvable) as bystander:
                await resolve_turn_action(
                    turn.action_ref,
                    workspace_id=WORKSPACE_ID,
                    actor_id=OTHER_USER_ID,
                    conn_factory=cf,
                )
            assert bystander.value.reason_code == ACTOR_MISMATCH

            with pytest.raises(TurnActionUnresolvable) as unknown:
                await resolve_turn_action(
                    derive_turn_action_ref(uuid4()),
                    workspace_id=WORKSPACE_ID,
                    actor_id=USER_ID,
                    conn_factory=cf,
                )
            assert unknown.value.reason_code == TURN_NOT_FOUND

    run_async(scenario())


def test_a_turn_without_an_internal_submitter_proves_no_human_action(tmp_path: Path) -> None:
    """Every turn written today (trial, fleet, delegation) is exactly this shape."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, WORKSPACE_ID, name="Lane D1")
            cf = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "artifacts"),
                conn_factory=cf,
            )
            turn = await _persist_human_turn(
                conn,
                artifacts=artifacts,
                label="unauthenticated",
                **_seeded(project),
                submitted_by_user_id=None,
                submitted_via_membership_id=None,
            )

            with pytest.raises(TurnActionUnresolvable) as refused:
                await resolve_turn_action(
                    turn.action_ref,
                    workspace_id=WORKSPACE_ID,
                    actor_id=USER_ID,
                    conn_factory=cf,
                )
            assert refused.value.reason_code == SUBMITTER_MISSING

    run_async(scenario())


def test_a_turn_whose_message_is_not_a_human_capture_proves_nothing(tmp_path: Path) -> None:
    """The integrity join is re-run at resolution, not trusted from binding time."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            project = await seed_project(conn, WORKSPACE_ID, name="Lane D1")
            cf = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "artifacts"),
                conn_factory=cf,
            )
            turn = await _persist_human_turn(
                conn,
                artifacts=artifacts,
                label="uncaptured",
                **_seeded(project),
                capture=False,
            )

            with pytest.raises(TurnActionUnresolvable) as refused:
                await resolve_turn_action(
                    turn.action_ref,
                    workspace_id=WORKSPACE_ID,
                    actor_id=USER_ID,
                    conn_factory=cf,
                )
            assert refused.value.reason_code == CAPTURE_NOT_FOUND

    run_async(scenario())


# --- end to end: draft through the agent seam, then confirm on the turn's own receipt ----------


def test_the_confirming_turn_is_the_receipt_end_to_end(tmp_path: Path) -> None:
    """The Option-B first two steps, on the canonical fixture.

    ``draft_account_research_directive@2`` runs through the agent seam (the model proposes only
    what it may; the engine serves the user's words and the turn receipt), and the human gate then
    confirms that draft with the *ambient* identity derived from the same turn.
    """

    from clue_api.trial.account_deep_fixture import seed_insight_health_account_deep_fixture

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "artifacts")
            fixture = await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            cf = conn_session_factory(conn)
            artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=cf)
            turn = await _persist_human_turn(conn, artifacts=artifacts, label="option-b")

            def memory_factory(write_conn: AsyncConnection) -> WriteSeam:
                return WriteSeam(
                    write_conn,
                    add_judge(),
                    settings=make_settings(),
                    caps=MemoryCaps(),
                )

            registry = ToolRegistry()
            for tool in build_research_directive_tools(
                memory_write_factory=memory_factory,
                conn_factory=cf,
            ):
                registry.register(tool, make_default=tool.version == "2")

            # --- the agent seam: the model's proposal plus the engine's trusted merge -----------
            binder = CapturedTurnBinder(artifacts=artifacts, conn_factory=cf)
            request = turn.request()
            binding = await binder.bind(request)
            proposed: dict[str, Any] = {
                "product_id": PRODUCT_ID,
                "icp_key": fixture.deep_icp_key,
                "icp_version": fixture.deep_icp_version,
                "body": _body(fixture.selected_account_id).model_dump(mode="json"),
            }
            merged = _trusted_tool_arguments(
                arguments=proposed,
                input_model=DraftAccountResearchDirectiveInput,
                constitution=request.constitution,
                captured_turn=binding,
            )
            # The two fields that made this tool uncallable now arrive from the turn itself.
            assert merged["user_instruction"] == INSTRUCTION
            assert merged["source_turn_ref"] == turn.action_ref
            assert merged["project_id"] == PROJECT_ID

            draft_operation = new_operation_id()
            drafted = await invoke_tool(
                registry,
                "draft_account_research_directive",
                dict(merged),
                ToolContext(
                    workspace_id=WORKSPACE_ID,
                    actor="agent",
                    conn_factory=cf,
                    operation_id=draft_operation,
                    actor_id=USER_ID,
                    action_ref=turn.action_ref,
                ),
                idempotency_ttl_s=TTL,
            )
            assert drafted.references["status"] == "draft"
            directive_id = ResearchDirectiveId(draft_operation)
            stored = (
                await conn.execute(
                    text(
                        "SELECT source_turn_ref, draft_request_sha256, created_by "
                        "FROM account_research_directive WHERE directive_id = :directive_id"
                    ),
                    {"directive_id": directive_id},
                )
            ).one()
            assert stored.source_turn_ref == turn.action_ref
            assert stored.created_by == USER_ID

            # The user's exact bytes are not merely passed through: they are inside the durable
            # draft request digest, so a retyped-but-tidied instruction is a different draft.
            def request_digest(instruction: str) -> str:
                return research_directive_draft_request_sha256(
                    workspace_id=WORKSPACE_ID,
                    project_id=PROJECT_ID,
                    product_id=PRODUCT_ID,
                    icp_key=fixture.deep_icp_key,
                    icp_version=fixture.deep_icp_version,
                    body=_body(fixture.selected_account_id),
                    account_overrides={},
                    user_instruction=instruction,
                    source_turn_ref=turn.action_ref,
                    created_by=USER_ID,
                    actor_type="agent",
                    predecessor_id=None,
                )

            assert stored.draft_request_sha256 == request_digest(INSTRUCTION)
            assert stored.draft_request_sha256 != request_digest(INSTRUCTION.replace(",", ""))

            # --- the human gate: ambient identity, derived from the same turn -------------------
            resolved = await resolve_turn_action(
                turn.action_ref,
                workspace_id=WORKSPACE_ID,
                actor_id=USER_ID,
                conn_factory=cf,
            )
            confirm_body = {
                "directive_id": str(directive_id),
                "expected_sha256": drafted.references["canonical_json_sha256"],
            }
            confirm_ctx = ToolContext(
                workspace_id=WORKSPACE_ID,
                actor="human",
                conn_factory=cf,
                operation_id=new_operation_id(),
                actor_id=resolved.submitted_by_user_id,
                action_ref=resolved.action_ref,
            )
            confirmed = await invoke_tool(
                registry,
                "confirm_account_research_directive",
                confirm_body,
                confirm_ctx,
                idempotency_ttl_s=TTL,
            )

            assert confirmed.references["status"] == "confirmed"
            assert confirmed.references["confirmed_by"] == USER_ID
            assert confirmed.references["confirming_action_ref"] == turn.action_ref
            durable = (
                await conn.execute(
                    text(
                        "SELECT confirmed_by, confirming_turn_ref FROM "
                        "account_research_directive WHERE directive_id = :directive_id"
                    ),
                    {"directive_id": directive_id},
                )
            ).one()
            assert durable.confirmed_by == USER_ID
            assert durable.confirming_turn_ref == turn.action_ref

    run_async(scenario())


def test_a_confirmation_without_an_ambient_receipt_is_refused(tmp_path: Path) -> None:
    """The gate's floor, restated on this lane: no ambient identity, no confirmation."""

    from clue_api.trial.account_deep_fixture import seed_insight_health_account_deep_fixture

    async def scenario() -> None:
        async with rollback_conn() as conn:
            storage = FsStorage(tmp_path / "artifacts")
            await seed_insight_health_account_deep_fixture(
                conn,
                pages=_pages(),
                storage=storage,
            )
            cf = conn_session_factory(conn)
            registry = ToolRegistry()
            for tool in build_research_directive_tools(
                memory_write_factory=None,
                conn_factory=cf,
            ):
                registry.register(tool, make_default=tool.version == "2")

            with pytest.raises(PreconditionFailed) as refused:
                await invoke_tool(
                    registry,
                    "confirm_account_research_directive",
                    {"directive_id": str(uuid4()), "expected_sha256": "0" * 64},
                    ToolContext(
                        workspace_id=WORKSPACE_ID,
                        actor="human",
                        conn_factory=cf,
                        operation_id=new_operation_id(),
                    ),
                    idempotency_ttl_s=TTL,
                )
            assert refused.value.reason_codes == ("trusted_human_receipt_required",)

    run_async(scenario())

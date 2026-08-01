"""C8 Slice-0 evidence — characterizes pre-C8 behavior; tasks 1.1-1.5 flip these into fix guards.

Every assertion here **passes against today's code** and freezes a defect named in
``docs/specs/PC-C8-stage0-context-card.md`` §1 as executable evidence. Nothing in this module is a
guard yet: when Slice 1 lands the card compiler (task 1.1), the engine-side turn binding (1.2), the
constitution delta (1.3), the trial capability surface (1.4) and the inspection tools (1.5), each
test below is *inverted* into the assertion that the defect is gone. Deleting one instead of
flipping it silently drops the only executable record that the defect existed.

The five defects, and what happens to each:

* **L3 required bundle over budget** — the three required L3 artifacts (stage snapshot, readiness
  snapshot, budget envelope) blow the 48,000-byte ``l3_project`` budget
  (``stage0_trial.py:398-412``), so ``DeterministicAgentContextAssembler.assemble`` raises
  ``required l3_project context exceeds its hard layer budget`` (``context.py:578``) and the
  session bricks with HTTP 422. Reference numbers from the failing run
  ``trial-63553478967758a6`` (spec §1): stage 32,178 B + readiness 15,889 B + budget 140 B =
  48,207 B against a 48,000 B budget. Those figures are documentation, **not** assertions — the
  byte counts depend on id lengths and row content, so the tests assert the *relation* (over
  budget, duplicated, growing) and print the measured numbers. → 1.1/1.3 replace the two snapshots
  with one ≤24,000-byte ``Stage0ProjectCard``; this test flips to "the required bundle fits".
* **Readiness duplication** — the stage artifact embeds ``current_truth.readiness_decisions``
  (``stage0_trial.py:750``) and the readiness artifact serializes the identical list again
  (``:760``). → 1.1/1.3: one owner, asserted absent.
* **Linear required growth** — the ledger is re-serialized in full, twice, on every turn, so
  required L3 grows with conversation length regardless of message content. → 1.1: the card is
  hard-bounded, so growth flattens.
* **Turn authority round-trip** — the model-facing ``record_interview_answer`` schema requires the
  model to author the byte-identical ``answer`` plus the trusted ``onboarding_input_id`` and
  ``artifact_key`` (``stage0_tools.py:286``), while ``project_id`` on the same input is already
  engine-injected. → 1.2 moves the three engine-side; this test flips to "absent from the
  model-facing schema".
* **Identity injected twice** — the L1 context candidate body is the resolved profile's system
  prompt (``context.py:209-217``) *and* the runtime separately hands
  ``resolved_profile.prompt_body`` to ``create_deep_agent`` (``runtime.py:297``), which the
  tool-surface middleware then completes with the same resource map. Recorded here; **fixed in
  Slice 2**, not Slice 1.

Measured by this fixture at 22 statements / 20 readiness decisions (2026-08-01): stage 33,671 B +
readiness 16,942 B + budget 140 B = 50,753 B against the 48,000 B budget; the duplicated ledger is
16,832 B of that (~35% of the whole layer budget); required L3 grows ~2,324 B per material turn.
The same shape as the failing run, reached two turns later.

DB-backed tests reuse the ``tests/api`` conventions: a per-branch ``CLUE_DATABASE_URL``, one
rollback-only transaction per scenario, and ``pytest.skip`` when no database is reachable, so
``make check`` stays green without one. The api conftest's autouse hermetic-flag fixture keeps a
local ``.env`` from changing what these tests observe.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    AgentRole,
    AgentTurnRequest,
    ArtifactRef,
    AssembledAgentContext,
    ContextLayer,
    DeepAgentTurnRuntime,
)
from clue_agents.context import IdentityLayerSource
from clue_agents.contracts import AgentConstitution, DomainObjectRef
from clue_agents.registry import ResolvedAgentProfile
from clue_api.account_research_turn_wiring import DbCompiledContextCardReader
from clue_api.agent_platform_wiring import build_agent_context_assembler
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_runtime_wiring import GovernedAgentToolFactory
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.stage0_tools import RecordInterviewAnswerTool
from clue_api.stage0_trial import (
    CLIENT_KNOWLEDGE_FIELDS,
    Stage0Trial,
    Stage0TrialPaths,
    Stage0TrialState,
    _json_bytes,
    stage0_trial_context_policy,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import DEFAULT_STAGE0_POLICY
from clue_core import (
    AccountStatus,
    EntityId,
    ExecutionId,
    MemoryType,
    OnboardingInputId,
    OnboardingInputKind,
    ReadinessDecisionId,
    ReadinessGate,
)
from clue_db import db_lifespan
from clue_research.identity import insert_account_entity
from clue_research.stage0 import (
    StatementRoute,
    evaluate_readiness,
    record_statement,
    submit_onboarding_input,
)
from clue_spine import create_brand, create_product, create_project, create_workspace
from clue_storage import FsStorage
from tests.agents.test_contracts import context_manifest
from tests.agents.test_runtime import _CaptureModelInput, _Execution, _Models, _request
from tests.api.test_stage0_tool_guidance import _model_facing_parameters
from tests.db.conftest import _db_available, run_async

# The historical failing bundle (spec §1, trial-63553478967758a6). Reference only.
HISTORICAL_STAGE_BYTES = 32_178
HISTORICAL_READINESS_BYTES = 15_889
HISTORICAL_BUDGET_BYTES = 140
HISTORICAL_TOTAL_BYTES = 48_207
# The material-turn counts that produced it: ~20 volunteered statements, ~18 readiness decisions.
HISTORICAL_STATEMENTS = 20
HISTORICAL_DECISIONS = 18
# What this fixture seeds. The synthetic rows are slightly *smaller* than the failing run's (its
# ids, route keys, KB claims and metrics were longer), so the historical 20/18 measures ~46 KB
# here — a faithful shape, a couple of turns short of the cliff. Two more material turns cross it,
# which is itself the point: the overflow is a function of conversation length, not content.
REPRO_STATEMENTS = 22
REPRO_DECISIONS = 20

# One plausible interview answer per turn; the statement quote is a real span of it, exactly as
# ``record_interview_answer`` records one (offsets + sha into the captured artifact, no text).
_ANSWER = (
    "We sell an AI-native ABM platform to neurosurgery practices in the US that run their own "
    "imaging, and the campaign should open with the practice administrators rather than the "
    "surgeons because they own the scheduling pain."
)
_QUOTE_START = 33
_QUOTE_END = 76  # "neurosurgery practices in the US that run t"
_ROUTE_KEYS = (
    "campaign_goal_and_target_scope",
    "target_segment",
    "buying_committee_shape",
    "channel_preference",
)


@pytest.fixture
def stage0_db_available() -> bool:
    return _db_available()


def _state(slug: str) -> Stage0TrialState:
    session_id = uuid4()
    return Stage0TrialState(
        session_id=session_id,
        session_slug=slug,
        workspace_id=f"s0-{slug}-{session_id.hex[:8]}",
        brand_id=f"brand_{session_id.hex[:8]}",
        product_id=f"product_{session_id.hex[:8]}",
        project_id=f"project_{session_id.hex[:8]}",
        client_entity_id=uuid4(),
        client_kb_version=1,
        company_name="Aura AI",
        website="https://aura.invalid",
        product_name="Aura ABM",
        project_name="Aura Stage 0 trial",
        thread_id=f"stage0-trial-{session_id.hex}",
        created_at=datetime.now(UTC),
    )


class _NoMemory:
    """L4 with nothing to say; the defect under test lives entirely in L3."""

    async def assemble(self, request: object) -> None:
        del request
        return None


async def _seed_material_turns(
    conn: AsyncConnection,
    artifacts: DurableAgentArtifactStore,
    *,
    state: Stage0TrialState,
    statements: int,
    decisions: int,
    first_turn: int = 0,
) -> None:
    """Capture ``statements`` material turns and evaluate readiness on ``decisions`` of them.

    Mirrors what one Stage-0 trial turn durably writes (``stage0_trial.py:697-716`` captures the
    input, ``record_interview_answer`` routes the statement, ``_recompute_readiness`` at ``:927``
    appends the decision) without a model call.
    """

    for index in range(first_turn, first_turn + statements):
        ref = await artifacts.persist_body(
            workspace_id=state.workspace_id,
            data=f"{_ANSWER} (turn {index})".encode(),
            media_type="text/plain",
        )
        captured = await submit_onboarding_input(
            conn,
            workspace_id=state.workspace_id,
            brand_id=state.brand_id,
            product_id=state.product_id,
            project_id=state.project_id,
            client_entity_id=EntityId(state.client_entity_id),
            kind=OnboardingInputKind.USER_TURN,
            artifact_key=ref.artifact_key,
            content_sha256=ref.sha256,
            actor="human",
            onboarding_input_id=OnboardingInputId(
                uuid5(NAMESPACE_URL, f"c8-slice0:{state.session_id}:input:{index}")
            ),
        )
        await record_statement(
            conn,
            onboarding_input_id=captured.onboarding_input_id,
            workspace_id=state.workspace_id,
            brand_id=state.brand_id,
            product_id=state.product_id,
            project_id=state.project_id,
            client_entity_id=EntityId(state.client_entity_id),
            entity_id=EntityId(state.client_entity_id),
            route_kind=StatementRoute.PROJECT_STATE,
            route_key=_ROUTE_KEYS[index % len(_ROUTE_KEYS)],
            quote=_ANSWER[_QUOTE_START:_QUOTE_END],
            quote_start=_QUOTE_START,
            quote_end=_QUOTE_END,
            created_by_actor="agent",
        )
        if index >= first_turn + decisions:
            continue
        await evaluate_readiness(
            conn,
            workspace_id=state.workspace_id,
            brand_id=state.brand_id,
            product_id=state.product_id,
            project_id=state.project_id,
            client_entity_id=EntityId(state.client_entity_id),
            client_kb_version=state.client_kb_version,
            gate=ReadinessGate.ICP_SYNTHESIS,
            spec=DEFAULT_STAGE0_POLICY.readiness,
            metrics={
                "coverage_ratio": 0.0,
                "verified_claims": 0,
                "open_policy_blocks": 0,
                "available_field_keys": [],
                "project_state_statements": index + 1,
                "routed_statements_this_turn": 1,
                "material_statements_this_turn": 1,
            },
            created_by_actor="system",
            readiness_decision_id=ReadinessDecisionId(
                uuid5(NAMESPACE_URL, f"c8-slice0:{state.session_id}:readiness:{index}")
            ),
        )


async def _required_l3_artifacts(
    trial: Stage0Trial,
    current: dict[str, object],
) -> tuple[ArtifactRef, ArtifactRef, ArtifactRef]:
    """Compose the three **required** L3 artifacts exactly as one live turn does.

    Payload shapes copied verbatim from ``stage0_trial.py:729`` (stage snapshot), ``:756``
    (readiness snapshot) and ``:766`` (budget envelope) — the three refs ``ProjectLayerSource``
    marks ``required=True`` (``context.py:304-319``). ``run_turn`` cannot be called here because it
    needs a live model call, so the composition (not the whole turn) is what is reproduced.
    """

    stage_ref = await trial._artifact(
        "application/vnd.clue.agent-stage-snapshot+json",
        {
            "schema_version": "1",
            "surface": "stage0_conversation_trial",
            "acquisition_mode": "manual_conversation_only",
            "external_research_enabled": False,
            "specialist_delegation_enabled": False,
            "instruction": (
                "Use only supplied durable truth and the current user message. Do not call "
                "start_recon or imply that website, Exa, scraping, or campaign files were "
                "read. The current user turn is already a captured onboarding input; use its "
                "provided onboarding_input_id and do not call submit_onboarding_input again. "
                "Treat the user's target-ICP and campaign-strategy choices as project_state, "
                "not as an invented claim field. Claims about the client may use only the "
                "registered_client_claim_fields below and must include the supplied client "
                "entity id with entity_type=account. The human triggers inspectable ICP "
                "synthesis with /synthesize-icp; do not call synthesize_icps in this trial "
                "because its v1 tool result exposes only a count."
            ),
            "registered_client_claim_fields": list(CLIENT_KNOWLEDGE_FIELDS),
            "current_truth": current,
        },
    )
    project = current["project"]
    assert isinstance(project, dict)
    readiness_ref = await trial._artifact(
        "application/vnd.clue.agent-readiness-snapshot+json",
        {
            "schema_version": "1",
            "readiness_decisions": current["readiness_decisions"],
            "confirmed_icps": current["icps"],
            "product_confirmed": project.get("product_id") == trial.state.product_id,
        },
    )
    budget_ref = await trial._artifact(
        "application/vnd.clue.agent-budget-envelope+json",
        {
            "schema_version": "1",
            "limit_millicents": 1_000_000,
            "external_research_budget_cents": "0",
            "scope": "conversation and Stage-0 domain writes only",
        },
    )
    return stage_ref, readiness_ref, budget_ref


def _turn_request(
    *,
    state: Stage0TrialState,
    resolved: ResolvedAgentProfile,
    stage_ref: ArtifactRef,
    readiness_ref: ArtifactRef,
    budget_ref: ArtifactRef,
    manifest_ref: ArtifactRef,
    user_ref: ArtifactRef,
) -> AgentTurnRequest:
    """The same constitution shape one live turn builds (``stage0_trial.py:818-841``)."""

    focus_ref = DomainObjectRef(
        workspace_id=state.workspace_id,
        object_type="client_account",
        object_id=str(state.client_entity_id),
        version=state.client_kb_version,
    )
    return AgentTurnRequest(
        turn_id=uuid5(state.session_id, "c8-slice0-turn"),
        thread_id=state.thread_id,
        constitution=AgentConstitution(
            workspace_id=state.workspace_id,
            project_id=state.project_id,
            execution_id=ExecutionId(uuid5(state.session_id, "c8-slice0-execution")),
            actor_id="stage0-trial-user",
            role=AgentRole.HEAD_OF_ABM,
            brand_id=state.brand_id,
            product_id=state.product_id,
            workspace_root_id="c8-slice0-workspace-root",
            stage_snapshot_ref=stage_ref,
            readiness_snapshot_ref=readiness_ref,
            budget_envelope_ref=budget_ref,
            profile_ref=resolved.profile_ref,
            resource_manifest_ref=manifest_ref,
            resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
            focus_refs=(focus_ref,),
        ),
        user_message_artifact_ref=user_ref,
        focus_refs=(focus_ref,),
        requested_at=datetime.now(UTC),
    )


async def _scenario(
    tmp_path: Path,
    *,
    slug: str,
    body: Any,
) -> None:
    """One rollback-only transaction holding a fully seeded Stage-0 project."""

    state = _state(slug)
    async with db_lifespan() as engine:
        conn = await engine.connect()
        outer = await conn.begin()

        @asynccontextmanager
        async def connection_factory() -> AsyncIterator[AsyncConnection]:
            yield conn

        try:
            await create_workspace(
                conn, workspace_id=state.workspace_id, name="C8 slice-0 evidence"
            )
            brand = await create_brand(
                conn, workspace_id=state.workspace_id, name="Aura", brand_id=state.brand_id
            )
            product = await create_product(
                conn,
                workspace_id=state.workspace_id,
                brand_id=brand.brand_id,
                name="Aura ABM",
                product_id=state.product_id,
            )
            await create_project(
                conn,
                workspace_id=state.workspace_id,
                brand_id=brand.brand_id,
                product_id=product.product_id,
                name="Aura Stage 0 trial",
                project_id=state.project_id,
            )
            client = await insert_account_entity(
                conn,
                canonical_name="Aura AI",
                primary_domain="aura.invalid",
                workspace_id=state.workspace_id,
                status=AccountStatus.ACTIVE,
            )
            seeded = state.model_copy(update={"client_entity_id": client})
            artifacts = DurableAgentArtifactStore(
                storage=FsStorage(tmp_path / "artifacts"),
                conn_factory=connection_factory,
            )
            trial = object.__new__(Stage0Trial)
            trial.state = seeded
            trial.paths = Stage0TrialPaths.for_session(tmp_path, seeded.session_slug)
            trial._components = SimpleNamespace(artifacts=artifacts)  # type: ignore[assignment]
            trial._conn_factory = connection_factory  # type: ignore[assignment]
            await body(trial, conn, artifacts, connection_factory)
        finally:
            await outer.rollback()
            await conn.close()


def test_required_l3_bundle_exceeds_its_hard_budget_at_a_normal_interview_length(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """The 422 that bricked ``trial-63553478967758a6``, reproduced from durable state.

    Historical bundle (spec §1): stage 32,178 B + readiness 15,889 B + budget 140 B = 48,207 B
    against the 48,000 B ``l3_project`` budget. Asserted here as a *relation* — the required bundle
    exceeds the budget and the real assembler refuses the turn — because the exact byte counts move
    with id lengths and row content.

    After 1.1/1.3 this flips: one bounded ``project_card_ref`` (≤24,000 B) plus the budget
    envelope, and ``assemble`` returns a context instead of raising.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def body(
        trial: Stage0Trial,
        conn: AsyncConnection,
        artifacts: DurableAgentArtifactStore,
        connection_factory: Any,
    ) -> None:
        await _seed_material_turns(
            conn,
            artifacts,
            state=trial.state,
            statements=REPRO_STATEMENTS,
            decisions=REPRO_DECISIONS,
        )
        current = await trial.snapshot(
            current_turn={
                "onboarding_input_id": str(uuid4()),
                "artifact_key": f"{trial.state.workspace_id}/{'0' * 64}",
                "sha256": "0" * 64,
                "media_type": "text/plain",
                "byte_count": len(_ANSWER),
                "answer_is_exact_artifact_body": True,
            }
        )
        stage_ref, readiness_ref, budget_ref = await _required_l3_artifacts(trial, current)

        policy = stage0_trial_context_policy()
        budget = policy.budget_for(ContextLayer.L3_PROJECT)
        required_bytes = stage_ref.byte_count + readiness_ref.byte_count + budget_ref.byte_count
        assert budget == 48_000
        assert required_bytes > budget, (
            "expected the required L3 bundle to exceed its budget "
            f"(stage={stage_ref.byte_count} readiness={readiness_ref.byte_count} "
            f"budget={budget_ref.byte_count} total={required_bytes} limit={budget})"
        )

        registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
        resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
        manifest_ref = await trial._artifact(
            "application/vnd.clue.agent-resource-manifest+json",
            resolved.resource_manifest.model_dump(mode="json"),
        )
        user_ref = await artifacts.persist_body(
            workspace_id=trial.state.workspace_id,
            data=_ANSWER.encode(),
            media_type="text/plain",
        )
        assembler = build_agent_context_assembler(
            resolved_profile=resolved,
            artifacts=artifacts,
            cards=DbCompiledContextCardReader(conn_factory=connection_factory),
            memory=cast(Any, _NoMemory()),
            memory_recipe="recipe0-stage0@3",
            requested_memory_types=(MemoryType.PREFERENCE, MemoryType.BEHAVIORAL_LEARNING),
            policy=policy,
            conn_factory=connection_factory,
        )
        request = _turn_request(
            state=trial.state,
            resolved=resolved,
            stage_ref=stage_ref,
            readiness_ref=readiness_ref,
            budget_ref=budget_ref,
            manifest_ref=manifest_ref,
            user_ref=user_ref,
        )

        with pytest.raises(
            ValueError, match="required l3_project context exceeds its hard layer budget"
        ):
            await assembler.assemble(request=request, profile=resolved.profile, history=())

    run_async(_scenario(tmp_path, slug=f"over-budget-{uuid4().hex[:8]}", body=body))


def test_the_readiness_ledger_is_serialized_twice_into_required_l3(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """~a third of the L3 budget is the same list twice, byte for byte.

    ``stage0_trial.py:750`` embeds ``current_truth.readiness_decisions`` in the stage artifact and
    ``:760`` serializes the identical list as the readiness artifact's own payload. After 1.1/1.3
    the ledger has exactly one owner (the card's ``readiness.latest_by_gate``) and this flips to
    asserting the duplicate is gone.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    async def body(
        trial: Stage0Trial,
        conn: AsyncConnection,
        artifacts: DurableAgentArtifactStore,
        connection_factory: Any,
    ) -> None:
        await _seed_material_turns(
            conn,
            artifacts,
            state=trial.state,
            statements=REPRO_STATEMENTS,
            decisions=REPRO_DECISIONS,
        )
        current = await trial.snapshot()
        stage_ref, readiness_ref, _ = await _required_l3_artifacts(trial, current)

        ledger = current["readiness_decisions"]
        assert isinstance(ledger, list)
        assert len(ledger) == REPRO_DECISIONS
        serialized = _json_bytes(ledger)

        stage_body = await artifacts.read(stage_ref)
        readiness_body = await artifacts.read(readiness_ref)
        # Not "equal objects" — the same bytes, in both artifacts the model is handed.
        assert serialized in stage_body
        assert serialized in readiness_body
        assert json.loads(stage_body)["current_truth"]["readiness_decisions"] == ledger
        assert json.loads(readiness_body)["readiness_decisions"] == ledger
        # And it is not a rounding error: the duplicate alone is a large share of the budget.
        assert len(serialized) > 8_000

    run_async(_scenario(tmp_path, slug=f"dup-ledger-{uuid4().hex[:8]}", body=body))


def test_required_l3_bytes_grow_with_every_material_turn(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """Required L3 grows ~linearly with the readiness ledger, independent of message content.

    Spec §1 measured ~930 B per decision row, re-serialized twice, so ~1.9 KB of required L3 per
    material turn. Asserted as a per-row *floor* (900 B, one copy) rather than an exact rate.
    After 1.1 the card is hard-bounded (≤24,000 B at any ledger length), so this flips into the
    bounded-growth assertion of AC-1.
    """

    if not stage0_db_available:
        pytest.skip("requires a migrated per-branch Postgres database")

    added = 8

    async def body(
        trial: Stage0Trial,
        conn: AsyncConnection,
        artifacts: DurableAgentArtifactStore,
        connection_factory: Any,
    ) -> None:
        async def required_bytes() -> int:
            current = await trial.snapshot()
            refs = await _required_l3_artifacts(trial, current)
            return sum(ref.byte_count for ref in refs)

        await _seed_material_turns(
            conn,
            artifacts,
            state=trial.state,
            statements=REPRO_DECISIONS,
            decisions=REPRO_DECISIONS,
        )
        before = await required_bytes()
        await _seed_material_turns(
            conn,
            artifacts,
            state=trial.state,
            statements=added,
            decisions=added,
            first_turn=REPRO_DECISIONS,
        )
        after = await required_bytes()

        growth = after - before
        assert growth > 0
        assert growth / added >= 900, (
            f"expected >=900 B of required L3 per material turn, measured {growth / added:.0f} B "
            f"({before} -> {after} over {added} turns)"
        )

    run_async(_scenario(tmp_path, slug=f"growth-{uuid4().hex[:8]}", body=body))


def test_record_interview_answer_still_makes_the_model_author_the_answer_and_trusted_ids() -> None:
    """The model round-trips the captured bytes and two trusted identifiers it should never author.

    ``project_id`` on the same input is already engine-injected — ``_with_trusted_runtime`` strips
    every ``MODEL_FORBIDDEN_AUTHORITY_KEYS`` name from the model-facing schema — which is the seam
    task 1.2 extends to ``answer``/``onboarding_input_id``/``artifact_key``: the engine loads the
    captured body from the artifact store and applies the model's offsets against those exact
    bytes. When that lands, this flips to asserting the three are absent from the model-facing
    schema and that a forged id is refused at the execution seam (spec AC-6).
    """

    parameters = _model_facing_parameters(RecordInterviewAnswerTool)
    properties = parameters["properties"]
    required = set(parameters["required"])

    # Authority the model must author today, and must not after 1.2.
    assert {"answer", "onboarding_input_id", "artifact_key"} <= required
    assert "byte-identical" in properties["answer"]["description"].casefold()
    # The model authors only offsets into that body; the body itself is the round-trip.
    statement = properties["statements"]["items"]["properties"]
    assert {"quote_start", "quote_end"} <= set(statement)
    # The seam 1.2 extends already exists — and already covers project_id on this same input.
    assert "project_id" in RecordInterviewAnswerTool.input_model.model_fields
    assert "project_id" not in properties


def test_the_identity_prompt_is_injected_into_every_model_call_twice() -> None:
    """L1 carries the resolved system prompt and the runtime hands it to ``create_deep_agent`` too.

    ``IdentityLayerSource`` (``context.py:209-217``) emits the resolved profile's ``system_prompt``
    as the required L1 candidate, and ``DeepAgentTurnRuntime.run`` (``runtime.py:297``) separately
    passes ``resolved_profile.prompt_body`` as the deepagent's own system prompt, which
    ``ExactAgentToolSurfaceMiddleware`` then completes with the same generated resource map. The
    model therefore receives the identical prompt twice on every call — verified here against the
    real runtime's captured model input, not by reading source.

    Recorded, not fixed, by Slice 1: identity single-injection is **Slice 2**.
    """

    request, resolved = _request()
    identity = run_async(
        IdentityLayerSource(resolved).load(  # type: ignore[arg-type]
            request=request,
            profile=resolved.profile,
            history=(),
        )
    )
    assert len(identity) == 1
    candidate = identity[0]
    assert candidate.required is True
    assert candidate.body == resolved.system_prompt
    assert resolved.prompt_body.rstrip() in candidate.body

    capture = _CaptureModelInput()
    execution = _Execution()
    runtime = DeepAgentTurnRuntime(
        models=_Models(AIMessage(content="A polished but uncommitted answer.")),
        execution=execution,
        max_runtime_s=5,
    )
    tools = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, object()),
        artifacts=cast(Any, object()),
    ).build()
    context = AssembledAgentContext(
        manifest=context_manifest(),
        messages=(
            SystemMessage(content=candidate.body),  # what the assembler emits for L1
            HumanMessage(content="Where should this campaign start?"),
        ),
    )
    run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,
            context=context,
            backend=None,
            governed_tools=tools,
            callbacks=(capture,),
        )
    )

    sent = [str(getattr(message, "content", "")) for message in capture.messages[0]]
    copies = [body for body in sent if resolved.prompt_body.rstrip() in body]
    assert len(copies) == 2, "the identity prompt should reach the model exactly twice today"
    # One copy is the L1 context message verbatim; the other is the deepagent's own system prompt,
    # which is ``prompt_body`` plus the framework preamble plus the *same* generated resource map
    # the middleware appends — so the resource map is duplicated as well.
    assert resolved.system_prompt in copies
    other = next(body for body in copies if body != resolved.system_prompt)
    assert other.rstrip().endswith(resolved.generated_resource_map)
    assert sum(body.count(resolved.generated_resource_map) for body in sent) == 2

"""C8 Slice-0 evidence — the five §1 defects, each now a guard of its own fix.

Every test here started as a *characterization* test that passed against pre-C8 code and froze a
defect named in ``docs/specs/PC-C8-stage0-context-card.md`` §1. As each slice landed, the test was
**flipped** rather than deleted: the fixture and the durable state stay identical, and only the
assertion turns around. That is what keeps an executable record that the defect was real, and what
makes a regression fail here rather than in a live session.

The five defects and where each stands:

* **L3 required bundle over budget — FIXED (1.1/1.3).** The three required L3 artifacts (stage
  snapshot, readiness snapshot, budget envelope) blew the 48,000-byte ``l3_project`` budget, so
  ``DeterministicAgentContextAssembler.assemble`` raised ``required l3_project context exceeds its
  hard layer budget`` and the session bricked with HTTP 422. Reference numbers from the failing run
  ``trial-63553478967758a6`` (spec §1): stage 32,178 B + readiness 15,889 B + budget 140 B =
  48,207 B; this fixture measured ~60,000 B at 26/24. Required L3 is now the bounded project card
  plus the budget envelope, and the same project assembles. (Since the founder's ruling of
  2026-09-14 no layer budget can raise at all — budgets are tracked, never enforced — so the
  assertion below is no longer a guard against a live 422. It is kept as what it always measured:
  that the bounded card is small, which is why it is worth having whether or not it is policed.)
* **Readiness duplication — FIXED (1.1/1.3).** The stage artifact embedded
  ``current_truth.readiness_decisions`` and the readiness artifact serialized the identical list
  again. The card carries the latest authoritative decision per gate plus a ledger *length*.
* **Linear required growth — FIXED (1.1/1.3).** The ledger was re-serialized in full, twice, every
  turn, so required L3 grew with conversation length regardless of content. Ledger growth now
  moves the bundle by the digits of one integer.
* **Turn authority round-trip — FIXED (1.2/1.3).** The model-facing ``record_interview_answer``
  schema used to require the model to author the byte-identical ``answer`` plus the trusted
  ``onboarding_input_id``/``artifact_key``, and to copy back ``brand_id``/``client_entity_id``,
  while only ``project_id`` was engine-injected. All six are now served from trusted sources — the
  turn's capture record (1.2) and the constitution (1.3). The engine-side half is covered by
  ``tests/api/test_c8_turn_binding.py``.
* **Identity injected twice** — the L1 context candidate body is the resolved profile's system
  prompt (``context.py:209-217``) *and* the runtime separately hands
  ``resolved_profile.prompt_body`` to ``create_deep_agent`` (``runtime.py:297``), which the
  tool-surface middleware then completes with the same resource map. Still **recorded, not
  fixed**: identity single-injection is Slice 2.

Byte figures live in docstrings as reference; the assertions are relational (fits / bounded /
unique / flat), never equalities, because the counts move with id lengths and row content.

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
from sqlalchemy import text
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
from clue_agents.contracts import (
    MODEL_FORBIDDEN_AUTHORITY_KEYS,
    AgentConstitution,
    DomainObjectRef,
)
from clue_agents.registry import ResolvedAgentProfile
from clue_api.account_research_turn_wiring import DbCompiledContextCardReader
from clue_api.agent_platform_wiring import build_agent_context_assembler
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_runtime_wiring import GovernedAgentToolFactory
from clue_api.agent_turn_wiring import DbAgentTurnJournal, DurableAgentArtifactStore
from clue_api.stage0_tools import RecordInterviewAnswerTool
from clue_api.stage0_trial import (
    Stage0Trial,
    Stage0TrialPaths,
    Stage0TrialState,
    _json_bytes,
    stage0_trial_context_policy,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.turn_binding import trusted_turn_fields
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
from clue_projections import (
    STAGE0_CARD_POLICY_V1,
    STAGE0_PROJECT_CARD_MEDIA_TYPE,
)
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
# here — a faithful shape, a few turns short of the cliff. More material turns cross it, which is
# itself the point: the overflow is a function of conversation length, not content. Sized for
# headroom rather than the exact cliff: 22/20 clears the budget by well under one material turn,
# so ordinary content drift could flip the over-budget test red for the wrong reason. At 26/24 the
# bundle measures ~60,000 B against the 48,000 B budget — ~5 turns of margin.
REPRO_STATEMENTS = 26
REPRO_DECISIONS = 24

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


async def _seed_ledger_only(
    conn: AsyncConnection,
    *,
    state: Stage0TrialState,
    decisions: int,
    first_turn: int,
) -> None:
    """Append readiness decisions with no new statements — pure ledger growth."""

    for index in range(first_turn, first_turn + decisions):
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
                "routed_statements_this_turn": 0,
                "material_statements_this_turn": 0,
            },
            created_by_actor="system",
            readiness_decision_id=ReadinessDecisionId(
                uuid5(NAMESPACE_URL, f"c8-slice0:{state.session_id}:ledger-only:{index}")
            ),
        )


async def _required_l3_artifacts(
    trial: Stage0Trial,
) -> tuple[ArtifactRef, ArtifactRef]:
    """Compose the two **required** L3 artifacts exactly as one live turn does.

    Post-1.3 there is no payload to copy: the card is compiled by the production code path
    (``Stage0Trial._project_card_ref``), and only the budget envelope — untouched by the delta,
    because it is spend authority rather than project state — is still an inline literal
    (``stage0_trial.py``'s budget block). That collapse is itself the fix: the retired helper had
    to duplicate two large snapshot payloads to say what one turn puts in front of the model.

    ``run_turn`` still cannot be called here (it needs a live model call), so the composition, not
    the whole turn, is what is reproduced.
    """

    card_ref = await trial._project_card_ref()
    budget_ref = await trial._artifact(
        "application/vnd.clue.agent-budget-envelope+json",
        {
            "schema_version": "1",
            "limit_millicents": 1_000_000,
            "external_research_budget_cents": "0",
            "scope": "conversation and Stage-0 domain writes only",
        },
    )
    return card_ref, budget_ref


def _turn_request(
    *,
    state: Stage0TrialState,
    resolved: ResolvedAgentProfile,
    card_ref: ArtifactRef,
    budget_ref: ArtifactRef,
    manifest_ref: ArtifactRef,
    user_ref: ArtifactRef,
) -> AgentTurnRequest:
    """The same constitution shape one live turn builds (``stage0_trial.py``'s ``run_turn``)."""

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
            client_entity_id=str(state.client_entity_id),
            workspace_root_id="c8-slice0-workspace-root",
            project_card_ref=card_ref,
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
            # The one durable row these fixtures need beyond Stage 0: a turn's context receipt is
            # journaled against its execution, so an assembling test has something to hang on.
            await conn.execute(
                text(
                    "INSERT INTO execution (id, workspace_id, project_id, started_by, "
                    "parameter_manifest_hash, pin_manifest_hash) "
                    "VALUES (:id, :workspace, :project, 'human', :hash, :hash)"
                ),
                {
                    "id": uuid5(seeded.session_id, "c8-slice0-execution"),
                    "workspace": seeded.workspace_id,
                    "project": seeded.project_id,
                    "hash": "0" * 64,
                },
            )
            await body(trial, conn, artifacts, connection_factory)
        finally:
            await outer.rollback()
            await conn.close()


def test_the_required_l3_bundle_now_fits_its_hard_budget_at_the_same_interview_length(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """FLIPPED (1.1/1.3). The project that used to 422 now assembles, from the same durable state.

    Historical bundle (spec §1): stage 32,178 B + readiness 15,889 B + budget 140 B = 48,207 B
    against the 48,000 B ``l3_project`` budget; this fixture measured ~60,000 B at 26 statements /
    24 decisions. Required L3 is now exactly two candidates — the bounded project card and the
    budget envelope — so the same seeded project assembles instead of raising, and the card obeys
    the ``Stage0CardPolicy`` 24,000-byte ceiling with the whole 48,000 B layer budget to spare.

    Assertions stay relational (fits / bounded / exactly two required candidates); the byte counts
    move with id lengths and row content and are reported, not pinned.
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
        card_ref, budget_ref = await _required_l3_artifacts(trial)

        policy = stage0_trial_context_policy()
        budget = policy.budget_for(ContextLayer.L3_PROJECT)
        required_bytes = card_ref.byte_count + budget_ref.byte_count
        assert budget == 48_000
        assert card_ref.media_type == STAGE0_PROJECT_CARD_MEDIA_TYPE
        assert card_ref.byte_count <= STAGE0_CARD_POLICY_V1.max_card_bytes
        assert required_bytes < budget, (
            "expected the required L3 bundle to fit the size its budget reports "
            f"(card={card_ref.byte_count} budget_envelope={budget_ref.byte_count} "
            f"total={required_bytes} limit={budget})"
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
            card_ref=card_ref,
            budget_ref=budget_ref,
            manifest_ref=manifest_ref,
            user_ref=user_ref,
        )

        # The assembler journals a context receipt against the live turn, so the turn has to
        # exist — the same order a real run uses (``turns.create`` then ``contexts.assemble``).
        await DbAgentTurnJournal(conn_factory=connection_factory).create(
            request=request, profile=resolved.profile
        )
        context = await assembler.assemble(request=request, profile=resolved.profile, history=())
        layer = next(
            item for item in context.manifest.layers if item.layer is ContextLayer.L3_PROJECT
        )
        # Exactly two: the card and the budget envelope. The compiled ``project`` context card
        # ``ProjectLayerSource`` also used to read is gone — the card subsumes it.
        assert [item.artifact_key for item in layer.source_refs] == [
            budget_ref.artifact_key,  # candidates are ordered by stable key: budget, project_card
            card_ref.artifact_key,
        ]
        assert layer.excluded_refs == ()
        assert layer.token_count < budget

    run_async(_scenario(tmp_path, slug=f"fits-{uuid4().hex[:8]}", body=body))


def test_the_readiness_ledger_is_serialized_exactly_once_into_required_l3(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """FLIPPED (1.1/1.3). One owner: no readiness row appears twice in the required L3 bytes.

    The retired pair embedded ``current_truth.readiness_decisions`` in the stage artifact and
    serialized the identical list again as the readiness artifact's whole payload — ~20 KB of the
    48 KB layer budget spent saying the same thing twice, every row, twice over. The card carries
    the *latest authoritative decision per gate* instead, so this asserts both halves of the fix:
    only the shown decisions are named at all (the rest of the ledger is a count, with the rows
    behind the bounded inspection tool), and a named decision appears only as its own 36-byte id —
    once on its gate and once in the compile-lineage receipt, never as a second copy of the row.
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
        card_ref, budget_ref = await _required_l3_artifacts(trial)
        required = (await artifacts.read(card_ref)) + (await artifacts.read(budget_ref))

        ledger = (await trial.snapshot())["readiness_decisions"]
        assert isinstance(ledger, list)
        assert len(ledger) == REPRO_DECISIONS
        card = json.loads(await artifacts.read(card_ref))
        shown = {
            entry["decision_id"]
            for entry in card["readiness"]["latest_by_gate"]
            if entry.get("decision_id") is not None
        }
        # One decision per gate, not the ledger; the rest is a count plus a cursor.
        assert 0 < len(shown) < REPRO_DECISIONS
        assert card["readiness"]["ledger_length"] == REPRO_DECISIONS
        assert set(card["compiled_from"]["readiness_decision_ids"]) == shown

        for row in ledger:
            assert isinstance(row, dict)
            decision_id = str(row["id"])
            mentions = required.count(decision_id.encode())
            if decision_id in shown:
                # Its gate entry and the compile-lineage receipt — two ids, not two rows.
                assert mentions == 2, f"decision {decision_id} appears {mentions} times"
            else:
                assert mentions == 0, f"unshown decision {decision_id} leaked into required L3"

        # The whole serialized ledger used to be ~20 KB of required L3, twice; none of it is there
        # now — and what replaced it is smaller than one copy of it.
        serialized = _json_bytes(ledger)
        assert len(serialized) > 8_000
        assert serialized not in required
        assert card_ref.byte_count < len(serialized)

    run_async(_scenario(tmp_path, slug=f"dup-ledger-{uuid4().hex[:8]}", body=body))


def test_required_l3_bytes_stop_growing_with_the_readiness_ledger(
    tmp_path: Path,
    stage0_db_available: bool,
) -> None:
    """FLIPPED (1.1/1.3). Ledger length no longer buys bytes, and the card stays hard-bounded.

    Spec §1 measured ~930 B per decision row re-serialized twice — ~1.9 KB of required L3 per
    material turn, which is what walked the trial into the 422. Two halves here:

    * **flat**: eight more readiness decisions and *nothing else* move the required bundle by only
      the digits of ``ledger_length`` — the card shows the latest decision per gate, so the ledger
      is a number, not a payload;
    * **bounded**: eight further turns that each also route a statement do add content (a card is
      supposed to describe the project), but far below the retired 900 B/turn floor, and the card
      remains under its 24,000 B policy ceiling.
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
        async def required_bytes() -> tuple[int, int]:
            card_ref, budget_ref = await _required_l3_artifacts(trial)
            return card_ref.byte_count + budget_ref.byte_count, card_ref.byte_count

        await _seed_material_turns(
            conn,
            artifacts,
            state=trial.state,
            statements=REPRO_STATEMENTS,
            decisions=REPRO_DECISIONS,
        )
        before, _ = await required_bytes()

        # Ledger-only growth: readiness decisions with no new statements.
        await _seed_ledger_only(
            conn, state=trial.state, decisions=added, first_turn=REPRO_STATEMENTS
        )
        ledger_only, _ = await required_bytes()
        assert abs(ledger_only - before) <= 8, (
            f"{added} extra readiness decisions moved required L3 by "
            f"{ledger_only - before} B ({before} -> {ledger_only}); it should move by at most the "
            "digits of ledger_length"
        )

        # Material growth: statements are content, so the card does grow — but bounded, and an
        # order of magnitude below the rate that used to blow the budget.
        await _seed_material_turns(
            conn,
            artifacts,
            state=trial.state,
            statements=added,
            decisions=added,
            first_turn=REPRO_STATEMENTS + added,
        )
        after, card_bytes = await required_bytes()
        growth = (after - ledger_only) / added
        assert growth < 900, (
            f"expected far under the retired 900 B/turn floor, measured {growth:.0f} B/turn "
            f"({ledger_only} -> {after} over {added} turns)"
        )
        assert card_bytes <= STAGE0_CARD_POLICY_V1.max_card_bytes

    run_async(_scenario(tmp_path, slug=f"growth-{uuid4().hex[:8]}", body=body))


def test_record_interview_answer_no_longer_lets_the_model_author_the_answer_or_trusted_ids() -> (
    None
):
    """Flipped by tasks 1.2 and 1.3: neither the turn nor the project scope is the model's to name.

    Pre-C8 the model round-tripped the byte-identical ``answer``, authored
    ``onboarding_input_id``/``artifact_key``, and copied ``brand_id``/``client_entity_id`` back out
    of its own context — while ``project_id`` on the same input was already engine-injected. Both
    halves now come from a trusted source through the *same* two-part seam
    (``_with_trusted_runtime`` strips, the execution seam injects), differing only in where the
    value lives: the turn's capture record (1.2) or the constitution (1.3).

    What the model still authors is the classification: route kind/key, the verbatim quote it
    means (PC-C8 §6c-a took the offsets too), correction lineage, proposed typed values (spec AC-6,
    first clause).
    """

    parameters = _model_facing_parameters(RecordInterviewAnswerTool)
    properties = parameters["properties"]
    required = set(parameters["required"])
    turn_authority = {"answer", "onboarding_input_id", "artifact_key"}
    project_authority = {"project_id", "brand_id", "client_entity_id"}

    # Gone from the model surface entirely — not merely optional.
    assert turn_authority.isdisjoint(properties)
    assert turn_authority.isdisjoint(required)
    assert project_authority.isdisjoint(properties)
    # Still declared on the tool's own input model: the C4 recipe path supplies them directly, and
    # the execution seam serves them there from the binding and the constitution.
    assert turn_authority <= set(RecordInterviewAnswerTool.input_model.model_fields)
    assert project_authority <= set(RecordInterviewAnswerTool.input_model.model_fields)
    assert turn_authority == set(trusted_turn_fields(RecordInterviewAnswerTool.input_model))
    assert project_authority <= MODEL_FORBIDDEN_AUTHORITY_KEYS
    # The model authors the span it means, in the user's own words; the engine locates it in the
    # body it loaded and computes the offsets (§6c-a). No offset field survives on this surface.
    statement = properties["statements"]["items"]["properties"]
    assert {"quote", "occurrence"} <= set(statement)
    assert {"quote_start", "quote_end"}.isdisjoint(statement)
    assert "captured user message" in statement["quote"]["description"].casefold()
    # What survives is the classification surface plus the one scope the model genuinely chooses:
    # the *candidate* product, which in Stage 0 may differ from the confirmed one.
    assert set(properties) == {"product_id", "statements"}


def test_the_identity_prompt_is_injected_into_every_model_call_twice() -> None:
    """L1 carries the resolved system prompt and the runtime hands it to ``create_deep_agent`` too.

    ``IdentityLayerSource`` (``context.py:209-217``) emits the resolved profile's ``system_prompt``
    as the required L1 candidate, and ``DeepAgentTurnRuntime.run`` (``runtime.py:297``) separately
    passes ``resolved_profile.prompt_body`` as the deepagent's own system prompt, which
    ``ExactAgentToolSurfaceMiddleware`` then completes with the same generated resource map. The
    identity prompt body and the generated resource map each reach the model twice (the two system
    messages are not byte-identical — the deepagent copy adds the framework preamble) — verified
    here against the real runtime's captured model input, not by reading source.

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

"""Turn-level routing honesty: prose may not claim a durable write the turn never made.

The live defect (`_memory/2026-07-31-stage0-structured-output-failure-chain.md`): across seven
turns the Stage-0 agent told the human "this is now captured as project state" while the database
held zero interview statements, zero plans, and zero tool results — and `readiness_decisions` stayed
empty for the whole trial. These tests pin the two structural repairs:

* a Stage-0 :data:`~clue_api.agent_runtime_wiring.CompletionGuard` that refuses a
  ``completed``/``awaiting_input`` finalize when a substantive user turn produced **zero** durable
  routing receipts. The refusal is structural — receipt present or not — never a judgment about the
  words the model wrote, and ``InterviewRoute.UNMAPPED`` is always an honest way to satisfy it;
* a deterministic readiness recompute after any turn that routed at least one non-``unmapped``
  statement, so the readiness ledger reflects the conversation instead of staying empty.
"""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4, uuid5

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents import (
    AgentExecutionStatus,
    AgentRole,
    AgentTurnRequest,
    AssembledAgentContext,
    DeepAgentTurnRuntime,
    FinalizeStatus,
)
from clue_api import stage0_trial as stage0_trial_module
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_runtime_wiring import GovernedAgentToolFactory, ModelFinalizeRequest
from clue_api.stage0_trial import (
    Stage0RoutingReceiptGuard,
    Stage0Trial,
    Stage0TrialPaths,
    Stage0TrialState,
    is_pure_command,
)
from clue_api.toolbelt_wiring import build_toolbelt
from clue_api.trial import spine as spine_module
from clue_core import (
    AccountStatus,
    Claim,
    EntityId,
    EntityType,
    ExtractionMethod,
    OnboardingInputId,
    OnboardingInputKind,
    ResearchMode,
    RunId,
    VerificationStatus,
)
from clue_research.claimstore import WorkspaceScope, claims_for, record_verification
from clue_research.identity import insert_account_entity
from clue_research.stage0 import (
    ClientInput,
    InterviewRoute,
    InterviewStatement,
    VolunteeredMaterial,
    client_kb_readiness_metrics,
    count_statements_for_input,
    reverse_profile,
    route_interview_answer,
    submit_onboarding_input,
)
from clue_research.stage0.fields import (
    CLIENT_KB_VERSION,
    CLIENT_KNOWLEDGE_FIELDS,
    CLIENT_PRODUCT,
    CLIENT_VALUE_PROP,
)
from clue_spine import create_brand, create_product, create_project
from clue_storage import artifact_key as make_artifact_key
from clue_storage import record_artifact
from tests.agents.conftest import NOW, artifact, constitution
from tests.agents.test_contracts import context_manifest
from tests.agents.test_finalize_contract import (
    _CountModelCalls,
    _finalize_call,
    _FinalizingExecutionAdapter,
)
from tests.agents.test_runtime import _DelegationArtifacts, _EmptyOutputBackend, _Models
from tests.db.conftest import run_async
from tests.stage0.conftest import rollback_conn

_ANSWER = "We target neurosurgery practices in the US, and our value proposition is speed."
_QUESTION = "Which practices should this project prioritize first?"


# --- the structural definition of "substantive" -------------------------------------------


@pytest.mark.parametrize(
    "message",
    ["/status", "/report", "/confirm-icp 2", "  /synthesize-icp  "],
)
def test_a_pure_command_turn_is_not_substantive(message: str) -> None:
    assert is_pure_command(message) is True


@pytest.mark.parametrize(
    "message",
    [
        "We target neurosurgery practices.",
        "/status is what I want, but first let me explain who we sell to and why.",
        "/note\nWe target neurosurgery practices.",
        "",
    ],
)
def test_everything_else_is_substantive(message: str) -> None:
    assert is_pure_command(message) is False


# --- the guard, against the real durable receipt table ------------------------------------


async def _seed_turn(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    answer: str = _ANSWER,
) -> tuple[str, str, EntityId, OnboardingInputId, str]:
    brand = await create_brand(conn, workspace_id=workspace_id, name="Routing brand")
    product = await create_product(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        name="Routing product",
    )
    project = await create_project(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        product_id=None,
        name="Routing project",
    )
    client = await insert_account_entity(
        conn,
        canonical_name="Routing Client",
        primary_domain="routing.example",
        workspace_id=workspace_id,
        status=AccountStatus.ACTIVE,
    )
    digest = hashlib.sha256(answer.encode()).hexdigest()
    key = make_artifact_key(workspace_id, digest)
    await record_artifact(
        conn,
        storage_key=key,
        workspace_id=workspace_id,
        content_sha256=digest,
        media_type="text/plain",
        size_bytes=len(answer),
    )
    captured = await submit_onboarding_input(
        conn,
        workspace_id=workspace_id,
        brand_id=brand.brand_id,
        product_id=product.product_id,
        project_id=project.project_id,
        client_entity_id=client,
        kind=OnboardingInputKind.USER_TURN,
        artifact_key=key,
        content_sha256=digest,
        actor="human",
    )
    return (
        brand.brand_id,
        product.product_id,
        client,
        captured.onboarding_input_id,
        project.project_id,
    )


def _guard(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    onboarding_input_id: OnboardingInputId,
    user_message: str = _ANSWER,
) -> Stage0RoutingReceiptGuard:
    @asynccontextmanager
    async def connection_factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return Stage0RoutingReceiptGuard(
        workspace_id=workspace_id,
        onboarding_input_id=onboarding_input_id,
        user_message=user_message,
        conn_factory=connection_factory,
    )


def _proposal(status: str) -> ModelFinalizeRequest:
    return ModelFinalizeRequest.model_validate({"status": status, "user_message": _QUESTION})


@pytest.mark.usefixtures("require_profiling_db")
@pytest.mark.parametrize("status", ["completed", "awaiting_input"])
def test_a_substantive_turn_with_no_receipt_is_refused(status: str) -> None:
    workspace_id = f"s0-guard-{uuid4().hex[:8]}"

    async def scenario() -> None:
        async with rollback_conn(workspace_id=workspace_id) as conn:
            _, _, _, onboarding_input_id, _ = await _seed_turn(conn, workspace_id=workspace_id)
            guard = _guard(
                conn,
                workspace_id=workspace_id,
                onboarding_input_id=onboarding_input_id,
            )
            with pytest.raises(ValueError) as refusal:
                await guard(_proposal(status))
            # The refusal must name the repair, including the honest escape hatch.
            assert "record_interview_answer" in str(refusal.value)
            assert "unmapped" in str(refusal.value)

    run_async(scenario())


@pytest.mark.usefixtures("require_profiling_db")
def test_an_unmapped_route_satisfies_the_guard() -> None:
    """UNMAPPED is the escape hatch that keeps the guard structural rather than semantic."""

    workspace_id = f"s0-unmapped-{uuid4().hex[:8]}"

    async def scenario() -> None:
        async with rollback_conn(workspace_id=workspace_id) as conn:
            brand_id, product_id, client, onboarding_input_id, project_id = await _seed_turn(
                conn, workspace_id=workspace_id
            )
            result = await route_interview_answer(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                product_id=product_id,
                project_id=project_id,
                client_entity_id=client,
                onboarding_input_id=onboarding_input_id,
                artifact_key=make_artifact_key(
                    workspace_id, hashlib.sha256(_ANSWER.encode()).hexdigest()
                ),
                answer=_ANSWER,
                statements=(
                    InterviewStatement(
                        route=InterviewRoute.UNMAPPED,
                        route_key="unmapped_small_talk",
                        quote_start=0,
                        quote_end=len(_ANSWER),
                    ),
                ),
                actor="agent",
            )
            assert len(result.unmapped_statement_ids) == 1
            counts = await count_statements_for_input(
                conn,
                workspace_id=workspace_id,
                onboarding_input_id=onboarding_input_id,
            )
            assert (counts.total, counts.non_unmapped) == (1, 0)
            guard = _guard(
                conn,
                workspace_id=workspace_id,
                onboarding_input_id=onboarding_input_id,
            )
            await guard(_proposal("completed"))

    run_async(scenario())


@pytest.mark.usefixtures("require_profiling_db")
def test_a_pure_command_turn_never_needs_a_receipt() -> None:
    workspace_id = f"s0-command-{uuid4().hex[:8]}"

    async def scenario() -> None:
        async with rollback_conn(workspace_id=workspace_id) as conn:
            _, _, _, onboarding_input_id, _ = await _seed_turn(conn, workspace_id=workspace_id)
            guard = _guard(
                conn,
                workspace_id=workspace_id,
                onboarding_input_id=onboarding_input_id,
                user_message="/status",
            )
            await guard(_proposal("completed"))
            await guard(_proposal("awaiting_input"))

    run_async(scenario())


@pytest.mark.usefixtures("require_profiling_db")
def test_a_failed_or_blocked_finalize_is_not_gated_on_receipts() -> None:
    """An honest failure must never be forced through a durable write it could not make."""

    workspace_id = f"s0-failed-{uuid4().hex[:8]}"

    async def scenario() -> None:
        async with rollback_conn(workspace_id=workspace_id) as conn:
            _, _, _, onboarding_input_id, _ = await _seed_turn(conn, workspace_id=workspace_id)
            guard = _guard(
                conn,
                workspace_id=workspace_id,
                onboarding_input_id=onboarding_input_id,
            )
            await guard(
                ModelFinalizeRequest.model_validate(
                    {"status": "failed", "failure_code": "interview_routing_failed"}
                )
            )
            await guard(_proposal("blocked"))

    run_async(scenario())


# --- the deterministic per-turn readiness recompute ---------------------------------------


def _claim(field_key: str, status: VerificationStatus) -> Claim:
    return Claim(
        entity_id=EntityId(uuid4()),
        entity_type=EntityType.ACCOUNT,
        field_key=field_key,
        value_json="volunteered",
        source_tier=1,
        extraction_method=ExtractionMethod.HUMAN,
        confidence=1.0,
        run_id=RunId(uuid4()),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        verification_status=status,
    )


def _trial(conn: AsyncConnection, state: Stage0TrialState, root: Any) -> Stage0Trial:
    trial = object.__new__(Stage0Trial)
    trial.state = state
    trial.paths = Stage0TrialPaths.for_session(root, state.session_slug)

    @asynccontextmanager
    async def connection_factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    trial._conn_factory = connection_factory
    return trial


def test_the_metric_compilation_means_what_its_names_say() -> None:
    """The one helper both readiness surfaces use, over a claim map it must not miscount.

    Three failure modes are pinned here because they are silent and land in a persisted,
    human-facing ledger: counting *all* claims as verified, counting a non-pack claim toward
    coverage (which can push the ratio past 1.0), and listing that non-pack key as an available
    field. The pack-marker claim ``client.kb_version`` is the real-world non-pack member.
    """

    claims = {
        CLIENT_VALUE_PROP: _claim(CLIENT_VALUE_PROP, VerificationStatus.VERIFIED),
        CLIENT_PRODUCT: _claim(CLIENT_PRODUCT, VerificationStatus.UNVERIFIED),
        CLIENT_KB_VERSION: _claim(CLIENT_KB_VERSION, VerificationStatus.VERIFIED),
    }

    metrics = client_kb_readiness_metrics(claims)

    assert metrics["verified_claims"] == 1  # not 2: the non-pack marker is not a pack field
    assert metrics["available_field_keys"] == [CLIENT_PRODUCT, CLIENT_VALUE_PROP]
    assert metrics["coverage_ratio"] == 2 / len(CLIENT_KNOWLEDGE_FIELDS)
    assert isinstance(metrics["coverage_ratio"], float)
    assert 0.0 <= metrics["coverage_ratio"] <= 1.0


def test_both_readiness_surfaces_compile_metrics_through_the_one_helper() -> None:
    """No second compilation may exist: a ledger that tells two stories about one trial is the
    defect class this helper was extracted to close."""

    for module in (stage0_trial_module, spine_module):
        source = Path(module.__file__ or "").read_text(encoding="utf-8")
        name = module.__name__
        assert "client_kb_readiness_metrics(claims)" in source, (
            f"{name} must compile Client-KB readiness metrics through the shared helper"
        )
        for token in ('"verified_claims"', '"coverage_ratio"', "verification_status"):
            assert token not in source, (
                f"{name} appears to re-derive {token} instead of using "
                "client_kb_readiness_metrics; there must be exactly one compilation"
            )


async def _seed_client_kb(
    conn: AsyncConnection,
    *,
    workspace_id: str,
    product_id: str,
    client: EntityId,
) -> int:
    """Publish one real Client-KB version carrying two pack claims, one of them verified.

    The published version also carries the ``client.kb_version`` marker — a legitimate non-pack
    claim — so the metric assertions below are made against a KB shaped like a real one, not a
    degenerate empty set where every metric is trivially 0.
    """

    published = await reverse_profile(
        conn,
        ClientInput(
            name="Routing Client",
            website="https://routing.example",
            materials=(
                VolunteeredMaterial(
                    kind="interview",
                    label="value prop",
                    content="Our value proposition is speed.",
                    asserted_fields={CLIENT_VALUE_PROP: "speed"},
                ),
                VolunteeredMaterial(
                    kind="interview",
                    label="product",
                    content="We sell a surgical scheduling platform.",
                    asserted_fields={CLIENT_PRODUCT: "surgical scheduling platform"},
                ),
            ),
        ),
        workspace_id=workspace_id,
        budget_cap_cents=Decimal(0),
        product_id=product_id,
        max_source_tier=0,
    )
    assert UUID(str(published.ref.client_entity_id)) == UUID(str(client))
    verified = next(
        item
        for item in await claims_for(
            conn,
            client,
            scope=WorkspaceScope.for_workspace(workspace_id),
        )
        if item.field_key == CLIENT_VALUE_PROP
    )
    await record_verification(conn, verified.id, status=VerificationStatus.VERIFIED)
    return published.ref.client_kb_version


@pytest.mark.usefixtures("require_profiling_db")
def test_a_material_routed_turn_persists_a_readiness_decision(tmp_path: Any) -> None:
    workspace_id = f"s0-readiness-{uuid4().hex[:8]}"

    async def scenario() -> None:
        async with rollback_conn(workspace_id=workspace_id) as conn:
            brand_id, product_id, client, onboarding_input_id, project_id = await _seed_turn(
                conn, workspace_id=workspace_id
            )
            kb_version = await _seed_client_kb(
                conn,
                workspace_id=workspace_id,
                product_id=product_id,
                client=client,
            )
            await route_interview_answer(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                product_id=product_id,
                project_id=project_id,
                client_entity_id=client,
                onboarding_input_id=onboarding_input_id,
                artifact_key=make_artifact_key(
                    workspace_id, hashlib.sha256(_ANSWER.encode()).hexdigest()
                ),
                answer=_ANSWER,
                statements=(
                    InterviewStatement(
                        route=InterviewRoute.PROJECT_STATE,
                        route_key="target_segment",
                        quote_start=0,
                        quote_end=41,
                    ),
                ),
                actor="agent",
            )
            session_id = uuid4()
            state = Stage0TrialState(
                session_id=session_id,
                session_slug="readiness-trial",
                workspace_id=workspace_id,
                brand_id=brand_id,
                product_id=product_id,
                project_id=project_id,
                client_entity_id=UUID(str(client)),
                client_kb_version=kb_version,
                company_name="Routing Client",
                website="https://routing.example",
                product_name="Routing product",
                project_name="Routing project",
                thread_id=f"stage0-trial-{session_id.hex}",
                created_at=NOW,
            )
            trial = _trial(conn, state, tmp_path)
            turn_id = uuid5(session_id, "turn-1")

            first = await trial._recompute_readiness(
                turn_id=turn_id,
                onboarding_input_id=onboarding_input_id,
            )
            assert first is not None
            rows = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, gate, verdict, metrics FROM readiness_decision "
                            "WHERE workspace_id = :workspace AND project_id = :project"
                        ),
                        {"workspace": workspace_id, "project": project_id},
                    )
                )
                .mappings()
                .all()
            )
            assert len(rows) == 1
            assert rows[0]["gate"] == "icp_synthesis"
            # The persisted, human-facing metrics must mean exactly what their names say. Two
            # pack claims are pinned and only one of them is verified, so a compilation that
            # counted every claim (or counted the non-pack `client.kb_version` marker toward
            # coverage) is caught here rather than in a ledger someone later trusts.
            metrics = rows[0]["metrics"]
            assert metrics["verified_claims"] == 1
            assert metrics["available_field_keys"] == [CLIENT_PRODUCT, CLIENT_VALUE_PROP]
            assert metrics["coverage_ratio"] == 2 / len(CLIENT_KNOWLEDGE_FIELDS)
            assert metrics["coverage_ratio"] <= 1.0
            assert metrics["project_state_statements"] == 1
            assert metrics["routed_statements_this_turn"] == 1
            assert metrics["material_statements_this_turn"] == 1

            # Re-running the identical turn is idempotent, not a second decision.
            again = await trial._recompute_readiness(
                turn_id=turn_id,
                onboarding_input_id=onboarding_input_id,
            )
            assert again is not None
            assert again.readiness_decision_id == first.readiness_decision_id
            count = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM readiness_decision "
                        "WHERE workspace_id = :workspace AND project_id = :project"
                    ),
                    {"workspace": workspace_id, "project": project_id},
                )
            ).scalar_one()
            assert count == 1

    run_async(scenario())


@pytest.mark.usefixtures("require_profiling_db")
def test_an_unmapped_only_turn_records_no_readiness_decision(tmp_path: Any) -> None:
    """Routing "nothing material" is honest, but it is not new evidence to re-evaluate."""

    workspace_id = f"s0-nomaterial-{uuid4().hex[:8]}"

    async def scenario() -> None:
        async with rollback_conn(workspace_id=workspace_id) as conn:
            brand_id, product_id, client, onboarding_input_id, project_id = await _seed_turn(
                conn, workspace_id=workspace_id
            )
            await route_interview_answer(
                conn,
                workspace_id=workspace_id,
                brand_id=brand_id,
                product_id=product_id,
                project_id=project_id,
                client_entity_id=client,
                onboarding_input_id=onboarding_input_id,
                artifact_key=make_artifact_key(
                    workspace_id, hashlib.sha256(_ANSWER.encode()).hexdigest()
                ),
                answer=_ANSWER,
                statements=(
                    InterviewStatement(
                        route=InterviewRoute.UNMAPPED,
                        route_key="unmapped_small_talk",
                        quote_start=0,
                        quote_end=len(_ANSWER),
                    ),
                ),
                actor="agent",
            )
            session_id = uuid4()
            state = Stage0TrialState(
                session_id=session_id,
                session_slug="nomaterial-trial",
                workspace_id=workspace_id,
                brand_id=brand_id,
                product_id=product_id,
                project_id=project_id,
                client_entity_id=UUID(str(client)),
                client_kb_version=1,
                company_name="Routing Client",
                website="https://routing.example",
                product_name="Routing product",
                project_name="Routing project",
                thread_id=f"stage0-trial-{session_id.hex}",
                created_at=NOW,
            )
            trial = _trial(conn, state, tmp_path)

            assert (
                await trial._recompute_readiness(
                    turn_id=uuid5(session_id, "turn-1"),
                    onboarding_input_id=onboarding_input_id,
                )
                is None
            )
            count = (
                await conn.execute(
                    text("SELECT count(*) FROM readiness_decision WHERE workspace_id = :workspace"),
                    {"workspace": workspace_id},
                )
            ).scalar_one()
            assert count == 0

    run_async(scenario())


# --- the guard inside the real deepagent loop ---------------------------------------------


class _RoutingReceipts:
    """Count routing receipts the way the durable table does: from what the turn actually did."""

    def __init__(self, execution: _FinalizingExecutionAdapter) -> None:
        self._execution = execution

    async def __call__(self, conn: Any, **kwargs: Any) -> Any:
        del conn, kwargs
        return SimpleNamespace(total=self.routed, non_unmapped=self.routed)

    @property
    def routed(self) -> int:
        return sum(
            1
            for plan in self._execution.validated_plans
            if getattr(getattr(plan.steps[0], "tool", None), "name", None)
            == "record_interview_answer"
        )


def _route_call(call_id: str) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[
            {
                "name": "record_interview_answer",
                "args": {
                    "brand_id": "brand-routing",
                    "onboarding_input_id": "00000000-0000-0000-0000-0000000000a1",
                    "artifact_key": "ws/abc",
                    "answer": _ANSWER,
                    "client_entity_id": "00000000-0000-0000-0000-0000000000a2",
                    "statements": [
                        {
                            "route": "project_state",
                            "route_key": "target_segment",
                            "quote_start": 0,
                            "quote_end": 41,
                        }
                    ],
                },
                "id": call_id,
                "type": "tool_call",
            }
        ],
    )


def _run_guarded(
    responses: tuple[AIMessage, ...],
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Any, _FinalizingExecutionAdapter, _CountModelCalls, _RoutingReceipts]:
    execution = _FinalizingExecutionAdapter()
    receipts = _RoutingReceipts(execution)
    monkeypatch.setattr("clue_api.stage0_trial.count_statements_for_input", receipts)
    registry = build_agent_profile_registry(build_toolbelt(storage=None, gateway=None))
    resolved = registry.resolve(AgentRole.HEAD_OF_ABM)
    request = AgentTurnRequest(
        turn_id=UUID("00000000-0000-0000-0000-0000000006a5"),
        thread_id="thread-routing-honesty",
        constitution=constitution(
            profile_ref=resolved.profile_ref,
            resource_manifest_sha256=resolved.resource_manifest.aggregate_sha256,
        ),
        user_message_artifact_ref=artifact("user-message.json"),
        requested_at=NOW,
    )

    @asynccontextmanager
    async def connection_factory() -> AsyncIterator[object]:
        yield object()

    guard = Stage0RoutingReceiptGuard(
        workspace_id="ws-routing",
        onboarding_input_id=OnboardingInputId(UUID("00000000-0000-0000-0000-0000000000a1")),
        user_message=_ANSWER,
        conn_factory=cast(Any, connection_factory),
    )
    factory = GovernedAgentToolFactory(
        request=request,
        resolved_profile=resolved,
        registry=build_toolbelt(storage=None, gateway=None),
        execution=cast(Any, execution),
        lease=cast(Any, SimpleNamespace(backend=_EmptyOutputBackend())),
        artifacts=cast(Any, _DelegationArtifacts()),
        completion_guard=guard,
    )
    runtime = DeepAgentTurnRuntime(
        models=_Models(responses),
        execution=cast(Any, execution),
        max_runtime_s=10,
    )
    calls = _CountModelCalls()
    outcome = run_async(
        runtime.run(
            request=request,
            resolved_profile=resolved,
            context=AssembledAgentContext(
                manifest=context_manifest(),
                messages=(HumanMessage(content=_ANSWER),),
            ),
            backend=None,
            governed_tools=factory.build(),
            callbacks=(calls,),
        )
    )
    return outcome, execution, calls, receipts


def test_a_receiptless_finalize_is_refused_and_the_model_recovers_by_routing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome, execution, calls, receipts = _run_guarded(
        (
            _finalize_call("finalize-no-receipt", status="awaiting_input", user_message=_QUESTION),
            _route_call("route-after-refusal"),
            _finalize_call(
                "finalize-after-routing",
                status="awaiting_input",
                user_message=_QUESTION,
            ),
        ),
        monkeypatch,
    )

    # The first proposal was refused *before* anything was committed, and the refusal — with the
    # UNMAPPED escape hatch in it — came back to the model as readable tool feedback.
    assert len(calls.batches) == 3
    feedback = str(calls.batches[1][-1].content)
    assert "record_interview_answer" in feedback
    assert "unmapped" in feedback
    # ... the model then actually routed, and only that turn committed.
    assert receipts.routed == 1
    assert outcome.status is AgentExecutionStatus.AWAITING_INPUT
    assert outcome.finalization_ref is not None
    assert [envelope.status for envelope in execution.envelopes] == [FinalizeStatus.AWAITING_INPUT]


def test_two_receiptless_finalizations_still_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    outcome, execution, calls, receipts = _run_guarded(
        (
            _finalize_call("finalize-none-1", status="completed", user_message=_QUESTION),
            _finalize_call("finalize-none-2", status="completed", user_message=_QUESTION),
        ),
        monkeypatch,
    )

    assert outcome.status is AgentExecutionStatus.FAILED
    assert outcome.failure_code == "missing_finalize"
    assert execution.envelopes == []
    assert receipts.routed == 0
    # Exactly one bounded corrective retry: the model is not asked a third time.
    assert len(calls.batches) == 2

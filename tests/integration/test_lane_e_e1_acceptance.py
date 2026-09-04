"""Lane E E1 acceptance — on-completion prose synthesis, end to end over the real substrate.

Nothing here is a shortcut around production. A real account-research fleet is launched, a real
job is driven terminal through ``finalize_entity_research_job``, the real
``AccountResearchFleetService`` reconciles it, the real toolbelt registry + :class:`ToolInvoker`
carry the governed ``synthesize_entity_prose@1`` call, and the real :class:`ProseSynthesizer` +
:class:`FaithfulnessJudgeImpl` write and judge the claim. The only doubles are the LLM gateway
(a paid network call) and the per-job research *driver* (which would run a whole agent).

The acceptance criteria (charter §5-E1) are claim- and ledger-based, in both toggle states:

1. a completed job produces ONE verified ``account.summary`` claim citing its evidence;
2. a judge-rejected synthesis changes nothing a reader can see;
3. an exploding synthesis leaves the job terminal and the fleet unsuspended;
4. a redelivered task produces no second claim;
5. a second completed pass supersedes rather than accumulates;
6. the four non-synthesizable outcomes produce nothing;
7. with verification disabled the claim is written UNVERIFIED and still served, while a REJECTED
   claim is still withheld.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from pydantic import JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_fleet import (
    AccountResearchFleetPolicy,
    AccountResearchFleetProjection,
    AccountResearchFleetService,
    AccountResearchFleetWorkHandler,
)
from clue_api.execution_wiring import build_tool_invoker
from clue_api.prose_synthesis_step import ProseSynthesisStep, prose_operation_id
from clue_api.prose_synthesis_tools import ProseSynthesisServices
from clue_api.research_view_runtime import ProductionResearchViewComposer
from clue_api.toolbelt_wiring import build_toolbelt
from clue_config import Settings
from clue_core import (
    AccountStatus,
    ClaimId,
    Completion,
    EntityId,
    EntityType,
    ExtractionMethod,
    Message,
    ProjectRunId,
    ResearchAvailability,
    ResearchMode,
    ResearchSectionKind,
    ResearchStatement,
    ResearchViewReadRequest,
    RunId,
    VerificationStatus,
    account_claim,
    new_project_run_id,
    new_run_id,
)
from clue_core.entity_research import (
    EntityResearchJobAuthorization,
    FinalizationVerification,
    ResearchFinalizationOutcome,
    ResearchFinalizationProposal,
    ResearchFinalizationReceipt,
    ResearchJobState,
    ResearchRunKind,
    ResearchSubjectType,
)
from clue_fleet import (
    EntityResearchExecutionFence,
    EntityResearchJobEnvelope,
    EntityResearchRunEnvelope,
    FleetTaskKind,
    LeaseGeneration,
    WorkContext,
    WorkId,
    WorkResult,
    acquire_work_lease,
    begin_entity_research_job,
    claim_next_task,
    finalize_entity_research_job,
    release_work_lease,
)
from clue_obs.otel import InMemorySink
from clue_research.claimstore import (
    WorkspaceScope,
    current_values,
    insert_claim,
    record_run_lineage,
    record_verification,
)
from clue_research.durable import AccountRunStatus, insert_account_run
from clue_research.identity import DEFAULT_REUSE_POLICY, insert_account_entity, stamp_reuse
from clue_research.narrative import (
    ACCOUNT_SUMMARY,
    METRIC_PROSE_FAILED,
    ProseSynthesizer,
    load_prose_pack,
    read_claim_support,
)
from clue_research.verification import FaithfulnessJudgeImpl
from clue_spine import Project
from tests._run_lineage import assert_written_claims_are_attributable
from tests._workspace import seed_project, seed_run, seed_workspace
from tests.fleet.entity_research_r2_helpers import run_envelope
from tests.profiling.conftest import conn_session_factory, rollback_conn, seed_packs
from tests.toolbelt.conftest import InMemoryStore

from .conftest import run_async

pytestmark = pytest.mark.usefixtures("require_integration_db")

_TTL = timedelta(seconds=60)
_PARAGRAPHS = (
    '{"paragraphs": ["Acme Robotics builds warehouse automation systems.", '
    '"It employs around 400 people and is expanding into the EU."]}'
)

#: Five merge-winning core facts — comfortably over the synthesizer's `min_facts` floor of 3.
_FACTS: tuple[tuple[str, JsonValue], ...] = (
    ("core.account_name", "Acme Robotics"),
    ("core.industry", "warehouse automation"),
    ("core.company_about", "Robotic picking and sortation for high-volume warehouses."),
    ("core.employee_count", 400),
    ("account.strategic_moves", "expanding to the EU"),
)


# --- doubles: the paid network call, and the per-job research agent --------------------------


class ScriptedGateway:
    """One gateway serving BOTH the prose synthesis and the faithfulness judge.

    Dispatch is by model id (the synthesizer and the judge use different configured models), so the
    real :class:`FaithfulnessJudgeImpl` runs unmodified — the toggle idiom under test is the
    production one, not a fake judge.
    """

    def __init__(self, *, prose: str = _PARAGRAPHS, verdict: str = "supported") -> None:
        self._prose = prose
        self._verdict = verdict
        self.models: list[str] = []

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        self.models.append(model)
        text_out = (
            self._prose
            if "claude-3.5-sonnet" not in model
            else (
                f'{{"verdict": "{self._verdict}", "score": '
                f"{0.95 if self._verdict == 'supported' else 0.05}, "
                '"rationale": "scripted"}'
            )
        )
        return Completion(
            model=model, text=text_out, cost_cents=Decimal("0.4"), finish_reason="stop"
        )

    def embed(self, *, model: str, inputs: list[str]) -> object:  # pragma: no cover - unused
        raise NotImplementedError("prose synthesis never embeds")


class ExplodingGateway:
    """A provider outage, injected at the one place the synthesis genuinely depends on."""

    def complete(self, *, model: str, messages: list[Message], **opts: object) -> Completion:
        raise RuntimeError("synthesis gateway exploded")

    def embed(self, *, model: str, inputs: list[str]) -> object:  # pragma: no cover - unused
        raise NotImplementedError


class _MemoryStorage:
    """The parameter-artifact backing the real invoker needs (no S3 in a test)."""

    def __init__(self) -> None:
        self.blobs: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self.blobs[key] = data

    async def get(self, key: str) -> bytes:
        return self.blobs[key]

    async def delete(self, key: str) -> None:
        self.blobs.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.blobs

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        return f"memory://{key}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, Any]]:  # pragma: no cover - unused
        return
        yield


@dataclass
class _FinalizingDriver:
    """Stands in for the whole per-job research agent — but drives the REAL R2 finalization, so the
    handler sees exactly the finalized-this-cycle ``WorkResult`` production produces."""

    conn: AsyncConnection
    envelope: EntityResearchRunEnvelope
    outcome: ResearchFinalizationOutcome = ResearchFinalizationOutcome.COMPLETED

    async def handle(self, context: WorkContext) -> WorkResult:
        job_id = self.envelope.jobs[0].authorization.job_id
        await _finalize(self.conn, self.envelope, outcome=self.outcome)
        receipt_ref = (
            await self.conn.execute(
                text("SELECT finalization_receipt_ref FROM entity_research_job WHERE job_id=:id"),
                {"id": job_id},
            )
        ).scalar_one()
        return WorkResult(
            outcome=self.outcome.value,
            references={"job_id": str(job_id), "finalization_receipt_ref": receipt_ref},
            task_finalized=True,
        )


def _factory(conn: AsyncConnection) -> Callable[[], AbstractAsyncContextManager[AsyncConnection]]:
    @asynccontextmanager
    async def factory() -> AsyncIterator[AsyncConnection]:
        yield conn

    return factory


# --- fixture: a workspace, an account with facts, and a finalized research job ----------------


@dataclass(frozen=True)
class LaneE:
    workspace_id: str
    project: Project
    account_id: EntityId
    envelope: EntityResearchRunEnvelope
    job_id: UUID
    research_run_id: UUID
    projection: AccountResearchFleetProjection
    fact_run_id: RunId
    project_run_id: ProjectRunId


def _envelope(
    *,
    workspace_id: str,
    project_id: str,
    product_id: str,
    project_run_id: UUID,
    account_id: EntityId,
) -> EntityResearchRunEnvelope:
    """The frozen R0 account envelope, re-pointed at this test's workspace/project/account."""
    base = run_envelope(ResearchRunKind.ACCOUNT_RESEARCH, concurrency_limit=1)
    subject = base.lifecycle.selection.subjects[0].model_copy(
        update={"subject_entity_id": UUID(str(account_id))}
    )
    selection = base.lifecycle.selection.model_copy(
        update={
            "workspace_id": workspace_id,
            "project_id": project_id,
            "product_id": product_id,
            "project_run_id": project_run_id,
            "subjects": (subject,),
        }
    )
    lifecycle = base.lifecycle.model_copy(update={"selection": selection})
    template = base.jobs[0]
    authorization = EntityResearchJobAuthorization(
        **{
            **template.authorization.model_dump(mode="python"),
            "job_id": uuid4(),
            "research_run_id": lifecycle.run_id,
            "workspace_id": workspace_id,
            "project_id": project_id,
            "product_id": product_id,
            "project_run_id": project_run_id,
            "subject_entity_id": UUID(str(account_id)),
            "selection": selection,
            "checkpoint_thread_id": f"checkpoint:{lifecycle.run_id}:{account_id}",
            "attempt_id": uuid4(),
            "lease_id": uuid4(),
        }
    )
    return EntityResearchRunEnvelope(
        lifecycle=lifecycle,
        jobs=(
            EntityResearchJobEnvelope(
                authorization=authorization,
                priority=0,
                budget_envelope_ref=f"budget:job:{authorization.job_id}",
                budget_cap_cents=Decimal("3.00"),
            ),
        ),
        budget_cap_cents=Decimal("10.00"),
        concurrency_limit=1,
    )


async def _write_fact(
    conn: AsyncConnection,
    account: EntityId,
    field_key: str,
    value: JsonValue,
    *,
    workspace_id: str,
    run_id: RunId,
) -> ClaimId:
    claim = stamp_reuse(
        account_claim(
            entity_id=account,
            field_key=field_key,
            value_json=value,
            source_tier=2,
            extraction_method=ExtractionMethod.SCRAPE,
            confidence=0.9,
            run_id=run_id,
            research_mode=ResearchMode.ACCOUNT_PROFILING,
            source_url="https://acme.example/about",
            evidence_span=f"evidence for {field_key}",
        ),
        workspace_id=workspace_id,
        policy=DEFAULT_REUSE_POLICY,
    )
    claim_id = await insert_claim(conn, claim)
    await record_verification(conn, claim_id, status=VerificationStatus.VERIFIED)
    return claim_id


def _receipt(
    *,
    job_id: UUID,
    subject_type: ResearchSubjectType,
    target_entity_id: UUID,
    current_state_sha256: str,
    outcome: ResearchFinalizationOutcome,
) -> ResearchFinalizationReceipt:
    """The R2 finalization receipt for any of the six outcomes.

    Written locally rather than borrowed from ``tests.fleet.entity_research_r2_helpers`` because a
    ``needs_review`` proposal is invalid without durable ``review_flags`` — and ``needs_review`` is
    one of the two outcomes Lane E must synthesize from, so this suite needs it to be constructible.
    """
    proposal = ResearchFinalizationProposal(
        proposal_id=uuid4(),
        subject_type=subject_type,
        target_entity_id=target_entity_id,
        outcome=outcome,
        current_state_sha256=current_state_sha256,
        coverage_ledger_ref=f"coverage:{job_id}",
        claim_delta_ledger_ref=f"claim-delta:{job_id}",
        spend_reconciliation_ref=f"spend:{job_id}",
        identity_use_verification_ref=f"identity-use:{job_id}",
        completed_field_keys=(
            (f"{subject_type.value}.research_complete",)
            if outcome is ResearchFinalizationOutcome.COMPLETED
            else ()
        ),
        review_flags=(
            ("low_confidence_committee",)
            if outcome is ResearchFinalizationOutcome.NEEDS_REVIEW
            else ()
        ),
    )
    return ResearchFinalizationReceipt(
        receipt_id=uuid4(),
        proposal=proposal,
        proposal_ref=f"finalization-proposal:{proposal.proposal_id}",
        engine_actor="engine:entity-research-finalizer",
        accepted_at=datetime.now(UTC),
        accepted_state_sha256=current_state_sha256,
        verification=FinalizationVerification(
            no_pending_operations=True,
            evidence_complete=True,
            coverage_matches=True,
            spend_reconciled=True,
            identity_use_verification_complete=True,
            policy_scope_respected=True,
            current_state_matches=True,
        ),
    )


async def _finalize(
    conn: AsyncConnection,
    envelope: EntityResearchRunEnvelope,
    *,
    outcome: ResearchFinalizationOutcome,
) -> None:
    """Drive the job terminal through the REAL R2 lifecycle (claim → lease → begin → finalize)."""
    job_id = envelope.jobs[0].authorization.job_id
    worker_id = f"worker:{job_id}"
    task = await claim_next_task(
        conn,
        kind=FleetTaskKind.ENTITY_RESEARCH_JOB,
        worker_id=worker_id,
        project_run_id=ProjectRunId(job_id),
    )
    assert task is not None
    lease = await acquire_work_lease(conn, work_id=WorkId(job_id), worker_id=worker_id, ttl=_TTL)
    assert lease is not None
    fence = EntityResearchExecutionFence(
        task_id=task.task_id,
        worker_id=worker_id,
        lease_generation=lease.generation,
        task_attempt=1,
    )
    begin = await begin_entity_research_job(conn, job_id, fence=fence)
    assert begin.admitted
    receipt = _receipt(
        job_id=job_id,
        subject_type=envelope.jobs[0].authorization.subject_type,
        target_entity_id=envelope.jobs[0].authorization.subject_entity_id,
        current_state_sha256=begin.job.current_state_sha256,
        outcome=outcome,
    )
    terminal = await finalize_entity_research_job(conn, job_id, fence=fence, receipt=receipt)
    assert terminal.state is ResearchJobState.TERMINAL
    await release_work_lease(
        conn,
        work_id=WorkId(job_id),
        worker_id=worker_id,
        generation=LeaseGeneration(lease.generation),
    )


async def _seed(
    conn: AsyncConnection,
    *,
    outcome: ResearchFinalizationOutcome = ResearchFinalizationOutcome.COMPLETED,
    facts: tuple[tuple[str, JsonValue], ...] = _FACTS,
    workspace_id: str | None = None,
    account_id: EntityId | None = None,
    project: Project | None = None,
    finalize: bool = True,
) -> LaneE:
    await seed_packs(conn)
    from clue_api.composition import load_research_packs

    await load_research_packs(conn)
    await load_prose_pack(conn)

    workspace_id = workspace_id or await seed_workspace(conn, f"ws_{uuid4().hex[:8]}")
    project = project or await seed_project(conn, workspace_id)
    if account_id is None:
        account_id = await insert_account_entity(
            conn,
            canonical_name="Acme Robotics",
            primary_domain=f"{uuid4().hex[:8]}.example",
            status=AccountStatus.ACTIVE,
            workspace_id=workspace_id,
        )
        fact_run_id = new_run_id()
        await record_run_lineage(
            conn,
            run_id=UUID(str(fact_run_id)),
            workspace_id=workspace_id,
            kind="enrichment",
            project_id=project.project_id,
        )
        for field_key, value in facts:
            await _write_fact(
                conn,
                account_id,
                field_key,
                value,
                workspace_id=workspace_id,
                run_id=fact_run_id,
            )
    else:
        fact_run_id = new_run_id()

    # A durable project run + one account run for it: the C7 view's scope resolver refuses to
    # compose without both, and production never mints a run id without them either.
    project_run_id = new_project_run_id()
    await seed_run(
        conn,
        project_run_id=project_run_id,
        workspace_id=workspace_id,
        project_id=project.project_id,
    )
    await insert_account_run(
        conn,
        account_run_id=new_run_id(),
        project_run_id=project_run_id,
        entity_id=account_id,
        tier="top",
        status=AccountRunStatus.DONE,
    )
    envelope = _envelope(
        workspace_id=workspace_id,
        project_id=project.project_id,
        product_id=f"product-{uuid4().hex[:8]}",
        project_run_id=UUID(str(project_run_id)),
        account_id=account_id,
    )
    # The prose claim is stamped with the job's research run, so that run must be attributable.
    await record_run_lineage(
        conn,
        run_id=envelope.lifecycle.run_id,
        workspace_id=workspace_id,
        kind="entity_research",
        project_id=project.project_id,
        project_run_id=UUID(str(project_run_id)),
    )
    service = AccountResearchFleetService(conn_factory=_factory(conn))
    await service.launch(
        envelope,
        policy=AccountResearchFleetPolicy(canary_size=1),
        actor="user:lane-e",
        source_operation_id=envelope.lifecycle.run_id,
        source_action_ref=f"agent-action:launch-account-research:{envelope.lifecycle.run_id}",
    )
    if finalize:
        await _finalize(conn, envelope, outcome=outcome)
    projection = await service.reconcile(envelope.lifecycle.run_id)
    return LaneE(
        workspace_id=workspace_id,
        project=project,
        account_id=account_id,
        envelope=envelope,
        job_id=envelope.jobs[0].authorization.job_id,
        research_run_id=envelope.lifecycle.run_id,
        projection=projection,
        fact_run_id=fact_run_id,
        project_run_id=project_run_id,
    )


# --- composition: the real toolbelt + invoker + bound step ------------------------------------


def _compose_step(
    conn: AsyncConnection,
    *,
    gateway: ScriptedGateway,
    verification_enabled: bool,
    sink: InMemorySink | None = None,
) -> tuple[ProseSynthesisStep, Any]:
    cf = conn_session_factory(conn)
    # The production toggle idiom, verbatim (`run_composition.py`): no judge when verification is
    # off, and NO explicit merge policy anywhere — the accessor must be what flips the read side.
    judge = (
        FaithfulnessJudgeImpl(gateway=cast(Any, gateway), conn_factory=cf)
        if verification_enabled
        else None
    )
    # E2 made `contact` required; production composes one instance as both fields, so this suite
    # composes it the same way. Nothing in E1's ACs touches the contact species.
    synthesizer = ProseSynthesizer(gateway=cast(Any, gateway), judge=judge, conn_factory=cf)
    registry = build_toolbelt(
        storage=None,
        gateway=cast(Any, gateway),
        conn_factory=cf,
        prose_synthesis=ProseSynthesisServices(account=synthesizer, contact=synthesizer),
    )
    invoker = build_tool_invoker(
        registry=registry,
        idempotency_store=InMemoryStore(),
        storage=cast(Any, _MemoryStorage()),
        settings=Settings(_env_file=None),
        conn_factory=cf,
    )
    step = ProseSynthesisStep(sink=sink, conn_factory=cf)
    step.bind(invoker)
    return step, invoker


def _terminal_result(fixture: LaneE, *, finalized: bool = True) -> WorkResult:
    """What the inner R2 handler returns on the finalized-this-cycle path."""
    references: dict[str, Any] = {"job_id": str(fixture.job_id)}
    if finalized:
        summary = next(item for item in fixture.projection.jobs if item.job_id == fixture.job_id)
        assert summary.finalization_receipt_ref is not None
        references["finalization_receipt_ref"] = summary.finalization_receipt_ref
    return WorkResult(outcome="completed", references=references, task_finalized=True)


async def _fire(fixture: LaneE, step: ProseSynthesisStep, *, finalized: bool = True) -> None:
    await step.after_account_job(
        job_id=fixture.job_id,
        result=_terminal_result(fixture, finalized=finalized),
        projection=fixture.projection,
    )


async def _live_summaries(conn: AsyncConnection, fixture: LaneE) -> list[Any]:
    rows = (
        await conn.execute(
            text(
                "SELECT id, verification_status, value_json, run_id FROM claim "
                "WHERE entity_id=:entity AND field_key=:field AND superseded_by IS NULL "
                "ORDER BY collected_at"
            ),
            {"entity": UUID(str(fixture.account_id)), "field": ACCOUNT_SUMMARY},
        )
    ).mappings()
    return list(rows)


async def _summary_section(conn: AsyncConnection, fixture: LaneE) -> Any:
    """The SUMMARY section of the live C7 account research view (production composer, real
    readers): the surface a human actually reads, not just the merge view underneath it."""
    view = await ProductionResearchViewComposer(conn_factory=conn_session_factory(conn)).compose(
        ResearchViewReadRequest(
            workspace_id=fixture.workspace_id,
            project_id=fixture.project.project_id,
            project_run_id=fixture.project_run_id,
            subject_entity_id=fixture.account_id,
            subject_entity_type=EntityType.ACCOUNT,
        )
    )
    return next(section for section in view.sections if section.kind is ResearchSectionKind.SUMMARY)


async def _served_summary(conn: AsyncConnection, fixture: LaneE) -> Any:
    merged = await current_values(
        conn,
        [fixture.account_id],
        (ACCOUNT_SUMMARY,),
        scope=WorkspaceScope.for_workspace(fixture.workspace_id),
    )
    return merged.get((fixture.account_id, ACCOUNT_SUMMARY))


# --- AC1: a completed job produces one verified, evidence-citing summary ----------------------


def test_a_completed_job_produces_one_verified_evidence_backed_summary() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn)
            step, _ = _compose_step(conn, gateway=ScriptedGateway(), verification_enabled=True)
            await _fire(fixture, step)

            rows = await _live_summaries(conn, fixture)
            assert len(rows) == 1
            row = rows[0]
            assert row["verification_status"] == VerificationStatus.VERIFIED.value
            value = row["value_json"]
            assert value["research_outcome"] == "completed"
            assert value["synthesized_from_job_id"] == str(fixture.job_id)
            # The §7-D2 amendment: the project leg is carried and pinned null while neutral.
            assert value["project_id"] is None
            assert len(value["paragraphs"]) == 2

            support = await read_claim_support(conn, ClaimId(row["id"]))
            assert support is not None
            assert len(support.account_evidence_ids) >= 3
            assert support.client_knowledge_ids == ()

            served = await _served_summary(conn, fixture)
            assert served is not None
            assert served.provenance.source_tier == 4

            # ...and the reader that actually matters: the live C7 account view's SUMMARY section,
            # composed by the production composer over the real readers.
            summary = await _summary_section(conn, fixture)
            assert summary.availability is ResearchAvailability.AVAILABLE
            statements = [item for item in summary.items if isinstance(item, ResearchStatement)]
            assert [item.field_key for item in statements] == [ACCOUNT_SUMMARY]
            assert statements[0].claim_id == ClaimId(row["id"])

            await assert_written_claims_are_attributable(
                conn,
                fixture.research_run_id,
                kind="entity_research",
                workspace_id=fixture.workspace_id,
                project_id=fixture.project.project_id,
                project_run_id=fixture.project_run_id,
            )

    run_async(scenario())


# --- AC2: a judge-rejected synthesis changes nothing a reader can see -------------------------


def test_a_judge_rejected_synthesis_is_not_served() -> None:
    """The claim exists (an auditable record of what was refused) but never reaches a reader."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn)
            step, _ = _compose_step(
                conn,
                gateway=ScriptedGateway(verdict="unsupported"),
                verification_enabled=True,
            )
            await _fire(fixture, step)

            rows = await _live_summaries(conn, fixture)
            assert len(rows) == 1
            assert rows[0]["verification_status"] == VerificationStatus.REJECTED.value
            assert await _served_summary(conn, fixture) is None

            # Zero visible change: the section keeps rendering its honest empty state.
            summary = await _summary_section(conn, fixture)
            assert summary.items == ()
            assert summary.availability is not ResearchAvailability.AVAILABLE

    run_async(scenario())


# --- AC3: an exploding synthesis never suspends the fleet -------------------------------------


def test_a_synthesis_failure_leaves_the_job_terminal_and_the_fleet_unsuspended() -> None:
    """The step sits outside the handler's suspend-on-error try; this proves it stays there."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            # Not pre-finalized: the handler parks an already-terminal redelivery, so the only way
            # to exercise the real post-finalize path is to let the driver drive the job terminal.
            fixture = await _seed(conn, finalize=False)
            sink = InMemorySink()
            # The REAL step, over a gateway that explodes mid-synthesis — the failure therefore
            # travels the production path (tool → synthesizer → gateway) into the step's catch-all.
            step, _ = _compose_step(
                conn,
                gateway=cast(Any, ExplodingGateway()),
                verification_enabled=True,
                sink=sink,
            )
            handler = AccountResearchFleetWorkHandler(
                inner=cast(Any, _FinalizingDriver(conn=conn, envelope=fixture.envelope)),
                fleets=AccountResearchFleetService(conn_factory=_factory(conn)),
                prose_step=step,
            )
            result = await handler.handle(
                WorkContext(
                    task_id=uuid4(),
                    work_id=WorkId(fixture.job_id),
                    worker_id="worker:lane-e",
                    lease_generation=cast(Any, 1),
                    payload={"job_id": str(fixture.job_id)},
                    stop_requested=cast(Any, _event()),
                    lease_lost=cast(Any, _event()),
                )
            )
            assert result.outcome == "completed"
            assert result.outcome != "supervisor_suspended"
            assert sink.counter(METRIC_PROSE_FAILED, field_key=ACCOUNT_SUMMARY) == 1
            # The job is untouched by the prose failure, and nothing half-written survives.
            state = (
                await conn.execute(
                    text("SELECT state FROM entity_research_job WHERE job_id=:id"),
                    {"id": fixture.job_id},
                )
            ).scalar_one()
            assert state == ResearchJobState.TERMINAL.value
            assert await _live_summaries(conn, fixture) == []

    run_async(scenario())


def _event() -> Any:
    import asyncio

    return asyncio.Event()


# --- AC4: a redelivered finalized task produces no second claim --------------------------------


def test_a_second_delivery_of_the_same_job_replays_instead_of_re_synthesizing() -> None:
    """One job = one synthesis. The A9 identity is content-addressed, so the journal replays."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn)
            gateway = ScriptedGateway()
            step, invoker = _compose_step(conn, gateway=gateway, verification_enabled=True)
            await _fire(fixture, step)
            synthesis_calls = len(gateway.models)

            replayed = await invoker.invoke(
                "synthesize_entity_prose",
                {"job_id": str(fixture.job_id), "field_key": ACCOUNT_SUMMARY},
                _machine_ctx(conn, fixture),
            )
            assert replayed.replayed is True
            assert len(gateway.models) == synthesis_calls  # no second paid call
            assert len(await _live_summaries(conn, fixture)) == 1

    run_async(scenario())


def _machine_ctx(conn: AsyncConnection, fixture: LaneE) -> Any:
    from clue_toolbelt import ToolContext

    return ToolContext(
        workspace_id=fixture.workspace_id,
        actor="agent",
        conn_factory=conn_session_factory(conn),
        operation_id=cast(Any, prose_operation_id(fixture.job_id, ACCOUNT_SUMMARY)),
    )


# --- AC5: a second completed pass supersedes rather than accumulates ---------------------------


def test_a_second_completed_research_pass_supersedes_the_prior_summary() -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            first = await _seed(conn)
            step, _ = _compose_step(conn, gateway=ScriptedGateway(), verification_enabled=True)
            await _fire(first, step)
            original = (await _live_summaries(conn, first))[0]["id"]

            second = await _seed(
                conn,
                workspace_id=first.workspace_id,
                account_id=first.account_id,
                project=first.project,
            )
            await _fire(second, step)

            rows = await _live_summaries(conn, second)
            assert len(rows) == 1
            assert rows[0]["id"] != original
            assert rows[0]["value_json"]["synthesized_from_job_id"] == str(second.job_id)
            superseded_by = (
                await conn.execute(
                    text("SELECT superseded_by FROM claim WHERE id=:id"), {"id": original}
                )
            ).scalar_one()
            assert superseded_by == rows[0]["id"]
            support = await read_claim_support(conn, ClaimId(rows[0]["id"]))
            assert support is not None and len(support.account_evidence_ids) >= 3

    run_async(scenario())


# --- AC6: the outcome gate --------------------------------------------------------------------


@pytest.mark.parametrize(
    "outcome",
    [
        ResearchFinalizationOutcome.EXHAUSTED,
        ResearchFinalizationOutcome.CANCELLED,
        ResearchFinalizationOutcome.BUDGET_STOPPED,
        ResearchFinalizationOutcome.FAILED,
    ],
)
def test_a_non_synthesizable_outcome_produces_no_prose(
    outcome: ResearchFinalizationOutcome,
) -> None:
    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn, outcome=outcome)
            gateway = ScriptedGateway()
            step, _ = _compose_step(conn, gateway=gateway, verification_enabled=True)
            await _fire(fixture, step)
            assert await _live_summaries(conn, fixture) == []
            assert gateway.models == []  # not even a refused spend reached the model

    run_async(scenario())


def test_a_needs_review_outcome_does_synthesize() -> None:
    """The other half of the D1 gate: needs_review is a *basis*, not a disqualification."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn, outcome=ResearchFinalizationOutcome.NEEDS_REVIEW)
            step, _ = _compose_step(conn, gateway=ScriptedGateway(), verification_enabled=True)
            await _fire(fixture, step)
            rows = await _live_summaries(conn, fixture)
            assert len(rows) == 1
            assert rows[0]["value_json"]["research_outcome"] == "needs_review"

    run_async(scenario())


# --- AC7: both toggle states ------------------------------------------------------------------


def test_with_verification_disabled_the_summary_is_unverified_yet_served(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No judge exists, so the claim keeps its born status — and the disabled-mode effective merge
    policy (never an explicit one) is what serves it."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn)
            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "false")
            gateway = ScriptedGateway()
            step, _ = _compose_step(conn, gateway=gateway, verification_enabled=False)
            await _fire(fixture, step)

            rows = await _live_summaries(conn, fixture)
            assert len(rows) == 1
            assert rows[0]["verification_status"] == VerificationStatus.UNVERIFIED.value
            # One completion only: the judge never ran.
            assert len(gateway.models) == 1
            served = await _served_summary(conn, fixture)
            assert served is not None
            assert served.value_json["research_outcome"] == "completed"

            # ...and the enabled-mode read withholds the very same unverified tier-4 claim.
            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "true")
            assert await _served_summary(conn, fixture) is None

    run_async(scenario())


def test_a_rejected_summary_is_withheld_in_disabled_mode_too(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled mode drops the tier-4 *verified* gate, never the REJECTED exclusion: a claim the
    judge refused must never serve, in either mode."""

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            fixture = await _seed(conn)
            step, _ = _compose_step(
                conn,
                gateway=ScriptedGateway(verdict="unsupported"),
                verification_enabled=True,
            )
            await _fire(fixture, step)
            assert (await _live_summaries(conn, fixture))[0]["verification_status"] == (
                VerificationStatus.REJECTED.value
            )
            monkeypatch.setenv("CLUE_VERIFICATION_ENABLED", "false")
            assert await _served_summary(conn, fixture) is None

    run_async(scenario())

"""Lane E E1 — the governed ``synthesize_entity_prose@1`` tool and its fail-soft fleet step.

Three surfaces, three postures:

* **the tool** — a fail-closed governed surface: every refusal is a typed ``reason_code`` in a
  documented check order, and a cross-workspace job is indistinguishable from an absent one;
* **the step** — fail-*soft*: it runs outside the fleet handler's suspend-on-error try, so a
  synthesis that raises is logged + counted and the job stays terminal;
* **the handler** — provably unchanged when no step is composed.

The synthesizer itself (`clue_research.narrative.prose`) is faked here on purpose: WP-A owns its
behaviour, and these tests own the *seam*.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from clue_core import EntityId, RunId
from clue_core.entity_research import (
    ResearchFinalizationOutcome,
    ResearchJobState,
    ResearchSubjectType,
)
from clue_core.execution_graph import operation_id_from_key
from clue_db import transaction
from clue_research.narrative import ACCOUNT_SUMMARY, CONTACT_OVERVIEW, ProseOutcome
from clue_toolbelt import (
    ReplayPolicy,
    ToolContext,
    ToolEffectClass,
    ToolResult,
)
from tests.db.conftest import run_async

_WS = "ws-lane-e"

#: Explicit "compose this tool with no gateway" sentinel — distinct from ``_tool``'s default,
#: which supplies a fake one (``None`` would be ambiguous with "not supplied").
_NO_GATEWAY = object()


# --- doubles ----------------------------------------------------------------------------------


@dataclass
class _FakeJob:
    """The subset of ``EntityResearchJobRow`` the tool reads (structural double)."""

    job_id: UUID
    research_run_id: UUID
    subject_entity_id: UUID
    workspace_id: str
    state: ResearchJobState
    finalization_outcome: ResearchFinalizationOutcome | None
    subject_type: ResearchSubjectType = ResearchSubjectType.ACCOUNT


@dataclass
class _FakeJobReader:
    jobs: dict[UUID, _FakeJob] = field(default_factory=dict)

    async def get_job(self, job_id: UUID) -> Any:
        return self.jobs.get(job_id)


@dataclass
class _FakeSynthesizer:
    outcome: ProseOutcome = field(
        default_factory=lambda: ProseOutcome(kind="coverage_gap", gap_reason="insufficient_facts")
    )
    calls: list[dict[str, Any]] = field(default_factory=list)
    error: Exception | None = None

    async def synthesize_account_summary(
        self,
        *,
        account_entity_id: EntityId,
        workspace_id: str,
        research_run_id: RunId,
        job_id: UUID,
        research_outcome: str,
    ) -> ProseOutcome:
        self.calls.append(
            {
                "account_entity_id": account_entity_id,
                "workspace_id": workspace_id,
                "research_run_id": research_run_id,
                "job_id": job_id,
                "research_outcome": research_outcome,
            }
        )
        if self.error is not None:
            raise self.error
        return self.outcome


class _FakeGateway:
    def complete(self, *, model: str, messages: Any) -> Any:  # pragma: no cover - never called
        raise AssertionError("the tool must not call the gateway itself")


def _terminal_job(
    *,
    workspace_id: str = _WS,
    outcome: ResearchFinalizationOutcome | None = ResearchFinalizationOutcome.COMPLETED,
    state: ResearchJobState = ResearchJobState.TERMINAL,
) -> _FakeJob:
    return _FakeJob(
        job_id=uuid4(),
        research_run_id=uuid4(),
        subject_entity_id=uuid4(),
        workspace_id=workspace_id,
        state=state,
        finalization_outcome=outcome,
    )


def _ctx(workspace_id: str = _WS) -> ToolContext:
    return ToolContext(
        workspace_id=workspace_id,
        actor="agent",
        conn_factory=transaction,
        operation_id=operation_id_from_key("lane_e_prose", f"{uuid4()}:{ACCOUNT_SUMMARY}"),
    )


def _tool(
    *,
    services: Any,
    jobs: _FakeJobReader | None = None,
    gateway: Any = None,
) -> Any:
    from clue_api.prose_synthesis_tools import SynthesizeEntityProseTool

    return SynthesizeEntityProseTool(
        services=services,
        gateway=None if gateway is _NO_GATEWAY else cast(Any, gateway or _FakeGateway()),
        jobs=cast(Any, jobs if jobs is not None else _FakeJobReader()),
    )


def _services(synthesizer: _FakeSynthesizer) -> Any:
    from clue_api.prose_synthesis_tools import ProseSynthesisServices

    return ProseSynthesisServices(account=cast(Any, synthesizer))


async def _codes(tool: Any, body: dict[str, object], ctx: ToolContext) -> tuple[str, ...]:
    failures = await tool.preconditions(tool.input_model(**body), ctx)
    return tuple(item.reason_code for item in failures)


# --- the governed tool contract ---------------------------------------------------------------


def test_the_tool_descriptor_pins_its_governed_contract() -> None:
    """A machine-invoked spend tool whose only replay defence is the A9 operation id."""
    descriptor = _tool(services=None).descriptor
    assert descriptor.address == "synthesize_entity_prose@1"
    assert descriptor.effect_class is ToolEffectClass.SPEND
    assert descriptor.replay.policy is ReplayPolicy.OPERATION_IDEMPOTENT
    assert descriptor.replay.operation_id_required is True
    assert descriptor.parameter_policy.safe_display_fields == ("job_id", "field_key")
    assert descriptor.has_typed_output
    assert descriptor.recipe_safe


def test_an_uncomposed_prose_service_refuses_before_any_other_check() -> None:
    """``projections_main`` builds the same toolbelt with no synthesizer: refuse, never crash."""

    async def scenario() -> None:
        tool = _tool(services=None)
        # Even a structurally invalid field key reports the composition refusal first.
        assert await _codes(tool, {"job_id": str(uuid4()), "field_key": "nope"}, _ctx()) == (
            "prose_synthesis_not_composed",
        )

    run_async(scenario())


def test_an_unregistered_field_key_is_refused() -> None:
    async def scenario() -> None:
        tool = _tool(services=_services(_FakeSynthesizer()))
        body = {"job_id": str(uuid4()), "field_key": "account.about"}
        assert await _codes(tool, body, _ctx()) == ("invalid_field_key",)

    run_async(scenario())


def test_contact_overview_is_refused_as_not_yet_composed() -> None:
    """E1 ships the account synthesizer only; ``contact.overview`` is E2's."""

    async def scenario() -> None:
        tool = _tool(services=_services(_FakeSynthesizer()))
        body = {"job_id": str(uuid4()), "field_key": CONTACT_OVERVIEW}
        assert await _codes(tool, body, _ctx()) == ("field_not_composed",)

    run_async(scenario())


def test_an_absent_job_and_a_cross_workspace_job_refuse_identically() -> None:
    """Fail-closed with no existence leak: another tenant's job looks exactly like no job."""

    async def scenario() -> None:
        foreign = _terminal_job(workspace_id="ws-other")
        reader = _FakeJobReader({foreign.job_id: foreign})
        tool = _tool(services=_services(_FakeSynthesizer()), jobs=reader)
        absent = await _codes(tool, {"job_id": str(uuid4()), "field_key": ACCOUNT_SUMMARY}, _ctx())
        cross = await _codes(
            tool, {"job_id": str(foreign.job_id), "field_key": ACCOUNT_SUMMARY}, _ctx()
        )
        assert absent == ("job_not_found",)
        assert cross == absent

    run_async(scenario())


def test_a_malformed_job_id_refuses_job_not_found() -> None:
    async def scenario() -> None:
        tool = _tool(services=_services(_FakeSynthesizer()))
        body = {"job_id": "not-a-uuid", "field_key": ACCOUNT_SUMMARY}
        assert await _codes(tool, body, _ctx()) == ("job_not_found",)

    run_async(scenario())


def test_a_job_that_is_not_terminal_is_refused() -> None:
    async def scenario() -> None:
        job = _terminal_job(state=ResearchJobState.RUNNING, outcome=None)
        tool = _tool(services=_services(_FakeSynthesizer()), jobs=_FakeJobReader({job.job_id: job}))
        body = {"job_id": str(job.job_id), "field_key": ACCOUNT_SUMMARY}
        assert await _codes(tool, body, _ctx()) == ("job_not_terminal",)

    run_async(scenario())


@pytest.mark.parametrize(
    "outcome",
    [
        ResearchFinalizationOutcome.EXHAUSTED,
        ResearchFinalizationOutcome.BUDGET_STOPPED,
        ResearchFinalizationOutcome.CANCELLED,
        ResearchFinalizationOutcome.FAILED,
    ],
)
def test_only_completed_and_needs_review_may_synthesize(
    outcome: ResearchFinalizationOutcome,
) -> None:
    """The §7-D1 gate: four of the six terminal outcomes never produce prose."""

    async def scenario() -> None:
        job = _terminal_job(outcome=outcome)
        tool = _tool(services=_services(_FakeSynthesizer()), jobs=_FakeJobReader({job.job_id: job}))
        body = {"job_id": str(job.job_id), "field_key": ACCOUNT_SUMMARY}
        assert await _codes(tool, body, _ctx()) == ("outcome_not_synthesizable",)

    run_async(scenario())


@pytest.mark.parametrize(
    "outcome",
    [ResearchFinalizationOutcome.COMPLETED, ResearchFinalizationOutcome.NEEDS_REVIEW],
)
def test_a_composed_synthesizable_job_has_no_unmet_preconditions(
    outcome: ResearchFinalizationOutcome,
) -> None:
    async def scenario() -> None:
        job = _terminal_job(outcome=outcome)
        tool = _tool(services=_services(_FakeSynthesizer()), jobs=_FakeJobReader({job.job_id: job}))
        body = {"job_id": str(job.job_id), "field_key": ACCOUNT_SUMMARY}
        assert await _codes(tool, body, _ctx()) == ()

    run_async(scenario())


def test_a_gatewayless_composition_refuses_rather_than_raising() -> None:
    """The posture precedent (``coverage_tools``): a typed refusal, never ``GatewayRequired``."""

    async def scenario() -> None:
        job = _terminal_job()
        tool = _tool(
            services=_services(_FakeSynthesizer()),
            jobs=_FakeJobReader({job.job_id: job}),
            gateway=_NO_GATEWAY,
        )
        body = {"job_id": str(job.job_id), "field_key": ACCOUNT_SUMMARY}
        assert await _codes(tool, body, _ctx()) == ("gateway_required",)

    run_async(scenario())


def test_invoke_hands_the_synthesizer_the_jobs_own_identity() -> None:
    """No tool-authored entity/run/outcome: every one is read off the durable job row."""

    async def scenario() -> None:
        job = _terminal_job(outcome=ResearchFinalizationOutcome.NEEDS_REVIEW)
        synthesizer = _FakeSynthesizer()
        tool = _tool(services=_services(synthesizer), jobs=_FakeJobReader({job.job_id: job}))
        await tool.invoke(
            tool.input_model(job_id=str(job.job_id), field_key=ACCOUNT_SUMMARY), _ctx()
        )
        assert synthesizer.calls == [
            {
                "account_entity_id": EntityId(job.subject_entity_id),
                "workspace_id": _WS,
                "research_run_id": RunId(job.research_run_id),
                "job_id": job.job_id,
                "research_outcome": "needs_review",
            }
        ]

    run_async(scenario())


def test_invoke_maps_a_written_outcome_to_typed_references() -> None:
    async def scenario() -> None:
        job = _terminal_job()
        claim_id = uuid4()
        support = (uuid4(), uuid4(), uuid4())
        synthesizer = _FakeSynthesizer(
            outcome=ProseOutcome(
                kind="written",
                claim_id=cast(Any, claim_id),
                support_claim_ids=cast(Any, support),
                verification_status="verified",
            )
        )
        tool = _tool(services=_services(synthesizer), jobs=_FakeJobReader({job.job_id: job}))
        result = await tool.invoke(
            tool.input_model(job_id=str(job.job_id), field_key=ACCOUNT_SUMMARY), _ctx()
        )
        assert isinstance(result, ToolResult)
        assert result.references == {
            "job_id": str(job.job_id),
            "field_key": ACCOUNT_SUMMARY,
            "claim_id": str(claim_id),
            "support_claim_ids": [str(item) for item in support],
            "verification_status": "verified",
            "outcome": "written",
            "research_outcome": "completed",
        }
        # The typed output model must accept its own tool's references (recipe safety is real).
        assert tool.output_model.model_validate(result.references).claim_id == str(claim_id)

    run_async(scenario())


def test_invoke_maps_a_coverage_gap_to_a_null_claim_id() -> None:
    """Empty beats fabricated: a gap is a *successful* invocation carrying no claim."""

    async def scenario() -> None:
        job = _terminal_job()
        synthesizer = _FakeSynthesizer(
            outcome=ProseOutcome(kind="coverage_gap", gap_reason="ungrounded_synthesis")
        )
        tool = _tool(services=_services(synthesizer), jobs=_FakeJobReader({job.job_id: job}))
        result = await tool.invoke(
            tool.input_model(job_id=str(job.job_id), field_key=ACCOUNT_SUMMARY), _ctx()
        )
        assert result.references["outcome"] == "coverage_gap"
        assert result.references["claim_id"] is None
        assert result.references["support_claim_ids"] == []
        assert result.references["verification_status"] == ""

    run_async(scenario())


def test_the_estimate_is_a_single_synthesis_completion() -> None:
    tool = _tool(services=None)
    estimate = tool.estimate(tool.input_model(job_id=str(uuid4()), field_key=ACCOUNT_SUMMARY))
    assert estimate.cost_cents >= Decimal(0)
    assert estimate.detail["basis"] == "prose_synthesis_single_completion"


# --- the fail-soft fleet step --------------------------------------------------------------


def _summary(
    job_id: UUID,
    *,
    outcome: ResearchFinalizationOutcome | None = ResearchFinalizationOutcome.COMPLETED,
) -> Any:
    from clue_api.account_research_fleet import (
        AccountResearchAdmissionState,
        AccountResearchFleetCohort,
        AccountResearchJobSummary,
    )

    return AccountResearchJobSummary(
        job_id=job_id,
        account_run_id=uuid4(),
        account_entity_id=uuid4(),
        cohort=AccountResearchFleetCohort.CANARY,
        admission_state=AccountResearchAdmissionState.ADMITTED,
        effective_priority=0,
        job_state=ResearchJobState.TERMINAL,
        finalization_outcome=outcome,
        finalization_receipt_ref=f"entity-research-finalization:{uuid4()}",
        current_wait_ref=None,
        spent_cents=Decimal("1.00"),
    )


def _projection(*summaries: Any, workspace_id: str = _WS) -> Any:
    from clue_api.account_research_fleet import (
        AccountResearchFleetProjection,
        AccountResearchFleetState,
    )

    return AccountResearchFleetProjection(
        research_run_id=uuid4(),
        workspace_id=workspace_id,
        project_id="prj-lane-e",
        product_id="prod-lane-e",
        project_run_id=uuid4(),
        fleet_state=AccountResearchFleetState.TERMINAL,
        run_state="terminal",
        selected_accounts=len(summaries),
        queued_accounts=0,
        active_accounts=0,
        waiting_accounts=0,
        paused_accounts=0,
        terminal_accounts=len(summaries),
        completed_accounts=len(summaries),
        needs_review_accounts=0,
        spent_cents=Decimal("1.00"),
        budget_cap_cents=Decimal("10.00"),
        jobs=summaries,
        review_queue=(),
        contact_research_request_count=0,
    )


def _work_result(*, finalized: bool = True) -> Any:
    from clue_fleet import WorkResult

    references: dict[str, Any] = {"job_id": str(uuid4())}
    if finalized:
        references["finalization_receipt_ref"] = f"entity-research-finalization:{uuid4()}"
    return WorkResult(outcome="completed", references=references, task_finalized=True)


@dataclass
class _FakeInvoker:
    calls: list[tuple[str, dict[str, object], ToolContext]] = field(default_factory=list)
    error: Exception | None = None

    async def invoke(
        self, name: str, body: dict[str, object], context: ToolContext, **kwargs: Any
    ) -> Any:
        self.calls.append((name, body, context))
        if self.error is not None:
            raise self.error
        return ToolResult(tool=name, version="1", references={})


def _step(*, sink: Any = None) -> Any:
    from clue_api.prose_synthesis_step import ProseSynthesisStep

    return ProseSynthesisStep(sink=sink)


def _sink() -> Any:
    from clue_obs.otel import InMemorySink

    return InMemorySink()


def _failed_counts(sink: Any) -> float:
    from clue_research.narrative import METRIC_PROSE_FAILED

    return cast(float, sink.counter(METRIC_PROSE_FAILED, field_key=ACCOUNT_SUMMARY))


def test_binding_the_step_twice_is_refused() -> None:
    """The deferred-bind precedent: a silent second bind would hide a composition mistake."""
    step = _step()
    step.bind(cast(Any, _FakeInvoker()))
    with pytest.raises(RuntimeError, match="already bound"):
        step.bind(cast(Any, _FakeInvoker()))


def test_a_redelivered_already_terminal_task_never_synthesizes() -> None:
    """Only the finalized-*this-cycle* path carries a receipt ref; a redelivery cannot re-spend."""

    async def scenario() -> None:
        job_id = uuid4()
        invoker = _FakeInvoker()
        step = _step()
        step.bind(cast(Any, invoker))
        await step.after_account_job(
            job_id=job_id,
            result=_work_result(finalized=False),
            projection=_projection(_summary(job_id)),
        )
        assert invoker.calls == []

    run_async(scenario())


def test_a_job_absent_from_the_projection_never_synthesizes() -> None:
    async def scenario() -> None:
        invoker = _FakeInvoker()
        step = _step()
        step.bind(cast(Any, invoker))
        await step.after_account_job(
            job_id=uuid4(),
            result=_work_result(),
            projection=_projection(_summary(uuid4())),
        )
        assert invoker.calls == []

    run_async(scenario())


@pytest.mark.parametrize(
    "outcome",
    [
        ResearchFinalizationOutcome.EXHAUSTED,
        ResearchFinalizationOutcome.BUDGET_STOPPED,
        ResearchFinalizationOutcome.CANCELLED,
        ResearchFinalizationOutcome.FAILED,
        None,
    ],
)
def test_the_step_reapplies_the_outcome_gate_before_spending(
    outcome: ResearchFinalizationOutcome | None,
) -> None:
    """The tool would refuse anyway; the step declines first so the journal stays clean."""

    async def scenario() -> None:
        job_id = uuid4()
        invoker = _FakeInvoker()
        step = _step()
        step.bind(cast(Any, invoker))
        await step.after_account_job(
            job_id=job_id,
            result=_work_result(),
            projection=_projection(_summary(job_id, outcome=outcome)),
        )
        assert invoker.calls == []

    run_async(scenario())


def test_the_step_invokes_the_tool_with_the_content_addressed_operation_id() -> None:
    """One job = one synthesis: the A9 identity is derived, never minted."""

    async def scenario() -> None:
        job_id = uuid4()
        invoker = _FakeInvoker()
        step = _step()
        step.bind(cast(Any, invoker))
        projection = _projection(_summary(job_id))
        await step.after_account_job(job_id=job_id, result=_work_result(), projection=projection)
        assert len(invoker.calls) == 1
        name, body, ctx = invoker.calls[0]
        assert name == "synthesize_entity_prose"
        assert body == {"job_id": str(job_id), "field_key": ACCOUNT_SUMMARY}
        assert ctx.workspace_id == projection.workspace_id
        assert ctx.actor == "agent"
        assert ctx.actor_id is None and ctx.action_ref is None
        assert ctx.operation_id == operation_id_from_key(
            "lane_e_prose", f"{job_id}:{ACCOUNT_SUMMARY}"
        )
        # Re-running the same finalized job derives the identical operation id (the crash-rerun
        # collapse the invocation journal then resolves to a replay).
        await step.after_account_job(job_id=job_id, result=_work_result(), projection=projection)
        assert invoker.calls[1][2].operation_id == ctx.operation_id

    run_async(scenario())


def test_a_synthesis_that_raises_is_swallowed_and_counted() -> None:
    """The step runs OUTSIDE the handler's suspend-on-error try: it must never re-raise."""

    async def scenario() -> None:
        job_id = uuid4()
        sink = _sink()
        invoker = _FakeInvoker(error=RuntimeError("gateway exploded"))
        step = _step(sink=sink)
        step.bind(cast(Any, invoker))
        await step.after_account_job(
            job_id=job_id, result=_work_result(), projection=_projection(_summary(job_id))
        )
        assert _failed_counts(sink) == 1

    run_async(scenario())


def test_a_precondition_refusal_is_not_a_failure() -> None:
    """An ineligible job is a *decision*, not an incident — no failure metric."""

    async def scenario() -> None:
        from clue_toolbelt import PreconditionFailed, PreconditionFailure

        job_id = uuid4()
        sink = _sink()
        refusal = PreconditionFailed(
            (PreconditionFailure(reason_code="job_not_terminal", message="not yet"),)
        )
        invoker = _FakeInvoker(error=refusal)
        step = _step(sink=sink)
        step.bind(cast(Any, invoker))
        await step.after_account_job(
            job_id=job_id, result=_work_result(), projection=_projection(_summary(job_id))
        )
        assert _failed_counts(sink) == 0

    run_async(scenario())


def test_an_unbound_step_fails_soft_rather_than_breaking_the_fleet() -> None:
    """A composition mistake degrades prose, never the research run."""

    async def scenario() -> None:
        job_id = uuid4()
        sink = _sink()
        step = _step(sink=sink)
        await step.after_account_job(
            job_id=job_id, result=_work_result(), projection=_projection(_summary(job_id))
        )
        assert _failed_counts(sink) == 1

    run_async(scenario())


# --- the handler seam ------------------------------------------------------------------------


@dataclass
class _FakeFleets:
    projection: Any
    reconciled: list[UUID] = field(default_factory=list)
    suspended: int = 0

    async def job_run_id(self, job_id: UUID) -> UUID:
        return cast(UUID, self.projection.research_run_id)

    async def admission_state(self, job_id: UUID) -> Any:
        from clue_api.account_research_fleet import AccountResearchAdmissionState

        return AccountResearchAdmissionState.ADMITTED

    async def park_unadmitted_claim(self, job_id: UUID, *, state: Any) -> None:  # pragma: no cover
        raise AssertionError("an admitted job is never parked")

    async def reconcile(self, research_run_id: UUID) -> Any:
        self.reconciled.append(research_run_id)
        return self.projection

    async def suspend_failure(self, context: Any, error: Exception) -> Any:  # pragma: no cover
        self.suspended += 1
        return self.projection


@dataclass
class _FakeInner:
    result: Any

    async def handle(self, context: Any) -> Any:
        return self.result


@dataclass
class _RecordingStep:
    seen: list[tuple[UUID, Any, Any]] = field(default_factory=list)

    async def after_account_job(self, *, job_id: UUID, result: Any, projection: Any) -> None:
        self.seen.append((job_id, result, projection))


def _work_context(job_id: UUID) -> Any:
    import asyncio

    from clue_fleet import WorkContext, WorkId

    return WorkContext(
        task_id=uuid4(),
        work_id=WorkId(job_id),
        worker_id="worker:lane-e",
        lease_generation=cast(Any, 1),
        payload={"job_id": str(job_id)},
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )


def test_the_handler_without_a_prose_step_is_byte_identical_to_today() -> None:
    """The default composition must be provably unchanged: no step, no extra call, same result."""

    async def scenario() -> None:
        from clue_api.account_research_fleet import AccountResearchFleetWorkHandler

        job_id = uuid4()
        inner_result = _work_result()
        fleets = _FakeFleets(projection=_projection(_summary(job_id)))
        handler = AccountResearchFleetWorkHandler(
            inner=cast(Any, _FakeInner(result=inner_result)), fleets=cast(Any, fleets)
        )
        result = await handler.handle(_work_context(job_id))
        assert result.outcome == inner_result.outcome
        assert (
            result.references["finalization_receipt_ref"]
            == (inner_result.references["finalization_receipt_ref"])
        )
        assert result.references["research_run_id"] == str(fleets.projection.research_run_id)
        assert fleets.reconciled == [fleets.projection.research_run_id]

    run_async(scenario())


def test_the_handler_hands_the_step_the_inner_result_after_reconcile() -> None:
    """The step sees the INNER result (whose references carry the receipt ref) and the reconciled
    projection — and it runs after reconcile, outside the suspend-on-error try."""

    async def scenario() -> None:
        from clue_api.account_research_fleet import AccountResearchFleetWorkHandler

        job_id = uuid4()
        inner_result = _work_result()
        fleets = _FakeFleets(projection=_projection(_summary(job_id)))
        step = _RecordingStep()
        handler = AccountResearchFleetWorkHandler(
            inner=cast(Any, _FakeInner(result=inner_result)),
            fleets=cast(Any, fleets),
            prose_step=cast(Any, step),
        )
        result = await handler.handle(_work_context(job_id))
        assert result.outcome == "completed"
        assert len(step.seen) == 1
        seen_job, seen_result, seen_projection = step.seen[0]
        assert seen_job == job_id
        assert seen_result is inner_result
        assert seen_projection is fleets.projection

    run_async(scenario())


# --- composition threading (§3.3) --------------------------------------------------------------
#
# These assert on the handler's private ``_prose_step`` deliberately: the composition's whole job
# is to put the step *there*, and the handler exposes no public accessor (adding one purely for a
# test would be production API written for the test suite). A drop anywhere along the chain —
# provider wiring → entity composition → account composition → handler — fails here.


class _StubProviderActions:
    """A non-static account provider resolver (the production composition refuses static ones)."""

    async def resolve(self, job: Any) -> dict[str, Any]:  # pragma: no cover - never resolved
        return {}


class _StubChannelActions:
    async def resolve(self, job: Any) -> dict[str, Any]:  # pragma: no cover - never resolved
        return {}


def _model_policy() -> Any:
    from clue_agents import ModelPolicy

    return ModelPolicy(
        model_id="model-lane-e",
        timeout_s=30,
        max_retries=1,
        max_output_tokens=1024,
        temperature=0,
    )


def test_the_account_fleet_composition_threads_the_prose_step_to_the_handler() -> None:
    from clue_api.account_research_fleet_composition import (
        build_account_research_fleet_composition,
    )

    step = _step()
    composition = build_account_research_fleet_composition(
        storage=cast(Any, None),
        models=cast(Any, None),
        provider_actions=cast(Any, _StubProviderActions()),
        model_policy=_model_policy(),
        prose_step=cast(Any, step),
    )
    assert composition.handler._prose_step is step


def test_the_account_fleet_composition_defaults_to_no_prose_step() -> None:
    """Every existing call site keeps composing the pre-Lane-E handler."""
    from clue_api.account_research_fleet_composition import (
        build_account_research_fleet_composition,
    )

    composition = build_account_research_fleet_composition(
        storage=cast(Any, None),
        models=cast(Any, None),
        provider_actions=cast(Any, _StubProviderActions()),
        model_policy=_model_policy(),
    )
    assert composition.handler._prose_step is None


def test_the_entity_fleet_composition_forwards_the_prose_step_to_the_account_lane() -> None:
    from clue_api.entity_research_fleet_composition import (
        build_entity_research_fleet_composition,
    )

    step = _step()
    composition = build_entity_research_fleet_composition(
        storage=cast(Any, None),
        models=cast(Any, None),
        account_provider_actions=cast(Any, _StubProviderActions()),
        contact_provider_actions=cast(Any, _StubProviderActions()),
        contact_channel_actions=cast(Any, _StubChannelActions()),
        model_policy=_model_policy(),
        prose_step=cast(Any, step),
    )
    assert composition.accounts.handler._prose_step is step


def test_the_production_entity_fleet_wiring_forwards_the_prose_step() -> None:
    """The last link before ``fleet_main``: the production builder must not drop the step."""
    from clue_api.entity_research_provider_wiring import build_production_entity_research_fleet
    from clue_config import Secrets, Settings, default_gateway_config

    step = _step()
    composition = build_production_entity_research_fleet(
        settings=Settings(_env_file=None, entity_research_runtime_enabled=True),
        secrets=Secrets(_env_file=None),
        storage=cast(Any, None),
        models=None,
        gateway=cast(Any, _FakeGateway()),
        gateway_config=default_gateway_config(),
        pre_spend_gate=cast(Any, None),
        prose_step=cast(Any, step),
    )
    assert composition is not None
    assert composition.accounts.handler._prose_step is step


def test_the_production_entity_fleet_wiring_stays_off_under_its_own_switch() -> None:
    """A prose step never turns the entity-research runtime on by itself."""
    from clue_api.entity_research_provider_wiring import build_production_entity_research_fleet
    from clue_config import Secrets, Settings, default_gateway_config

    assert (
        build_production_entity_research_fleet(
            settings=Settings(_env_file=None, entity_research_runtime_enabled=False),
            secrets=Secrets(_env_file=None),
            storage=cast(Any, None),
            models=None,
            gateway=cast(Any, _FakeGateway()),
            gateway_config=default_gateway_config(),
            pre_spend_gate=cast(Any, None),
            prose_step=cast(Any, _step()),
        )
        is None
    )

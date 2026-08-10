"""Lane E E3 — the governed ``synthesize_value_narrative@1`` tool.

The seam, not the synthesis: the :class:`~clue_research.narrative.Positioner` is WP-A-owned and
already has its own suite. What these tests own is the governed surface around it —

* the descriptor's frozen contract (a machine-invoked SPEND whose only replay defence is the A9
  operation id) **including the nested-model output surviving a journal replay round-trip**;
* the refusal ladder, in order, each code fail-closed and each reachable;
* the workspace fail-closed job load (a cross-tenant job is indistinguishable from an absent one);
* the committee **probe**: an account with no resolvable buying committee is a typed refusal
  outcome, never a zero-length "success" — and the positioner is never invoked for it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID, uuid4

import pytest

from clue_core import (
    EntityId,
    ICPCreatedFrom,
    ProjectPhase,
    ProjectRunId,
    new_project_run_id,
)
from clue_core.entity_research import (
    ResearchFinalizationOutcome,
    ResearchJobState,
    ResearchSubjectType,
)
from clue_core.execution_graph import operation_id_from_key
from clue_core.handoff import ICPSpec
from clue_db import transaction
from clue_obs.otel import InMemorySink
from clue_research.durable import ProjectRunRow, ProjectRunStatus
from clue_toolbelt import (
    ReplayPolicy,
    ToolContext,
    ToolEffectClass,
    ToolResult,
)
from clue_toolbelt.runner import validate_tool_result
from tests.db.conftest import run_async

_WS = "ws-lane-e3"
_ICP_KEY = "icp-primary"
_PRODUCT = "product-e3"

#: Explicit "compose this tool with no gateway" sentinel (the E1 idiom): ``None`` alone would be
#: ambiguous with "not supplied".
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
    project_id: str = "project-e3"
    product_id: str | None = _PRODUCT
    project_run_id: UUID | None = None
    subject_type: ResearchSubjectType = ResearchSubjectType.ACCOUNT
    parent_account_id: UUID | None = None


@dataclass
class _FakeJobReader:
    jobs: dict[UUID, _FakeJob] = field(default_factory=dict)

    async def get_job(self, job_id: UUID) -> Any:
        return self.jobs.get(job_id)


def _project_run(
    *,
    project_run_id: ProjectRunId,
    client_entity_id: EntityId | None,
    client_kb_version: int | None,
) -> ProjectRunRow:
    now = datetime.now(UTC)
    return ProjectRunRow(
        id=project_run_id,
        project_id="project-e3",
        brand_id="brand-e3",
        workspace_id=_WS,
        icp_key=_ICP_KEY,
        icp_version=3,
        phase=ProjectPhase.DEEP,
        status=ProjectRunStatus.ACTIVE,
        budget_cap_cents=None,
        spent_cents=Decimal(0),
        tier_cutoffs={},
        paused_at=None,
        resumed_at=None,
        created_at=now,
        updated_at=now,
        client_entity_id=client_entity_id,
        client_kb_version=client_kb_version,
        product_id=_PRODUCT,
    )


@dataclass
class _FakeContextReader:
    """The two pinned reads the client-context resolution needs, as a pure double."""

    run: ProjectRunRow | None = None
    spec: ICPSpec | None = None
    icp_calls: list[tuple[str, str, int]] = field(default_factory=list)

    async def get_project_run(self, project_run_id: ProjectRunId) -> ProjectRunRow | None:
        return self.run

    async def get_icp_version(
        self, *, workspace_id: str, icp_key: str, version: int
    ) -> ICPSpec | None:
        self.icp_calls.append((workspace_id, icp_key, version))
        return self.spec


class _FakeGateway:
    def complete(self, *, model: str, messages: Any) -> Any:  # pragma: no cover - never called
        raise AssertionError("the tool must not call the gateway itself")


class _FakeRetriever:
    async def retrieve(self, **kwargs: Any) -> tuple[Any, ...]:  # pragma: no cover - unused here
        return ()


def _services(**overrides: Any) -> Any:
    from clue_api.value_narrative_tools import ValueNarrativeServices

    kwargs: dict[str, Any] = {
        "gateway": cast(Any, _FakeGateway()),
        "judge": None,
        "retriever": cast(Any, _FakeRetriever()),
    }
    kwargs.update(overrides)
    return ValueNarrativeServices(**kwargs)


def _job(
    *,
    workspace_id: str = _WS,
    outcome: ResearchFinalizationOutcome | None = ResearchFinalizationOutcome.COMPLETED,
    state: ResearchJobState = ResearchJobState.TERMINAL,
    subject_type: ResearchSubjectType = ResearchSubjectType.ACCOUNT,
    product_id: str | None = _PRODUCT,
    project_run_id: UUID | None = None,
) -> _FakeJob:
    return _FakeJob(
        job_id=uuid4(),
        research_run_id=uuid4(),
        subject_entity_id=uuid4(),
        workspace_id=workspace_id,
        state=state,
        finalization_outcome=outcome,
        product_id=product_id,
        project_run_id=project_run_id if project_run_id is not None else uuid4(),
        subject_type=subject_type,
    )


def _ctx(workspace_id: str = _WS) -> ToolContext:
    return ToolContext(
        workspace_id=workspace_id,
        actor="agent",
        conn_factory=transaction,
        operation_id=operation_id_from_key("lane_e_prose", f"{uuid4()}:account.value_narrative"),
    )


def _tool(
    *,
    services: Any,
    jobs: _FakeJobReader | None = None,
    context: _FakeContextReader | None = None,
    gateway: Any = None,
    sink: Any = None,
    conn_factory: Any = None,
) -> Any:
    from clue_api.value_narrative_tools import SynthesizeValueNarrativeTool

    resolved = context
    if resolved is None:
        # The default: a Stage-0-confirmed run whose own client legs answer, so a test that is
        # about some *other* rung of the ladder never trips over the client resolution.
        resolved = _FakeContextReader(
            run=_project_run(
                project_run_id=new_project_run_id(),
                client_entity_id=EntityId(uuid4()),
                client_kb_version=2,
            )
        )
    kwargs: dict[str, Any] = {
        "services": services,
        "gateway": None if gateway is _NO_GATEWAY else cast(Any, gateway or _FakeGateway()),
        "jobs": cast(Any, jobs if jobs is not None else _FakeJobReader()),
        "context": cast(Any, resolved),
        "sink": sink,
    }
    if conn_factory is not None:
        kwargs["conn_factory"] = conn_factory
    return SynthesizeValueNarrativeTool(**kwargs)


async def _codes(tool: Any, body: dict[str, object], ctx: ToolContext) -> tuple[str, ...]:
    failures = await tool.preconditions(tool.input_model(**body), ctx)
    return tuple(item.reason_code for item in failures)


# --- the governed tool contract ---------------------------------------------------------------


def test_the_tool_descriptor_pins_its_governed_contract() -> None:
    descriptor = _tool(services=None).descriptor
    assert descriptor.address == "synthesize_value_narrative@1"
    assert descriptor.effect_class is ToolEffectClass.SPEND
    assert descriptor.replay.policy is ReplayPolicy.OPERATION_IDEMPOTENT
    assert descriptor.replay.operation_id_required is True
    assert descriptor.parameter_policy.safe_display_fields == ("job_id",)
    assert descriptor.has_typed_output
    assert descriptor.recipe_safe
    # One job = one narrative RUN, so the crash window repeats N completions, not one.
    assert "N" in descriptor.replay.notes or "per persona" in descriptor.replay.notes


def test_the_nested_output_survives_the_journal_replay_round_trip() -> None:
    """``validate_tool_result`` re-validates a stored result against the strict output model on
    every replay, so the per-persona nested rows must survive dict → model → JSON → model."""
    from clue_api.value_narrative_tools import SynthesizeValueNarrativeTool

    tool = _tool(services=None)
    references: dict[str, Any] = {
        "job_id": str(uuid4()),
        "outcome": "written",
        "committee_size": 2,
        "narratives": [
            {
                "claim_id": str(uuid4()),
                "persona": "champion",
                "angle_label": "operational relief",
                "judge_verdict": "supported",
            }
        ],
        "coverage_gaps": [{"persona": "blocker", "reason": "no_client_knowledge"}],
    }
    result = ToolResult(
        tool=SynthesizeValueNarrativeTool.name,
        version=SynthesizeValueNarrativeTool.version,
        references=references,
    )
    validated = validate_tool_result(tool, result)
    # The journal stores the JSON-mode dump and re-validates it on replay: that second pass is the
    # one a nested model can fail, so it is the one pinned here.
    replayed = validate_tool_result(
        tool,
        ToolResult(
            tool=SynthesizeValueNarrativeTool.name,
            version=SynthesizeValueNarrativeTool.version,
            references=validated.references,
        ),
    )
    assert replayed.references == validated.references
    assert replayed.references["narratives"][0]["persona"] == "champion"
    assert replayed.references["coverage_gaps"][0]["reason"] == "no_client_knowledge"


# --- the refusal ladder, in order --------------------------------------------------------------


def test_an_uncomposed_narrative_service_refuses_before_any_other_check() -> None:
    """``projections_main`` (and every flag-off deployment) builds the same toolbelt with no
    positioning services: refuse fail-closed, never crash, and never read a job."""

    async def scenario() -> None:
        jobs = _FakeJobReader()
        tool = _tool(services=None, jobs=jobs)
        assert await _codes(tool, {"job_id": "not-a-uuid"}, _ctx()) == (
            "value_narrative_not_composed",
        )

    run_async(scenario())


def test_an_absent_job_and_a_cross_workspace_job_refuse_identically() -> None:
    async def scenario() -> None:
        foreign = _job(workspace_id="ws-other")
        reader = _FakeJobReader({foreign.job_id: foreign})
        tool = _tool(services=_services(), jobs=reader)
        absent = await _codes(tool, {"job_id": str(uuid4())}, _ctx())
        cross = await _codes(tool, {"job_id": str(foreign.job_id)}, _ctx())
        malformed = await _codes(tool, {"job_id": "not-a-uuid"}, _ctx())
        assert absent == ("job_not_found",)
        assert cross == absent == malformed

    run_async(scenario())


def test_a_job_that_is_not_terminal_is_refused() -> None:
    async def scenario() -> None:
        job = _job(state=ResearchJobState.RUNNING, outcome=None)
        tool = _tool(services=_services(), jobs=_FakeJobReader({job.job_id: job}))
        assert await _codes(tool, {"job_id": str(job.job_id)}, _ctx()) == ("job_not_terminal",)

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
def test_only_completed_and_needs_review_may_position(
    outcome: ResearchFinalizationOutcome,
) -> None:
    """The §7-D1 gate is shared with the prose tool — imported, never redefined."""

    async def scenario() -> None:
        job = _job(outcome=outcome)
        tool = _tool(services=_services(), jobs=_FakeJobReader({job.job_id: job}))
        assert await _codes(tool, {"job_id": str(job.job_id)}, _ctx()) == (
            "outcome_not_synthesizable",
        )

    run_async(scenario())


def test_the_shared_outcome_gate_is_the_prose_tools_own() -> None:
    from clue_api.prose_synthesis_tools import SYNTHESIZABLE_OUTCOMES as prose_gate
    from clue_api.value_narrative_tools import SYNTHESIZABLE_OUTCOMES as narrative_gate

    assert narrative_gate is prose_gate


def test_a_contact_job_is_refused_as_not_an_account_job() -> None:
    """The value narrative is keyed on ``(account, persona)``: a contact job has no committee to
    position, and positioning its subject would key the claim to the wrong entity."""

    async def scenario() -> None:
        job = _job(subject_type=ResearchSubjectType.CONTACT)
        tool = _tool(services=_services(), jobs=_FakeJobReader({job.job_id: job}))
        assert await _codes(tool, {"job_id": str(job.job_id)}, _ctx()) == ("not_an_account_job",)

    run_async(scenario())


def test_a_job_without_a_project_run_is_refused() -> None:
    async def scenario() -> None:
        job = _job()
        job.project_run_id = None
        tool = _tool(services=_services(), jobs=_FakeJobReader({job.job_id: job}))
        assert await _codes(tool, {"job_id": str(job.job_id)}, _ctx()) == (
            "project_run_unresolved",
        )

    run_async(scenario())


def test_a_product_less_job_is_refused_rather_than_writing_invisible_shelfware() -> None:
    """``account.value_narrative`` is an ``exact_required`` product route: a product-less narrative
    claim is invisible to every reader, so writing one would be paid-for fabrication."""

    async def scenario() -> None:
        job = _job(product_id=None)
        tool = _tool(services=_services(), jobs=_FakeJobReader({job.job_id: job}))
        assert await _codes(tool, {"job_id": str(job.job_id)}, _ctx()) == (
            "product_context_unresolved",
        )

    run_async(scenario())


def test_an_unresolvable_client_context_is_refused_not_fabricated() -> None:
    async def scenario() -> None:
        job = _job()
        context = _FakeContextReader(
            run=_project_run(
                project_run_id=ProjectRunId(cast(UUID, job.project_run_id)),
                client_entity_id=None,
                client_kb_version=None,
            ),
            spec=None,
        )
        tool = _tool(services=_services(), jobs=_FakeJobReader({job.job_id: job}), context=context)
        assert await _codes(tool, {"job_id": str(job.job_id)}, _ctx()) == (
            "client_context_unresolved",
        )
        # The fallback was attempted against the RUN's pin, never the active ICP.
        assert context.icp_calls == [(_WS, _ICP_KEY, 3)]

    run_async(scenario())


def test_a_vanished_project_run_row_refuses_project_run_unresolved() -> None:
    async def scenario() -> None:
        job = _job()
        tool = _tool(
            services=_services(),
            jobs=_FakeJobReader({job.job_id: job}),
            context=_FakeContextReader(run=None, spec=None),
        )
        assert await _codes(tool, {"job_id": str(job.job_id)}, _ctx()) == (
            "project_run_unresolved",
        )

    run_async(scenario())


def test_the_confirmed_icp_lineage_resolves_the_client_when_the_run_legs_are_null() -> None:
    """Every non-Stage-0-confirmed run today carries NULL client legs; the C4 lineage on the RUN's
    pinned ICP version is what makes those runs positionable at all."""

    async def scenario() -> None:
        job = _job()
        client = EntityId(uuid4())
        context = _FakeContextReader(
            run=_project_run(
                project_run_id=ProjectRunId(cast(UUID, job.project_run_id)),
                client_entity_id=None,
                client_kb_version=None,
            ),
            spec=ICPSpec(
                workspace_id=_WS,
                icp_key=_ICP_KEY,
                version=3,
                created_from=ICPCreatedFrom.SYNTHESIS,
                client_entity_id=client,
                client_kb_version=7,
                product_id=_PRODUCT,
            ),
        )
        tool = _tool(services=_services(), jobs=_FakeJobReader({job.job_id: job}), context=context)
        assert await _codes(tool, {"job_id": str(job.job_id)}, _ctx()) == ()

    run_async(scenario())


def test_a_gatewayless_composition_refuses_rather_than_raising() -> None:
    async def scenario() -> None:
        job = _job()
        tool = _tool(
            services=_services(),
            jobs=_FakeJobReader({job.job_id: job}),
            gateway=_NO_GATEWAY,
        )
        assert await _codes(tool, {"job_id": str(job.job_id)}, _ctx()) == ("gateway_required",)

    run_async(scenario())


def test_a_composed_positionable_job_has_no_unmet_preconditions() -> None:
    async def scenario() -> None:
        job = _job()
        tool = _tool(services=_services(), jobs=_FakeJobReader({job.job_id: job}))
        assert await _codes(tool, {"job_id": str(job.job_id)}, _ctx()) == ()

    run_async(scenario())


# --- the committee probe -----------------------------------------------------------------------


def test_an_empty_committee_is_a_typed_outcome_and_never_a_zero_length_success(
    require_profiling_db: None,
) -> None:
    """The production-realistic starved path (no ``references_index`` writer on the M8D fleet):
    the tool refuses honestly rather than reporting a successful synthesis of nothing, and the
    positioner — every completion of it — is never reached."""
    from clue_api.value_narrative_tools import METRIC_COMMITTEE_UNAVAILABLE
    from tests.profiling.conftest import conn_session_factory, rollback_conn

    async def scenario() -> None:
        async with rollback_conn(seed_pack=True) as conn:
            job = _job()
            gateway = _CountingGateway()
            sink = InMemorySink()
            tool = _tool(
                services=_services(gateway=cast(Any, gateway)),
                jobs=_FakeJobReader({job.job_id: job}),
                gateway=cast(Any, gateway),
                sink=sink,
                conn_factory=conn_session_factory(conn),
            )
            result = await tool.invoke(tool.input_model(job_id=str(job.job_id)), _ctx())
            assert result.references["outcome"] == "committee_unavailable"
            assert result.references["committee_size"] == 0
            assert result.references["narratives"] == []
            assert gateway.calls == 0
            assert sink.counter(METRIC_COMMITTEE_UNAVAILABLE) == 1

    run_async(scenario())


class _CountingGateway:
    def __init__(self) -> None:
        self.calls = 0

    def complete(self, *, model: str, messages: Any, **opts: Any) -> Any:
        self.calls += 1
        raise AssertionError("no committee means no synthesis spend")


# --- the deployment flag ------------------------------------------------------------------------


def test_the_synthesis_flag_is_default_off_and_env_bound(monkeypatch: pytest.MonkeyPatch) -> None:
    """A pinning test (the flag is config, not behaviour): default-off is the whole safety story
    for a surface that spends one completion per committee persona, and the env name is the only
    thing a deployment can reach for."""
    from clue_config import Settings

    assert Settings(_env_file=None).value_narrative_synthesis_enabled is False
    monkeypatch.setenv("CLUE_VALUE_NARRATIVE_SYNTHESIS_ENABLED", "true")
    assert Settings(_env_file=None).value_narrative_synthesis_enabled is True

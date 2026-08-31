"""Lane E E3 — the governed ``synthesize_value_narrative@1`` tool.

E1/E2 taught the fleet to write *neutral* prose about a finished research job. This is the other
species: the per-persona **argument** — why this client matters to this account, for this buyer —
which the M12.1 :class:`~clue_research.narrative.Positioner` has been able to produce since M12 but
which no production process has ever constructed. E3 composes it, behind its own flag, at the
same post-finalize seam.

It is a separate tool rather than a third field on the prose tool because the two are structurally
different results: prose is one claim, the narrative is *N* claims plus the per-persona coverage
gaps, and its effect profile is N gateway completions + N judge calls rather than one of each.

Two disciplines shape everything below.

* **Nothing is caller-authored.** The account, the research run, the project, the product, the ICP
  pin and the client lineage are all read from durable rows — the job, its ``project_run``, and
  (when the run's client legs are null, which is every non-Stage-0-confirmed run today) that run's
  *pinned* ICP version. A leg that cannot be resolved is a typed refusal, never a default.
* **An empty committee is a refusal, not a success.** ``Positioner.position`` over an empty
  committee returns zero narratives *and* zero gaps — a silent no-op indistinguishable from
  "nothing to say". Since the only writer of the committee membership this reads
  (``account_run.references_index``) is the R1-quarantined M8A/C orchestrator, that is the *common*
  case on the M8D fleet today. So the tool probes the committee itself, before spending anything,
  and reports ``committee_unavailable`` with its own metric.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Protocol
from uuid import UUID

import structlog

from clue_api.contact_eligibility import (
    ContactEligibilityResolver,
    ProductionHandoffCommitteeReader,
)
from clue_api.prose_synthesis_tools import (
    SYNTHESIZABLE_OUTCOMES,
    EntityResearchJobReader,
)
from clue_core import EntityId, FaithfulnessJudge, LLMGateway, ProjectRunId, RunId
from clue_core.entity_research import ResearchJobState, ResearchSubjectType
from clue_core.handoff import ICPSpec
from clue_core.retrieval import ClientKnowledgeRetriever
from clue_db import ConnFactory, transaction
from clue_fleet import DbEntityResearchJobStore
from clue_fleet.entity_research import EntityResearchJobRow
from clue_obs.otel import MetricSink, get_metric_sink
from clue_research.durable import ProjectRunRow, get_project_run
from clue_research.icp import get_icp_version
from clue_research.narrative import (
    Positioner,
    PositioningResult,
    load_positioning_policy,
)
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolOutput,
    ToolResult,
)

log = structlog.get_logger(__name__)

#: Emitted when the account has no resolvable buying committee, so no narrative could be attempted.
#: The durable signal is the *absence* of narrative claims; this is what makes that absence
#: observable rather than mute.
METRIC_COMMITTEE_UNAVAILABLE = "research.value_narrative.committee_unavailable"
#: One per completed positioning run (not per persona — the positioner emits its own per-persona
#: counter). Carries the persona count so a run that produced two of four is legible.
METRIC_NARRATIVES_PRODUCED = "research.value_narrative.produced"
#: The per-run coverage-gap count: personas the committee had but no grounded argument covered.
METRIC_COVERAGE_GAPS = "research.value_narrative.coverage_gaps"

#: The three terminal shapes a positioning run can report.
OUTCOME_WRITTEN = "written"
OUTCOME_COMMITTEE_UNAVAILABLE = "committee_unavailable"
OUTCOME_NO_NARRATIVES = "no_narratives"


class NarrativeContextReader(Protocol):
    """The two pinned reads the client-context resolution needs.

    A seam for the same reason ``EntityResearchJobReader`` is one: it keeps the resolution ladder
    unit-testable without a database, and keeps the tool honest that these are *reads of durable
    rows*, not knobs a caller can supply.
    """

    async def get_project_run(self, project_run_id: ProjectRunId) -> ProjectRunRow | None: ...

    async def get_icp_version(
        self, *, workspace_id: str, icp_key: str, version: int
    ) -> ICPSpec | None: ...


class DbNarrativeContextReader:
    """The production reader: each read in its own short transaction through the injected
    factory."""

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def get_project_run(self, project_run_id: ProjectRunId) -> ProjectRunRow | None:
        async with self._conn_factory() as conn:
            return await get_project_run(conn, project_run_id)

    async def get_icp_version(
        self, *, workspace_id: str, icp_key: str, version: int
    ) -> ICPSpec | None:
        async with self._conn_factory() as conn:
            return await get_icp_version(conn, workspace_id, icp_key, version)


@dataclass(frozen=True, slots=True)
class ValueNarrativeServices:
    """The long-lived positioning collaborators, composed once at the fleet root.

    Everything here outlives a single invocation. The per-invocation half — the positioning policy,
    the committee reader (scoped to *this* job's run and product), and the ``Positioner`` itself
    (which takes its policy at construction) — is built inside :meth:`invoke`.
    """

    gateway: LLMGateway
    judge: FaithfulnessJudge | None
    retriever: ClientKnowledgeRetriever
    conn_factory: ConnFactory = transaction


class SynthesizeValueNarrativeInput(ToolInput):
    job_id: str


class NarrativeRefOutput(ToolOutput):
    """One produced narrative, by reference.

    Every leaf is a plain JSON scalar on purpose: a stored result is re-validated against this
    strict model on every journal replay, and a ``UUID``/``datetime`` leaf would round-trip out as a
    string and fail that second pass.
    """

    claim_id: str
    persona: str
    angle_label: str
    judge_verdict: str | None


class CoverageGapOutput(ToolOutput):
    """A persona the committee had, for which no argument could be grounded."""

    persona: str
    reason: str


class SynthesizeValueNarrativeOutput(ToolOutput):
    job_id: str
    #: ``written`` | ``committee_unavailable`` | ``no_narratives``.
    outcome: str
    committee_size: int
    narratives: list[NarrativeRefOutput]
    coverage_gaps: list[CoverageGapOutput]


@dataclass(frozen=True, slots=True)
class _ClientContext:
    """The resolved, never-defaulted positioning scope for one job."""

    run: ProjectRunRow
    client_entity_id: EntityId
    client_kb_version: int | None


def _fail(code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=code, message=message),)


def _uuid(raw: str) -> UUID | None:
    try:
        return UUID(raw)
    except (TypeError, ValueError, AttributeError):
        return None


class SynthesizeValueNarrativeTool(Tool):
    name = "synthesize_value_narrative"
    version = "1"
    model_description = (
        "Synthesize the per-persona value narrative for an account whose research job has already "
        "finalized as completed or needs_review, writing one evidence-backed claim per buying "
        "committee persona. It never researches and never invents scope: the account, product, "
        "ICP pin and client knowledge base are all read from durable rows, and it refuses rather "
        "than positioning an account with no resolvable committee."
    )
    input_model: ClassVar[type[ToolInput]] = SynthesizeValueNarrativeInput
    output_model: ClassVar[type[ToolOutput]] = SynthesizeValueNarrativeOutput
    effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity=(
            "tool_invocation.operation_id derived from (job_id, account.value_narrative); each "
            "narrative supersedes the prior live one for its (persona, icp, product, project)"
        ),
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
        notes=(
            "One job is one narrative RUN, so a crash between the last synthesis and the "
            "invocation receipt may repeat up to N LLM calls — one per committee persona — where "
            "E1's prose synthesis repeats one; the per-persona supersede makes the whole run "
            "converge either way, so at most one live narrative per persona survives."
        ),
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("job_id",))
    pin_requirements = ("entity_research_job",)

    def __init__(
        self,
        *,
        services: ValueNarrativeServices | None,
        gateway: LLMGateway | None,
        conn_factory: ConnFactory = transaction,
        jobs: EntityResearchJobReader | None = None,
        context: NarrativeContextReader | None = None,
        sink: MetricSink | None = None,
    ) -> None:
        self._services = services
        self._gateway = gateway
        self._conn_factory = conn_factory
        self._jobs = jobs or DbEntityResearchJobStore(conn_factory=conn_factory)
        self._context = context or DbNarrativeContextReader(conn_factory=conn_factory)
        self._sink = sink

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, SynthesizeValueNarrativeInput)
        if self._services is None:
            return _fail(
                "value_narrative_not_composed",
                "the Lane E positioning services are not composed in this process",
            )
        job = await self._load_job(inputs.job_id, ctx)
        if job is None:
            return _fail("job_not_found", "no such entity research job")
        if job.state is not ResearchJobState.TERMINAL:
            return _fail("job_not_terminal", "entity research job has not finalized")
        if job.finalization_outcome not in SYNTHESIZABLE_OUTCOMES:
            return _fail(
                "outcome_not_synthesizable",
                "only a completed or needs_review research outcome may be positioned",
            )
        if job.subject_type is not ResearchSubjectType.ACCOUNT:
            return _fail(
                "not_an_account_job",
                "the value narrative is keyed on (account, persona); a contact job has no "
                "committee to position",
            )
        if job.project_run_id is None:
            return _fail(
                "project_run_unresolved",
                "the job carries no project run, so the ICP pin and product scope are unknown",
            )
        if job.product_id is None:
            # `account.value_narrative` is an `exact_required` product route: a product-less claim
            # is invisible to every reader, so writing one would be paid-for shelf-ware.
            return _fail(
                "product_context_unresolved",
                "a value narrative must be written for an exact product",
            )
        _context, refusal = await self._resolve_client_context(job)
        if refusal is not None:
            return refusal
        if self._gateway is None:
            return _fail(
                "gateway_required",
                "value narrative synthesis requires a configured LLM gateway",
            )
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        # One completion (plus at most one judge call) per committee persona; the committee size is
        # not knowable without the reads `invoke` does, and the real cost is stamped on each claim
        # from the gateway's own accounting, so the prior stays a static basis.
        return ToolEstimate(
            cost_cents=Decimal(0),
            detail={"basis": "value_narrative_completion_per_persona"},
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, SynthesizeValueNarrativeInput)
        services = self._services
        assert services is not None
        job = await self._load_job(inputs.job_id, ctx)
        if job is None or job.project_run_id is None or job.product_id is None:
            raise RuntimeError("value narrative synthesis lost its job scope after preconditions")
        context, refusal = await self._resolve_client_context(job)
        if context is None:
            raise RuntimeError(
                "value narrative synthesis lost its client context after preconditions: "
                f"{refusal[0].reason_code if refusal else 'unknown'}"
            )

        async with self._conn_factory() as conn:
            policy = await load_positioning_policy(conn, workspace_id=job.workspace_id)

        # Scoped to *this* job's run and product: membership comes from the run's own references,
        # and a claim stamped for another product can never enter this product's narrative.
        committee_reader = ProductionHandoffCommitteeReader(
            ContactEligibilityResolver(
                project_run_id=ProjectRunId(job.project_run_id),
                product_id=job.product_id,
                conn_factory=self._conn_factory,
            )
        )
        account = EntityId(job.subject_entity_id)
        # The probe. `position()` over an empty committee is a silent no-op (zero narratives AND
        # zero gaps), so the emptiness is caught here and reported as its own outcome — before any
        # spend, and without the positioner ever being constructed.
        committee = await committee_reader.committee_for(
            account_entity_id=account, workspace_id=job.workspace_id
        )
        if not committee:
            log.info(
                "value_narrative.committee_unavailable",
                job_id=str(job.job_id),
                workspace_id=job.workspace_id,
                account_entity_id=str(account),
            )
            self._emit(METRIC_COMMITTEE_UNAVAILABLE, {})
            return self._result(
                job.job_id,
                outcome=OUTCOME_COMMITTEE_UNAVAILABLE,
                committee_size=0,
                result=None,
            )

        positioner = Positioner(
            gateway=services.gateway,
            retriever=services.retriever,
            committee_reader=committee_reader,
            judge=services.judge,
            policy=policy,
            conn_factory=services.conn_factory,
            sink=self._sink,
        )
        result = await positioner.position(
            account,
            icp_spec_version=context.run.icp_version,
            workspace_id=job.workspace_id,
            client_entity_id=context.client_entity_id,
            run_id=RunId(job.research_run_id),
            icp_key=context.run.icp_key,
            kb_version=context.client_kb_version,
            product_id=job.product_id,
            project_id=job.project_id,
        )
        self._emit(METRIC_NARRATIVES_PRODUCED, {"personas": str(len(result.narratives))})
        if result.coverage_gaps:
            self._emit(METRIC_COVERAGE_GAPS, {"personas": str(len(result.coverage_gaps))})
        return self._result(
            job.job_id,
            outcome=OUTCOME_WRITTEN if result.narratives else OUTCOME_NO_NARRATIVES,
            committee_size=len(committee),
            result=result,
        )

    def _result(
        self,
        job_id: UUID,
        *,
        outcome: str,
        committee_size: int,
        result: PositioningResult | None,
    ) -> ToolResult:
        narratives = () if result is None else result.narratives
        gaps = () if result is None else result.coverage_gaps
        output = SynthesizeValueNarrativeOutput(
            job_id=str(job_id),
            outcome=outcome,
            committee_size=committee_size,
            narratives=[
                NarrativeRefOutput(
                    claim_id=str(ref.claim_id),
                    persona=ref.persona.value,
                    angle_label=ref.angle_label,
                    judge_verdict=ref.judge_verdict,
                )
                for ref in narratives
            ],
            coverage_gaps=[
                CoverageGapOutput(persona=gap.persona.value, reason=gap.reason) for gap in gaps
            ],
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references=output.model_dump(mode="json"),
        )

    async def _resolve_client_context(
        self, job: EntityResearchJobRow
    ) -> tuple[_ClientContext | None, tuple[PreconditionFailure, ...] | None]:
        """Resolve the run's ICP pin and the client lineage behind it, or say which leg is missing.

        The RUN's pinned ``(icp_key, icp_version)`` is authoritative — never ``get_active_icp``:
        under D5 multi-ICP a run must stay reproducible against the segment it was started for, and
        a newer active ICP would silently re-point the argument.

        The client legs sit on the ``project_run`` only for a Stage-0-confirmed run entry; every
        other run leaves them null and the C4-confirmed lineage on the pinned ICP version is what
        answers (that lineage is all-or-none validated at the model, so a resolved
        ``client_entity_id`` brings its ``client_kb_version`` with it).
        """
        if job.project_run_id is None:
            return None, _fail(
                "project_run_unresolved",
                "the job carries no project run",
            )
        run = await self._context.get_project_run(ProjectRunId(job.project_run_id))
        if run is None:
            return None, _fail(
                "project_run_unresolved",
                "the job's project run no longer exists",
            )
        if run.client_entity_id is not None:
            return (
                _ClientContext(
                    run=run,
                    client_entity_id=run.client_entity_id,
                    client_kb_version=run.client_kb_version,
                ),
                None,
            )
        spec = await self._context.get_icp_version(
            workspace_id=run.workspace_id, icp_key=run.icp_key, version=run.icp_version
        )
        if spec is None or spec.client_entity_id is None:
            return None, _fail(
                "client_context_unresolved",
                "neither the project run nor its pinned ICP version names a client knowledge base",
            )
        return (
            _ClientContext(
                run=run,
                client_entity_id=spec.client_entity_id,
                client_kb_version=spec.client_kb_version,
            ),
            None,
        )

    async def _load_job(self, raw_id: str, ctx: ToolContext) -> EntityResearchJobRow | None:
        """Fail-closed job→workspace guard (the E1 posture, verbatim): a missing, malformed, or
        other-workspace job all resolve to ``None``, so a cross-tenant id is indistinguishable from
        a non-existent one."""
        job_id = _uuid(raw_id)
        job = await self._jobs.get_job(job_id) if job_id is not None else None
        if job is None or job.workspace_id != ctx.workspace_id:
            log.warning(
                "toolbelt.account_scope_refused",
                tool=self.name,
                actor=ctx.actor,
                workspace_id=ctx.workspace_id,
                job_id=raw_id,
            )
            return None
        return job

    def _emit(self, metric: str, attributes: dict[str, str]) -> None:
        sink = self._sink or get_metric_sink()
        sink.add(metric, 1, attributes)


def build_value_narrative_tools(
    services: ValueNarrativeServices | None,
    *,
    gateway: LLMGateway | None,
    conn_factory: ConnFactory = transaction,
) -> tuple[Tool, ...]:
    return (
        SynthesizeValueNarrativeTool(
            services=services,
            gateway=gateway,
            conn_factory=conn_factory,
        ),
    )


__all__ = [
    "METRIC_COMMITTEE_UNAVAILABLE",
    "METRIC_COVERAGE_GAPS",
    "METRIC_NARRATIVES_PRODUCED",
    "OUTCOME_COMMITTEE_UNAVAILABLE",
    "OUTCOME_NO_NARRATIVES",
    "OUTCOME_WRITTEN",
    "SYNTHESIZABLE_OUTCOMES",
    "CoverageGapOutput",
    "DbNarrativeContextReader",
    "NarrativeContextReader",
    "NarrativeRefOutput",
    "SynthesizeValueNarrativeInput",
    "SynthesizeValueNarrativeOutput",
    "SynthesizeValueNarrativeTool",
    "ValueNarrativeServices",
    "build_value_narrative_tools",
]

"""Lane E E1 — the governed ``synthesize_entity_prose@1`` tool.

The on-completion prose synthesis is a **spend** that writes a tier-4 claim, so it does not hang
off a fleet handler as a direct method call: it goes through the toolbelt like every other governed
capability, which is what gives it an invocation journal entry, the A9 idempotency collapse, the
pre/post envelope, and a single reviewable authority decision
(:data:`~clue_api.agent_registry_wiring.C6_AGENT_TOOL_AUTHORITY`). In E1 the only caller is the
machine (:class:`~clue_api.prose_synthesis_step.ProseSynthesisStep`); the authority tuple is
therefore empty — structurally absent from every model surface.

Everything the synthesis is *about* is read from the durable ``entity_research_job`` row, never
from the caller: the account entity, the research run, the workspace, and the finalization outcome
all come off the job. A caller can only name a job and a field, and both are checked fail-closed.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from typing import ClassVar, Protocol
from uuid import UUID

import structlog

from clue_core import EntityId, LLMGateway, RunId
from clue_core.entity_research import ResearchFinalizationOutcome, ResearchJobState
from clue_db import ConnFactory, transaction
from clue_fleet import DbEntityResearchJobStore
from clue_fleet.entity_research import EntityResearchJobRow
from clue_research.narrative import ACCOUNT_SUMMARY, CONTACT_OVERVIEW, ProseSynthesizer
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

#: The §7-D1 gate. Four of the six terminal outcomes (exhausted / budget_stopped / cancelled /
#: failed) describe research that did *not* reach a defensible picture of the account — prose over
#: them would be a confident summary of a broken pass, so they never synthesize.
SYNTHESIZABLE_OUTCOMES = frozenset(
    {ResearchFinalizationOutcome.COMPLETED, ResearchFinalizationOutcome.NEEDS_REVIEW}
)

#: The registered Lane E prose fields, both composed as of E2. The separate ``field_not_composed``
#: refusal below survives as a per-field check: an unregistered key and an uncomposed one are
#: different mistakes and get different reason codes.
_PROSE_FIELDS = (ACCOUNT_SUMMARY, CONTACT_OVERVIEW)


class EntityResearchJobReader(Protocol):
    """The one job read this tool needs (satisfied structurally by ``DbEntityResearchJobStore``)."""

    async def get_job(self, job_id: UUID) -> EntityResearchJobRow | None: ...


@dataclass(frozen=True, slots=True)
class ProseSynthesisServices:
    """The composed synthesizers, one per prose field species.

    E2 adds the contact overview as a second *field* here rather than a second tool, so the governed
    surface and its authority decision stay singular. Both fields are required: production composes
    one :class:`ProseSynthesizer` instance and passes it as both, and the split exists so the two
    species can later be composed differently (a different policy, model, or judge) — not because
    either is optional.
    """

    account: ProseSynthesizer
    contact: ProseSynthesizer


class SynthesizeEntityProseInput(ToolInput):
    job_id: str
    field_key: str


class SynthesizeEntityProseOutput(ToolOutput):
    """The reference-only result.

    ``support_claim_ids`` is a ``list`` (not the brief's ``tuple``) because :class:`ToolOutput` is
    ``strict=True`` and every result round-trips through JSON — the invocation journal replays a
    stored result by re-validating it, and a JSON array can never satisfy a strict ``tuple`` field.
    Every other typed output in ``tool_outputs.py`` is ``list[str]`` for the same reason.
    """

    job_id: str
    field_key: str
    claim_id: str | None
    support_claim_ids: list[str]
    verification_status: str
    outcome: str
    research_outcome: str


def _fail(code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=code, message=message),)


def _uuid(raw: str) -> UUID | None:
    try:
        return UUID(raw)
    except (TypeError, ValueError, AttributeError):
        return None


class SynthesizeEntityProseTool(Tool):
    name = "synthesize_entity_prose"
    version = "1"
    model_description = (
        "Synthesize the neutral prose summary for an entity whose research job has already "
        "finalized as completed or needs_review, writing it as one evidence-backed claim. It "
        "never researches, never spends on providers, and refuses any job that is not terminal "
        "or whose outcome is not synthesizable."
    )
    input_model: ClassVar[type[ToolInput]] = SynthesizeEntityProseInput
    output_model: ClassVar[type[ToolOutput]] = SynthesizeEntityProseOutput
    effect_class = ToolEffectClass.SPEND
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity=(
            "tool_invocation.operation_id derived from (job_id, field_key); the prose claim "
            "supersedes any prior live summary for the same (entity, field, workspace)"
        ),
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
        notes=(
            "A crash between the synthesis completion and the invocation receipt may repeat one "
            "LLM call; the claim write converges by supersede, so at most one live summary "
            "survives either way."
        ),
    )
    parameter_policy = JournalParameterPolicy(safe_display_fields=("job_id", "field_key"))
    pin_requirements = ("entity_research_job",)

    def __init__(
        self,
        *,
        services: ProseSynthesisServices | None,
        gateway: LLMGateway | None,
        conn_factory: ConnFactory = transaction,
        jobs: EntityResearchJobReader | None = None,
    ) -> None:
        self._services = services
        self._gateway = gateway
        # The real store opens its own short transaction through the injected factory; tests inject
        # a savepoint-scoped one (or a pure double) so a precondition read never escapes the case.
        self._jobs = jobs or DbEntityResearchJobStore(conn_factory=conn_factory)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, SynthesizeEntityProseInput)
        if self._services is None:
            return _fail(
                "prose_synthesis_not_composed",
                "the Lane E prose synthesizers are not composed in this process",
            )
        if inputs.field_key not in _PROSE_FIELDS:
            return _fail("invalid_field_key", "field key is not a Lane E prose field")
        if self._synthesizer_for(inputs.field_key) is None:
            return _fail(
                "field_not_composed",
                f"no synthesizer is composed for {inputs.field_key}",
            )
        job = await self._load_job(inputs.job_id, ctx)
        if job is None:
            return _fail("job_not_found", "no such entity research job")
        if job.state is not ResearchJobState.TERMINAL:
            return _fail("job_not_terminal", "entity research job has not finalized")
        if job.finalization_outcome not in SYNTHESIZABLE_OUTCOMES:
            return _fail(
                "outcome_not_synthesizable",
                "only a completed or needs_review research outcome may be summarized",
            )
        if self._gateway is None:
            return _fail(
                "gateway_required",
                "prose synthesis requires a configured LLM gateway",
            )
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        # One synthesis completion (plus at most one judge call); the real cost is stamped on the
        # claim from the gateway's own accounting, so the pre-spend prior stays a static basis.
        return ToolEstimate(
            cost_cents=Decimal(0),
            detail={"basis": "prose_synthesis_single_completion"},
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, SynthesizeEntityProseInput)
        assert self._services is not None
        job = await self._load_job(inputs.job_id, ctx)
        if job is None or job.finalization_outcome is None:
            raise RuntimeError("prose synthesis lost its entity research job after preconditions")
        # The *field key* selects the species, not the job's subject type: the two are consistent in
        # production (the account lane asks for `account.summary`, the contact lane for
        # `contact.overview`), and reading the field the caller named keeps this branch honest about
        # what was actually requested.
        if inputs.field_key == ACCOUNT_SUMMARY:
            outcome = await self._services.account.synthesize_account_summary(
                account_entity_id=EntityId(job.subject_entity_id),
                workspace_id=job.workspace_id,
                research_run_id=RunId(job.research_run_id),
                job_id=job.job_id,
                research_outcome=job.finalization_outcome.value,
            )
        else:
            # Employer context is optional garnish, and `parent_account_id` is nullable on the job
            # row — a parentless contact synthesizes with less material, never a refusal.
            parent = job.parent_account_id
            outcome = await self._services.contact.synthesize_contact_overview(
                contact_entity_id=EntityId(job.subject_entity_id),
                workspace_id=job.workspace_id,
                research_run_id=RunId(job.research_run_id),
                job_id=job.job_id,
                research_outcome=job.finalization_outcome.value,
                parent_account_id=None if parent is None else EntityId(parent),
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "job_id": str(job.job_id),
                "field_key": inputs.field_key,
                "claim_id": None if outcome.claim_id is None else str(outcome.claim_id),
                "support_claim_ids": [str(item) for item in outcome.support_claim_ids],
                "verification_status": outcome.verification_status,
                "outcome": outcome.kind,
                "research_outcome": job.finalization_outcome.value,
            },
        )

    def _synthesizer_for(self, field_key: str) -> ProseSynthesizer | None:
        """Per-field composition, so a partially composed services object refuses only its own
        missing species. Both dataclass fields are required, so this is unreachable from the
        production composition — it stays because "composed" is a property of a *field*, and a
        blanket refusal keyed on the field name would go stale the moment a third species lands."""
        if self._services is None:
            return None
        return self._services.account if field_key == ACCOUNT_SUMMARY else self._services.contact

    async def _load_job(self, raw_id: str, ctx: ToolContext) -> EntityResearchJobRow | None:
        """Fail-closed job→workspace guard: a missing, malformed, or other-workspace job all
        resolve to ``None``, so the caller surfaces one ``job_not_found`` refusal and a
        cross-tenant id is indistinguishable from a non-existent one (no existence leak) — the
        same posture as the toolbelt's account guard. Refusals are WARNING-logged."""
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


def build_prose_synthesis_tools(
    services: ProseSynthesisServices | None,
    *,
    gateway: LLMGateway | None,
    conn_factory: ConnFactory = transaction,
) -> tuple[Tool, ...]:
    return (
        SynthesizeEntityProseTool(
            services=services,
            gateway=gateway,
            conn_factory=conn_factory,
        ),
    )


__all__ = [
    "SYNTHESIZABLE_OUTCOMES",
    "EntityResearchJobReader",
    "ProseSynthesisServices",
    "SynthesizeEntityProseInput",
    "SynthesizeEntityProseOutput",
    "SynthesizeEntityProseTool",
    "build_prose_synthesis_tools",
]

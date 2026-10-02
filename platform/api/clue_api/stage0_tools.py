"""C4's seven governed Stage-0 tools; all business logic delegates to Stage-0 services."""

from __future__ import annotations

import hashlib
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from decimal import Decimal
from typing import cast
from uuid import UUID

from pydantic import Field, JsonValue
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_agents.manual import tool_manual_link
from clue_api.auth_tool_context import require_human_authority
from clue_api.conversation_capture import project_client_entity_id
from clue_api.project_execution_router import ProjectExecutionRouter
from clue_api.stage0_field_events import ReconFieldProgressEmitter
from clue_api.tool_outputs import (
    ConfirmedProjectRunOutput,
    InterviewAnswerOutput,
    OnboardingInputOutput,
    ProjectProductOutput,
    ReconOutput,
    Stage0OverrideOutput,
    Stage0ReadinessOutput,
)
from clue_api.turn_binding import TRUSTED_TURN_FIELD
from clue_config import DEFAULT_STAGE0_POLICY, Stage0Policy
from clue_core import (
    RECON_TRANSITION_KIND,
    AccountEntity,
    EntityId,
    ICPStatus,
    MemoryWriteSeam,
    OnboardingInputId,
    OnboardingInputKind,
    PreSpendGate,
    ProductContextVersionId,
    ProjectPhase,
    ProjectRunId,
    ReadinessDecisionId,
    ReadinessGate,
    ReadinessVerdict,
    ReconRunId,
    RunEventTopic,
    RunId,
)
from clue_db import ConnFactory, transaction
from clue_execution.run_events import emit_run_event
from clue_obs import get_logger
from clue_research.durable import (
    ProjectRunStatus,
    ensure_project_run,
    get_project_run,
)
from clue_research.icp import get_icp_version
from clue_research.stage0 import (
    CLIENT_ONBOARDING_FIELDS,
    ClaimEntailmentJudge,
    ClientInput,
    InterviewClaimEntityRefused,
    InterviewEvidenceRefused,
    InterviewStatement,
    ReconLaneStatus,
    compile_product_context,
    ensure_product_kb_baseline,
    evaluate_readiness,
    get_onboarding_input,
    get_readiness_decision,
    judge_interview_values,
    override_readiness,
    prepare_interview_statements,
    recon_dedupe_hash,
    reverse_profile,
    route_interview_answer,
    start_recon,
    submit_onboarding_input,
    transition_recon_lane,
)
from clue_spine import confirm_project_product, get_brand, get_product, get_project
from clue_storage import SnapshotSink, StorageBackend, bind_snapshots, get_artifact
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
    ToolResult,
)

MemoryWriteFactory = Callable[[AsyncConnection], MemoryWriteSeam]
log = get_logger("clue_api.stage0_tools")


def _failure(code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=code, message=message),)


def _uuid(raw: str) -> UUID | None:
    try:
        return UUID(raw)
    except (TypeError, ValueError, AttributeError):
        return None


async def _emit_recon_transition(
    conn: AsyncConnection,
    *,
    recon_run_id: UUID,
    workspace_id: str,
    lane: str,
    status: ReconLaneStatus,
    budget_exhausted: bool | None = None,
) -> None:
    """Append exactly one event in the same transaction as one actual lane transition.

    ``budget_exhausted`` rides the terminal COMPLETED event only: a lane that stopped at its
    cap "completed" with fields it never reached, and the progress surface must be able to say
    so rather than presenting a truncated run as full coverage."""
    payload: dict[str, JsonValue] = {
        "kind": RECON_TRANSITION_KIND,
        "recon_run_id": str(recon_run_id),
        "lane": lane,
        "status": status.value,
    }
    if budget_exhausted is not None:
        payload["budget_exhausted"] = budget_exhausted
    await emit_run_event(
        conn,
        workspace_id=workspace_id,
        run_id=ProjectRunId(recon_run_id),
        topic=RunEventTopic.STEP_PROGRESS.value,
        payload=payload,
    )


async def start_confirmed_project_run(
    conn: AsyncConnection,
    *,
    project_run_id: ProjectRunId,
    workspace_id: str,
    project_id: str,
    client_entity_id: EntityId,
    client_kb_version: int,
    product_id: str,
    product_context_version_id: ProductContextVersionId,
    readiness_decision_id: ReadinessDecisionId,
    icp_key: str,
    icp_version: int,
    budget_cap_cents: Decimal | None = None,
) -> ProjectRunId:
    """API-root proof joining Stage 0, ICP, spine, and durable run machinery."""
    project = await get_project(conn, project_id)
    if project is None or project.workspace_id != workspace_id or project.product_id != product_id:
        raise ValueError("project does not carry the requested confirmed product")
    spec = await get_icp_version(conn, workspace_id, icp_key, icp_version)
    if spec is None or (
        spec.status is not ICPStatus.ACTIVE
        or spec.client_entity_id != client_entity_id
        or spec.client_kb_version != client_kb_version
        or spec.product_id != product_id
    ):
        raise ValueError("ICP does not carry the requested Client-KB/product lineage")
    context_exists = (
        await conn.execute(
            text(
                """
                SELECT 1
                FROM product_context_version
                WHERE id = :id
                  AND workspace_id = :workspace_id
                  AND brand_id = :brand_id
                  AND product_id = :product_id
                  AND client_entity_id = :client_entity_id
                  AND client_kb_version = :client_kb_version
                """
            ),
            {
                "id": product_context_version_id,
                "workspace_id": workspace_id,
                "brand_id": project.brand_id,
                "product_id": product_id,
                "client_entity_id": client_entity_id,
                "client_kb_version": client_kb_version,
            },
        )
    ).scalar_one_or_none()
    if context_exists is None:
        raise ValueError("product context does not carry the requested Client-KB/product lineage")
    decision = await get_readiness_decision(conn, readiness_decision_id, workspace_id=workspace_id)
    if decision is None or (
        decision.project_id != project_id
        or decision.product_id != product_id
        or decision.client_entity_id != client_entity_id
        or decision.client_kb_version != client_kb_version
        or decision.icp_key != icp_key
        or decision.icp_version != icp_version
        or decision.product_context_version_id != product_context_version_id
        or decision.gate is not ReadinessGate.DISCOVERY_SPEND
    ):
        raise ValueError("readiness decision does not pin the requested confirmed context")
    overridden = (
        await conn.execute(
            text(
                "SELECT 1 FROM readiness_override "
                "WHERE readiness_decision_id = :id AND workspace_id = :workspace_id"
            ),
            {"id": readiness_decision_id, "workspace_id": workspace_id},
        )
    ).scalar_one_or_none()
    if decision.verdict is not ReadinessVerdict.READY and overridden is None:
        raise ValueError("discovery readiness is not ready and has no human override")
    await ensure_project_run(
        conn,
        project_run_id=project_run_id,
        project_id=project_id,
        workspace_id=workspace_id,
        icp_key=icp_key,
        icp_version=icp_version,
        budget_cap_cents=budget_cap_cents,
        phase=ProjectPhase.DISCOVERY,
        status=ProjectRunStatus.ACTIVE,
        client_entity_id=client_entity_id,
        client_kb_version=client_kb_version,
        product_id=product_id,
        product_context_version_id=product_context_version_id,
        readiness_decision_id=readiness_decision_id,
    )
    run = await get_project_run(conn, project_run_id)
    if run is None:  # pragma: no cover - same-transaction invariant
        raise ValueError("confirmed project run vanished after insertion")
    expected_lineage = (
        project_id,
        workspace_id,
        icp_key,
        icp_version,
        client_entity_id,
        client_kb_version,
        product_id,
        product_context_version_id,
        readiness_decision_id,
        budget_cap_cents,
    )
    actual_lineage = (
        run.project_id,
        run.workspace_id,
        run.icp_key,
        run.icp_version,
        run.client_entity_id,
        run.client_kb_version,
        run.product_id,
        run.product_context_version_id,
        run.readiness_decision_id,
        run.budget_cap_cents,
    )
    if actual_lineage != expected_lineage:
        raise ValueError("confirmed project run id already belongs to different immutable lineage")
    if tuple(ProjectPhase).index(run.phase) < tuple(ProjectPhase).index(ProjectPhase.DISCOVERY):
        raise ValueError("confirmed project run has not reached its discovery entry phase")
    return project_run_id


# NOTE (PC-C8 §6a, tasks 1.3 + 1.4): `brand_id` and `client_entity_id` joined `project_id` in
# `MODEL_FORBIDDEN_AUTHORITY_KEYS`, so on every input model below they are stripped from the
# model-visible schema and served from the `AgentConstitution` at the execution seam. They stay
# declared because the C4 recipe path supplies them directly.
#
# Task 1.3 deliberately left their `description` text stale — it is part of `model_json_schema()`
# and therefore of the tool's pinned `input_schema_sha256`, so rewording it would have forced a
# second catalog bump for text no model reads. Task 1.4's coordinated bump (skill
# `stage0-interview/v7`, profile `head-of-abm/v9`) does the reword: all eight descriptions that
# described a field the model fills now state the same thing `project_id` always did — the
# platform supplies it. (`confirm_icp`, `import_accounts` and `synthesize_icps` declare
# `client_entity_id` with no description at all; nothing to reword there, and adding one would
# move their digests for no model-visible gain.)


class SubmitOnboardingInput(ToolInput):
    brand_id: str = Field(
        description="Trusted brand authority; supplied by the platform, never by you."
    )
    kind: OnboardingInputKind = Field(
        description=(
            "What was captured: a live human turn is `user_turn`, a supplied page is `website`, "
            "an uploaded file is `upload`."
        )
    )
    artifact_key: str = Field(
        description=(
            "Storage key of an artifact already captured in this workspace; an absent or foreign "
            "key is refused (`artifact_not_found`). Capture happens outside you, so use a key you "
            "were given rather than inventing one."
        )
    )
    content_sha256: str = Field(
        description=(
            "Hex SHA-256 of the exact captured bytes. It is stored immutably and re-checked "
            "later: `record_interview_answer` refuses an `answer` that does not hash to it."
        )
    )
    product_id: str | None = Field(
        default=None,
        description="Confirmed product this input belongs to, when the project has one.",
    )
    project_id: str | None = Field(
        default=None,
        description="Trusted project authority; supplied by the platform, never by you.",
    )
    client_entity_id: str | None = Field(
        default=None,
        description="Trusted client-entity authority; supplied by the platform, never by you.",
    )
    source_ref: str | None = Field(
        default=None,
        description="Where the input came from (URL, filename, or channel), for the audit trail.",
    )


class StartReconInput(ToolInput):
    brand_id: str = Field(
        description="Trusted brand authority; supplied by the platform, never by you."
    )
    name: str = Field(
        description="Client company name exactly as the human gave it; not an expansion of yours."
    )
    website: str = Field(
        description=(
            "The client's official website URL. Recon reads official surfaces only, so a guessed "
            "domain produces wrong Client-KB claims rather than an error."
        )
    )
    onboarding_input_ids: list[str] = Field(
        description=(
            "At least one onboarding input id captured in this workspace; an empty list, a "
            "malformed id, or a foreign id is refused (`onboarding_input_not_found`). These pin "
            "the captured evidence this recon is grounded in."
        )
    )
    product_id: str | None = Field(
        default=None, description="Confirmed product this recon profiles for, when one exists."
    )
    project_id: str | None = Field(
        default=None,
        description="Trusted project authority; supplied by the platform, never by you.",
    )


class RecordInterviewAnswerInput(ToolInput):
    """Route one captured turn. The model classifies; the platform supplies the turn itself.

    ``onboarding_input_id``, ``artifact_key`` and ``answer`` are trusted turn authority (PC-C8
    §6a): they are stripped from the model-visible schema and served at the execution seam from
    the binding compiled off this turn's own artifact and capture record
    (:mod:`clue_api.turn_binding`). They stay declared here because the C4 recipe path supplies
    them directly — only the *agent* surface loses them.
    """

    brand_id: str = Field(
        description="Trusted brand authority; supplied by the platform, never by you."
    )
    onboarding_input_id: str = Field(
        json_schema_extra={TRUSTED_TURN_FIELD: True},
        description=(
            "The onboarding input that captured this turn. Trusted turn authority: supplied by "
            "the platform from the captured turn, never by you. It must exist in this workspace "
            "and carry the same `artifact_key`."
        ),
    )
    artifact_key: str = Field(
        json_schema_extra={TRUSTED_TURN_FIELD: True},
        description=(
            "Artifact key of that captured turn — the same key the onboarding input carries. "
            "Trusted turn authority: supplied by the platform, never by you."
        ),
    )
    answer: str = Field(
        json_schema_extra={TRUSTED_TURN_FIELD: True},
        description=(
            "The captured user message, byte-identical. Trusted turn authority: the platform "
            "loads these exact bytes from the captured artifact and verifies their SHA-256 "
            "against the onboarding input's `content_sha256`, so there is nothing here for you "
            "to retype. Every statement's quote offsets index into this exact string."
        ),
    )
    client_entity_id: str = Field(
        description="Trusted client-entity authority; supplied by the platform, never by you."
    )
    statements: list[InterviewStatement] = Field(
        description=(
            "One statement per material fact, preference, or project decision in the answer, each "
            "carrying its own exact quote offsets. A turn with nothing material is routed as one "
            "`unmapped` statement — routing nothing is never the honest answer."
        )
    )
    product_id: str | None = Field(
        default=None, description="Confirmed product this answer is about, when one exists."
    )
    project_id: str | None = Field(
        default=None,
        description="Trusted project authority; supplied by the platform, never by you.",
    )


class ConfirmProjectProductInput(ToolInput):
    project_id: str = Field(
        description="Project whose product is being confirmed; human-only (`human_required`)."
    )
    product_id: str = Field(
        description=(
            "Product to bind to the project; both must exist in this workspace and share one "
            "brand. The binding is immutable once made."
        )
    )


class EvaluateStage0ReadinessInput(ToolInput):
    brand_id: str = Field(
        description="Trusted brand authority; supplied by the platform, never by you."
    )
    gate: ReadinessGate = Field(
        description=(
            "Which floor to evaluate. `start_confirmed_project_run` accepts only a "
            "`discovery_spend` decision."
        )
    )
    metrics: dict[str, JsonValue] = Field(
        description=(
            "Measured evidence, never estimates. The floor reads exactly `coverage_ratio` "
            "(number), `verified_claims` (integer), `open_policy_blocks` (integer), and "
            "`available_field_keys` (list of registered field keys); an absent key counts as "
            "zero/empty. A number you inflate records a false readiness decision — it does not "
            "make the gate pass honestly."
        )
    )
    product_id: str | None = Field(
        default=None,
        description=(
            "Confirmed product. Gates that require a product report `product_not_confirmed` "
            "while this is absent."
        ),
    )
    project_id: str | None = Field(
        default=None,
        description="Trusted project authority; supplied by the platform, never by you.",
    )
    client_entity_id: str | None = Field(
        default=None,
        description="Trusted client-entity authority; supplied by the platform, never by you.",
    )
    client_kb_version: int | None = Field(
        default=None,
        description=(
            "Client-KB version the decision is made against; part of the lineage a confirmed run "
            "re-checks, so pin the version you actually read."
        ),
    )
    icp_key: str | None = Field(
        default=None,
        description=(
            "Confirmed ICP key. Gates that require an ICP report `icp_not_confirmed` while this "
            "or `icp_version` is absent."
        ),
    )
    icp_version: int | None = Field(
        default=None, description="Confirmed ICP version that goes with `icp_key`."
    )
    product_context_version_id: str | None = Field(
        default=None,
        description=(
            "Existing compiled product-context version. Leave it out to compile a new one from "
            "the refs below (needs product, client entity, and Client-KB version)."
        ),
    )
    claim_refs: list[str] = Field(
        default=[],
        description="Claim ids that evidence this readiness; compiled into the product context.",
    )
    memory_refs: list[str] = Field(
        default=[],
        description="Memory ids that inform this readiness; compiled into the product context.",
    )
    artifact_refs: list[str] = Field(
        default=[],
        description="Artifact keys backing this readiness; compiled into the product context.",
    )
    gap_refs: list[dict[str, JsonValue]] = Field(
        default=[],
        description="Named open gaps recorded on the decision; they do not change the verdict.",
    )
    field_proposal_refs: list[str] = Field(
        default=[],
        description="Open `propose_field` references; a proposal grants no promotion authority.",
    )
    source_proposal_refs: list[str] = Field(
        default=[],
        description="Open `propose_source` references; a proposal grants no trust authority.",
    )
    ingestion_refs: list[str] = Field(
        default=[], description="`submit_ingestion` references recorded on this decision."
    )
    agent_sufficiency_status: str = Field(
        default="not_evaluated",
        description=(
            "Your advisory judgment: `not_evaluated`, `sufficient`, or `insufficient`. Advisory "
            "only — `insufficient` adds a not-ready reason, but this field can never turn a "
            "failing deterministic floor into ready."
        ),
    )
    agent_sufficiency_ref: str | None = Field(
        default=None, description="Reference backing that advisory judgment, when you have one."
    )


class OverrideStage0ReadinessInput(ToolInput):
    readiness_decision_id: str = Field(
        description=(
            "The not-ready decision being overridden; it must exist in this workspace. Human-only "
            "(`human_required`)."
        )
    )
    gate: ReadinessGate = Field(
        description="Gate of that decision; a mismatch is refused (`readiness_not_found`)."
    )
    reason: str = Field(
        description="The human's durable justification for proceeding without a ready verdict."
    )


class StartConfirmedProjectRunInput(ToolInput):
    project_id: str = Field(
        description="Trusted project authority; supplied by the platform, never by you."
    )
    client_entity_id: str = Field(
        description="Trusted client-entity authority; supplied by the platform, never by you."
    )
    client_kb_version: int = Field(
        description=(
            "Client-KB version of that lineage; the ICP, product context, and readiness decision "
            "must all carry this exact version."
        )
    )
    product_id: str = Field(
        description=(
            "Confirmed product; the project must already carry it (a human confirms it through "
            "`confirm_project_product`)."
        )
    )
    product_context_version_id: str = Field(
        description=(
            "Compiled product-context version carrying this brand, product, client entity, and "
            "Client-KB version; a context outside that lineage is refused."
        )
    )
    readiness_decision_id: str = Field(
        description=(
            "A `discovery_spend` readiness decision pinning this exact lineage whose verdict is "
            "ready, or which carries a durable human override. Anything else is refused — report "
            "the refusal rather than restating the call."
        )
    )
    icp_key: str = Field(
        description=(
            "Confirmed ICP key whose spec carries this client entity, Client-KB version, and "
            "product; an ICP outside that lineage is refused."
        )
    )
    icp_version: int = Field(
        description="Confirmed ICP version that goes with `icp_key`, in the same lineage."
    )
    budget_cap_cents: int | None = Field(
        default=None, description="Optional hard spend cap, in cents, for the whole run."
    )


class _Stage0Tool(Tool):
    def __init__(
        self,
        *,
        conn_factory: ConnFactory = transaction,
        policy: Stage0Policy = DEFAULT_STAGE0_POLICY,
        pre_spend_gate: PreSpendGate,
        memory_write: MemoryWriteSeam | None = None,
        memory_write_factory: MemoryWriteFactory | None = None,
        scrape_binder: Callable[[AccountEntity], None] | None = None,
        storage: StorageBackend | None = None,
        project_execution_router: ProjectExecutionRouter | None = None,
        entailment_judge: ClaimEntailmentJudge | None = None,
        field_progress_factory: ConnFactory | None = None,
    ) -> None:
        self._conn_factory = conn_factory
        self._policy = policy
        self._pre_spend_gate = pre_spend_gate
        self._memory_write = memory_write
        self._memory_write_factory = memory_write_factory
        self._scrape_binder = scrape_binder
        self._storage = storage
        self._project_execution_router = project_execution_router
        # Recon field progress commits on its own connection only when a factory is injected
        # (production: `clue_db.transaction`, so a poller sees motion mid-lane). Default None
        # keeps the events on the lane's own connection — the only shape that is safe under a
        # single-connection / lock-guarded test factory, which an autonomous checkout deadlocks.
        self._field_progress_factory = field_progress_factory
        self._entailment_judge = entailment_judge

    def _gate_for_connection(self, conn: AsyncConnection) -> PreSpendGate:
        """Bind transaction-aware gates to the lane's caller-owned connection.

        ``reverse_profile`` creates the Stage-0 client identity inside the lane transaction. A
        production pre-spend gate that opens a second transaction cannot see that uncommitted row
        and rejects every legitimate source call. Concrete gates expose ``with_conn_factory`` for
        exactly this atomic-admission case; keep the milestone boundary protocol-only by detecting
        that optional capability rather than importing the M9 implementation here.
        """
        rebind = getattr(self._pre_spend_gate, "with_conn_factory", None)
        if not callable(rebind):
            return self._pre_spend_gate

        @asynccontextmanager
        async def lane_connection() -> AsyncIterator[AsyncConnection]:
            yield conn

        return cast(PreSpendGate, rebind(lane_connection))

    async def _project_audit_snapshot(self, project_id: str, ctx: ToolContext) -> dict[str, object]:
        async with self._conn_factory() as conn:
            project = await get_project(conn, project_id)
        if project is None or project.workspace_id != ctx.workspace_id:
            return {"project_id": project_id, "exists": False}
        return {
            "project_id": project.project_id,
            "exists": True,
            "brand_id": project.brand_id,
            "product_id": project.product_id,
        }

    async def _readiness_override_audit_snapshot(
        self, readiness_decision_id: str, ctx: ToolContext
    ) -> dict[str, object]:
        decision_uuid = _uuid(readiness_decision_id)
        if decision_uuid is None:
            return {"readiness_decision_id": readiness_decision_id, "exists": False}
        async with self._conn_factory() as conn:
            decision = await get_readiness_decision(
                conn,
                ReadinessDecisionId(decision_uuid),
                workspace_id=ctx.workspace_id,
            )
            override = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, actor FROM readiness_override "
                            "WHERE readiness_decision_id = :id AND workspace_id = :workspace_id"
                        ),
                        {"id": decision_uuid, "workspace_id": ctx.workspace_id},
                    )
                )
                .mappings()
                .one_or_none()
            )
        return {
            "readiness_decision_id": readiness_decision_id,
            "exists": decision is not None,
            "gate": decision.gate.value if decision is not None else None,
            "verdict": decision.verdict.value if decision is not None else None,
            "overridden": override is not None,
            "override_id": str(override["id"]) if override is not None else None,
            "override_actor": str(override["actor"]) if override is not None else None,
        }


class SubmitOnboardingInputTool(_Stage0Tool):
    name = "submit_onboarding_input"
    input_model = SubmitOnboardingInput
    output_model = OnboardingInputOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="OnboardingInputId(operation_id)",
        operation_id_required=True,
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "brand_id",
            "kind",
            "artifact_key",
            "product_id",
            "project_id",
            "client_entity_id",
            "source_ref",
        )
    )
    pin_requirements = ("artifact_input", "brand", "product", "project")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, SubmitOnboardingInput)
        async with self._conn_factory() as conn:
            artifact = await get_artifact(conn, inputs.artifact_key)
        if artifact is None or artifact.workspace_id != ctx.workspace_id:
            return _failure(
                "artifact_not_found",
                "captured artifact does not exist in this workspace",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, SubmitOnboardingInput)
        entity_uuid = _uuid(inputs.client_entity_id) if inputs.client_entity_id else None
        async with self._conn_factory() as conn:
            ref = await submit_onboarding_input(
                conn,
                workspace_id=ctx.workspace_id,
                brand_id=inputs.brand_id,
                product_id=inputs.product_id,
                project_id=inputs.project_id,
                client_entity_id=EntityId(entity_uuid) if entity_uuid else None,
                kind=inputs.kind,
                artifact_key=inputs.artifact_key,
                content_sha256=inputs.content_sha256,
                source_ref=inputs.source_ref,
                actor=ctx.actor,
                onboarding_input_id=OnboardingInputId(ctx.operation_id),
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "onboarding_input_id": str(ref.onboarding_input_id),
                "artifact_key": ref.artifact_key,
                "kind": ref.kind.value,
            },
        )


class StartReconTool(_Stage0Tool):
    name = "start_recon"
    input_model = StartReconInput
    output_model = ReconOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.AT_LEAST_ONCE,
        durable_identity=(
            "ReconRunId(operation_id) when newly created; a live equivalent recon may be shared"
        ),
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("brand_id", "name", "website", "product_id", "project_id")
    )
    pin_requirements = (
        "artifact_input",
        "field_registry",
        "source_registry",
        "stage0_policy",
        "stage0_skill",
    )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, StartReconInput)
        parsed = [_uuid(item) for item in inputs.onboarding_input_ids]
        if not parsed or any(item is None for item in parsed):
            return _failure("onboarding_input_not_found", "recon requires valid onboarding refs")
        async with self._conn_factory() as conn:
            rows = [
                await get_onboarding_input(
                    conn, OnboardingInputId(item), workspace_id=ctx.workspace_id
                )
                for item in parsed
                if item is not None
            ]
        if any(row is None for row in rows):
            return _failure("onboarding_input_not_found", "an onboarding ref is absent or foreign")
        if self._scrape_binder is None or self._storage is None:
            return _failure(
                "stage0_recon_not_configured",
                "live official-surface scrape composition is not configured",
            )
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate(
            cost_cents=self._policy.fast_budget_cents,
            detail={"background_budget_cents": str(self._policy.background_budget_cents)},
        )

    def _field_progress(
        self, recon_run_id: UUID, ctx: ToolContext, lane: str
    ) -> ReconFieldProgressEmitter:
        """One per-lane progress sink; the emitter itself decides autonomous-vs-lane commit."""
        return ReconFieldProgressEmitter(
            workspace_id=ctx.workspace_id,
            recon_run_id=recon_run_id,
            lane=lane,
            conn_factory=self._field_progress_factory,
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, StartReconInput)
        input_ids = tuple(OnboardingInputId(UUID(item)) for item in inputs.onboarding_input_ids)
        dedupe = recon_dedupe_hash(
            workspace_id=ctx.workspace_id,
            brand_id=inputs.brand_id,
            product_id=inputs.product_id,
            identity=inputs.website,
        )
        async with self._conn_factory() as conn:
            recon = await start_recon(
                conn,
                workspace_id=ctx.workspace_id,
                brand_id=inputs.brand_id,
                product_id=inputs.product_id,
                project_id=inputs.project_id,
                dedupe_hash=dedupe,
                onboarding_input_ids=input_ids,
                fast_budget_cents=self._policy.fast_budget_cents,
                background_budget_cents=self._policy.background_budget_cents,
                dedupe_ttl_seconds=self._policy.recon_dedupe_ttl_seconds,
                recon_run_id=ReconRunId(ctx.operation_id),
            )
            started_fast = recon.fast_status is ReconLaneStatus.QUEUED
            if started_fast:
                recon = await transition_recon_lane(
                    conn,
                    recon_run_id=recon.id,
                    workspace_id=ctx.workspace_id,
                    lane="fast",
                    status=ReconLaneStatus.RUNNING,
                )
                await _emit_recon_transition(
                    conn,
                    recon_run_id=recon.id,
                    workspace_id=ctx.workspace_id,
                    lane="fast",
                    status=ReconLaneStatus.RUNNING,
                )
                budget_exhausted: bool | None = None
                with bind_snapshots(
                    SnapshotSink(workspace_id=ctx.workspace_id),
                    self._storage,
                ):
                    try:
                        async with conn.begin_nested():
                            result = await reverse_profile(
                                conn,
                                ClientInput(name=inputs.name, website=inputs.website),
                                workspace_id=ctx.workspace_id,
                                run_id=recon.fast_run_id,
                                budget_cap_cents=self._policy.fast_budget_cents,
                                pre_spend_gate=self._gate_for_connection(conn),
                                # The fast release boundary is the original eleven-field
                                # onboarding contract. Company catalog navigation is allowed to
                                # arrive later and must never delay entry into the application.
                                company_field_keys=CLIENT_ONBOARDING_FIELDS,
                                max_source_tier=2,
                                on_client_resolved=self._scrape_binder,
                                on_field_progress=self._field_progress(recon.id, ctx, "fast"),
                            )
                    except Exception as exc:  # noqa: BLE001 - persist a durable failed lane
                        log.exception(
                            "stage0.recon_lane_failed",
                            workspace_id=ctx.workspace_id,
                            recon_run_id=str(recon.id),
                            lane="fast",
                            error_type=type(exc).__name__,
                        )
                        recon = await transition_recon_lane(
                            conn,
                            recon_run_id=recon.id,
                            workspace_id=ctx.workspace_id,
                            lane="fast",
                            status=ReconLaneStatus.FAILED,
                            failure_code=type(exc).__name__,
                        )
                    else:
                        budget_exhausted = result.budget_exhausted
                        recon = await transition_recon_lane(
                            conn,
                            recon_run_id=recon.id,
                            workspace_id=ctx.workspace_id,
                            lane="fast",
                            status=ReconLaneStatus.COMPLETED,
                            cost_cents=result.cost_cents,
                            client_kb_version=result.ref.client_kb_version,
                            client_entity_id=result.ref.client_entity_id,
                        )
                await _emit_recon_transition(
                    conn,
                    recon_run_id=recon.id,
                    workspace_id=ctx.workspace_id,
                    lane="fast",
                    status=recon.fast_status,
                    budget_exhausted=budget_exhausted,
                )
            elif recon.background_status in {
                ReconLaneStatus.QUEUED,
                ReconLaneStatus.RUNNING,
            }:
                if recon.background_status is ReconLaneStatus.QUEUED:
                    recon = await transition_recon_lane(
                        conn,
                        recon_run_id=recon.id,
                        workspace_id=ctx.workspace_id,
                        lane="background",
                        status=ReconLaneStatus.RUNNING,
                    )
                    await _emit_recon_transition(
                        conn,
                        recon_run_id=recon.id,
                        workspace_id=ctx.workspace_id,
                        lane="background",
                        status=ReconLaneStatus.RUNNING,
                    )
                budget_exhausted = None
                with bind_snapshots(
                    SnapshotSink(workspace_id=ctx.workspace_id),
                    self._storage,
                ):
                    try:
                        async with conn.begin_nested():
                            result = await reverse_profile(
                                conn,
                                ClientInput(name=inputs.name, website=inputs.website),
                                workspace_id=ctx.workspace_id,
                                run_id=recon.background_run_id,
                                budget_cap_cents=self._policy.background_budget_cents,
                                pre_spend_gate=self._gate_for_connection(conn),
                                max_source_tier=3,
                                on_client_resolved=self._scrape_binder,
                                on_field_progress=self._field_progress(recon.id, ctx, "background"),
                            )
                    except Exception as exc:  # noqa: BLE001 - persist a durable failed lane
                        log.exception(
                            "stage0.recon_lane_failed",
                            workspace_id=ctx.workspace_id,
                            recon_run_id=str(recon.id),
                            lane="background",
                            error_type=type(exc).__name__,
                        )
                        recon = await transition_recon_lane(
                            conn,
                            recon_run_id=recon.id,
                            workspace_id=ctx.workspace_id,
                            lane="background",
                            status=ReconLaneStatus.FAILED,
                            failure_code=type(exc).__name__,
                        )
                    else:
                        budget_exhausted = result.budget_exhausted
                        recon = await transition_recon_lane(
                            conn,
                            recon_run_id=recon.id,
                            workspace_id=ctx.workspace_id,
                            lane="background",
                            status=ReconLaneStatus.COMPLETED,
                            cost_cents=result.cost_cents,
                            client_kb_version=result.ref.client_kb_version,
                            client_entity_id=result.ref.client_entity_id,
                        )
                await _emit_recon_transition(
                    conn,
                    recon_run_id=recon.id,
                    workspace_id=ctx.workspace_id,
                    lane="background",
                    status=recon.background_status,
                    budget_exhausted=budget_exhausted,
                )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "recon_run_id": str(recon.id),
                "client_entity_id": (
                    str(recon.client_entity_id) if recon.client_entity_id is not None else None
                ),
                "fast_client_kb_version": recon.fast_client_kb_version,
                "fast_status": recon.fast_status.value,
                "background_status": recon.background_status.value,
                "background_run_id": str(recon.background_run_id),
            },
        )


class RecordInterviewAnswerTool(_Stage0Tool):
    name = "record_interview_answer"
    # The descriptor's own fallback sentence, stated here so the manual anchor can ride on it.
    # What the tool actually does, route by route, is the chapter this points at.
    model_description = (
        "Invoke exact governed platform tool record_interview_answer@1. "
        + tool_manual_link("record_interview_answer")
    )
    input_model = RecordInterviewAnswerInput
    output_model = InterviewAnswerOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="onboarding input + deterministic statement ids + RunId(operation_id)",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    # The turn-authority fields are deliberately absent: a journal display is a summary of what
    # the *caller* asked for, and since PC-C8 §6a nothing about the turn's identity is asked for —
    # it is served from the binding. The durable receipt still carries them in the full validated
    # body; they just stop being displayed as if the caller had chosen them.
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "brand_id",
            "client_entity_id",
            "product_id",
            "project_id",
        )
    )
    pin_requirements = ("artifact_input", "stage0_skill", "memory_switch")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, RecordInterviewAnswerInput)
        input_uuid = _uuid(inputs.onboarding_input_id)
        client_uuid = _uuid(inputs.client_entity_id)
        if input_uuid is None or client_uuid is None:
            return _failure(
                "onboarding_input_not_found",
                "interview input or client entity is malformed",
            )
        async with self._conn_factory() as conn:
            captured = await get_onboarding_input(
                conn, OnboardingInputId(input_uuid), workspace_id=ctx.workspace_id
            )
            artifact = await get_artifact(conn, inputs.artifact_key)
        if (
            captured is None
            or captured.artifact_key != inputs.artifact_key
            or artifact is None
            or artifact.workspace_id != ctx.workspace_id
            or (
                captured is not None
                and hashlib.sha256(inputs.answer.encode()).hexdigest() != captured.content_sha256
            )
        ):
            return _failure(
                "onboarding_input_not_found",
                "captured interview input does not exist in this workspace",
            )
        if (
            any(statement.route.value == "memory" for statement in inputs.statements)
            and self._memory_write is None
            and self._memory_write_factory is None
        ):
            return _failure(
                "memory_not_configured",
                "memory-routed interview statements require the MemoryWriteSeam",
            )
        # PC-C8 §8 (B1 layer 2) + §6c: every statement's evidence is located, its entity resolved,
        # and its value vouched for before any write — through the *same* function the routing
        # engine runs as its own pass one. That turns what used to be a silent tier downgrade (and,
        # since §6c, a mid-write `ValueError`) into a typed refusal the model can read and act on;
        # `route_interview_answer` still runs the pass independently, so the guarantee does not
        # depend on this precondition being called, and the judge's content-addressed cache means
        # the second run asks no second question.
        try:
            async with self._conn_factory() as conn:
                prepared = await prepare_interview_statements(
                    conn,
                    workspace_id=ctx.workspace_id,
                    answer=inputs.answer,
                    statements=tuple(inputs.statements),
                    client_entity_id=EntityId(client_uuid),
                )
            # Outside the connection scope on purpose: the entailment judge makes a (synchronous,
            # multi-second) gateway call, and no pooled transaction stays open across it.
            await judge_interview_values(
                prepared,
                workspace_id=ctx.workspace_id,
                entailment_judge=self._entailment_judge,
            )
        except (InterviewClaimEntityRefused, InterviewEvidenceRefused) as exc:
            return _failure(exc.reason_code, str(exc))
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, RecordInterviewAnswerInput)
        async with self._conn_factory() as conn:
            memory_write = (
                self._memory_write_factory(conn)
                if self._memory_write_factory is not None
                else self._memory_write
            )
            result = await route_interview_answer(
                conn,
                workspace_id=ctx.workspace_id,
                brand_id=inputs.brand_id,
                product_id=inputs.product_id,
                project_id=inputs.project_id,
                client_entity_id=EntityId(UUID(inputs.client_entity_id)),
                onboarding_input_id=OnboardingInputId(UUID(inputs.onboarding_input_id)),
                artifact_key=inputs.artifact_key,
                answer=inputs.answer,
                statements=tuple(inputs.statements),
                actor=ctx.actor,
                memory_write=memory_write,
                entailment_judge=self._entailment_judge,
                run_id=RunId(ctx.operation_id),
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "statement_ids": [str(item) for item in result.statement_ids],
                "claim_refs": [str(item) for item in result.claim_refs],
                "memory_refs": list(result.memory_refs),
                "project_state_refs": list(result.project_state_refs),
                "proposal_refs": list(result.proposal_refs),
                "unmapped_statement_ids": [str(item) for item in result.unmapped_statement_ids],
            },
        )


class ConfirmProjectProductTool(_Stage0Tool):
    name = "confirm_project_product"
    input_model = ConfirmProjectProductInput
    output_model = ProjectProductOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project immutable product selection",
    )
    effect_class = ToolEffectClass.STEERING
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_id", "product_id"))
    pin_requirements = ("project", "product")

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> dict[str, object]:
        assert isinstance(inputs, ConfirmProjectProductInput)
        return await self._project_audit_snapshot(inputs.project_id, ctx)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ConfirmProjectProductInput)
        authority = require_human_authority(
            ctx,
            reason_code="human_required",
            message="only an authenticated human can confirm the project product",
        )
        if authority:
            return authority
        async with self._conn_factory() as conn:
            project = await get_project(conn, inputs.project_id)
            product = await get_product(conn, inputs.product_id)
        if (
            project is None
            or product is None
            or project.workspace_id != ctx.workspace_id
            or product.workspace_id != ctx.workspace_id
            or project.brand_id != product.brand_id
        ):
            return _failure(
                "project_product_not_found",
                "project and product do not form a same-workspace brand pair",
            )
        if project.product_id is not None and project.product_id != product.product_id:
            return _failure(
                "project_product_conflict",
                "this project already has a different immutable product selection",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ConfirmProjectProductInput)
        async with self._conn_factory() as conn:
            project = await confirm_project_product(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
                product_id=inputs.product_id,
            )
            if project is None:
                raise ValueError("project/product pair is absent, foreign, or already conflicts")
            client_entity_id = await project_client_entity_id(
                conn,
                workspace_id=ctx.workspace_id,
                project_id=project.project_id,
            )
            if client_entity_id is None:
                raise ValueError(
                    "project product confirmation requires an established workspace client"
                )
            await ensure_product_kb_baseline(
                conn,
                workspace_id=ctx.workspace_id,
                client_entity_id=client_entity_id,
                product_id=inputs.product_id,
                operation_key=f"project-product-selection:{project.project_id}:{inputs.product_id}",
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"project_id": project.project_id, "product_id": project.product_id},
        )


class EvaluateStage0ReadinessTool(_Stage0Tool):
    name = "evaluate_stage0_readiness"
    input_model = EvaluateStage0ReadinessInput
    output_model = Stage0ReadinessOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="ReadinessDecisionId(operation_id)",
        operation_id_required=True,
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "brand_id",
            "gate",
            "product_id",
            "project_id",
            "client_entity_id",
            "client_kb_version",
            "icp_key",
            "icp_version",
            "product_context_version_id",
        )
    )
    pin_requirements = ("readiness_policy", "product_context", "client_kb", "icp")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, EvaluateStage0ReadinessInput)
        async with self._conn_factory() as conn:
            brand = await get_brand(conn, workspace_id=ctx.workspace_id, brand_id=inputs.brand_id)
        if brand is None:
            return _failure("stage0_scope_not_found", "brand does not exist in this workspace")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        """Evaluate one gate, compiling the product context first when the lineage is complete.

        **Behavior change, PC-C8 task 1.3.** ``client_entity_id`` used to be optional *in practice*
        as well as in the schema: the model filled it, and a model that omitted it fell through to
        the no-context branch. It is now engine-injected from the constitution on every agent call,
        so whenever ``product_id`` and ``client_kb_version`` are also present the
        ``compile_product_context`` branch below runs where it previously often did not. That is
        the correct direction — a readiness decision that *could* pin a product-context version and
        silently did not was under-evidenced — but it is a real change in what this tool does per
        call, and it costs one extra compile+write. The C4 recipe path is unaffected: it supplied
        the id already.
        """

        assert isinstance(inputs, EvaluateStage0ReadinessInput)
        client_uuid = _uuid(inputs.client_entity_id) if inputs.client_entity_id else None
        context_uuid = (
            _uuid(inputs.product_context_version_id) if inputs.product_context_version_id else None
        )
        async with self._conn_factory() as conn:
            context_id = ProductContextVersionId(context_uuid) if context_uuid is not None else None
            if (
                context_id is None
                and inputs.product_id is not None
                and client_uuid is not None
                and inputs.client_kb_version is not None
            ):
                context = await compile_product_context(
                    conn,
                    workspace_id=ctx.workspace_id,
                    brand_id=inputs.brand_id,
                    product_id=inputs.product_id,
                    client_entity_id=EntityId(client_uuid),
                    client_kb_version=inputs.client_kb_version,
                    claim_refs=inputs.claim_refs,
                    memory_refs=inputs.memory_refs,
                    artifact_refs=inputs.artifact_refs,
                )
                context_id = context.version_id
            snapshot = await evaluate_readiness(
                conn,
                workspace_id=ctx.workspace_id,
                brand_id=inputs.brand_id,
                product_id=inputs.product_id,
                project_id=inputs.project_id,
                client_entity_id=EntityId(client_uuid) if client_uuid else None,
                client_kb_version=inputs.client_kb_version,
                icp_key=inputs.icp_key,
                icp_version=inputs.icp_version,
                product_context_version_id=context_id,
                gate=inputs.gate,
                spec=self._policy.readiness,
                metrics=inputs.metrics,
                gap_refs=inputs.gap_refs,
                field_proposal_refs=inputs.field_proposal_refs,
                source_proposal_refs=inputs.source_proposal_refs,
                ingestion_refs=inputs.ingestion_refs,
                agent_sufficiency_status=inputs.agent_sufficiency_status,
                agent_sufficiency_ref=inputs.agent_sufficiency_ref,
                created_by_actor=ctx.actor,
                readiness_decision_id=ReadinessDecisionId(ctx.operation_id),
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "readiness_decision_id": str(snapshot.readiness_decision_id),
                "gate": snapshot.gate.value,
                "verdict": snapshot.verdict.value,
                "spec_version": snapshot.spec_version,
                "product_context_version_id": str(context_id) if context_id else None,
            },
        )


class OverrideStage0ReadinessTool(_Stage0Tool):
    name = "override_stage0_readiness"
    input_model = OverrideStage0ReadinessInput
    output_model = Stage0OverrideOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="unique readiness_decision override",
    )
    effect_class = ToolEffectClass.STEERING
    parameter_policy = JournalParameterPolicy(safe_display_fields=("readiness_decision_id", "gate"))
    pin_requirements = ("readiness_decision",)

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> dict[str, object]:
        assert isinstance(inputs, OverrideStage0ReadinessInput)
        return await self._readiness_override_audit_snapshot(inputs.readiness_decision_id, ctx)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, OverrideStage0ReadinessInput)
        authority = require_human_authority(
            ctx,
            reason_code="human_required",
            message="only an authenticated human can record just-go",
        )
        if authority:
            return authority
        decision_uuid = _uuid(inputs.readiness_decision_id)
        if decision_uuid is None:
            return _failure("readiness_not_found", "readiness decision does not exist")
        async with self._conn_factory() as conn:
            decision = await get_readiness_decision(
                conn,
                ReadinessDecisionId(decision_uuid),
                workspace_id=ctx.workspace_id,
            )
        if decision is None or decision.gate is not inputs.gate:
            return _failure("readiness_not_found", "readiness decision does not exist")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, OverrideStage0ReadinessInput)
        async with self._conn_factory() as conn:
            override_id = await override_readiness(
                conn,
                decision_id=ReadinessDecisionId(UUID(inputs.readiness_decision_id)),
                workspace_id=ctx.workspace_id,
                gate=inputs.gate,
                actor=ctx.actor,
                reason=inputs.reason,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "readiness_override_id": str(override_id),
                "readiness_decision_id": inputs.readiness_decision_id,
            },
        )


class StartConfirmedProjectRunTool(_Stage0Tool):
    name = "start_confirmed_project_run"
    input_model = StartConfirmedProjectRunInput
    output_model = ConfirmedProjectRunOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="ProjectRunId(operation_id)",
        operation_id_required=True,
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "project_id",
            "client_entity_id",
            "client_kb_version",
            "product_id",
            "product_context_version_id",
            "readiness_decision_id",
            "icp_key",
            "icp_version",
            "budget_cap_cents",
        )
    )
    pin_requirements = ("project", "client_kb", "product_context", "readiness_decision", "icp")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, StartConfirmedProjectRunInput)
        ids = (
            _uuid(inputs.client_entity_id),
            _uuid(inputs.product_context_version_id),
            _uuid(inputs.readiness_decision_id),
        )
        if any(item is None for item in ids):
            return _failure(
                "confirmed_stage0_context_not_found",
                "confirmed Stage-0 context is malformed or absent",
            )
        async with self._conn_factory() as conn:
            project = await get_project(conn, inputs.project_id)
        if project is None or project.workspace_id != ctx.workspace_id:
            return _failure(
                "confirmed_stage0_context_not_found",
                "confirmed Stage-0 context is malformed or absent",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, StartConfirmedProjectRunInput)
        run_id = ProjectRunId(ctx.operation_id)
        async with self._conn_factory() as conn:
            await start_confirmed_project_run(
                conn,
                project_run_id=run_id,
                workspace_id=ctx.workspace_id,
                project_id=inputs.project_id,
                client_entity_id=EntityId(UUID(inputs.client_entity_id)),
                client_kb_version=inputs.client_kb_version,
                product_id=inputs.product_id,
                product_context_version_id=ProductContextVersionId(
                    UUID(inputs.product_context_version_id)
                ),
                readiness_decision_id=ReadinessDecisionId(UUID(inputs.readiness_decision_id)),
                icp_key=inputs.icp_key,
                icp_version=inputs.icp_version,
                budget_cap_cents=(
                    Decimal(inputs.budget_cap_cents)
                    if inputs.budget_cap_cents is not None
                    else None
                ),
            )
        if self._project_execution_router is not None:
            await self._project_execution_router.attach_if_eligible(
                run_id,
                actor=ctx.actor,
                parent_execution_id=ctx.execution_id,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "project_run_id": str(run_id),
                "phase": "discovery",
                "product_context_version_id": inputs.product_context_version_id,
                "readiness_decision_id": inputs.readiness_decision_id,
            },
        )


def stage0_tools(
    *,
    conn_factory: ConnFactory,
    policy: Stage0Policy,
    pre_spend_gate: PreSpendGate,
    memory_write: MemoryWriteSeam | None,
    scrape_binder: Callable[[AccountEntity], None] | None,
    storage: StorageBackend | None,
    memory_write_factory: MemoryWriteFactory | None = None,
    project_execution_router: ProjectExecutionRouter | None = None,
    entailment_judge: ClaimEntailmentJudge | None = None,
    field_progress_factory: ConnFactory | None = None,
) -> tuple[Tool, ...]:
    def make(tool_type: type[_Stage0Tool]) -> _Stage0Tool:
        return tool_type(
            conn_factory=conn_factory,
            policy=policy,
            pre_spend_gate=pre_spend_gate,
            memory_write=memory_write,
            memory_write_factory=memory_write_factory,
            scrape_binder=scrape_binder,
            storage=storage,
            project_execution_router=project_execution_router,
            entailment_judge=entailment_judge,
            field_progress_factory=field_progress_factory,
        )

    return (
        make(SubmitOnboardingInputTool),
        make(StartReconTool),
        make(RecordInterviewAnswerTool),
        make(ConfirmProjectProductTool),
        make(EvaluateStage0ReadinessTool),
        make(OverrideStage0ReadinessTool),
        make(StartConfirmedProjectRunTool),
    )


__all__ = [
    "ConfirmProjectProductTool",
    "EvaluateStage0ReadinessTool",
    "OverrideStage0ReadinessTool",
    "RecordInterviewAnswerTool",
    "StartConfirmedProjectRunTool",
    "StartReconTool",
    "SubmitOnboardingInputTool",
    "stage0_tools",
]

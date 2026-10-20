"""Api-root construction + registration of the concrete toolbelt (PB-B4 slice 2, D5).

``clue_toolbelt`` ships the *pure* envelope (imports only core/config/db/obs); the concrete tools —
which actually touch the research capabilities — are constructed **here**, at the composition root
that may import everything. Each tool is a **thin delegation** over an existing capability: real
typed inputs, **real machine-readable preconditions** checked against the DB (pre-mortem #2 — an
unmet prerequisite is a loud typed refusal, never a silent-empty success), a cost estimate, and an
``invoke`` that returns **references** (ids/keys/versions), never blobs. No business logic lives in
the wiring — a tool builds the minimal collaborators and calls the one existing entry point.

The registered set (spec §2 slice 2) with each tool's precondition reason codes:

* setup / stage-0 — ``reverse_profile`` (none), ``synthesize_icps`` (``no_client_kb``),
  ``confirm_icp`` (``no_client_kb``), ``import_accounts`` (``no_active_icp``, ``invalid_entity_id``,
  ``no_client_kb``, ``project_not_found``);
* discovery / scoring — ``discover_accounts`` (``run_not_found``, ``icp_version_missing``),
  ``score_accounts`` (``run_not_found``, ``discovery_not_run``), ``submit_tier_checkpoint``
  (``run_not_found``, ``checkpoint_not_awaiting``);
* deep / committee / contact — ``run_deep_account`` (``no_active_icp``; with a ``project_run_id``:
  ``run_not_found`` / ``icp_version_missing``; plus ``invalid_tier``, ``account_not_found``),
  ``resolve_committee`` (``account_not_found``), ``profile_contact`` (``account_not_found``,
  ``contact_not_found``);
* verification / handoff — ``run_verification`` (``run_not_found``, ``icp_version_missing``),
  ``compose_handoff`` (``run_not_found``, ``handoff_not_reached``);
* estimate — ``estimate_project`` (none — pure);
* run controls — ``start_project_run`` (``project_not_found``), ``pause_run`` (``run_not_found``),
  ``resume_run`` (``run_not_found``, ``run_not_paused``), ``adjust_budget`` (``run_not_found``).

**Workspace scoping (B4 slice-2 review B1).** Every *run*-scoped tool loads its run through
``_load_run``, which fails closed (``run_not_found``, no existence leak) when the run's
``workspace_id`` differs from ``ctx.workspace_id`` — so ``pause_run`` / ``adjust_budget`` /
``submit_tier_checkpoint`` / ``score_accounts`` / ``discover_accounts`` / ``run_verification`` /
``compose_handoff`` / ``resume_run`` all inherit the guard and cannot touch another tenant's run.
Run-scoped tools also resolve the run's **pinned** ICP version (``get_icp_version`` — the version
the machine advanced on), not the *active* ICP, so a tool and the later machine drive agree
byte-for-byte; ``import_accounts`` (not run-scoped) legitimately keeps active-ICP semantics.

**Account workspace scoping is fail-closed** ([B3×research], resolved 2026-07-23). The
account-scoped spend tools — ``run_deep_account`` / ``resolve_committee`` / ``profile_contact`` —
load their account through ``_load_account``, the analogue of ``_load_run``: an account whose
``workspace_id`` differs from ``ctx.workspace_id`` resolves to the same ``account_not_found``
refusal a truly-absent id gets, so a cross-tenant id is indistinguishable from a non-existent one
(no existence leak). Now that ``account_entity`` requires ``workspace_id`` on every account, this
is the same B1 guard the run-scoped tools enforce.
Refusals emit a structured WARNING (``toolbelt.account_scope_refused`` with actor + workspace +
account id) so a scope violation stays auditable; the pre-B3 ``toolbelt.unscoped_account_access``
warn-and-proceed placeholder is retired.

Preconditions read through ``ctx.conn_factory``; a malformed id resolves to the same not-found
refusal (never a raw traceback). The ``compose_handoff`` result surfaces the slice-1
legacy ``narrative_emit_skipped`` gap flag from a pre-C7.6 HANDOFF checkpoint payload, so a
historical gap-completed
run is distinguishable from a truly-handed-off one (spec §2 amendment / slice-1 review #10).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import ClassVar, Protocol, cast
from uuid import UUID

from pydantic import Field, JsonValue
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.account_research_fleet import read_latest_account_fleet_for_project_run
from clue_api.agent_gate_wiring import register_agent_gate_tools
from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.artifact_read_tools import build_artifact_read_tools
from clue_api.arv2.account_research_launch import Arv2LaunchService, build_arv2_launch_tools
from clue_api.arv2.discovery_launch import (
    Arv2DiscoveryService,
    build_arv2_discovery_tools,
)
from clue_api.arv2.icp_authoring import IcpAuthoringService
from clue_api.arv2.read_tools import (
    Arv2ReadService,
    ReadAccountResearchV3Tool,
    ReadDiscoveryRunV3Tool,
    build_arv2_paged_read_tools,
    build_arv2_read_tools,
)
from clue_api.auth_tool_context import require_human_authority
from clue_api.claim_entailment import FaithfulnessClaimEntailmentJudge
from clue_api.client_knowledge_tools import (
    build_client_knowledge_tools,
    build_client_knowledge_v2_tools,
)
from clue_api.composition import build_pre_spend_gate
from clue_api.contact_content_handoff import ContactContentHandoffService
from clue_api.coverage_tools import (
    build_research_account_gaps_tool,
    build_research_account_gaps_v2_tool,
)
from clue_api.crm.read_sinks import CrmReadSinks
from clue_api.crm.tools import build_crm_tools
from clue_api.design_leg_tools import build_design_leg_tools
from clue_api.design_tools import build_design_tools, is_default_design_tool
from clue_api.discovery_configuration import ConfirmedDiscoveryPreflight
from clue_api.discovery_seal import DbSealedDiscoveryAccountManifestReader
from clue_api.dynamic_client_kb import DynamicClientKbMaterializer
from clue_api.entity_research_launch_tools import (
    EntityResearchLaunchServices,
    build_entity_research_launch_tools,
)
from clue_api.entity_research_quarantine import quarantine_entity_research_tool
from clue_api.entity_research_verification_resolver import (
    build_entity_research_account_resolver,
)
from clue_api.exa_targeted_enrichment import (
    DEFAULT_EXA_TARGETED_ENRICHMENT_POLICY,
    ExaTargetedEligibilityError,
    ExaTargetedResult,
    approved_targeted_field_plans,
)
from clue_api.exa_websets_submit import DEFAULT_EXA_WEBSETS_PRICING
from clue_api.fleet_wiring import enqueue_run_drive
from clue_api.icp_artifact_gate_tools import build_icp_artifact_gate_tools
from clue_api.icp_authoring_tools import build_icp_authoring_tools
from clue_api.independent_contact_research import IndependentContactResearchRunner
from clue_api.ingestion_tools import RetryIngestionTool, SubmitIngestionTool
from clue_api.locks import lazy_account_lock_factory
from clue_api.onboarding_evidence_tools import build_onboarding_evidence_tools
from clue_api.persona_request_tools import PersonaRequestService, build_persona_request_tools
from clue_api.phase_wiring import build_discovery_handler, build_scoring_handler
from clue_api.product_knowledge_tools import build_product_knowledge_tools
from clue_api.product_management_tools import ManageProductsTool
from clue_api.product_set_selection_gate_tools import (
    build_product_set_selection_gate_tools,
)
from clue_api.project_document_tools import (
    ProjectDocumentService,
    build_project_document_tools,
)
from clue_api.project_execution_router import ProjectExecutionRouter
from clue_api.project_targeting_tools import ConfigureProjectTargetingTool
from clue_api.project_tools import (
    CreateProjectTool,
    RenameProjectTool,
    SetProjectArchivedTool,
    SetProjectPinnedTool,
    UpdateProjectDetailsTool,
)
from clue_api.proposal_tools import (
    DecideFieldProposalTool,
    DecideSourceProposalTool,
    LegacyDecideFieldProposalTool,
    LegacyProposeFieldTool,
    ProposeFieldTool,
    ProposeSourceTool,
)
from clue_api.prose_synthesis_tools import (
    ProseSynthesisServices,
    build_prose_synthesis_tools,
)
from clue_api.research_directive_tools import build_research_directive_tools
from clue_api.research_view_tools import build_research_view_tools
from clue_api.run_python_tool import build_run_python_tools
from clue_api.sandbox.workspaces import SandboxWorkspaces
from clue_api.stage0_inspection_tools import build_stage0_inspection_tools
from clue_api.stage0_project_tools import stage0_project_tools
from clue_api.stage0_tools import stage0_tools
from clue_api.statement_evidence import ArtifactStatementEvidenceReader
from clue_api.storage_wiring import SnapshotBindingPhaseHandler
from clue_api.sumble_account_gaps import (
    DEFAULT_SUMBLE_ACCOUNT_GAP_POLICY,
    SumbleAccountGapEligibilityError,
    SumbleAccountGapResult,
)
from clue_api.thread_wiring import register_thread_tools
from clue_api.tool_outputs import (
    AccountDeepLaunchOutput,
    AccountGapEnrichmentOutput,
    CommitteeOutput,
    ConfirmIcpOutput,
    ContactContentHandoffOutput,
    ContactProfileOutput,
    ContactResearchSelectionApprovalOutput,
    DeepAccountOutput,
    DiscoverAccountsOutput,
    GovernedContactProfileOutput,
    HandoffOutput,
    ImportAccountsOutput,
    PhaseAccountsOutput,
    ProjectEstimateOutput,
    ProjectRunBudgetOutput,
    ProjectRunResumeOutput,
    ProjectRunStartOutput,
    ProjectRunStatusOutput,
    ReverseProfileOutput,
    SynthesizeIcpsOutput,
    TargetedEnrichmentOutput,
    TierCheckpointOutput,
)
from clue_api.value_narrative_tools import (
    ValueNarrativeServices,
    build_value_narrative_tools,
)
from clue_api.verification import build_verification_phase_handler
from clue_api.web_search_tool import build_web_search_tools
from clue_config import (
    DEFAULT_STAGE0_POLICY,
    Secrets,
    Settings,
    load_settings,
    stage0_policy_from_settings,
)
from clue_core import (
    NARRATIVE_EMIT_SKIPPED_KEY,
    AccountEntity,
    ContactContentHandoff,
    ContactResearchSelection,
    ContactResearchSelectionId,
    CostCents,
    EntityId,
    ICPSpec,
    LLMGateway,
    MemoryWriteSeam,
    PhaseContext,
    PhaseHandler,
    PreSpendGate,
    ProjectPhase,
    ProjectRunId,
    ResearchDirectiveId,
    ResearchViewComposer,
    RunId,
)
from clue_db import ConnFactory, transaction
from clue_fleet import TaskQueue
from clue_obs import get_logger
from clue_research.claimstore import ALL_WORKSPACES
from clue_research.discovery_scoring.discovery import ChannelRegistry
from clue_research.discovery_scoring.phases import discovery_run_id
from clue_research.discovery_scoring.scoring import admitted_account_ids
from clue_research.discovery_scoring.tiering import DEFAULT_TIERING_CONFIG
from clue_research.durable import (
    AccountDeepLaunchConflict,
    AccountDeepLaunchInvalid,
    BudgetEngine,
    ContactResearchSelectionApprovalAuthority,
    ContactResearchSelectionApprovalKind,
    ContactResearchSelectionNotFound,
    DbBudgetStore,
    DbIdempotencyStore,
    DbProjectRunStore,
    DiscoverySealConflict,
    LockFactory,
    PhaseCheckpointStatus,
    PhaseHandlerRegistry,
    ProjectRun,
    ProjectRunRow,
    ProjectRunStatus,
    create_account_deep_launch,
    get_checkpoint,
    get_contact_research_selection,
    get_project_run,
    latest_contact_research_selection,
    preview_account_deep_launch,
    store_contact_research_selection,
)
from clue_research.icp.rubric import TierCutoffs, rubric_from_slot
from clue_research.icp.spec import get_active_icp, get_icp_version
from clue_research.identity import get_account, get_contact
from clue_research.ingestion import IngestionEngine
from clue_research.narrative import (
    ResearchViewRecheckService,
    ResearchViewSnapshotService,
    list_handoffs_for_run,
)
from clue_research.profiling import (
    CommitteeSource,
    discover_committee,
    profile_account,
    profile_contact,
)
from clue_research.proposals import SourceProposalPayload
from clue_research.stage0 import (
    ClientInput,
    ClientKnowledgeBaseRef,
    EstimateInputs,
    ICPProposal,
    ICPProposalEdits,
    ICPSpecRef,
    ImportRow,
    confirm_icp,
    current_kb_version,
    estimate_campaign,
    import_accounts,
    reverse_profile,
    synthesize_icps,
)
from clue_research.verification import FaithfulnessJudgeImpl
from clue_spine import get_project
from clue_storage import StorageBackend
from clue_toolbelt import (
    ExternalReplayBoundary,
    JournalParameterPolicy,
    PreconditionFailed,
    PreconditionFailure,
    ReplayPolicy,
    ReplaySafety,
    Tool,
    ToolContext,
    ToolEffectClass,
    ToolEstimate,
    ToolInput,
    ToolRegistry,
    ToolResult,
)

__all__ = ["build_toolbelt", "GatewayRequired"]

log = get_logger("clue_api.toolbelt_wiring")


class GatewayRequired(RuntimeError):
    """A spend tool was invoked but the toolbelt was built without an ``LLMGateway``. The
    composition root must inject one (from settings/secrets) for the LLM-touching tools; the
    prerequisite-free / pure-read tools do not need it. Raised (not silently stubbed) so a
    misconfigured deployment fails loud, per pre-mortem #2."""


# --- id parsing (a malformed id resolves to not-found, never a raw traceback) -----------------


def _parse_run_id(raw: str) -> ProjectRunId | None:
    try:
        return ProjectRunId(UUID(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _parse_entity_id(raw: str) -> EntityId | None:
    try:
        return EntityId(UUID(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _parse_contact_selection_id(raw: str) -> ContactResearchSelectionId | None:
    try:
        return ContactResearchSelectionId(UUID(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _parse_account_run_id(raw: str) -> RunId | None:
    try:
        return RunId(UUID(raw))
    except (ValueError, AttributeError, TypeError):
        return None


def _fail(reason_code: str, message: str) -> tuple[PreconditionFailure, ...]:
    return (PreconditionFailure(reason_code=reason_code, message=message),)


# =============================================================================================
# input models (defined at the api root so they may embed research pydantic types)
# =============================================================================================


class ReverseProfileInput(ToolInput):
    name: str
    website: str


class SynthesizeIcpsInput(ToolInput):
    client_entity_id: str
    kb_version: int | None = None
    product_id: str | None = None


class ConfirmIcpInput(ToolInput):
    client_entity_id: str
    proposal: ICPProposal
    edits: ICPProposalEdits | None = None
    created_by: str | None = None
    client_kb_version: int | None = None
    product_id: str | None = None


class ImportAccountsInput(ToolInput):
    client_entity_id: str
    icp_key: str
    rows: list[ImportRow]
    # FI-2 H3 (spec §8.3): the project this list is being imported *into*. ``ToolContext`` carries
    # workspace + actor + operation but no project, and import is not run-scoped, so the project
    # cannot be derived from context — it has to be an input. Optional: omitted, the import is
    # workspace-level and the accounts join no project's target list (today's behaviour).
    project_id: str | None = None


class DiscoverAccountsInput(ToolInput):
    project_run_id: str


class ScoreAccountsInput(ToolInput):
    project_run_id: str


class EnrichSelectedAccountsInput(ToolInput):
    project_run_id: str
    account_entity_ids: tuple[str, ...]
    field_keys: tuple[str, ...]


class EnrichAccountGapsInput(ToolInput):
    project_run_id: str
    account_entity_id: str
    field_expected_value_credits: dict[str, Decimal]
    provider_credit_cap: int
    allow_unbounded_tech: bool = False


class SubmitTierCheckpointInput(ToolInput):
    project_run_id: str
    decision: dict[str, object] = {}


class LaunchAccountDeepInput(ToolInput):
    project_run_id: str
    research_directive_id: str
    account_entity_ids: tuple[str, ...] = Field(min_length=1, max_length=500)
    approved_budget_cap_cents: Decimal = Field(ge=0)
    expected_estimated_cost_cents: Decimal = Field(ge=0)


class RunDeepAccountInput(ToolInput):
    account_entity_id: str
    icp_key: str
    tier: str
    # S1: when supplied, the deep spend is threaded to this run (budget-visible), and the tier is
    # validated against the run's own cutoff bands rather than the active ICP rubric's.
    project_run_id: str | None = None


class ResolveCommitteeInput(ToolInput):
    account_entity_id: str
    icp_key: str | None = None


class ProfileContactInput(ToolInput):
    contact_entity_id: str
    account_entity_id: str
    tier: str
    icp_key: str | None = None


class GovernedProfileContactInput(ToolInput):
    project_run_id: str
    contact_entity_id: str
    account_entity_id: str


class RunVerificationInput(ToolInput):
    project_run_id: str


class ComposeHandoffInput(ToolInput):
    project_run_id: str


class ComposeContactContentHandoffInput(ToolInput):
    project_id: str
    project_run_id: str
    account_entity_id: str
    product_id: str | None = None


class ApproveContactResearchSelectionInput(ToolInput):
    selection: ContactResearchSelection
    account_run_id: str
    predecessor_selection_id: str


class EstimateProjectInput(ToolInput):
    projected_account_count: int | None = None
    deep_fraction: float | None = None


class StartProjectRunInput(ToolInput):
    project_id: str
    icp_key: str
    icp_version: int
    budget_cap_cents: int | None = None


class PauseRunInput(ToolInput):
    project_run_id: str


class ResumeRunInput(ToolInput):
    project_run_id: str


class AdjustBudgetInput(ToolInput):
    project_run_id: str
    budget_cap_cents: int


# =============================================================================================
# tool base with shared collaborators (gateway / channels / sources / run machine / queue)
# =============================================================================================


class _CapabilityTool(Tool):
    """Base for the concrete tools — holds the injected collaborators the api root supplies once.
    Each tool remains a thin delegation; this only removes the constructor boilerplate."""

    def __init__(
        self,
        *,
        settings: Settings,
        gateway: LLMGateway | None,
        channels: ChannelRegistry,
        committee_sources: Sequence[CommitteeSource],
        run_machine: ProjectRun,
        queue: TaskQueue | None,
        conn_factory: ConnFactory,
        pre_spend_gate: PreSpendGate,
        lock_factory: LockFactory,
        storage: StorageBackend | None,
        project_execution_router: ProjectExecutionRouter | None,
        account_deep_full_unit_available: bool,
        independent_contact_research: IndependentContactResearchRunner | None,
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._channels = channels
        self._committee_sources = tuple(committee_sources)
        self._run = run_machine
        self._queue = queue
        self._conn_factory = conn_factory
        self._pre_spend_gate = pre_spend_gate
        self._lock_factory = lock_factory
        self._storage = storage
        self._project_execution_router = project_execution_router
        self._account_deep_full_unit_available = account_deep_full_unit_available
        self._independent_contact_research = independent_contact_research

    def _require_gateway(self) -> LLMGateway:
        if self._gateway is None:
            raise GatewayRequired(f"tool {self.name!r} needs an LLMGateway but none was injected")
        return self._gateway

    async def _load_run(self, raw_id: str, ctx: ToolContext) -> ProjectRunRow | None:
        """The run for ``raw_id``, **fail-closed to the caller's workspace** (B4 slice-2 review B1):
        a run whose ``workspace_id`` differs from ``ctx.workspace_id`` resolves to ``None`` (the
        same ``run_not_found`` refusal a truly-absent / malformed id gets), so a cross-tenant id is
        indistinguishable from a non-existent one — no existence leak."""
        run_id = _parse_run_id(raw_id)
        if run_id is None:
            return None
        async with self._conn_factory() as conn:
            run = await get_project_run(conn, run_id)
        if run is None or run.workspace_id != ctx.workspace_id:
            return None
        return run

    async def _run_audit_snapshot(self, raw_id: str, ctx: ToolContext) -> dict[str, object]:
        run = await self._load_run(raw_id, ctx)
        if run is None:
            return {"project_run_id": raw_id, "exists": False}
        return {
            "project_run_id": str(run.id),
            "exists": True,
            "phase": run.phase.value,
            "status": run.status.value,
            "budget_cap_cents": (
                str(run.budget_cap_cents) if run.budget_cap_cents is not None else None
            ),
            "tier_cutoffs": dict(run.tier_cutoffs),
        }

    async def _load_account(
        self, tool: str, raw_id: str, ctx: ToolContext, conn: AsyncConnection
    ) -> AccountEntity | None:
        """Fail-closed account→workspace guard ([B3×research], resolved 2026-07-23): a missing,
        malformed, or other-workspace account resolves to ``None`` — the caller then surfaces the
        same ``account_not_found`` refusal a truly-absent id gets, so a cross-tenant id is
        indistinguishable from a non-existent one (no existence leak), mirroring
        :meth:`_load_run`. Refusals are WARNING-logged (``toolbelt.account_scope_refused``) so
        misuse stays visible."""
        entity_id = _parse_entity_id(raw_id)
        account = await get_account(conn, entity_id) if entity_id is not None else None
        if account is None or account.workspace_id != ctx.workspace_id:
            log.warning(
                "toolbelt.account_scope_refused",
                tool=tool,
                actor=ctx.actor,
                workspace_id=ctx.workspace_id,
                account_entity_id=raw_id,
            )
            return None
        return account

    async def _load_active_spec(self, workspace_id: str, icp_key: str) -> ICPSpec | None:
        async with self._conn_factory() as conn:
            return await get_active_icp(conn, workspace_id, icp_key)

    async def _load_pinned_spec(self, run: ProjectRunRow) -> ICPSpec | None:
        """The run's **pinned** ICP spec version (S3): ``get_icp_version`` returns the exact version
        the machine advanced on, not whichever is currently ``active`` — so a run-scoped tool and
        the later fleet drive resolve the identical spec even after a newer ICP is activated."""
        async with self._conn_factory() as conn:
            return await get_icp_version(conn, run.workspace_id, run.icp_key, run.icp_version)

    def _phase_ctx(self, run: ProjectRunRow, phase: ProjectPhase) -> PhaseContext:
        # N4: always carry the run's tier_cutoffs in params (the shape ``ProjectRun`` itself builds
        # in ``durable/project.py`` — ``params={"tier_cutoffs": run.tier_cutoffs}``), so the DEEP
        # handler's high-tier resolver reads the same content-addressed cutoff set either driver.
        return PhaseContext(
            project_run_id=run.id,
            project_id=run.project_id,
            brand_id=run.brand_id,
            phase=phase,
            workspace_id=run.workspace_id,
            icp_key=run.icp_key,
            icp_version=run.icp_version,
            budget_cap_cents=run.budget_cap_cents,
            params={"tier_cutoffs": run.tier_cutoffs},
        )

    def _wrap_snapshots(self, handler: PhaseHandler) -> PhaseHandler:
        """S2: wrap a run-drive phase handler in the B2 snapshot-binding wrapper when a storage
        backend is wired, so each tool-path phase run captures/flushes evidence under one ambient
        per-run sink (exactly as the DEEP registration surface does). Without storage the bare
        handler is used (the pre-B2 no-snapshot path)."""
        if self._storage is None:
            return handler
        return SnapshotBindingPhaseHandler(inner=handler, storage=self._storage)


# =============================================================================================
# setup / stage-0 tools
# =============================================================================================


class ReverseProfileTool(_CapabilityTool):
    name = "reverse_profile"
    input_model = ReverseProfileInput
    output_model = ReverseProfileOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="workspace client identity + RunId(operation_id)",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(safe_display_fields=("name", "website"))
    pin_requirements = ("field_registry", "source_registry", "stage0_policy")

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReverseProfileInput)
        async with ctx.conn_factory() as conn:
            result = await reverse_profile(
                conn,
                ClientInput(name=inputs.name, website=inputs.website),
                workspace_id=ctx.workspace_id,
                run_id=RunId(ctx.operation_id),
                pre_spend_gate=self._pre_spend_gate,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "client_entity_id": str(result.ref.client_entity_id),
                "client_kb_version": result.ref.client_kb_version,
                "fields_resolved": result.fields_resolved,
            },
        )


class SynthesizeIcpsTool(_CapabilityTool):
    name = "synthesize_icps"
    input_model = SynthesizeIcpsInput
    output_model = SynthesizeIcpsOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.AT_LEAST_ONCE,
        durable_identity="reference-only completion; synthesis writes no confirmed ICP",
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("client_entity_id", "kb_version", "product_id")
    )
    pin_requirements = ("client_kb", "field_registry", "model_prompt")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, SynthesizeIcpsInput)
        entity = _parse_entity_id(inputs.client_entity_id)
        if entity is None:
            return _fail("no_client_kb", "client_entity_id is not a valid entity id")
        async with ctx.conn_factory() as conn:
            version = await current_kb_version(conn, entity, workspace_id=ctx.workspace_id)
            if inputs.product_id is not None:
                version = await current_kb_version(
                    conn,
                    entity,
                    workspace_id=ctx.workspace_id,
                    product_id=inputs.product_id,
                )
        if version is None:
            return _fail(
                "no_client_kb",
                "no Client Knowledge Base for this client — run reverse_profile first",
            )
        if inputs.kb_version is not None and inputs.kb_version != version:
            return _fail(
                "client_kb_version_missing",
                "the requested product-scoped Client Knowledge Base version is not current",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, SynthesizeIcpsInput)
        entity = _parse_entity_id(inputs.client_entity_id)
        assert entity is not None  # narrowed by preconditions
        async with ctx.conn_factory() as conn:
            version = inputs.kb_version
            if version is None:
                version = await current_kb_version(conn, entity, workspace_id=ctx.workspace_id)
                if inputs.product_id is not None:
                    version = await current_kb_version(
                        conn,
                        entity,
                        workspace_id=ctx.workspace_id,
                        product_id=inputs.product_id,
                    )
            assert version is not None
            ref = ClientKnowledgeBaseRef(
                client_entity_id=entity,
                client_kb_version=version,
                product_id=inputs.product_id,
            )
            result = await synthesize_icps(
                conn, ref, workspace_id=ctx.workspace_id, gateway=self._gateway
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "proposal_count": len(result.proposals),
                "client_kb_version": version,
            },
        )


class ConfirmIcpTool(_CapabilityTool):
    name = "confirm_icp"
    input_model = ConfirmIcpInput
    output_model = ConfirmIcpOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="workspace + icp_key + compiled selection equality",
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("client_entity_id", "client_kb_version", "product_id")
    )
    pin_requirements = ("client_kb", "field_registry", "source_profile")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ConfirmIcpInput)
        if (inputs.client_kb_version is None) != (inputs.product_id is None):
            return _fail(
                "incomplete_stage0_lineage",
                "C4 confirmation requires both client_kb_version and product_id",
            )
        entity = _parse_entity_id(inputs.client_entity_id)
        if entity is None:
            return _fail("no_client_kb", "client_entity_id is not a valid entity id")
        async with ctx.conn_factory() as conn:
            version = await current_kb_version(conn, entity, workspace_id=ctx.workspace_id)
            if inputs.product_id is not None:
                version = await current_kb_version(
                    conn,
                    entity,
                    workspace_id=ctx.workspace_id,
                    product_id=inputs.product_id,
                )
        if version is None:
            return _fail(
                "no_client_kb",
                "no Client Knowledge Base for this client — run reverse_profile first",
            )
        if inputs.client_kb_version is not None and inputs.client_kb_version != version:
            return _fail(
                "client_kb_version_missing",
                "the requested product-scoped Client Knowledge Base version is not current",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ConfirmIcpInput)
        entity = _parse_entity_id(inputs.client_entity_id)
        assert entity is not None
        async with ctx.conn_factory() as conn:
            confirmation = await confirm_icp(
                conn,
                inputs.proposal,
                inputs.edits,
                workspace_id=ctx.workspace_id,
                client_entity_id=entity,
                created_by=inputs.created_by,
                client_kb_version=inputs.client_kb_version,
                product_id=inputs.product_id,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "icp_key": confirmation.ref.icp_key,
                "icp_version": confirmation.ref.icp_version,
            },
        )


class ImportAccountsTool(_CapabilityTool):
    name = "import_accounts"
    input_model = ImportAccountsInput
    output_model = ImportAccountsOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="import_batch_id derived from operation_id",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("client_entity_id", "icp_key", "project_id")
    )
    # FI-2 H3: ``project`` is deliberately NOT pinned even though ``project_id`` is now an input.
    # The parameter is *optional* — a workspace-level import with no project is a supported, tested
    # shape — and ``pin_requirements`` is an all-or-nothing availability check (Recipe 1 refuses the
    # tool when a required pin has no value), so declaring it would make every legitimately
    # projectless import unavailable. The project is instead validated per call in ``preconditions``
    # (typed ``project_not_found``, workspace-scoped) and journalled via ``safe_display_fields``.
    pin_requirements = ("client_kb", "icp", "source_registry")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ImportAccountsInput)
        spec = await self._load_active_spec(ctx.workspace_id, inputs.icp_key)
        if spec is None:
            return _fail(
                "no_active_icp",
                f"no active ICP {inputs.icp_key!r} — confirm an ICP before importing accounts",
            )
        # S5: parse + client-KB existence, mirroring synthesize_icps — a malformed id or a missing
        # KB is a typed refusal here, not an AssertionError in invoke.
        entity = _parse_entity_id(inputs.client_entity_id)
        if entity is None:
            return _fail("invalid_entity_id", "client_entity_id is not a valid entity id")
        async with ctx.conn_factory() as conn:
            version = await current_kb_version(conn, entity, workspace_id=ctx.workspace_id)
            if version is None:
                return _fail(
                    "no_client_kb",
                    "no Client Knowledge Base for this client — run reverse_profile first",
                )
            # The capability refuses an unowned project with ImportProjectNotFound; checking it
            # here keeps the refusal typed and machine-readable rather than a raised traceback, and
            # fails closed on another workspace's project exactly like _load_run / _load_account.
            if inputs.project_id is not None:
                project = await get_project(conn, inputs.project_id)
                if project is None or project.workspace_id != ctx.workspace_id:
                    return _fail("project_not_found", "no such project")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ImportAccountsInput)
        entity = _parse_entity_id(inputs.client_entity_id)
        assert entity is not None  # narrowed by preconditions
        async with ctx.conn_factory() as conn:
            spec = await get_active_icp(conn, ctx.workspace_id, inputs.icp_key)
            assert spec is not None  # narrowed by preconditions
            spec_ref = ICPSpecRef(
                workspace_id=ctx.workspace_id, icp_key=spec.icp_key, icp_version=spec.version
            )
            result = await import_accounts(
                conn,
                inputs.rows,
                spec_ref,
                workspace_id=ctx.workspace_id,
                client_entity_id=entity,
                import_batch_id=f"operation-{ctx.operation_id}",
                project_id=inputs.project_id,
                pre_spend_gate=self._pre_spend_gate,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "import_batch_id": str(result.import_batch_id),
                "resolved": len(result.resolved),
                "needs_review": len(result.needs_review),
                "unresolved": len(result.unresolved),
            },
        )


# =============================================================================================
# discovery / scoring / tier-checkpoint tools (run-scoped phase capabilities)
# =============================================================================================


class DiscoverAccountsTool(_CapabilityTool):
    name = "discover_accounts"
    input_model = DiscoverAccountsInput
    output_model = DiscoverAccountsOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project_run + discovery phase ledger + deterministic discovery run",
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_run_id",))
    pin_requirements = ("project_run", "icp", "source_profile", "source_registry")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, DiscoverAccountsInput)
        run = await self._load_run(inputs.project_run_id, ctx)
        if run is None:
            return _fail("run_not_found", "no such project run")
        if await self._load_pinned_spec(run) is None:
            return _fail(
                "icp_version_missing",
                f"no pinned ICP {run.icp_key!r} v{run.icp_version} for this run",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, DiscoverAccountsInput)
        run = await self._load_run(inputs.project_run_id, ctx)
        assert run is not None
        # B2: delegate to the real DISCOVERY phase handler (discover → admit → provenance), exactly
        # as score_accounts delegates to ScoringPhaseHandler — so the deterministic discovery run-id
        # derivation, the admission-gate writes, and the M7.4 replay-idempotency all match the
        # machine's later drive. The bare ``discover()`` call this replaces did none of that.
        handler = self._wrap_snapshots(
            build_discovery_handler(
                channels=self._channels,
                gateway=self._gateway,
                durable_batches=self._storage is not None,
                storage=self._storage,
                session_factory=self._conn_factory,
            )
        )
        result = await handler.run(self._phase_ctx(run, ProjectPhase.DISCOVERY))
        payload = result.payload
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "status": result.status.value,
                "discovery_run_id": payload.get("discovery_run_id"),
                # The handler's real counts: admitted accounts (not just candidates seen).
                "admitted": result.accounts_processed,
                "candidates": payload.get("candidates"),
                "needs_review": payload.get("needs_review"),
                "rejected": payload.get("rejected"),
                "stopping_reason": payload.get("stopping_reason"),
            },
        )


class ScoreAccountsTool(_CapabilityTool):
    name = "score_accounts"
    input_model = ScoreAccountsInput
    output_model = PhaseAccountsOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project_run + scoring phase ledger",
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_run_id",))
    pin_requirements = ("project_run", "icp", "scoring_policy")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ScoreAccountsInput)
        run = await self._load_run(inputs.project_run_id, ctx)
        if run is None:
            return _fail("run_not_found", "no such project run")
        if run.phase is not ProjectPhase.SCORING:
            return _fail(
                "project_phase_not_scoring",
                "score_accounts is available only while the project run is in scoring",
            )
        if run.status is not ProjectRunStatus.ACTIVE:
            return _fail(
                "project_run_not_active",
                "score_accounts requires an active project run",
            )
        admitted: Sequence[EntityId]
        if self._storage is not None:
            try:
                sealed = await DbSealedDiscoveryAccountManifestReader(
                    storage=self._storage,
                    conn_factory=self._conn_factory,
                ).read(
                    workspace_id=run.workspace_id,
                    project_run_id=run.id,
                    icp_key=run.icp_key,
                    icp_version=run.icp_version,
                )
            except DiscoverySealConflict:
                return _fail(
                    "discovery_not_sealed",
                    "the exact current discovery generation is not sealed",
                )
            if sealed is not None:
                admitted = sealed.account_ids
            else:
                # The durable feature flag may be enabled for a historical run which never
                # acquired a batch. Preserve the legacy run's existing provenance semantics.
                discovery_run = discovery_run_id(self._phase_ctx(run, ProjectPhase.SCORING))
                async with self._conn_factory() as conn:
                    admitted = await admitted_account_ids(
                        conn, run_id=discovery_run, scope=ALL_WORKSPACES
                    )
        else:
            discovery_run = discovery_run_id(self._phase_ctx(run, ProjectPhase.SCORING))
            async with self._conn_factory() as conn:
                admitted = await admitted_account_ids(
                    conn, run_id=discovery_run, scope=ALL_WORKSPACES
                )
        if not admitted:
            return _fail(
                "discovery_not_run",
                "no admitted accounts for this run — run discover_accounts first",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ScoreAccountsInput)
        run = await self._load_run(inputs.project_run_id, ctx)
        assert run is not None
        if run.phase is not ProjectPhase.SCORING:
            raise PreconditionFailed(
                _fail(
                    "project_phase_not_scoring",
                    "score_accounts is available only while the project run is in scoring",
                )
            )
        if run.status is not ProjectRunStatus.ACTIVE:
            raise PreconditionFailed(
                _fail(
                    "project_run_not_active",
                    "score_accounts requires an active project run",
                )
            )
        sealed_reader = (
            DbSealedDiscoveryAccountManifestReader(
                storage=self._storage,
                conn_factory=self._conn_factory,
            )
            if self._storage is not None
            else None
        )
        handler = self._wrap_snapshots(
            build_scoring_handler(
                pre_spend_gate=self._pre_spend_gate,
                sealed_account_reader=sealed_reader,
                session_factory=self._conn_factory,
            )
        )
        result = await handler.run(self._phase_ctx(run, ProjectPhase.SCORING))
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "status": result.status.value,
                "accounts_processed": result.accounts_processed,
            },
        )


class TargetedEnrichmentStarter(Protocol):
    async def start(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_ids: Sequence[EntityId],
        field_keys: Sequence[str],
    ) -> ExaTargetedResult: ...


class AccountGapEnrichmentStarter(Protocol):
    async def start(
        self,
        *,
        workspace_id: str,
        project_run_id: ProjectRunId,
        account_id: EntityId,
        field_expected_value_credits: dict[str, Decimal],
        provider_credit_cap: int,
        allow_unbounded_tech: bool,
    ) -> SumbleAccountGapResult: ...


class EnrichAccountGapsTool(Tool):
    """Explicit S1 spend for native Sumble fields on one selected account."""

    name = "enrich_account_gaps"
    input_model = EnrichAccountGapsInput
    output_model = AccountGapEnrichmentOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project run + discovery seal + account + field set + policy window",
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "project_run_id",
            "account_entity_id",
            "field_expected_value_credits",
            "provider_credit_cap",
            "allow_unbounded_tech",
        )
    )
    pin_requirements = (
        "project_run",
        "discovery_seal",
        "tier_checkpoint",
        "field_policy",
        "budget_policy",
    )

    def __init__(
        self,
        *,
        starter: AccountGapEnrichmentStarter | None,
        conn_factory: ConnFactory,
        cents_per_credit: Decimal,
    ) -> None:
        self._starter = starter
        self._conn_factory = conn_factory
        self._cents_per_credit = cents_per_credit

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, EnrichAccountGapsInput)
        if self._starter is None:
            return _fail(
                "sumble_account_gap_not_configured",
                "Sumble account-gap enrichment is disabled or unavailable",
            )
        run_id = _parse_run_id(inputs.project_run_id)
        account_id = _parse_entity_id(inputs.account_entity_id)
        if run_id is None:
            return _fail("run_not_found", "no such project run")
        if account_id is None:
            return _fail("account_not_found", "no such account")
        if (
            not inputs.field_expected_value_credits
            or len(inputs.field_expected_value_credits)
            > DEFAULT_SUMBLE_ACCOUNT_GAP_POLICY.maximum_fields
            or any(value <= 0 for value in inputs.field_expected_value_credits.values())
        ):
            return _fail("invalid_sumble_field_plan", "field expected values must be positive")
        if inputs.provider_credit_cap <= 0:
            return _fail("invalid_sumble_budget", "provider credit cap must be positive")
        async with self._conn_factory() as conn:
            run = await get_project_run(conn, run_id)
        if run is None or run.workspace_id != ctx.workspace_id:
            return _fail("run_not_found", "no such project run")
        if run.status is not ProjectRunStatus.ACTIVE or run.phase is not ProjectPhase.DEEP:
            return _fail(
                "sumble_account_gap_phase_ineligible",
                "Sumble account-gap enrichment requires an active deep-phase run",
            )
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        assert isinstance(inputs, EnrichAccountGapsInput)
        return ToolEstimate(
            cost_cents=Decimal(inputs.provider_credit_cap) * self._cents_per_credit,
            detail={
                "basis": "sumble_explicit_provider_credit_cap",
                "provider_units": str(inputs.provider_credit_cap),
                "unbounded_tech_approved": inputs.allow_unbounded_tech,
            },
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, EnrichAccountGapsInput)
        assert self._starter is not None
        run_id = _parse_run_id(inputs.project_run_id)
        account_id = _parse_entity_id(inputs.account_entity_id)
        assert run_id is not None and account_id is not None
        try:
            result = await self._starter.start(
                workspace_id=ctx.workspace_id,
                project_run_id=run_id,
                account_id=account_id,
                field_expected_value_credits=inputs.field_expected_value_credits,
                provider_credit_cap=inputs.provider_credit_cap,
                allow_unbounded_tech=inputs.allow_unbounded_tech,
            )
        except SumbleAccountGapEligibilityError as exc:
            raise PreconditionFailed(_fail("sumble_account_gap_ineligible", str(exc))) from exc
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "operation_id": str(result.operation.operation_id),
                "account_entity_id": str(result.operation.request.account_id),
                "state": result.operation.state.value,
                "outcome": result.outcome.value,
                "provider_units_reserved": str(result.operation.provider_units_reserved),
                "provider_units_charged": str(result.operation.provider_units_charged),
                "claim_ids": list(result.claim_ids),
            },
        )


class EnrichSelectedAccountsTool(Tool):
    """Explicit post-checkpoint E1 spend over an exact selected-account/field set."""

    name = "enrich_selected_accounts"
    input_model = EnrichSelectedAccountsInput
    output_model = TargetedEnrichmentOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity=(
            "project run + exact discovery seal + selected accounts + field policy window"
        ),
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_run_id", "account_entity_ids", "field_keys")
    )
    pin_requirements = (
        "project_run",
        "discovery_seal",
        "tier_checkpoint",
        "field_policy",
        "budget_policy",
    )

    def __init__(
        self,
        *,
        starter: TargetedEnrichmentStarter | None,
        conn_factory: ConnFactory,
    ) -> None:
        self._starter = starter
        self._conn_factory = conn_factory

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, EnrichSelectedAccountsInput)
        if self._starter is None:
            return _fail(
                "targeted_enrichment_not_configured",
                "targeted Exa enrichment is disabled or unavailable",
            )
        run_id = _parse_run_id(inputs.project_run_id)
        if run_id is None:
            return _fail("run_not_found", "no such project run")
        async with self._conn_factory() as conn:
            run = await get_project_run(conn, run_id)
        if run is None or run.workspace_id != ctx.workspace_id:
            return _fail("run_not_found", "no such project run")
        if run.status is not ProjectRunStatus.ACTIVE or run.phase is not ProjectPhase.DEEP:
            return _fail(
                "targeted_enrichment_phase_ineligible",
                "targeted enrichment requires an active project run in deep phase",
            )
        account_ids = tuple(_parse_entity_id(value) for value in inputs.account_entity_ids)
        if not account_ids or any(value is None for value in account_ids):
            return _fail("invalid_account_set", "account ids must be non-empty UUIDs")
        if len(account_ids) != len(set(account_ids)):
            return _fail("invalid_account_set", "account ids must be unique")
        if len(account_ids) > DEFAULT_EXA_TARGETED_ENRICHMENT_POLICY.maximum_accounts:
            return _fail("invalid_account_set", "account count exceeds targeted policy")
        try:
            fields = approved_targeted_field_plans(inputs.field_keys)
        except ExaTargetedEligibilityError as exc:
            return _fail("invalid_field_set", str(exc))
        if len(fields) > DEFAULT_EXA_TARGETED_ENRICHMENT_POLICY.maximum_fields:
            return _fail("invalid_field_set", "field count exceeds targeted policy")
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        assert isinstance(inputs, EnrichSelectedAccountsInput)
        try:
            fields = approved_targeted_field_plans(inputs.field_keys)
        except ExaTargetedEligibilityError:
            return ToolEstimate(cost_cents=Decimal(0), detail={"basis": "invalid_field_set"})
        units = DEFAULT_EXA_WEBSETS_PRICING.maximum_targeted_import_units(
            account_count=len(set(inputs.account_entity_ids)),
            formats=[field.format for field in fields],
        )
        return ToolEstimate(
            cost_cents=DEFAULT_EXA_WEBSETS_PRICING.monetary_value(units),
            detail={
                "basis": "exa_targeted_maximum_credit_allocation",
                "provider_units": str(units),
            },
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, EnrichSelectedAccountsInput)
        assert self._starter is not None
        run_id = _parse_run_id(inputs.project_run_id)
        assert run_id is not None
        account_ids = tuple(_parse_entity_id(value) for value in inputs.account_entity_ids)
        assert all(value is not None for value in account_ids)
        result = await self._starter.start(
            workspace_id=ctx.workspace_id,
            project_run_id=run_id,
            account_ids=cast(tuple[EntityId, ...], account_ids),
            field_keys=inputs.field_keys,
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "operation_id": str(result.operation.operation_id),
                "state": result.operation.state.value,
                "outcome": result.outcome.value,
                "provider_units_reserved": str(result.operation.provider_units_reserved),
                "cost_cents_reserved": str(result.operation.cost_cents_reserved),
            },
        )


class SubmitTierCheckpointTool(_CapabilityTool):
    name = "submit_tier_checkpoint"
    input_model = SubmitTierCheckpointInput
    output_model = TierCheckpointOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project_run + tier-checkpoint phase ledger",
    )
    effect_class = ToolEffectClass.STEERING
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_run_id",))
    pin_requirements: ClassVar[tuple[str, ...]] = ("project_run", "tier_policy")

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> dict[str, object]:
        assert isinstance(inputs, SubmitTierCheckpointInput)
        return await self._run_audit_snapshot(inputs.project_run_id, ctx)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, SubmitTierCheckpointInput)
        run = await self._load_run(inputs.project_run_id, ctx)
        if run is None:
            return _fail("run_not_found", "no such project run")
        async with self._conn_factory() as conn:
            checkpoint = await get_checkpoint(conn, run.id, run.phase)
        # S9: mirror ``ProjectRun.submit_checkpoint``'s acceptance exactly (durable/project.py):
        # it accepts (a) an AWAITING_INPUT checkpoint at the run's current phase, or (b) the
        # crash-recovery case — a COMMITTED-but-not-transitioned checkpoint with the run still
        # PAUSED or ACTIVE (a crash mid-approve-finalize; re-submitting re-runs the idempotent
        # finalize). Refusing (b) here would make the tool refuse a submit the machine would heal.
        awaiting = (
            checkpoint is not None and checkpoint.status == PhaseCheckpointStatus.AWAITING_INPUT
        )
        self_heal = (
            checkpoint is not None
            and checkpoint.status == PhaseCheckpointStatus.COMMITTED
            and run.status in (ProjectRunStatus.PAUSED, ProjectRunStatus.ACTIVE)
        )
        if not (awaiting or self_heal):
            return _fail(
                "checkpoint_not_awaiting",
                "the run is not suspended at the tier checkpoint gate",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, SubmitTierCheckpointInput)
        run_id = _parse_run_id(inputs.project_run_id)
        assert run_id is not None
        decision = cast(dict[str, JsonValue], inputs.decision)
        row = await self._run.submit_checkpoint(run_id, decision=decision)
        # Tier approval exposes the eligible account set but is not authorization to spend on
        # account-deep research.  Leave an ACTIVE run parked at DEEP; launch_account_deep@1 creates
        # the separate exact-set receipt and is the only tool that re-enqueues this boundary.
        if row.phase is not ProjectPhase.DEEP:
            routed = (
                await self._project_execution_router.resume_owned(run_id, actor=ctx.actor)
                if self._project_execution_router is not None
                else False
            )
            if not routed and self._queue is not None:
                await enqueue_run_drive(
                    run_id,
                    queue=self._queue,
                    conn_factory=self._conn_factory,
                )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"project_run_id": str(row.id), "phase": row.phase.value},
        )


class SubmitProjectCheckpointTool(SubmitTierCheckpointTool):
    """Generic human/supervisor checkpoint decision for non-tier Recipe #1 waits."""

    name = "submit_project_checkpoint"
    pin_requirements: ClassVar[tuple[str, ...]] = ("project_run",)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, SubmitTierCheckpointInput)
        run = await self._load_run(inputs.project_run_id, ctx)
        if run is None:
            return _fail("run_not_found", "no such project run")
        async with self._conn_factory() as conn:
            checkpoint = await get_checkpoint(conn, run.id, run.phase)
        awaiting = (
            checkpoint is not None and checkpoint.status == PhaseCheckpointStatus.AWAITING_INPUT
        )
        self_heal = (
            checkpoint is not None
            and checkpoint.status == PhaseCheckpointStatus.COMMITTED
            and run.status in (ProjectRunStatus.PAUSED, ProjectRunStatus.ACTIVE)
        )
        if not (awaiting or self_heal):
            return _fail(
                "checkpoint_not_awaiting",
                "the run is not suspended at an actionable project checkpoint",
            )
        return ()


# =============================================================================================
# full account-deep fleet launch (set-scoped O2 capability)
# =============================================================================================


class LaunchAccountDeepTool(_CapabilityTool):
    """Authorize and enqueue the existing account-deep fleet for one exact selected set.

    The confirmed directive remains planning state.  This tool creates the distinct immutable
    launch receipt only after recomputing the directive-derived estimate, proving the selected
    accounts are members, and verifying that a committee source/preparer is actually composed.
    """

    name = "launch_account_deep"
    model_description = (
        "Create or exactly replay the immutable set-scoped account-deep launch receipt only after "
        "an explicit human go-ahead over the confirmed directive, exact account set, and reviewed "
        "estimate. A successful result means launched/enqueued or replayed; it never means the "
        "account or committee research has completed."
    )
    input_model = LaunchAccountDeepInput
    output_model = AccountDeepLaunchOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project_run + exact directive pin + selected account set + budget",
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "project_run_id",
            "research_directive_id",
            "account_entity_ids",
            "approved_budget_cap_cents",
            "expected_estimated_cost_cents",
        )
    )
    pin_requirements = ("project_run", "research_directive", "deep_policy")

    @staticmethod
    def _ids(
        inputs: LaunchAccountDeepInput,
    ) -> tuple[ProjectRunId | None, ResearchDirectiveId | None, tuple[EntityId, ...] | None]:
        run_id = _parse_run_id(inputs.project_run_id)
        try:
            directive_id = ResearchDirectiveId(UUID(inputs.research_directive_id))
        except (ValueError, AttributeError, TypeError):
            directive_id = None
        accounts = tuple(_parse_entity_id(value) for value in inputs.account_entity_ids)
        if any(value is None for value in accounts):
            return run_id, directive_id, None
        return run_id, directive_id, cast(tuple[EntityId, ...], accounts)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, LaunchAccountDeepInput)
        if not self._account_deep_full_unit_available:
            return _fail(
                "committee_capability_not_configured",
                "full account-deep launch requires at least one governed committee source",
            )
        if ctx.action_ref is None:
            return _fail(
                "launch_action_ref_missing",
                "account-deep launch requires the captured user/agent action reference",
            )
        run_id, directive_id, account_ids = self._ids(inputs)
        if run_id is None:
            return _fail("run_not_found", "no such project run")
        if directive_id is None:
            return _fail("research_directive_not_found", "no such research directive")
        if account_ids is None:
            return _fail("invalid_account_id", "one or more account ids are malformed")
        try:
            async with self._conn_factory() as conn:
                await preview_account_deep_launch(
                    conn,
                    workspace_id=ctx.workspace_id,
                    project_run_id=run_id,
                    directive_id=directive_id,
                    account_entity_ids=account_ids,
                    approved_budget_cap_cents=inputs.approved_budget_cap_cents,
                    expected_estimated_cost_cents=inputs.expected_estimated_cost_cents,
                )
        except AccountDeepLaunchConflict as exc:
            return _fail("account_deep_launch_conflict", str(exc))
        except AccountDeepLaunchInvalid as exc:
            return _fail("account_deep_launch_invalid", str(exc))
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        assert isinstance(inputs, LaunchAccountDeepInput)
        return ToolEstimate(
            cost_cents=inputs.expected_estimated_cost_cents,
            detail={"selected_accounts": len(inputs.account_entity_ids)},
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, LaunchAccountDeepInput)
        run_id, directive_id, account_ids = self._ids(inputs)
        assert run_id is not None and directive_id is not None and account_ids is not None
        assert ctx.action_ref is not None
        async with self._conn_factory() as conn:
            created = await create_account_deep_launch(
                conn,
                workspace_id=ctx.workspace_id,
                project_run_id=run_id,
                directive_id=directive_id,
                account_entity_ids=account_ids,
                approved_budget_cap_cents=inputs.approved_budget_cap_cents,
                expected_estimated_cost_cents=inputs.expected_estimated_cost_cents,
                created_by=ctx.actor_id or ctx.actor,
                source_operation_id=ctx.operation_id,
                source_action_ref=ctx.action_ref,
            )
        routed = (
            await self._project_execution_router.resume_owned(run_id, actor=ctx.actor)
            if self._project_execution_router is not None
            else False
        )
        enqueued = routed
        if not routed and self._queue is not None:
            await enqueue_run_drive(
                run_id,
                queue=self._queue,
                conn_factory=self._conn_factory,
            )
            enqueued = True
        launch = created.launch
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "launch_id": str(launch.id),
                "project_run_id": str(launch.project_run_id),
                "research_directive_id": str(launch.directive_id),
                "selected_accounts": len(created.account_entity_ids),
                "estimated_cost_cents": str(launch.estimated_cost_cents),
                "approved_budget_cap_cents": str(launch.approved_budget_cap_cents),
                "replayed": created.replayed,
                "enqueued": enqueued,
            },
        )


# =============================================================================================
# deep / committee / contact tools (per-account capabilities)
# =============================================================================================


class RunDeepAccountTool(_CapabilityTool):
    """Deep-profile one account. **Account workspace-scoping is fail-closed** ([B3×research],
    resolved 2026-07-23): the account is loaded through :meth:`_load_account`, so a cross-workspace
    account refuses ``account_not_found`` — the same shape a truly-absent id gets (no existence
    leak) — before any deep spend runs."""

    name = "run_deep_account"
    input_model = RunDeepAccountInput
    output_model = DeepAccountOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="account + RunId(operation_id) + project/account ledgers",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "account_entity_id",
            "icp_key",
            "tier",
            "project_run_id",
        )
    )
    pin_requirements = ("account", "icp", "field_registry", "source_registry", "deep_policy")

    async def _resolve_spec(
        self, inputs: RunDeepAccountInput, ctx: ToolContext
    ) -> tuple[ICPSpec | None, ProjectRunRow | None, tuple[PreconditionFailure, ...]]:
        """(spec, run, failures): with a ``project_run_id`` the run's pinned spec (S3 — the version
        the machine advanced on), else the active ICP for ``icp_key``."""
        if inputs.project_run_id is not None:
            run = await self._load_run(inputs.project_run_id, ctx)
            if run is None:
                return None, None, _fail("run_not_found", "no such project run")
            spec = await self._load_pinned_spec(run)
            if spec is None:
                return (
                    None,
                    run,
                    _fail(
                        "icp_version_missing",
                        f"no pinned ICP {run.icp_key!r} v{run.icp_version} for this run",
                    ),
                )
            return spec, run, ()
        spec = await self._load_active_spec(ctx.workspace_id, inputs.icp_key)
        if spec is None:
            return None, None, _fail("no_active_icp", f"no active ICP {inputs.icp_key!r}")
        return spec, None, ()

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, RunDeepAccountInput)
        spec, run, failures = await self._resolve_spec(inputs, ctx)
        if failures:
            return failures
        assert spec is not None
        # S8: validate the tier against the known bands — the run's committed cutoffs when a run id
        # is supplied (the tier vocabulary the checkpoint approved), else the ICP rubric's proposed
        # cutoff bands. An empty band set cannot validate, so it refuses any tier (fail-closed: a
        # deep spend against no known band is never silently accepted). The run row carries raw
        # JSON cutoffs — parsed with the same coercion the deep composition uses (garbage → None).
        cutoffs: TierCutoffs | None = None
        if run is not None and run.tier_cutoffs:
            try:
                cutoffs = TierCutoffs.model_validate(run.tier_cutoffs)
            except (ValueError, TypeError):
                cutoffs = None
        if cutoffs is None:
            rubric = rubric_from_slot(spec.scoring_rubric)
            cutoffs = rubric.tier_cutoffs if rubric is not None else None
        known = frozenset(b.tier for b in cutoffs.bands) if cutoffs is not None else frozenset()
        if inputs.tier not in known:
            return _fail(
                "invalid_tier",
                f"tier {inputs.tier!r} is not a known band (known: {sorted(known) or 'none'})",
            )
        async with ctx.conn_factory() as conn:
            account = await self._load_account(self.name, inputs.account_entity_id, ctx, conn)
        if account is None:
            return _fail("account_not_found", "no such account entity")
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        # N2: a defensible static prior — the Doc C §5 per-account Pass-B band for the requested
        # tier (TieringConfig.band_cents; zero for a non-deep-eligible tier). Policy-as-data: the
        # default bands, not a per-client override (the runner surfaces this as a prior, never a
        # commitment).
        assert isinstance(inputs, RunDeepAccountInput)
        band = DEFAULT_TIERING_CONFIG.band_cents(inputs.tier)
        return ToolEstimate(
            cost_cents=band, detail={"basis": "pass_b_band_cents", "tier": inputs.tier}
        )

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, RunDeepAccountInput)
        entity = _parse_entity_id(inputs.account_entity_id)
        assert entity is not None
        spec, run, failures = await self._resolve_spec(inputs, ctx)
        assert spec is not None and not failures  # narrowed by preconditions
        # [B3×research]: preconditions loaded the account fail-closed to ctx.workspace_id via
        # _load_account (cross-workspace → account_not_found), so invoke is only reached for an
        # in-workspace account.
        # S1: budget-visible spend — with a run supplied, thread its id + remaining headroom into
        # the deep profile so the spend lands against the run's cap.
        remaining: CostCents | None = None
        if run is not None and run.budget_cap_cents is not None:
            remaining = max(Decimal(0), run.budget_cap_cents - run.spent_cents)
        # S1: the Doc C §4 per-entity single-flight lock around the account-scoped work, and the
        # M9.1 concrete pre-spend gate threaded into every claim-producing path.
        async with self._lock_factory(entity):
            result = await profile_account(
                account_entity_id=entity,
                spec=spec,
                tier=inputs.tier,
                run_id=RunId(ctx.operation_id),
                project_run_id=run.id if run is not None else None,
                budget_cap_cents=remaining,
                workspace_id=ctx.workspace_id,
                gateway=self._require_gateway(),
                pre_spend_gate=self._pre_spend_gate,
                session_factory=self._conn_factory,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "account_entity_id": str(result.account_entity_id),
                "run_id": str(result.run_id),
                "status": result.status.value,
                "claim_refs": [str(c) for c in result.claim_refs],
            },
        )


class ResolveCommitteeTool(_CapabilityTool):
    """Resolve one account's buying committee. **Account workspace-scoping is fail-closed**
    ([B3×research], resolved 2026-07-23): the account is loaded through :meth:`_load_account`, so a
    cross-workspace account refuses ``account_not_found`` (the same shape a truly-absent id gets —
    no existence leak) before any committee walk runs."""

    name = "resolve_committee"
    input_model = ResolveCommitteeInput
    output_model = CommitteeOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="account + RunId(operation_id)",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(safe_display_fields=("account_entity_id", "icp_key"))
    pin_requirements = ("account", "icp", "source_registry", "committee_policy")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ResolveCommitteeInput)
        async with ctx.conn_factory() as conn:
            account = await self._load_account(self.name, inputs.account_entity_id, ctx, conn)
        if account is None:
            return _fail("account_not_found", "no such account entity")
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        # N2: committee discovery has no tier input; the conservative static prior is the largest
        # configured Pass-B band (committee resolution is a component of a high-tier deep run).
        band = max(DEFAULT_TIERING_CONFIG.pass_b_bands_cents.values(), default=Decimal(0))
        return ToolEstimate(cost_cents=band, detail={"basis": "max_pass_b_band_cents"})

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ResolveCommitteeInput)
        entity = _parse_entity_id(inputs.account_entity_id)
        assert entity is not None
        # [B3×research]: preconditions loaded the account fail-closed to ctx.workspace_id via
        # _load_account, so invoke is only reached for an in-workspace account.
        spec = (
            await self._load_active_spec(ctx.workspace_id, inputs.icp_key)
            if inputs.icp_key is not None
            else None
        )
        # S1: single-flight the account-scoped committee walk + gate each enumeration (M9.1).
        async with self._lock_factory(entity), self._conn_factory() as conn:
            result = await discover_committee(
                conn,
                account_entity_id=entity,
                run_id=RunId(ctx.operation_id),
                workspace_id=ctx.workspace_id,
                sources=self._committee_sources,
                gateway=self._require_gateway(),
                spec=spec,
                pre_spend_gate=self._pre_spend_gate,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "account_entity_id": str(result.account_entity_id),
                "members": len(result.members),
                "admitted": result.admitted,
            },
        )


class ProfileContactTool(_CapabilityTool):
    """Profile one committee member. **Account workspace-scoping is fail-closed** ([B3×research],
    resolved 2026-07-23): the parent account is loaded through :meth:`_load_account` (before the
    contact check), so a cross-workspace account refuses ``account_not_found`` (the same shape a
    truly-absent id gets — no existence leak) before any contact spend runs."""

    name = "profile_contact"
    input_model = ProfileContactInput
    output_model = ContactProfileOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="contact + account + RunId(operation_id)",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("contact_entity_id", "account_entity_id", "tier", "icp_key")
    )
    pin_requirements = ("account", "contact", "icp", "field_registry", "source_registry")

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        # N2: the per-account Pass-B band for the requested tier as an upper-bound static prior
        # (contact profiling is one component of that band's per-account deep work).
        assert isinstance(inputs, ProfileContactInput)
        band = DEFAULT_TIERING_CONFIG.band_cents(inputs.tier)
        return ToolEstimate(
            cost_cents=band, detail={"basis": "pass_b_band_cents", "tier": inputs.tier}
        )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ProfileContactInput)
        contact = _parse_entity_id(inputs.contact_entity_id)
        if contact is None:
            return _fail("contact_not_found", "contact_entity_id is not a valid entity id")
        async with ctx.conn_factory() as conn:
            account = await self._load_account(self.name, inputs.account_entity_id, ctx, conn)
            if account is None:
                return _fail("account_not_found", "no such account entity")
            # The tool profiles a committee member *of* this in-workspace account, so the contact
            # must resolve under it. A missing contact, a foreign-workspace contact, or a contact of
            # a different account all collapse to the same not-found shape (no existence leak — a
            # cross-account/cross-workspace contact is indistinguishable from an absent one).
            loaded = await get_contact(conn, contact)
            if loaded is None or loaded.account_entity_id != account.id:
                return _fail("contact_not_found", "no such contact entity")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ProfileContactInput)
        account = _parse_entity_id(inputs.account_entity_id)
        contact = _parse_entity_id(inputs.contact_entity_id)
        assert account is not None and contact is not None
        # [B3×research]: preconditions loaded the parent account fail-closed to ctx.workspace_id via
        # _load_account, so invoke is only reached for an in-workspace account.
        spec = (
            await self._load_active_spec(ctx.workspace_id, inputs.icp_key)
            if inputs.icp_key is not None
            else None
        )
        # S1: single-flight the account-scoped contact work + gate each field spend (M9.1).
        async with self._lock_factory(account), self._conn_factory() as conn:
            result = await profile_contact(
                conn,
                contact_entity_id=contact,
                account_entity_id=account,
                run_id=RunId(ctx.operation_id),
                workspace_id=ctx.workspace_id,
                tier=inputs.tier,
                spec=spec,
                pre_spend_gate=self._pre_spend_gate,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "contact_entity_id": str(result.contact_entity_id),
                "fields_filled": result.fields_filled,
                "profile_claims": len(result.profile_claims),
            },
        )


class GovernedProfileContactTool(_CapabilityTool):
    """C6 independent-contact entry: exact project run, selection, preparation, then claims."""

    name = "profile_contact"
    version = "2"
    input_model = GovernedProfileContactInput
    output_model = GovernedContactProfileOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project run + account + selected contact + immutable provider receipts",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=(
            "project_run_id",
            "contact_entity_id",
            "account_entity_id",
        )
    )
    pin_requirements = (
        "project_run",
        "account",
        "contact",
        "research_directive",
        "contact_research_selection",
        "field_registry",
        "source_registry",
    )

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        return ToolEstimate(
            cost_cents=Decimal(0),
            detail={"basis": "durable selection and provider-specific reservations"},
        )

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, GovernedProfileContactInput)
        if self._independent_contact_research is None:
            return _fail(
                "contact_research_not_composed",
                "provider-neutral contact research is unavailable",
            )
        run = await self._load_run(inputs.project_run_id, ctx)
        if run is None:
            return _fail("run_not_found", "no such project run")
        contact = _parse_entity_id(inputs.contact_entity_id)
        if contact is None:
            return _fail("contact_not_found", "no such contact entity")
        async with ctx.conn_factory() as conn:
            account = await self._load_account(
                self.name,
                inputs.account_entity_id,
                ctx,
                conn,
            )
            if account is None:
                return _fail("account_not_found", "no such account entity")
            loaded = await get_contact(conn, contact)
            if loaded is None or loaded.account_entity_id != account.id:
                return _fail("contact_not_found", "no such contact entity")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, GovernedProfileContactInput)
        runner = self._independent_contact_research
        assert runner is not None
        project_run_id = _parse_run_id(inputs.project_run_id)
        account = _parse_entity_id(inputs.account_entity_id)
        contact = _parse_entity_id(inputs.contact_entity_id)
        assert project_run_id is not None and account is not None and contact is not None
        result = await runner.run(
            workspace_id=ctx.workspace_id,
            project_run_id=project_run_id,
            account_entity_id=account,
            contact_entity_id=contact,
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "contact_entity_id": str(result.contact_entity_id),
                "project_run_id": str(result.project_run_id),
                "status": result.preparation.status.value,
                "selection_ref": result.selection_ref,
                "claim_refs": [str(claim_id) for claim_id in result.claim_refs],
                "fields_filled": result.fields_filled,
            },
        )


class ComposeContactContentHandoffTool(Tool):
    """C7 read-only account x contact x persona projection for governed content consumers."""

    name = "compose_contact_content_handoff"
    version = "1"
    input_model = ComposeContactContentHandoffInput
    output_model = ContactContentHandoffOutput
    model_description = (
        "Read the current reference-only contact research handoff for one exact project run and "
        "account. This never calls a research provider and never returns raw email or phone values."
    )
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="repeatable-read governed C7 projection",
        external_boundary=ExternalReplayBoundary.NONE,
    )
    effect_class = ToolEffectClass.READ
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_id", "project_run_id", "account_entity_id", "product_id")
    )
    pin_requirements = (
        "project_run",
        "account",
        "contact_research_selection",
        "research_view",
        "use_policy",
    )

    def __init__(self, *, service: ContactContentHandoffService | None) -> None:
        self._service = service

    async def preconditions(
        self,
        inputs: ToolInput,
        ctx: ToolContext,
    ) -> Sequence[PreconditionFailure]:
        del ctx
        assert isinstance(inputs, ComposeContactContentHandoffInput)
        if self._service is None:
            return _fail(
                "contact_content_handoff_not_composed",
                "the governed C7 contact handoff reader is unavailable",
            )
        if _parse_run_id(inputs.project_run_id) is None:
            return _fail("run_not_found", "no such project run")
        if _parse_entity_id(inputs.account_entity_id) is None:
            return _fail("account_not_found", "no such account entity")
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ComposeContactContentHandoffInput)
        service = self._service
        assert service is not None
        project_run_id = _parse_run_id(inputs.project_run_id)
        account_id = _parse_entity_id(inputs.account_entity_id)
        assert project_run_id is not None and account_id is not None
        handoff: ContactContentHandoff = await service.compose(
            workspace_id=ctx.workspace_id,
            project_id=inputs.project_id,
            project_run_id=project_run_id,
            account_entity_id=account_id,
            product_id=inputs.product_id,
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"handoff": handoff.model_dump(mode="json")},
        )


def _successor_scope_matches(
    successor: ContactResearchSelection,
    predecessor: ContactResearchSelection,
) -> bool:
    current = predecessor.body
    proposed = successor.body
    return bool(
        successor.selection_id != predecessor.selection_id
        and proposed.workspace_id == current.workspace_id
        and proposed.project_id == current.project_id
        and proposed.project_run_id == current.project_run_id
        and proposed.account_entity_id == current.account_entity_id
        and proposed.research_directive == current.research_directive
        and proposed.policy == current.policy
        and proposed.source_profile_ref == current.source_profile_ref
        and proposed.jurisdiction_policy_ref == current.jurisdiction_policy_ref
        and proposed.use_policy_ref == current.use_policy_ref
        and proposed.retention_policy_ref == current.retention_policy_ref
    )


class ApproveContactResearchSelectionTool(Tool):
    """Persist a human-approved, exact successor to the current contact selection head."""

    name = "approve_contact_research_selection"
    version = "1"
    input_model = ApproveContactResearchSelectionInput
    output_model = ContactResearchSelectionApprovalOutput
    model_description = (
        "Approve one exact content-addressed successor to the current contact-research selection. "
        "Agents can prepare the reviewed receipt but only an authenticated human can approve it."
    )
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="database-backed contact selection approval receipt",
        operation_id_required=True,
        external_boundary=ExternalReplayBoundary.NONE,
    )
    effect_class = ToolEffectClass.STEERING
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("account_run_id", "predecessor_selection_id")
    )
    pin_requirements = (
        "project_run",
        "account",
        "research_directive",
        "contact_research_selection",
    )

    def __init__(self, *, conn_factory: ConnFactory = transaction) -> None:
        self._conn_factory = conn_factory

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> dict[str, object]:
        assert isinstance(inputs, ApproveContactResearchSelectionInput)
        predecessor_id = _parse_contact_selection_id(inputs.predecessor_selection_id)
        exists = False
        current = False
        if predecessor_id is not None:
            async with self._conn_factory() as conn:
                try:
                    predecessor = await get_contact_research_selection(
                        conn,
                        workspace_id=ctx.workspace_id,
                        selection_id=predecessor_id,
                    )
                except ContactResearchSelectionNotFound:
                    predecessor = None
                if predecessor is not None:
                    exists = True
                    head = await latest_contact_research_selection(
                        conn,
                        workspace_id=ctx.workspace_id,
                        project_run_id=predecessor.body.project_run_id,
                        account_id=predecessor.body.account_entity_id,
                        include_cancelled=True,
                    )
                    current = head is not None and head.selection_id == predecessor_id
        return {
            "predecessor_selection_id": inputs.predecessor_selection_id,
            "predecessor_exists": exists,
            "predecessor_is_current": current,
            "successor_selection_id": str(inputs.selection.selection_id),
            "successor_selection_sha256": inputs.selection.selection_sha256,
        }

    async def preconditions(
        self,
        inputs: ToolInput,
        ctx: ToolContext,
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ApproveContactResearchSelectionInput)
        authority = require_human_authority(
            ctx,
            action_ref_required=True,
            message=(
                "selection approval requires authenticated human identity and action reference"
            ),
        )
        if authority:
            return authority
        if ctx.actor_id is None or ctx.action_ref is None:
            return _fail(
                "trusted_human_receipt_required",
                "selection approval requires authenticated human identity and action reference",
            )
        selection = inputs.selection
        if (
            selection.body.workspace_id != ctx.workspace_id
            or selection.body.approved_by != ctx.actor_id
        ):
            return _fail(
                "trusted_human_receipt_mismatch",
                "selection scope or approval identity differs from the invocation context",
            )
        predecessor_id = _parse_contact_selection_id(inputs.predecessor_selection_id)
        account_run_id = _parse_account_run_id(inputs.account_run_id)
        if predecessor_id is None or account_run_id is None:
            return _fail("contact_selection_not_found", "no such contact selection authority")
        async with self._conn_factory() as conn:
            try:
                predecessor = await get_contact_research_selection(
                    conn,
                    workspace_id=ctx.workspace_id,
                    selection_id=predecessor_id,
                )
            except ContactResearchSelectionNotFound:
                return _fail("contact_selection_not_found", "no such contact selection authority")
            current = await latest_contact_research_selection(
                conn,
                workspace_id=ctx.workspace_id,
                project_run_id=predecessor.body.project_run_id,
                account_id=predecessor.body.account_entity_id,
                include_cancelled=True,
            )
        if current is None or current.selection_id != predecessor_id:
            return _fail(
                "contact_selection_not_current",
                "the named predecessor is not the current contact selection head",
            )
        if not _successor_scope_matches(selection, predecessor):
            return _fail(
                "contact_selection_scope_mismatch",
                "the successor crosses its predecessor project, account, or policy authority",
            )
        return ()

    def estimate(self, inputs: ToolInput) -> ToolEstimate:
        del inputs
        return ToolEstimate.free()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ApproveContactResearchSelectionInput)
        if ctx.actor != "human" or ctx.actor_id is None or ctx.action_ref is None:
            raise ValueError("trusted human selection approval receipt is missing")
        predecessor_id = _parse_contact_selection_id(inputs.predecessor_selection_id)
        account_run_id = _parse_account_run_id(inputs.account_run_id)
        if predecessor_id is None or account_run_id is None:
            raise ValueError("contact selection authority is malformed")
        async with self._conn_factory() as conn:
            stored = await store_contact_research_selection(
                conn,
                inputs.selection,
                account_run_id=account_run_id,
                predecessor_id=predecessor_id,
                approval=ContactResearchSelectionApprovalAuthority(
                    kind=ContactResearchSelectionApprovalKind.HUMAN_SUCCESSOR,
                    operation_id=ctx.operation_id,
                    approved_by=ctx.actor_id,
                    action_ref=ctx.action_ref,
                    approved_at=inputs.selection.body.approved_at,
                ),
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "selection_id": str(stored.selection_id),
                "selection_sha256": stored.selection_sha256,
                "predecessor_selection_id": str(predecessor_id),
                "approval_ref": f"contact-research-selection-approval:{ctx.operation_id}",
            },
        )


# =============================================================================================
# verification / handoff tools
# =============================================================================================


class RunVerificationTool(_CapabilityTool):
    name = "run_verification"
    input_model = RunVerificationInput
    output_model = PhaseAccountsOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project_run + verification phase/account ledgers",
        external_boundary=ExternalReplayBoundary.AT_LEAST_ONCE,
    )
    effect_class = ToolEffectClass.SPEND
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_run_id",))
    pin_requirements = ("project_run", "icp", "verification_policy", "model_prompt")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, RunVerificationInput)
        run = await self._load_run(inputs.project_run_id, ctx)
        if run is None:
            return _fail("run_not_found", "no such project run")
        if await self._load_pinned_spec(run) is None:
            return _fail(
                "icp_version_missing",
                f"no pinned ICP {run.icp_key!r} v{run.icp_version} for this run",
            )
        # M8D R11.3, defense in depth: refuse *before* the phase runs when the run has no
        # account-research fleet run, so an operator gets an actionable refusal rather than the
        # resolver's exception mid-phase — and never the pre-R11 silent ``accounts_processed=0``
        # success. The resolver still raises on its own (a run whose fleet vanished between these
        # two reads is a failure, not an empty success).
        async with self._conn_factory() as conn:
            fleet = await read_latest_account_fleet_for_project_run(
                conn, UUID(str(run.id)), workspace_id=run.workspace_id
            )
        if fleet is None or fleet.project_id != run.project_id:
            return _fail(
                "entity_research_run_missing",
                "no M8D account-research fleet run is bound to this project run; launch account "
                "research through the confirmed launch_account_research@1 action, then verify",
            )
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, RunVerificationInput)
        run = await self._load_run(inputs.project_run_id, ctx)
        assert run is not None
        handler = self._wrap_snapshots(
            build_verification_phase_handler(
                gateway=self._gateway,
                # R11.3: the researched-account set comes from the run's latest human-confirmed
                # fleet run, not the quarantined ``account_deep_launch`` ledger.
                account_resolver=build_entity_research_account_resolver(
                    session_factory=self._conn_factory
                ),
                session_factory=self._conn_factory,
                verification_enabled=self._settings.verification_enabled,
            )
        )
        result = await handler.run(self._phase_ctx(run, ProjectPhase.VERIFICATION))
        # References must match ``PhaseAccountsOutput`` exactly (extras are a contract violation).
        # This result used to add ``verification_enabled``, which the schema has never carried — an
        # unreachable bug until R11.3 gave the tool an account set it could actually succeed on.
        # The toggle state is still recorded on the phase result payload (and on the VERIFICATION
        # checkpoint when the state machine drives it); surfacing it *here* needs a new pinned
        # output schema — the reviewed agent profiles pin ``run_verification@1``'s
        # ``output_schema_sha256`` — which is a governed change, not this slice's.
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "status": result.status.value,
                "accounts_processed": result.accounts_processed,
            },
        )


class ComposeHandoffTool(_CapabilityTool):
    name = "compose_handoff"
    input_model = ComposeHandoffInput
    output_model = HandoffOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="project_run handoff projection",
    )
    effect_class = ToolEffectClass.READ
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_run_id",))
    pin_requirements = ("project_run",)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ComposeHandoffInput)
        run = await self._load_run(inputs.project_run_id, ctx)
        if run is None:
            return _fail("run_not_found", "no such project run")
        async with self._conn_factory() as conn:
            checkpoint = await get_checkpoint(conn, run.id, ProjectPhase.HANDOFF)
        if checkpoint is None:
            return _fail("handoff_not_reached", "the run has not reached the HANDOFF phase yet")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ComposeHandoffInput)
        run = await self._load_run(inputs.project_run_id, ctx)
        assert run is not None
        async with self._conn_factory() as conn:
            checkpoint = await get_checkpoint(conn, run.id, ProjectPhase.HANDOFF)
            handoffs = await list_handoffs_for_run(
                conn, workspace_id=run.workspace_id, project_run_id=run.id
            )
        # Surface the slice-1 gap marker (spec §2 amendment): a HANDOFF that completed WITHOUT
        # emitting narratives (the composer's documented M12-integration gap) carries
        # ``narrative_emit_skipped`` in its checkpoint payload — so a gap-completed run is
        # distinguishable from a truly-handed-off one by any reader of this tool result.
        payload = checkpoint.payload if checkpoint is not None else {}
        narrative_emit_skipped = bool(payload.get(NARRATIVE_EMIT_SKIPPED_KEY, False))
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "project_run_id": str(run.id),
                "handoffs": len(handoffs),
                NARRATIVE_EMIT_SKIPPED_KEY: narrative_emit_skipped,
            },
        )


# =============================================================================================
# estimate tool
# =============================================================================================


class EstimateProjectTool(_CapabilityTool):
    name = "estimate_project"
    input_model = EstimateProjectInput
    output_model = ProjectEstimateOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.EFFECT_FREE,
        durable_identity="validated estimate inputs + pinned estimate policy",
    )
    effect_class = ToolEffectClass.READ
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("projected_account_count", "deep_fraction")
    )
    pin_requirements = ("cost_policy",)

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, EstimateProjectInput)
        base = EstimateInputs()
        estimate_inputs = base.model_copy(
            update={
                k: v
                for k, v in {
                    "projected_account_count": inputs.projected_account_count,
                    "deep_fraction": inputs.deep_fraction,
                }.items()
                if v is not None
            }
        )
        estimate = estimate_campaign(estimate_inputs)
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "discovered_count": estimate.discovered_count,
                "projected_deep_count": estimate.projected_deep_count,
                "estimated_cost_cents": str(estimate.estimated_cost_cents),
                "cost_per_account_cents": str(estimate.cost_per_account_cents),
            },
        )


# =============================================================================================
# run-control tools (delegate to the ProjectRun state machine; D4 for resume)
# =============================================================================================


class StartProjectRunTool(_CapabilityTool):
    name = "start_project_run"
    input_model = StartProjectRunInput
    output_model = ProjectRunStartOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.OPERATION_IDEMPOTENT,
        durable_identity="ProjectRunId(operation_id)",
        operation_id_required=True,
    )
    effect_class = ToolEffectClass.WRITE
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_id", "icp_key", "icp_version", "budget_cap_cents")
    )
    pin_requirements = ("project", "icp")

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, StartProjectRunInput)
        async with self._conn_factory() as conn:
            project = await get_project(conn, inputs.project_id)
        if project is None or project.workspace_id != ctx.workspace_id:
            return _fail("project_not_found", "no such project")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, StartProjectRunInput)
        cap = Decimal(inputs.budget_cap_cents) if inputs.budget_cap_cents is not None else None
        run_id = await self._run.start(
            project_id=inputs.project_id,
            workspace_id=ctx.workspace_id,
            icp_key=inputs.icp_key,
            icp_version=inputs.icp_version,
            budget_cap_cents=cap,
            project_run_id=ProjectRunId(ctx.operation_id),
        )
        if self._project_execution_router is not None:
            await self._project_execution_router.attach_if_eligible(
                run_id,
                actor=ctx.actor,
                parent_execution_id=ctx.execution_id,
            )
        return ToolResult(
            tool=self.name, version=self.version, references={"project_run_id": str(run_id)}
        )


class PauseRunTool(_CapabilityTool):
    name = "pause_run"
    input_model = PauseRunInput
    output_model = ProjectRunStatusOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project_run desired status PAUSED",
    )
    effect_class = ToolEffectClass.STEERING
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_run_id",))
    pin_requirements = ("project_run",)

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> dict[str, object]:
        assert isinstance(inputs, PauseRunInput)
        return await self._run_audit_snapshot(inputs.project_run_id, ctx)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, PauseRunInput)
        if await self._load_run(inputs.project_run_id, ctx) is None:
            return _fail("run_not_found", "no such project run")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, PauseRunInput)
        run_id = _parse_run_id(inputs.project_run_id)
        assert run_id is not None
        row = await self._run.pause(run_id)
        if self._project_execution_router is not None:
            await self._project_execution_router.pause_owned(
                run_id,
                actor=ctx.actor,
                reason_code="project_run_paused",
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"project_run_id": str(row.id), "status": row.status.value},
        )


class ResumeRunTool(_CapabilityTool):
    name = "resume_run"
    input_model = ResumeRunInput
    output_model = ProjectRunResumeOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project_run desired status ACTIVE + queue single-flight",
    )
    effect_class = ToolEffectClass.STEERING
    parameter_policy = JournalParameterPolicy(safe_display_fields=("project_run_id",))
    pin_requirements = ("project_run",)

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> dict[str, object]:
        assert isinstance(inputs, ResumeRunInput)
        return await self._run_audit_snapshot(inputs.project_run_id, ctx)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ResumeRunInput)
        run = await self._load_run(inputs.project_run_id, ctx)
        if run is None:
            return _fail("run_not_found", "no such project run")
        if run.status not in (ProjectRunStatus.PAUSED, ProjectRunStatus.ACTIVE):
            return _fail("run_not_paused", "only a PAUSED run can be resumed")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ResumeRunInput)
        run_id = _parse_run_id(inputs.project_run_id)
        assert run_id is not None
        row = await self._run.resume(run_id)
        # D4: fleet deployments re-drive by enqueue (a fresh drive task); with no queue wired the
        # status flip stands and the in-process ProjectRunResumeHook drives out-of-band.
        enqueued = False
        routed = (
            await self._project_execution_router.resume_owned(run_id, actor=ctx.actor)
            if self._project_execution_router is not None
            else False
        )
        if not routed and self._queue is not None:
            enqueued = await enqueue_run_drive(
                run_id,
                queue=self._queue,
                conn_factory=self._conn_factory,
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "project_run_id": str(row.id),
                "status": row.status.value,
                "enqueued": enqueued,
            },
        )


class AdjustBudgetTool(_CapabilityTool):
    name = "adjust_budget"
    input_model = AdjustBudgetInput
    output_model = ProjectRunBudgetOutput
    replay = ReplaySafety(
        policy=ReplayPolicy.DOMAIN_IDEMPOTENT,
        durable_identity="project_run + desired budget cap diff guard",
    )
    effect_class = ToolEffectClass.STEERING
    parameter_policy = JournalParameterPolicy(
        safe_display_fields=("project_run_id", "budget_cap_cents")
    )
    pin_requirements = ("project_run", "budget_policy")

    async def audit_snapshot(self, inputs: ToolInput, ctx: ToolContext) -> dict[str, object]:
        assert isinstance(inputs, AdjustBudgetInput)
        return await self._run_audit_snapshot(inputs.project_run_id, ctx)

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, AdjustBudgetInput)
        if await self._load_run(inputs.project_run_id, ctx) is None:
            return _fail("run_not_found", "no such project run")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, AdjustBudgetInput)
        run_id = _parse_run_id(inputs.project_run_id)
        assert run_id is not None
        current = await self._run.status(run_id)
        requested = Decimal(inputs.budget_cap_cents)
        row = (
            current
            if current.budget_cap_cents == requested
            else await self._run.adjust(run_id, budget_cap_cents=requested)
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "project_run_id": str(row.id),
                "budget_cap_cents": str(row.budget_cap_cents),
            },
        )


# =============================================================================================
# the builder
# =============================================================================================

_TOOL_TYPES: tuple[type[_CapabilityTool], ...] = (
    ReverseProfileTool,
    SynthesizeIcpsTool,
    ConfirmIcpTool,
    ImportAccountsTool,
    DiscoverAccountsTool,
    ScoreAccountsTool,
    SubmitTierCheckpointTool,
    SubmitProjectCheckpointTool,
    LaunchAccountDeepTool,
    RunDeepAccountTool,
    ResolveCommitteeTool,
    ProfileContactTool,
    GovernedProfileContactTool,
    RunVerificationTool,
    ComposeHandoffTool,
    EstimateProjectTool,
    StartProjectRunTool,
    PauseRunTool,
    ResumeRunTool,
    AdjustBudgetTool,
)


def build_toolbelt(
    *,
    storage: StorageBackend | None,
    settings: Settings | None = None,
    secrets: Secrets | None = None,
    gateway: LLMGateway | None = None,
    channels: ChannelRegistry | None = None,
    committee_sources: Sequence[CommitteeSource] = (),
    run_machine: ProjectRun | None = None,
    queue: TaskQueue | None = None,
    conn_factory: ConnFactory = transaction,
    pre_spend_gate: PreSpendGate | None = None,
    lock_factory: LockFactory | None = None,
    ingestion_engine: IngestionEngine | None = None,
    proposal_credential_ready: Callable[[str], bool] | None = None,
    proposal_personal_source_allowed: Callable[[SourceProposalPayload], bool] | None = None,
    stage0_memory_write: MemoryWriteSeam | None = None,
    stage0_memory_write_factory: Callable[[AsyncConnection], MemoryWriteSeam] | None = None,
    research_directive_memory_write_factory: (
        Callable[[AsyncConnection], MemoryWriteSeam] | None
    ) = None,
    stage0_scrape_binder: Callable[[AccountEntity], None] | None = None,
    project_execution_router: ProjectExecutionRouter | None = None,
    confirmed_discovery_preflight: ConfirmedDiscoveryPreflight | None = None,
    research_view_composer: ResearchViewComposer | None = None,
    research_view_snapshots: ResearchViewSnapshotService | None = None,
    research_view_recheck: ResearchViewRecheckService | None = None,
    targeted_enrichment_starter: TargetedEnrichmentStarter | None = None,
    account_gap_enrichment_starter: AccountGapEnrichmentStarter | None = None,
    account_deep_full_unit_available: bool | None = None,
    independent_contact_research: IndependentContactResearchRunner | None = None,
    contact_content_handoff: ContactContentHandoffService | None = None,
    entity_research_launches: EntityResearchLaunchServices | None = None,
    arv2_account_launch: Arv2LaunchService | None = None,
    arv2_discovery_launch: Arv2DiscoveryService | None = None,
    arv2_reads: Arv2ReadService | None = None,
    icp_authoring: IcpAuthoringService | None = None,
    persona_requests: PersonaRequestService | None = None,
    project_documents: ProjectDocumentService | None = None,
    prose_synthesis: ProseSynthesisServices | None = None,
    sandbox_workspaces: SandboxWorkspaces | None = None,
    value_narrative: ValueNarrativeServices | None = None,
    crm_read_sinks: CrmReadSinks | None = None,
) -> ToolRegistry:
    """Construct + register the concrete toolbelt over the existing capabilities (spec §2 slice 2).

    Every tool is a thin delegation; the collaborators are injected once here so the tools stay
    boilerplate-free and testable:

    * ``storage`` — a **required** keyword (S2 — the same posture as the phase registration
      surfaces): pass ``build_storage_backend()`` so the tool-path phase handlers (discovery /
      scoring / verification) run inside the B2 snapshot-binding wrapper, or an explicit ``None``
      for the bare pre-B2 handlers. Forgetting it is a ``TypeError``, never a silent no-snapshot
      composition.
    * ``gateway`` — the shared :class:`~clue_core.LLMGateway` the LLM-touching tools (synthesize /
      discover / deep / committee / verification) use. ``None`` is allowed (the pure / prerequisite-
      free tools do not need it); a spend tool invoked without one raises :class:`GatewayRequired`.
    * ``secrets`` — the provider credentials the ARV2 onboarding evidence tool composes its Exa
      client from (ARV2 O4). Unlike ``settings`` this does **not** default to reading the
      environment: ``None`` means *no credentials*, so the tool registers but refuses
      ``exa_not_configured`` before any spend. That default is fail-closed by design — resolving it
      to :class:`~clue_config.Secrets` here would make every test toolbelt compose a live, billable
      Exa client on any machine with a key in its ``.env``. Production composition roots pass a
      real :class:`~clue_config.Secrets` explicitly.
    * ``channels`` — the bound discovery :class:`ChannelRegistry` (empty default: discovery finds
      nothing and advances, never fabricates).
    * ``committee_sources`` — the committee :class:`CommitteeSource` set (empty → empty committee).
    * ``run_machine`` — the :class:`~clue_research.durable.ProjectRun` the run-control tools drive.
      Defaults to one over the Db stores + a :class:`BudgetEngine`, each threaded with the injected
      ``conn_factory`` (S6), and an **explicit empty** :class:`PhaseHandlerRegistry` (S7 / D1 —
      never the process-global default: the toolbelt's run controls must not silently dispatch
      whatever handlers another composition site registered process-wide).
    * ``queue`` — the fleet :class:`~clue_fleet.TaskQueue`; when supplied, ``resume_run`` re-drives
      by enqueue (D4), else the status flip stands for the in-process resume hook.
    * ``conn_factory`` — the :data:`~clue_db.ConnFactory` every precondition read + capability call
      uses (tests inject a savepoint-scoped factory).
    * ``pre_spend_gate`` — the M9.1 concrete gate the spend tools (deep / committee / contact)
      thread into every claim-producing path (S1); defaults to :func:`build_pre_spend_gate` over
      ``conn_factory``.
    * ``lock_factory`` — the Doc C §4 per-entity single-flight lock the account-scoped spend tools
      acquire (S1); defaults to the lazy production factory (Redis resolved at first acquisition).
    * ``ingestion_engine`` — the C3 engine assembled with storage, extraction, governance, and
      erasure collaborators. The two ingestion tools are always registered; without an engine they
      fail closed with ``ingestion_not_configured`` after proving the referenced job/artifact.
    * ``proposal_credential_ready`` / ``proposal_personal_source_allowed`` — C2 promotion
      authorities. Absence leaves credentialed/personal source promotion unavailable rather than
      silently approving it.
    * ``stage0_scrape_binder`` — C4's required composition-root bridge to the live official-site
      resolver. Build it with :func:`clue_api.phase_c_wiring.build_stage0_scrape_binder`; when it
      is absent, ``start_recon`` refuses before spend instead of running a fake/no-source recon.

    Duplicate registration is loud (the :class:`ToolRegistry` contract), so a mis-wired double
    registration fails at construction, not in production."""
    resolved_settings = settings if settings is not None else load_settings()
    machine = (
        run_machine
        if run_machine is not None
        else ProjectRun(
            store=DbProjectRunStore(conn_factory=conn_factory),
            budget_engine=BudgetEngine(store=DbBudgetStore(conn_factory=conn_factory)),
            ledger=DbIdempotencyStore(conn_factory=conn_factory),
            registry=PhaseHandlerRegistry(),
            # FI pilot budget-controls: the run-control tools' machine follows the same deployment
            # switch as the driver's, so no surface can graceful-stop a run the other would advance.
            enforce_budget=resolved_settings.budget_controls_enabled,
        )
    )
    gate = (
        pre_spend_gate
        if pre_spend_gate is not None
        else build_pre_spend_gate(conn_factory=conn_factory)
    )
    entailment_judge = (
        None
        if gateway is None or not resolved_settings.verification_enabled
        else FaithfulnessClaimEntailmentJudge(
            judge=FaithfulnessJudgeImpl(gateway=gateway, conn_factory=conn_factory)
        )
    )
    statement_evidence = (
        ArtifactStatementEvidenceReader(
            artifacts=DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory),
            conn_factory=conn_factory,
        )
        if storage is not None
        else None
    )
    dynamic_client_kb_materializer = (
        DynamicClientKbMaterializer(
            evidence=statement_evidence,
            entailment_judge=entailment_judge,
        )
        if statement_evidence is not None
        else None
    )
    locks = lock_factory if lock_factory is not None else lazy_account_lock_factory()
    full_unit_available = (
        bool(committee_sources)
        if account_deep_full_unit_available is None
        else account_deep_full_unit_available
    )
    registry = ToolRegistry()
    for tool_type in _TOOL_TYPES:
        # C6 keeps the v1 address for exact historical pins, but the name-only alias must elect
        # the governed v2 implementation.  ToolRegistry deliberately refuses two defaults.
        make_default = tool_type not in {ProfileContactTool, SynthesizeIcpsTool}
        registry.register(
            quarantine_entity_research_tool(
                tool_type(
                    settings=resolved_settings,
                    gateway=gateway,
                    channels=channels if channels is not None else ChannelRegistry(),
                    committee_sources=committee_sources,
                    run_machine=machine,
                    queue=queue,
                    conn_factory=conn_factory,
                    pre_spend_gate=gate,
                    lock_factory=locks,
                    storage=storage,
                    project_execution_router=project_execution_router,
                    account_deep_full_unit_available=full_unit_available,
                    independent_contact_research=independent_contact_research,
                )
            ),
            make_default=make_default,
        )
    registry.register(
        ComposeContactContentHandoffTool(service=contact_content_handoff),
        make_default=True,
    )
    registry.register(
        ApproveContactResearchSelectionTool(conn_factory=conn_factory),
        make_default=False,
    )
    for tool in build_entity_research_launch_tools(
        entity_research_launches,
        budget_controls_enabled=resolved_settings.budget_controls_enabled,
        conn_factory=conn_factory,
    ):
        registry.register(tool, make_default=True)
    # ARV2 Track R, R2 (seam 1). Registered on every deployment so the platform's write surface
    # stays complete and the authority audit sees both tools; ``arv2_account_launch`` is composed
    # only where the lane is (the projections app root and ``fleet_main``, behind
    # ``arv2_account_research_enabled``). Without it the pair registers and refuses
    # ``arv2_account_research_not_composed`` before any spend.
    for tool in build_arv2_launch_tools(arv2_account_launch):
        registry.register(tool, make_default=True)
    # ARV2 Track R, R4 (verified account discovery). Same posture as its R2 sibling: registered
    # everywhere so the write surface and the authority audit stay complete, composed only where
    # the lane is (``fleet_main`` and the projections app root, behind ``arv2_discovery_enabled``).
    # Without a service it registers and refuses ``arv2_discovery_not_composed`` before any spend.
    # ``@1`` stays registered for replay and refuses ``discovery_tool_retired``; ``@2`` (the brief
    # the Head of ABM writes) owns the name-only default.
    # The name-only alias follows the version the active profile pins: `head-of-abm@v72` pins `@3`
    # (the brief's exclude list, spec 2026-10-16); `@1` and `@2` stay registered for replay.
    for tool in build_arv2_discovery_tools(arv2_discovery_launch):
        registry.register(tool, make_default=tool.version == "3")
    # The other side of the lane: what the project's rows already say. Registered everywhere like
    # its launching neighbours, but composed with no flag of its own — these four read
    # ``project_account``, the display blocks, the claim store and the discovery run, all of which
    # exist wherever there is a database, and reading them spends nothing. Without a service they
    # refuse ``arv2_reads_not_composed`` before they touch a row.
    # `read_claims` is the fourth: it is the general claims query — by field family, tier,
    # verification status or date, over an account or a contact — and it registers here on the
    # same service. It is granted at `head-of-abm@v56`, the bump that pins its contract and mints
    # the manual chapter that teaches it.
    # Two of the four keep the name-only alias here and two give it up: `head-of-abm@v56` pins the
    # PAGED `read_account_research@2` / `read_discovery_run@2`, so their `@1`s register without
    # the default. The alias must never disagree with the promoted profile's pin — it would hand
    # an unversioned caller the version nobody holds — which is why it moves in the same step as
    # the grant and the recipe address.
    _unaliased_reads = {"read_account_research", "read_discovery_run"}
    for tool in build_arv2_read_tools(arv2_reads):
        registry.register(tool, make_default=tool.descriptor.name not in _unaliased_reads)
    # The paged `@2` of those two, beside their frozen `@1`s, holding the alias their `@1`s gave
    # up. `@1` stays registered so an execution pinned to recipe0-stage0@27 or earlier still
    # resolves the address it planned; it is simply no longer the version an unversioned caller
    # gets — the reasoning `open_icp_confirmation_gate` already established, in this direction.
    for tool in build_arv2_paged_read_tools(arv2_reads):
        registry.register(tool, make_default=tool.descriptor.name != "read_discovery_run")
    # Agent-authored discovery (2026-09-30): `read_discovery_run@3` adds the run's end reason, its
    # summary and the companies its gates excluded (listed apart). It owns the name-only default;
    # `@2` stays registered and granted while `head-of-abm@v69` pins it (plan task 8 moves the pin).
    registry.register(ReadDiscoveryRunV3Tool(arv2_reads), make_default=True)
    # `read_account_research@3` (2026-10-05): `@2` plus the account's insights page and its
    # buying committee with each person's contact page. Granted to the website design agent
    # (design@v4) so a 1:1 page is written from the whole of what research found. `@2` keeps the
    # name-only alias because head-of-abm still pins it; `@3` is reached by its address only.
    registry.register(ReadAccountResearchV3Tool(arv2_reads), make_default=False)
    # The gallery's own read, on the reads' terms and beside them. It takes no service at all: the
    # design documents and the legs that bind them to a project exist wherever there is a database,
    # so the ambient ``conn_factory`` is its whole composition. Granted at `head-of-abm@v56`,
    # together with the manual chapter that teaches it and the recipe revision that admits it.
    for tool in build_artifact_read_tools(conn_factory=conn_factory):
        registry.register(tool, make_default=True)
    # The code sandbox (spec 2026-09-19 §3.4). Registered on every deployment like its
    # neighbours above so the write surface and the authority audit stay complete; composed
    # only where turns are driven, because ``sandbox_workspaces`` is the registry the turn
    # worker binds one execution's host directories into. Without it — and on a host with no
    # sandbox image, or with ``CLUE_SANDBOX_ENABLED`` off — it refuses
    # ``sandbox_unavailable`` before it reaches for a container. Registered UNGRANTED: the
    # grant is a reviewed head-of-abm profile bump, never a dict edit.
    for tool in build_run_python_tools(settings=resolved_settings, workspaces=sandbox_workspaces):
        registry.register(tool, make_default=True)
    # ICP authoring: the surface a brand-level or project-local ICP proposal comes *from*, beside
    # the gate that confirms one. Registered on every deployment for the same reason as its
    # neighbours above; composed wherever the knowledge documents' storage is (``fleet_main`` and
    # the projections app root), with no flag of its own — writing a proposal spends nothing and
    # confirms nothing. Without a service it refuses ``icp_authoring_not_composed`` before it reads
    # a row.
    for tool in build_icp_authoring_tools(icp_authoring, conn_factory=conn_factory):
        registry.register(tool, make_default=True)
    # The other half of the same flow: authoring writes the profile, this asks for the personas of
    # the version the project pinned. Registered everywhere, composed where the onboarding fleet
    # lane is; without a service it refuses ``persona_synthesis_not_composed`` before it reads a
    # row.
    for tool in build_persona_request_tools(persona_requests, conn_factory=conn_factory):
        registry.register(tool, make_default=True)
    # The project's own plan: what the agent and the human settled, written down where both can
    # read and edit it. Registered on every deployment on the same terms as its neighbours above;
    # composed wherever the knowledge documents' storage is, with no flag of its own — writing the
    # plan spends nothing and confirms nothing. Without a service it refuses
    # ``project_documents_not_composed`` before it reads a row.
    for tool in build_project_document_tools(project_documents, conn_factory=conn_factory):
        registry.register(tool, make_default=True)
    registry.register(
        quarantine_entity_research_tool(
            EnrichSelectedAccountsTool(
                starter=targeted_enrichment_starter,
                conn_factory=conn_factory,
            )
        ),
        make_default=True,
    )
    registry.register(
        quarantine_entity_research_tool(
            EnrichAccountGapsTool(
                starter=account_gap_enrichment_starter,
                conn_factory=conn_factory,
                cents_per_credit=resolved_settings.sumble_cents_per_credit,
            )
        ),
        make_default=True,
    )
    registry.register(
        quarantine_entity_research_tool(
            build_research_account_gaps_tool(
                gateway=gateway,
                conn_factory=conn_factory,
                pre_spend_gate=gate,
                lock_factory=locks,
            )
        ),
        make_default=True,
    )
    registry.register(
        quarantine_entity_research_tool(
            build_research_account_gaps_v2_tool(
                gateway=gateway,
                conn_factory=conn_factory,
                pre_spend_gate=gate,
                lock_factory=locks,
            )
        ),
        make_default=False,
    )
    registry.register(
        ProposeFieldTool(dynamic_client_kb_materializer=dynamic_client_kb_materializer),
        make_default=True,
    )
    registry.register(LegacyProposeFieldTool(), make_default=False)
    registry.register(
        DecideFieldProposalTool(
            credential_ready=proposal_credential_ready,
            personal_source_allowed=proposal_personal_source_allowed,
            dynamic_client_kb_materializer=dynamic_client_kb_materializer,
        ),
        make_default=True,
    )
    registry.register(
        LegacyDecideFieldProposalTool(
            credential_ready=proposal_credential_ready,
            personal_source_allowed=proposal_personal_source_allowed,
        ),
        make_default=False,
    )
    registry.register(ProposeSourceTool(), make_default=True)
    registry.register(
        DecideSourceProposalTool(
            credential_ready=proposal_credential_ready,
            personal_source_allowed=proposal_personal_source_allowed,
        ),
        make_default=True,
    )
    registry.register(SubmitIngestionTool(ingestion_engine), make_default=True)
    registry.register(RetryIngestionTool(ingestion_engine), make_default=True)
    # FI Lane D D0 / REQ-21: thread CRUD is a governed tool set like everything else that mutates
    # durable state (Doc A — the toolbelt is the only write path), registered from its own wiring
    # module per the chokepoint protocol.
    register_thread_tools(registry, conn_factory=conn_factory)
    registry.register(RenameProjectTool(conn_factory=conn_factory), make_default=True)
    # Projects directory (2026-09-19): the four project-row tools the directory and the
    # project header drive. Registered like every other write path, granted to no role —
    # filing, pinning and archiving a project are the human's decisions.
    for tool in (
        CreateProjectTool(conn_factory=conn_factory),
        UpdateProjectDetailsTool(conn_factory=conn_factory),
        SetProjectPinnedTool(conn_factory=conn_factory),
        SetProjectArchivedTool(conn_factory=conn_factory),
    ):
        registry.register(tool, make_default=True)
    # FI Lane D D4 / §3-P5(a): the durable confirmation gate is opened through a governed tool for
    # the same reason, and from its own wiring module for the same one.
    register_agent_gate_tools(
        registry,
        conn_factory=conn_factory,
        budget_controls_enabled=resolved_settings.budget_controls_enabled,
    )
    # ARV2 onboarding O6: the ICP gate over a knowledge document, registered here rather than in
    # ``agent_gate_wiring`` because — unlike its ``@1`` sibling — its subject is an artifact, so it
    # needs the storage the knowledge documents live in. It is the DEFAULT version now: T6 promoted
    # ``head-of-abm@v44``, which pins ``@2``, so the unversioned address must resolve to the gate
    # the active profile actually holds. ``@1`` stays registered and frozen for replay.
    for tool in build_icp_artifact_gate_tools(conn_factory=conn_factory, storage=storage):
        registry.register(tool, make_default=True)
    # ARV2 onboarding O6: the set-valued sibling of the S5-F product gate. It reads the brand's own
    # product rows and knowledge documents (never a Client-KB version), so it needs the storage the
    # knowledge documents live in; without one it still presents every candidate, just without the
    # catalog's descriptions.
    for tool in build_product_set_selection_gate_tools(
        conn_factory=conn_factory,
        storage=storage,
    ):
        registry.register(tool, make_default=True)
    registry.register(
        ConfigureProjectTargetingTool(conn_factory=conn_factory, storage=storage), make_default=True
    )
    # Product management (spec 2026-10-15): the Head of ABM adds, renames, merges and removes the
    # brand's products when the person asks, through the same service as Brand context.
    registry.register(
        ManageProductsTool(conn_factory=conn_factory, storage=storage), make_default=True
    )
    # FI-4 slice 3: recon field progress commits on its OWN connection so the setup screen sees
    # motion while the lane runs (the lane's own transaction stays uncommitted until it ends).
    # That second checkout is only safe against the real pooled factory — an injected
    # single-connection / lock-guarded factory (every DB test harness) would have the lane wait
    # on a connection it is itself holding. So the autonomous path is composed only for
    # `transaction`; anything else falls back to the emitter's lane-connection write, which is
    # correct everywhere, just post-commit-visible — and post-commit-visible means the
    # onboarding screen shows nothing for the whole fast lane, so say so out loud rather than
    # degrading in silence (a future request-scoped/instrumented production factory would
    # otherwise kill the feature with green tests and green logs).
    stage0_field_progress_factory = conn_factory if conn_factory is transaction else None
    if stage0_field_progress_factory is None:
        log.info(
            "toolbelt.stage0_field_progress_lane_bound",
            reason="conn_factory is not clue_db.transaction",
            effect="recon per-field progress is visible only after the lane commits",
        )
    for tool in stage0_tools(
        conn_factory=conn_factory,
        # Founder ruling (FI-4 §9, 2026-08-13): onboarding is budget-unconstrained — an envelope
        # must never truncate onboarding research. So the composed policy takes its two lane caps
        # from deployment settings (default 25¢ fast: the whole eleven-field firecrawl walk with
        # headroom) instead of the library's frozen 5¢, which released the user with the last
        # checklist groups unreached. `DEFAULT_STAGE0_POLICY` is unchanged for uncomposed callers.
        policy=stage0_policy_from_settings(resolved_settings),
        pre_spend_gate=gate,
        memory_write=stage0_memory_write,
        memory_write_factory=stage0_memory_write_factory,
        scrape_binder=stage0_scrape_binder,
        storage=storage,
        project_execution_router=project_execution_router,
        # PC-C8 §6c-b: typed interview values are admitted by the shipped M9.3 faithfulness judge,
        # never by a second entailment mechanism. Without a gateway there is no judge, and a typed
        # value is then refused rather than written unvouched-for — which is exactly the pre-§6c
        # behaviour, so an ungatewayed composition is never *worse* than before.
        entailment_judge=entailment_judge,
        field_progress_factory=stage0_field_progress_factory,
    ):
        registry.register(
            tool,
            # Preserve @1 for historical recipe replay. The trusted project-scoped successors
            # registered immediately below own the name-only defaults for readiness and confirmed
            # run start; active resources pin those exact @2 addresses after promotion.
            make_default=tool.name
            not in {"evaluate_stage0_readiness", "start_confirmed_project_run"},
        )
    for tool in stage0_project_tools(
        conn_factory=conn_factory,
        policy=DEFAULT_STAGE0_POLICY,
        gateway=gateway,
        synthesis_model=resolved_settings.synthesis_model,
        statement_evidence=statement_evidence,
        project_execution_router=project_execution_router,
        confirmed_discovery_preflight=confirmed_discovery_preflight,
        budget_controls_enabled=resolved_settings.budget_controls_enabled,
    ):
        registry.register(
            tool,
            make_default=(
                (tool.name != "start_confirmed_project_run" or tool.version == "3")
                and (tool.name != "synthesize_icps" or tool.version == "3")
            ),
        )
    for tool in build_research_directive_tools(
        memory_write_factory=(
            research_directive_memory_write_factory or stage0_memory_write_factory
        ),
        conn_factory=conn_factory,
    ):
        registry.register(
            tool,
            make_default=(
                (tool.name != "draft_account_research_directive" or tool.version == "5")
                and (tool.name != "confirm_account_research_directive" or tool.version == "2")
            ),
        )
    # PC-C8 §7: the two bounded, read-only Stage-0 history tools the card's `omissions` cursors
    # resolve. Both are granted to `AgentRole.HEAD_OF_ABM` in `C6_AGENT_TOOL_AUTHORITY` (the
    # deferred grant landed against profile v10) and are *not* withheld by the trial's
    # `C6_SURFACE_POLICIES` entry — §7 sanctions them on that surface explicitly, because they are
    # read-only, effect-free, page-bounded and fail-closed on workspace/project scope, and a card
    # that emits an omission kind no installed tool can resolve is what
    # `test_c8_omission_resolution_contract.py` refuses to let ship.
    # Without a storage backend the evidence reader cannot exist, so the statement tool refuses
    # `statement_evidence_not_configured` rather than serving quote-less rows.
    for tool in build_stage0_inspection_tools(
        evidence=statement_evidence,
        conn_factory=conn_factory,
    ):
        registry.register(tool, make_default=True)
    # S4-D: preserve @1 for exact historical replay, but make the strictly artifact-bound @2
    # contracts the production defaults. Both versions register in every process so profile and
    # recipe compatibility composition is deterministic. A constitution without S3's paired
    # Client-KB artifact cannot satisfy @2; the old trial focus-ref fallback remains @1-only.
    for tool in build_client_knowledge_tools(conn_factory=conn_factory):
        registry.register(tool, make_default=False)
    for tool in build_client_knowledge_v2_tools(conn_factory=conn_factory):
        registry.register(tool, make_default=True)
    # S5-D: selected-product knowledge is a separate exact-scope read surface.  These tools never
    # widen the company tools with a model-authored product selector; product authority is restored
    # only from the immutable turn constitution at execution time.
    for tool in build_product_knowledge_tools(conn_factory=conn_factory):
        registry.register(tool, make_default=True)
    for tool in build_research_view_tools(
        composer=research_view_composer,
        snapshots=research_view_snapshots,
        recheck=research_view_recheck,
        read_enabled=resolved_settings.c7_research_view_read_enabled,
        snapshot_compose_enabled=resolved_settings.c7_snapshot_compose_enabled,
        recheck_enabled=resolved_settings.c7_recheck_enabled,
        admitted_workspace_ids=frozenset(resolved_settings.c7_workspace_canary_ids),
    ):
        registry.register(tool, make_default=True)
    # Lane E E1. The tool registers in EVERY composition — including the gateway-less HTTP process
    # — so the registered name set (and therefore the C6 authority check) is identical everywhere;
    # an uncomposed process simply refuses `prose_synthesis_not_composed` / `gateway_required`
    # rather than being silently absent.
    for tool in build_prose_synthesis_tools(
        prose_synthesis,
        gateway=gateway,
        conn_factory=conn_factory,
    ):
        registry.register(tool, make_default=True)
    # ARV2 O4. Registers in EVERY composition (the C6 authority audit needs one registry shape);
    # an off flag or a missing Exa key is refused in `preconditions`, never by absence.
    for tool in build_onboarding_evidence_tools(
        settings=resolved_settings,
        secrets=secrets,
        artifacts=(
            None
            if storage is None
            else DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)
        ),
    ):
        registry.register(tool, make_default=True)
    # web_search@1 (spec 2026-09-22). Registers in EVERY composition like its neighbour above —
    # the C6 authority audit needs one registry shape — and a missing Exa key is refused in
    # `preconditions`, never by absence. Registered UNGRANTED here: the grants are the reviewed
    # `head-of-abm@v62` and `design@v3` bumps, never a dict edit.
    for tool in build_web_search_tools(secrets=secrets):
        registry.register(tool, make_default=True)
    # CRM integration (spec docs/superpowers/specs/crm-integration/): always registered; the
    # tools refuse until the flag, the Composio key and an auth config are configured.
    # ``crm_read_sinks`` is the registry the turn worker binds each turn's ``reads/`` folder into
    # (the ``sandbox_workspaces`` arrangement); without it ``run_crm_action`` refuses by name.
    for tool in build_crm_tools(
        settings=resolved_settings,
        secrets=secrets,
        conn_factory=conn_factory,
        read_sinks=crm_read_sinks,
    ):
        registry.register(tool, make_default=True)
    # Lane E E3. Same everywhere-registered posture as the prose surface above, with one extra
    # gate: the positioning services are composed only when `value_narrative_synthesis_enabled`,
    # so a flag-off deployment registers the name and refuses `value_narrative_not_composed`.
    for tool in build_value_narrative_tools(
        value_narrative,
        gateway=gateway,
        conn_factory=conn_factory,
    ):
        registry.register(tool, make_default=True)
    # Part II D6: the design subsystem's governed write path. Registered UNCONDITIONALLY (the C6
    # authority audit is a strict set equality — a registry whose shape depends on
    # `design_runtime_enabled` would make flipping that switch an AgentCatalogError), but LIVE
    # only where a design runtime is composed; elsewhere every design tool refuses
    # `design_runtime_not_configured` before any write. P3.3 granted the set to
    # `AgentRole.DESIGN` — see `C6_AGENT_TOOL_AUTHORITY`.
    for tool in build_design_tools(
        enabled=resolved_settings.design_runtime_enabled,
        storage=storage,
    ):
        registry.register(tool, make_default=is_default_design_tool(tool))
    # P3.4 (PD-part3 §1-D1/§2.3): the head-of-abm's delegation entry onto the design leg.
    # Registered unconditionally for the same audit reason, and gated on the SAME runtime
    # switch as the design_* set (the thread-wedge guard, adversarial-review fix): a leg
    # opened where no design runtime is composed is a thread nothing can serve, so on such a
    # deployment both tools refuse `design_leg_runtime_not_configured` before any write;
    # without a storage backend they refuse `design_leg_storage_not_configured`.
    for tool in build_design_leg_tools(
        conn_factory=conn_factory,
        storage=storage,
        enabled=resolved_settings.design_runtime_enabled,
        site_engine_workspaces=frozenset(
            w.strip()
            for w in resolved_settings.design_site_engine_workspaces.split(",")
            if w.strip()
        ),
    ):
        registry.register(tool, make_default=True)
    return registry

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
  ``confirm_icp`` (``no_client_kb``), ``import_accounts`` (``no_active_icp``);
* discovery / scoring — ``discover_accounts`` (``run_not_found``, ``no_active_icp``),
  ``score_accounts`` (``run_not_found``), ``submit_tier_checkpoint`` (``run_not_found``,
  ``checkpoint_not_awaiting``);
* deep / committee / contact — ``run_deep_account`` (``no_active_icp``, ``account_not_found``),
  ``resolve_committee`` (``account_not_found``), ``profile_contact`` (``account_not_found``,
  ``contact_not_found``);
* verification / handoff — ``run_verification`` (``run_not_found``, ``no_active_icp``),
  ``compose_handoff`` (``run_not_found``, ``handoff_not_reached``);
* estimate — ``estimate_project`` (none — pure);
* run controls — ``start_project_run`` (none), ``pause_run`` (``run_not_found``),
  ``resume_run`` (``run_not_found``, ``run_not_paused``), ``adjust_budget`` (``run_not_found``).

Preconditions read through ``ctx.conn_factory``; a malformed id resolves to the same not-found
refusal (never a raw traceback). The ``compose_handoff`` result surfaces the slice-1
``narrative_emit_skipped`` gap flag from the run's HANDOFF checkpoint payload, so a gap-completed
run is distinguishable from a truly-handed-off one (spec §2 amendment / slice-1 review #10).
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from typing import cast
from uuid import UUID

from pydantic import JsonValue

from clue_api.deep.composition import build_high_tier_resolver
from clue_api.fleet_wiring import enqueue_run_drive
from clue_api.verification import build_verification_phase_handler
from clue_config import Settings, load_settings
from clue_core import (
    EntityId,
    ICPSpec,
    LLMGateway,
    PhaseContext,
    ProjectPhase,
    ProjectRunId,
    new_project_run_id,
    new_run_id,
)
from clue_db import ConnFactory, transaction
from clue_fleet import TaskQueue
from clue_research.discovery_scoring.discovery import ChannelRegistry
from clue_research.discovery_scoring.discovery import discover as discover_accounts_fn
from clue_research.discovery_scoring.phases import ScoringPhaseHandler
from clue_research.durable import (
    BudgetEngine,
    DbIdempotencyStore,
    DbProjectRunStore,
    PhaseCheckpointStatus,
    ProjectRun,
    ProjectRunRow,
    ProjectRunStatus,
    get_checkpoint,
    get_project_run,
)
from clue_research.icp.spec import get_active_icp
from clue_research.identity import get_account, get_contact
from clue_research.narrative import list_handoffs_for_run
from clue_research.profiling import (
    CommitteeSource,
    discover_committee,
    profile_account,
    profile_contact,
)
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
from clue_toolbelt import (
    PreconditionFailure,
    Tool,
    ToolContext,
    ToolInput,
    ToolRegistry,
    ToolResult,
)

__all__ = ["build_toolbelt", "GatewayRequired"]


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


class ConfirmIcpInput(ToolInput):
    client_entity_id: str
    proposal: ICPProposal
    edits: ICPProposalEdits | None = None
    created_by: str | None = None


class ImportAccountsInput(ToolInput):
    client_entity_id: str
    icp_key: str
    rows: list[ImportRow]


class DiscoverAccountsInput(ToolInput):
    project_run_id: str


class ScoreAccountsInput(ToolInput):
    project_run_id: str


class SubmitTierCheckpointInput(ToolInput):
    project_run_id: str
    decision: dict[str, object] = {}


class RunDeepAccountInput(ToolInput):
    account_entity_id: str
    icp_key: str
    tier: str


class ResolveCommitteeInput(ToolInput):
    account_entity_id: str
    icp_key: str | None = None


class ProfileContactInput(ToolInput):
    contact_entity_id: str
    account_entity_id: str
    tier: str
    icp_key: str | None = None


class RunVerificationInput(ToolInput):
    project_run_id: str


class ComposeHandoffInput(ToolInput):
    project_run_id: str


class EstimateProjectInput(ToolInput):
    projected_account_count: int | None = None
    deep_fraction: float | None = None


class StartProjectRunInput(ToolInput):
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
    ) -> None:
        self._settings = settings
        self._gateway = gateway
        self._channels = channels
        self._committee_sources = tuple(committee_sources)
        self._run = run_machine
        self._queue = queue
        self._conn_factory = conn_factory

    def _require_gateway(self) -> LLMGateway:
        if self._gateway is None:
            raise GatewayRequired(f"tool {self.name!r} needs an LLMGateway but none was injected")
        return self._gateway

    async def _load_run(self, raw_id: str) -> ProjectRunRow | None:
        run_id = _parse_run_id(raw_id)
        if run_id is None:
            return None
        async with self._conn_factory() as conn:
            return await get_project_run(conn, run_id)

    async def _load_active_spec(self, workspace_id: str, icp_key: str) -> ICPSpec | None:
        async with self._conn_factory() as conn:
            return await get_active_icp(conn, workspace_id, icp_key)

    def _phase_ctx(self, run: ProjectRunRow, phase: ProjectPhase) -> PhaseContext:
        return PhaseContext(
            project_run_id=run.id,
            phase=phase,
            workspace_id=run.workspace_id,
            icp_key=run.icp_key,
            icp_version=run.icp_version,
            budget_cap_cents=run.budget_cap_cents,
            params=dict(run.tier_cutoffs and {"tier_cutoffs": run.tier_cutoffs} or {}),
        )


# =============================================================================================
# setup / stage-0 tools
# =============================================================================================


class ReverseProfileTool(_CapabilityTool):
    name = "reverse_profile"
    input_model = ReverseProfileInput

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ReverseProfileInput)
        async with ctx.conn_factory() as conn:
            result = await reverse_profile(
                conn,
                ClientInput(name=inputs.name, website=inputs.website),
                workspace_id=ctx.workspace_id,
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

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, SynthesizeIcpsInput)
        entity = _parse_entity_id(inputs.client_entity_id)
        if entity is None:
            return _fail("no_client_kb", "client_entity_id is not a valid entity id")
        async with ctx.conn_factory() as conn:
            version = await current_kb_version(conn, entity, workspace_id=ctx.workspace_id)
        if version is None:
            return _fail(
                "no_client_kb",
                "no Client Knowledge Base for this client — run reverse_profile first",
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
            assert version is not None
            ref = ClientKnowledgeBaseRef(client_entity_id=entity, client_kb_version=version)
            proposals = await synthesize_icps(
                conn, ref, workspace_id=ctx.workspace_id, gateway=self._gateway
            )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"proposal_count": len(proposals), "client_kb_version": version},
        )


class ConfirmIcpTool(_CapabilityTool):
    name = "confirm_icp"
    input_model = ConfirmIcpInput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ConfirmIcpInput)
        entity = _parse_entity_id(inputs.client_entity_id)
        if entity is None:
            return _fail("no_client_kb", "client_entity_id is not a valid entity id")
        async with ctx.conn_factory() as conn:
            version = await current_kb_version(conn, entity, workspace_id=ctx.workspace_id)
        if version is None:
            return _fail(
                "no_client_kb",
                "no Client Knowledge Base for this client — run reverse_profile first",
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
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ImportAccountsInput)
        entity = _parse_entity_id(inputs.client_entity_id)
        async with ctx.conn_factory() as conn:
            spec = await get_active_icp(conn, ctx.workspace_id, inputs.icp_key)
            assert spec is not None and entity is not None
            spec_ref = ICPSpecRef(
                workspace_id=ctx.workspace_id, icp_key=spec.icp_key, icp_version=spec.version
            )
            result = await import_accounts(
                conn,
                inputs.rows,
                spec_ref,
                workspace_id=ctx.workspace_id,
                client_entity_id=entity,
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

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, DiscoverAccountsInput)
        run = await self._load_run(inputs.project_run_id)
        if run is None:
            return _fail("run_not_found", "no such project run")
        spec = await self._load_active_spec(run.workspace_id, run.icp_key)
        if spec is None:
            return _fail("no_active_icp", f"no active ICP {run.icp_key!r} for this run")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, DiscoverAccountsInput)
        run = await self._load_run(inputs.project_run_id)
        assert run is not None
        spec = await self._load_active_spec(run.workspace_id, run.icp_key)
        assert spec is not None
        result = await discover_accounts_fn(
            spec=spec, run_id=new_run_id(), channels=self._channels, gateway=self._gateway
        )
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "run_id": str(result.run_id),
                "candidates": len(result.candidates),
                "stopping_reason": result.stopping_reason.value,
            },
        )


class ScoreAccountsTool(_CapabilityTool):
    name = "score_accounts"
    input_model = ScoreAccountsInput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ScoreAccountsInput)
        run = await self._load_run(inputs.project_run_id)
        if run is None:
            return _fail("run_not_found", "no such project run")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ScoreAccountsInput)
        run = await self._load_run(inputs.project_run_id)
        assert run is not None
        handler = ScoringPhaseHandler(session_factory=self._conn_factory)
        result = await handler.run(self._phase_ctx(run, ProjectPhase.SCORING))
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "status": result.status.value,
                "accounts_processed": result.accounts_processed,
            },
        )


class SubmitTierCheckpointTool(_CapabilityTool):
    name = "submit_tier_checkpoint"
    input_model = SubmitTierCheckpointInput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, SubmitTierCheckpointInput)
        run = await self._load_run(inputs.project_run_id)
        if run is None:
            return _fail("run_not_found", "no such project run")
        async with self._conn_factory() as conn:
            checkpoint = await get_checkpoint(conn, run.id, ProjectPhase.TIER_CHECKPOINT)
        if checkpoint is None or checkpoint.status != PhaseCheckpointStatus.AWAITING_INPUT:
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
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"project_run_id": str(row.id), "phase": row.phase.value},
        )


# =============================================================================================
# deep / committee / contact tools (per-account capabilities)
# =============================================================================================


class RunDeepAccountTool(_CapabilityTool):
    name = "run_deep_account"
    input_model = RunDeepAccountInput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, RunDeepAccountInput)
        spec = await self._load_active_spec(ctx.workspace_id, inputs.icp_key)
        if spec is None:
            return _fail("no_active_icp", f"no active ICP {inputs.icp_key!r}")
        entity = _parse_entity_id(inputs.account_entity_id)
        if entity is None:
            return _fail("account_not_found", "account_entity_id is not a valid entity id")
        async with ctx.conn_factory() as conn:
            account = await get_account(conn, entity)
        if account is None:
            return _fail("account_not_found", "no such account entity")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, RunDeepAccountInput)
        entity = _parse_entity_id(inputs.account_entity_id)
        assert entity is not None
        spec = await self._load_active_spec(ctx.workspace_id, inputs.icp_key)
        assert spec is not None
        result = await profile_account(
            account_entity_id=entity,
            spec=spec,
            tier=inputs.tier,
            workspace_id=ctx.workspace_id,
            gateway=self._require_gateway(),
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
    name = "resolve_committee"
    input_model = ResolveCommitteeInput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ResolveCommitteeInput)
        entity = _parse_entity_id(inputs.account_entity_id)
        if entity is None:
            return _fail("account_not_found", "account_entity_id is not a valid entity id")
        async with ctx.conn_factory() as conn:
            account = await get_account(conn, entity)
        if account is None:
            return _fail("account_not_found", "no such account entity")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ResolveCommitteeInput)
        entity = _parse_entity_id(inputs.account_entity_id)
        assert entity is not None
        spec = (
            await self._load_active_spec(ctx.workspace_id, inputs.icp_key)
            if inputs.icp_key is not None
            else None
        )
        async with ctx.conn_factory() as conn:
            result = await discover_committee(
                conn,
                account_entity_id=entity,
                run_id=new_run_id(),
                workspace_id=ctx.workspace_id,
                sources=self._committee_sources,
                gateway=self._require_gateway(),
                spec=spec,
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
    name = "profile_contact"
    input_model = ProfileContactInput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ProfileContactInput)
        account = _parse_entity_id(inputs.account_entity_id)
        if account is None:
            return _fail("account_not_found", "account_entity_id is not a valid entity id")
        contact = _parse_entity_id(inputs.contact_entity_id)
        if contact is None:
            return _fail("contact_not_found", "contact_entity_id is not a valid entity id")
        async with ctx.conn_factory() as conn:
            if await get_account(conn, account) is None:
                return _fail("account_not_found", "no such account entity")
            if await get_contact(conn, contact) is None:
                return _fail("contact_not_found", "no such contact entity")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ProfileContactInput)
        account = _parse_entity_id(inputs.account_entity_id)
        contact = _parse_entity_id(inputs.contact_entity_id)
        assert account is not None and contact is not None
        spec = (
            await self._load_active_spec(ctx.workspace_id, inputs.icp_key)
            if inputs.icp_key is not None
            else None
        )
        async with ctx.conn_factory() as conn:
            result = await profile_contact(
                conn,
                contact_entity_id=contact,
                account_entity_id=account,
                run_id=new_run_id(),
                workspace_id=ctx.workspace_id,
                tier=inputs.tier,
                spec=spec,
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


# =============================================================================================
# verification / handoff tools
# =============================================================================================


class RunVerificationTool(_CapabilityTool):
    name = "run_verification"
    input_model = RunVerificationInput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, RunVerificationInput)
        run = await self._load_run(inputs.project_run_id)
        if run is None:
            return _fail("run_not_found", "no such project run")
        spec = await self._load_active_spec(run.workspace_id, run.icp_key)
        if spec is None:
            return _fail("no_active_icp", f"no active ICP {run.icp_key!r} for this run")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, RunVerificationInput)
        run = await self._load_run(inputs.project_run_id)
        assert run is not None
        spec = await self._load_active_spec(run.workspace_id, run.icp_key)
        assert spec is not None
        handler = build_verification_phase_handler(
            gateway=self._require_gateway(),
            account_resolver=build_high_tier_resolver(spec=spec),
            session_factory=self._conn_factory,
        )
        result = await handler.run(self._phase_ctx(run, ProjectPhase.VERIFICATION))
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

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ComposeHandoffInput)
        run = await self._load_run(inputs.project_run_id)
        if run is None:
            return _fail("run_not_found", "no such project run")
        async with self._conn_factory() as conn:
            checkpoint = await get_checkpoint(conn, run.id, ProjectPhase.HANDOFF)
        if checkpoint is None:
            return _fail("handoff_not_reached", "the run has not reached the HANDOFF phase yet")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, ComposeHandoffInput)
        run = await self._load_run(inputs.project_run_id)
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
        narrative_emit_skipped = bool(payload.get("narrative_emit_skipped", False))
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={
                "project_run_id": str(run.id),
                "handoffs": len(handoffs),
                "narrative_emit_skipped": narrative_emit_skipped,
            },
        )


# =============================================================================================
# estimate tool
# =============================================================================================


class EstimateProjectTool(_CapabilityTool):
    name = "estimate_project"
    input_model = EstimateProjectInput

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

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, StartProjectRunInput)
        cap = Decimal(inputs.budget_cap_cents) if inputs.budget_cap_cents is not None else None
        run_id = await self._run.start(
            workspace_id=ctx.workspace_id,
            icp_key=inputs.icp_key,
            icp_version=inputs.icp_version,
            budget_cap_cents=cap,
            project_run_id=new_project_run_id(),
        )
        return ToolResult(
            tool=self.name, version=self.version, references={"project_run_id": str(run_id)}
        )


class PauseRunTool(_CapabilityTool):
    name = "pause_run"
    input_model = PauseRunInput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, PauseRunInput)
        if await self._load_run(inputs.project_run_id) is None:
            return _fail("run_not_found", "no such project run")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, PauseRunInput)
        run_id = _parse_run_id(inputs.project_run_id)
        assert run_id is not None
        row = await self._run.pause(run_id)
        return ToolResult(
            tool=self.name,
            version=self.version,
            references={"project_run_id": str(row.id), "status": row.status.value},
        )


class ResumeRunTool(_CapabilityTool):
    name = "resume_run"
    input_model = ResumeRunInput

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, ResumeRunInput)
        run = await self._load_run(inputs.project_run_id)
        if run is None:
            return _fail("run_not_found", "no such project run")
        if run.status != ProjectRunStatus.PAUSED:
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
        if self._queue is not None:
            enqueued = await enqueue_run_drive(run_id, queue=self._queue)
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

    async def preconditions(
        self, inputs: ToolInput, ctx: ToolContext
    ) -> Sequence[PreconditionFailure]:
        assert isinstance(inputs, AdjustBudgetInput)
        if await self._load_run(inputs.project_run_id) is None:
            return _fail("run_not_found", "no such project run")
        return ()

    async def invoke(self, inputs: ToolInput, ctx: ToolContext) -> ToolResult:
        assert isinstance(inputs, AdjustBudgetInput)
        run_id = _parse_run_id(inputs.project_run_id)
        assert run_id is not None
        row = await self._run.adjust(run_id, budget_cap_cents=Decimal(inputs.budget_cap_cents))
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
    RunDeepAccountTool,
    ResolveCommitteeTool,
    ProfileContactTool,
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
    settings: Settings | None = None,
    gateway: LLMGateway | None = None,
    channels: ChannelRegistry | None = None,
    committee_sources: Sequence[CommitteeSource] = (),
    run_machine: ProjectRun | None = None,
    queue: TaskQueue | None = None,
    conn_factory: ConnFactory = transaction,
) -> ToolRegistry:
    """Construct + register the concrete toolbelt over the existing capabilities (spec §2 slice 2).

    Every tool is a thin delegation; the collaborators are injected once here so the tools stay
    boilerplate-free and testable:

    * ``gateway`` — the shared :class:`~clue_core.LLMGateway` the LLM-touching tools (synthesize /
      discover / deep / committee / verification) use. ``None`` is allowed (the pure / prerequisite-
      free tools do not need it); a spend tool invoked without one raises :class:`GatewayRequired`.
    * ``channels`` — the bound discovery :class:`ChannelRegistry` (empty default: discovery finds
      nothing and advances, never fabricates).
    * ``committee_sources`` — the committee :class:`CommitteeSource` set (empty → empty committee).
    * ``run_machine`` — the :class:`~clue_research.durable.ProjectRun` the run-control tools drive
      (defaults to one over the Db stores + a :class:`BudgetEngine`).
    * ``queue`` — the fleet :class:`~clue_fleet.TaskQueue`; when supplied, ``resume_run`` re-drives
      by enqueue (D4), else the status flip stands for the in-process resume hook.
    * ``conn_factory`` — the :data:`~clue_db.ConnFactory` every precondition read + capability call
      uses (tests inject a savepoint-scoped factory).

    Duplicate registration is loud (the :class:`ToolRegistry` contract), so a mis-wired double
    registration fails at construction, not in production."""
    resolved_settings = settings if settings is not None else load_settings()
    machine = (
        run_machine
        if run_machine is not None
        else ProjectRun(
            store=DbProjectRunStore(),
            budget_engine=BudgetEngine(),
            ledger=DbIdempotencyStore(),
        )
    )
    registry = ToolRegistry()
    for tool_type in _TOOL_TYPES:
        registry.register(
            tool_type(
                settings=resolved_settings,
                gateway=gateway,
                channels=channels if channels is not None else ChannelRegistry(),
                committee_sources=committee_sources,
                run_machine=machine,
                queue=queue,
                conn_factory=conn_factory,
            )
        )
    return registry

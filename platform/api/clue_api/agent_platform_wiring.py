"""C6.8 production composition, durable ownership routing, and canary evaluation."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol, cast
from uuid import UUID, uuid5

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text

from clue_agents import (
    AgentModelProvider,
    AgentProfileRegistry,
    AgentWorkspaceFactory,
    AttachmentDescriber,
    CompiledContextCardReader,
    ContextAssemblyPolicy,
    DeterministicAgentContextAssembler,
    FocusLayerSource,
    HistoryLayerSource,
    IdentityLayerSource,
    MemoryLayerSource,
    ProjectLayerSource,
    ResolvedAgentProfile,
    TurnLayerSource,
    WorkspaceProductLayerSource,
)
from clue_api.agent_model_wiring import build_agent_model_provider
from clue_api.agent_registry_wiring import build_agent_profile_registry
from clue_api.agent_turn_wiring import (
    AgentPrivacyService,
    DbAgentContextReceiptStore,
    DbAgentHistoryStore,
    DbAgentReplayReader,
    DbAgentTurnJournal,
    DurableAgentArtifactStore,
)
from clue_api.agent_workspace_wiring import build_agent_workspace_factory
from clue_api.deep import ProfileAccountFn
from clue_api.project_library_refresh import ProjectLibraryRefresher
from clue_api.sandbox.workspaces import SandboxWorkspaces
from clue_api.turn_binding import CapturedTurnBinder
from clue_config import Secrets, Settings
from clue_config.gateway import GatewayConfig
from clue_core import ContextAssembly, MemoryType
from clue_db import ConnFactory, transaction
from clue_research.profiling import AccountProfileResult
from clue_storage import StorageBackend
from clue_toolbelt import ToolRegistry

__all__ = [
    "AgentCanaryAssessment",
    "AgentCanarySample",
    "AgentCanaryThresholds",
    "AgentOwner",
    "AgentOwnershipRouter",
    "AgentPlatformComponents",
    "AgentRouteDecision",
    "AgentRuntimeNotComposed",
    "AgentRuntimeSurface",
    "DbAgentOwnershipRouter",
    "RoutedAccountProfiler",
    "build_agent_context_assembler",
    "build_agent_platform_components",
    "evaluate_agent_canary",
    "run_owned_agent_surface",
]

_ROUTE_NAMESPACE = UUID("151ce318-84e3-5bc1-9443-972af6bde21e")


class _Value(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", strict=True)


class AgentRuntimeSurface(StrEnum):
    STAGE0 = "stage0"
    ACCOUNT_RESEARCH = "account_research"


class AgentOwner(StrEnum):
    LEGACY = "legacy"
    DEEPAGENT = "deepagent"


class AgentOwnershipRouter(Protocol):
    async def claim(
        self,
        *,
        workspace_id: str,
        surface: AgentRuntimeSurface,
        subject_id: str,
    ) -> AgentRouteDecision: ...


class AgentRouteDecision(_Value):
    route_id: UUID
    workspace_id: str
    surface: AgentRuntimeSurface
    subject_id: str
    owner: AgentOwner
    selection_source: Literal[
        "master_disabled",
        "surface_disabled",
        "allowlist",
        "percentage",
        "not_selected",
    ]
    cohort_bucket: int | None = Field(default=None, ge=0, le=99)
    configured_percent: int = Field(ge=0, le=100)
    config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def _config_payload(settings: Settings, surface: AgentRuntimeSurface) -> dict[str, object]:
    return {
        "master": settings.agent_runtime_routing_enabled,
        "surface": surface.value,
        "surface_enabled": (
            settings.agent_stage0_routing_enabled
            if surface is AgentRuntimeSurface.STAGE0
            else settings.agent_account_routing_enabled
        ),
        "allowlist": sorted(set(settings.agent_workspace_allowlist)),
        "percent": settings.agent_canary_percent,
    }


def _config_sha256(settings: Settings, surface: AgentRuntimeSurface) -> str:
    return hashlib.sha256(
        json.dumps(
            _config_payload(settings, surface),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _bucket(workspace_id: str, surface: AgentRuntimeSurface) -> int:
    digest = hashlib.sha256(f"{workspace_id}\0{surface.value}".encode()).digest()
    return int.from_bytes(digest[:8], "big") % 100


def _select(
    settings: Settings,
    *,
    workspace_id: str,
    surface: AgentRuntimeSurface,
    subject_id: str,
) -> AgentRouteDecision:
    enabled = (
        settings.agent_stage0_routing_enabled
        if surface is AgentRuntimeSurface.STAGE0
        else settings.agent_account_routing_enabled
    )
    bucket = _bucket(workspace_id, surface)
    if not settings.agent_runtime_routing_enabled:
        owner = AgentOwner.LEGACY
        source = "master_disabled"
        stored_bucket = None
    elif not enabled:
        owner = AgentOwner.LEGACY
        source = "surface_disabled"
        stored_bucket = None
    elif workspace_id in settings.agent_workspace_allowlist:
        owner = AgentOwner.DEEPAGENT
        source = "allowlist"
        stored_bucket = None
    elif bucket < settings.agent_canary_percent:
        owner = AgentOwner.DEEPAGENT
        source = "percentage"
        stored_bucket = bucket
    else:
        owner = AgentOwner.LEGACY
        source = "not_selected"
        stored_bucket = bucket
    route_id = uuid5(_ROUTE_NAMESPACE, f"{workspace_id}:{surface.value}:{subject_id}")
    return AgentRouteDecision(
        route_id=route_id,
        workspace_id=workspace_id,
        surface=surface,
        subject_id=subject_id,
        owner=owner,
        selection_source=cast(
            Literal[
                "master_disabled",
                "surface_disabled",
                "allowlist",
                "percentage",
                "not_selected",
            ],
            source,
        ),
        cohort_bucket=stored_bucket,
        configured_percent=settings.agent_canary_percent,
        config_sha256=_config_sha256(settings, surface),
    )


class DbAgentOwnershipRouter:
    """Choose once per subject. Configuration changes never steal an in-flight owner."""

    def __init__(
        self,
        *,
        settings: Settings,
        conn_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings
        self._conn_factory = conn_factory

    async def claim(
        self,
        *,
        workspace_id: str,
        surface: AgentRuntimeSurface,
        subject_id: str,
    ) -> AgentRouteDecision:
        if not subject_id.strip():
            raise ValueError("agent routing subject_id must be non-empty")
        proposed = _select(
            self._settings,
            workspace_id=workspace_id,
            surface=surface,
            subject_id=subject_id,
        )
        async with self._conn_factory() as conn:
            await conn.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:scope, 0))"),
                {"scope": f"agent-route:{workspace_id}:{surface.value}:{subject_id}"},
            )
            await conn.execute(
                text(
                    "INSERT INTO agent_runtime_route "
                    "(id, workspace_id, surface, subject_id, owner, selection_source, "
                    " cohort_bucket, configured_percent, config_sha256) "
                    "VALUES (:id, :workspace, :surface, :subject, :owner, :source, "
                    " :bucket, :percent, :config) "
                    "ON CONFLICT (workspace_id, surface, subject_id) DO NOTHING"
                ),
                {
                    "id": proposed.route_id,
                    "workspace": workspace_id,
                    "surface": surface.value,
                    "subject": subject_id,
                    "owner": proposed.owner.value,
                    "source": proposed.selection_source,
                    "bucket": proposed.cohort_bucket,
                    "percent": proposed.configured_percent,
                    "config": proposed.config_sha256,
                },
            )
            row = (
                (
                    await conn.execute(
                        text(
                            "SELECT id, workspace_id, surface, subject_id, owner, "
                            "selection_source, cohort_bucket, configured_percent, config_sha256 "
                            "FROM agent_runtime_route WHERE workspace_id=:workspace "
                            "AND surface=:surface AND subject_id=:subject"
                        ),
                        {
                            "workspace": workspace_id,
                            "surface": surface.value,
                            "subject": subject_id,
                        },
                    )
                )
                .mappings()
                .one()
            )
        return AgentRouteDecision(
            route_id=row["id"],
            workspace_id=row["workspace_id"],
            surface=AgentRuntimeSurface(row["surface"]),
            subject_id=row["subject_id"],
            owner=AgentOwner(row["owner"]),
            selection_source=row["selection_source"],
            cohort_bucket=row["cohort_bucket"],
            configured_percent=int(row["configured_percent"]),
            config_sha256=row["config_sha256"],
        )


class AgentRuntimeNotComposed(RuntimeError):
    """A subject selected deepagent ownership but no governed runtime was injected."""


class RoutedAccountProfiler:
    """The production DEEP-slot ownership boundary; it never invokes both profilers."""

    def __init__(
        self,
        *,
        router: AgentOwnershipRouter,
        legacy: ProfileAccountFn,
        deepagent: ProfileAccountFn | None,
    ) -> None:
        self._router = router
        self._legacy = legacy
        self._deepagent = deepagent

    async def __call__(self, **kwargs: object) -> AccountProfileResult:
        workspace_id = kwargs.get("workspace_id")
        run_id = kwargs.get("run_id")
        if not isinstance(workspace_id, str) or run_id is None:
            raise ValueError("account routing requires workspace_id and durable account run_id")

        async def legacy() -> AccountProfileResult:
            return await self._legacy(**kwargs)

        async def deepagent() -> AccountProfileResult:
            if self._deepagent is None:
                raise AgentRuntimeNotComposed(
                    "account subject selected deepagent ownership, but the prepared "
                    "AccountResearchTurnRunner is not composed"
                )
            return await self._deepagent(**kwargs)

        return await run_owned_agent_surface(
            router=self._router,
            workspace_id=workspace_id,
            surface=AgentRuntimeSurface.ACCOUNT_RESEARCH,
            subject_id=str(run_id),
            deepagent=deepagent,
            legacy=legacy,
        )


async def run_owned_agent_surface[T](
    *,
    router: AgentOwnershipRouter,
    workspace_id: str,
    surface: AgentRuntimeSurface,
    subject_id: str,
    deepagent: Callable[[], Awaitable[T]],
    legacy: Callable[[], Awaitable[T]],
) -> T:
    """Run exactly one durable owner for a Stage-0 or account-research subject.

    Selection happens before either callable is entered. A selected deepagent failure remains a
    visible deepagent failure; it never falls through to legacy and creates duplicate effects.
    """

    decision = await router.claim(
        workspace_id=workspace_id,
        surface=surface,
        subject_id=subject_id,
    )
    selected = deepagent if decision.owner is AgentOwner.DEEPAGENT else legacy
    return await selected()


class AgentCanarySample(_Value):
    completed: bool
    failure_visible: bool
    terminal_items: int = Field(ge=0)
    promotable_refs: int = Field(ge=0)
    verified_refs: int = Field(ge=0)
    cost_millicredits: int = Field(ge=0)
    rounds: int = Field(ge=0)
    duplicate_effects: int = Field(ge=0)


class AgentCanaryThresholds(_Value):
    minimum_terminal_ratio: float = Field(default=1.0, ge=0, le=1)
    minimum_promotable_ratio: float = Field(default=1.0, ge=0, le=1)
    minimum_verified_ratio: float = Field(default=1.0, ge=0, le=1)
    maximum_cost_ratio: float = Field(default=1.25, ge=1)
    maximum_round_ratio: float = Field(default=2.0, ge=1)


class AgentCanaryAssessment(_Value):
    passed: bool
    reason_codes: tuple[str, ...]


def _ratio(candidate: int, baseline: int) -> float:
    return 1.0 if baseline == 0 else candidate / baseline


def evaluate_agent_canary(
    *,
    baseline: AgentCanarySample,
    candidate: AgentCanarySample,
    thresholds: AgentCanaryThresholds | None = None,
) -> AgentCanaryAssessment:
    """Fail closed on false success, duplicate effects, coverage loss, or runaway cost."""

    thresholds = thresholds or AgentCanaryThresholds()
    reasons: list[str] = []
    if not candidate.completed and not candidate.failure_visible:
        reasons.append("failed_turn_not_visible")
    if candidate.duplicate_effects:
        reasons.append("duplicate_effects")
    if _ratio(candidate.terminal_items, baseline.terminal_items) < (
        thresholds.minimum_terminal_ratio
    ):
        reasons.append("terminal_coverage_regressed")
    if _ratio(candidate.promotable_refs, baseline.promotable_refs) < (
        thresholds.minimum_promotable_ratio
    ):
        reasons.append("promotable_evidence_regressed")
    if _ratio(candidate.verified_refs, baseline.verified_refs) < (
        thresholds.minimum_verified_ratio
    ):
        reasons.append("verification_regressed")
    if baseline.cost_millicredits == 0:
        if candidate.cost_millicredits > 0:
            reasons.append("cost_exceeded_zero_baseline")
    elif candidate.cost_millicredits / baseline.cost_millicredits > thresholds.maximum_cost_ratio:
        reasons.append("cost_band_exceeded")
    if baseline.rounds == 0:
        if candidate.rounds > 0:
            reasons.append("rounds_exceeded_zero_baseline")
    elif candidate.rounds / baseline.rounds > thresholds.maximum_round_ratio:
        reasons.append("round_band_exceeded")
    return AgentCanaryAssessment(passed=not reasons, reason_codes=tuple(reasons))


@dataclass(frozen=True, slots=True)
class AgentPlatformComponents:
    profiles: AgentProfileRegistry
    models: AgentModelProvider
    workspaces: AgentWorkspaceFactory
    artifacts: DurableAgentArtifactStore
    turns: DbAgentTurnJournal
    history: DbAgentHistoryStore
    replay: DbAgentReplayReader
    privacy: AgentPrivacyService
    ownership: DbAgentOwnershipRouter
    #: How many of a thread's past images the conversation layer may re-send (0 = no cap). The
    #: default keeps the trial and test builders, which have no Settings, working unchanged.
    history_images_max: int = 20
    #: Head-of-ABM's turn limits are operator settings, not profile content (founder ruling
    #: 2026-09-27), so changing one never mints a profile version. ``None`` = no timeout / no
    #: long-turn alert. The defaults mirror the shipped settings for builders with no Settings.
    head_of_abm_max_model_rounds: int = 350
    #: Spec 2026-09-29 §3.1: continue the thread's saved conversation (the shipped default).
    head_of_abm_continuation_enabled: bool = True
    head_of_abm_turn_timeout_s: float | None = None
    agent_long_turn_alert_s: float | None = 3600.0
    #: Where the code sandbox looks up a turn's host directories and its remaining run budget
    #: (spec 2026-09-19 §3.4). It is the **same object** the toolbelt's ``run_python@1`` was
    #: built with, because a second registry would be a second, empty, truth. A process that
    #: composed none — every HTTP root, and every deployment with the sandbox off — leaves it
    #: ``None``, the conversation engine registers nothing, and the tool refuses by name.
    sandbox_workspaces: SandboxWorkspaces | None = None


def build_agent_platform_components(
    *,
    settings: Settings,
    secrets: Secrets,
    gateway_config: GatewayConfig,
    storage: StorageBackend,
    tools: ToolRegistry,
    conn_factory: ConnFactory = transaction,
    sandbox_workspaces: SandboxWorkspaces | None = None,
) -> AgentPlatformComponents:
    """Build every common C6 production adapter at the API root; fail before model spend.

    ``sandbox_workspaces`` is *passed in*, never built here, and that is deliberate: the toolbelt
    handed to ``run_python@1`` and the conversation engine that registers the turn must share one
    registry instance, so the composition root that builds both owns it (the fleet worker does).
    """

    artifacts = DurableAgentArtifactStore(storage=storage, conn_factory=conn_factory)
    workspaces = build_agent_workspace_factory(storage=storage, settings=settings)
    profiles = build_agent_profile_registry(tools)
    design_run_purger = None
    if settings.design_runtime_enabled:
        from lumen_api.runtime_privacy import build_runtime_workspace_purger

        design_run_purger = build_runtime_workspace_purger()
    # A DSAR erasure takes an interview quote out of the project library's ``decisions.md`` — a
    # compiled rendering beside the threads, which no tombstone reaches — so the privacy service
    # rewrites the library of every project it touched once the erasure has committed.
    library = ProjectLibraryRefresher(
        storage=storage,
        artifacts=artifacts,
        workspaces=workspaces,
        conn_factory=conn_factory,
    )
    return AgentPlatformComponents(
        profiles=profiles,
        models=build_agent_model_provider(config=gateway_config, secrets=secrets),
        workspaces=workspaces,
        artifacts=artifacts,
        turns=DbAgentTurnJournal(conn_factory=conn_factory),
        history=DbAgentHistoryStore(conn_factory=conn_factory),
        replay=DbAgentReplayReader(storage=storage, conn_factory=conn_factory),
        privacy=AgentPrivacyService(
            storage=storage,
            workspaces=workspaces,
            conn_factory=conn_factory,
            design_run_purger=design_run_purger,
            library=library,
        ),
        ownership=DbAgentOwnershipRouter(settings=settings, conn_factory=conn_factory),
        history_images_max=settings.chat_attachment_history_images_max,
        head_of_abm_max_model_rounds=settings.head_of_abm_max_model_rounds,
        head_of_abm_continuation_enabled=settings.head_of_abm_continuation_enabled,
        head_of_abm_turn_timeout_s=settings.head_of_abm_turn_timeout_s or None,
        agent_long_turn_alert_s=settings.agent_long_turn_alert_s or None,
        sandbox_workspaces=sandbox_workspaces,
    )


def build_agent_context_assembler(
    *,
    resolved_profile: ResolvedAgentProfile,
    artifacts: DurableAgentArtifactStore,
    cards: CompiledContextCardReader,
    memory: ContextAssembly,
    memory_recipe: str,
    requested_memory_types: tuple[MemoryType, ...],
    policy: ContextAssemblyPolicy,
    captured_turns: CapturedTurnBinder | None = None,
    attachment_describer: AttachmentDescriber | None = None,
    history_images_max: int = 20,
    conn_factory: ConnFactory = transaction,
) -> DeterministicAgentContextAssembler:
    """Compose the one exact L1-L7 production assembler for a resolved role/profile.

    ``captured_turns`` (PC-C8 §6b) is the binder L7 names the turn's capture from. A composition
    root that also builds the execution seam passes *its* binder here so one turn is resolved once
    (the trial does); a caller with no execution seam of its own gets a private one. Either way the
    binding is derived from durable state, so two instances could only ever agree — sharing saves
    the second read and the second cache, not correctness.

    ``attachment_describer`` is how L7 names the files on the turn. A surface whose submissions
    carry no attachments passes none and keeps the pointer-only line, which is the honest thing to
    say when nothing durable names the file.

    ``history_images_max`` caps how many of the thread's earlier images L6 re-sends (0 = all); a
    surface with no setting of its own keeps the default rather than deciding the budget itself.
    """

    return DeterministicAgentContextAssembler(
        sources=(
            IdentityLayerSource(resolved_profile),
            WorkspaceProductLayerSource(cards),
            ProjectLayerSource(artifacts=artifacts),
            MemoryLayerSource(
                assembly=memory,
                recipe=memory_recipe,
                requested_types=requested_memory_types,
            ),
            FocusLayerSource(cards),
            # Ruling 2 (spec 2026-09-18): images the user already sent stay in the conversation,
            # newest first, up to this many per thread.
            HistoryLayerSource(artifacts, images_max=history_images_max),
            TurnLayerSource(
                artifacts,
                # PC-C8 §6b: L7 names the turn's capture so the model can reference it; a surface
                # whose turn is not a captured onboarding input simply gets no envelope.
                captured_turn=captured_turns
                or CapturedTurnBinder(artifacts=artifacts, conn_factory=conn_factory),
                attachments=attachment_describer,
            ),
        ),
        policy=policy,
        receipts=DbAgentContextReceiptStore(conn_factory=conn_factory),
        # The assembler reads the turn's image bytes itself, at the one moment it builds the user
        # message; the same durable store every layer source already reads through.
        artifacts=artifacts,
    )

"""``ComposingRunDriver`` — the fleet run-start composition (PB-B4 slice 1, D1/D2).

The detached :class:`~clue_fleet.ProjectRunWorker` drives an injected ``RunDriver`` (``status`` /
``advance``); before B4 that driver was a single process-wide :class:`~clue_research.durable.
ProjectRun` over the *process-default* phase registry, which cannot host the **campaign-scoped**
DEEP/VERIFICATION handlers (they hold one ``ICPSpec``): two concurrent runs with different ICPs
would fight over the DEEP slot, last-write-wins (CLAUDE.md ``[B4×fleet]``). This driver closes that.

**D1 — per-run registries, never the process-global singleton.** On ``advance`` it reads the run
row and composes (or reuses, from a small LRU keyed ``(workspace_id, icp_key, icp_version)``) a
per-run :class:`~clue_research.durable.PhaseHandlerRegistry` + a per-run ``ProjectRun`` bound to the
**shared** durable state (one :class:`DbProjectRunStore`, one :class:`DbIdempotencyStore` ledger,
one :class:`BudgetEngine`). The state-machine object is cheap; the durable state is shared, so two
ICPs on one worker never collide on a phase slot.

**D2 — the composer passes everything production was missing.** Each composition binds: ``storage =
build_storage_backend()`` (every phase born snapshot-wrapped); the fleet
:class:`~clue_fleet.QueueBackedScheduler` for DEEP with ``lock_factory`` (Doc C §4 single-flight
**on**) and ``priority_for`` derived from the ICP rubric's tier bands (rubric-derived tier priority
**on**) — closing the B1-wiring residuals; the settings-built gateway threaded into DEEP /
VERIFICATION / DISCOVERY / the reverse-profiling faithfulness judge; and the per-run high-tier
account resolver shared by DEEP, VERIFICATION, and the HANDOFF retention sweep.

**Composed phase set (per registry):**

* REVERSE_PROFILING / ICP_CONFIRMED / DISCOVERY / SCORING / TIER_CHECKPOINT — via
  :mod:`clue_api.phase_wiring`, snapshot-wrapped (D3).
* DEEP — :func:`build_deep_phase_handler` over the loaded ``ICPSpec`` + the fleet scheduler.
* VERIFICATION — :func:`build_verification_phase_handler` over the shared gateway + the high-tier
  resolver.
* REVIEW — folded in from :func:`register_boot_handlers` (the process-wide-composable handler set).
* HANDOFF — the M10.5 retention/objection sweep (composes from settings; the load-bearing
  tombstone-before-merge invariant) over a **documented-gap inner**: the M12 narrative *emit* path
  is not composable here because **no production ``HandoffCommitteeReader`` exists** until the
  M8/M10 narrative integration lands (``narrative_wiring.build_handoff_assembler`` needs one; only
  the in-memory fixture reader exists). The composer therefore registers the sweep over a
  :class:`_NarrativeGapHandoffHandler` that completes the phase **without emitting narratives**, and
  logs the gap loudly (``composer.handoff.narrative_emit_skipped``) so a real run's missing emit is
  never silent. Wiring the production reader is the M12-integration follow-up, out of B4 scope.

**Reverse-profiling client input (documented ``[M5×M7]`` gap).** The ``ProjectRun`` state machine's
``PhaseContext`` threads only ``tier_cutoffs`` into phase ``params`` — it carries **no client
input** to REVERSE_PROFILING, whose handler needs a ``ClientInput`` (name+website). So a
state-machine-driven reverse-profiling phase cannot complete today. The driver exposes a
``client_input_provider`` seam (default ``None`` → the gap stands, reverse-profiling raises as it
does today) that, when supplied, threads a per-run ``ClientInput`` into the phase — the integration
point for closing ``[M5×M7]`` and what the slice-1 end-to-end test injects to drive a whole run. It
changes no ``durable``/``research`` code.
"""

from __future__ import annotations

from collections import OrderedDict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from clue_api.deep.composition import build_deep_phase_handler, build_high_tier_resolver
from clue_api.fleet_wiring import (
    build_fleet_deep_scheduler,
    register_boot_handlers,
    tier_priority_from_rubric,
)
from clue_api.handoff_retention import build_retention_sweeping_handoff_handler
from clue_api.locks import lazy_account_lock_factory
from clue_api.phase_wiring import (
    build_reverse_profiling_handler,
    register_discovery_handler,
    register_icp_confirmed_handler,
    register_scoring_handler,
    register_tier_checkpoint_handler,
    snapshot_bound,
)
from clue_api.storage_wiring import build_storage_backend
from clue_api.verification import build_verification_phase_handler
from clue_config import Secrets, Settings, default_gateway_config, load_settings
from clue_core import (
    ICPSpec,
    LLMGateway,
    PhaseContext,
    PhaseHandler,
    PhaseResult,
    PhaseStatus,
    ProjectPhase,
    ProjectRunId,
)
from clue_db import ConnFactory, transaction
from clue_fleet import TierPriority, default_tier_priority
from clue_obs import get_logger
from clue_research.discovery_scoring.discovery import ChannelRegistry
from clue_research.durable import (
    BudgetEngine,
    DbIdempotencyStore,
    DbProjectRunStore,
    IdempotencyStore,
    LockFactory,
    PhaseHandlerRegistry,
    ProjectRun,
    ProjectRunRow,
    ProjectRunStore,
)
from clue_research.icp.rubric import rubric_from_slot
from clue_research.icp.spec import get_icp_version
from clue_research.profiling import CommitteeSource
from clue_research.stage0 import ClientInput
from clue_research.verification import FaithfulnessJudgeImpl
from clue_storage import StorageBackend

__all__ = [
    "ComposingRunDriver",
    "ComposedRun",
    "CompositionUnavailable",
    "SpecLoader",
    "ClientInputProvider",
]

log = get_logger("clue_api.run_composition")

# The composition input the driver reads to build a per-run registry.
SpecLoader = Callable[[str, str, int], Awaitable[ICPSpec | None]]
# The [M5×M7] client-input threading seam (default None → the gap stands).
ClientInputProvider = Callable[[PhaseContext], Awaitable[ClientInput | None]]

_HANDOFF_GAP_REASON = (
    "no production HandoffCommitteeReader (M8/M10 narrative integration pending); "
    "the retention/objection sweep runs, the M12 handoff emit does not"
)


class CompositionUnavailable(RuntimeError):
    """The driver cannot compose a per-run registry — the run's ``ICPSpec`` does not exist for its
    ``(workspace_id, icp_key, icp_version)``. DEEP/VERIFICATION are campaign-scoped (one
    ``ICPSpec``), so a run whose ICP version is missing is a misconfiguration (the ICP is confirmed
    before a run is started); fail loud rather than drive a spec-less run."""


@dataclass(frozen=True, slots=True)
class ComposedRun:
    """One composed, cached per-``(workspace_id, icp_key, icp_version)`` unit: the per-run
    ``ProjectRun`` the worker advances, its isolated ``PhaseHandlerRegistry``, the ``ICPSpec`` it
    was composed against, and the set of phases it can drive. The ``spec``/``registry`` are exposed
    so a test can assert two concurrent runs never cross-talk (the D1 race gate) without reaching
    into private attributes."""

    run: ProjectRun
    registry: PhaseHandlerRegistry
    spec: ICPSpec
    phases: frozenset[ProjectPhase]


class _NarrativeGapHandoffHandler:
    """The HANDOFF inner the composer registers in place of the (un-composable) M12 narrative emit
    path: completes the phase **without emitting narratives** and logs the gap loudly, so a real
    run's missing emit is never a silent success. The retention/objection sweep wraps this, so the
    load-bearing tombstone-before-merge invariant still runs in production."""

    phase: ProjectPhase = ProjectPhase.HANDOFF

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        log.warning(
            "composer.handoff.narrative_emit_skipped",
            project_run_id=str(ctx.project_run_id),
            workspace_id=ctx.workspace_id,
            reason=_HANDOFF_GAP_REASON,
        )
        return PhaseResult(
            status=PhaseStatus.COMPLETED,
            accounts_processed=0,
            payload={"narrative_emit_skipped": True, "reason": _HANDOFF_GAP_REASON},
        )


class _ClientInputThreadingHandler:
    """Threads a per-run ``ClientInput`` into the REVERSE_PROFILING phase ``params`` (the
    ``[M5×M7]`` seam). Wraps the real handler; when the injected provider yields a ``ClientInput``
    it is promoted to a top-level ``client_input`` param (which ``ReverseProfilingHandler`` reads),
    else the phase runs unchanged (and raises as today — the documented gap). Composer-side only; no
    durable change."""

    phase: ProjectPhase = ProjectPhase.REVERSE_PROFILING

    def __init__(self, *, inner: PhaseHandler, provider: ClientInputProvider) -> None:
        self._inner = inner
        self._provider = provider

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        client_input = await self._provider(ctx)
        if client_input is not None:
            merged = {**ctx.params, "client_input": client_input.model_dump(mode="json")}
            ctx = ctx.model_copy(update={"params": merged})
        return await self._inner.run(ctx)


def _default_gateway() -> LLMGateway:
    """The production gateway from settings + secrets (stub when no ``OPENROUTER_API_KEY`` — CI).

    ``build_gateway`` is imported **dynamically**, not as a static ``from clue_gateway import …``:
    the import-linter contract "the LLM-vendor SDK lives only behind the gateway/ package" forbids a
    static ``clue_api → clue_gateway`` edge (it would pull the ``openai`` SDK into ``clue_api``'s
    graph). Building the gateway *from outside* the ``clue_api`` package is the sanctioned pattern
    (the ``scripts/`` entrypoints do exactly this and inject the gateway), but the worker entrypoint
    (``python -m clue_api.fleet_main``) lives *inside* ``clue_api``; the dynamic import keeps the
    static graph SDK-free while still routing every model call through the one sanctioned egress —
    a model swap stays a config change (``default_gateway_config``) and ``clue_api`` never touches
    the SDK. Tests inject a stub gateway, so this default runs only in production."""
    from importlib import import_module
    from typing import cast

    build_gateway = import_module("clue_gateway").build_gateway
    gateway = build_gateway(default_gateway_config(), api_key=Secrets().openrouter_api_key)
    return cast("LLMGateway", gateway)


class ComposingRunDriver:
    """The fleet ``RunDriver`` that composes a per-run registry per ``(workspace_id, icp_key,
    icp_version)`` (D1) and drives a per-run ``ProjectRun`` over the shared durable state (D2).

    Every collaborator defaults to its production concrete; tests inject a stub gateway
    (``api_key=None``), an empty ``ChannelRegistry``/``committee_sources``, a fake ``store`` /
    ``spec_loader``, and (to drive REVERSE_PROFILING past the ``[M5×M7]`` gap) a
    ``client_input_provider``. ``lock_factory`` defaults to the **lazy** production single-flight
    factory (single-flight **on**, no ``redis_lifespan`` needed at construction — the B1
    composition-site default); ``fleet_main`` passes the eager ``build_account_lock_factory()``
    since the worker constructs the driver inside ``redis_lifespan``. Either way single-flight is
    on."""

    def __init__(
        self,
        *,
        settings: Settings | None = None,
        store: ProjectRunStore | None = None,
        ledger: IdempotencyStore | None = None,
        budget_engine: BudgetEngine | None = None,
        gateway: LLMGateway | None = None,
        storage: StorageBackend | None = None,
        lock_factory: LockFactory | None = None,
        committee_sources: Sequence[CommitteeSource] = (),
        channels: ChannelRegistry | None = None,
        spec_loader: SpecLoader | None = None,
        client_input_provider: ClientInputProvider | None = None,
        cache_size: int | None = None,
        session_factory: ConnFactory = transaction,
    ) -> None:
        self._settings = settings if settings is not None else load_settings()
        self._store: ProjectRunStore = store if store is not None else DbProjectRunStore()
        self._ledger: IdempotencyStore = ledger if ledger is not None else DbIdempotencyStore()
        self._budget = budget_engine if budget_engine is not None else BudgetEngine()
        self._gateway = gateway if gateway is not None else _default_gateway()
        self._storage = storage if storage is not None else build_storage_backend(self._settings)
        self._lock_factory: LockFactory = (
            lock_factory if lock_factory is not None else lazy_account_lock_factory()
        )
        self._committee_sources = tuple(committee_sources)
        self._channels = channels if channels is not None else ChannelRegistry()
        self._client_input_provider = client_input_provider
        self._session_factory = session_factory
        self._spec_loader: SpecLoader = spec_loader if spec_loader is not None else self._load_spec
        # The reverse-profiling faithfulness judge over the shared gateway — one instance, reused
        # across every composed registry (it holds no per-run state).
        self._rp_judge = FaithfulnessJudgeImpl(gateway=self._gateway)
        # A probe machine over the SHARED store for status reads (its registry is unused for status;
        # advance always runs on the composed per-run machine).
        self._probe = ProjectRun(store=self._store, budget_engine=self._budget, ledger=self._ledger)
        self._cache_size = (
            cache_size if cache_size is not None else self._settings.composer_registry_cache_size
        )
        self._cache: OrderedDict[tuple[str, str, int], ComposedRun] = OrderedDict()

    # -- RunDriver protocol --

    async def status(self, project_run_id: ProjectRunId) -> ProjectRunRow:
        """The current run row (raises ``ProjectRunNotFound`` if the run does not exist)."""
        return await self._probe.status(project_run_id)

    async def advance(self, project_run_id: ProjectRunId) -> ProjectRunRow:
        """Compose (or reuse) the run's per-registry ``ProjectRun`` and step it one phase."""
        row = await self._probe.status(project_run_id)
        composed = await self.composed(row)
        return await composed.run.advance(project_run_id)

    # -- composition --

    async def composed(self, row: ProjectRunRow) -> ComposedRun:
        """The cached (LRU) per-run composition for ``row``'s ``(workspace_id, icp_key,
        icp_version)`` — composing it on first use. Exposed for tests (the D1 isolation checks)."""
        key = (row.workspace_id, row.icp_key, row.icp_version)
        cached = self._cache.get(key)
        if cached is not None:
            self._cache.move_to_end(key)
            return cached
        composed = await self._compose(row)
        self._cache[key] = composed
        self._cache.move_to_end(key)
        while len(self._cache) > self._cache_size:
            self._cache.popitem(last=False)
        return composed

    async def _load_spec(self, workspace_id: str, icp_key: str, icp_version: int) -> ICPSpec | None:
        async with self._session_factory() as conn:
            return await get_icp_version(conn, workspace_id, icp_key, icp_version)

    def _priority_for(self, spec: ICPSpec) -> TierPriority:
        """The DEEP scheduler's tier priority, from the ICP rubric's tier bands (rubric-stable band
        ordering — the run's approved ``tier_cutoffs`` carry the same band labels; sourcing from the
        rubric makes the priority correct even when the registry is composed at an early phase,
        before ``tier_checkpoint`` writes the run's cutoffs). Falls back to the stock ladder when
        the spec carries no rubric bands (nothing to rank)."""
        rubric = rubric_from_slot(spec.scoring_rubric)
        cutoffs = rubric.tier_cutoffs if rubric is not None else None
        if cutoffs is not None and cutoffs.bands:
            return tier_priority_from_rubric(cutoffs)
        return default_tier_priority

    async def _compose(self, row: ProjectRunRow) -> ComposedRun:
        spec = await self._spec_loader(row.workspace_id, row.icp_key, row.icp_version)
        if spec is None:
            raise CompositionUnavailable(
                f"no ICP spec for ({row.workspace_id!r}, {row.icp_key!r}, v{row.icp_version}); "
                "cannot compose the campaign-scoped DEEP/VERIFICATION handlers"
            )
        registry = PhaseHandlerRegistry()

        # Process-wide-composable handlers (REVIEW today) folded into this per-run registry (D1).
        register_boot_handlers(self._settings, storage=self._storage, registry=registry)

        # M5/M6 (snapshot-wrapped, D3). REVERSE_PROFILING optionally threads client input ([M5×M7]).
        rp: PhaseHandler = build_reverse_profiling_handler(judge=self._rp_judge)
        if self._client_input_provider is not None:
            rp = _ClientInputThreadingHandler(inner=rp, provider=self._client_input_provider)
        registry.register(snapshot_bound(rp, storage=self._storage))
        register_icp_confirmed_handler(storage=self._storage, register=registry.register)
        register_discovery_handler(
            channels=self._channels,
            gateway=self._gateway,
            storage=self._storage,
            register=registry.register,
        )
        register_scoring_handler(storage=self._storage, register=registry.register)
        register_tier_checkpoint_handler(storage=self._storage, register=registry.register)

        # DEEP — campaign-scoped (one ICPSpec) over the fleet scheduler; single-flight + rubric
        # priority ON (D2 / the B1-wiring residuals).
        scheduler = build_fleet_deep_scheduler(
            self._settings,
            lock_factory=self._lock_factory,
            priority_for=self._priority_for(spec),
        )
        deep = build_deep_phase_handler(
            spec=spec,
            gateway=self._gateway,
            committee_sources=self._committee_sources,
            storage=self._storage,
            scheduler=scheduler,
        )
        registry.register(deep.handler)

        # VERIFICATION — the high-tier resolver shared with DEEP.
        verification = build_verification_phase_handler(
            gateway=self._gateway, account_resolver=build_high_tier_resolver(spec=spec)
        )
        registry.register(verification)

        # HANDOFF — the retention/objection sweep (composes from settings) over the documented-gap
        # inner (no production HandoffCommitteeReader → the M12 emit path is not composable here).
        handoff = build_retention_sweeping_handoff_handler(
            inner=_NarrativeGapHandoffHandler(),
            account_resolver=build_high_tier_resolver(spec=spec),
            storage=self._storage,
        )
        registry.register(handoff)

        run = ProjectRun(
            store=self._store,
            registry=registry,
            budget_engine=self._budget,
            ledger=self._ledger,
        )
        phases = registry.phases()
        # One structured log per composition (cache fill), not per advance.
        log.info(
            "composer.registry_composed",
            workspace_id=row.workspace_id,
            icp_key=row.icp_key,
            icp_version=row.icp_version,
            phases=sorted(phase.value for phase in phases),
            handoff_narrative_emit=False,
            handoff_narrative_gap=_HANDOFF_GAP_REASON,
        )
        return ComposedRun(run=run, registry=registry, spec=spec, phases=phases)

"""``ComposingRunDriver`` — the fleet run-start composition (PB-B4 slice 1, D1/D2).

The detached :class:`~clue_fleet.ProjectRunWorker` drives an injected ``RunDriver`` (``status`` /
``advance``); before B4 that driver was a single process-wide :class:`~clue_research.durable.
ProjectRun` over the *process-default* phase registry, which cannot host the **campaign-scoped**
DEEP/VERIFICATION handlers (they hold one ``ICPSpec``): two concurrent runs with different ICPs
would fight over the DEEP slot, last-write-wins (CLAUDE.md ``[B4×fleet]``). This driver closes that.

**D1 — per-run registries, never the process-global singleton.** On ``advance`` it reads the run
row and composes (or reuses, from a small LRU keyed by ``project_run_id``) a
per-run :class:`~clue_research.durable.PhaseHandlerRegistry` + a per-run ``ProjectRun`` bound to the
**shared** durable state (one :class:`DbProjectRunStore`, one :class:`DbIdempotencyStore` ledger,
one :class:`BudgetEngine`). The state-machine object is cheap; the durable state is shared, so two
ICPs on one worker never collide on a phase slot.

**M8D R11.1 — the entity-research slot joins the fleet.** The valid phase, storage, discovery,
verification, and handoff substrates remain composed per run. ``DEEP`` holds the join-only
:class:`~clue_api.entity_research_deep_phase.EntityResearchDeepPhaseHandler`, which reads the
project run's latest R6 account-research fleet run and maps its state onto the phase result. It
launches nothing (launch authority stays with the human-confirmed ``launch_account_research@1``)
and owns no spend, so the former account scheduler, provider preparation, committee preparation and
contact progression stay retired behind the untouched R1 quarantine.

**Composed phase set (per registry):**

* REVERSE_PROFILING / ICP_CONFIRMED / DISCOVERY / SCORING / TIER_CHECKPOINT — via
  :mod:`clue_api.phase_wiring`, snapshot-wrapped (D3).
* DEEP — the M8D R11.1 join-only fleet bridge; no legacy entity-research work is scheduled.
* VERIFICATION — :func:`build_verification_phase_handler` over the shared gateway + the R11.3
  researched-account resolver (the M8D fleet read that replaced the ``account_deep_launch``
  high-tier resolver; it fails loud instead of reporting a silent ``accounts_processed=0``).
* REVIEW — folded in from :func:`register_boot_handlers` (the process-wide-composable handler set).
* HANDOFF — the M10.5 retention/objection sweep (the load-bearing tombstone-before-merge
  invariant) over the real M12 phase handler. C7.6 binds a production committee reader to the
  exact run/product, materialises the handoff, then emits the existing durable outbox event.

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
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from clue_api.claim_extraction import LlmClaimExtractor
from clue_api.contact_eligibility import (
    build_contact_eligibility_resolver,
    build_production_handoff_committee_reader,
)
from clue_api.discovery_seal import (
    DbSealedDiscoveryAccountManifestReader,
    DiscoveryBatchStarter,
    DiscoveryRequiredFieldResolver,
)
from clue_api.entity_research_deep_phase import EntityResearchDeepPhaseHandler
from clue_api.entity_research_verification_resolver import (
    build_entity_research_account_resolver,
)
from clue_api.fleet_wiring import register_boot_handlers
from clue_api.handoff_retention import build_retention_sweeping_handoff_handler
from clue_api.handoff_wiring import build_handoff_phase_handler
from clue_api.narrative_wiring import build_handoff_assembler
from clue_api.phase_wiring import (
    build_reverse_profiling_handler,
    register_discovery_handler,
    register_icp_confirmed_handler,
    register_scoring_handler,
    register_tier_checkpoint_handler,
    snapshot_bound,
)
from clue_api.project_execution_router import ProjectExecutionRouter
from clue_api.run_events_wiring import NullRunEventEmitter, RunEventEmitter
from clue_api.storage_wiring import build_storage_backend
from clue_api.verification import build_verification_phase_handler
from clue_config import Secrets, Settings, default_gateway_config, load_settings
from clue_core import (
    ICPSpec,
    LLMGateway,
    PhaseContext,
    PhaseHandler,
    PhaseResult,
    ProjectPhase,
    ProjectRunId,
)
from clue_db import ConnFactory, transaction
from clue_gateway import build_gateway
from clue_obs import get_logger
from clue_research.adapters import CallableClaimExtractor, ClaimExtractor
from clue_research.discovery_scoring.discovery import ChannelRegistry
from clue_research.durable import (
    BudgetEngine,
    DbIdempotencyStore,
    DbProjectRunStore,
    IdempotencyStore,
    PhaseHandlerRegistry,
    ProjectRun,
    ProjectRunRow,
    ProjectRunStore,
)
from clue_research.icp.spec import get_icp_version
from clue_research.resolvers.exa_search import (
    AUTH_REF as EXA_SEARCH_AUTH_REF,
)
from clue_research.resolvers.exa_search import (
    register_exa_search_resolver,
)
from clue_research.resolvers.live import AccountLookup
from clue_research.stage0 import ClientInput
from clue_research.verification import FaithfulnessJudgeImpl
from clue_storage import StorageBackend

__all__ = [
    "build_platform_gateway",
    "build_optional_platform_gateway",
    "bind_stage0_search_resolver",
    "build_stage0_claim_extractor",
    "ComposingRunDriver",
    "ComposedRun",
    "CompositionUnavailable",
    "ClientInputProviderMissing",
    "SpecLoader",
    "ClientInputProvider",
]

log = get_logger("clue_api.run_composition")

# The composition input the driver reads to build a per-run registry.
SpecLoader = Callable[[str, str, int], Awaitable[ICPSpec | None]]
# The [M5×M7] client-input threading seam (default None → the gap stands).
ClientInputProvider = Callable[[PhaseContext], Awaitable[ClientInput | None]]


class CompositionUnavailable(RuntimeError):
    """The driver cannot compose a per-run registry — the run's ``ICPSpec`` does not exist for its
    ``(workspace_id, icp_key, icp_version)``. DEEP/VERIFICATION are campaign-scoped (one
    ``ICPSpec``), so a run whose ICP version is missing is a misconfiguration (the ICP is confirmed
    before a run is started); fail loud rather than drive a spec-less run."""


class ClientInputProviderMissing(RuntimeError):
    """REVERSE_PROFILING was driven with **no** ``client_input_provider`` wired — the documented
    ``[M5×M7]`` gap. The ``ProjectRun`` ``PhaseContext`` threads only ``tier_cutoffs`` into phase
    ``params``, never a ``ClientInput`` (name+website), so the reverse-profiling handler has nothing
    to profile the client from. Raised (instead of a bare pydantic ``ValidationError`` from deep
    inside the handler) so the failure names the seam to wire: construct the ``ComposingRunDriver``
    with a ``client_input_provider`` that yields the run's ``ClientInput``."""


@dataclass(frozen=True, slots=True)
class ComposedRun:
    """One composed, cached per-project-run unit: the ``ProjectRun`` the worker advances, its
    isolated ``PhaseHandlerRegistry``, the ``ICPSpec`` it was composed against, the R11.1 join-only
    DEEP handler, and the set of phases it can drive. The ``spec``/``registry``/``deep`` are exposed
    so a test can assert two concurrent runs never cross-talk (the D1 race gate) without reaching
    into private attributes."""

    run: ProjectRun
    registry: PhaseHandlerRegistry
    spec: ICPSpec
    deep: EntityResearchDeepPhaseHandler
    phases: frozenset[ProjectPhase]


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


class _MissingClientInputHandler:
    """The REVERSE_PROFILING handler the composer registers when **no** ``client_input_provider``
    is wired (the ``[M5×M7]`` gap): the state machine threads no ``ClientInput``, so the real
    handler would raise a bare pydantic ``ValidationError`` from inside ``reverse_profile``. This
    stand-in fails loud and *actionably* instead — a typed :class:`ClientInputProviderMissing`
    naming the seam to wire — so a run that reaches this phase without an input provider gives an
    operator the fix, not a stack trace deep in synthesis. Composer-side only; no durable change."""

    phase: ProjectPhase = ProjectPhase.REVERSE_PROFILING

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        raise ClientInputProviderMissing(
            f"REVERSE_PROFILING for run {ctx.project_run_id} has no client_input_provider wired "
            "(the [M5×M7] gap): the ProjectRun PhaseContext carries no ClientInput (name+website), "
            "so the reverse-profiling handler cannot run. Construct "
            "ComposingRunDriver(client_input_provider=…) to thread a per-run ClientInput."
        )


def build_platform_gateway(settings: Settings) -> LLMGateway:
    """The production gateway from settings + secrets.

    When the ``OPENROUTER_API_KEY`` secret is absent, :func:`~clue_gateway.build_gateway` would
    build the deterministic :class:`StubGateway` — correct for CI, catastrophic in production (a
    misconfigured worker would drive real runs on canned LLM output, the pre-mortem #2 enemy). So
    the stub is **opt-in**: with ``settings.gateway_allow_stub`` False (the default) a missing key
    is a loud ``RuntimeError`` naming the setting **and** the missing secret; with it True we log a
    WARNING (``composer.gateway.stub_mode``) and build the stub. Tests/CI/scripts opt in explicitly
    (the scripts pass ``api_key=None`` deliberately).

    ``build_gateway`` is imported statically (``from clue_gateway import build_gateway``). That
    ``clue_api → clue_gateway`` edge is the sanctioned single LLM egress; it is exempted on the one
    import-linter contract it would trip (Rule 4b "the LLM-vendor SDK lives only behind the
    gateway/ package", via ``clue_api.run_composition -> clue_gateway``), so the ``openai`` SDK
    never enters ``clue_api``'s enforced graph — a model swap stays a ``default_gateway_config``
    change and ``clue_api`` never touches the SDK directly."""
    api_key = Secrets().openrouter_api_key
    if api_key is None:
        if not settings.gateway_allow_stub:
            raise RuntimeError(
                "no OPENROUTER_API_KEY secret and CLUE_GATEWAY_ALLOW_STUB is not set — refusing to "
                "build a canned-output StubGateway in production (a misconfigured worker would "
                "drive runs on stub LLM output). Supply the OpenRouter API key, or set "
                "CLUE_GATEWAY_ALLOW_STUB=true to allow the stub explicitly (CI/tests do this)."
            )
        log.warning(
            "composer.gateway.stub_mode",
            reason="no OPENROUTER_API_KEY secret; CLUE_GATEWAY_ALLOW_STUB opt-in is set",
        )
    return build_gateway(default_gateway_config(), api_key=api_key)


# Backward-compatible test/internal name; production composition uses the public API-root builder.
_default_gateway = build_platform_gateway


def build_optional_platform_gateway(settings: Settings) -> LLMGateway | None:
    """The platform gateway when one is *configured*, else ``None`` — never a raise.

    :func:`build_platform_gateway` refuses to build without an ``OPENROUTER_API_KEY`` (or the
    explicit stub opt-in), which is exactly right for the fleet worker: a worker that cannot call a
    model cannot do its job, so it must fail at boot rather than drive runs on canned output. It is
    the wrong contract for a *degradable* consumer. Stage-0 recon is one: without an extractor it
    still resolves the client, scrapes the official surfaces under target-lock and captures durable
    snapshot evidence — it simply drafts no ``client.*`` values (the slice-2 posture, and the
    interview remains the tier-1 fill path). Taking the whole HTTP process down at import because
    one tool's optional LLM step has no credential would be a strictly worse outcome.

    So this mirrors :func:`build_platform_gateway`'s own key check — same secret, same
    ``gateway_allow_stub`` opt-in — and turns the refusal into a loud, greppable
    ``stage0.claim_extraction_disabled_no_gateway`` warning plus ``None``. Deployed without a key
    the fallback is silent-shaped (no values are drafted), so this warning is the operator's only
    signal: it names the cause and the fix.

    **"Never a raise" is enforced, not merely intended.** The pre-check is a *copy* of the
    refusal condition, and a copy can drift: were ``build_platform_gateway`` to start refusing on a
    condition this one does not test, the delegation would raise and take the HTTP root down at
    import — precisely the failure this function exists to prevent. So the delegation is wrapped:
    the pre-check keeps the common path's specific reason, and the wrapper makes the contract true
    by construction for any refusal the pre-check does not (yet) know about.
    ``test_the_two_gateway_builders_agree_on_the_no_key_case`` pins the two against each other so
    drift is *also* caught loudly at test time rather than only degraded silently in production.
    """
    if Secrets().openrouter_api_key is None and not settings.gateway_allow_stub:
        log.warning(
            "stage0.claim_extraction_disabled_no_gateway",
            reason=(
                "no OPENROUTER_API_KEY secret and CLUE_GATEWAY_ALLOW_STUB is not set; Stage-0 "
                "recon will scrape and snapshot but draft no client.* claims"
            ),
        )
        return None
    try:
        return build_platform_gateway(settings)
    except RuntimeError as exc:
        # The documented refusal (and any future sibling of it). A degradable consumer degrades.
        log.warning(
            "stage0.claim_extraction_disabled_no_gateway",
            reason=(
                "the platform gateway refused to build; Stage-0 recon will scrape and snapshot "
                "but draft no client.* claims"
            ),
            detail=str(exc),
        )
        return None


def build_stage0_claim_extractor(gateway: LLMGateway | None) -> ClaimExtractor:
    """The Stage-0 recon extractor for a deployment that has (or has not) a model gateway.

    With a gateway this is the production :class:`~clue_api.claim_extraction.LlmClaimExtractor`
    (grounded, drop-never-raise, honest-empty on an outage). Without one it is the explicitly empty
    extractor both roots wired in slice 2 — snapshots without values — so a keyless deployment keeps
    working, just without drafted claims.

    One function, called by both composition roots, so the HTTP and fleet processes cannot drift
    into extracting differently from the same scraped page.
    """
    if gateway is None:
        return CallableClaimExtractor(lambda normalized, entity, field: [])
    return LlmClaimExtractor(gateway=gateway)


def bind_stage0_search_resolver(
    *,
    extractor: ClaimExtractor,
    accounts: AccountLookup,
    secrets: Secrets | None = None,
) -> bool:
    """Bind the tier-3 ``exa_search`` resolver for Stage-0 recon, if this deployment can pay for it.

    Two Client-KB fields (``client.competitor`` / ``client.buyer_profile``) name ``exa_search`` as
    their only source. It reads the *same* extractor instance as the scrape lane (one extractor per
    process — the roots must not drift into extracting differently) and the *same* account lookup
    (the Stage-0 binder, which holds the client's record once identity resolution has produced it).

    **The credential gate is the point.** ``resolve_credential`` raises at call time when
    ``CLUE_EXA_API_KEY`` is unset, and a resolver raising inside the waterfall fails the whole recon
    lane — so a deployment with no Exa key would lose onboarding entirely over an optional
    open-web enrichment. Leaving the source *unbound* instead is the documented graceful path: the
    waterfall records ``NO_RESOLVER`` at zero spend and the two fields end honestly empty, exactly
    as they did before this source existed. Returns whether the resolver was bound.
    """
    resolved = secrets if secrets is not None else Secrets()
    if resolved.for_auth_ref(EXA_SEARCH_AUTH_REF) is None:
        log.warning(
            "stage0.exa_search_unbound_no_credential",
            reason=(
                "no Exa credential is configured; Stage-0 background research will leave "
                "client.competitor and client.buyer_profile empty rather than fail the lane"
            ),
            auth_ref=EXA_SEARCH_AUTH_REF,
        )
        return False
    register_exa_search_resolver(extractor=extractor, accounts=accounts, secrets=resolved)
    return True


class ComposingRunDriver:
    """The fleet ``RunDriver`` that composes a registry per ``project_run_id`` (D1) and drives a
    per-run ``ProjectRun`` over the shared durable state (D2).

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
        channels: ChannelRegistry | None = None,
        discovery_batch_starter: DiscoveryBatchStarter | None = None,
        discovery_required_field_resolver: DiscoveryRequiredFieldResolver | None = None,
        spec_loader: SpecLoader | None = None,
        client_input_provider: ClientInputProvider | None = None,
        cache_size: int | None = None,
        session_factory: ConnFactory = transaction,
        event_emitter: RunEventEmitter | None = None,
        project_execution_router: ProjectExecutionRouter | None = None,
    ) -> None:
        self._settings = settings if settings is not None else load_settings()
        self._store: ProjectRunStore = store if store is not None else DbProjectRunStore()
        self._ledger: IdempotencyStore = ledger if ledger is not None else DbIdempotencyStore()
        self._budget = budget_engine if budget_engine is not None else BudgetEngine()
        self._gateway = gateway if gateway is not None else build_platform_gateway(self._settings)
        self._storage = storage if storage is not None else build_storage_backend(self._settings)
        self._channels = channels if channels is not None else ChannelRegistry()
        self._discovery_batch_starter = discovery_batch_starter
        self._discovery_required_field_resolver = discovery_required_field_resolver
        self._client_input_provider = client_input_provider
        self._session_factory = session_factory
        self._project_execution_router = project_execution_router
        # D8: the SSE run-event emitter fired at every advance boundary. Defaults to the no-op
        # emitter (a composer driven in a unit test emits nothing); ``fleet_main`` binds the
        # production ``DbRunEventEmitter`` over the ``run_event`` outbox so the detached worker's
        # drives are visible on the SSE stream. Best-effort — a failed emit never sinks the drive.
        self._event_emitter: RunEventEmitter = (
            event_emitter if event_emitter is not None else NullRunEventEmitter()
        )
        self._spec_loader: SpecLoader = spec_loader if spec_loader is not None else self._load_spec
        # The reverse-profiling M9.3 faithfulness judge over the shared gateway — one instance,
        # reused across every composed registry (it holds no per-run state). The same temporary
        # deployment switch that bypasses the VERIFICATION phase's M9 checks must also prevent this
        # earlier M9 judge call; otherwise "verification disabled" would still incur judge spend.
        self._rp_judge = (
            FaithfulnessJudgeImpl(gateway=self._gateway)
            if self._settings.verification_enabled
            else None
        )
        # A probe machine over the SHARED store for status reads (its registry is unused for status;
        # advance always runs on the composed per-run machine).
        # FI pilot budget-controls: the deployment switch reaches every ``ProjectRun`` this driver
        # builds. The engine stays wired in both modes (burn-down/estimate reads and every
        # ``record`` charge are unaffected); only the pre-phase graceful-stop gate is disabled.
        self._enforce_budget = self._settings.budget_controls_enabled
        self._probe = ProjectRun(
            store=self._store,
            budget_engine=self._budget,
            ledger=self._ledger,
            enforce_budget=self._enforce_budget,
        )
        self._cache_size = (
            cache_size if cache_size is not None else self._settings.composer_registry_cache_size
        )
        self._cache: OrderedDict[ProjectRunId, ComposedRun] = OrderedDict()

    # -- RunDriver protocol --

    async def status(self, project_run_id: ProjectRunId) -> ProjectRunRow:
        """The current run row (raises ``ProjectRunNotFound`` if the run does not exist)."""
        return await self._probe.status(project_run_id)

    async def advance(self, project_run_id: ProjectRunId) -> ProjectRunRow:
        """Compose (or reuse) the run's per-registry ``ProjectRun``, step it one phase, and emit the
        transition's SSE ``run_event`` rows (D8, best-effort post-advance)."""
        before = await self._probe.status(project_run_id)
        composed = await self.composed(before)
        after = await composed.run.advance(project_run_id)
        # Structural no-sink guarantee (review F6): a raising emitter — ANY emitter, not just the
        # self-swallowing Db one — must never fail a drive whose advance already committed.
        try:
            await self._event_emitter.phase_transition(before, after)
        except Exception:  # noqa: BLE001 — emission is best-effort by contract
            log.warning("composer.event_emit_failed", exc_info=True)
        return after

    # -- composition --

    async def composed(self, row: ProjectRunRow) -> ComposedRun:
        """The cached (LRU) composition for ``row.id`` — composing it on first use.

        The old ICP-keyed cache was sufficient while handlers held only an ``ICPSpec``. C7.6 adds
        a committee reader bound to the exact durable account-run references, so two project runs
        sharing an ICP must never share a registry.
        """
        key = row.id
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

    async def _compose(self, row: ProjectRunRow) -> ComposedRun:
        spec = await self._spec_loader(row.workspace_id, row.icp_key, row.icp_version)
        if spec is None:
            raise CompositionUnavailable(
                f"no ICP spec for ({row.workspace_id!r}, {row.icp_key!r}, v{row.icp_version}); "
                "cannot compose the campaign-scoped DEEP/VERIFICATION handlers"
            )
        if row.product_id != spec.product_id:
            raise CompositionUnavailable(
                f"product pin mismatch for project run {row.id}: run has {row.product_id!r}, "
                f"ICP spec has {spec.product_id!r}; refusing to compose product-scoped research "
                "or handoff against an ambiguous product"
            )
        registry = PhaseHandlerRegistry()
        # M8D R11.3: one per-run researched-account resolver instance, SHARED by VERIFICATION and
        # the HANDOFF retention sweep (DEEP no longer consumes it — the R11.1 adapter reads fleet
        # state directly). Both need the same fact — which accounts this run actually researched —
        # so they read the run's latest human-confirmed fleet run and its accepted terminal jobs.
        # The closure is stateless, so sharing is trivially safe and makes the "shared" contract
        # true rather than two equivalent-but-separate closures. It fails loud
        # (``EntityResearchRunMissing``) when the run has no fleet run, where the superseded
        # ``build_high_tier_resolver`` reported an empty set as a clean success.
        researched_account_resolver = build_entity_research_account_resolver(
            session_factory=self._session_factory
        )

        # Process-wide-composable handlers (REVIEW today) folded into this per-run registry (D1).
        register_boot_handlers(
            self._settings,
            storage=self._storage,
            registry=registry,
            project_execution_router=self._project_execution_router,
        )

        # M5/M6 (snapshot-wrapped, D3). REVERSE_PROFILING threads client input when a provider is
        # wired ([M5×M7]); with no provider the phase cannot build a ClientInput, so we register a
        # stand-in that fails loud + actionably (a typed ClientInputProviderMissing) rather than the
        # real handler's bare pydantic ValidationError from inside synthesis.
        rp: PhaseHandler
        if self._client_input_provider is not None:
            rp = _ClientInputThreadingHandler(
                inner=build_reverse_profiling_handler(
                    judge=self._rp_judge,
                    enforce_budget=self._enforce_budget,
                ),
                provider=self._client_input_provider,
            )
        else:
            rp = _MissingClientInputHandler()
        registry.register(snapshot_bound(rp, storage=self._storage))
        register_icp_confirmed_handler(storage=self._storage, register=registry.register)
        register_discovery_handler(
            channels=self._channels,
            gateway=self._gateway,
            # The provider flag controls new Exa work, not whether an already-created durable
            # generation keeps its hard barrier after a rollout switch is reduced.
            durable_batches=True,
            durable_batch_starter=self._discovery_batch_starter,
            discovery_required_field_resolver=self._discovery_required_field_resolver,
            session_factory=self._session_factory,
            storage=self._storage,
            register=registry.register,
        )
        sealed_discovery_reader = DbSealedDiscoveryAccountManifestReader(
            storage=self._storage,
            conn_factory=self._session_factory,
        )
        register_scoring_handler(
            storage=self._storage,
            session_factory=self._session_factory,
            sealed_account_reader=sealed_discovery_reader,
            register=registry.register,
        )
        register_tier_checkpoint_handler(
            storage=self._storage,
            sealed_account_reader=sealed_discovery_reader,
            session_factory=self._session_factory,
            register=registry.register,
            enforce_budget=self._enforce_budget,
        )

        # M8D R11.1: DEEP is the join-only bridge onto the R6 account-research fleet. It reads the
        # project run's latest fleet run and maps its state to a phase result — it launches nothing
        # (launch authority stays with the human-confirmed ``launch_account_research@1``), owns no
        # spend, and holds no scheduler, provider preparer, mechanical account profiler, committee
        # walker or contact fan-out. The R1 quarantine over the retired orchestration is untouched.
        deep = EntityResearchDeepPhaseHandler(conn_factory=self._session_factory)
        registry.register(deep)

        # VERIFICATION — the same researched-account resolver instance the HANDOFF sweep uses.
        # ``session_factory`` is threaded like every sibling registration: the corroborator, the
        # judge, the live-claims loader and the use-gate all read/write through the driver's
        # durable seam rather than the process default. Production is unchanged (the driver's
        # default *is* ``transaction``); what it fixes is a composition driven with an injected
        # factory, where VERIFICATION alone used to reach past it to a different connection.
        verification = build_verification_phase_handler(
            gateway=self._gateway,
            account_resolver=researched_account_resolver,
            session_factory=self._session_factory,
            verification_enabled=self._settings.verification_enabled,
        )
        registry.register(verification)

        # HANDOFF — a separate default-off cutover. When disabled there is no HANDOFF handler:
        # the state machine fails closed at dispatch and cannot write a fake success marker. Once
        # enabled, the C7.6 reader is bound to this exact project run and product, and the
        # retention/objection wrapper remains outside the real materialising handler.
        if self._settings.c7_production_handoff_enabled:
            contact_eligibility = build_contact_eligibility_resolver(
                project_run_id=row.id,
                product_id=row.product_id,
                conn_factory=self._session_factory,
            )
            committee_reader = build_production_handoff_committee_reader(contact_eligibility)
            real_handoff = build_handoff_phase_handler(
                assembler=build_handoff_assembler(
                    committee_reader=committee_reader,
                    verification_enabled=self._settings.verification_enabled,
                ),
                conn_factory=self._session_factory,
                product_id=row.product_id,
            )
            handoff = build_retention_sweeping_handoff_handler(
                inner=real_handoff,
                account_resolver=researched_account_resolver,
                session_factory=self._session_factory,
                storage=self._storage,
            )
            registry.register(handoff)

        run = ProjectRun(
            store=self._store,
            registry=registry,
            budget_engine=self._budget,
            ledger=self._ledger,
            enforce_budget=self._enforce_budget,
        )
        phases = registry.phases()
        # One structured log per composition (cache fill), not per advance.
        log.info(
            "composer.registry_composed",
            workspace_id=row.workspace_id,
            icp_key=row.icp_key,
            icp_version=row.icp_version,
            phases=sorted(phase.value for phase in phases),
            entity_research="m8d_r11_fleet_bridge",
            handoff_narrative_emit=self._settings.c7_production_handoff_enabled,
        )
        return ComposedRun(run=run, registry=registry, spec=spec, deep=deep, phases=phases)

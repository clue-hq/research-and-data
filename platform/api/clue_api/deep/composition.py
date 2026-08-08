"""The DEEP-phase composition root (M8A.6) — wire every concrete and register the handler.

This is the one co-import point for the deep phase: the ``api`` composition root where the otherwise
independent milestone packages meet (import-linter Rule 5 — ``api`` is exempt; nothing imports
``api``). It constructs the concretes the M8A.1 orchestrator + M8A.2 handler are *typed against* and
injects them, then registers the :class:`~clue_api.deep.DeepPhaseHandler` so
``ProjectRun.advance()`` dispatches ``ProjectPhase.DEEP`` with zero new dispatch code (the run no
longer raises ``NoPhaseHandlerRegistered(DEEP)``).

What it wires, and where each piece comes from:

* **The three deep callables** — ``profile_account`` / ``discover_committee`` / ``profile_contact``
  (M8) — injected as the orchestrator's stage workers. ``profile_account`` is self-contained (it
  builds its own account-axis aspect workers and runs them directly), so the account axis needs no
  graph dispatch; committee + contact run as direct callables, **not** registered as graph aspects
  (spec §M8A.6 — "committee/contact run as callables and are NOT registered as aspects").
* **The M9 governance seams** (reused from the M8 composition root,
  :mod:`clue_api.composition`) — the concrete :class:`PreSpendGate`
  (:func:`~clue_api.composition.build_pre_spend_gate`) threaded into **all three** axes so
  every claim-producing path gates before it spends (the deferred M9.1 routing, M8A.6 AC-6), and
  ``verification.classify_binding`` behind M8.4's ``BindingClassifier``
  (:func:`~clue_api.composition.production_binding_classifier`) so a born
  ``contact.facet.*`` ``identity_binding`` is the authoritative immutable M9 verdict (the deferred
  M9.4 stamp, AC-4).
  The injected gate is a **required, non-None** collaborator here (it defaults to a real gate) — the
  AC-6 test, not hope, is what enforces that #1 landed before this wiring.
* **The M7 substrate** — the concrete ``BudgetEngine`` (the single live ``cost_cents`` writer +
  admission ``check``), the M8A.4 :class:`DbExactlyOnceSpend` over it (claim + charge + ledger in
  one transaction), the :class:`DbAccountRunIO` sub-phase cursor, an ``AccountResearchGraph`` over
  an account-axis-only :class:`WorkerRegistry`, and the :class:`AccountScheduler` whose M8A.0
  ``run_one`` slot runs the orchestrator under bounded parallelism + the per-entity lock.
* **The high-tier resolver** (D-B) — :func:`build_high_tier_resolver` reads the human-approved set
  from the claim store: every account whose live ``account.scoring.tier`` claim names a (non-
  fallback) band under the committed ``cutoff_version`` carried in the tier-checkpoint ``params``,
  scoped to this ICP. The committed ``cutoff_version`` is re-derived from ``params["tier_cutoffs"]``
  (content-addressed), so it matches what tiering wrote without the handler re-deriving cutoffs.

The DEEP handler is **campaign-scoped** (it holds one ``ICPSpec``): production builds + registers
one per ``(client, icp)`` at run start; a single-ICP deployment builds it once. Pack loading
(:func:`load_research_packs`) is a deploy-time prerequisite — call it once on a connection before
the first deep run so the ``account.resonance.*`` / ``contact.facet.*`` / committee field
definitions a deep run reads are registered.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Final

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from clue_api.composition import (
    load_research_packs,
)
from clue_api.deep.handler import (
    CheckpointerFactory,
    DeepAccountScheduler,
    HighTierResolver,
)
from clue_api.deep.orchestrator import AccountDeepOrchestrator
from clue_api.entity_research_quarantine import EntityResearchAgentNotComposed
from clue_config import OverlayStore
from clue_core import (
    Claim,
    ICPSpec,
    LLMGateway,
    PhaseContext,
    PhaseHandler,
    PreSpendGate,
)
from clue_db import ConnFactory, transaction
from clue_research.claimstore import WorkspaceScope, claims_for, entities_with_field_claim
from clue_research.directives import (
    effective_account_research_directive,
    get_research_directive,
)
from clue_research.discovery_scoring.tiering import (
    TIER_FIELD,
    DiscoverySelectionPolicy,
    ScoringMode,
    cutoff_version,
)
from clue_research.durable import (
    AccountSpec,
    BudgetEngine,
    WorkerRegistry,
    account_deep_launch_account_pins,
    get_account_deep_launch,
    register_phase_handler,
)
from clue_research.icp.rubric import TierCutoffs
from clue_research.profiling import (
    CommitteeSource,
    SynthesisGuard,
    account_axis_workers,
)
from clue_research.profiling.contact.binding import BindingClassifier
from clue_research.synthesis import guard_synthesis_resolution
from clue_storage import StorageBackend

__all__ = [
    "DeepPhaseComposition",
    "build_high_tier_resolver",
    "build_account_axis_registry",
    "build_deep_phase_handler",
    "register_deep_phase_handler",
    "load_research_packs",
]


class _LazyLockDefault:
    """Sentinel distinguishing "``lock_factory`` was not passed" (→ the lazy production default,
    single-flight on) from an explicit ``lock_factory=None`` (→ the written opt-out, single-flight
    off — for tests). ``None`` cannot serve as the sentinel because it is the opt-out value."""


_LAZY_LOCK_DEFAULT: Final[_LazyLockDefault] = _LazyLockDefault()


@dataclass(frozen=True, slots=True)
class DeepPhaseComposition:
    """The wired DEEP-phase collaborators (M8A.6).

    :attr:`handler` is the registered article — the bare :class:`DeepPhaseHandler`, or (when a B2
    ``storage`` backend is supplied) that handler wrapped in a
    :class:`~clue_api.storage_wiring.SnapshotBindingPhaseHandler` so each deep run captures/flushes
    under one ambient per-run snapshot sink; either way it is a ``core.PhaseHandler`` serving
    ``ProjectPhase.DEEP``. The rest are exposed so a test can assert the governance seams are the
    concretes (the gate + classifier the orchestrator threads into the committee/contact callables)
    without reaching into private attributes. :attr:`spec` is the campaign ``ICPSpec`` the phase was
    composed against — exposed so a per-run composer (the B4 ``ComposingRunDriver``) can prove each
    composed DEEP handler is bound to its run's *own* spec, not a shared/overwritten one."""

    handler: PhaseHandler
    orchestrator: AccountDeepOrchestrator
    scheduler: DeepAccountScheduler
    budget: BudgetEngine
    pre_spend_gate: PreSpendGate
    binding_classifier: BindingClassifier
    spec: ICPSpec


# --- high-tier resolution (D-B) ----------------------------------------------


def build_high_tier_resolver(
    *,
    spec: ICPSpec,
    session_factory: ConnFactory = transaction,
    deep_tiers: frozenset[str] | None = None,
) -> HighTierResolver:
    """The :data:`~clue_api.deep.handler.HighTierResolver` that reads the human-approved
    high-tier set from the claim store (D-B), mapping each to a ``durable.AccountSpec``.

    The committed decision arrives two ways and we honour both: ``ctx.params["tier_cutoffs"]`` (the
    cutoffs the run advanced on — campaign.py threads them into every ``PhaseContext``) gives the
    *approved cutoff* and the band ordering; ``persist_tier`` wrote the per-account verdict as a
    ``account.scoring.tier`` claim carrying ``{tier, cutoff_version, icp_key, …}``. We re-derive the
    content-addressed :func:`cutoff_version` from the params cutoffs (so it matches the claim's
    version without trusting a separately-passed string) and select every account whose **live**
    tier claim, **for this ICP**, names a deep-eligible band at that version.

    "Deep-eligible" defaults to every band the cutoffs *name* (the fallback tier — accounts that
    cleared no band — is excluded); pass ``deep_tiers`` to research only a subset (e.g. the top
    band). An empty / band-less cutoff set selects nothing — a clean COMPLETED no-op for the phase.
    The tier claims are ``tenant_private`` (keyed by ``workspace_id``), so the read is scoped
    :meth:`WorkspaceScope.for_workspace`.
    """

    async def _resolve(ctx: PhaseContext) -> Sequence[AccountSpec]:
        # A confirmed directive is necessary but not itself a launch. O2 persists a separate,
        # immutable launch receipt for the exact run/account subset. Absence is a zero-call no-op,
        # preserving the conversational pause after discovery; a later directive supersession
        # cannot mutate an already-authorized fleet because every selected account carries its
        # immutable effective pin on the launch receipt.
        try:
            selection_policy = DiscoverySelectionPolicy.from_slot(spec.discovery_strategy)
        except ValueError:
            return ()
        selection_mode = selection_policy.scoring_mode is ScoringMode.DISABLED
        if selection_mode:
            committed = selection_policy.policy_version
            eligible = frozenset({selection_policy.approved_tier})
            if deep_tiers is not None:
                eligible &= deep_tiers
        else:
            cutoffs = _tier_cutoffs(ctx.params.get("tier_cutoffs"))
            if cutoffs is None or not cutoffs.bands:
                return ()
            committed = cutoff_version(cutoffs)
            eligible = (
                deep_tiers if deep_tiers is not None else frozenset(b.tier for b in cutoffs.bands)
            )
        scope = WorkspaceScope.for_workspace(ctx.workspace_id)
        specs: list[AccountSpec] = []
        async with session_factory() as conn:
            launch = await get_account_deep_launch(
                conn,
                ctx.project_run_id,
                workspace_id=ctx.workspace_id,
            )
            if launch is None or launch.project_id != ctx.project_id:
                return ()
            directive = await get_research_directive(
                conn,
                launch.directive_id,
                workspace_id=ctx.workspace_id,
            )
            if (
                directive is None
                or directive.project_id != ctx.project_id
                or directive.icp_key != ctx.icp_key
                or directive.icp_version != ctx.icp_version
                or directive.version != launch.directive_version
                or directive.canonical_json_sha256 != launch.directive_sha256
            ):
                return ()
            directed_specs: dict[object, AccountSpec] = {}
            for pin in await account_deep_launch_account_pins(conn, launch):
                effective = await effective_account_research_directive(
                    conn,
                    workspace_id=ctx.workspace_id,
                    directive_id=launch.directive_id,
                    account_id=pin.account_id,
                    expected_pin=pin,
                )
                directed_specs[pin.account_id] = AccountSpec(
                    entity_id=pin.account_id,
                    tier=effective.effort_policy.tier,
                    workspace_id=ctx.workspace_id,
                    field_keys=effective.field_keys,
                    research_directive=pin,
                    budget_cap_cents=effective.effort_policy.budget_cap_cents,
                    contact_profiling_allowed=(effective.privacy_policy.contact_profiling_allowed),
                )
            entity_ids = await entities_with_field_claim(conn, TIER_FIELD, scope=scope)
            for entity_id in entity_ids:
                directed = directed_specs.get(entity_id)
                if directed is None or directed.research_directive is None:
                    continue
                # FI-2 §6.4: an account shared by two projects now carries **two** live tier
                # claims (P2's tier no longer supersedes P1's), so "the most recent live claim"
                # is no longer this project's by construction. Take the most recent live tier
                # THIS project wrote; an unstamped legacy tier is still honoured (it belongs to
                # no project's lens, so any project may read it — the read-side mirror of the
                # legacy absorb rule).
                value = _live_tier_for_project(
                    await claims_for(conn, entity_id, TIER_FIELD, scope=scope),
                    project_id=ctx.project_id,
                )
                if value is None:
                    continue
                if selection_mode:
                    if (
                        value.get("decision_basis") != "discovery_criteria"
                        or value.get("selection_policy_version") != committed
                        or value.get("project_run_id") != str(ctx.project_run_id)
                    ):
                        continue
                elif value.get("cutoff_version") != committed:
                    continue
                if value.get("icp_key") != ctx.icp_key:
                    continue
                tier = value.get("tier")
                if not isinstance(tier, str) or tier not in eligible or directed.tier != tier:
                    continue
                specs.append(
                    AccountSpec(
                        entity_id=entity_id,
                        tier=tier,
                        workspace_id=ctx.workspace_id,
                        field_keys=directed.field_keys,
                        research_directive=directed.research_directive,
                        budget_cap_cents=directed.budget_cap_cents,
                        contact_profiling_allowed=directed.contact_profiling_allowed,
                    )
                )
        return tuple(specs)

    return _resolve


def _live_tier_for_project(
    live: Sequence[Claim], *, project_id: str
) -> Mapping[str, JsonValue] | None:
    """The most-recent live ``account.scoring.tier`` payload belonging to ``project_id`` (FI-2
    §6.4), or ``None``.

    ``claims_for`` returns live claims most-recent-first. Since §6.4 stopped cross-project
    supersession, several may be live at once — one per project that tiered the account — so this
    picks the caller's own rather than whichever landed last. A payload with **no** ``project_id``
    is a legacy (pre-§6.4) tier attributed to no project and is accepted by any project; a payload
    stamped for a *different* project is skipped.
    """
    for claim in live:
        value = claim.value_json
        if not isinstance(value, dict):
            continue
        stamped = value.get("project_id")
        if isinstance(stamped, str) and stamped != project_id:
            continue
        return value
    return None


def _tier_cutoffs(raw: JsonValue | None) -> TierCutoffs | None:
    """Coerce ``params["tier_cutoffs"]`` to a :class:`TierCutoffs` (it may arrive as the model or
    its JSON dump, depending on how the ``PhaseContext`` was built); ``None``/garbage → ``None``."""
    if raw is None:
        return None
    try:
        return TierCutoffs.model_validate(raw)
    except (ValueError, TypeError):
        return None


# --- worker registry (account axis only) -------------------------------------


def build_account_axis_registry(
    *,
    gateway: LLMGateway,
    pre_spend_gate: PreSpendGate,
    session_factory: ConnFactory = transaction,
    planner_model: str | None = None,
    pack_namespaces: Sequence[str] = (),
    synthesis_guard: SynthesisGuard = guard_synthesis_resolution,
    config_store: OverlayStore | None = None,
) -> WorkerRegistry:
    """A :class:`WorkerRegistry` holding **only** the account-axis aspect workers
    (account / core / resonance / pack) — the graph the M8A scheduler is built over.

    Committee + contact are deliberately absent: the deep orchestrator runs them as direct callables
    (spec §M8A.6), never as graph aspects. ``profile_account`` is itself self-contained (it builds
    its own workers), so the graph this registry backs is never ``.run()`` on the orchestrator's
    ``run_one`` path — but wiring it faithfully keeps the M7 graph dispatchable for the account axis
    and asserts the disjoint-aspect contract (no committee/contact key here)."""
    registry = WorkerRegistry()
    for worker in account_axis_workers(
        pack_namespaces=pack_namespaces,
        session_factory=session_factory,
        gateway=gateway,
        planner_model=planner_model,
        pre_spend_gate=pre_spend_gate,
        synthesis_guard=synthesis_guard,
        config_store=config_store,
    ):
        registry.register(worker)
    return registry


# --- the handler factory -----------------------------------------------------


def _memory_checkpointer_factory() -> CheckpointerFactory:
    """A default :data:`CheckpointerFactory` that yields an in-memory saver.

    ``run_accounts`` requires a checkpointer, but the M8A.1 ``run_one`` path drives the three deep
    callables directly (``profile_account`` owns its own durability), so the scheduler never threads
    it into a graph ``run`` — an in-memory saver is correct and DB-free. Production may pass
    ``checkpointer_factory=lambda: postgres_checkpointer()`` if the account axis is ever moved
    in-graph; today it is unused on this path."""

    class _Cm(AbstractAsyncContextManager[BaseCheckpointSaver[Any]]):
        async def __aenter__(self) -> BaseCheckpointSaver[Any]:
            return InMemorySaver()

        async def __aexit__(self, *exc: object) -> None:
            return None

    def _factory() -> AbstractAsyncContextManager[BaseCheckpointSaver[Any]]:
        return _Cm()

    return _factory


def build_deep_phase_handler(*args: Any, **kwargs: Any) -> DeepPhaseComposition:
    """Retired M8A constructor retained only as a fail-loud compatibility address.

    R1 forbids constructing the pre-agent account -> committee -> contact pipeline for any new
    research launch.  Historical exact replay is served by the tool invocation ledger and never
    requires rebuilding this composition.
    """

    del args, kwargs
    raise EntityResearchAgentNotComposed()


def register_deep_phase_handler(
    *,
    spec: ICPSpec,
    gateway: LLMGateway,
    committee_sources: Sequence[CommitteeSource],
    storage: StorageBackend | None,
    register: Callable[[PhaseHandler], None] = register_phase_handler,
    **kwargs: Any,
) -> DeepPhaseComposition:
    """Build the DEEP phase (:func:`build_deep_phase_handler`) and register its handler into the
    process phase-handler registry — the api-root binder that makes ``ProjectRun.advance()``
    dispatch ``ProjectPhase.DEEP``. ``register`` is injectable so a test can register into a fresh
    :class:`~clue_research.durable.PhaseHandlerRegistry` instead of the process default.

    ``storage`` is a **required** keyword (unlike :func:`build_deep_phase_handler`, where it
    defaults to ``None``): the *production registration* surface makes the B2 snapshot-binding
    decision explicit — pass ``build_storage_backend()`` to register the snapshot-binding wrapper,
    or pass ``None`` to register the bare (pre-B2) handler. Forgetting it is a ``TypeError``, never
    a silent no-snapshot registration."""
    composition = build_deep_phase_handler(
        spec=spec,
        gateway=gateway,
        committee_sources=committee_sources,
        storage=storage,
        **kwargs,
    )
    register(composition.handler)
    return composition

"""The DEEP-phase composition root (M8A.6) — wire every concrete and register the handler.

This is the one co-import point for the deep phase: the ``api`` composition root where the otherwise
independent milestone packages meet (import-linter Rule 5 — ``api`` is exempt; nothing imports
``api``). It constructs the concretes the M8A.1 orchestrator + M8A.2 handler are *typed against* and
injects them, then registers the :class:`~clue_api.deep.DeepPhaseHandler` so
``CampaignRun.advance()`` dispatches ``CampaignPhase.DEEP`` with zero new dispatch code (the run no
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

import functools
from collections.abc import Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import JsonValue

from clue_api.composition import (
    build_pre_spend_gate,
    load_research_packs,
    production_binding_classifier,
)
from clue_api.deep.handler import (
    CheckpointerFactory,
    DeepPhaseHandler,
    HighTierResolver,
)
from clue_api.deep.orchestrator import AccountDeepOrchestrator
from clue_api.deep.run_io import DbAccountRunIO
from clue_api.deep.spend import DbExactlyOnceSpend
from clue_config import DeepPhaseConfig, OverlayStore, RecursionPolicy
from clue_core import (
    CostCents,
    ICPSpec,
    LLMGateway,
    PhaseContext,
    PreSpendGate,
)
from clue_db import ConnFactory, transaction
from clue_research.claimstore import WorkspaceScope, claims_for, entities_with_field_claim
from clue_research.discovery_scoring.tiering import TIER_FIELD, cutoff_version
from clue_research.durable import (
    AccountResearchGraph,
    AccountScheduler,
    AccountSpec,
    BudgetEngine,
    WorkerRegistry,
    register_phase_handler,
)
from clue_research.icp.rubric import TierCutoffs
from clue_research.profiling import (
    CommitteeSource,
    SynthesisGuard,
    account_axis_workers,
    discover_committee,
    profile_account,
    profile_contact,
)
from clue_research.profiling.contact.binding import BindingClassifier
from clue_research.synthesis import guard_synthesis_resolution

__all__ = [
    "DeepPhaseComposition",
    "build_high_tier_resolver",
    "build_account_axis_registry",
    "build_deep_phase_handler",
    "register_deep_phase_handler",
    "load_research_packs",
]


@dataclass(frozen=True, slots=True)
class DeepPhaseComposition:
    """The wired DEEP-phase collaborators (M8A.6).

    :attr:`handler` is the registered article; the rest are exposed so a test can assert the
    governance seams are the concretes (the gate + classifier the orchestrator threads into the
    committee/contact callables) without reaching into private attributes."""

    handler: DeepPhaseHandler
    orchestrator: AccountDeepOrchestrator
    scheduler: AccountScheduler
    budget: BudgetEngine
    pre_spend_gate: PreSpendGate
    binding_classifier: BindingClassifier


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
            entity_ids = await entities_with_field_claim(conn, TIER_FIELD, scope=scope)
            for entity_id in entity_ids:
                live = await claims_for(conn, entity_id, TIER_FIELD, scope=scope)
                if not live:
                    continue
                value = live[0].value_json  # most-recent live tier claim for this account
                if not isinstance(value, dict):
                    continue
                if value.get("cutoff_version") != committed:
                    continue
                if value.get("icp_key") != ctx.icp_key:
                    continue
                tier = value.get("tier")
                if not isinstance(tier, str) or tier not in eligible:
                    continue
                specs.append(
                    AccountSpec(
                        entity_id=entity_id,
                        tier=tier,
                        workspace_id=ctx.workspace_id,
                        field_keys=spec.field_keys or None,
                    )
                )
        return tuple(specs)

    return _resolve


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


def build_deep_phase_handler(
    *,
    spec: ICPSpec,
    gateway: LLMGateway,
    committee_sources: Sequence[CommitteeSource],
    config: DeepPhaseConfig | None = None,
    recursion_policy: RecursionPolicy | None = None,
    role_model: str | None = None,
    planner_model: str | None = None,
    budget: BudgetEngine | None = None,
    pre_spend_gate: PreSpendGate | None = None,
    binding_classifier: BindingClassifier | None = None,
    synthesis_guard: SynthesisGuard = guard_synthesis_resolution,
    session_factory: ConnFactory = transaction,
    high_tier_resolver: HighTierResolver | None = None,
    checkpointer_factory: CheckpointerFactory | None = None,
    budget_cap_cents: CostCents | None = None,
    config_store: OverlayStore | None = None,
) -> DeepPhaseComposition:
    """Construct the fully-wired DEEP phase for one campaign's ICP and return the bundle (M8A.6).

    Every concrete defaults to its production binding, so the minimal call supplies only the
    campaign ``spec``, an ``LLMGateway``, and the committee ``sources`` (no concrete
    :class:`CommitteeSource` lives in any milestone package — they are bound here). The
    ``pre_spend_gate`` and ``binding_classifier`` default to real M9 concretes and are **never
    None** on the orchestrator (the required-collaborator enforcement of AC-6/AC-4). Call
    :func:`register_deep_phase_handler` instead to also register the handler.
    """
    config = config or DeepPhaseConfig()
    recursion_policy = recursion_policy or RecursionPolicy()
    budget = budget or BudgetEngine()
    gate = pre_spend_gate or build_pre_spend_gate()
    binder = binding_classifier or production_binding_classifier()
    resolver = high_tier_resolver or build_high_tier_resolver(
        spec=spec, session_factory=session_factory
    )
    checkpointers = checkpointer_factory or _memory_checkpointer_factory()
    # Bind the layered-config seam onto the live account + contact callables so an injected
    # (test/Stage-0) overlay store reaches the deep workers; ``None`` leaves them on the process
    # default store (the production config source — staged-flow §2 "policy is data").
    account_fn = (
        functools.partial(profile_account, config_store=config_store)
        if config_store is not None
        else profile_account
    )
    contact_fn = (
        functools.partial(profile_contact, config_store=config_store)
        if config_store is not None
        else profile_contact
    )

    orchestrator = AccountDeepOrchestrator(
        profile_account=account_fn,
        discover_committee=discover_committee,
        profile_contact=contact_fn,
        io=DbAccountRunIO(session_factory=session_factory),
        session_factory=session_factory,
        spec=spec,
        config=config,
        budget=budget,
        spend=DbExactlyOnceSpend(budget),
        sources=committee_sources,
        gateway=gateway,
        role_model=role_model,
        binding_classifier=binder,
        recursion_policy=recursion_policy,
        planner_model=planner_model,
        pre_spend_gate=gate,
        synthesis_guard=synthesis_guard,
        budget_cap_cents=budget_cap_cents,
    )

    registry = build_account_axis_registry(
        gateway=gateway,
        pre_spend_gate=gate,
        session_factory=session_factory,
        planner_model=planner_model,
        synthesis_guard=synthesis_guard,
        config_store=config_store,
    )
    graph = AccountResearchGraph(workers=registry, recursion_policy=recursion_policy)
    scheduler = AccountScheduler(graph, max_parallel=config.max_parallel_accounts)

    handler = DeepPhaseHandler(
        scheduler=scheduler,
        orchestrator=orchestrator,
        high_tier_resolver=resolver,
        checkpointer_factory=checkpointers,
    )
    return DeepPhaseComposition(
        handler=handler,
        orchestrator=orchestrator,
        scheduler=scheduler,
        budget=budget,
        pre_spend_gate=gate,
        binding_classifier=binder,
    )


def register_deep_phase_handler(
    *,
    spec: ICPSpec,
    gateway: LLMGateway,
    committee_sources: Sequence[CommitteeSource],
    register: Callable[[DeepPhaseHandler], None] = register_phase_handler,
    **kwargs: Any,
) -> DeepPhaseComposition:
    """Build the DEEP phase (:func:`build_deep_phase_handler`) and register its handler into the
    process phase-handler registry — the api-root binder that makes ``CampaignRun.advance()``
    dispatch ``CampaignPhase.DEEP``. ``register`` is injectable so a test can register into a fresh
    :class:`~clue_research.durable.PhaseHandlerRegistry` instead of the process default."""
    composition = build_deep_phase_handler(
        spec=spec, gateway=gateway, committee_sources=committee_sources, **kwargs
    )
    register(composition.handler)
    return composition

"""The M8A.6 DEEP-phase composition root — wiring, dispatch, and the high-tier resolver.

The composition-root assertions that do not need a DB (construction + threading + registration are
pure) live here as plain unit tests; the high-tier resolver's claim-store read is DB-gated. The two
governance enforcement axes (M9.1 AC-6 routing, M9.4 AC-4 born binding) are proven through the deep
callables in ``test_gate_routing_ac6`` / ``test_identity_binding_ac4``.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.deep import (
    DeepPhaseComposition,
    build_deep_phase_handler,
    build_high_tier_resolver,
    register_deep_phase_handler,
)
from clue_core import (
    ExtractionMethod,
    ICPCreatedFrom,
    ICPSpec,
    PhaseContext,
    PhaseStatus,
    ProjectPhase,
    ResearchMode,
    account_claim,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import insert_claim
from clue_research.discovery_scoring.tiering import (
    TIER_FIELD,
    DiscoverySelectionPolicy,
    cutoff_version,
)
from clue_research.durable import (
    AccountSpec,
    PhaseHandlerRegistry,
    ProjectRun,
    ProjectRunStatus,
)
from clue_research.icp.rubric import TierBand, TierCutoffs
from clue_research.identity import stamp_reuse
from clue_research.profiling import discover_committee, profile_account, profile_contact
from tests.durable.conftest import FakeProjectRunStore
from tests.profiling.conftest import (
    FakeCommitteeSource,
    FakeGateway,
    conn_session_factory,
    insert_test_account,
    rollback_conn,
    run_async,
    seed_packs,
)

_CLIENT = "acme"
_ICP = "seg1"
_COMMITTEE = [FakeCommitteeSource(source_key="apollo_people", tier=2)]


def _spec(*, icp_key: str = _ICP) -> ICPSpec:
    return ICPSpec(workspace_id=_CLIENT, icp_key=icp_key, created_from=ICPCreatedFrom.SYNTHESIS)


async def _empty_resolver(_ctx: PhaseContext) -> tuple[AccountSpec, ...]:
    """A high-tier resolver that selects no accounts — keeps the handler DB-free so the
    state-machine wiring (dispatch + transition) can be exercised without a Postgres read."""
    return ()


def _composition(**kwargs: object) -> DeepPhaseComposition:
    return build_deep_phase_handler(
        spec=_spec(),
        gateway=FakeGateway(),
        committee_sources=_COMMITTEE,
        **kwargs,  # type: ignore[arg-type]
    )


def test_handler_is_a_deep_phase_handler() -> None:
    """The built article is a ``PhaseHandler`` for ``ProjectPhase.DEEP`` (construction is DB-free —
    every concrete is built without touching a connection)."""
    comp = _composition()
    assert comp.handler.phase is ProjectPhase.DEEP
    assert hasattr(comp.handler, "run")


def test_gate_and_classifier_are_threaded_into_the_orchestrator() -> None:
    """The composition's concrete gate + binding classifier are the same objects the orchestrator
    holds — so the gate it threads into the committee/contact callables (and the classifier it hands
    ``profile_contact``) are the wired M9 concretes, never None (the required-collaborator
    enforcement behind AC-6 / AC-4)."""
    comp = _composition()
    assert comp.pre_spend_gate is not None
    assert comp.orchestrator._pre_spend_gate is comp.pre_spend_gate
    assert comp.orchestrator._binding_classifier is comp.binding_classifier
    # The three stage workers are the real M8 deep callables (composition, not re-implementation).
    assert comp.orchestrator._profile_account is profile_account
    assert comp.orchestrator._discover_committee is discover_committee
    assert comp.orchestrator._profile_contact is profile_contact


def test_provider_neutral_committee_preparer_is_threaded_into_orchestrator() -> None:
    preparer = object()
    comp = _composition(committee_preparer=preparer)
    assert comp.orchestrator._committee_preparer is preparer


def test_account_axis_registry_excludes_committee_and_contact() -> None:
    """The graph's worker registry holds only the account-axis aspects; committee/contact run as
    direct callables and must NOT be registered as graph aspects (spec §M8A.6)."""
    comp = _composition()
    aspects = comp.scheduler._graph._workers.aspects()  # type: ignore[attr-defined]
    assert "committee" not in aspects
    assert "contact.facet" not in aspects
    assert {"account", "account.resonance"} <= aspects


def test_lock_factory_is_threaded_into_the_baseline_account_scheduler() -> None:
    """Integrator checklist fix (PB-B1): the in-process ``AccountScheduler`` is now built WITH the
    Doc C §4 per-entity lock factory. It was silently omitted before — single-flight OFF wherever
    the baseline scheduler ran. Production passes ``account_entity_lock_factory(get_redis())``."""
    sentinel = object()  # AccountScheduler only stores the factory; no call at construction
    comp = _composition(lock_factory=sentinel)
    assert comp.scheduler._lock_factory is sentinel  # type: ignore[attr-defined]


def test_default_composition_carries_a_lazy_lock_factory() -> None:
    """Fix (PB-B1 review): omitting ``lock_factory`` now ships single-flight ON — the scheduler
    carries the lazy production factory (resolves ``get_redis()`` only at acquisition, so building
    needs no live redis), never ``None``. This closes the pre-B1 silent-off default."""
    comp = _composition()
    assert comp.scheduler._lock_factory is not None  # type: ignore[attr-defined]
    assert callable(comp.scheduler._lock_factory)  # type: ignore[attr-defined]


def test_explicit_none_lock_factory_opts_out_of_single_flight() -> None:
    """Passing ``lock_factory=None`` *explicitly* remains the written opt-out (single-flight off) —
    distinct from omitting it (the lazy default). Tests rely on this to stay Redis-free."""
    comp = _composition(lock_factory=None)
    assert comp.scheduler._lock_factory is None  # type: ignore[attr-defined]


class _FakeDeepScheduler:
    """A minimal ``DeepAccountScheduler`` stand-in (structural seam) for the fleet-swap test."""

    async def run_accounts(self, specs: object, **kwargs: object) -> list[object]:
        return []


def test_scheduler_param_swaps_in_an_alternative_deep_drain() -> None:
    """A supplied ``scheduler`` (the PB-B1 ``QueueBackedScheduler`` in prod) drives the deep phase
    in place of the in-process ``AccountScheduler`` — the fleet-mode swap, opt-in per deployment.
    The in-process path (no ``scheduler``) stays the default."""
    fake = _FakeDeepScheduler()
    comp = _composition(scheduler=fake)
    assert comp.scheduler is fake


def test_register_makes_the_phase_dispatchable() -> None:
    """Registering the handler makes the phase resolvable through a registry — the seam that lets
    ``ProjectRun.advance()`` dispatch ``DEEP`` instead of raising ``NoPhaseHandlerRegistered``."""
    registry = PhaseHandlerRegistry()
    comp = register_deep_phase_handler(
        spec=_spec(),
        gateway=FakeGateway(),
        committee_sources=_COMMITTEE,
        storage=None,  # storage is a REQUIRED kw on the register surface; None = the opt-out
        register=registry.register,
    )
    assert registry.get(ProjectPhase.DEEP) is comp.handler
    assert ProjectPhase.DEEP in registry.phases()


def test_empty_high_tier_set_is_a_clean_completed_no_op() -> None:
    """A high-tier set of zero (no approved accounts) is a clean COMPLETED no-op — the handler
    short-circuits before the scheduler/checkpointer, so it needs no DB."""

    comp = _composition(high_tier_resolver=_empty_resolver)
    ctx = PhaseContext(
        project_run_id=new_project_run_id(),
        project_id="prj-test",
        brand_id="brd-test",
        phase=ProjectPhase.DEEP,
        workspace_id=_CLIENT,
        icp_key=_ICP,
        icp_version=1,
    )
    result = run_async(comp.handler.run(ctx))
    assert result.status is PhaseStatus.COMPLETED
    assert result.accounts_processed == 0


# --- B2: the registered handler is snapshot-bound when a storage backend is supplied -------------


def test_no_storage_registers_the_bare_deep_handler() -> None:
    """Without a B2 backend the composition registers the plain ``DeepPhaseHandler`` (the pre-B2
    no-snapshotting path) — unchanged behavior, so the existing DEEP flow is untouched."""
    from clue_api.deep.handler import DeepPhaseHandler

    comp = _composition()
    assert isinstance(comp.handler, DeepPhaseHandler)


def test_storage_wraps_the_deep_handler_with_the_snapshot_binder() -> None:
    """Passing a ``storage`` backend registers the transparent snapshot-binding wrapper (still a
    ``PhaseHandler`` for ``DEEP``), so every deep run captures/flushes under one ambient per-run
    sink (audit finding 5)."""
    from clue_api.storage_wiring import SnapshotBindingPhaseHandler
    from tests.api.test_storage_wiring import FakeStorage

    comp = _composition(storage=FakeStorage())
    assert isinstance(comp.handler, SnapshotBindingPhaseHandler)
    assert comp.handler.phase is ProjectPhase.DEEP


# --- the high-tier resolver (D-B) reads tier claims by the committed cutoff_version --------------


async def _write_tier_claim(
    conn: AsyncConnection,
    account_id: UUID,
    *,
    tier: str,
    cversion: str,
    icp_key: str,
) -> None:
    claim = stamp_reuse(
        account_claim(
            entity_id=account_id,
            field_key=TIER_FIELD,
            value_json={
                "tier": tier,
                "cutoff_version": cversion,
                "icp_key": icp_key,
                "icp_version": 1,
            },
            source_tier=1,
            extraction_method=ExtractionMethod.HUMAN,
            confidence=1.0,
            run_id=new_run_id(),
            research_mode=ResearchMode.ACCOUNT_PROFILING,
        ),
        workspace_id=_CLIENT,
    )
    await insert_claim(conn, claim)


def test_high_tier_resolver_selects_named_band_at_committed_cutoff(
    require_profiling_db: None,
) -> None:
    """Only accounts whose live ``account.scoring.tier`` claim names a (non-fallback) band, at the
    committed ``cutoff_version``, for THIS ICP, resolve to an ``AccountSpec`` (D-B): a fallback-tier
    account, a wrong-version account, and a wrong-ICP account are all excluded."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            factory = conn_session_factory(conn)
            cutoffs = TierCutoffs(
                bands=(TierBand(tier="high", min_fit=0.5, min_intent=0.5),),
                fallback_tier="untiered",
            )
            committed = cutoff_version(cutoffs)

            high = await insert_test_account(conn, name="High Co", domain="high.example")
            fallback = await insert_test_account(conn, name="Low Co", domain="low.example")
            wrong_ver = await insert_test_account(conn, name="Stale Co", domain="stale.example")
            wrong_icp = await insert_test_account(conn, name="Other Co", domain="other.example")
            await _write_tier_claim(conn, high.id, tier="high", cversion=committed, icp_key=_ICP)
            await _write_tier_claim(
                conn, fallback.id, tier="untiered", cversion=committed, icp_key=_ICP
            )
            await _write_tier_claim(
                conn, wrong_ver.id, tier="high", cversion="v-other", icp_key=_ICP
            )
            await _write_tier_claim(
                conn, wrong_icp.id, tier="high", cversion=committed, icp_key="seg2"
            )

            resolver = build_high_tier_resolver(spec=_spec(), session_factory=factory)
            ctx = PhaseContext(
                project_run_id=new_project_run_id(),
                project_id="prj-test",
                brand_id="brd-test",
                phase=ProjectPhase.DEEP,
                workspace_id=_CLIENT,
                icp_key=_ICP,
                icp_version=1,
                params={"tier_cutoffs": cutoffs.model_dump(mode="json")},
            )
            # Production now fails closed until a confirmed directive is explicitly launched.
            specs = tuple(await resolver(ctx))

            assert specs == ()

    run_async(scenario())


def test_high_tier_resolver_selects_only_current_run_human_approved_criteria_account(
    require_profiling_db: None,
) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            factory = conn_session_factory(conn)
            strategy = {
                "scoring_mode": "disabled",
                "selection_mode": "discovery_criteria",
                "must_have_criteria": ["Independent practice"],
                "approved_tier": "high",
            }
            spec = ICPSpec(
                workspace_id=_CLIENT,
                icp_key=_ICP,
                created_from=ICPCreatedFrom.SYNTHESIS,
                discovery_strategy=strategy,
            )
            policy = DiscoverySelectionPolicy.from_slot(strategy)
            current_run = new_project_run_id()
            stale_run = new_project_run_id()
            approved = await insert_test_account(
                conn, name="Approved Co", domain="approved.example"
            )
            stale = await insert_test_account(
                conn, name="Stale Co", domain="stale-selection.example"
            )

            async def write(account_id: UUID, project_run_id) -> None:
                await insert_claim(
                    conn,
                    stamp_reuse(
                        account_claim(
                            entity_id=account_id,
                            field_key=TIER_FIELD,
                            value_json={
                                "tier": "high",
                                "decision_basis": "discovery_criteria",
                                "selection_policy_version": policy.policy_version,
                                "cutoff_version": "criteria-decision",
                                "project_run_id": str(project_run_id),
                                "icp_key": _ICP,
                                "icp_version": 1,
                            },
                            source_tier=1,
                            extraction_method=ExtractionMethod.HUMAN,
                            confidence=1.0,
                            run_id=new_run_id(),
                            research_mode=ResearchMode.ACCOUNT_PROFILING,
                        ),
                        workspace_id=_CLIENT,
                    ),
                )

            await write(approved.id, current_run)
            await write(stale.id, stale_run)
            resolver = build_high_tier_resolver(spec=spec, session_factory=factory)
            ctx = PhaseContext(
                project_run_id=current_run,
                project_id="prj-test",
                brand_id="brd-test",
                phase=ProjectPhase.DEEP,
                workspace_id=_CLIENT,
                icp_key=_ICP,
                icp_version=1,
            )
            specs = tuple(await resolver(ctx))
            assert specs == ()

    run_async(scenario())


# --- end to end: the registered handler is dispatched by the state machine ----------------------


def test_advance_dispatches_deep_and_transitions_to_verification() -> None:
    """The milestone's reason to exist: registering the deep handler makes ``ProjectRun.advance()``
    dispatch ``ProjectPhase.DEEP`` (no ``NoPhaseHandlerRegistered``) and, on a clean COMPLETED,
    advance the run ``DEEP → VERIFICATION`` — the state-machine integration through the real wired
    handler. (Per-account claim production through the orchestrator is covered on a real DB by the
    M8A.4 orchestrator suite + the AC-6/AC-4 deep-callable tests; here the high-tier set is empty so
    the wiring is exercised without Postgres.)"""

    async def scenario() -> None:
        store = FakeProjectRunStore()
        registry = PhaseHandlerRegistry()
        register_deep_phase_handler(
            spec=_spec(),
            gateway=FakeGateway(),
            committee_sources=_COMMITTEE,
            storage=None,  # required kw; None = the pre-B2 no-snapshot registration
            high_tier_resolver=_empty_resolver,
            register=registry.register,
        )
        machine = ProjectRun(store=store, registry=registry)
        run_id = await machine.start(
            project_id="prj-test", workspace_id=_CLIENT, icp_key=_ICP, icp_version=1
        )
        # Park the run at DEEP (the prior phases have their own handlers/milestones); advancing must
        # now dispatch our handler rather than raise NoPhaseHandlerRegistered(DEEP).
        await store.transition(run_id, phase=ProjectPhase.DEEP, status=ProjectRunStatus.ACTIVE)
        run = await machine.advance(run_id)
        assert run.phase is ProjectPhase.VERIFICATION
        assert run.status is ProjectRunStatus.ACTIVE

    run_async(scenario())

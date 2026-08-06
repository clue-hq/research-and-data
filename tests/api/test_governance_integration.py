"""The deferred M9-into-M8 governance wiring, proven at the api composition root (DB-gated).

* **M9.4×M8.4** — injecting ``verification.classify_binding`` behind M8.4's ``BindingClassifier``
  makes a born ``contact.facet.*`` ``identity_binding`` equal the authoritative M9 verdict (not
  the M8 default placeholder), for both verified-handle (STRONG) and same-name (WEAK) fixtures.
* **M9.1 AC6** — the composition root injects a ``PreSpendGate`` into the account-axis workers, so a
  tier≥2 spend records a ``gate_decision`` for its ``(run_id, entity, field)`` *before* the
  waterfall runs (spend ⇒ a prior gate decision exists).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from decimal import Decimal
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api import (
    build_pre_spend_gate,
    build_profiling_workers,
    production_binding_classifier,
)
from clue_core import (
    AccountStatus,
    AspectContext,
    Claim,
    Entity,
    EntityScope,
    ExtractionMethod,
    FieldDef,
    ICPCreatedFrom,
    IdentityBinding,
    Modality,
    PassKind,
    PreSpendVerdict,
    ResearchMode,
    SourceManifest,
    account_claim,
    new_entity_id,
    new_project_run_id,
    new_run_id,
)
from clue_research.claimstore import (
    PUBLIC_ONLY,
    WorkspaceScope,
    claims_for,
    get_field,
    register_field,
)
from clue_research.icp import (
    Pack,
    PackSourceSlot,
    SourceWeight,
    WeightedSource,
    create_icp_spec,
    register_pack_catalog,
)
from clue_research.identity import insert_account_entity
from clue_research.profiling import params_for_run
from clue_research.profiling.contact.fill import fill_contact_field
from clue_research.profiling.fields import FACET_STATED_INTERESTS
from clue_research.sources import RegistrySourceManifest, bind_resolver, register_source
from clue_research.verification import classify_binding
from tests._workspace import seed_workspace
from tests.profiling.conftest import (
    TEST_FACET_SOURCE,
    FakeCommitteeSource,
    FakeFacetResolver,
    FakeGateway,
    conn_session_factory,
    insert_test_account,
    insert_test_contact,
    register_facet_source,
    rollback_conn,
    run_async,
    seed_packs,
)

_RUN = UUID("a1a1a1a1-a1a1-a1a1-a1a1-a1a1a1a1a1a1")
_TENANT = "acme"
_FACET_SOURCE = TEST_FACET_SOURCE
_COMMITTEE = [FakeCommitteeSource(source_key="apollo_people", tier=2)]


# --- M9.4: the injected authoritative binding classifier stamps the born column -------------


def _run_facet_fill(
    *, resolver: FakeFacetResolver, manifest_tier: int = 4
) -> tuple[Claim, object, object]:
    """Drive M8.4 facet fill with the api-root binding classifier injected; return the written claim
    plus its contact + account. ``manifest_tier`` registers the facet source's test manifest at that
    tier (the shared engine enforces claim tier == manifest tier)."""

    async def scenario() -> tuple[Claim, object, object]:
        bind_resolver(_FACET_SOURCE, resolver)
        async with rollback_conn() as conn:
            await seed_packs(conn)
            await register_facet_source(conn, tier=manifest_tier)
            account = await insert_test_account(conn)
            contact = await insert_test_contact(conn, account)
            field = await get_field(conn, FACET_STATED_INTERESTS)
            assert field is not None
            result = await fill_contact_field(
                conn,
                contact,
                account,
                field,
                run_id=_RUN,
                workspace_id=_TENANT,
                tier="top",
                binding_classifier=production_binding_classifier(),
            )
            assert len(result.claim_refs) == 1, result
            written = (
                await claims_for(
                    conn,
                    contact.id,
                    FACET_STATED_INTERESTS,
                    scope=WorkspaceScope.for_workspace(_TENANT),
                )
            )[0]
            return written, contact, account

    return run_async(scenario())


def test_injected_classifier_born_binding_strong_on_verified_handle(
    require_profiling_db: None,
) -> None:
    """A facet claim whose evidence sits on the contact's verified handle is born STRONG — and the
    born value equals the authoritative ``classify_binding`` verdict (M9.4 AC4)."""
    written, contact, account = _run_facet_fill(
        resolver=FakeFacetResolver(
            tier=4,
            extractions=[
                {
                    "value_json": ["robotics"],
                    "evidence_span": "Jane CFO at Acme Robotics writes about robotics.",
                    "source_url": "https://linkedin.com/in/jane-cfo",  # the verified handle
                    "confidence": 0.95,
                }
            ],
        )
    )
    verdict = classify_binding(
        written,
        contact,  # type: ignore[arg-type]
        account_name=account.canonical_name,  # type: ignore[attr-defined]
        account_aliases=tuple(getattr(account, "aliases", ()) or ()),
    ).strength
    assert written.identity_binding is verdict
    assert written.identity_binding is IdentityBinding.STRONG


def test_injected_classifier_born_binding_weak_on_same_name(require_profiling_db: None) -> None:
    """A lower-tier, name-only, off-handle facet claim is born WEAK — equal to the authoritative
    verdict, and unpromotable (the same-name trap)."""
    # Founder-sanctioned re-fixture (claim_tagger consolidation): the tier-3 fake binds behind a
    # genuine tier-3 test manifest — the shared engine enforces claim tier == manifest tier.
    written, contact, account = _run_facet_fill(
        manifest_tier=3,
        resolver=FakeFacetResolver(
            tier=3,  # tier-3 scrape: written-but-weak (tier-4 same-name is rejected outright)
            extractions=[
                {
                    "value_json": ["gardening"],
                    "evidence_span": "Jane CFO enjoys gardening.",  # name-only, off-handle
                    "source_url": "https://random-blog.example/post",
                    "confidence": 0.9,
                }
            ],
        ),
    )
    verdict = classify_binding(
        written,
        contact,  # type: ignore[arg-type]
        account_name=account.canonical_name,  # type: ignore[attr-defined]
        account_aliases=tuple(getattr(account, "aliases", ()) or ()),
    ).strength
    assert written.identity_binding is verdict
    assert written.identity_binding is IdentityBinding.WEAK
    assert written.is_promotable is False


# --- M9.1 AC6: the injected gate is consulted before an account-axis spend -------------------

_GATE_FIELD = "account.gate_probe"
_GATE_SOURCE = "gate_probe_src"


def test_composition_injects_gate_into_all_axes() -> None:
    """The composition root threads its ``PreSpendGate`` into EVERY worker — account field-fill,
    committee people-enumeration (Option C) + role inference, and contact facet-fill all consult it
    (M9.1 across all three axes)."""
    gate = build_pre_spend_gate()
    workers = build_profiling_workers(
        gateway=FakeGateway(), committee_sources=_COMMITTEE, pre_spend_gate=gate
    )
    assert {w.aspect for w in workers} >= {
        "core",
        "account",
        "account.resonance",
        "committee",
        "contact.facet",
    }
    for worker in workers:
        assert getattr(worker, "_pre_spend_gate", None) is gate, worker.aspect


class _Fake:
    """A resolver double (mirrors the M4.1 waterfall test): re-stamps entity_id on each claim."""

    tier = 2

    def __init__(self, claims: list[Claim]) -> None:
        self._claims = claims

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        return [c.model_copy(update={"entity_id": entity.entity_id}) for c in self._claims]


def _probe_claim() -> Claim:
    return account_claim(
        entity_id=new_entity_id(),  # placeholder — _Fake re-stamps the resolved entity_id
        field_key=_GATE_FIELD,
        value_json={"summary": "x"},
        source_tier=2,
        extraction_method=ExtractionMethod.API,
        confidence=0.9,
        run_id=new_run_id(),  # placeholder — the engine stamps the run's id
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://acme.com/x",
        evidence_span="evidence",
        cost_cents=Decimal(0),
    )


async def _gate_rows(conn: AsyncConnection, run_id: object) -> list[tuple[str, str, int]]:
    rows = (
        await conn.execute(
            text("SELECT field_key, decision, source_tier FROM gate_decision WHERE run_id = :r"),
            {"r": str(run_id)},
        )
    ).all()
    return [(fk, d, t) for fk, d, t in rows]


def test_account_spend_records_prior_gate_decision(require_profiling_db: None) -> None:
    """End to end: with the composition root's gate injected and an ICP that authorizes a tier-2
    source, the account worker gates the field *before* the waterfall runs — a ``gate_decision`` row
    exists for ``(run_id, entity, field)`` and the spend then writes its claim (M9.1 AC6)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            # a tier-2 account gap field + an active tier-2 source + a resolver that would spend.
            await register_field(
                conn,
                FieldDef(
                    field_key=_GATE_FIELD,
                    value_type="object",
                    tier_plan=(_GATE_SOURCE,),
                    pass_kind=PassKind.DEEP,
                ),
            )
            await register_source(
                conn,
                RegistrySourceManifest(
                    manifest=SourceManifest(
                        source_key=_GATE_SOURCE,
                        modality=Modality.STRUCTURED,
                        entity_scope=EntityScope.ACCOUNT,
                        yields=("account",),
                        tier=2,
                        cost_cents=Decimal(0),
                    ),
                    active=True,
                ),
            )
            # an ICP whose pack profile authorizes the source (so the planner emits a RUN
            # source — the condition under which the account worker consults the gate).
            await register_pack_catalog(
                conn,
                Pack(
                    pack_key="probepack",
                    namespace="probepack",
                    title="Probe",
                    source_profile=(
                        PackSourceSlot(
                            sources=(
                                WeightedSource(
                                    source_key=_GATE_SOURCE, weight=SourceWeight.HIGH, rank=1
                                ),
                            )
                        ),
                    ),
                ),
            )
            spec = await create_icp_spec(
                conn,
                workspace_id=_TENANT,
                icp_key="seg1",
                created_from=ICPCreatedFrom.SYNTHESIS,
                enabled_packs=("probepack",),
            )
            bind_resolver(_GATE_SOURCE, _Fake([_probe_claim()]))
            await seed_workspace(conn, _TENANT)
            account_id = await insert_account_entity(
                conn,
                canonical_name="Acme Robotics",
                primary_domain="acme.com",
                status=AccountStatus.ACTIVE,
                workspace_id=_TENANT,
            )

            # The gate writes its audit into THIS rolled-back transaction (tests inject the conn).
            @asynccontextmanager
            async def gate_conn() -> AsyncIterator[AsyncConnection]:
                yield conn

            gate = build_pre_spend_gate(conn_factory=gate_conn)
            workers = build_profiling_workers(
                gateway=FakeGateway(),
                committee_sources=_COMMITTEE,
                session_factory=conn_session_factory(conn),
                pre_spend_gate=gate,
            )
            account_worker = next(w for w in workers if w.aspect == "account")

            run_id = new_run_id()
            ctx = AspectContext(
                entity_id=account_id,
                project_run_id=new_project_run_id(),
                run_id=run_id,
                tier="top",
                aspect="account",
                field_keys=(_GATE_FIELD,),
                params=params_for_run(
                    workspace_id=_TENANT, icp_key="seg1", icp_version=spec.version
                ),
            )
            await account_worker.research(ctx)

            rows = await _gate_rows(conn, run_id)
            probe = [(fk, d, t) for fk, d, t in rows if fk == _GATE_FIELD]
            assert probe, f"no gate_decision recorded before the tier-2 spend: {rows}"
            decision, tier = probe[0][1], probe[0][2]
            assert decision == PreSpendVerdict.PASS.value  # tier-2 source is in-plan → pass
            assert tier == 2  # the gate was keyed on the RUN source's tier (a real spend)
            written = await claims_for(conn, account_id, _GATE_FIELD, scope=PUBLIC_ONLY)
            assert written, "gate passed but the spend wrote no claim"

    run_async(scenario())


# --- M9.1 AC6 (tier-4): the M11 synthesis spend path is gated before it spends --------------

_T4_FIELD = "account.synth_probe"  # a tier-4 account-synthesis gap field
_T4_SOURCE = "synth_probe_src"  # a tier-4 synthesis source (the exa_deep/parallel_task shape)


class _FakeT4(_Fake):
    """A tier-4 synthesis resolver double (the exa_deep/parallel_task shape) that would spend."""

    tier = 4


def _t4_probe_claim() -> Claim:
    return account_claim(
        entity_id=new_entity_id(),  # placeholder — _FakeT4 re-stamps the resolved entity_id
        field_key=_T4_FIELD,
        value_json="engineers describe relentless on-call burnout",
        source_tier=4,
        extraction_method=ExtractionMethod.LLM_SYNTHESIS,
        confidence=0.9,
        run_id=new_run_id(),  # placeholder — the engine stamps the run's id
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url="https://news.example/acme",
        evidence_span="relentless on-call burnout",
        cost_cents=Decimal(0),
    )


def test_tier4_synthesis_spend_records_prior_gate_decision(require_profiling_db: None) -> None:
    """The headline M11 path: with the composition root's gate injected and an ICP authorizing a
    **tier-4** synthesis source, the account worker gates the field *before* the waterfall invokes
    the tier-4 resolver — a ``gate_decision`` keyed on ``(run_id, entity, field)`` with
    ``source_tier=4`` exists, and only then is the synthesis claim written (M9.1 AC6 tier-4)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            await register_field(
                conn,
                FieldDef(
                    field_key=_T4_FIELD,
                    value_type="str",
                    tier_plan=(_T4_SOURCE,),
                    pass_kind=PassKind.DEEP,
                ),
            )
            await register_source(
                conn,
                RegistrySourceManifest(
                    manifest=SourceManifest(
                        source_key=_T4_SOURCE,
                        modality=Modality.TEXT,
                        entity_scope=EntityScope.ACCOUNT,
                        yields=("account",),
                        tier=4,  # the least-trusted, most-expensive synthesis tier
                        cost_cents=Decimal(0),
                    ),
                    active=True,
                ),
            )
            await register_pack_catalog(
                conn,
                Pack(
                    pack_key="synthpack",
                    namespace="synthpack",
                    title="Synth",
                    source_profile=(
                        PackSourceSlot(
                            sources=(
                                WeightedSource(
                                    source_key=_T4_SOURCE, weight=SourceWeight.HIGH, rank=1
                                ),
                            )
                        ),
                    ),
                ),
            )
            spec = await create_icp_spec(
                conn,
                workspace_id=_TENANT,
                icp_key="seg1",
                created_from=ICPCreatedFrom.SYNTHESIS,
                enabled_packs=("synthpack",),
            )
            bind_resolver(_T4_SOURCE, _FakeT4([_t4_probe_claim()]))
            await seed_workspace(conn, _TENANT)
            account_id = await insert_account_entity(
                conn,
                canonical_name="Acme Robotics",
                primary_domain="acme.com",
                status=AccountStatus.ACTIVE,
                workspace_id=_TENANT,
            )

            @asynccontextmanager
            async def gate_conn() -> AsyncIterator[AsyncConnection]:
                yield conn

            gate = build_pre_spend_gate(conn_factory=gate_conn)
            workers = build_profiling_workers(
                gateway=FakeGateway(),
                committee_sources=_COMMITTEE,
                session_factory=conn_session_factory(conn),
                pre_spend_gate=gate,
            )
            account_worker = next(w for w in workers if w.aspect == "account")

            run_id = new_run_id()
            ctx = AspectContext(
                entity_id=account_id,
                project_run_id=new_project_run_id(),
                run_id=run_id,
                tier="top",
                aspect="account",
                field_keys=(_T4_FIELD,),
                params=params_for_run(
                    workspace_id=_TENANT, icp_key="seg1", icp_version=spec.version
                ),
            )
            await account_worker.research(ctx)

            rows = await _gate_rows(conn, run_id)
            probe = [(fk, d, t) for fk, d, t in rows if fk == _T4_FIELD]
            assert probe, f"no gate_decision recorded before the tier-4 synthesis spend: {rows}"
            decision, tier = probe[0][1], probe[0][2]
            assert decision == PreSpendVerdict.PASS.value
            assert tier == 4  # gated on the tier-4 synthesis source — the M11 spend path
            written = await claims_for(conn, account_id, _T4_FIELD, scope=PUBLIC_ONLY)
            assert written, "gate passed but the tier-4 synthesis spend wrote no claim"

    run_async(scenario())


# --- M11.3: the synthesis guard is injected into the account-axis workers -------------------


def test_composition_injects_synthesis_guard_into_account_axis() -> None:
    """The composition threads ``guard_synthesis_resolution`` (M11.3's account-only + Pass-B-only
    tripwire) into the account-axis workers, so a mis-wired synthesis resolve fails loud before the
    tier-4 spend — the M8-side ``guard_synthesis_resolution`` call site (DB-free)."""
    from clue_research.synthesis import guard_synthesis_resolution

    workers = build_profiling_workers(gateway=FakeGateway(), committee_sources=_COMMITTEE)
    account_axis = [w for w in workers if w.aspect in {"core", "account", "account.resonance"}]
    assert {w.aspect for w in account_axis} == {"core", "account", "account.resonance"}
    for worker in account_axis:
        assert getattr(worker, "_synthesis_guard", None) is guard_synthesis_resolution, (
            worker.aspect
        )

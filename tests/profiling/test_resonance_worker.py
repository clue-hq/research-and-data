"""M8.2 — the ``account.resonance.*`` collector end to end (DB-gated).

The resonance aspect of M8.1's converge loop: tier-4-absent resonance fields populate empty/flagged
(never fabricated); the sensitivity firewall drops a value smuggling a named individual's
special-category attribute while keeping clean account-scoped resonance; a newly-registered field is
picked up with no code change (open by registration); and ``collect_resonance`` is the
directly-callable seam.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from clue_research.claimstore import register_field
from clue_research.core import (
    AspectContext,
    Claim,
    Entity,
    EntityScope,
    ExtractionMethod,
    FieldDef,
    Modality,
    PassKind,
    ResearchMode,
    SourceManifest,
    WorkerStatus,
    account_claim,
    new_campaign_run_id,
    new_entity_id,
    new_run_id,
)
from clue_research.identity import insert_account_entity
from clue_research.profiling import (
    ProfilingFieldDisposition,
    ResonanceAspectWorker,
    collect_resonance,
    params_for_run,
)
from clue_research.sources import RegistrySourceManifest, bind_resolver, register_source

from .conftest import conn_session_factory, rollback_conn, run_async

pytestmark = pytest.mark.usefixtures("require_db")

_TENANT = "acme"
_DOMAIN = "acme-robotics.com"
_CUSTOM = "account.resonance.test"


class _Fake:
    tier = 3

    def __init__(self, claims: list[Claim]) -> None:
        self._claims = claims
        self.calls = 0

    def resolve(self, entity: Entity, field: FieldDef) -> list[Claim]:
        self.calls += 1
        return [c.model_copy(update={"entity_id": entity.entity_id}) for c in self._claims]


def _resonance_claim(
    *, span: str, summary: str = "morale is mixed", field_key: str = _CUSTOM
) -> Claim:
    return account_claim(
        entity_id=new_entity_id(),
        field_key=field_key,
        value_json={"label": "mixed", "summary": summary},
        source_tier=3,
        extraction_method=ExtractionMethod.SCRAPE,
        confidence=0.9,
        run_id=new_run_id(),
        research_mode=ResearchMode.ACCOUNT_PROFILING,
        source_url=f"https://glassdoor.example/{_DOMAIN}",
        evidence_span=span,
    )


async def _register_source(conn, source_key: str, *, tier: int) -> None:
    await register_source(
        conn,
        RegistrySourceManifest(
            manifest=SourceManifest(
                source_key=source_key,
                modality=Modality.TEXT,
                entity_scope=EntityScope.ACCOUNT,
                yields=("account.resonance",),
                tier=tier,
                cost_cents=Decimal(0),
            ),
            active=True,
        ),
    )


async def _register_custom_resonance_field(
    conn, *, field_key: str = _CUSTOM, source: str = "fakerev"
) -> None:
    await register_field(
        conn,
        FieldDef(
            field_key=field_key,
            value_type="object",
            tier_plan=(source,),
            pass_kind=PassKind.DEEP,
        ),
    )


async def _insert_account(conn):
    return await insert_account_entity(
        conn,
        canonical_name="Acme Robotics",
        primary_domain=_DOMAIN,
        hq_geo={"city": "Boston", "region": "Massachusetts"},
    )


def _ctx(entity_id, field_keys, *, tenant_id=_TENANT):
    return AspectContext(
        entity_id=entity_id,
        campaign_run_id=new_campaign_run_id(),
        run_id=new_run_id(),
        tier="top",
        aspect="account.resonance",
        field_keys=field_keys,
        params=params_for_run(client_id=None, icp_key=None, icp_version=None, tenant_id=tenant_id),
    )


# --- tier-4 absent → empty/flagged (M8.2 AC) --------------------------------


def test_seeded_resonance_tier4_absent_is_empty_flagged() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            acct = await _insert_account(conn)
            worker = ResonanceAspectWorker(session_factory=conn_session_factory(conn))
            # employee_sentiment plans into tier-4 synthesis (resolver-absent until M11).
            result = await worker.research(_ctx(acct, ("account.resonance.employee_sentiment",)))

            assert result.status is WorkerStatus.OK  # empty is a correct output, not a failure
            assert result.claim_refs == ()
            assert result.detail["fields_empty"] == 1
            assert (
                result.detail["dispositions"]["account.resonance.employee_sentiment"]
                == ProfilingFieldDisposition.SOURCES_EXHAUSTED.value
            )

    run_async(_run())


# --- the sensitivity firewall (M8.2 AC6) ------------------------------------


def test_firewall_drops_named_individual_special_category() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_custom_resonance_field(conn)
            await _register_source(conn, "fakerev", tier=3)
            # binds (domain is in the evidence) but smuggles a person's special-category attribute
            smuggled = _resonance_claim(
                span=f"{_DOMAIN} review: morale dipped after "
                "CEO Jane Doe disclosed a cancer diagnosis."
            )
            bind_resolver("fakerev", _Fake([smuggled]))
            acct = await _insert_account(conn)

            worker = ResonanceAspectWorker(session_factory=conn_session_factory(conn))
            result = await worker.research(_ctx(acct, (_CUSTOM,)))

            assert result.status is WorkerStatus.PARTIAL
            assert result.claim_refs == ()  # the smuggled value is not surfaced
            assert result.detail["filter_rejected"] == 1
            assert result.detail["target_lock_rejected"] == 0  # it DID bind; the firewall caught it

    run_async(_run())


def test_firewall_keeps_clean_account_resonance() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            await _register_custom_resonance_field(conn)
            await _register_source(conn, "fakerev", tier=3)
            clean = _resonance_claim(
                span=f"{_DOMAIN} glassdoor: employees cite low pay but value the team culture.",
                summary="employees frustrated about compensation",
            )
            bind_resolver("fakerev", _Fake([clean]))
            acct = await _insert_account(conn)

            worker = ResonanceAspectWorker(session_factory=conn_session_factory(conn))
            result = await worker.research(_ctx(acct, (_CUSTOM,)))

            assert result.status is WorkerStatus.OK
            assert len(result.claim_refs) == 1
            assert result.detail["filter_rejected"] == 0

    run_async(_run())


# --- open-by-registration (M8.2 AC1) ----------------------------------------


def test_new_resonance_field_is_picked_up_without_code_change() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            brand_new = "account.resonance.brand_new_signal"
            await _register_custom_resonance_field(conn, field_key=brand_new, source="fakerev")
            await _register_source(conn, "fakerev", tier=3)
            bind_resolver(
                "fakerev",
                _Fake([_resonance_claim(span=f"{_DOMAIN} review", field_key=brand_new)]),
            )
            acct = await _insert_account(conn)

            worker = ResonanceAspectWorker(session_factory=conn_session_factory(conn))
            result = await worker.research(_ctx(acct, (brand_new,)))

            # the freshly-registered field is filled by the same collector — no code change.
            assert brand_new in result.detail["dispositions"]
            assert len(result.claim_refs) == 1

    run_async(_run())


# --- the collect_resonance seam ---------------------------------------------


def test_collect_resonance_entrypoint_returns_worker_result() -> None:
    async def _run() -> None:
        async with rollback_conn() as conn:
            acct = await _insert_account(conn)
            worker = ResonanceAspectWorker(session_factory=conn_session_factory(conn))
            result = await collect_resonance(
                account_entity_id=acct,
                run_id=new_run_id(),
                tier="top",
                tenant_id=_TENANT,
                field_keys=("account.resonance.employee_sentiment",),
                worker=worker,
            )
            assert result.aspect == "account.resonance"
            assert isinstance(result.claim_refs, tuple)

    run_async(_run())

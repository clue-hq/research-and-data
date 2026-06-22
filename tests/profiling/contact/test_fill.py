"""M8.4 facet-aware fill (DB-gated).

Drives a fake facet resolver and asserts M8.4 *re-tags* every claim with the authoritative per-claim
identity_binding + use_class (overriding the resolver's placeholders) before writing — and that a
resolver-absent field yields a correct flagged-empty output.
"""

from __future__ import annotations

from uuid import UUID

from clue_research.claimstore import TenantScope, claims_for
from clue_research.core import IdentityBinding, ResearchMode, UseClass
from clue_research.profiling.contact.fill import fill_contact_field
from clue_research.profiling.fields import FACET_STATED_INTERESTS
from clue_research.sources import bind_resolver, clear_resolver_bindings

from ..conftest import (
    FakeFacetResolver,
    insert_test_account,
    insert_test_contact,
    rollback_conn,
    run_async,
    seed_packs,
)

_RUN = UUID("55555555-5555-5555-5555-555555555555")
_TENANT = "acme"
# The seeded facet fields' tier_plan source (resolver-absent in prod; we bind a fake here).
_FACET_SOURCE = "exa_deep"


async def _field_def(conn, field_key):  # type: ignore[no-untyped-def]
    from clue_research.claimstore import get_field

    field = await get_field(conn, field_key)
    assert field is not None
    return field


def test_no_resolver_yields_flagged_empty(require_profiling_db: None) -> None:
    async def scenario() -> None:
        clear_resolver_bindings()
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            contact = await insert_test_contact(conn, account)
            field = await _field_def(conn, FACET_STATED_INTERESTS)
            result = await fill_contact_field(
                conn, contact, account, field, run_id=_RUN, tenant_id=_TENANT, tier="top"
            )
            assert result.claim_refs == []
            assert result.stop_reason == "no_resolver"

    run_async(scenario())


def test_fill_retags_binding_and_use_class(require_profiling_db: None) -> None:
    """A religious interest on the contact's verified handle → written STRONG + SENSITIVE, over the
    resolver's placeholder (WEAK + professional)."""

    async def scenario() -> None:
        clear_resolver_bindings()
        resolver = FakeFacetResolver(
            tier=4,
            extractions=[
                {
                    "value_json": ["bible study", "robotics"],
                    "evidence_span": "Jane CFO is active in her church and Bible study.",
                    "source_url": "https://linkedin.com/in/jane-cfo",  # the verified handle
                    "confidence": 0.95,
                }
            ],
        )
        bind_resolver(_FACET_SOURCE, resolver)
        try:
            async with rollback_conn() as conn:
                await seed_packs(conn)
                account = await insert_test_account(conn)
                contact = await insert_test_contact(conn, account)
                field = await _field_def(conn, FACET_STATED_INTERESTS)
                result = await fill_contact_field(
                    conn, contact, account, field, run_id=_RUN, tenant_id=_TENANT, tier="top"
                )
                assert len(result.claim_refs) == 1
                written = (
                    await claims_for(
                        conn,
                        contact.id,
                        FACET_STATED_INTERESTS,
                        scope=TenantScope.for_tenant(_TENANT),
                    )
                )[0]
                # M8.4 re-tagged: verified handle → STRONG; religious marker → SENSITIVE.
                assert written.identity_binding is IdentityBinding.STRONG
                assert written.use_class is UseClass.SENSITIVE
                assert written.research_mode is ResearchMode.CONTACT_PROFILING
                assert written.source_key == _FACET_SOURCE
                assert written.run_id == _RUN
                assert written.tenant_id == _TENANT
        finally:
            clear_resolver_bindings()

    run_async(scenario())


def test_fill_tags_same_name_stranger_weak(require_profiling_db: None) -> None:
    async def scenario() -> None:
        clear_resolver_bindings()
        resolver = FakeFacetResolver(
            tier=4,
            extractions=[
                {
                    "value_json": ["gardening"],
                    "evidence_span": "Jane CFO enjoys gardening.",  # name only, off-handle blog
                    "source_url": "https://random-blog.example/post",
                    "confidence": 0.9,
                }
            ],
        )
        bind_resolver(_FACET_SOURCE, resolver)
        try:
            async with rollback_conn() as conn:
                await seed_packs(conn)
                account = await insert_test_account(conn)
                contact = await insert_test_contact(conn, account)
                field = await _field_def(conn, FACET_STATED_INTERESTS)
                await fill_contact_field(
                    conn, contact, account, field, run_id=_RUN, tenant_id=_TENANT, tier="top"
                )
                written = (
                    await claims_for(
                        conn,
                        contact.id,
                        FACET_STATED_INTERESTS,
                        scope=TenantScope.for_tenant(_TENANT),
                    )
                )[0]
                assert written.identity_binding is IdentityBinding.WEAK  # same-name trap → weak
                assert written.is_promotable is False  # weak contact claim never promotes
        finally:
            clear_resolver_bindings()

    run_async(scenario())


def test_fill_is_idempotent(require_profiling_db: None) -> None:
    async def scenario() -> None:
        clear_resolver_bindings()
        resolver = FakeFacetResolver(
            tier=4,
            extractions=[
                {
                    "value_json": ["robotics"],
                    "evidence_span": "Jane CFO at Acme Robotics writes about robotics.",
                    "source_url": "https://linkedin.com/in/jane-cfo",
                    "confidence": 0.95,
                }
            ],
        )
        bind_resolver(_FACET_SOURCE, resolver)
        try:
            async with rollback_conn() as conn:
                await seed_packs(conn)
                account = await insert_test_account(conn)
                contact = await insert_test_contact(conn, account)
                field = await _field_def(conn, FACET_STATED_INTERESTS)
                first = await fill_contact_field(
                    conn, contact, account, field, run_id=_RUN, tenant_id=_TENANT, tier="top"
                )
                second = await fill_contact_field(
                    conn, contact, account, field, run_id=_RUN, tenant_id=_TENANT, tier="top"
                )
                assert first.claim_refs == second.claim_refs  # reused, not double-written
                live = await claims_for(
                    conn, contact.id, FACET_STATED_INTERESTS, scope=TenantScope.for_tenant(_TENANT)
                )
                assert len(live) == 1
        finally:
            clear_resolver_bindings()

    run_async(scenario())

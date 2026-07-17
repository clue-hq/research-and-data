"""M8.4 target-lock per person (DB-gated) — Decision 13.

A tier-4 claim must bind to *this* resolved contact: a same-name-stranger fact (or a fact on a
different person's verified handle) is rejected before write; only evidence on the contact's own
verified handle (or co-occurring with strong identifiers) lands on the contact's entity_id.
"""

from __future__ import annotations

from uuid import UUID

from clue_core import IdentityBinding
from clue_research.claimstore import WorkspaceScope, claims_for
from clue_research.profiling.contact.fill import fill_contact_field
from clue_research.profiling.fields import FACET_STATED_INTERESTS
from clue_research.sources import bind_resolver

from ..conftest import (
    FakeFacetResolver,
    insert_test_account,
    insert_test_contact,
    rollback_conn,
    run_async,
    seed_packs,
)

_RUN = UUID("88888888-8888-8888-8888-888888888888")
_TENANT = "acme"
_FACET_SOURCE = "exa_deep"


async def _field(conn):  # type: ignore[no-untyped-def]
    from clue_research.claimstore import get_field

    field = await get_field(conn, FACET_STATED_INTERESTS)
    assert field is not None
    return field


def test_verified_handle_claim_is_written_strong(require_profiling_db: None) -> None:
    async def scenario() -> None:
        bind_resolver(
            _FACET_SOURCE,
            FakeFacetResolver(
                tier=4,
                extractions=[
                    {
                        "value_json": ["robotics"],
                        "evidence_span": "On her profile: robotics.",
                        "source_url": "https://linkedin.com/in/jane-cfo",  # the contact's handle
                        "confidence": 0.95,
                    }
                ],
            ),
        )
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            contact = await insert_test_contact(conn, account)
            result = await fill_contact_field(
                conn,
                contact,
                account,
                await _field(conn),
                run_id=_RUN,
                workspace_id=_TENANT,
                tier="top",
            )
            assert len(result.claim_refs) == 1
            written = (
                await claims_for(
                    conn,
                    contact.id,
                    FACET_STATED_INTERESTS,
                    scope=WorkspaceScope.for_workspace(_TENANT),
                )
            )[0]
            assert written.identity_binding is IdentityBinding.STRONG

    run_async(scenario())


def test_same_name_stranger_fact_not_written_to_contact(require_profiling_db: None) -> None:
    """Two similarly-named contacts under one account: a fact on contact A's verified handle is NOT
    written to contact B's entity_id (it does not bind to B → weak → tier-4 reject)."""

    async def scenario() -> None:
        # The resolver always reports evidence on contact A's handle.
        bind_resolver(
            _FACET_SOURCE,
            FakeFacetResolver(
                tier=4,
                extractions=[
                    {
                        "value_json": ["sailing"],
                        "evidence_span": "Jane Smith enjoys sailing.",  # name-only for B
                        "source_url": "https://linkedin.com/in/jane-a",  # A's handle, not B's
                        "confidence": 0.95,
                    }
                ],
            ),
        )
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)
            contact_a = await insert_test_contact(
                conn, account, full_name="Jane Smith", linkedin_url="https://linkedin.com/in/jane-a"
            )
            contact_b = await insert_test_contact(
                conn, account, full_name="Jane Smith", linkedin_url="https://linkedin.com/in/jane-b"
            )
            field = await _field(conn)
            scope = WorkspaceScope.for_workspace(_TENANT)

            # Filling B: the evidence is on A's handle → does not bind to B → tier-4 reject.
            res_b = await fill_contact_field(
                conn, contact_b, account, field, run_id=_RUN, workspace_id=_TENANT, tier="top"
            )
            assert res_b.claim_refs == []
            assert await claims_for(conn, contact_b.id, FACET_STATED_INTERESTS, scope=scope) == []

            # Filling A: the same evidence IS on A's handle → strong → written to A only.
            res_a = await fill_contact_field(
                conn, contact_a, account, field, run_id=_RUN, workspace_id=_TENANT, tier="top"
            )
            assert len(res_a.claim_refs) == 1
            a_claims = await claims_for(conn, contact_a.id, FACET_STATED_INTERESTS, scope=scope)
            assert len(a_claims) == 1
            assert a_claims[0].identity_binding is IdentityBinding.STRONG

    run_async(scenario())

"""M8A.6 AC-6 — the deep committee/contact spend paths route through the pre-spend gate.

The deferred M9.1 routing (CLAUDE.md ENG-130), closed at the deep composition root: the gate the
composition builds (:func:`~clue_api.composition.build_pre_spend_gate`) is the one the
orchestrator threads into the committee + contact callables, so neither people-enumeration nor a
facet fill can spend without a recorded ``gate_decision`` first. These drive the **exact callables**
``AccountDeepOrchestrator`` invokes (``discover_committee`` / ``profile_contact``) with that gate
and assert the audit row exists — the test fails if a spend path skips the gate.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api import build_pre_spend_gate
from clue_research.profiling import discover_committee, profile_contact
from clue_research.profiling.fields import FACET_STATED_INTERESTS
from clue_research.sources import (
    bind_resolver,
    clear_resolver_bindings,
)
from tests.profiling.conftest import (
    TEST_FACET_SOURCE,
    FakeCommitteeSource,
    FakeFacetResolver,
    FakeGateway,
    insert_test_account,
    insert_test_contact,
    register_facet_source,
    rollback_conn,
    run_async,
    seed_packs,
)

_RUN = UUID("c6c6c6c6-c6c6-c6c6-c6c6-c6c6c6c6c6c6")
_TENANT = "acme"
_FACET_SOURCE = TEST_FACET_SOURCE


async def _gate_rows(conn: AsyncConnection) -> list[tuple[str, str | None, str]]:
    rows = (
        await conn.execute(
            text("SELECT request_kind, field_key, decision FROM gate_decision WHERE run_id = :r"),
            {"r": str(_RUN)},
        )
    ).all()
    return [(k, f, d) for k, f, d in rows]


def test_deep_committee_enumeration_records_a_gate_decision(require_profiling_db: None) -> None:
    """The committee people-enumeration the orchestrator runs (``discover_committee`` with the
    composition's gate) records an ``enumeration``-kind ``gate_decision`` for the account before it
    queries a people source — the deep enumeration spend cannot skip the gate (AC-6)."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            await seed_packs(conn)
            account = await insert_test_account(conn)

            @asynccontextmanager
            async def gate_conn() -> AsyncIterator[AsyncConnection]:
                yield conn  # the gate writes its audit into THIS rolled-back transaction

            gate = build_pre_spend_gate(conn_factory=gate_conn)
            await discover_committee(
                conn,
                account_entity_id=account.id,
                run_id=_RUN,
                workspace_id=_TENANT,
                sources=[FakeCommitteeSource(source_key="apollo_people", tier=2, candidates=[])],
                gateway=FakeGateway(),
                role_model="stub/role",
                pre_spend_gate=gate,
            )

            rows = await _gate_rows(conn)
            enumeration = [r for r in rows if r[0] == "enumeration"]
            assert enumeration, f"committee enumeration skipped the gate: {rows}"
            # an enumeration request has no single field — field_key is NULL (Option C honesty)
            assert enumeration[0][1] is None

    run_async(scenario())


def test_deep_contact_facet_fill_records_a_gate_decision(require_profiling_db: None) -> None:
    """The contact facet fill the orchestrator runs (``profile_contact`` with the composition's
    gate) records a ``field``-kind ``gate_decision`` keyed on the facet field before the resolver
    spends — the deep contact spend cannot skip the gate (AC-6)."""

    async def scenario() -> None:
        clear_resolver_bindings()
        bind_resolver(
            _FACET_SOURCE,
            FakeFacetResolver(
                tier=4,
                extractions=[
                    {
                        "value_json": ["robotics"],
                        "evidence_span": "Jane CFO at Acme Robotics: robotics.",
                        "source_url": "https://linkedin.com/in/jane-cfo",
                        "confidence": 0.95,
                    }
                ],
            ),
        )
        try:
            async with rollback_conn() as conn:
                await seed_packs(conn)
                account = await insert_test_account(conn)
                contact = await insert_test_contact(conn, account)
                await register_facet_source(conn)

                @asynccontextmanager
                async def gate_conn() -> AsyncIterator[AsyncConnection]:
                    yield conn

                gate = build_pre_spend_gate(conn_factory=gate_conn)
                await profile_contact(
                    conn,
                    contact_entity_id=contact.id,
                    account_entity_id=account.id,
                    run_id=_RUN,
                    workspace_id=_TENANT,
                    tier="top",
                    field_keys=(FACET_STATED_INTERESTS,),
                    pre_spend_gate=gate,
                )

                rows = await _gate_rows(conn)
                facet = [r for r in rows if r[0] == "field" and r[1] == FACET_STATED_INTERESTS]
                assert facet, f"contact facet fill skipped the gate: {rows}"
        finally:
            clear_resolver_bindings()

    run_async(scenario())

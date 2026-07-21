"""Account-scope battery (Doc M §4; founder ruling 2026-07-22 — accounts are workspace-local).

Exercises the live ``account`` scope end-to-end: round-trip, its place last in stability order,
the workspace-locality *structural* guarantees (cross-workspace / unstamped-legacy accounts die at
the schema), per-instance reconciliation, the account store cap, the three-way cross-branch pairs,
and cycle aging. Two-workspace isolation proves Company X in A and B is two independent stores.
"""

from __future__ import annotations

import json

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AssemblyRequest,
    MemoryAccepted,
    MemoryPreconditionFailed,
    MemoryScopeType,
    MemoryStatus,
    MemoryType,
    ScopeStack,
)
from clue_memory import (
    Assembly,
    WriteSeam,
    _store,  # test setup/inspection only — see conftest docstring
    record_kickoff,
)

from .conftest import (
    add_judge,
    make_caps,
    make_settings,
    rollback_conn,
    run_async,
    seed_account,
    seed_spine,
    submission,
)

pytestmark = pytest.mark.usefixtures("require_memory_db")

_TYPES = (MemoryType.PREFERENCE, MemoryType.BEHAVIORAL_LEARNING)


def _seam(conn: AsyncConnection, *, caps: object = None) -> WriteSeam:
    return WriteSeam(conn, add_judge(), settings=make_settings(), caps=caps or make_caps())  # type: ignore[arg-type]


async def _write_account(
    conn: AsyncConnection, workspace_id: str, account_id: object, *, body: str, caps: object = None
) -> str:
    outcome = await _seam(conn, caps=caps).submit(
        submission(
            workspace_id, scope_type=MemoryScopeType.ACCOUNT, scope_id=str(account_id), body=body
        )
    )
    assert isinstance(outcome, MemoryAccepted)
    return outcome.memory_id


def _request(spine: object) -> AssemblyRequest:
    return AssemblyRequest(
        scope_stack=ScopeStack(
            workspace_id=spine.workspace_id,  # type: ignore[attr-defined]
            brand_id=spine.brand_id,  # type: ignore[attr-defined]
            product_id=spine.product_id,  # type: ignore[attr-defined]
            project_id=spine.project_id,  # type: ignore[attr-defined]
            account_entity_id=spine.account_entity_id,  # type: ignore[attr-defined]
        ),
        recipe="draft_outreach",
        requested_types=_TYPES,
    )


# --- round-trip --------------------------------------------------------------


def test_account_scoped_memory_round_trips() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            memory_id = await _write_account(
                conn, spine.workspace_id, spine.account_entity_id, body="This account likes ROI."
            )
            row = await _store.get_memory(conn, memory_id)
            assert row is not None
            assert row.scope_type is MemoryScopeType.ACCOUNT
            assert row.scope_id == str(spine.account_entity_id)
            assert row.status is MemoryStatus.ACTIVE

    run_async(scenario())


# --- assembly: account is present and last in stability order ----------------


def test_assembly_includes_account_scope_last_in_stability_order() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            seam = _seam(conn)
            await seam.submit(submission(spine.workspace_id, scope_type=MemoryScopeType.WORKSPACE))
            await seam.submit(submission(spine.workspace_id, scope_id=spine.brand_id))
            await seam.submit(
                submission(
                    spine.workspace_id,
                    scope_type=MemoryScopeType.PRODUCT,
                    scope_id=spine.product_id,
                )
            )
            await seam.submit(
                submission(
                    spine.workspace_id,
                    scope_type=MemoryScopeType.PROJECT,
                    scope_id=spine.project_id,
                )
            )
            await _write_account(
                conn, spine.workspace_id, spine.account_entity_id, body="Account-scoped guidance."
            )
            bundle = await Assembly(conn, settings=make_settings(), caps=make_caps()).assemble(
                _request(spine)
            )
            assert bundle is not None
            order = [e.label.scope_type.value for e in bundle.entries]
            assert order == ["workspace", "brand", "product", "project", "account"]

    run_async(scenario())


# --- workspace-locality is structural ----------------------------------------


def test_cross_workspace_account_reference_is_unrepresentable() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine_a = await seed_spine(conn, tag="A")
            spine_b = await seed_spine(conn, tag="B")
            # Workspace A names workspace B's account — dies at the composite FK.
            with pytest.raises(IntegrityError):
                await _write_account(
                    conn, spine_a.workspace_id, spine_b.account_entity_id, body="Leak attempt."
                )

    run_async(scenario())


def test_unstamped_legacy_account_cannot_own_memory() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            # A legacy/global account row (workspace_id NULL) — no global memory (fail-closed).
            legacy = await seed_account(conn, workspace_id=None)
            with pytest.raises(IntegrityError):
                await _write_account(
                    conn, spine.workspace_id, legacy, body="Global memory attempt."
                )

    run_async(scenario())


def test_malformed_account_scope_id_is_precondition_failed() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            with pytest.raises(MemoryPreconditionFailed):
                await _seam(conn).submit(
                    submission(
                        spine.workspace_id,
                        scope_type=MemoryScopeType.ACCOUNT,
                        scope_id="not-a-uuid",
                    )
                )

    run_async(scenario())


# --- two-workspace isolation -------------------------------------------------


def test_same_company_in_two_workspaces_assembles_in_isolation() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            # Company X seeded independently in each workspace (two rows, no shared identity).
            spine_a = await seed_spine(conn, tag="A")
            spine_b = await seed_spine(conn, tag="B")
            await _write_account(
                conn, spine_a.workspace_id, spine_a.account_entity_id, body="Account note A."
            )
            await _write_account(
                conn, spine_b.workspace_id, spine_b.account_entity_id, body="Account note B."
            )
            engine = Assembly(conn, settings=make_settings(), caps=make_caps())
            bundle_a = await engine.assemble(_request(spine_a))
            bundle_b = await engine.assemble(_request(spine_b))
            assert bundle_a is not None and bundle_b is not None
            assert [e.body for e in bundle_a.entries] == ["Account note A."]
            assert [e.body for e in bundle_b.entries] == ["Account note B."]

    run_async(scenario())


# --- reconciliation is per account instance ----------------------------------


def test_reconciliation_is_scoped_per_account_instance() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            account_2 = await seed_account(
                conn, workspace_id=spine.workspace_id, brand_id=spine.brand_id
            )
            body = "Never use fear-based hooks."
            first = await _write_account(
                conn, spine.workspace_id, spine.account_entity_id, body=body
            )
            # Same body, different account instance → a genuine ADD, never a cross-instance NOOP.
            second = await _write_account(conn, spine.workspace_id, account_2, body=body)
            assert first != second
            rows = await _store.list_records(
                conn, workspace_id=spine.workspace_id, statuses=(MemoryStatus.ACTIVE,)
            )
            assert {r.memory_id for r in rows} == {first, second}
            # Restating account-1's own record NOOPs onto it (its scope instance).
            outcome = await _seam(conn).submit(
                submission(
                    spine.workspace_id,
                    scope_type=MemoryScopeType.ACCOUNT,
                    scope_id=str(spine.account_entity_id),
                    body="never use FEAR-BASED hooks!!",
                )
            )
            assert isinstance(outcome, MemoryAccepted)
            assert outcome.verdict.value == "noop"
            assert outcome.memory_id == first

    run_async(scenario())


# --- store cap ---------------------------------------------------------------


def test_account_store_cap_evicts_to_dormant() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            caps = make_caps(store_caps={"account": 1})
            first = await _write_account(
                conn,
                spine.workspace_id,
                spine.account_entity_id,
                body="Account guidance one.",
                caps=caps,
            )
            await _store.record_confirmation(conn, first, trust_grade=4)  # first outranks
            second = await _write_account(
                conn,
                spine.workspace_id,
                spine.account_entity_id,
                body="Account guidance two.",
                caps=caps,
            )
            row = await _store.get_memory(conn, second)
            assert row is not None and row.status is MemoryStatus.DORMANT  # crowded out
            evicted = [
                e for e in await _store.list_events(conn, second) if e["event_type"] == "evicted"
            ]
            assert len(evicted) == 1
            assert "store cap 1" in (evicted[0]["cause"] or "")

    run_async(scenario())


# --- three-way cross-branch pairs --------------------------------------------


def test_cross_branch_pairs_include_account() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            seam = _seam(conn)
            product_out = await seam.submit(
                submission(
                    spine.workspace_id,
                    scope_type=MemoryScopeType.PRODUCT,
                    scope_id=spine.product_id,
                    body="Product-branch guidance.",
                )
            )
            project_out = await seam.submit(
                submission(
                    spine.workspace_id,
                    scope_type=MemoryScopeType.PROJECT,
                    scope_id=spine.project_id,
                    body="Project-branch guidance.",
                )
            )
            assert isinstance(product_out, MemoryAccepted)
            assert isinstance(project_out, MemoryAccepted)
            account_mem = await _write_account(
                conn, spine.workspace_id, spine.account_entity_id, body="Account-branch guidance."
            )
            bundle = await Assembly(conn, settings=make_settings(), caps=make_caps()).assemble(
                _request(spine)
            )
            assert bundle is not None
            journal = await _store.get_bundle_journal(conn, bundle.journal_id or "")
            assert journal is not None
            pairs = journal["cross_branch_pairs"]
            pairs = json.loads(pairs) if isinstance(pairs, str) else pairs
            # All three unordered sibling-branch pairings, "a" from the earlier stability branch.
            assert {
                "a": product_out.memory_id,
                "b": project_out.memory_id,
                "type": "preference",
            } in pairs
            assert {"a": product_out.memory_id, "b": account_mem, "type": "preference"} in pairs
            assert {"a": project_out.memory_id, "b": account_mem, "type": "preference"} in pairs

    run_async(scenario())


# --- cycle aging -------------------------------------------------------------


def test_kickoff_ages_account_scope() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            memory_id = await _write_account(
                conn, spine.workspace_id, spine.account_entity_id, body="Account guidance."
            )
            stack = ScopeStack(
                workspace_id=spine.workspace_id,
                brand_id=spine.brand_id,
                account_entity_id=spine.account_entity_id,
            )
            aged = await record_kickoff(
                conn, scope_stack=stack, settings=make_settings(), actor="test"
            )
            assert memory_id in aged
            row = await _store.get_memory(conn, memory_id)
            assert row is not None and row.cycles_since_confirmed == 1

    run_async(scenario())

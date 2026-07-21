"""Read-seam battery (Doc M §19 "read path"): determinism, the journal contract
(ids-never-bodies), no-step short-circuits, budgets, stability order, cross-branch labeling."""

from __future__ import annotations

import json

import pytest
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AssemblyRequest,
    MemoryAccepted,
    MemoryScopeType,
    MemoryType,
    ScopeStack,
)
from clue_memory import (
    Assembly,
    WriteSeam,
    _store,  # test setup/inspection only
)

from .conftest import (
    add_judge,
    make_caps,
    make_settings,
    rollback_conn,
    run_async,
    seed_spine,
    submission,
)

pytestmark = pytest.mark.usefixtures("require_memory_db")

_TYPES = (MemoryType.PREFERENCE, MemoryType.BEHAVIORAL_LEARNING)


def _assembly(conn: AsyncConnection, **caps_overrides: object) -> Assembly:
    return Assembly(conn, settings=make_settings(), caps=make_caps(**caps_overrides))


def _request(spine: object, *, recipe: str = "draft_outreach") -> AssemblyRequest:
    return AssemblyRequest(
        scope_stack=ScopeStack(
            workspace_id=spine.workspace_id,  # type: ignore[attr-defined]
            brand_id=spine.brand_id,  # type: ignore[attr-defined]
            product_id=spine.product_id,  # type: ignore[attr-defined]
            project_id=spine.project_id,  # type: ignore[attr-defined]
        ),
        recipe=recipe,
        requested_types=_TYPES,
    )


async def _write(conn: AsyncConnection, spine: object, **kwargs: object) -> str:
    outcome = await WriteSeam(conn, add_judge(), settings=make_settings(), caps=make_caps()).submit(
        submission(spine.workspace_id, **kwargs)  # type: ignore[attr-defined, arg-type]
    )
    assert isinstance(outcome, MemoryAccepted)
    return outcome.memory_id


def test_assembly_is_byte_identical_and_journal_witnesses_it() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            await _write(conn, spine, scope_id=spine.brand_id, body="Brand guidance one.")
            await _write(
                conn,
                spine,
                scope_type=MemoryScopeType.PROJECT,
                scope_id=spine.project_id,
                body="Project guidance one.",
            )
            engine = _assembly(conn)
            first = await engine.assemble(_request(spine))
            second = await engine.assemble(_request(spine))
            assert first is not None and second is not None
            assert first.canonical_bytes() == second.canonical_bytes()
            assert first.bundle_hash() == second.bundle_hash()
            assert first.journal_id != second.journal_id  # two assemblies, two journal rows
            journal = await _store.get_bundle_journal(conn, first.journal_id or "")
            assert journal is not None
            assert journal["bundle_hash"] == first.bundle_hash()

    run_async(scenario())


def test_journal_carries_ids_and_labels_never_bodies() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            body = "A distinctive body sentence that must never appear in the journal."
            memory_id = await _write(conn, spine, scope_id=spine.brand_id, body=body)
            bundle = await _assembly(conn).assemble(_request(spine))
            assert bundle is not None
            journal = await _store.get_bundle_journal(conn, bundle.journal_id or "")
            assert journal is not None
            included = (
                json.loads(journal["included"])
                if isinstance(journal["included"], str)
                else journal["included"]
            )
            assert [m["memory_id"] for m in included] == [memory_id]
            assert {"scope_type", "trust_grade", "confirmation_count"} <= set(included[0])
            # Ids-never-bodies — structurally AND in the serialized metadata.
            assert body not in json.dumps(
                {k: v for k, v in journal.items() if k != "created_at"}, default=str
            )

    run_async(scenario())


def test_recipe_declaring_no_types_gets_no_memory_step_and_no_journal() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            await _write(conn, spine, scope_id=spine.brand_id)
            request = _request(spine).model_copy(update={"requested_types": ()})
            assert await _assembly(conn).assemble(request) is None
            count = await conn.execute(
                __import__("sqlalchemy").text("SELECT count(*) FROM memory_bundle_journal")
            )
            assert count.scalar_one() == 0

    run_async(scenario())


def test_bundle_budget_excludes_with_losing_comparison_but_record_stays_active() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            first = await _write(conn, spine, scope_id=spine.brand_id, body="Guidance alpha.")
            second = await _write(conn, spine, scope_id=spine.brand_id, body="Guidance beta.")
            # Confirm the first so ranking is decided by confirmations, not id order.
            await _store.record_confirmation(conn, first, trust_grade=4)
            bundle = await _assembly(conn, bundle_budgets={"brand": 1}).assemble(_request(spine))
            assert bundle is not None
            assert [e.memory_id for e in bundle.entries] == [first]
            journal = await _store.get_bundle_journal(conn, bundle.journal_id or "")
            assert journal is not None
            excluded = journal["excluded"]
            excluded = json.loads(excluded) if isinstance(excluded, str) else excluded
            assert [m["memory_id"] for m in excluded] == [second]
            assert "lost to" in excluded[0]["losing_comparison"]
            # Budget exclusion is NOT dormancy.
            row = await _store.get_memory(conn, second)
            assert row is not None and row.status.value == "active"

    run_async(scenario())


def test_stability_order_workspace_brand_product_project() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            await _write(
                conn,
                spine,
                scope_type=MemoryScopeType.PROJECT,
                scope_id=spine.project_id,
                body="Project-level guidance.",
            )
            await _write(
                conn,
                spine,
                scope_type=MemoryScopeType.PRODUCT,
                scope_id=spine.product_id,
                body="Product-level guidance.",
            )
            await _write(conn, spine, scope_id=spine.brand_id, body="Brand-level guidance.")
            await _write(
                conn,
                spine,
                scope_type=MemoryScopeType.WORKSPACE,
                body="Workspace-level guidance.",
            )
            bundle = await _assembly(conn).assemble(_request(spine))
            assert bundle is not None
            order = [e.label.scope_type.value for e in bundle.entries]
            assert order == ["workspace", "brand", "product", "project"]

    run_async(scenario())


def test_cross_branch_tension_both_included_labeled_and_journaled() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            product_mem = await _write(
                conn,
                spine,
                scope_type=MemoryScopeType.PRODUCT,
                scope_id=spine.product_id,
                body="Keep the tone formal for this product line.",
            )
            project_mem = await _write(
                conn,
                spine,
                scope_type=MemoryScopeType.PROJECT,
                scope_id=spine.project_id,
                body="This committee responds to casual outreach.",
            )
            bundle = await _assembly(conn).assemble(_request(spine))
            assert bundle is not None
            ids = {e.memory_id for e in bundle.entries}
            assert {product_mem, project_mem} <= ids  # both included, never arbitrated
            journal = await _store.get_bundle_journal(conn, bundle.journal_id or "")
            assert journal is not None
            pairs = journal["cross_branch_pairs"]
            pairs = json.loads(pairs) if isinstance(pairs, str) else pairs
            assert {"a": product_mem, "b": project_mem, "type": "preference"} in pairs

    run_async(scenario())


def test_cross_tenant_bundles_never_mix() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine_a = await seed_spine(conn, tag="A")
            spine_b = await seed_spine(conn, tag="B")
            await _write(conn, spine_a, scope_id=spine_a.brand_id, body="Tenant A only.")
            await _write(conn, spine_b, scope_id=spine_b.brand_id, body="Tenant B only.")
            bundle_a = await _assembly(conn).assemble(_request(spine_a))
            bundle_b = await _assembly(conn).assemble(_request(spine_b))
            assert bundle_a is not None and bundle_b is not None
            assert [e.body for e in bundle_a.entries] == ["Tenant A only."]
            assert [e.body for e in bundle_b.entries] == ["Tenant B only."]

    run_async(scenario())

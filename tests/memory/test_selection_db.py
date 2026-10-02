"""Pinned read selections preserve meaning and identity without persisting memory bodies."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import MemoryBundle, MemoryScopeType, MemoryStatus, MemoryType
from clue_memory import Assembly, _store, erase_subject, set_memory_enabled

from .conftest import make_caps, make_settings, rollback_conn, run_async, seed_contact, seed_spine
from .test_assembly_db import _assembly, _request, _write

pytestmark = pytest.mark.usefixtures("require_memory_db")


def test_pin_is_body_free_and_resolves_original_selection_after_new_eligible_rows() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            body = "Use charcoal and warm cream for this campaign."
            trigger = "Only for the late summer product launch."
            memory_id = await _write(
                conn, spine, scope_id=spine.brand_id, body=body, trigger=trigger
            )
            engine = _assembly(conn)
            request = _request(spine)
            assert callable(getattr(engine, "select", None)), "read seam needs pinned selection"
            pin = await engine.select(request)
            wire = pin.model_dump_json()
            assert body not in wire and trigger not in wire
            assert pin.selected_ids == (memory_id,)
            assert pin.version == 1
            journal = await _store.get_bundle_journal(conn, str(pin.journal_id))
            assert journal is not None
            journal_wire = json.dumps(journal, default=str)
            assert body not in journal_wire and trigger not in journal_wire
            assert pin.bundle_hash == journal["bundle_hash"]

            await _write(conn, spine, scope_id=spine.brand_id, body="A newer eligible preference.")
            # Simulate a new process/caps policy and a serialized durable selection.
            retry = _assembly(conn, bundle_budgets={"brand": 1})
            resolved = await retry.resolve(request, type(pin).model_validate_json(wire))
            assert isinstance(resolved, MemoryBundle)
            assert [(e.memory_id, e.body, e.label.trigger) for e in resolved.entries] == [
                (memory_id, body, trigger)
            ]
            assert resolved.journal_id == str(pin.journal_id)
            assert resolved.bundle_hash() == pin.bundle_hash
            assert (
                await conn.execute(text("SELECT count(*) FROM memory_bundle_journal"))
            ).scalar_one() == 1

    run_async(scenario())


def test_empty_selection_stays_empty_and_no_step_does_not_write_a_journal() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            request = _request(spine)
            engine = _assembly(conn)
            no_types = await engine.select(request.model_copy(update={"requested_types": ()}))
            assert no_types.status == "unavailable" and no_types.reason == "no_requested_types"
            pin = await engine.select(request)
            assert pin.selected_ids == ()
            await _write(conn, spine, scope_id=spine.brand_id)
            resolved = await engine.resolve(request, pin)
            assert isinstance(resolved, MemoryBundle) and resolved.entries == ()
            await set_memory_enabled(conn, spine.workspace_id, False, actor="test")
            disabled = await engine.select(request)
            assert disabled.status == "unavailable" and disabled.reason == "memory_disabled"
            disabled_retry = await engine.resolve(request, pin)
            assert disabled_retry.status == "unavailable"
            assert disabled_retry.reason == "memory_disabled"
            assert (
                await conn.execute(text("SELECT count(*) FROM memory_bundle_journal"))
            ).scalar_one() == 1

    run_async(scenario())


@pytest.mark.parametrize(
    "field", ["workspace_id", "brand_id", "product_id", "project_id", "account_entity_id"]
)
def test_request_scope_change_cannot_resolve_a_pin(field: str) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            other = await seed_spine(conn, tag="other")
            await _write(conn, spine, scope_id=spine.brand_id)
            request = _request(spine)
            engine = _assembly(conn)
            pin = await engine.select(request)
            changed = pin.request.model_copy(
                update={
                    "scope_stack": pin.request.scope_stack.model_copy(
                        update={field: getattr(other, field)}
                    )
                }
            )
            result = await engine.resolve(changed, pin)
            assert result.status == "stale" and result.reason == "request_mismatch"
            # Altering BOTH the request and the caller-owned pin must not evade the journal.
            forged = pin.model_copy(update={"request": changed})
            result = await engine.resolve(changed, forged)
            assert result.status == "stale" and result.reason == "journal_mismatch"

    run_async(scenario())


@pytest.mark.parametrize(
    "change", [{"recipe": "different_recipe"}, {"requested_types": (MemoryType.PREFERENCE,)}]
)
def test_recipe_or_type_change_cannot_resolve_a_pin(change: dict[str, object]) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            engine = _assembly(conn)
            request = _request(spine)
            pin = await engine.select(request)
            changed = pin.request.model_copy(update=change)
            result = await engine.resolve(changed, pin)
            assert result.status == "stale" and result.reason == "request_mismatch"
            result = await engine.resolve(changed, pin.model_copy(update={"request": changed}))
            assert result.status == "stale" and result.reason == "journal_mismatch"

    run_async(scenario())


def test_account_scope_is_journaled_and_requested_types_are_canonical() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            memory_id = await _write(
                conn,
                spine,
                scope_type=MemoryScopeType.ACCOUNT,
                scope_id=str(spine.account_entity_id),
            )
            request = _request(spine)
            request = request.model_copy(
                update={
                    "scope_stack": request.scope_stack.model_copy(
                        update={
                            "account_entity_id": spine.account_entity_id,
                        }
                    ),
                    "requested_types": (
                        MemoryType.PREFERENCE,
                        MemoryType.BEHAVIORAL_LEARNING,
                        MemoryType.PREFERENCE,
                    ),
                }
            )
            engine = _assembly(conn)
            pin = await engine.select(request)
            assert pin.request.requested_types == (
                MemoryType.BEHAVIORAL_LEARNING,
                MemoryType.PREFERENCE,
            )
            journal = await _store.get_bundle_journal(conn, str(pin.journal_id))
            assert journal is not None
            assert journal["scope_stack"]["account_entity_id"] == str(spine.account_entity_id)
            reordered = request.model_copy(
                update={"requested_types": tuple(reversed(request.requested_types))}
            )
            result = await engine.resolve(reordered, pin)
            assert isinstance(result, MemoryBundle)
            assert [e.memory_id for e in result.entries] == [memory_id]

    run_async(scenario())


@pytest.mark.parametrize("status", [s for s in MemoryStatus if s != MemoryStatus.ACTIVE])
def test_selected_memory_must_still_be_active(status: MemoryStatus) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            memory_id = await _write(conn, spine, scope_id=spine.brand_id)
            engine = _assembly(conn)
            request = _request(spine)
            pin = await engine.select(request)
            successor = None
            if status == MemoryStatus.SUPERSEDED:
                successor = await _write(
                    conn, spine, scope_id=spine.brand_id, body="Replacement guidance."
                )
            await _store.set_status(conn, memory_id, status, superseded_by=successor)
            result = await engine.resolve(request, pin)
            assert result.status == "unavailable" and result.reason == "selected_memory_unavailable"

    run_async(scenario())


@pytest.mark.parametrize(
    "mutation",
    [
        "body",
        "trigger",
        "trust_grade",
        "confirmation_count",
        "cycles_since_confirmed",
        "scope",
        "type",
        "provenance_class",
        "claim_refs",
    ],
)
def test_content_or_any_label_change_makes_selection_stale(mutation: str) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            memory_id = await _write(conn, spine, scope_id=spine.brand_id)
            engine = _assembly(conn)
            request = _request(spine)
            pin = await engine.select(request)
            if mutation == "scope":
                await conn.execute(
                    text(
                        "UPDATE memory SET scope_type='product', scope_brand_id=NULL, "
                        "scope_product_id=:product WHERE memory_id=:id"
                    ),
                    {"product": spine.product_id, "id": memory_id},
                )
            elif mutation == "claim_refs":
                from .conftest import seed_claim

                claim_id = await seed_claim(conn)
                await conn.execute(
                    text("INSERT INTO memory_claim_ref (memory_id, claim_id) VALUES (:id, :claim)"),
                    {"id": memory_id, "claim": claim_id},
                )
            else:
                values = {
                    "body": "Changed advice.",
                    "trigger": "A different context.",
                    "trust_grade": 4,
                    "confirmation_count": 1,
                    "cycles_since_confirmed": 1,
                    "type": "behavioral_learning",
                    "provenance_class": "agent_observed",
                }
                await conn.execute(
                    text(f"UPDATE memory SET {mutation}=:value WHERE memory_id=:id"),
                    {"value": values[mutation], "id": memory_id},
                )
            result = await engine.resolve(request, pin)
            assert result.status == "stale" and result.reason == "bundle_changed"

    run_async(scenario())


@pytest.mark.parametrize("field", ["selected_ids", "bundle_hash", "journal_id"])
def test_forged_selection_cannot_override_authoritative_journal(field: str) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            await _write(conn, spine, scope_id=spine.brand_id)
            engine = _assembly(conn)
            request = _request(spine)
            pin = await engine.select(request)
            replacements = {"selected_ids": (), "bundle_hash": "0" * 64, "journal_id": str(uuid4())}
            result = await engine.resolve(
                request, pin.model_copy(update={field: replacements[field]})
            )
            expected = (
                ("unavailable", "journal_unavailable")
                if field == "journal_id"
                else ("stale", "journal_mismatch")
            )
            assert (result.status, result.reason) == expected

    run_async(scenario())


@pytest.mark.parametrize("removed", ["memory", "journal"])
def test_deleted_selected_record_or_journal_is_unavailable(removed: str) -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            memory_id = await _write(conn, spine, scope_id=spine.brand_id)
            engine = _assembly(conn)
            request = _request(spine)
            pin = await engine.select(request)
            if removed == "memory":
                # Simulate missing storage, not the supported erasure path (tested below).
                await conn.execute(
                    text("DELETE FROM memory_event WHERE memory_id=:id"), {"id": memory_id}
                )
                await conn.execute(
                    text("DELETE FROM memory WHERE memory_id=:id"), {"id": memory_id}
                )
            else:
                await conn.execute(
                    text("DELETE FROM memory_bundle_journal WHERE journal_id=:id"),
                    {"id": pin.journal_id},
                )
            result = await engine.resolve(request, pin)
            assert result.status == "unavailable"
            assert result.reason == (
                "selected_memory_unavailable" if removed == "memory" else "journal_unavailable"
            )

    run_async(scenario())


def test_erasure_blocks_pinned_content_even_after_switch_is_reenabled() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            subject = await seed_contact(conn)
            body = "Prefers a short text invitation for this person."
            memory_id = await _write(
                conn, spine, scope_id=spine.brand_id, body=body, subject_entity_id=subject
            )
            engine = _assembly(conn)
            request = _request(spine)
            pin = await engine.select(request)
            master_off = Assembly(
                conn, settings=make_settings(memory_enabled=False), caps=make_caps()
            )
            result = await master_off.resolve(request, pin)
            assert result.status == "unavailable" and result.reason == "memory_disabled"
            await set_memory_enabled(conn, spine.workspace_id, False, actor="test")
            erased = await erase_subject(
                conn, workspace_id=spine.workspace_id, subject_entity_id=subject, caps=make_caps()
            )
            assert erased == [memory_id]
            await set_memory_enabled(conn, spine.workspace_id, True, actor="test")
            result = await engine.resolve(request, pin)
            assert result.status == "unavailable" and result.reason == "selected_memory_unavailable"
            assert body not in result.model_dump_json()
            journal = await _store.get_bundle_journal(conn, str(pin.journal_id))
            assert body not in json.dumps(journal, default=str)

    run_async(scenario())


def test_transactional_wrapper_selects_and_resolves_with_fresh_transaction_scopes() -> None:
    from clue_api.memory_wiring import memory_assembly_factory

    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            memory_id = await _write(conn, spine, scope_id=spine.brand_id)

            @asynccontextmanager
            async def connection_factory() -> AsyncIterator[AsyncConnection]:
                # Real DB savepoints keep this battery rollback-isolated while checking that
                # each public wrapper method completes its own transactional scope.
                assert not conn.in_nested_transaction()
                async with conn.begin_nested():
                    yield conn

            seam = memory_assembly_factory(make_settings(), connection_factory)
            request = _request(spine)
            pin = await seam.select(request)
            assert pin is not None, "production wrapper must implement selection"
            assert not conn.in_nested_transaction()
            assert pin.selected_ids == (memory_id,)
            journal = await _store.get_bundle_journal(conn, str(pin.journal_id))
            assert journal is not None
            result = await seam.resolve(request, pin)
            assert isinstance(result, MemoryBundle)
            assert not conn.in_nested_transaction()
            assert [e.memory_id for e in result.entries] == [memory_id]
            await set_memory_enabled(conn, spine.workspace_id, False, actor="test")
            result = await seam.resolve(request, pin)
            assert result.status == "unavailable" and result.reason == "memory_disabled"
            assert not conn.in_nested_transaction()

    run_async(scenario())

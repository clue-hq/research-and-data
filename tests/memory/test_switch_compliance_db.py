"""Kill-switch + compliance battery (Doc M §19 "kill-switch" / "compliance"): typed no-op,
no phantom bundle, audit trail, freeze-intact, master default; erasure leaves no personal
substring at rest or in any rendered view; the objection lock preserves the row."""

from __future__ import annotations

import json

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    AssemblyRequest,
    MemoryAccepted,
    MemoryDisabled,
    MemoryStatus,
    MemoryType,
    ScopeStack,
)
from clue_memory import (
    ERASED,
    Assembly,
    WriteSeam,
    _store,  # test setup/inspection only
    erase_subject,
    lock_memory,
    set_memory_enabled,
    switch_audit,
)

from .conftest import (
    add_judge,
    make_caps,
    make_settings,
    rollback_conn,
    run_async,
    seed_contact,
    seed_spine,
    submission,
)

pytestmark = pytest.mark.usefixtures("require_memory_db")


def _request(spine: object) -> AssemblyRequest:
    return AssemblyRequest(
        scope_stack=ScopeStack(
            workspace_id=spine.workspace_id,  # type: ignore[attr-defined]
            brand_id=spine.brand_id,  # type: ignore[attr-defined]
        ),
        recipe="draft_outreach",
        requested_types=(MemoryType.PREFERENCE,),
    )


async def _write(conn: AsyncConnection, spine: object, **kwargs: object) -> str:
    outcome = await WriteSeam(conn, add_judge(), settings=make_settings(), caps=make_caps()).submit(
        submission(spine.workspace_id, scope_id=spine.brand_id, **kwargs)
    )  # type: ignore[attr-defined, arg-type]
    assert isinstance(outcome, MemoryAccepted)
    return outcome.memory_id


# --- kill-switch -------------------------------------------------------------


def test_switch_off_write_noop_read_no_step_audit_recorded_freeze_intact() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            settings = make_settings()
            memory_id = await _write(conn, spine, body="Guidance before the flip.")
            baseline = await Assembly(conn, settings=settings, caps=make_caps()).assemble(
                _request(spine)
            )
            assert baseline is not None

            await set_memory_enabled(conn, spine.workspace_id, False, actor="ops@client")

            # Write seam: a quiet TYPED no-op — not an error, and nothing lands.
            outcome = await WriteSeam(
                conn, add_judge(), settings=settings, caps=make_caps()
            ).submit(submission(spine.workspace_id, scope_id=spine.brand_id, body="Lost words."))
            assert isinstance(outcome, MemoryDisabled)
            rows = await _store.list_records(
                conn, workspace_id=spine.workspace_id, statuses=tuple(MemoryStatus)
            )
            assert [m.memory_id for m in rows] == [memory_id]

            # Read seam: no memory step at all — no phantom empty bundle, no journal row.
            journal_count_before = (
                await conn.execute(text("SELECT count(*) FROM memory_bundle_journal"))
            ).scalar_one()
            assert (
                await Assembly(conn, settings=settings, caps=make_caps()).assemble(_request(spine))
                is None
            )
            journal_count_after = (
                await conn.execute(text("SELECT count(*) FROM memory_bundle_journal"))
            ).scalar_one()
            assert journal_count_after == journal_count_before

            # The audit makes "memory was off" verifiable: who, when.
            audit = await switch_audit(conn, spine.workspace_id)
            assert [(a["enabled"], a["actor"]) for a in audit] == [(False, "ops@client")]

            # Off ≠ erasure: toggling back on serves the store unchanged (freeze-intact).
            await set_memory_enabled(conn, spine.workspace_id, True, actor="ops@client")
            restored = await Assembly(conn, settings=settings, caps=make_caps()).assemble(
                _request(spine)
            )
            assert restored is not None
            assert restored.bundle_hash() == baseline.bundle_hash()

    run_async(scenario())


def test_deploy_master_default_off_blanks_every_workspace() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            await _write(conn, spine, body="Guidance one.")
            off = make_settings(memory_enabled=False)
            outcome = await WriteSeam(conn, add_judge(), settings=off, caps=make_caps()).submit(
                submission(spine.workspace_id, scope_id=spine.brand_id, body="More words.")
            )
            assert isinstance(outcome, MemoryDisabled)
            assert (
                await Assembly(conn, settings=off, caps=make_caps()).assemble(_request(spine))
                is None
            )

    run_async(scenario())


# --- DSAR: erasure + objection lock ------------------------------------------


def test_erasure_leaves_no_personal_substring_anywhere() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            contact = await seed_contact(conn)
            secret = "prefers whisky tastings over golf"
            memory_id = await _write(
                conn,
                spine,
                body=f"This champion {secret}.",
                subject_entity_id=contact,
            )
            settings = make_settings()
            bundle = await Assembly(conn, settings=settings, caps=make_caps()).assemble(
                _request(spine)
            )
            assert bundle is not None and secret in bundle.entries[0].body

            erased = await erase_subject(
                conn,
                workspace_id=spine.workspace_id,
                subject_entity_id=contact,
                caps=make_caps(),
            )
            assert erased == [memory_id]

            # At rest: content redacted, refs severed, status tombstoned.
            row = await _store.get_memory(conn, memory_id)
            assert row is not None
            assert row.status is MemoryStatus.TOMBSTONED
            assert row.body == ERASED and row.trigger == ERASED
            assert row.creating_quote is None and row.claim_refs == ()
            # Served projections: the next bundle carries nothing of it.
            after = await Assembly(conn, settings=settings, caps=make_caps()).assemble(
                _request(spine)
            )
            assert after is not None
            assert secret not in after.canonical_bytes().decode()
            # And no journal row (before or after) carries the substring — ids-never-bodies.
            journals = await conn.execute(
                text("SELECT included, excluded, cross_branch_pairs FROM memory_bundle_journal")
            )
            assert secret not in json.dumps(
                [dict(r) for r in journals.mappings().all()], default=str
            )

    run_async(scenario())


def test_objection_lock_excludes_from_bundles_but_preserves_the_row() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            memory_id = await _write(conn, spine, body="Guidance to object to.")
            locked = await lock_memory(conn, memory_id, caps=make_caps(), actor="dsar-surface")
            assert locked is not None and locked.status is MemoryStatus.LOCKED
            assert locked.body == "Guidance to object to."  # survives, distinct from tombstone
            bundle = await Assembly(conn, settings=make_settings(), caps=make_caps()).assemble(
                _request(spine)
            )
            assert bundle is not None and bundle.entries == ()
            events = {e["event_type"] for e in await _store.list_events(conn, memory_id)}
            assert "locked" in events

    run_async(scenario())


def test_dsar_verbs_operate_while_memory_is_off() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            contact = await seed_contact(conn)
            memory_id = await _write(
                conn, spine, body="Champion-specific guidance.", subject_entity_id=contact
            )
            await set_memory_enabled(conn, spine.workspace_id, False, actor="admin")
            erased = await erase_subject(
                conn,
                workspace_id=spine.workspace_id,
                subject_entity_id=contact,
                caps=make_caps(),
            )
            assert erased == [memory_id]  # obligations attach to holding, not using

    run_async(scenario())

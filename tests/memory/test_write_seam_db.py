"""Write-seam battery (Doc M §19 "write path" + "model & seams"): the enforcement chain,
born trust, reconciliation dispositions, and the schema-level structural guarantees."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import (
    MemoryAccepted,
    MemoryPreconditionFailed,
    MemoryProvenanceClass,
    MemoryRejected,
    MemoryScopeType,
    MemoryStatus,
    ReconcileJudgment,
    ReconcileVerdictKind,
)
from clue_memory import (
    WriteSeam,
    _store,  # test setup/inspection only — see conftest docstring
    retire,
)

from .conftest import (
    RaisingJudge,
    ScriptedJudge,
    add_judge,
    make_caps,
    make_settings,
    rollback_conn,
    run_async,
    seed_claim,
    seed_contact,
    seed_spine,
    submission,
)

pytestmark = pytest.mark.usefixtures("require_memory_db")


def _seam(conn: AsyncConnection, judge: object) -> WriteSeam:
    return WriteSeam(conn, judge, settings=make_settings(), caps=make_caps())  # type: ignore[arg-type]


# --- born trust (provenance × status matrix) --------------------------------


def test_born_trust_matrix() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            expectations = [
                (MemoryProvenanceClass.USER_STATED, MemoryStatus.ACTIVE, 3),
                (MemoryProvenanceClass.EDIT_DISTILLED, MemoryStatus.PROPOSED, 2),
                (MemoryProvenanceClass.AGENT_OBSERVED, MemoryStatus.PROPOSED, 1),
            ]
            for i, (provenance, status, trust) in enumerate(expectations):
                outcome = await _seam(conn, add_judge()).submit(
                    submission(
                        spine.workspace_id,
                        scope_id=spine.brand_id,
                        body=f"Distinct guidance number {i}.",
                        provenance=provenance,
                    )
                )
                assert isinstance(outcome, MemoryAccepted)
                assert outcome.status is status
                row = await _store.get_memory(conn, outcome.memory_id)
                assert row is not None and row.trust_grade == trust
                events = await _store.list_events(conn, outcome.memory_id)
                assert {e["event_type"] for e in events} == {"created"}

    run_async(scenario())


# --- species / body / subject-binding refusals ------------------------------


def test_fact_shaped_submission_rejected_toward_the_ckb() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            judge = ScriptedJudge(
                ReconcileJudgment(
                    verdict=ReconcileVerdictKind.ADD, species_ok=False, rationale="a fact"
                )
            )
            outcome = await _seam(conn, judge).submit(
                submission(spine.workspace_id, scope_id=spine.brand_id, body="They raised $40M.")
            )
            assert isinstance(outcome, MemoryRejected)
            assert outcome.reason.value == "fact_shaped"
            assert "claim store" in outcome.detail
            # Nothing landed.
            rows = await _store.list_records(
                conn, workspace_id=spine.workspace_id, statuses=tuple(MemoryStatus)
            )
            assert rows == []

    run_async(scenario())


def test_body_rule_rejection() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            judge = ScriptedJudge(
                ReconcileJudgment(
                    verdict=ReconcileVerdictKind.ADD, body_ok=False, rationale="verbatim quote"
                )
            )
            outcome = await _seam(conn, judge).submit(
                submission(
                    spine.workspace_id,
                    scope_id=spine.brand_id,
                    body="Their champion wrote: 'my CFO vetoed per-seat pricing'.",
                )
            )
            assert isinstance(outcome, MemoryRejected)
            assert outcome.reason.value == "body_rule"

    run_async(scenario())


def test_person_adjacent_body_without_subject_binding_is_precondition_failed() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            with pytest.raises(MemoryPreconditionFailed):
                await _seam(conn, add_judge()).submit(
                    submission(
                        spine.workspace_id,
                        scope_id=spine.brand_id,
                        body="Reach the champion at jordan.rivers@example.com for approvals.",
                    )
                )

    run_async(scenario())


def test_subject_bound_memory_lands_person_adjacent_with_refs() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            contact = await seed_contact(conn)
            claim = await seed_claim(conn)
            outcome = await _seam(conn, add_judge()).submit(
                submission(
                    spine.workspace_id,
                    scope_id=spine.brand_id,
                    body="This champion prefers short, numbers-first emails.",
                    subject_entity_id=contact,
                    claim_refs=(claim,),
                )
            )
            assert isinstance(outcome, MemoryAccepted)
            row = await _store.get_memory(conn, outcome.memory_id)
            assert row is not None
            assert row.retention_class == "person_adjacent"
            assert row.subject_entity_id == contact
            assert row.claim_refs == (claim,)
            # Reverse direction of the ref relation is queryable (DSAR cascade / ref health).
            reverse = await conn.execute(
                text("SELECT memory_id FROM memory_claim_ref WHERE claim_id = :c"),
                {"c": claim},
            )
            assert reverse.scalar_one() == outcome.memory_id

    run_async(scenario())


# --- scope validity: the schema is the enforcement --------------------------


def test_cross_workspace_scope_reference_is_unrepresentable() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine_a = await seed_spine(conn, tag="A")
            spine_b = await seed_spine(conn, tag="B")
            with pytest.raises(IntegrityError):
                await _seam(conn, add_judge()).submit(
                    submission(spine_a.workspace_id, scope_id=spine_b.brand_id)
                )

    run_async(scenario())


def test_dangling_scope_id_dies_at_the_schema() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            with pytest.raises(IntegrityError):
                await _seam(conn, add_judge()).submit(
                    submission(spine.workspace_id, scope_id="brd_missing")
                )

    run_async(scenario())


def test_non_workspace_scope_requires_scope_id() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            with pytest.raises(MemoryPreconditionFailed):
                await _seam(conn, add_judge()).submit(
                    submission(spine.workspace_id, scope_type=MemoryScopeType.PROJECT)
                )

    run_async(scenario())


# --- reconciliation dispositions --------------------------------------------


def test_deterministic_restatement_confirms_without_consulting_the_judge() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            first = await _seam(conn, add_judge()).submit(
                submission(spine.workspace_id, scope_id=spine.brand_id)
            )
            assert isinstance(first, MemoryAccepted)
            judge = RaisingJudge()  # would raise if consulted
            outcome = await _seam(conn, judge).submit(
                submission(
                    spine.workspace_id, scope_id=spine.brand_id, body="never use FEAR-BASED hooks"
                )
            )
            assert isinstance(outcome, MemoryAccepted)
            assert outcome.verdict is ReconcileVerdictKind.NOOP
            assert outcome.memory_id == first.memory_id
            assert judge.calls == 0
            row = await _store.get_memory(conn, first.memory_id)
            assert row is not None
            assert row.confirmation_count == 1
            assert row.cycles_since_confirmed == 0
            assert row.trust_grade == 4  # raised by confirmation, capped

    run_async(scenario())


def test_zombie_twin_guard_dormant_restatement_reactivates_with_history() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            first = await _seam(conn, add_judge()).submit(
                submission(spine.workspace_id, scope_id=spine.brand_id)
            )
            assert isinstance(first, MemoryAccepted)
            await _store.set_status(conn, first.memory_id, MemoryStatus.DORMANT)  # crowded out
            outcome = await _seam(conn, RaisingJudge()).submit(
                submission(
                    spine.workspace_id, scope_id=spine.brand_id, body="Never use fear-based hooks"
                )
            )
            assert isinstance(outcome, MemoryAccepted)
            assert outcome.memory_id == first.memory_id  # never a duplicate ADD
            assert outcome.status is MemoryStatus.ACTIVE  # promotion with history intact
            rows = await _store.list_records(
                conn, workspace_id=spine.workspace_id, statuses=tuple(MemoryStatus)
            )
            assert len(rows) == 1  # no zombie twin
            events = await _store.list_events(conn, first.memory_id)
            assert {"confirmed", "reactivated"} <= {e["event_type"] for e in events}

    run_async(scenario())


def test_contradiction_supersedes_with_linked_trail_and_single_served_side() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            first = await _seam(conn, add_judge()).submit(
                submission(spine.workspace_id, scope_id=spine.brand_id)
            )
            assert isinstance(first, MemoryAccepted)
            judge = ScriptedJudge(
                ReconcileJudgment(
                    verdict=ReconcileVerdictKind.SUPERSEDE,
                    target_memory_id=first.memory_id,
                    rationale="the old guidance is wrong",
                )
            )
            outcome = await _seam(conn, judge).submit(
                submission(
                    spine.workspace_id,
                    scope_id=spine.brand_id,
                    body="Fear-based hooks actually convert best here.",
                )
            )
            assert isinstance(outcome, MemoryAccepted)
            assert outcome.verdict is ReconcileVerdictKind.SUPERSEDE
            old = await _store.get_memory(conn, first.memory_id)
            assert old is not None
            assert old.status is MemoryStatus.SUPERSEDED
            assert old.superseded_by == outcome.memory_id  # the trail
            assert old.trust_grade == 2  # contradiction lowered trust, journaled
            # The read path never serves both sides: only the successor is active.
            active = await _store.list_records(
                conn, workspace_id=spine.workspace_id, statuses=(MemoryStatus.ACTIVE,)
            )
            assert [m.memory_id for m in active] == [outcome.memory_id]
            events = {e["event_type"] for e in await _store.list_events(conn, first.memory_id)}
            assert {"contradicted", "superseded"} <= events

    run_async(scenario())


def test_judge_failure_parks_proposed_even_for_user_stated() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn)
            outcome = await _seam(conn, RaisingJudge()).submit(
                submission(spine.workspace_id, scope_id=spine.brand_id)
            )
            assert isinstance(outcome, MemoryAccepted)
            assert outcome.status is MemoryStatus.PROPOSED  # never silently activated

    run_async(scenario())


# --- cross-tenant isolation (fail-closed) ------------------------------------


def test_cross_tenant_fuzz_zero_leakage() -> None:
    async def scenario() -> None:
        async with rollback_conn() as conn:
            spines = [await seed_spine(conn, tag=t) for t in ("A", "B", "C")]
            for i, spine in enumerate(spines):
                for j in range(2):
                    outcome = await _seam(conn, add_judge()).submit(
                        submission(
                            spine.workspace_id,
                            scope_id=spine.brand_id,
                            body=f"Workspace {i} guidance {j}.",
                        )
                    )
                    assert isinstance(outcome, MemoryAccepted)
            # Every read is tenant-filtered: each workspace sees exactly its own rows.
            for i, spine in enumerate(spines):
                rows = await _store.list_records(
                    conn, workspace_id=spine.workspace_id, statuses=tuple(MemoryStatus)
                )
                assert len(rows) == 2
                assert all(m.workspace_id == spine.workspace_id for m in rows)
                assert all(f"Workspace {i} " in m.body for m in rows)

    run_async(scenario())


# --- source thread + the human retire verb -----------------------------------


def test_a_project_note_carries_its_source_thread_and_can_be_retired() -> None:
    """The project home writes a note from a thread and removes it: the row remembers which
    thread said it, and *Remove memory* invalidates (never deletes) — fail-closed per workspace."""
    from clue_api.thread_store import create_thread

    async def scenario() -> None:
        async with rollback_conn() as conn:
            spine = await seed_spine(conn, "-src")
            thread = await create_thread(
                conn,
                thread_id="thr_memory_src",
                workspace_id=spine.workspace_id,
                project_id=spine.project_id,
            )
            seam = WriteSeam(
                conn,
                add_judge(),  # type: ignore[arg-type]
                settings=make_settings(memory_enabled=True),
                caps=make_caps(),
            )
            outcome = await seam.submit(
                submission(
                    spine.workspace_id,
                    scope_type=MemoryScopeType.PROJECT,
                    scope_id=spine.project_id,
                    body="Keep outreach under 120 words.",
                ).model_copy(update={"source_thread_id": thread.id})
            )
            assert isinstance(outcome, MemoryAccepted)
            memory = await _store.get_memory(conn, outcome.memory_id)
            assert memory is not None and memory.source_thread_id == "thr_memory_src"
            assert memory.status is MemoryStatus.ACTIVE

            assert (
                await retire(
                    conn,
                    memory_id=memory.memory_id,
                    workspace_id=spine.workspace_id,
                    actor="usr_home",
                    cause="removed on project home",
                )
                is True
            )
            retired = await _store.get_memory(conn, memory.memory_id)
            assert retired is not None and retired.status is MemoryStatus.INVALIDATED
            events = await _store.list_events(conn, memory.memory_id)
            assert events[-1]["event_type"] == "invalidated"
            assert events[-1]["actor"] == "usr_home"
            # Already retired, and another workspace's caller: both refused, not re-journaled.
            assert (
                await retire(
                    conn,
                    memory_id=memory.memory_id,
                    workspace_id=spine.workspace_id,
                    actor="usr_home",
                    cause="again",
                )
                is False
            )
            assert (
                await retire(
                    conn,
                    memory_id=memory.memory_id,
                    workspace_id="ws_other",
                    actor="usr_home",
                    cause="x",
                )
                is False
            )

    run_async(scenario())

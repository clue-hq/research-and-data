"""DB-gated tests for the M7.1 persistence path — the ``account_run`` table + the production store.

These need a reachable, migrated Postgres (``account_run`` + the field registry) and ``pytest.skip``
without one. They cover: the ``account_run_status`` enum parity with :class:`AccountRunStatus`, the
repository round-trip, gap detection over the merge view, and an end-to-end graph run on
:class:`DbAccountRunStore` + a real ``AsyncPostgresSaver`` (with resume), cleaning up its committed
rows afterwards.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import text

from clue_core import (
    ExtractionMethod,
    PassKind,
    ResearchMode,
    account_claim,
    new_claim_id,
    new_entity_id,
    new_project_run_id,
    new_run_id,
)
from clue_core.field import FieldDef
from clue_db import db_lifespan, transaction
from clue_research.claimstore import insert_claim, register_field
from clue_research.claimstore.tenancy import WorkspaceScope
from clue_research.durable import (
    AccountResearchGraph,
    AccountRunStatus,
    AccountRunSubPhase,
    DbAccountRunStore,
    WorkerRegistry,
    compute_gap_fields,
    ensure_account_run,
    get_account_run,
    insert_account_run,
    save_plan,
    save_references,
    set_account_sub_phase,
    set_status,
)
from clue_research.durable.planning import build_plan
from tests.db.conftest import run_async
from tests.durable.conftest import StubAspectWorker, rollback_conn

pytestmark = pytest.mark.usefixtures("require_durable_db")

_DEEP_FIELD = "account.strategic_moves"


def _deep_field() -> FieldDef:
    return FieldDef(
        field_key=_DEEP_FIELD,
        value_type="str",
        pass_kind=PassKind.DEEP,
        freshness_ttl=timedelta(days=365),
    )


def test_account_run_status_enum_matches_db() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            rows = await conn.execute(
                text(
                    "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
                    "WHERE t.typname = 'account_run_status' ORDER BY e.enumsortorder"
                )
            )
            db_labels = [r[0] for r in rows.all()]
        assert db_labels == [s.value for s in AccountRunStatus]

    run_async(_run())


def test_account_run_sub_phase_enum_matches_db() -> None:
    # M8A.0 parity: the account_run_sub_phase PG enum labels equal AccountRunSubPhase's values, in
    # order (guards drift between the migration and the durable enum).
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            rows = await conn.execute(
                text(
                    "SELECT e.enumlabel FROM pg_type t JOIN pg_enum e ON e.enumtypid = t.oid "
                    "WHERE t.typname = 'account_run_sub_phase' ORDER BY e.enumsortorder"
                )
            )
            db_labels = [r[0] for r in rows.all()]
        assert db_labels == [s.value for s in AccountRunSubPhase]

    run_async(_run())


def test_account_run_repository_round_trip() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = new_run_id()
            project_run_id = new_project_run_id()
            entity_id = new_entity_id()

            await insert_account_run(
                conn,
                account_run_id=run_id,
                project_run_id=project_run_id,
                entity_id=entity_id,
                tier="top",
            )
            row = await get_account_run(conn, run_id)
            assert row is not None
            assert row.status is AccountRunStatus.PENDING
            assert row.plan_json == {} and row.references_index == {}
            assert row.cost_cents == Decimal(0)

            # ensure_account_run is a no-op when the row already exists (resume-safe).
            await ensure_account_run(
                conn,
                account_run_id=run_id,
                project_run_id=project_run_id,
                entity_id=entity_id,
                tier="ignored-on-conflict",
            )
            assert (await get_account_run(conn, run_id)).tier == "top"

            plan = build_plan([_deep_field()], tier="top")
            await save_plan(
                conn,
                run_id,
                plan_json=plan.model_dump(mode="json"),
                status=AccountRunStatus.RUNNING,
            )
            row = await get_account_run(conn, run_id)
            assert row.status is AccountRunStatus.RUNNING
            assert row.plan_json["aspects"][0]["aspect"] == "account"

            refs = {"account": [str(new_claim_id())]}
            await save_references(
                conn,
                run_id,
                references_index=refs,
                cost_cents=Decimal("12"),
                status=AccountRunStatus.DONE,
            )
            row = await get_account_run(conn, run_id)
            assert row.status is AccountRunStatus.DONE
            assert row.references_index == refs
            assert row.cost_cents == Decimal("12")

            await set_status(conn, run_id, AccountRunStatus.FAILED)
            assert (await get_account_run(conn, run_id)).status is AccountRunStatus.FAILED

    run_async(_run())


def test_account_run_sub_phase_repository_round_trip() -> None:
    # M8A.0: a fresh row's sub_phase is NULL (not started); set_account_sub_phase advances it
    # monotonically through the three deep boundaries, leaving the coarse status untouched.
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = new_run_id()
            await insert_account_run(
                conn,
                account_run_id=run_id,
                project_run_id=new_project_run_id(),
                entity_id=new_entity_id(),
                tier="top",
            )

            row = await get_account_run(conn, run_id)
            assert row is not None and row.sub_phase is None  # born NULL

            for sub in (
                AccountRunSubPhase.ACCOUNT_PROFILED,
                AccountRunSubPhase.COMMITTEE_DISCOVERED,
                AccountRunSubPhase.CONTACTS_COMPLETE,
            ):
                await set_account_sub_phase(conn, run_id, sub)
                row = await get_account_run(conn, run_id)
                assert row is not None and row.sub_phase is sub

            # sub_phase is orthogonal to status: advancing the marker never touched the lifecycle.
            assert row.status is AccountRunStatus.PENDING

    run_async(_run())


def test_db_store_sub_phase_round_trips_through_the_seam() -> None:
    # M8A.0: the AccountRunStore seam (own-transaction) round-trips the marker against a committed
    # row — the convenience path the M8A.1 orchestrator uses for the simple resume marker.
    async def _run() -> None:
        async with db_lifespan():
            committed_id = new_run_id()
            store = DbAccountRunStore()
            try:
                async with transaction() as conn:
                    await insert_account_run(
                        conn,
                        account_run_id=committed_id,
                        project_run_id=new_project_run_id(),
                        entity_id=new_entity_id(),
                        tier="top",
                    )
                # born NULL through the seam, then advances and reads back.
                assert await store.get_account_sub_phase(account_run_id=committed_id) is None
                await store.set_account_sub_phase(
                    account_run_id=committed_id, sub_phase=AccountRunSubPhase.ACCOUNT_PROFILED
                )
                assert (
                    await store.get_account_sub_phase(account_run_id=committed_id)
                    is AccountRunSubPhase.ACCOUNT_PROFILED
                )
                await store.set_account_sub_phase(
                    account_run_id=committed_id, sub_phase=AccountRunSubPhase.CONTACTS_COMPLETE
                )
                assert (
                    await store.get_account_sub_phase(account_run_id=committed_id)
                    is AccountRunSubPhase.CONTACTS_COMPLETE
                )
                # an unknown run resolves to None (no row), not an error.
                assert await store.get_account_sub_phase(account_run_id=new_run_id()) is None
            finally:
                async with transaction() as conn:
                    await conn.execute(
                        text("DELETE FROM account_run WHERE id = :id"), {"id": committed_id}
                    )

    run_async(_run())


def test_compute_gap_fields_detects_missing_and_filled() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            await register_field(conn, _deep_field())
            entity_id = new_entity_id()
            scope = WorkspaceScope.public_only()

            # No claim yet → the deep field is a gap.
            gaps = await compute_gap_fields(conn, entity_id, scope=scope, field_keys=(_DEEP_FIELD,))
            assert [f.field_key for f in gaps] == [_DEEP_FIELD]

            # A fresh claim fills it → no longer a gap.
            await insert_claim(
                conn,
                account_claim(
                    entity_id=entity_id,
                    field_key=_DEEP_FIELD,
                    value_json="expanding into EU",
                    source_tier=2,
                    extraction_method=ExtractionMethod.SCRAPE,
                    confidence=0.9,
                    run_id=new_run_id(),
                    research_mode=ResearchMode.ACCOUNT_PROFILING,
                    source_url="https://example.com/news",
                    evidence_span="opening a Berlin office",
                ),
            )
            gaps = await compute_gap_fields(conn, entity_id, scope=scope, field_keys=(_DEEP_FIELD,))
            assert gaps == []

    run_async(_run())


def test_graph_end_to_end_on_db_store_and_postgres_checkpointer() -> None:
    """The production path: a real graph run on :class:`DbAccountRunStore` + ``AsyncPostgresSaver``,
    asserting references land + the ``account_run`` row is persisted, and a re-invocation resumes
    without re-spawning. Commits real rows, so it cleans them up afterwards."""
    from clue_research.durable.graph import postgres_checkpointer

    async def _run() -> None:
        run_id = new_run_id()
        entity_id = new_entity_id()
        project_run_id = new_project_run_id()
        worker = StubAspectWorker("account", n_claims=2, cost_cents=Decimal("5"))
        registry = WorkerRegistry()
        registry.register(worker)
        graph = AccountResearchGraph(store=DbAccountRunStore(), workers=registry)

        async with db_lifespan():
            # Register the deep field (committed) so the store's gap detection sees it.
            async with transaction() as conn:
                await register_field(conn, _deep_field())
            try:
                async with postgres_checkpointer() as saver:
                    result = await graph.run(
                        entity_id,
                        tier="top",
                        project_run_id=project_run_id,
                        checkpointer=saver,
                        account_run_id=run_id,
                        field_keys=(_DEEP_FIELD,),
                    )
                    assert result.status is AccountRunStatus.DONE
                    assert len(result.references_index["account"]) == 2
                    assert result.cost_cents == Decimal("5")
                    assert worker.calls == 1

                    # the account_run row is persisted with the references + cost.
                    async with transaction() as conn:
                        row = await get_account_run(conn, run_id)
                    assert row is not None
                    assert row.status is AccountRunStatus.DONE
                    assert len(row.references_index["account"]) == 2

                    # resume: same thread → already complete → nothing re-spawned.
                    again = await graph.run(
                        entity_id,
                        tier="top",
                        project_run_id=project_run_id,
                        checkpointer=saver,
                        account_run_id=run_id,
                        field_keys=(_DEEP_FIELD,),
                    )
                    assert worker.calls == 1
                    assert again.references_index == result.references_index
            finally:
                async with transaction() as conn:
                    await conn.execute(
                        text("DELETE FROM account_run WHERE id = :id"), {"id": run_id}
                    )
                    await conn.execute(
                        text("DELETE FROM field_definition WHERE field_key = :k"),
                        {"k": _DEEP_FIELD},
                    )
                    # ``AsyncPostgresSaver.setup()`` created its checkpointer tables at runtime,
                    # OUTSIDE alembic. Drop them (not just this thread's rows) so a persistent
                    # schema stays alembic-only afterwards — otherwise a rerun of the suite fails
                    # tests/db/test_db_migrations.py::test_no_domain_tables_at_m0_head. They are
                    # cheap runtime state: the next ``postgres_checkpointer()`` recreates them.
                    for tbl in (
                        "checkpoint_blobs",
                        "checkpoint_writes",
                        "checkpoints",
                        "checkpoint_migrations",
                    ):
                        await conn.execute(text(f"DROP TABLE IF EXISTS {tbl} CASCADE"))

    run_async(_run())


def test_db_store_fail_marks_status() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = new_run_id()
            await insert_account_run(
                conn,
                account_run_id=run_id,
                project_run_id=new_project_run_id(),
                entity_id=new_entity_id(),
                tier="top",
            )

        # DbAccountRunStore.fail opens its own transaction; exercise it against a committed row.
        async with db_lifespan():
            committed_id = new_run_id()
            try:
                async with transaction() as conn:
                    await insert_account_run(
                        conn,
                        account_run_id=committed_id,
                        project_run_id=new_project_run_id(),
                        entity_id=new_entity_id(),
                        tier="top",
                    )
                await DbAccountRunStore().fail(
                    account_run_id=committed_id, status=AccountRunStatus.BUDGET_EXCEEDED
                )
                async with transaction() as conn:
                    row = await get_account_run(conn, committed_id)
                assert row is not None and row.status is AccountRunStatus.BUDGET_EXCEEDED
            finally:
                async with transaction() as conn:
                    await conn.execute(
                        text("DELETE FROM account_run WHERE id = :id"), {"id": committed_id}
                    )

    run_async(_run())

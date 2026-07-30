"""M12.3 — the ``handoff_event`` outbox (the durable emit/notify path).

Idempotent emission on ``(project_run, account, icp_spec_version, icp_key)``, tenant-scoped reads,
and the delivery-status lifecycle. DB-backed (skips without one, like the other M12 suites)."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from clue_core import new_entity_id, new_project_run_id
from clue_research.narrative import (
    HANDOFF_EVENT_STATUSES,
    HandoffEvent,
    HandoffEventStatus,
    emit_handoff_event,
    get_handoff_event,
    handoff_ref_for,
    list_handoff_events,
    mark_handoff_event,
)

from .conftest import rollback_conn, run_async

_CLIENT = "client-acme"
_OTHER = "client-other"

pytestmark = pytest.mark.usefixtures("require_narrative_db")


def _event(*, run, account, client=_CLIENT, icp_version=1, icp_key=""):
    return HandoffEvent(
        project_run_id=run,
        account_entity_id=account,
        icp_spec_version=icp_version,
        icp_key=icp_key,
        workspace_id=client,
        handoff_ref=handoff_ref_for(account, icp_version, icp_key),
        schema_version="1.0",
    )


def test_handoff_ref_includes_icp_key_only_for_segments() -> None:
    acc = new_entity_id()
    assert handoff_ref_for(acc, 1) == f"/accounts/{acc}/handoff?icp_spec_version=1"
    assert (
        handoff_ref_for(acc, 2, "seg_a")
        == f"/accounts/{acc}/handoff?icp_spec_version=2&icp_key=seg_a"
    )
    assert (
        handoff_ref_for(acc, 2, "seg a", "product/a")
        == f"/accounts/{acc}/handoff?icp_spec_version=2&icp_key=seg+a&product_id=product%2Fa"
    )


def test_status_allowlist_matches_enum() -> None:
    """Code-level drift guard: the CHECK allow-list mirrors the enum (migration hardcodes these)."""
    assert HANDOFF_EVENT_STATUSES == ("pending", "delivered", "failed")
    assert set(HANDOFF_EVENT_STATUSES) == {s.value for s in HandoffEventStatus}


def test_emit_is_idempotent_on_scope_key() -> None:
    """First emit inserts (``True``); a re-emit of the same scope key is a no-op (``False``) — a
    re-entered handoff phase / crash-resume never double-emits (AC3)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run, acc = new_project_run_id(), new_entity_id()
            ev = _event(run=run, account=acc)
            assert await emit_handoff_event(conn, ev) is True
            assert await emit_handoff_event(conn, ev) is False  # idempotent
            rows = await list_handoff_events(conn, project_run_id=run, workspace_id=_CLIENT)
            assert len(rows) == 1
            assert rows[0].status is HandoffEventStatus.PENDING
            assert rows[0].handoff_ref == ev.handoff_ref

    run_async(_run())


def test_distinct_icp_segments_emit_separately() -> None:
    """Two ICP segments of one account (D5) are distinct outbox rows, not a clobber."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run, acc = new_project_run_id(), new_entity_id()
            assert await emit_handoff_event(conn, _event(run=run, account=acc, icp_key="a")) is True
            assert await emit_handoff_event(conn, _event(run=run, account=acc, icp_key="b")) is True
            rows = await list_handoff_events(conn, project_run_id=run, workspace_id=_CLIENT)
            assert {r.icp_key for r in rows} == {"a", "b"}

    run_async(_run())


def test_reads_are_workspace_scoped() -> None:
    """A client only ever sees its own events (substrate §2)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run, acc = new_project_run_id(), new_entity_id()
            await emit_handoff_event(conn, _event(run=run, account=acc, client=_CLIENT))
            assert (
                await get_handoff_event(
                    conn,
                    project_run_id=run,
                    account_entity_id=acc,
                    icp_spec_version=1,
                    workspace_id=_OTHER,
                )
                is None
            )
            assert await list_handoff_events(conn, project_run_id=run, workspace_id=_OTHER) == []

    run_async(_run())


def test_mark_delivered_stamps_delivered_at_and_filters() -> None:
    """``mark`` sets the lifecycle status; ``delivered_at`` is stamped iff DELIVERED (the CHECK)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run, acc = new_project_run_id(), new_entity_id()
            await emit_handoff_event(conn, _event(run=run, account=acc))
            row = await get_handoff_event(
                conn,
                project_run_id=run,
                account_entity_id=acc,
                icp_spec_version=1,
                workspace_id=_CLIENT,
            )
            assert row is not None and row.delivered_at is None
            await mark_handoff_event(conn, row.id, status=HandoffEventStatus.DELIVERED)
            after = await get_handoff_event(
                conn,
                project_run_id=run,
                account_entity_id=acc,
                icp_spec_version=1,
                workspace_id=_CLIENT,
            )
            assert after is not None
            assert after.status is HandoffEventStatus.DELIVERED
            assert after.delivered_at is not None
            delivered = await list_handoff_events(
                conn, project_run_id=run, workspace_id=_CLIENT, status=HandoffEventStatus.DELIVERED
            )
            assert [r.id for r in delivered] == [row.id]
            assert (
                await list_handoff_events(
                    conn,
                    project_run_id=run,
                    workspace_id=_CLIENT,
                    status=HandoffEventStatus.PENDING,
                )
                == []
            )

    run_async(_run())


def test_db_check_rejects_unknown_status() -> None:
    """The column CHECK rejects a status outside the allow-list (the DB-side drift guard)."""

    async def _run() -> None:
        async with rollback_conn() as conn:
            run, acc = new_project_run_id(), new_entity_id()
            with pytest.raises(IntegrityError):
                await conn.execute(
                    text(
                        "INSERT INTO handoff_event (project_run_id, account_entity_id, "
                        "icp_spec_version, workspace_id, handoff_ref, schema_version, status) "
                        "VALUES (:r, :a, 1, :c, '/x', '1.0', 'bogus')"
                    ),
                    {"r": run, "a": str(acc), "c": _CLIENT},
                )

    run_async(_run())

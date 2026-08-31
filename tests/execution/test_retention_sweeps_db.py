"""Part II D8 (ruling R-D8-4) — the two retention sweeps, at the substrate.

Two deletions land in D8 and they are of completely different kinds, so they are proven
differently:

1. :func:`~clue_execution.stream_tokens.sweep_stream_tokens` is **semantically free**. Both consume
   statements require ``used_at IS NULL AND expires_at > now()``, so a used or expired row is
   unreadable by every code path in the repository. The proof obligations are therefore about
   *scope* (a live token survives) and *unobservability* (a swept token is refused exactly as an
   unswept-but-used one is — no consumer can tell the sweep ran).
2. :func:`~clue_execution.run_events.prune_design_run_progress_events` **destroys durable history**,
   so what is proven is the floors: it never deletes a terminal row, never touches a ``project_run``
   subject, refuses whole any subject with no surviving terminal row, and leaves a contiguous
   suffix — never a mid-range hole.

The eligibility half of the pruner (which runs are old enough, and the retention floor) lives in the
design tree and is proven in ``tests/design/test_design_event_pruner_db.py``.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text

from clue_core import DESIGN_RUN_SUBJECT_KIND, new_project_run_id
from clue_execution.run_events import (
    emit_design_run_event,
    emit_run_event,
    list_run_events,
    prune_design_run_progress_events,
)
from clue_execution.stream_tokens import (
    consume_stream_token,
    consume_subject_stream_token,
    mint_stream_token,
    sweep_stream_tokens,
)
from tests.db.conftest import _db_available, run_async
from tests.profiling.conftest import rollback_conn

_needs_db = pytest.mark.skipif(
    not _db_available(), reason="CLUE_DATABASE_URL unset or database unreachable"
)

_WS = "ws-d8-retention"
_OTHER = "ws-d8-retention-other"


def _design_run() -> str:
    return f"run_{uuid4().hex}"


async def _age_token(conn, token, *, column: str, minutes: int = 10) -> None:
    """Push a token's ``used_at``/``expires_at`` into the past.

    Ageing rather than passing ``grace_s=0``: ``now()`` is the TRANSACTION's timestamp, so a token
    minted and consumed inside the test's own transaction carries the same instant the sweep
    compares against and no grace value can separate them. Ageing the row is also the honest
    simulation — in production a sweep pass always runs in a later transaction than the mint.
    """
    assert column in ("used_at", "expires_at")
    # ``created_at`` moves with ``expires_at``: the ``stream_token_expiry_after_creation`` CHECK
    # requires expiry strictly after creation, and a row minted a moment ago whose expiry is pushed
    # into the past would violate it. Ageing the whole row is the faithful shape anyway.
    columns = f"{column} = now() - make_interval(mins => :m)"
    if column == "expires_at":
        columns += ", created_at = now() - make_interval(mins => :m2)"
    await conn.execute(
        text(f"UPDATE stream_token SET {columns} WHERE token = :t"),
        {"m": minutes, "m2": minutes + 1, "t": token},
    )


# --- the stream_token sweep ---------------------------------------------------------------------


@_needs_db
def test_the_token_sweep_deletes_only_spent_tokens_and_leaves_live_ones() -> None:
    """Scope: used or expired go, live stays. Nothing else is a candidate."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            live = await mint_stream_token(conn, workspace_id=_WS, ttl_s=3600.0)
            used = await mint_stream_token(conn, workspace_id=_WS, ttl_s=3600.0)
            expired = await mint_stream_token(conn, workspace_id=_WS, ttl_s=3600.0)
            other_tenant_live = await mint_stream_token(conn, workspace_id=_OTHER, ttl_s=3600.0)

            assert await consume_stream_token(conn, token=used, workspace_id=_WS) is True
            await _age_token(conn, used, column="used_at")
            # Age the third one past its expiry rather than minting a negative TTL (the
            # ``stream_token_expiry_after_creation`` CHECK forbids that shape).
            await _age_token(conn, expired, column="expires_at")

            deleted = await sweep_stream_tokens(conn, grace_s=0.0)
            assert deleted == 2

            survivors = {
                str(row[0])
                for row in await conn.execute(
                    text("SELECT token FROM stream_token WHERE workspace_id IN (:a, :b)"),
                    {"a": _WS, "b": _OTHER},
                )
            }
            assert str(live) in survivors
            assert str(other_tenant_live) in survivors
            assert str(used) not in survivors
            assert str(expired) not in survivors

    run_async(_run())


@_needs_db
def test_the_token_sweeps_grace_window_spares_a_just_spent_token() -> None:
    """The grace is real: a token used seconds ago is not swept under the default window."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            used = await mint_stream_token(conn, workspace_id=_WS, ttl_s=3600.0)
            assert await consume_stream_token(conn, token=used, workspace_id=_WS) is True

            assert await sweep_stream_tokens(conn) == 0
            still_there = (
                await conn.execute(
                    text("SELECT count(*) FROM stream_token WHERE token = :t"), {"t": used}
                )
            ).scalar_one()
            assert still_there == 1

    run_async(_run())


@_needs_db
def test_a_swept_tokens_absence_is_unobservable_through_consume() -> None:
    """The whole safety argument, as a behavioural claim.

    A consumer cannot tell whether a spent token's row still exists: an already-used token and a
    swept-away token are refused *identically*, which is also how an unknown token is refused (no
    existence leak). And sweeping does not disturb a live token's consume.
    """

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = _design_run()
            spent = await mint_stream_token(
                conn,
                workspace_id=_WS,
                subject_kind=DESIGN_RUN_SUBJECT_KIND,
                subject_id=run_id,
                ttl_s=3600.0,
            )
            live = await mint_stream_token(
                conn,
                workspace_id=_WS,
                subject_kind=DESIGN_RUN_SUBJECT_KIND,
                subject_id=run_id,
                ttl_s=3600.0,
            )

            # First use succeeds and derives the tenant; the second is refused with the row present.
            assert (
                await consume_subject_stream_token(
                    conn, token=spent, subject_kind=DESIGN_RUN_SUBJECT_KIND, subject_id=run_id
                )
                == _WS
            )
            refused_with_row = await consume_subject_stream_token(
                conn, token=spent, subject_kind=DESIGN_RUN_SUBJECT_KIND, subject_id=run_id
            )

            await _age_token(conn, spent, column="used_at")
            assert await sweep_stream_tokens(conn, grace_s=0.0) == 1

            refused_without_row = await consume_subject_stream_token(
                conn, token=spent, subject_kind=DESIGN_RUN_SUBJECT_KIND, subject_id=run_id
            )
            assert refused_with_row is None
            assert refused_without_row is refused_with_row, (
                "a swept token is distinguishable from a merely-used one"
            )
            # An unknown token — never minted at all — is refused the same way.
            assert (
                await consume_subject_stream_token(
                    conn, token=uuid4(), subject_kind=DESIGN_RUN_SUBJECT_KIND, subject_id=run_id
                )
                is None
            )
            # And the sweep did not touch the live token minted for the same subject.
            assert (
                await consume_subject_stream_token(
                    conn, token=live, subject_kind=DESIGN_RUN_SUBJECT_KIND, subject_id=run_id
                )
                == _WS
            )

    run_async(_run())


@_needs_db
def test_the_token_sweep_is_idempotent() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            token = await mint_stream_token(conn, workspace_id=_WS, ttl_s=3600.0)
            assert await consume_stream_token(conn, token=token, workspace_id=_WS) is True
            await _age_token(conn, token, column="used_at")
            assert await sweep_stream_tokens(conn, grace_s=0.0) == 1
            assert await sweep_stream_tokens(conn, grace_s=0.0) == 0

    run_async(_run())


# --- the design run_event pruner's DELETE half ---------------------------------------------------


async def _emit_turn(
    conn, *, workspace_id: str, run_id: str, progress: int, terminal: bool
) -> None:
    for index in range(progress):
        await emit_design_run_event(
            conn,
            workspace_id=workspace_id,
            design_run_id=run_id,
            topic="design.run.event",
            payload={"event_type": "dsl_compiled", "n": index},
        )
    if terminal:
        await emit_design_run_event(
            conn,
            workspace_id=workspace_id,
            design_run_id=run_id,
            topic="design.run.completed",
            payload={"event_type": "result", "result": {"status": "succeeded"}},
        )


async def _subject_rows(conn, *, workspace_id: str, run_id: str) -> list[tuple[int, str]]:
    rows = await list_run_events(
        conn,
        workspace_id=workspace_id,
        subject_kind=DESIGN_RUN_SUBJECT_KIND,
        subject_id=run_id,
    )
    return [(row.seq, row.topic) for row in rows]


@_needs_db
def test_the_pruner_never_deletes_a_terminal_row() -> None:
    """Floor 2, the one the whole SSE close-out depends on: progress goes, terminal survives."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = _design_run()
            await _emit_turn(conn, workspace_id=_WS, run_id=run_id, progress=4, terminal=True)
            before = await _subject_rows(conn, workspace_id=_WS, run_id=run_id)
            assert [topic for _seq, topic in before] == ["design.run.event"] * 4 + [
                "design.run.completed"
            ]

            deleted = await prune_design_run_progress_events(
                conn, workspace_id=_WS, subject_id=run_id
            )
            assert deleted == 4

            after = await _subject_rows(conn, workspace_id=_WS, run_id=run_id)
            assert [topic for _seq, topic in after] == ["design.run.completed"]
            assert after[0] == before[-1], "the surviving row is the original terminal row"

    run_async(_run())


@_needs_db
def test_the_pruner_deletes_a_contiguous_prefix_and_never_a_mid_range_hole() -> None:
    """Floor 5. The terminal event is a run's last durable write, so what is removed is a prefix."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = _design_run()
            await _emit_turn(conn, workspace_id=_WS, run_id=run_id, progress=5, terminal=True)
            before = await _subject_rows(conn, workspace_id=_WS, run_id=run_id)

            await prune_design_run_progress_events(conn, workspace_id=_WS, subject_id=run_id)
            after = await _subject_rows(conn, workspace_id=_WS, run_id=run_id)

            surviving = [seq for seq, _topic in after]
            original = [seq for seq, _topic in before]
            # The survivors are exactly a SUFFIX of the original seq list: everything removed came
            # off the front. Any mid-range deletion would break this equality.
            assert surviving == original[len(original) - len(surviving) :]
            assert surviving == [original[-1]]

    run_async(_run())


@_needs_db
def test_the_pruner_refuses_a_subject_with_no_terminal_row() -> None:
    """Floor 2's second half: a still-running (or pre-D7) subject is skipped WHOLE, not partly."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = _design_run()
            await _emit_turn(conn, workspace_id=_WS, run_id=run_id, progress=3, terminal=False)

            deleted = await prune_design_run_progress_events(
                conn, workspace_id=_WS, subject_id=run_id
            )
            assert deleted == 0
            assert len(await _subject_rows(conn, workspace_id=_WS, run_id=run_id)) == 3

    run_async(_run())


@_needs_db
def test_the_pruner_touches_neither_another_subject_nor_another_tenant_nor_a_project_run() -> None:
    """Floors 1 and the tenancy scope, in one pass over a deliberately noisy table."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            target = _design_run()
            sibling = _design_run()
            project_run = new_project_run_id()

            await _emit_turn(conn, workspace_id=_WS, run_id=target, progress=2, terminal=True)
            await _emit_turn(conn, workspace_id=_WS, run_id=sibling, progress=2, terminal=True)
            await _emit_turn(conn, workspace_id=_OTHER, run_id=target, progress=2, terminal=True)
            project = await emit_run_event(
                conn, workspace_id=_WS, run_id=project_run, topic="run.step.progress"
            )

            assert (
                await prune_design_run_progress_events(conn, workspace_id=_WS, subject_id=target)
                == 2
            )

            assert len(await _subject_rows(conn, workspace_id=_WS, run_id=target)) == 1
            assert len(await _subject_rows(conn, workspace_id=_WS, run_id=sibling)) == 3
            assert len(await _subject_rows(conn, workspace_id=_OTHER, run_id=target)) == 3
            survived = await list_run_events(conn, workspace_id=_WS, run_id=project_run)
            assert [row.seq for row in survived] == [project.seq]

    run_async(_run())


@_needs_db
def test_the_pruner_is_idempotent() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = _design_run()
            await _emit_turn(conn, workspace_id=_WS, run_id=run_id, progress=3, terminal=True)
            assert (
                await prune_design_run_progress_events(conn, workspace_id=_WS, subject_id=run_id)
                == 3
            )
            assert (
                await prune_design_run_progress_events(conn, workspace_id=_WS, subject_id=run_id)
                == 0
            )

    run_async(_run())

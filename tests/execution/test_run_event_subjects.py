"""Part II D7 — the ``run_event`` stream's subject widening.

Three things are proven here, in order of how badly they would hurt if wrong:

1. **The DB integrity matrix.** ``run_event_subject_coherent`` is the whole point of the widening:
   a project-run event cannot lie about its subject and a non-project event cannot fake a project
   run. It is asserted against real Postgres, not against the writer that is supposed to obey it.
2. **The design emitter.** ``emit_design_run_event`` round-trips, and refuses a project-run topic
   loudly (a design leg that could stamp ``run.phase.completed`` would forge project lifecycle
   events on a client's project stream).
3. **Parity between the two DALs.** D7 ships two thin DALs over the one table for an import-contract
   reason (documented in ``clue_execution.run_events``). These tests are what stop that duplication
   from drifting: same row shape, same topic vocabulary, same subject vocabulary as the DB CHECK,
   same replay semantics.
"""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from clue_core import new_project_run_id
from clue_execution.run_events import (
    DESIGN_RUN_EVENT_TOPICS,
    DESIGN_RUN_SUBJECT_KIND,
    PROJECT_RUN_SUBJECT_KIND,
    InvalidRunEventSubject,
    SubjectReplayPlan,
    emit_design_run_event,
    list_subject_run_events,
    plan_subject_replay,
    subject_event_created_at,
)
from clue_execution.run_events import RunEventRow as ExecutionRunEventRow
from clue_projections import ReplayPlan, plan_replay
from clue_research.durable import (
    DESIGN_RUN_EVENT_TOPICS as RESEARCH_DESIGN_TOPICS,
)
from clue_research.durable import (
    RUN_EVENT_SUBJECT_KINDS,
    RUN_EVENT_TOPICS,
    emit_run_event,
    list_run_events,
)
from clue_research.durable import (
    RunEventRow as ResearchRunEventRow,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import rollback_conn

_WS = "ws-d7"
_OTHER = "ws-d7-other"
_DESIGN_RUN = "run_0123456789abcdef0123456789abcdef"

# The drift guards below are deliberately NOT DB-gated: the duplication they police is a source-
# level hazard, so they must fail in the offline ``make check`` gate, not only where a Postgres
# happens to be configured. Only the tests that touch the table carry the skip-gate.
_needs_db = pytest.mark.usefixtures("require_profiling_db")


# --- offline parity: the two DALs cannot drift ------------------------------------------------


def test_the_two_run_event_row_models_are_field_identical() -> None:
    """D7 ships two DALs over one table. If their row shapes diverge, a design consumer and a
    project consumer stop seeing the same envelope — so pin them field-for-field."""
    assert set(ExecutionRunEventRow.model_fields) == set(ResearchRunEventRow.model_fields)
    # Same names AND same annotations — a divergent type is drift just as much as a missing field.
    for name, field in ExecutionRunEventRow.model_fields.items():
        assert field.annotation == ResearchRunEventRow.model_fields[name].annotation, name
    # ``run_id`` is optional on BOTH (it is absent for every non-project subject).
    assert not ExecutionRunEventRow.model_fields["run_id"].is_required()
    assert not ResearchRunEventRow.model_fields["run_id"].is_required()


def test_design_topic_vocabularies_agree_and_are_stream_topics() -> None:
    """``clue_execution`` may not import ``clue_research``, so it re-states the design topics. This
    is the binding that keeps the restatement honest — and proves each is a *stored* stream topic
    (an emitter writing a topic outside ``RUN_EVENT_TOPICS`` would be invisible to the contract)."""
    assert DESIGN_RUN_EVENT_TOPICS == RESEARCH_DESIGN_TOPICS
    assert set(DESIGN_RUN_EVENT_TOPICS) <= set(RUN_EVENT_TOPICS)
    assert DESIGN_RUN_EVENT_TOPICS == (
        "design.run.event",
        "design.run.completed",
        "design.run.failed",
    )
    # The design topics are exactly the design.* prefix of the stream vocabulary — no design topic
    # may hide outside the prefix, and no design.* topic may exist that an emitter cannot write.
    assert set(DESIGN_RUN_EVENT_TOPICS) == {t for t in RUN_EVENT_TOPICS if t.startswith("design.")}


def test_subject_kind_constants_agree_across_packages() -> None:
    assert PROJECT_RUN_SUBJECT_KIND == RUN_EVENT_SUBJECT_KINDS[0] == "project_run"
    assert DESIGN_RUN_SUBJECT_KIND == "design_run"
    assert set(RUN_EVENT_SUBJECT_KINDS) == {PROJECT_RUN_SUBJECT_KIND, DESIGN_RUN_SUBJECT_KIND}


def test_the_stream_token_store_is_one_module_with_one_subject_vocabulary() -> None:
    """D7 Round B relocated the token DAL from ``clue_api`` to ``clue_execution`` so the design
    API can mint/consume the SAME token species (Rule 5 forbids ``lumen_api → clue_api``).

    Two things must stay true, and both are cheap to break silently: ``clue_api.stream_tokens``
    must be a re-export rather than a second implementation (a fork would drift into two auth
    models — exactly what D7 exists to prevent), and the token's subject vocabulary must be the
    stream's, or a token could be minted for a subject no stream serves.
    """
    import clue_api.stream_tokens as api_tokens
    import clue_execution.stream_tokens as exec_tokens

    for name in ("mint_stream_token", "consume_stream_token", "consume_subject_stream_token"):
        assert getattr(api_tokens, name) is getattr(exec_tokens, name)
    assert exec_tokens.PROJECT_RUN_SUBJECT_KIND == PROJECT_RUN_SUBJECT_KIND
    # The workspace-deriving consume exists precisely because the design stream cannot state its
    # tenant; it must therefore REQUIRE a subject (a workspace-wide token must not open a run).
    assert "subject_kind" in exec_tokens.consume_subject_stream_token.__annotations__
    assert "workspace_id" not in exec_tokens.consume_subject_stream_token.__annotations__


def test_the_two_replay_plan_shapes_agree() -> None:
    assert SubjectReplayPlan.__dataclass_fields__.keys() == ReplayPlan.__dataclass_fields__.keys()


# --- the DB integrity matrix -------------------------------------------------------------------


async def _refused(conn, sql: str, params: dict[str, object]) -> str:
    """Run an INSERT that must be refused; return the DB error text (which names the constraint).

    A SAVEPOINT keeps the rollback-scoped test connection usable after each expected failure."""
    savepoint = await conn.begin_nested()
    try:
        await conn.execute(text(sql), params)
    except (IntegrityError, DBAPIError) as exc:
        await savepoint.rollback()
        return str(exc)
    await savepoint.rollback()
    raise AssertionError(f"DB accepted a row it must refuse: {params}")


_INSERT = (
    "INSERT INTO run_event (workspace_id, subject_kind, subject_id, run_id, topic, payload) "
    "VALUES (:ws, :kind, :sid, :run_id, :topic, '{}'::jsonb)"
)


@_needs_db
def test_subject_coherence_check_matrix() -> None:
    """The four ways a row could lie about its subject, each refused by name."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = new_project_run_id()

            # A project-run row with no run_id — the subject claims a run that is not there.
            err = await _refused(
                conn,
                _INSERT,
                {
                    "ws": _WS,
                    "kind": "project_run",
                    "sid": str(run_id),
                    "run_id": None,
                    "topic": "run.done",
                },
            )
            assert "run_event_subject_coherent" in err

            # A design row carrying a run_id — a non-project subject faking a project run.
            err = await _refused(
                conn,
                _INSERT,
                {
                    "ws": _WS,
                    "kind": "design_run",
                    "sid": _DESIGN_RUN,
                    "run_id": run_id,
                    "topic": "design.run.event",
                },
            )
            assert "run_event_subject_coherent" in err

            # A project-run row whose subject_id is not its run id — the two keys disagreeing is
            # exactly the drift the CHECK exists to make unrepresentable.
            err = await _refused(
                conn,
                _INSERT,
                {
                    "ws": _WS,
                    "kind": "project_run",
                    "sid": "not-the-run-id",
                    "run_id": run_id,
                    "topic": "run.done",
                },
            )
            assert "run_event_subject_coherent" in err

            # An unknown subject kind (Part III must add it to the CHECK deliberately).
            err = await _refused(
                conn,
                _INSERT,
                {
                    "ws": _WS,
                    "kind": "agent_run",
                    "sid": "whatever",
                    "run_id": None,
                    "topic": "run.done",
                },
            )
            assert "run_event_subject_kind_known" in err

            # A blank subject id.
            err = await _refused(
                conn,
                _INSERT,
                {
                    "ws": _WS,
                    "kind": "design_run",
                    "sid": "   ",
                    "run_id": None,
                    "topic": "design.run.event",
                },
            )
            assert "run_event_subject_id_nonempty" in err

            # A pre-D7 writer (no subject columns) fails loudly instead of writing an unroutable
            # row — the migration's stated, deliberate non-zero-downtime posture.
            err = await _refused(
                conn,
                "INSERT INTO run_event (workspace_id, run_id, topic, payload) "
                "VALUES (:ws, :run_id, :topic, '{}'::jsonb)",
                {"ws": _WS, "run_id": run_id, "topic": "run.done"},
            )
            assert "subject_id" in err

    run_async(_run())


@_needs_db
def test_db_subject_kind_vocabulary_matches_the_code_constants() -> None:
    """The CHECK is the authority; the code constants mirror it. Read the constraint back and
    assert every declared kind is accepted and the set is exactly the declared one."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            src = (
                await conn.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = 'run_event_subject_kind_known'"
                    )
                )
            ).scalar_one()
            for kind in RUN_EVENT_SUBJECT_KINDS:
                assert f"'{kind}'" in src
            # No kind is accepted by the DB that the code does not know about: count the quoted
            # literals in the CHECK body.
            assert src.count("'") == 2 * len(RUN_EVENT_SUBJECT_KINDS)

    run_async(_run())


# --- the design emitter ------------------------------------------------------------------------


@_needs_db
def test_emit_design_run_event_round_trips_and_is_subject_scoped() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            other_design = "run_ffffffffffffffffffffffffffffffff"
            project_run = new_project_run_id()

            a = await emit_design_run_event(
                conn,
                workspace_id=_WS,
                design_run_id=_DESIGN_RUN,
                topic="design.run.event",
                payload={"event_type": "scene_patch_applied", "n": 1},
            )
            b = await emit_design_run_event(
                conn,
                workspace_id=_WS,
                design_run_id=_DESIGN_RUN,
                topic="design.run.completed",
                payload={"event_type": "turn_complete"},
            )
            # Same workspace, a DIFFERENT design subject, and a project run — neither may bleed in.
            noise = await emit_design_run_event(
                conn, workspace_id=_WS, design_run_id=other_design, topic="design.run.failed"
            )
            cross_tenant = await emit_design_run_event(
                conn, workspace_id=_OTHER, design_run_id=_DESIGN_RUN, topic="design.run.event"
            )
            project = await emit_run_event(
                conn, workspace_id=_WS, run_id=project_run, topic="run.done"
            )

            assert a.subject_kind == DESIGN_RUN_SUBJECT_KIND
            assert a.subject_id == _DESIGN_RUN
            assert a.run_id is None
            assert a.payload["event_type"] == "scene_patch_applied"
            assert a.seq < b.seq

            served = await list_subject_run_events(
                conn,
                workspace_id=_WS,
                subject_kind=DESIGN_RUN_SUBJECT_KIND,
                subject_id=_DESIGN_RUN,
            )
            assert [e.seq for e in served] == [a.seq, b.seq]
            assert noise.seq not in {e.seq for e in served}
            assert cross_tenant.seq not in {e.seq for e in served}
            assert project.seq not in {e.seq for e in served}

            # The cursor and the horizon probe behave exactly as on a project-run stream.
            assert [
                e.seq
                for e in await list_subject_run_events(
                    conn,
                    workspace_id=_WS,
                    subject_kind=DESIGN_RUN_SUBJECT_KIND,
                    subject_id=_DESIGN_RUN,
                    after_seq=a.seq,
                )
            ] == [b.seq]
            assert await subject_event_created_at(conn, workspace_id=_WS, seq=a.seq) is not None
            assert await subject_event_created_at(conn, workspace_id=_OTHER, seq=a.seq) is None

    run_async(_run())


@_needs_db
def test_design_emitter_may_not_impersonate_a_project_run_topic() -> None:
    """The DB CHECK stops a design event claiming a project-run *subject*; this guard stops it
    claiming a project-run *topic* — otherwise a design leg could forge ``run.done`` onto a
    client's project stream."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            for forged in ("run.done", "run.phase.completed", "research_view.updated", "design.x"):
                with pytest.raises(InvalidRunEventSubject):
                    await emit_design_run_event(
                        conn, workspace_id=_WS, design_run_id=_DESIGN_RUN, topic=forged
                    )
            with pytest.raises(InvalidRunEventSubject):
                await emit_design_run_event(
                    conn, workspace_id=_WS, design_run_id="   ", topic="design.run.event"
                )
            # Nothing was written by any refusal.
            assert (
                await list_subject_run_events(
                    conn,
                    workspace_id=_WS,
                    subject_kind=DESIGN_RUN_SUBJECT_KIND,
                    subject_id=_DESIGN_RUN,
                )
                == []
            )

    run_async(_run())


# --- one replay semantics ----------------------------------------------------------------------


@_needs_db
def test_both_replay_planners_agree_on_a_design_subject() -> None:
    """ "One replay semantics" is the D7 claim. Plan the same design stream through both planners
    (``clue_projections.plan_replay`` and ``clue_execution.plan_subject_replay``) and require
    identical reset / backlog / cursor decisions — fresh, mid-stream, and unknown-cursor."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            events = [
                await emit_design_run_event(
                    conn,
                    workspace_id=_WS,
                    design_run_id=_DESIGN_RUN,
                    topic="design.run.event",
                    payload={"i": i},
                )
                for i in range(4)
            ]
            horizon = 3600.0

            for cursor in (None, events[1].seq, 10_000_000):
                projections = await plan_replay(
                    conn,
                    workspace_id=_WS,
                    subject_kind=DESIGN_RUN_SUBJECT_KIND,
                    subject_id=_DESIGN_RUN,
                    last_event_id=cursor,
                    horizon_s=horizon,
                )
                execution = await plan_subject_replay(
                    conn,
                    workspace_id=_WS,
                    subject_kind=DESIGN_RUN_SUBJECT_KIND,
                    subject_id=_DESIGN_RUN,
                    last_event_id=cursor,
                    horizon_s=horizon,
                )
                assert projections.reset == execution.reset
                assert projections.effective_cursor == execution.effective_cursor
                assert [e.seq for e in projections.backlog] == [e.seq for e in execution.backlog]

            # Fresh connect: the whole subject backlog, no reset.
            fresh = await plan_subject_replay(
                conn,
                workspace_id=_WS,
                subject_kind=DESIGN_RUN_SUBJECT_KIND,
                subject_id=_DESIGN_RUN,
                last_event_id=None,
                horizon_s=horizon,
            )
            assert not fresh.reset
            assert [e.seq for e in fresh.backlog] == [e.seq for e in events]

            # Mid-stream cursor: gapless, no reset, cursor carried through as the tail floor.
            mid = await plan_subject_replay(
                conn,
                workspace_id=_WS,
                subject_kind=DESIGN_RUN_SUBJECT_KIND,
                subject_id=_DESIGN_RUN,
                last_event_id=events[1].seq,
                horizon_s=horizon,
            )
            assert not mid.reset and mid.effective_cursor == events[1].seq
            assert [e.seq for e in mid.backlog] == [e.seq for e in events[2:]]

            # An unknown cursor resets and drops the floor to 0 (never a dead tail) — identical to
            # the project-run rule.
            unknown = await plan_subject_replay(
                conn,
                workspace_id=_WS,
                subject_kind=DESIGN_RUN_SUBJECT_KIND,
                subject_id=_DESIGN_RUN,
                last_event_id=10_000_000,
                horizon_s=horizon,
            )
            assert unknown.reset and unknown.effective_cursor == 0
            assert [e.seq for e in unknown.backlog] == [e.seq for e in events]

    run_async(_run())


@_needs_db
def test_project_and_design_subjects_share_one_monotone_workspace_stream() -> None:
    """Both subjects append to the same per-workspace ``seq`` line — that is what makes "one
    transport" real — while each subject filter serves only its own rows."""

    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            run_id = new_project_run_id()
            p1 = await emit_run_event(conn, workspace_id=_WS, run_id=run_id, topic="run.done")
            d1 = await emit_design_run_event(
                conn, workspace_id=_WS, design_run_id=_DESIGN_RUN, topic="design.run.event"
            )
            p2 = await emit_run_event(
                conn, workspace_id=_WS, run_id=run_id, topic="run.phase.started"
            )
            assert p1.seq < d1.seq < p2.seq

            whole = await list_run_events(conn, workspace_id=_WS)
            assert [e.seq for e in whole] == [p1.seq, d1.seq, p2.seq]

            # The pre-D7 per-run filter is unchanged and never sees the design row.
            assert [
                e.seq for e in await list_run_events(conn, workspace_id=_WS, run_id=run_id)
            ] == [
                p1.seq,
                p2.seq,
            ]
            # The subject filter is the general form of the same thing.
            assert [
                e.seq
                for e in await list_run_events(
                    conn,
                    workspace_id=_WS,
                    subject_kind=PROJECT_RUN_SUBJECT_KIND,
                    subject_id=str(run_id),
                )
            ] == [p1.seq, p2.seq]
            assert [
                e.seq
                for e in await list_run_events(
                    conn,
                    workspace_id=_WS,
                    subject_kind=DESIGN_RUN_SUBJECT_KIND,
                    subject_id=_DESIGN_RUN,
                )
            ] == [d1.seq]
            # A whole-kind filter (every design leg in the workspace) is legal…
            assert [
                e.seq
                for e in await list_run_events(
                    conn, workspace_id=_WS, subject_kind=DESIGN_RUN_SUBJECT_KIND
                )
            ] == [d1.seq]
            # …but an unkinded subject_id is refused: ids are unique per kind only, so an unkinded
            # id filter would silently collide across taxonomies.
            with pytest.raises(ValueError, match="subject_kind"):
                await list_run_events(conn, workspace_id=_WS, subject_id=_DESIGN_RUN)

    run_async(_run())

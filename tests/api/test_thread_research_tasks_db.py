"""Slice C **C2**: the durable research-task read a thread's progress card polls.

D5 gave the *turn* a task part: at turn close the stream emits one snapshot per run the turn
launched, and then the stream ends. The fleet, however, keeps working for minutes afterwards — so
the card the founder is watching freezes at whatever the last SSE frame said. This suite pins the
read that unfreezes it: a plain GET a poller can hit every few seconds, serving the same task shape
the stream already emitted, plus the two things a poller needs and a stream frame does not carry —
a monotonic ``revision`` to merge on, and per-field progress inside the accounts still running.

What it pins:

* **the counts are the job rows** — a three-account fleet with one job settled reads
  ``total: 3 / queued: 2 / running: 0 / completed: 1``, never a guess and never a fabricated card;
* **the shape is the stream's shape** — ``part_id``/``kind``/``state``/``title``/``run_ref``/
  ``counts`` are byte-identical to the turn-close snapshot, because the route builds them with the
  same :func:`~clue_api.chat.turn_parts.task_part_from_run` the emitter uses;
* **``revision`` rises as the fleet moves** — it is the job-event ledger's high-water mark, so a
  second settlement outranks the first and the transcript reducer's highest-revision-wins merge
  can never show a stale snapshot over a fresher poll;
* **``field_progress`` sums the latest coverage row of each settled job** — the per-account field
  tally, latest-wins per job, and honestly ``null`` before any job has published coverage;
* **a thread that launched nothing is an empty list, not a 404** — the card asks every thread;
* **it is scoped like every other thread read** — another workspace, another project and no thread
  at all are the same 404, and a membership without ``thread.read`` is refused.

DB-backed and rollback-only per ``tests/api`` conventions.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from clue_api.chat import CHAT_PERMISSIONS
from clue_api.chat.turn_parts import PartKind, TaskState
from clue_api.turn_action import derive_turn_action_ref
from clue_core.entity_research import ResearchFinalizationOutcome, ResearchJobState
from clue_fleet import (
    EntityResearchJobEventKind,
    EntityResearchRunEnvelope,
    append_entity_research_job_event,
)

# The fleet's own run-state derivation. Private, borrowed the way the projection's
# ``_turn_action_ref`` is below: the C4 test drives job rows by hand, and duplicating the fleet's
# queued/running/terminal mapping here would let the two drift apart — the point is to advance the
# run exactly as the fleet does after every real transition.
from clue_fleet.entity_research import _refresh_run_state
from clue_projections.thread_research_tasks import _turn_action_ref
from tests.api.test_lane_d5_gate_read_and_rich_parts_db import (
    _answering_turn,
    _app,
    _client,
    _launch_run,
    _seed,
)
from tests.db.conftest import run_async
from tests.profiling.conftest import (
    migrated_db,  # noqa: F401 -- exposes the fixture to this test module
    rollback_conn,
)

_PATH = "/api/v1/projects/{project}/threads/{thread}/research-tasks"


@pytest.fixture
def require_chat_db(request: pytest.FixtureRequest) -> None:
    if not request.getfixturevalue("migrated_db"):
        pytest.skip("requires a migrated per-branch Postgres database")


pytestmark = pytest.mark.usefixtures("require_chat_db")


async def _settle(
    conn: Any,
    envelope: EntityResearchRunEnvelope,
    *,
    job_index: int,
    outcome: ResearchFinalizationOutcome = ResearchFinalizationOutcome.COMPLETED,
) -> UUID:
    """Finish one job the way the fleet finishes one: the row *and* its ledger event.

    The event is not decoration — it is where ``revision`` comes from. A test that only flipped the
    job row would leave the high-water mark where the launch put it and would prove nothing about
    the poller's merge.
    """

    job_id = envelope.jobs[job_index].authorization.job_id
    await conn.execute(
        text(
            "UPDATE entity_research_job SET state='terminal', finalization_outcome=:outcome, "
            " finalization_receipt_ref=:receipt, terminal_at=now() WHERE job_id = :job_id"
        ),
        {
            "outcome": outcome.value,
            "receipt": f"finalization-receipt:{job_id}",
            "job_id": job_id,
        },
    )
    await append_entity_research_job_event(
        conn,
        run_id=envelope.lifecycle.run_id,
        job_id=job_id,
        kind=EntityResearchJobEventKind.FINALIZED,
        from_state=ResearchJobState.QUEUED,
        to_state=ResearchJobState.TERMINAL,
        actor="test",
        references={"finalization_receipt_ref": f"finalization-receipt:{job_id}"},
    )
    return job_id


async def _coverage(
    conn: Any,
    envelope: EntityResearchRunEnvelope,
    *,
    workspace_id: str,
    job_index: int,
    completed: tuple[str, ...],
    unresolved: tuple[str, ...],
    sequence: int = 0,
) -> UUID:
    """One finalization-compiler coverage row, with an explicit ``created_at`` ordering.

    ``sequence`` exists because latest-wins is the contract under test: a job that re-finalizes
    appends a second row, and the projection must read the later one rather than whichever
    ``coverage_id`` sorts last.
    """

    coverage_id = uuid4()
    payload = {
        "coverage_id": str(coverage_id),
        "completed_field_keys": list(completed),
        "unresolved_field_keys": list(unresolved),
    }
    await conn.execute(
        text(
            """
            INSERT INTO entity_research_account_coverage
                (coverage_id, research_run_id, job_id, workspace_id, account_entity_id,
                 result_refs, completed_field_keys, unresolved_field_keys, unresolved_reasons,
                 committee_result_refs, committee_member_ids, committee_status, review_flags,
                 claim_refs, evidence_refs, coverage_json, coverage_sha256, created_at)
            VALUES
                (:coverage_id, :run_id, :job_id, :workspace_id, :account_id,
                 :result_refs, :completed, :unresolved, :reasons,
                 :committee_refs, :member_ids, 'complete', :review_flags,
                 :claim_refs, :evidence_refs, CAST(:coverage_json AS jsonb), :sha,
                 now() + make_interval(mins => :sequence))
            """
        ),
        {
            "coverage_id": coverage_id,
            "run_id": envelope.lifecycle.run_id,
            "job_id": envelope.jobs[job_index].authorization.job_id,
            "workspace_id": workspace_id,
            "account_id": envelope.jobs[job_index].authorization.subject_entity_id,
            "result_refs": [],
            "completed": list(completed),
            "unresolved": list(unresolved),
            "reasons": ["not_found" for _ in unresolved],
            "committee_refs": [],
            "member_ids": [],
            "review_flags": [],
            "claim_refs": [],
            "evidence_refs": [],
            "coverage_json": json.dumps(payload, sort_keys=True),
            "sequence": sequence,
            "sha": hashlib.sha256(
                json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
        },
    )
    return coverage_id


async def _read(conn: Any, seeded: Any, **overrides: str) -> Any:
    async with _client(_app(conn)) as client:
        return await client.get(
            _PATH.format(
                project=overrides.get("project_id", seeded.project_id),
                thread=overrides.get("thread_id", seeded.thread_id),
            ),
            headers={"X-Workspace-Id": overrides.get("workspace_id", seeded.workspace_id)},
        )


# --- the counted read ------------------------------------------------------------------------


def test_the_route_counts_a_three_account_fleet_off_its_own_job_rows(tmp_path: Path) -> None:
    """One settled subject out of three, in the same task shape the turn-close snapshot used."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-c2-count", label="c2_count")
            action_ref = derive_turn_action_ref(seeded.turn_id)
            envelope = await _launch_run(conn, seeded, action_ref=action_ref, accounts=3)
            await _settle(conn, envelope, job_index=0)

            response = await _read(conn, seeded)
            assert response.status_code == 200
            body = response.json()
            assert list(body) == ["tasks"]
            assert len(body["tasks"]) == 1
            served = body["tasks"][0]

            assert served["part_id"] == f"task:{envelope.lifecycle.run_id}"
            assert served["kind"] == PartKind.TASK.value
            assert served["state"] == TaskState.QUEUED.value
            assert served["title"] == "account research"
            assert served["run_ref"] == {
                "object_type": "entity_research_run",
                "object_id": str(envelope.lifecycle.run_id),
                "workspace_id": seeded.workspace_id,
            }
            assert served["counts"] == {
                "total": 3,
                "queued": 2,
                "running": 0,
                "completed": 1,
                "partial": 0,
                "needs_review": 0,
                "blocked": 0,
                "failed": 0,
            }
            # No coverage published yet: an honest null, never a zeroed progress bar.
            assert served["field_progress"] is None
            assert served["revision"] >= 1
            # C3's poller places a re-materialized card in its turn's message: the durable
            # ``turn-action:`` receipt already names the turn, so the wire says so too.
            assert served["source_turn_id"] == str(seeded.turn_id)

    run_async(scenario())


def test_a_second_settlement_raises_the_revision_the_poller_merges_on(tmp_path: Path) -> None:
    """The ledger's high-water mark, so a fresher poll always outranks the stream's snapshot."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-c2-rev", label="c2_rev")
            action_ref = derive_turn_action_ref(seeded.turn_id)
            envelope = await _launch_run(conn, seeded, action_ref=action_ref, accounts=3)
            await _settle(conn, envelope, job_index=0)
            first = (await _read(conn, seeded)).json()["tasks"][0]

            await _settle(conn, envelope, job_index=1)
            second = (await _read(conn, seeded)).json()["tasks"][0]

            assert second["revision"] > first["revision"]
            assert second["counts"]["completed"] == 2
            assert second["counts"]["queued"] == 1

    run_async(scenario())


def test_field_progress_sums_the_latest_coverage_row_of_each_settled_job(tmp_path: Path) -> None:
    """Per-account field tallies, latest-wins per job — the inside of a still-running account."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-c2-fields", label="c2_fields")
            action_ref = derive_turn_action_ref(seeded.turn_id)
            envelope = await _launch_run(conn, seeded, action_ref=action_ref, accounts=3)
            await _settle(conn, envelope, job_index=0)
            await _settle(conn, envelope, job_index=1)

            # The first job re-finalized: the earlier, thinner row must not be the one counted.
            await _coverage(
                conn,
                envelope,
                workspace_id=seeded.workspace_id,
                job_index=0,
                completed=("account.operational_pain",),
                unresolved=(),
                sequence=0,
            )
            await _coverage(
                conn,
                envelope,
                workspace_id=seeded.workspace_id,
                job_index=0,
                completed=("account.operational_pain", "account.strategic_move"),
                unresolved=("account.hiring_signal",),
                sequence=1,
            )
            await _coverage(
                conn,
                envelope,
                workspace_id=seeded.workspace_id,
                job_index=1,
                completed=("account.operational_pain",),
                unresolved=("account.tech_stack", "account.hiring_signal"),
                sequence=0,
            )

            served = (await _read(conn, seeded)).json()["tasks"][0]
            assert served["field_progress"] == {"completed": 3, "unresolved": 3}

    run_async(scenario())


def test_a_thread_that_launched_nothing_serves_an_empty_list_not_a_not_found(
    tmp_path: Path,
) -> None:
    """The card asks every thread: "no launches" is an answer, not a missing resource."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-c2-empty", label="c2_empty")
            response = await _read(conn, seeded)
            assert response.status_code == 200
            assert response.json() == {"tasks": []}

    run_async(scenario())


def test_a_submission_only_human_turn_still_links_its_launched_task(tmp_path: Path) -> None:
    """Gate answers launch before a worker creates ``agent_turn``; the submission is enough."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-c2-submit", label="c2_submit")
            turn_id = await _answering_turn(conn, seeded, label="c2_submit")
            envelope = await _launch_run(
                conn,
                seeded,
                action_ref=derive_turn_action_ref(turn_id),
                accounts=3,
            )

            response = await _read(conn, seeded)
            assert response.status_code == 200
            assert [task["part_id"] for task in response.json()["tasks"]] == [
                f"task:{envelope.lifecycle.run_id}"
            ]

    run_async(scenario())


def test_the_projections_action_ref_is_the_one_the_api_mints(tmp_path: Path) -> None:
    """The projections package may not import ``clue_api``, so the receipt prefix is spelled twice.

    That duplication is only safe while the two spellings are identical — a drifted prefix would
    make the poll silently find nothing, which reads exactly like "the fleet launched nothing".
    """

    del tmp_path
    turn_id = uuid4()
    assert _turn_action_ref(turn_id) == derive_turn_action_ref(turn_id)
    assert _turn_action_ref(str(turn_id)) == derive_turn_action_ref(turn_id)


# --- scoping ------------------------------------------------------------------------------


def test_the_route_refuses_a_thread_it_cannot_see_without_confirming_it_exists(
    tmp_path: Path,
) -> None:
    """Another workspace, another project, and no thread at all are the *same* 404."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-c2-scope-a", label="c2_scope_a")
            other = await _seed(conn, tmp_path, workspace_id="ws-c2-scope-b", label="c2_scope_b")
            action_ref = derive_turn_action_ref(seeded.turn_id)
            await _launch_run(conn, seeded, action_ref=action_ref, accounts=3)

            cross = await _read(conn, seeded, workspace_id=other.workspace_id)
            wrong_project = await _read(conn, seeded, project_id=other.project_id)
            missing = await _read(conn, seeded, thread_id="thr_c2_nope")

            for response in (cross, wrong_project, missing):
                assert response.status_code == 404
                assert response.json()["error"]["code"] == "THREAD_NOT_FOUND"

    run_async(scenario())


def test_the_route_requires_thread_read_on_the_active_membership(tmp_path: Path) -> None:
    """§3.5's floor: every request re-checks its own permission, not just surface entry."""

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-c2-perm", label="c2_perm")
            without_read = frozenset(
                permission for permission in CHAT_PERMISSIONS if permission != "thread.read"
            )
            async with _client(_app(conn, permissions=without_read)) as client:
                response = await client.get(
                    _PATH.format(project=seeded.project_id, thread=seeded.thread_id),
                    headers={"X-Workspace-Id": seeded.workspace_id},
                )
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "PERMISSION_DENIED"

    run_async(scenario())


# --- the C4 settle-advance acceptance proof (contract §11-C exit) ----------------------------


async def _transition(
    conn: Any,
    envelope: EntityResearchRunEnvelope,
    *,
    job_index: int,
    to_state: ResearchJobState,
    outcome: ResearchFinalizationOutcome | None = None,
) -> None:
    """Move one job exactly one lifecycle step, the way the fleet moves it.

    Each step is the row update, the matching ledger event (where ``revision`` comes from), and
    the fleet's own run-state refresh — so the run row, the job rows and the event ledger stay
    mutually truthful at every poll, which is the whole thing under test.
    """

    job_id = envelope.jobs[job_index].authorization.job_id
    worker = f"worker-{job_index}"
    if to_state is ResearchJobState.LEASED:
        await conn.execute(
            text(
                "UPDATE entity_research_job SET state='leased', active_worker_id=:worker, "
                " lease_generation=1, updated_at=now() WHERE job_id = :job_id"
            ),
            {"worker": worker, "job_id": job_id},
        )
        kind, from_state = EntityResearchJobEventKind.LEASED, ResearchJobState.QUEUED
        references: dict[str, Any] = {"lease_generation": 1}
    elif to_state is ResearchJobState.RUNNING:
        await conn.execute(
            text(
                "UPDATE entity_research_job SET state='running', updated_at=now() "
                "WHERE job_id = :job_id"
            ),
            {"job_id": job_id},
        )
        kind, from_state = EntityResearchJobEventKind.STARTED, ResearchJobState.LEASED
        references = {"lease_generation": 1}
    else:
        assert to_state is ResearchJobState.TERMINAL and outcome is not None
        await conn.execute(
            text(
                "UPDATE entity_research_job SET state='terminal', finalization_outcome=:outcome, "
                " finalization_receipt_ref=:receipt, terminal_at=now(), active_worker_id=NULL, "
                " updated_at=now() WHERE job_id = :job_id"
            ),
            {
                "outcome": outcome.value,
                "receipt": f"finalization-receipt:{job_id}",
                "job_id": job_id,
            },
        )
        kind, from_state = EntityResearchJobEventKind.FINALIZED, ResearchJobState.RUNNING
        references = {"finalization_receipt_ref": f"finalization-receipt:{job_id}"}
    await append_entity_research_job_event(
        conn,
        run_id=envelope.lifecycle.run_id,
        job_id=job_id,
        kind=kind,
        from_state=from_state,
        to_state=to_state,
        actor=worker,
        references=references,
    )
    await _refresh_run_state(conn, envelope.lifecycle.run_id)


def test_the_task_read_advances_truthfully_at_every_job_transition(tmp_path: Path) -> None:
    """Three jobs walked through queued → leased → running → terminal, polled at every step.

    The defect this pins against: the turn-close snapshot freezes at ``Queued — 0 of N`` while
    the fleet works on. The durable read must instead be truthful at *every* transition — the
    counts always sum to the fleet, queued only falls, settled only rises, the task state leaves
    ``queued`` the moment any job does, and the ledger revision strictly rises so the C3 merge
    can order every poll against the last.
    """

    async def scenario() -> None:
        async with rollback_conn() as conn:
            seeded = await _seed(conn, tmp_path, workspace_id="ws-c4-advance", label="c4_advance")
            action_ref = derive_turn_action_ref(seeded.turn_id)
            envelope = await _launch_run(conn, seeded, action_ref=action_ref, accounts=3)

            async def poll() -> dict[str, Any]:
                response = await _read(conn, seeded)
                assert response.status_code == 200
                (task,) = response.json()["tasks"]
                return cast("dict[str, Any]", task)

            def counts(**expected: int) -> dict[str, int]:
                base = {
                    "total": 3,
                    "queued": 0,
                    "running": 0,
                    "completed": 0,
                    "partial": 0,
                    "needs_review": 0,
                    "blocked": 0,
                    "failed": 0,
                }
                base.update(expected)
                return base

            # (transition, expected task state, expected counts) — the whole lifecycle of a
            # three-account fleet whose subjects end completed / needs_review / failed.
            steps: list[
                tuple[
                    tuple[int, ResearchJobState, ResearchFinalizationOutcome | None],
                    str,
                    dict[str, int],
                ]
            ] = [
                (
                    (0, ResearchJobState.LEASED, None),
                    "deep_research",
                    counts(queued=2, running=1),
                ),
                (
                    (0, ResearchJobState.RUNNING, None),
                    "deep_research",
                    counts(queued=2, running=1),
                ),
                (
                    (0, ResearchJobState.TERMINAL, ResearchFinalizationOutcome.COMPLETED),
                    "queued",
                    counts(queued=2, completed=1),
                ),
                (
                    (1, ResearchJobState.LEASED, None),
                    "deep_research",
                    counts(queued=1, running=1, completed=1),
                ),
                (
                    (1, ResearchJobState.RUNNING, None),
                    "deep_research",
                    counts(queued=1, running=1, completed=1),
                ),
                (
                    (1, ResearchJobState.TERMINAL, ResearchFinalizationOutcome.NEEDS_REVIEW),
                    "queued",
                    counts(queued=1, completed=1, needs_review=1),
                ),
                (
                    (2, ResearchJobState.LEASED, None),
                    "deep_research",
                    counts(running=1, completed=1, needs_review=1),
                ),
                (
                    (2, ResearchJobState.RUNNING, None),
                    "deep_research",
                    counts(running=1, completed=1, needs_review=1),
                ),
                (
                    (2, ResearchJobState.TERMINAL, ResearchFinalizationOutcome.FAILED),
                    "partial",
                    counts(completed=1, needs_review=1, failed=1),
                ),
            ]

            first = await poll()
            assert first["state"] == "queued"
            assert first["counts"] == counts(queued=3)
            previous_revision = first["revision"]
            previous_queued = 3
            previous_settled = 0

            for index, (transition, expected_state, expected_counts) in enumerate(steps):
                job_index, to_state, outcome = transition
                await _transition(
                    conn, envelope, job_index=job_index, to_state=to_state, outcome=outcome
                )
                served = await poll()
                label = f"step {index}: job {job_index} -> {to_state.value}"

                # Truthful: the exact fleet, never a guess and never a frozen snapshot.
                assert served["counts"] == expected_counts, label
                assert served["state"] == expected_state, label

                # Monotone: queued only falls, settled only rises, the fleet never shrinks.
                queued = served["counts"]["queued"]
                settled = sum(
                    served["counts"][key]
                    for key in ("completed", "partial", "needs_review", "failed")
                )
                assert queued <= previous_queued, label
                assert settled >= previous_settled, label
                assert (
                    sum(
                        served["counts"][key]
                        for key in (
                            "queued",
                            "running",
                            "blocked",
                            "completed",
                            "partial",
                            "needs_review",
                            "failed",
                        )
                    )
                    == 3
                ), label

                # Ordered: every transition appended to the ledger, so every poll outranks the
                # last — the C3 merge can never show this step's card below the previous one.
                assert served["revision"] > previous_revision, label

                # The pinned defect, verbatim: never "Queued — 0 of N" once any job left queued.
                assert not (served["state"] == "queued" and queued < 3 and settled == 0), label

                previous_revision = served["revision"]
                previous_queued = queued
                previous_settled = settled

    run_async(scenario())

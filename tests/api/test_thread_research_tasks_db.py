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
from typing import Any
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

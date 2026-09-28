"""D5 Round A acceptance tests: the design durable-job substrate.

What D5 Round A promises, and therefore what is proved here:

* **the claim CAS is a real fence** — ``queued -> running`` once; the *same* generation may
  re-claim (at-least-once redelivery must not be refused); a *higher* generation may take a
  ``running`` row over (its previous holder is gone — the point of leasing); a *lower* generation
  is refused (it has been fenced out) and does not overwrite the current holder's stamp; a
  terminal run is never re-claimed; an unknown work id is a different answer (raise) from a
  refused claim (``None``).
* **work ids round-trip** — the derivation inverts the run-id shape, the DAL stores what it
  derived, and a work id resolves back to its run across every workspace (the fleet-plane read).
* **the ingestion fleet handle** — a job can be stamped, found by work id, and have its staged
  request re-read with no status/progress side effect (what makes a requeue safe).
* **envelope validation** (offline, no DB) — the tagged union, the required tenancy anchor, and
  the frozen/extra-forbidden discipline that makes an envelope authority rather than a hint.

Enum parity for the new ``design_run_kind`` and the widened ``design_run_status`` is covered by
``test_design_schema_db.py::test_design_enum_parity`` (both are registered in
``clue_design.enums.DESIGN_PG_ENUMS``), and ``fleet_task_kind``'s new ``design_job`` label by
``tests/fleet/test_fleet_db.py::test_fleet_task_kind_enum_matches_db``. The one thing neither
covers — that the design substrate and the fleet mean the same *label* — is asserted below.

All writes run in rolled-back transactions against the session-migrated DB.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, get_args
from uuid import UUID, uuid4

import pytest
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_db import db_lifespan
from clue_design import ingestion as design_ingestion
from clue_design import runs as design_runs
from clue_design.enums import DesignIngestionKind, DesignRunKind, DesignRunStatus
from clue_design.envelopes import (
    DesignIngestionEnvelope,
    DesignJobEnvelope,
    DesignTurnEnvelope,
)
from clue_design.errors import DesignNotFoundError
from tests.design.conftest import run_async

_ENVELOPES = TypeAdapter[Any](DesignJobEnvelope)


async def _seed_ws(conn: AsyncConnection, tag: str) -> str:
    ws = f"ws_test_{tag}_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": ws}
    )
    return ws


# --- work-id derivation + round trip -----------------------------------------------------------


def test_work_id_derivation_inverts_the_shipped_run_id_shape() -> None:
    """For a server-minted id the derivation is not a hash at all: the uuid the fleet keys on is
    literally inside the run id, so an operator holding either identifier can reach the other."""
    raw = uuid4()
    assert design_runs.work_id_for_run(f"run_{raw.hex}") == raw


@pytest.mark.parametrize(
    "odd",
    ["", "run_", "runs_" + uuid4().hex, uuid4().hex, "run_not-a-uuid", "run_owned_abc123"],
)
def test_work_id_derivation_is_total_and_deterministic(odd: str) -> None:
    """Hand-made run ids exist (tests, scripts) and predate D5. They must still get a work id,
    and — the property every caller leans on — the SAME one every time, or a lookup by derived
    work id would stop finding its own run."""
    first = design_runs.work_id_for_run(odd)
    assert isinstance(first, UUID)
    assert design_runs.work_id_for_run(odd) == first


@pytest.mark.usefixtures("require_design_db")
def test_the_dal_derivation_agrees_with_the_migration_backfill() -> None:
    """The D5 migration backfills ``work_id`` in SQL and the DAL derives it in Python. If those
    two ever disagree, a backfilled row becomes unfindable by its own run id — a silent split.
    Both branches of the derivation are checked against Postgres's own evaluation of them."""

    async def scenario() -> None:
        conforming = f"run_{uuid4().hex}"
        hand_made = "run_owned_ff23f5b651a3"
        async with db_lifespan() as engine, engine.connect() as conn:
            for run_id in (conforming, hand_made):
                backfilled = (
                    await conn.execute(
                        text(
                            "SELECT CASE"
                            "  WHEN :r ~ '^run_[0-9a-f]{32}$'"
                            "    THEN CAST(substring(:r FROM 5) AS uuid)"
                            "  ELSE CAST(md5(:r) AS uuid) END"
                        ),
                        {"r": run_id},
                    )
                ).scalar_one()
                assert UUID(str(backfilled)) == design_runs.work_id_for_run(run_id), run_id

    run_async(scenario())


def test_distinct_run_ids_derive_distinct_work_ids() -> None:
    """The fallback must not collapse ids: ``design_agent_run_work_id_unique`` would reject the
    second run, which would look like a mysterious insert failure rather than an id collision."""
    ids = ["run_owned_a", "run_owned_b", "run_" + uuid4().hex, "run_" + uuid4().hex]
    assert len({design_runs.work_id_for_run(i) for i in ids}) == len(ids)


@pytest.mark.usefixtures("require_design_db")
def test_created_run_is_queued_and_carries_its_durable_job_columns() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws = await _seed_ws(conn, "d5born")
                run_id = f"run_{uuid4().hex}"
                envelope = {"prompt": "Make it pop", "target_node_ids": ["hero"]}

                created = await design_runs.create_run(
                    conn,
                    workspace_id=ws,
                    run_id=run_id,
                    document_id=None,
                    kind=DesignRunKind.WEB_TURN,
                    payload=envelope,
                )
                assert created["status"] == DesignRunStatus.QUEUED

                job = await design_runs.get_run_by_work_id(
                    conn, work_id=design_runs.work_id_for_run(run_id)
                )
                assert job is not None
                # The stored work id is exactly the derived one — no second identifier exists.
                assert job["work_id"] == str(design_runs.work_id_for_run(run_id))
                # The D5 ruling: the checkpoint thread IS the run, so a resume resumes the same
                # graph rather than opening a second one beside it.
                assert job["checkpoint_thread_id"] == run_id
                assert job["kind"] == DesignRunKind.WEB_TURN
                # The envelope is stored by value, verbatim.
                assert job["payload"] == envelope
                # The fleet-plane read carries the owner so the caller can continue in a
                # workspace-CORRECT store.
                assert job["workspace_id"] == ws
                # Unclaimed: no lease stamp yet.
                assert (job["leased_by"], job["lease_generation"], job["leased_at"]) == (
                    None,
                    None,
                    None,
                )
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_default_kind_and_payload_keep_pre_d5_callers_working() -> None:
    """Round B switches the API over to passing both explicitly; until then the defaults must
    make the shipped two-argument call site produce a valid durable-job row."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws = await _seed_ws(conn, "d5default")
                run_id = f"run_{uuid4().hex}"
                await design_runs.create_run(conn, workspace_id=ws, run_id=run_id, document_id=None)
                job = await design_runs.get_run_by_work_id(
                    conn, work_id=design_runs.work_id_for_run(run_id)
                )
                assert job is not None
                assert job["kind"] == DesignRunKind.AGENT_TURN
                assert job["payload"] == {}
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_get_run_by_work_id_is_none_for_an_unknown_work_id() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                assert await design_runs.get_run_by_work_id(conn, work_id=uuid4()) is None
            finally:
                await trans.rollback()

    run_async(scenario())


# --- the claim CAS -----------------------------------------------------------------------------


@pytest.mark.usefixtures("require_design_db")
def test_claim_moves_a_queued_run_to_running_and_stamps_the_lease() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws = await _seed_ws(conn, "d5claim")
                run_id = f"run_{uuid4().hex}"
                await design_runs.create_run(conn, workspace_id=ws, run_id=run_id, document_id=None)
                work_id = design_runs.work_id_for_run(run_id)

                claimed = await design_runs.claim_run_for_execution(
                    conn, work_id=work_id, worker_id="worker-a", lease_generation=1
                )
                assert claimed is not None
                assert claimed["status"] == DesignRunStatus.RUNNING
                assert claimed["leased_by"] == "worker-a"
                assert claimed["lease_generation"] == 1
                assert isinstance(claimed["leased_at"], str)
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_the_same_generation_may_re_claim_idempotently() -> None:
    """At-least-once delivery is the fleet's contract: a worker that already holds the lease and
    sees the task again must be allowed to proceed, not refused into a stall."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws = await _seed_ws(conn, "d5same")
                run_id = f"run_{uuid4().hex}"
                await design_runs.create_run(conn, workspace_id=ws, run_id=run_id, document_id=None)
                work_id = design_runs.work_id_for_run(run_id)

                first = await design_runs.claim_run_for_execution(
                    conn, work_id=work_id, worker_id="worker-a", lease_generation=3
                )
                again = await design_runs.claim_run_for_execution(
                    conn, work_id=work_id, worker_id="worker-a", lease_generation=3
                )
                assert first is not None and again is not None
                assert again["status"] == DesignRunStatus.RUNNING
                assert again["lease_generation"] == 3
                assert again["leased_by"] == "worker-a"
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_a_higher_generation_takes_over_a_running_run() -> None:
    """A ``running`` row whose generation is below the claimant's means the previous holder is
    gone — generations are issued monotonically, so a newer one is proof the old lease expired.
    Refusing here would strand exactly the runs D5 exists to rescue."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws = await _seed_ws(conn, "d5takeover")
                run_id = f"run_{uuid4().hex}"
                await design_runs.create_run(conn, workspace_id=ws, run_id=run_id, document_id=None)
                work_id = design_runs.work_id_for_run(run_id)

                await design_runs.claim_run_for_execution(
                    conn, work_id=work_id, worker_id="dead-worker", lease_generation=1
                )
                taken = await design_runs.claim_run_for_execution(
                    conn, work_id=work_id, worker_id="fresh-worker", lease_generation=2
                )
                assert taken is not None
                assert taken["leased_by"] == "fresh-worker"
                assert taken["lease_generation"] == 2
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_a_lower_generation_is_refused_and_changes_nothing() -> None:
    """The fenced-out worker must stop. It gets ``None`` — and, just as important, it must not
    have overwritten the live holder's stamp on the way to being told no."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws = await _seed_ws(conn, "d5fenced")
                run_id = f"run_{uuid4().hex}"
                await design_runs.create_run(conn, workspace_id=ws, run_id=run_id, document_id=None)
                work_id = design_runs.work_id_for_run(run_id)

                await design_runs.claim_run_for_execution(
                    conn, work_id=work_id, worker_id="current", lease_generation=5
                )
                refused = await design_runs.claim_run_for_execution(
                    conn, work_id=work_id, worker_id="zombie", lease_generation=4
                )
                assert refused is None

                unchanged = await design_runs.get_run_by_work_id(conn, work_id=work_id)
                assert unchanged is not None
                assert unchanged["leased_by"] == "current"
                assert unchanged["lease_generation"] == 5
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_a_terminal_run_is_never_re_claimed() -> None:
    """Finished work is not restarted by a takeover, however high the generation."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws = await _seed_ws(conn, "d5terminal")
                run_id = f"run_{uuid4().hex}"
                await design_runs.create_run(conn, workspace_id=ws, run_id=run_id, document_id=None)
                work_id = design_runs.work_id_for_run(run_id)
                await design_runs.claim_run_for_execution(
                    conn, work_id=work_id, worker_id="worker-a", lease_generation=1
                )
                await design_runs.set_run_result(
                    conn,
                    workspace_id=ws,
                    run_id=run_id,
                    status=DesignRunStatus.SUCCEEDED,
                    result={"status": "applied"},
                )

                assert (
                    await design_runs.claim_run_for_execution(
                        conn, work_id=work_id, worker_id="worker-b", lease_generation=99
                    )
                ) is None
            finally:
                await trans.rollback()

    run_async(scenario())


@pytest.mark.usefixtures("require_design_db")
def test_an_unknown_work_id_raises_rather_than_reporting_a_refusal() -> None:
    """A worker must be able to tell "someone else owns this" from "this job does not exist" —
    the first is a stop, the second is a poison task."""

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                with pytest.raises(DesignNotFoundError):
                    await design_runs.claim_run_for_execution(
                        conn, work_id=uuid4(), worker_id="worker-a", lease_generation=1
                    )
            finally:
                await trans.rollback()

    run_async(scenario())


# --- the derived open question (spec 2026-09-20) -------------------------------------------------


@pytest.mark.usefixtures("require_design_db")
def test_latest_terminal_run_for_document_reads_the_newest_terminal_envelope() -> None:
    """ "This document has an open question" is DERIVED from its latest terminal run, never
    stored — so the read must pick the newest terminal run by time (not by run id, and not the
    ``running`` one that has not said anything yet), and must key on the frozen envelope's
    ``document_id`` rather than the nullable column.

    The older run deliberately carries the lexicographically GREATER run id, so the query's
    ``run_id DESC`` tiebreak cannot produce the right answer by accident.
    """

    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws = await _seed_ws(conn, "openq")
                document_id = f"doc_{uuid4().hex}"

                async def seed(run_id: str, *, status: str, result: Any, at: datetime) -> None:
                    await design_runs.create_run(
                        conn,
                        workspace_id=ws,
                        run_id=run_id,
                        document_id=None,
                        kind=DesignRunKind.AGENT_TURN,
                        payload={"document_id": document_id, "prompt": "Make the ad"},
                    )
                    await design_runs.set_run_result(
                        conn, workspace_id=ws, run_id=run_id, status=status, result=result
                    )
                    # ``now()`` is transaction-fixed in Postgres, so every row in this test would
                    # otherwise share one ``created_at``; the read's ORDER BY needs real recency.
                    await conn.execute(
                        text(
                            "UPDATE design_agent_run SET created_at = :at"
                            " WHERE run_id = :r AND workspace_id = :w"
                        ),
                        {"at": at, "r": run_id, "w": ws},
                    )

                await seed(
                    "run_zzz_older",
                    status="succeeded",
                    result={"status": "proposed", "acceptance_scope": "design"},
                    at=datetime(2026, 9, 19, 10, tzinfo=UTC),
                )
                await seed(
                    "run_aaa_newer",
                    status="succeeded",
                    result={
                        "status": "clarification_requested",
                        "clarification": {"questions": [{"question": "Which proof point?"}]},
                    },
                    at=datetime(2026, 9, 19, 11, tzinfo=UTC),
                )
                await seed(
                    "run_mmm_running",
                    status="running",
                    result=None,
                    at=datetime(2026, 9, 19, 12, tzinfo=UTC),
                )

                latest = await design_runs.latest_terminal_run_for_document(
                    conn, workspace_id=ws, document_id=document_id
                )
                assert latest is not None
                assert latest["run_id"] == "run_aaa_newer"
                assert latest["status"] == DesignRunStatus.SUCCEEDED
                # Shaped exactly like ``get_run`` — the caller reads ``result`` the same way.
                assert latest == await design_runs.get_run(
                    conn, workspace_id=ws, run_id="run_aaa_newer"
                )
                assert (latest["result"] or {})["status"] == "clarification_requested"

                # A document nobody has run is honestly silent, not an open question.
                assert (
                    await design_runs.latest_terminal_run_for_document(
                        conn, workspace_id=ws, document_id=f"doc_{uuid4().hex}"
                    )
                    is None
                )
            finally:
                await trans.rollback()

    run_async(scenario())


# --- ingestion's fleet handle -------------------------------------------------------------------


@pytest.mark.usefixtures("require_design_db")
def test_ingestion_work_id_stamp_and_requeue_safe_request_read() -> None:
    async def scenario() -> None:
        async with db_lifespan() as engine, engine.connect() as conn:
            trans = await conn.begin()
            try:
                ws = await _seed_ws(conn, "d5ingest")
                request = {"url": "https://example.com", "staged": {"sha256": "a" * 64}}
                job = await design_ingestion.create_job(
                    conn,
                    workspace_id=ws,
                    kind=DesignIngestionKind.WEBSITE,
                    request=request,
                )
                job_id = job["job_id"]
                # Nullable by design: a job exists before anything is enqueued.
                assert (await design_ingestion.get_job_by_work_id(conn, work_id=uuid4())) is None

                work_id = uuid4()
                stamped = await design_ingestion.set_work_id(
                    conn, workspace_id=ws, job_id=job_id, work_id=work_id
                )
                assert stamped["job_id"] == job_id
                # Idempotent for the same value.
                await design_ingestion.set_work_id(
                    conn, workspace_id=ws, job_id=job_id, work_id=work_id
                )

                found = await design_ingestion.get_job_by_work_id(conn, work_id=work_id)
                assert found is not None
                assert found["job_id"] == job_id
                assert found["workspace_id"] == ws
                assert found["work_id"] == str(work_id)

                # The requeue-safe read: same inputs, no side effect on the job's progress.
                before = await design_ingestion.require_job(conn, workspace_id=ws, job_id=job_id)
                staged = await design_ingestion.read_staged_request(
                    conn, workspace_id=ws, job_id=job_id
                )
                assert staged == request
                after = await design_ingestion.require_job(conn, workspace_id=ws, job_id=job_id)
                assert (after["status"], after["progress"], after["stage"]) == (
                    before["status"],
                    before["progress"],
                    before["stage"],
                )
                assert after["updated_at"] == before["updated_at"]

                # Fail-closed: another tenant cannot read the staged inputs.
                other = await _seed_ws(conn, "d5ingestother")
                with pytest.raises(DesignNotFoundError):
                    await design_ingestion.read_staged_request(
                        conn, workspace_id=other, job_id=job_id
                    )
            finally:
                await trans.rollback()

    run_async(scenario())


# --- the fleet label the two packages must agree on ---------------------------------------------


def test_the_design_fleet_kind_label_is_the_one_the_fleet_registers() -> None:
    """``clue_design`` may not import ``clue_fleet`` (Rule S4), so the shared string is checked
    here — in the test layer, which may see both — rather than by a runtime coupling."""
    from clue_fleet.enums import FleetTaskKind

    assert FleetTaskKind.DESIGN_JOB.value == "design_job"


# --- envelopes (offline) -------------------------------------------------------------------------


@pytest.mark.parametrize("kind", ["agent_turn", "web_turn"])
def test_turn_envelopes_parse_through_the_tagged_union(kind: str) -> None:
    work_id = uuid4()
    envelope = _ENVELOPES.validate_python(
        {
            "kind": kind,
            "work_id": str(work_id),
            "workspace_id": "ws_alpha",
            "run_id": "run_" + "0" * 32,
            "checkpoint_thread_id": "run_" + "0" * 32,
            "config": {"brand_kit": {"id": "bk_1"}, "target_node_ids": ["hero"]},
        }
    )
    assert isinstance(envelope, DesignTurnEnvelope)
    assert envelope.kind == kind
    assert envelope.work_id == work_id
    # config is carried verbatim; the substrate does not schema the runtime's context bag.
    assert envelope.config["brand_kit"] == {"id": "bk_1"}


def test_the_turn_envelope_tags_are_exactly_the_design_run_kinds() -> None:
    """The envelope's ``kind`` tags and the ``design_run_kind`` column vocabulary are written in
    two places (the wire contract and the enum). This is the guard that keeps them equal — a tag
    the column cannot store, or a kind no envelope can carry, would be an undispatchable run."""
    tags = get_args(DesignTurnEnvelope.model_fields["kind"].annotation)
    assert set(tags) == {member.value for member in DesignRunKind}


def test_the_ingestion_envelope_is_the_other_arm_of_the_union() -> None:
    envelope = _ENVELOPES.validate_python(
        {
            "kind": "ingestion",
            "work_id": str(uuid4()),
            "workspace_id": "ws_alpha",
            "job_id": "ingest_" + "0" * 32,
            "ingestion_kind": "pdf",
        }
    )
    assert isinstance(envelope, DesignIngestionEnvelope)
    assert envelope.ingestion_kind is DesignIngestionKind.PDF
    assert envelope.config == {}


def test_an_envelope_without_a_usable_workspace_is_refused() -> None:
    """The tenancy anchor is the one thing the platform must be able to trust in an envelope: a
    design job with no workspace is unexecutable, and the D2.5A seam refuses what it cannot
    scope."""
    base: dict[str, Any] = {
        "kind": "agent_turn",
        "work_id": str(uuid4()),
        "run_id": "run_x",
        "checkpoint_thread_id": "run_x",
    }
    with pytest.raises(ValidationError):
        _ENVELOPES.validate_python(base)
    with pytest.raises(ValidationError):
        _ENVELOPES.validate_python({**base, "workspace_id": ""})


def test_an_unknown_kind_and_an_unknown_field_are_both_refused() -> None:
    """``extra="forbid"`` is what keeps ``config`` the only unstructured channel: a misspelled
    field cannot quietly become context the worker never reads."""
    good: dict[str, Any] = {
        "kind": "agent_turn",
        "work_id": str(uuid4()),
        "workspace_id": "ws_alpha",
        "run_id": "run_x",
        "checkpoint_thread_id": "run_x",
    }
    with pytest.raises(ValidationError):
        _ENVELOPES.validate_python({**good, "kind": "ingestion_turn"})
    with pytest.raises(ValidationError):
        _ENVELOPES.validate_python({**good, "targt_node_ids": ["hero"]})


def test_the_turn_project_id_is_optional_and_round_trips() -> None:
    """Lane 3 slice 5 (T3-1): the turn's project rides the envelope so the design side's spend
    scope can stamp it onto every ledger row. Optional because the model is ``extra="forbid"`` —
    an envelope frozen before the field existed must still replay verbatim."""
    base: dict[str, Any] = {
        "kind": "agent_turn",
        "work_id": str(uuid4()),
        "workspace_id": "ws_alpha",
        "run_id": "run_x",
        "checkpoint_thread_id": "run_x",
    }
    assert _ENVELOPES.validate_python(base).project_id is None
    stamped = _ENVELOPES.validate_python({**base, "project_id": "project-7"})
    assert stamped.project_id == "project-7"
    assert _ENVELOPES.validate_python(stamped.model_dump(mode="json")) == stamped


def test_an_envelope_is_frozen() -> None:
    """The envelope is the job's immutable authority — a worker that could edit it in flight
    would make a takeover replay something other than the enqueued work."""
    envelope = DesignTurnEnvelope(
        kind="agent_turn",
        work_id=uuid4(),
        workspace_id="ws_alpha",
        run_id="run_x",
        checkpoint_thread_id="run_x",
    )
    with pytest.raises(ValidationError):
        envelope.workspace_id = "ws_beta"  # type: ignore[misc]


def test_a_work_id_round_trips_through_the_envelope() -> None:
    """The envelope and the design row must be re-joinable without trusting the queue."""
    run_id = f"run_{uuid4().hex}"
    work_id = design_runs.work_id_for_run(run_id)
    envelope = DesignTurnEnvelope(
        kind="agent_turn",
        work_id=work_id,
        workspace_id="ws_alpha",
        run_id=run_id,
        checkpoint_thread_id=run_id,
    )
    reparsed = _ENVELOPES.validate_python(envelope.model_dump(mode="json"))
    assert reparsed == envelope
    assert isinstance(reparsed.work_id, UUID)
    assert design_runs.work_id_for_run(reparsed.run_id) == work_id

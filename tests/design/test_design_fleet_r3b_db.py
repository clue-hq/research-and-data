"""R3-B acceptance: a worker claims only what it can run, and a dead task never orphans a job.

The W5 Apollo acceptance walk caught one defect with two independent halves, and this file pins
both against the database they actually happen in.

**What went wrong.** A detached design fleet worker that had been running since before the lane
merged — ``LUMEN_BRAND_AD_ASSETS`` unset, no knowledge of the ``ad_assets`` ingestion kind at all
— claimed an ``ad_assets`` ingestion task 0.5s after it was enqueued and failed it immediately.
The fleet task went ``FAILED``; the owning ``design_ingestion_job`` row stayed ``queued`` with
``error_json`` NULL, and was still sitting there nine minutes later. Because the embedded worker
and the detached worker race for every ``design_job`` task, whether lane onboarding worked at all
came down to who won the claim.

**The two halves, and where each is proven here.**

1. *Capability-gated claims.* A worker may only claim payloads it can execute. The gate is a
   predicate inside the claim statement, so an unsupported task is never claimed — it keeps its
   place in the queue for a capable worker. Proven at the SQL seam (:func:`claim_next_task`) and
   at the design handler's declaration.
2. *Job/task reconciliation.* The exact gap that left the row ``queued``: the handler's preamble
   — parsing the envelope, checking the work id, the claim read itself — runs BEFORE the claim
   CAS moves the row out of ``queued``, and a raise there escaped into
   ``LeasedWorkWorker._run_task``, whose ``except Exception`` is fleet-plane only. It marked the
   TASK failed and never touched the design row, which no sweep could see either because the
   reaper only looked at ``running`` rows. Both layers are proven: the handler now terminalizes
   the row synchronously, and the reaper sweeps ``queued`` orphans as a backstop.

The tests drive the DAL / handler / reaper seams directly rather than over HTTP: what needs
proving is the claim and recovery machinery, and the route's own contribution (offer job + task
in one transaction) is asserted end to end in the design API suite.
"""

from __future__ import annotations

import asyncio
from typing import Any
from uuid import UUID, uuid4

import pytest
from lumen_api import run_stream
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_core import ProjectRunId
from clue_db import db_lifespan, transaction
from clue_design import ingestion as design_ingestion
from clue_design import runs as design_runs
from clue_design.enums import DesignIngestionKind, DesignRunKind
from clue_design.envelopes import DesignIngestionEnvelope, DesignTurnEnvelope
from clue_fleet.enums import FleetTaskKind, FleetTaskStatus
from clue_fleet.queue import TaskCapability, claim_next_task, enqueue_task
from clue_fleet.work_worker import WorkContext

pytestmark = pytest.mark.usefixtures("require_design_db")

#: Every ingestion lane a current build knows, minus the flagged one — i.e. exactly what a worker
#: with ``LUMEN_BRAND_AD_ASSETS`` off declares, and a superset of what the stale worker knew.
_WITHOUT_AD_ASSETS = frozenset({"website", "pdf", "asset_upload"})
_WITH_AD_ASSETS = _WITHOUT_AD_ASSETS | {"ad_assets"}


def _ingestion_capability(supported: frozenset[str]) -> tuple[TaskCapability, ...]:
    return (TaskCapability(field="ingestion_kind", supported=supported),)


# --- seeds and probes --------------------------------------------------------------------------


async def _seed_workspace(conn: AsyncConnection, tag: str) -> str:
    workspace_id = f"ws_test_{tag}_{uuid4().hex[:10]}"
    await conn.execute(
        text("INSERT INTO workspace (workspace_id, name) VALUES (:w, :w)"), {"w": workspace_id}
    )
    return workspace_id


async def _offer_ingestion(
    workspace_id: str,
    kind: DesignIngestionKind,
    *,
    envelope_kind_override: str | None = None,
) -> tuple[str, UUID]:
    """The ingestion route's one transaction, in miniature: a queued job plus its task.

    ``envelope_kind_override`` rewrites the ``ingestion_kind`` on the enqueued ENVELOPE only,
    leaving the design row a perfectly ordinary job. That is how a stale worker's world is
    reproduced honestly: nothing is wrong with the row — what the worker cannot cope with is the
    envelope riding its task, which names a lane its ``DesignIngestionKind`` has no member for.
    """
    job_id = design_ingestion.new_id("ingest")
    work_id = uuid4()
    envelope: dict[str, Any] = DesignIngestionEnvelope(
        work_id=work_id,
        workspace_id=workspace_id,
        kind="ingestion",
        job_id=job_id,
        ingestion_kind=kind,
    ).model_dump(mode="json")
    if envelope_kind_override is not None:
        envelope["ingestion_kind"] = envelope_kind_override
    async with transaction() as conn:
        await design_ingestion.create_job(
            conn,
            workspace_id=workspace_id,
            kind=kind.value,
            request={"url": "https://example.test"},
            job_id=job_id,
            work_id=work_id,
        )
        await enqueue_task(
            conn,
            kind=FleetTaskKind.DESIGN_JOB,
            project_run_id=ProjectRunId(work_id),
            dedup_key=str(work_id),
            payload=envelope,
        )
    return job_id, work_id


async def _task_payload(work_id: UUID) -> dict[str, Any]:
    """The envelope a worker would actually be handed for this work id."""
    async with transaction() as conn:
        row = (
            await conn.execute(
                text("SELECT payload_json FROM fleet_task WHERE work_id = :w"), {"w": work_id}
            )
        ).one()
    payload = row.payload_json
    return payload if isinstance(payload, dict) else {}


async def _offer_turn(workspace_id: str) -> tuple[str, UUID]:
    run_id = f"run_{uuid4().hex}"
    work_id = design_runs.work_id_for_run(run_id)
    envelope = DesignTurnEnvelope(
        work_id=work_id,
        workspace_id=workspace_id,
        kind="agent_turn",
        run_id=run_id,
        checkpoint_thread_id=run_id,
        document_id=None,
        config={
            "request": {
                "prompt": "hello",
                "scene": {"id": "scene_t", "schema_version": 1, "pages": [], "assets": {}},
                "diagnostics": [],
            },
            "reference_assets": None,
        },
    ).model_dump(mode="json")
    async with transaction() as conn:
        await design_runs.create_run(
            conn,
            workspace_id=workspace_id,
            run_id=run_id,
            document_id=None,
            kind=DesignRunKind.AGENT_TURN,
            payload=envelope,
            work_id=work_id,
        )
        await enqueue_task(
            conn,
            kind=FleetTaskKind.DESIGN_JOB,
            project_run_id=ProjectRunId(work_id),
            dedup_key=str(work_id),
            payload=envelope,
        )
    return run_id, work_id


async def _read_job(workspace_id: str, job_id: str) -> dict[str, Any]:
    async with transaction() as conn:
        job = await design_ingestion.require_job(conn, workspace_id=workspace_id, job_id=job_id)
    return job


async def _read_run(workspace_id: str, run_id: str) -> dict[str, Any]:
    async with transaction() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status, result_json FROM design_agent_run"
                    " WHERE run_id = :r AND workspace_id = :w"
                ),
                {"r": run_id, "w": workspace_id},
            )
        ).one()
    return {"status": row.status, "result": row.result_json}


async def _task_status(work_id: UUID) -> str | None:
    async with transaction() as conn:
        row = (
            await conn.execute(
                text(
                    "SELECT status FROM fleet_task WHERE work_id = :w"
                    " AND kind = CAST(:k AS fleet_task_kind) ORDER BY enqueue_seq DESC LIMIT 1"
                ),
                {"w": work_id, "k": FleetTaskKind.DESIGN_JOB.value},
            )
        ).first()
    return None if row is None else row.status


async def _force_task_status(work_id: UUID, status: FleetTaskStatus) -> None:
    """Put this work id's task into ``status`` directly — the reaper's INPUT is what is tested."""
    claimed = status is FleetTaskStatus.CLAIMED
    async with transaction() as conn:
        await conn.execute(
            text(
                "UPDATE fleet_task SET status = CAST(:s AS fleet_task_status),"
                " claimed_by = CASE WHEN :claimed THEN 'worker-holder' ELSE NULL END,"
                " claimed_at = CASE WHEN :claimed THEN now() ELSE NULL END"
                " WHERE work_id = :w AND kind = CAST(:k AS fleet_task_kind)"
            ),
            {
                "s": status.value,
                "claimed": claimed,
                "w": work_id,
                "k": FleetTaskKind.DESIGN_JOB.value,
            },
        )


async def _purge_work(*work_ids: UUID) -> None:
    """Erase every trace of this test's work — the suite shares one database and one reaper.

    The same hazard ``test_design_fleet_reaper_db`` documents: a leftover ``queued`` design task
    is handed to the next test's worker, and a leftover non-terminal design row is *orphaned
    work* to the next test's reaper pass.
    """
    async with transaction() as conn:
        for work_id in work_ids:
            await conn.execute(text("DELETE FROM fleet_task WHERE work_id = :w"), {"w": work_id})
            await conn.execute(text("DELETE FROM work_lease WHERE work_id = :w"), {"w": work_id})
            await conn.execute(
                text("DELETE FROM design_agent_run WHERE work_id = :w"), {"w": work_id}
            )
            await conn.execute(
                text("DELETE FROM design_ingestion_job WHERE work_id = :w"), {"w": work_id}
            )


def _context(work_id: UUID, *, generation: int = 1, payload: dict[str, Any]) -> WorkContext:
    from clue_fleet.lease import LeaseGeneration, WorkId

    return WorkContext(
        task_id=uuid4(),
        work_id=WorkId(work_id),
        worker_id="worker:r3b",
        lease_generation=LeaseGeneration(generation),
        payload=payload,
        stop_requested=asyncio.Event(),
        lease_lost=asyncio.Event(),
    )


# --- 1. capability-gated claims, at the claim statement ----------------------------------------


async def _claim(work_id: UUID, worker_id: str, supported: frozenset[str] | None) -> Any:
    """Claim THIS work id's task, as ``worker_id`` would.

    Narrowed to one work id deliberately: ``fleet_task`` is one table for the whole suite, so an
    unnarrowed claim would be answered by whichever sibling test's row happens to sort first —
    the documented "cross-test queue bleed" hazard. Narrowing changes nothing about the
    capability predicate under test; it only removes the other tests from the candidate set.

    ``supported=None`` declares no capability at all (the historical claim).
    """
    async with transaction() as conn:
        return await claim_next_task(
            conn,
            kind=FleetTaskKind.DESIGN_JOB,
            worker_id=worker_id,
            project_run_id=ProjectRunId(work_id),
            capabilities=() if supported is None else _ingestion_capability(supported),
        )


def test_the_claim_statement_hides_a_lane_this_worker_cannot_run() -> None:
    """The R3-B claim race, decided in SQL.

    The stale worker is not merely deprioritised on the ``ad_assets`` row — the row is *invisible*
    to it, which is the only answer that stops the race. It is not skipped for being busy, not
    claimed-then-requeued (a requeue would just be re-claimed next pass): the claim statement
    never selects it, so the row keeps its status, its place and its untouched attempt count for
    a capable worker.

    Nothing else about the worker is broken by the gate: the same claim, same worker, same
    capabilities takes the ``website`` row it CAN run.
    """

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "claimgate")
            ad_job, ad_work = await _offer_ingestion(workspace_id, DesignIngestionKind.AD_ASSETS)
            _, web_work = await _offer_ingestion(workspace_id, DesignIngestionKind.WEBSITE)

            refused = await _claim(ad_work, "worker:stale", _WITHOUT_AD_ASSETS)
            assert refused is None, "the incapable worker claimed the ad_assets row"

            allowed = await _claim(web_work, "worker:stale", _WITHOUT_AD_ASSETS)
            assert allowed is not None, "the gate must narrow one lane, not disable the worker"
            assert allowed.project_run_id == web_work

            # Untouched: still queued, never attempted — so a capable worker inherits it whole.
            async with transaction() as conn:
                row = (
                    await conn.execute(
                        text("SELECT status, attempts FROM fleet_task WHERE work_id = :w"),
                        {"w": ad_work},
                    )
                ).one()
            assert (row.status, row.attempts) == (FleetTaskStatus.QUEUED.value, 0)
            assert (await _read_job(workspace_id, ad_job))["status"] == "queued"

            capable = await _claim(ad_work, "worker:capable", _WITH_AD_ASSETS)
            assert capable is not None and capable.project_run_id == ad_work

            await _purge_work(ad_work, web_work)

    asyncio.run(scenario())


def test_a_turn_task_is_claimable_by_every_worker_whatever_its_ingestion_capability() -> None:
    """One fleet kind, two payload shapes. A turn envelope carries no ``ingestion_kind``, so the
    ingestion constraint does not apply to it — a worker with NO runnable ingestion lane at all
    still drains every design turn."""

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "turnclaim")
            _, work_id = await _offer_turn(workspace_id)

            claimed = await _claim(work_id, "worker:no-ingestion", frozenset())
            assert claimed is not None and claimed.project_run_id == work_id

            await _purge_work(work_id)

    asyncio.run(scenario())


def test_no_declared_capability_claims_everything_exactly_as_before() -> None:
    """The default is the historical statement, unchanged: an empty capability list filters
    nothing, so every handler that owns its whole kind is unaffected by this mechanism."""

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "nocaps")
            _, work_id = await _offer_ingestion(workspace_id, DesignIngestionKind.AD_ASSETS)

            claimed = await _claim(work_id, "worker:ungated", None)
            assert claimed is not None and claimed.project_run_id == work_id

            await _purge_work(work_id)

    asyncio.run(scenario())


def test_the_design_handler_declares_the_ad_assets_lane_only_when_its_flag_is_on(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The declaration side of the gate: support = "the build knows the lane AND its flag is on".

    Read live rather than cached at construction, so one handler answers for the configuration
    it would actually execute under — which is what makes the ``LUMEN_BRAND_AD_ASSETS``-unset
    worker in the R3-B report unable to claim the lane at all.
    """
    from lumen_api.fleet_handler import build_design_job_handler
    from py_lumen_config import settings

    handler = build_design_job_handler(checkpointer_factory=None, ingestion_only=True)

    monkeypatch.setattr(settings, "lumen_brand_ad_assets", False, raising=False)
    off = tuple(cap for cap in handler.task_capabilities if cap.field == "ingestion_kind")
    assert len(off) == 1
    assert off[0].field == "ingestion_kind"
    assert "ad_assets" not in off[0].supported
    # Every unflagged lane the build knows is still supported — this narrows one lane, not all.
    assert off[0].supported == frozenset(
        kind.value for kind in DesignIngestionKind if kind is not DesignIngestionKind.AD_ASSETS
    )

    monkeypatch.setattr(settings, "lumen_brand_ad_assets", True, raising=False)
    on = tuple(cap for cap in handler.task_capabilities if cap.field == "ingestion_kind")
    assert on[0].supported == frozenset(kind.value for kind in DesignIngestionKind)


# --- 2a. synchronous reconciliation: the preamble can no longer orphan a row --------------------


def test_a_preamble_failure_fails_the_job_row_instead_of_leaving_it_queued() -> None:
    """The exact R3-B shape, reproduced and repaired.

    The task carries an envelope this build cannot parse — the stale worker's world, where the
    payload names an ``ingestion_kind`` its ``DesignIngestionKind`` has no member for. That parse
    is the FIRST thing the handler does, before the claim CAS, so before the fix the raise
    escaped into the fleet-plane ``except Exception``: the task went FAILED with
    ``{"outcome": "error"}`` and the job row stayed ``queued`` with ``error_json`` NULL forever.

    Now the handler contains it: the job is ``failed``, its error names the preamble, and the
    handler reports an honest outcome instead of raising.
    """
    from lumen_api.fleet_handler import build_design_job_handler

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "preamble")
            job_id, work_id = await _offer_ingestion(
                workspace_id,
                DesignIngestionKind.WEBSITE,
                # A lane no member of this build's enum names — an envelope from the future.
                envelope_kind_override="lane_this_build_never_heard_of",
            )

            handler = build_design_job_handler(checkpointer_factory=None, ingestion_only=True)
            # The RED case: before the fix this call RAISED (the parse is the first thing
            # ``handle`` does), the fleet's generic ``except`` marked the task failed, and the
            # job below stayed ``queued`` with a NULL error forever.
            result = await handler.handle(_context(work_id, payload=await _task_payload(work_id)))

            assert result.outcome == "preamble_error"
            assert result.references["reconciliation"] == "job_failed"
            assert not result.requeue

            job = await _read_job(workspace_id, job_id)
            assert job["status"] == "failed", "the job row must not be left queued"
            assert job["error"] is not None, "error_json must not be NULL"
            assert job["error"]["code"] == "design_job.preamble_error"
            assert "not a valid design job envelope" in job["error"]["message"]

            await _purge_work(work_id)

    asyncio.run(scenario())


def test_a_preamble_failure_is_refused_when_a_newer_generation_owns_the_job() -> None:
    """A worker that could not run the job must not stamp ``failed`` over a capable takeover.

    The reconciliation carries the claim CAS's own fence predicate, so a lower generation is
    refused and says so (``job_refused``) rather than clobbering the live attempt.
    """
    from lumen_api.fleet_handler import build_design_job_handler

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "fenced")
            job_id, work_id = await _offer_ingestion(workspace_id, DesignIngestionKind.WEBSITE)

            # A capable worker has already taken it under generation 5.
            async with transaction() as conn:
                claimed = await design_ingestion.claim_job_for_execution(
                    conn, work_id=work_id, worker_id="worker:capable", lease_generation=5
                )
            assert claimed is not None

            handler = build_design_job_handler(checkpointer_factory=None, ingestion_only=True)
            result = await handler.handle(
                _context(work_id, generation=1, payload={"not": "an envelope"})
            )

            assert result.outcome == "preamble_error"
            assert result.references["reconciliation"] == "job_refused"
            job = await _read_job(workspace_id, job_id)
            assert job["status"] == "running", "the takeover's live attempt must stand"
            assert job["error"] is None

            await _purge_work(work_id)

    asyncio.run(scenario())


def test_a_preamble_failure_on_an_unknown_work_id_invents_nothing() -> None:
    """A poison task naming no design row is reported as such and finished, never requeued."""
    from lumen_api.fleet_handler import build_design_job_handler

    async def scenario() -> None:
        async with db_lifespan():
            handler = build_design_job_handler(checkpointer_factory=None, ingestion_only=True)
            result = await handler.handle(_context(uuid4(), payload={"not": "an envelope"}))
            assert result.outcome == "preamble_error"
            assert result.references["reconciliation"] == "unknown_work"
            assert not result.requeue

    asyncio.run(scenario())


# --- 2b. the sweep: a pre-existing orphan is reconciled -----------------------------------------


def test_the_reaper_fails_a_queued_job_whose_task_died() -> None:
    """The backstop, on a row the synchronous containment never saw.

    This is literally the state the acceptance walk found: job ``queued``, ``error_json`` NULL,
    fleet task ``FAILED``, nobody coming. The sweep terminalizes it with a code that names the
    reconciliation, so an operator reading the row learns what happened instead of nothing.
    """
    from lumen_api.fleet_reaper import ORPHANED_CODE, sweep_orphaned_jobs, sweep_stranded_jobs

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "orphjob")
            job_id, work_id = await _offer_ingestion(workspace_id, DesignIngestionKind.AD_ASSETS)
            await _force_task_status(work_id, FleetTaskStatus.FAILED)

            # The RED case, kept as a permanent guard rather than a moment in a git history: the
            # pre-R3-B reaper only ever looked at ``running`` rows, so this orphan was invisible
            # to it — which is why the acceptance walk's job was still ``queued`` nine minutes
            # later. If someone ever folds the two sweeps together, this line says why not.
            async with transaction() as conn:
                await sweep_stranded_jobs(conn, stranded_after_s=0)
            assert (await _read_job(workspace_id, job_id))["status"] == "queued"

            async with transaction() as conn:
                sweep = await sweep_orphaned_jobs(conn, stranded_after_s=0)
            assert sweep.failed >= 1, sweep
            assert sweep.reoffered == 0, "an orphan is failed, never re-offered"

            job = await _read_job(workspace_id, job_id)
            assert job["status"] == "failed"
            assert job["error"]["code"] == ORPHANED_CODE
            assert "failed" in job["error"]["message"]
            assert "never left 'queued'" in job["error"]["message"]

            await _purge_work(work_id)

    asyncio.run(scenario())


def test_the_reaper_fails_a_queued_job_whose_task_vanished() -> None:
    """Task absent is the same orphan as task terminal — nothing will ever bring a worker."""
    from lumen_api.fleet_reaper import ORPHANED_CODE, sweep_orphaned_jobs

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "orphgone")
            job_id, work_id = await _offer_ingestion(workspace_id, DesignIngestionKind.WEBSITE)
            async with transaction() as conn:
                await conn.execute(
                    text("DELETE FROM fleet_task WHERE work_id = :w"), {"w": work_id}
                )

            async with transaction() as conn:
                await sweep_orphaned_jobs(conn, stranded_after_s=0)

            job = await _read_job(workspace_id, job_id)
            assert job["status"] == "failed"
            assert job["error"]["code"] == ORPHANED_CODE
            assert "missing" in job["error"]["message"]

            await _purge_work(work_id)

    asyncio.run(scenario())


def test_the_reaper_leaves_a_queued_job_whose_task_is_still_waiting() -> None:
    """The healthy case, and the one that matters most: an ``ad_assets`` job left unclaimed by
    the capability gate is WAITING, not orphaned. The sweep must not turn "no capable worker has
    got to it yet" into a failure."""
    from lumen_api.fleet_reaper import sweep_orphaned_jobs

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "orphwait")
            queued_job, queued_work = await _offer_ingestion(
                workspace_id, DesignIngestionKind.AD_ASSETS
            )
            claimed_job, claimed_work = await _offer_ingestion(
                workspace_id, DesignIngestionKind.WEBSITE
            )
            await _force_task_status(claimed_work, FleetTaskStatus.CLAIMED)

            async with transaction() as conn:
                await sweep_orphaned_jobs(conn, stranded_after_s=0)

            assert (await _read_job(workspace_id, queued_job))["status"] == "queued"
            assert (await _read_job(workspace_id, claimed_job))["status"] == "queued"
            assert await _task_status(queued_work) == FleetTaskStatus.QUEUED.value

            await _purge_work(queued_work, claimed_work)

    asyncio.run(scenario())


def test_the_reaper_fails_a_queued_run_whose_task_died_and_settles_its_stream() -> None:
    """The run twin. A terminal row with no terminal event is an editor stream that hangs on a
    finished run forever, so the marker lands in the same transaction as the result."""
    from lumen_api.fleet_reaper import ORPHANED_CODE, sweep_orphaned_runs

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "orphrun")
            run_id, work_id = await _offer_turn(workspace_id)
            await _force_task_status(work_id, FleetTaskStatus.FAILED)

            async with transaction() as conn:
                sweep = await sweep_orphaned_runs(conn, stranded_after_s=0)
            assert sweep.failed >= 1, sweep

            row = await _read_run(workspace_id, run_id)
            assert row["status"] == "failed"
            assert row["result"]["error"]["code"] == ORPHANED_CODE

            async with transaction() as conn:
                events = await run_stream.run_snapshot_events(
                    conn, workspace_id=workspace_id, run_id=run_id
                )
            assert [event["type"] for event in events][-1] == "error"

            await _purge_work(work_id)

    asyncio.run(scenario())


def test_the_grace_window_protects_a_job_dispatched_moments_ago() -> None:
    """``set_work_id`` and the enqueue are not always one transaction, so a just-dispatched job
    can momentarily look task-less. The grace window is what keeps the sweep away from it."""
    from lumen_api.fleet_reaper import sweep_orphaned_jobs

    async def scenario() -> None:
        async with db_lifespan():
            async with transaction() as conn:
                workspace_id = await _seed_workspace(conn, "orphgrace")
            job_id, work_id = await _offer_ingestion(workspace_id, DesignIngestionKind.WEBSITE)
            async with transaction() as conn:
                await conn.execute(
                    text("DELETE FROM fleet_task WHERE work_id = :w"), {"w": work_id}
                )

            async with transaction() as conn:
                sweep = await sweep_orphaned_jobs(conn, stranded_after_s=3600)
            assert sweep.considered == 0, sweep
            assert (await _read_job(workspace_id, job_id))["status"] == "queued"

            await _purge_work(work_id)

    asyncio.run(scenario())

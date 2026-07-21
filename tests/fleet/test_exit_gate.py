"""The PB-B1 exit gate (treaty §2-B1): kill -9 at ~40% of a 500-account stub-mode run →
restart → resume completes **exactly-once**; a second worker may not drive a leased run and
takes over only after expiry.

Real OS processes (``exit_gate_harness.py``), real SIGKILL, the real M7 state machine + M7.4
ledger + PB-B1 lease/queue underneath; only the phase *bodies* are stubs. The double-spend
detector is the ``exit_gate_spend_journal`` table the stub job writes atomically with its ledger
finish: after the resumed run completes, every ``(account, field, tier)`` key must have exactly
one journal row and one ``succeeded`` ledger row, and every ``(campaign_run, phase)`` key one
``succeeded`` ledger row — no double spend anywhere despite the kill.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from clue_fleet import (
    DbTaskQueue,
    FleetTaskStatus,
    acquire_run_lease,
    enqueue_drive,
    get_run_lease,
)
from sqlalchemy import text
from tests.fleet.conftest import run_async
from tests.fleet.exit_gate_harness import STUB_COST, step_key_for

from clue_core import CampaignRunId, new_campaign_run_id
from clue_core.idempotency import phase_key
from clue_db import db_lifespan
from clue_research.durable import (
    PHASE_SEQUENCE,
    CampaignRun,
    CampaignRunStatus,
    DbCampaignRunStore,
    IdempotencyStatus,
    get_idempotency_ledger,
)

pytestmark = pytest.mark.usefixtures("require_fleet_db")

_HARNESS = Path(__file__).with_name("exit_gate_harness.py")

N_ACCOUNTS = 500
KILL_AT = int(N_ACCOUNTS * 0.4)
LEASE_TTL_S = 2.0

_CREATE_JOURNAL = text(
    """
    CREATE TABLE IF NOT EXISTS exit_gate_spend_journal (
        run_id   uuid NOT NULL,
        step_key text NOT NULL,
        worker   text NOT NULL,
        spent_at timestamptz NOT NULL DEFAULT now()
    )
    """
)


async def _setup(run_id: CampaignRunId) -> None:
    async with db_lifespan() as engine:
        async with engine.begin() as conn:
            await conn.execute(_CREATE_JOURNAL)
        # The real start path (idempotent on the minted id) + the drive offer.
        machine = CampaignRun(store=DbCampaignRunStore())
        await machine.start(
            workspace_id="ws-exit-gate",
            icp_key="icp-exit-gate",
            icp_version=1,
            campaign_run_id=run_id,
        )
        await enqueue_drive(DbTaskQueue(), run_id)


async def _query(sql: str, **params: Any) -> list[Any]:
    async with db_lifespan() as engine, engine.connect() as conn:
        return list((await conn.execute(text(sql), params)).all())


async def _execute(sql: str) -> None:
    """Run one committed statement (DDL/cleanup — ``_query`` reads roll back)."""
    async with db_lifespan() as engine, engine.begin() as conn:
        await conn.execute(text(sql))


async def _done_account_jobs(run_id: CampaignRunId) -> int:
    rows = await _query(
        "SELECT count(*) FROM fleet_task WHERE campaign_run_id = :run "
        "AND kind = 'account_job' AND status = 'done'",
        run=run_id,
    )
    return int(rows[0][0])


async def _run_status(run_id: CampaignRunId) -> str | None:
    rows = await _query("SELECT status FROM campaign_run WHERE id = :run", run=run_id)
    return str(rows[0][0]) if rows else None


async def _assert_lease_blocks_second_driver(run_id: CampaignRunId, holder: str) -> None:
    """The takeover gate, observed live: the killed worker's lease is still live, and an
    acquire by another worker id fails while it is."""
    async with db_lifespan() as engine:
        async with engine.connect() as conn:
            lease = await get_run_lease(conn, run_id)
            assert lease is not None, "the killed driver should still hold the run lease"
            assert lease.worker_id == holder
            assert lease.live, "lease must still be live right after the kill (TTL not lapsed)"
        conn = await engine.connect()
        trans = await conn.begin()
        try:
            acquired = await acquire_run_lease(
                conn,
                campaign_run_id=run_id,
                worker_id="probe-worker",
                ttl=timedelta(seconds=LEASE_TTL_S),
            )
            assert not acquired, "a second worker must NOT be able to drive a leased run"
        finally:
            await trans.rollback()
            await conn.close()


async def _assert_exactly_once(run_id: CampaignRunId, worker_a: str, worker_b: str) -> None:
    # 1. The spend journal — the airtight no-double-spend record (one row per key, ever).
    rows = await _query(
        "SELECT step_key, count(*) FROM exit_gate_spend_journal WHERE run_id = :run "
        "GROUP BY step_key",
        run=run_id,
    )
    counts = {key: int(n) for key, n in rows}
    doubles = {key: n for key, n in counts.items() if n != 1}
    assert not doubles, f"double spend detected on {len(doubles)} keys: {doubles}"
    expected_keys = {step_key_for(run_id, i) for i in range(N_ACCOUNTS)}
    assert set(counts) == expected_keys, f"journal covers {len(counts)} keys, expected {N_ACCOUNTS}"
    # Both workers really contributed (the kill landed mid-run; the takeover finished it).
    workers = {
        str(row[0])
        for row in await _query(
            "SELECT DISTINCT worker FROM exit_gate_spend_journal WHERE run_id = :run", run=run_id
        )
    }
    assert workers == {worker_a, worker_b}

    # 2. The account-step ledger: every key succeeded once with the single charge.
    async with db_lifespan() as engine, engine.connect() as conn:
        for i in range(N_ACCOUNTS):
            row = await get_idempotency_ledger(conn, step_key_for(run_id, i))
            assert row is not None and row.status is IdempotencyStatus.SUCCEEDED
            assert row.cost_cents_charged == STUB_COST
        # 3. The phase ledger: every (campaign_run, phase) key succeeded exactly once.
        for phase in PHASE_SEQUENCE:
            row = await get_idempotency_ledger(conn, phase_key(run_id, phase))
            assert row is not None and row.status is IdempotencyStatus.SUCCEEDED, (
                f"phase {phase.value} ledger not exactly-once"
            )
        # 4. The queue drained clean: all 500 account jobs + the drive task are DONE; the lease
        # was released by the finishing driver.
        assert await get_run_lease(conn, run_id) is None

    statuses = await _query(
        "SELECT status, count(*) FROM fleet_task WHERE campaign_run_id = :run "
        "AND kind = 'account_job' GROUP BY status",
        run=run_id,
    )
    assert {str(s): int(n) for s, n in statuses} == {FleetTaskStatus.DONE.value: N_ACCOUNTS}
    drive = await _query(
        "SELECT status, result_ref_json->>'outcome' FROM fleet_task "
        "WHERE campaign_run_id = :run AND kind = 'drive_run'",
        run=run_id,
    )
    assert len(drive) == 1 and str(drive[0][0]) == FleetTaskStatus.DONE.value
    assert drive[0][1] == "completed"


def _spawn(worker_id: str, run_id: CampaignRunId, log_path: Path) -> subprocess.Popen[bytes]:
    env = {
        **os.environ,
        "EXIT_GATE_ACCOUNTS": str(N_ACCOUNTS),
        "EXIT_GATE_WORKER_ID": worker_id,
        "EXIT_GATE_JOB_SLEEP_S": "0.1",
        "EXIT_GATE_LEASE_TTL_S": str(LEASE_TTL_S),
        "EXIT_GATE_HEARTBEAT_S": "0.5",
        "EXIT_GATE_STALE_S": "2",
        "EXIT_GATE_WINDOW": "16",
        # keep the run id in the env purely for debuggability of the log files
        "EXIT_GATE_RUN_ID": str(run_id),
    }
    log = open(log_path, "wb")  # noqa: SIM115 - handed to Popen for the process's lifetime
    return subprocess.Popen(
        [sys.executable, str(_HARNESS)], env=env, stdout=log, stderr=subprocess.STDOUT
    )


def test_kill9_at_40_percent_resumes_exactly_once(tmp_path: Path) -> None:
    run_id = new_campaign_run_id()
    run_async(_setup(run_id))

    worker_a_log = tmp_path / "worker-a.log"
    worker_b_log = tmp_path / "worker-b.log"
    proc_a = _spawn("exit-gate-worker-a", run_id, worker_a_log)
    proc_b: subprocess.Popen[bytes] | None = None
    try:
        # -- phase 1: let worker A drive to ~40% of the deep fleet, then kill -9 it -----------
        deadline = time.monotonic() + 120
        while True:
            assert proc_a.poll() is None, (
                f"worker A died prematurely; log:\n{worker_a_log.read_text(errors='replace')}"
            )
            done = run_async(_done_account_jobs(run_id))
            if done >= KILL_AT:
                break
            status = run_async(_run_status(run_id))
            assert status != CampaignRunStatus.COMPLETED.value, (
                "run completed before the kill point — raise EXIT_GATE_JOB_SLEEP_S"
            )
            assert time.monotonic() < deadline, (
                f"worker A never reached {KILL_AT} done account jobs (done={done}); "
                f"log:\n{worker_a_log.read_text(errors='replace')}"
            )
            time.sleep(0.05)
        proc_a.kill()  # SIGKILL — no cleanup, no release, no final heartbeat
        proc_a.wait(timeout=10)
        killed_at = run_async(_done_account_jobs(run_id))
        assert killed_at < N_ACCOUNTS, "kill landed after the fleet finished — not a resume test"

        # -- phase 2: the lease still gates the run — a second driver is blocked until expiry -
        run_async(_assert_lease_blocks_second_driver(run_id, "exit-gate-worker-a"))

        # -- phase 3: a fresh worker takes over (only after expiry) and completes the run -----
        proc_b = _spawn("exit-gate-worker-b", run_id, worker_b_log)
        deadline = time.monotonic() + 120
        while True:
            status = run_async(_run_status(run_id))
            if status == CampaignRunStatus.COMPLETED.value:
                break
            assert proc_b.poll() is None, (
                f"worker B died; log:\n{worker_b_log.read_text(errors='replace')}"
            )
            assert time.monotonic() < deadline, (
                f"resumed run never completed (status={status}, "
                f"done={run_async(_done_account_jobs(run_id))}); "
                f"log:\n{worker_b_log.read_text(errors='replace')}"
            )
            time.sleep(0.1)

        # -- phase 4: exactly-once, everywhere ------------------------------------------------
        run_async(_assert_exactly_once(run_id, "exit-gate-worker-a", "exit-gate-worker-b"))

        # -- graceful drain: SIGTERM stops worker B cleanly -----------------------------------
        proc_b.terminate()
        assert proc_b.wait(timeout=15) == 0, (
            f"worker B did not drain cleanly; log:\n{worker_b_log.read_text(errors='replace')}"
        )
    finally:
        for proc in (proc_a, proc_b):
            if proc is not None and proc.poll() is None:
                proc.kill()
                proc.wait(timeout=10)
        # Drop the (non-alembic) journal table so it cannot leak into other suites —
        # ``test_no_domain_tables_at_m0_head`` asserts a downgraded schema holds *only*
        # alembic-managed tables. Worker/failure diagnostics live in the log files, not here.
        run_async(_execute("DROP TABLE IF EXISTS exit_gate_spend_journal"))

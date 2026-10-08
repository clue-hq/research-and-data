"""Replay a research run's provider results through drain → index → recovery, without any model or
provider call, and time each step (W2 of the research cost/speed audit).

Every paid provider result of the run (``provider_call_ledger`` result rows with a stored
response) is replayed the way a research job lands it after the provider answers:

1. drain    — the raw response is written to storage again and a fresh ledger row is recorded;
2. index    — the real ``index_acquisition`` turns it into evidence sources (files + rows);
3. recover  — the real ``recover_acquisitions`` sweep that ``operate()`` runs after each call.

Each step runs in its own transaction through an emulated worker connection guarded by one lock,
exactly like ``Arv2AccountResearchWorkHandler._connection``. Jobs run concurrently, spread across
``--workers`` emulated workers; within a job up to ``--per-job`` calls run at once.

It writes, so it runs against a throwaway copy of the lane database, created from the lane
database (which must have no connections) and dropped afterwards unless ``--keep-db``:

    set -a; source .env; set +a
    .venv/bin/python scripts/bench_evidence_indexing.py --run <run id> --storage r2
    .venv/bin/python scripts/bench_evidence_indexing.py --run <run id> --storage fs

``--storage r2`` uses the ``CLUE_STORAGE_S3_*`` settings (a dev bucket); the run's raw responses
are copied there first (not timed). ``--storage fs`` uses a scratch directory.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import math
import os
import statistics
import sys
import tempfile
import time
from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (q in 0..100) of a non-empty sample."""
    ordered = sorted(values)
    rank = max(1, min(len(ordered), math.ceil(q / 100 * len(ordered))))
    return ordered[rank - 1]


def summarise(calls: Sequence[dict[str, float]]) -> dict[str, dict[str, float]]:
    """p50 / p95 / mean / total (ms) of each timed step across the replayed calls."""
    out: dict[str, dict[str, float]] = {}
    for step in ("lock_wait_ms", "drain_ms", "index_ms", "recover_ms", "total_ms"):
        values = [c[step] for c in calls if step in c]
        if values:
            out[step] = {
                "p50": round(percentile(values, 50), 1),
                "p95": round(percentile(values, 95), 1),
                "mean": round(statistics.fmean(values), 1),
                "total": round(sum(values), 1),
            }
    return out


class TimedStorage:
    """Count and time every storage call the indexing path makes."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner
        self.ops: Counter[str] = Counter()
        self.ms: defaultdict[str, float] = defaultdict(float)

    def __getattr__(self, name: str) -> Any:
        attr = getattr(self._inner, name)
        if not asyncio.iscoroutinefunction(attr):
            return attr

        async def timed(*args: Any, **kwargs: Any) -> Any:
            started = time.monotonic()
            try:
                return await attr(*args, **kwargs)
            finally:
                self.ops[name] += 1
                self.ms[name] += (time.monotonic() - started) * 1000

        return timed


async def _ledger_rows(conn: Any, run_id: UUID) -> list[dict[str, Any]]:
    from sqlalchemy import text

    return [
        dict(r)
        for r in (
            await conn.execute(
                text("""SELECT l.*, j.run_id, j.account_entity_id, j.workspace_id AS job_ws
                FROM provider_call_ledger l JOIN arv2_research_job j
                  ON j.job_id=l.entity_research_job_id
                WHERE j.run_id=:run AND l.phase='result'
                  AND l.provider NOT IN ('openrouter','model')
                  AND l.response_artifact_key IS NOT NULL
                ORDER BY l.recorded_at, l.ledger_id"""),
                {"run": run_id},
            )
        )
        .mappings()
        .all()
    ]


async def _copy_raw(source: Any, target: Any, keys: Iterable[str]) -> int:
    copied = 0
    for key in sorted(set(keys)):
        body = await source.get(key)
        await target.put(key, body, media_type="application/json")
        copied += 1
    return copied


class Worker:
    """One emulated fleet worker: one database connection, shared by its jobs behind one lock."""

    def __init__(self, conn: Any) -> None:
        self.conn = conn
        self.lock = asyncio.Lock()

    async def step(self, call: dict[str, float], name: str, work: Any) -> None:
        asked = time.monotonic()
        async with self.lock:
            call["lock_wait_ms"] = call.get("lock_wait_ms", 0.0) + (time.monotonic() - asked) * 1000
            started = time.monotonic()
            async with self.conn.begin():
                await work(self.conn)
            call[name] = (time.monotonic() - started) * 1000


async def _replay_call(
    worker: Worker, storage: TimedStorage, row: dict[str, Any], columns: Sequence[str]
) -> dict[str, float]:
    from sqlalchemy import text

    from clue_api.arv2.quality_acquisition import index_acquisition, recover_acquisitions
    from clue_api.arv2.research_operations import OperationScope
    from clue_spend.ledger import DrainReport, ledger_id_for
    from clue_spend.sinks import LedgerRow

    scope = OperationScope(
        row["job_ws"], row["run_id"], row["entity_research_job_id"], row["account_entity_id"]
    )
    row_id = f"bench-{uuid4()}"
    key = row["response_artifact_key"]
    call: dict[str, float] = {}
    held: dict[str, bytes] = {}
    started = time.monotonic()

    async def drain(conn: Any) -> None:
        body = await storage.get(key)  # the bytes the drain held in memory, from the replay copy
        await storage.put(key, body, media_type="application/json")
        held[key] = body
        values = {c: row[c] for c in columns}
        values["ledger_id"], values["call_id"] = ledger_id_for(row_id), uuid4()
        for c, v in values.items():
            if isinstance(v, dict | list):
                values[c] = json.dumps(v)
        await conn.execute(
            text(
                f"INSERT INTO provider_call_ledger ({', '.join(columns)}) VALUES "
                f"({', '.join(':' + c for c in columns)})"
            ),
            values,
        )

    async def index(conn: Any) -> None:
        report = DrainReport(
            rows=1,
            artifacts=1,
            cost_usd=Decimal(row["cost_usd"] or 0),
            credits=Decimal(row["credits"] or 0),
            media_seconds=row["media_seconds"] or 0,
            result_rows=(
                LedgerRow(
                    row_id=row_id,
                    call_id=row_id,
                    phase="result",
                    provider=row["provider"],
                    operation=row["operation"],
                    label=row["label"],
                    recorded_at=row["recorded_at"],
                    http_status=row["http_status"],
                    error_code=row["error_code"],
                    raw_ref="replay",
                ),
            ),
            raw_artifact_keys={"replay": key},
            raw_bodies=held,
        )
        await index_acquisition(conn, storage, scope, report)

    async def recover(conn: Any) -> None:
        await recover_acquisitions(conn, storage, scope)

    await worker.step(call, "drain_ms", drain)
    await worker.step(call, "index_ms", index)
    await worker.step(call, "recover_ms", recover)
    call["total_ms"] = (time.monotonic() - started) * 1000
    return call


async def bench(args: argparse.Namespace) -> dict[str, Any]:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from clue_config import Secrets, Settings
    from clue_storage import FsStorage, storage_from_settings

    lane_url = os.environ["CLUE_DATABASE_URL"]
    bench_db = f"{lane_url.rsplit('/', 1)[1]}_bench"
    admin = create_async_engine(
        lane_url.rsplit("/", 1)[0] + "/postgres", isolation_level="AUTOCOMMIT"
    )
    async with admin.connect() as conn:
        await conn.execute(text(f'DROP DATABASE IF EXISTS "{bench_db}"'))
        await conn.execute(
            text(f'CREATE DATABASE "{bench_db}" TEMPLATE "{lane_url.rsplit("/", 1)[1]}"')
        )
    engine = create_async_engine(
        f"{lane_url.rsplit('/', 1)[0]}/{bench_db}", pool_size=args.workers + 2
    )
    lane_storage = FsStorage(Path(os.environ.get("CLUE_STORAGE_FS_ROOT", ".artifacts")))
    scratch = None
    if args.storage == "r2":
        target = storage_from_settings(Settings(storage_backend="s3"), Secrets())
    else:
        scratch = tempfile.mkdtemp(prefix="bench-evidence-")
        target = FsStorage(Path(scratch))
    conns: list[Any] = []
    try:
        async with engine.connect() as conn:
            rows = await _ledger_rows(conn, UUID(args.run))
            listed = await conn.execute(
                text("""SELECT column_name FROM information_schema.columns
                WHERE table_name='provider_call_ledger' ORDER BY ordinal_position""")
            )
            columns = list(listed.scalars())
            await conn.rollback()
        if args.limit:
            rows = rows[: args.limit]
        copied = await _copy_raw(lane_storage, target, (r["response_artifact_key"] for r in rows))
        storage = TimedStorage(target)
        by_job: dict[Any, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            by_job[row["entity_research_job_id"]].append(row)
        conns.extend([await engine.connect() for _ in range(args.workers)])
        workers = [Worker(c) for c in conns]
        results: list[dict[str, float]] = []

        async def run_job(worker: Worker, job_rows: list[dict[str, Any]]) -> None:
            gate = asyncio.Semaphore(args.per_job)

            async def one(row: dict[str, Any]) -> None:
                async with gate:
                    results.append(await _replay_call(worker, storage, row, columns))

            await asyncio.gather(*(one(r) for r in job_rows))

        started = time.monotonic()
        await asyncio.gather(
            *(run_job(workers[i % len(workers)], jr) for i, jr in enumerate(by_job.values()))
        )
        wall_s = time.monotonic() - started
        return {
            "run": args.run,
            "storage": args.storage,
            "workers": args.workers,
            "per_job": args.per_job,
            "jobs": len(by_job),
            "calls": len(results),
            "raw_files_copied": copied,
            "wall_s": round(wall_s, 1),
            "steps": summarise(results),
            "storage_ops": dict(storage.ops),
            "storage_ms": {k: round(v, 1) for k, v in storage.ms.items()},
        }
    finally:
        for c in conns:
            with contextlib.suppress(Exception):  # cleanup must not hide the real error
                await c.close()
        await engine.dispose()
        if not args.keep_db:
            try:
                async with admin.connect() as conn:
                    await conn.execute(
                        text(
                            "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                            "WHERE datname=:db AND pid<>pg_backend_pid()"
                        ),
                        {"db": bench_db},
                    )
                    await conn.execute(text(f'DROP DATABASE IF EXISTS "{bench_db}"'))
            except Exception as error:  # noqa: BLE001 - report, never mask the real error
                print(f"could not drop {bench_db}: {error}", file=sys.stderr)
        await admin.dispose()
        if scratch:
            import shutil

            shutil.rmtree(scratch, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--run", required=True, help="research run id whose results to replay")
    parser.add_argument("--storage", choices=("r2", "fs"), default="r2")
    parser.add_argument("--workers", type=int, default=2, help="emulated fleet workers")
    parser.add_argument("--per-job", type=int, default=4, help="concurrent calls within one job")
    parser.add_argument("--limit", type=int, default=0, help="replay only the first N results")
    parser.add_argument("--keep-db", action="store_true")
    parser.add_argument("--json", help="also write the summary to this file")
    args = parser.parse_args()
    summary = asyncio.run(bench(args))
    print(json.dumps(summary, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()

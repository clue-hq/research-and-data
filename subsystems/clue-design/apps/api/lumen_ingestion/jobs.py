from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Protocol
from uuid import uuid4

JsonObject = Dict[str, Any]


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


def _default_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _encode_optional(value: Any) -> Optional[str]:
    return None if value is None else _encode(value)


def _decode_optional(value: Optional[str]) -> Any:
    return None if value is None else json.loads(value)


def _job_from_row(row: sqlite3.Row) -> JsonObject:
    return {
        "job_id": row["job_id"],
        "kind": row["kind"],
        "status": row["status"],
        "stage": row["stage"],
        "progress": row["progress"],
        "request": json.loads(row["request_json"]),
        "evidence": _decode_optional(row["evidence_json"]),
        "brand_kit_id": row["brand_kit_id"],
        "brand_kit_version": row["brand_kit_version"],
        "error": _decode_optional(row["error_json"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


class IngestionJobStore:
    """Durable store for brand-kit ingestion jobs.

    Takes a sqlite3.Connection like Repository. Timestamps are minted by an
    injectable ``now_iso`` (default ISO-8601 UTC) so tests can freeze them.
    """

    def __init__(
        self,
        connection: sqlite3.Connection,
        now_iso: Callable[[], str] = _default_now_iso,
    ) -> None:
        self.connection = connection
        self.now_iso = now_iso

    def create(self, kind: str, request: JsonObject) -> JsonObject:
        job_id = new_id("ingest")
        now = self.now_iso()
        self.connection.execute(
            """
            INSERT INTO ingestion_jobs (
              job_id, kind, status, stage, progress, request_json,
              evidence_json, brand_kit_id, brand_kit_version, error_json,
              created_at, updated_at
            )
            VALUES (?, ?, 'queued', NULL, 0, ?, NULL, NULL, NULL, NULL, ?, ?)
            """,
            (job_id, kind, _encode(request), now, now),
        )
        self.connection.commit()
        return self.require(job_id)

    def update_request(self, job_id: str, request: JsonObject) -> JsonObject:
        """Replace the stored request_json for a job (e.g. to record the
        tmp-file path once it is known post-create). Job-terminal columns are
        untouched."""
        self.connection.execute(
            """
            UPDATE ingestion_jobs
            SET request_json = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (_encode(request), self.now_iso(), job_id),
        )
        self.connection.commit()
        return self.require(job_id)

    def get(self, job_id: str) -> Optional[JsonObject]:
        row = self.connection.execute(
            "SELECT * FROM ingestion_jobs WHERE job_id = ?", (job_id,)
        ).fetchone()
        return _job_from_row(row) if row is not None else None

    def require(self, job_id: str) -> JsonObject:
        job = self.get(job_id)
        if job is None:
            raise KeyError(f"ingestion_job {job_id} was not found")
        return job

    def set_running(self, job_id: str) -> JsonObject:
        self.connection.execute(
            """
            UPDATE ingestion_jobs
            SET status = 'running', updated_at = ?
            WHERE job_id = ?
            """,
            (self.now_iso(), job_id),
        )
        self.connection.commit()
        return self.require(job_id)

    def set_stage(self, job_id: str, stage: str, progress: float) -> JsonObject:
        self.connection.execute(
            """
            UPDATE ingestion_jobs
            SET stage = ?, progress = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (stage, progress, self.now_iso(), job_id),
        )
        self.connection.commit()
        return self.require(job_id)

    def complete(
        self,
        job_id: str,
        brand_kit_id: str,
        version: int,
        evidence_json: Optional[str],
    ) -> JsonObject:
        self.connection.execute(
            """
            UPDATE ingestion_jobs
            SET status = 'succeeded', progress = 1, brand_kit_id = ?,
                brand_kit_version = ?, evidence_json = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (brand_kit_id, version, evidence_json, self.now_iso(), job_id),
        )
        self.connection.commit()
        return self.require(job_id)

    def fail(self, job_id: str, error: JsonObject) -> JsonObject:
        self.connection.execute(
            """
            UPDATE ingestion_jobs
            SET status = 'failed', error_json = ?, updated_at = ?
            WHERE job_id = ?
            """,
            (_encode_optional(error), self.now_iso(), job_id),
        )
        self.connection.commit()
        return self.require(job_id)


class StageReporter(Protocol):
    """Progress callback handed to capture/normalize code (not the store)."""

    def __call__(self, stage: str, progress: float) -> None: ...


def run_ingestion_job(
    store: IngestionJobStore,
    job_id: str,
    work: Callable[[StageReporter], "tuple[str, int, Optional[str]]"],
) -> None:
    """Drive a job to a terminal state. Never raises.

    ``work`` receives a StageReporter and returns
    ``(brand_kit_id, version, evidence_json)``. Any exception is captured into
    a ``failed`` row via ``store.fail`` — the job is always left in a terminal
    state and this function does not propagate.
    """
    store.set_running(job_id)

    def report(stage: str, progress: float) -> None:
        store.set_stage(job_id, stage, progress)

    try:
        brand_kit_id, version, evidence_json = work(report)
    except Exception as error:  # noqa: BLE001 - failure must never escape
        store.fail(
            job_id,
            {
                "code": "LUMI0401",
                "message": f"{type(error).__name__}: {error}",
            },
        )
        return
    store.complete(job_id, brand_kit_id, version, evidence_json)

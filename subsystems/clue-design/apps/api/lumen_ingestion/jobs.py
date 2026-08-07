"""Ingestion-job store (Part II slice D2.3: now Postgres, behind the same public surface).

The SQL moved to ``clue_design.ingestion``; this class is the sync facade the API and the
BackgroundTasks workers keep calling. Every method routes through one
:class:`~lumen_api.design_store.DesignStoreBridge` call — one coroutine, one loop, one
transaction (the O5 rule) — and returns the same JSON shape as before.

Two constructor arguments are now VESTIGIAL and kept only so the ~12 call sites (and the
suites) need no churn: ``connection`` (the SQLite handle: accepted, never used) and ``now_iso``
(timestamps are the database's ``now()`` since the port). Both die at D2.5 with the SQLite
Repository.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional, Protocol

from clue_design import ingestion as design_ingestion
from clue_design.ingestion import new_id as new_id  # re-exported: the ported public name
from lumen_api.design_store import DesignStoreBridge, default_workspace_id

JsonObject = Dict[str, Any]


def _default_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class IngestionJobStore:
    """Durable store for brand-kit ingestion jobs (Postgres, workspace-scoped).

    ``workspace_id`` defaults to the configured dev workspace, exactly like
    ``HybridRepository`` — request paths pass the resolved workspace explicitly.
    """

    def __init__(
        self,
        connection: Any = None,
        now_iso: Callable[[], str] = _default_now_iso,
        *,
        workspace_id: Optional[str] = None,
    ) -> None:
        # Vestigial (D2.5 deletes both): the SQLite handle and the caller-minted clock.
        self.connection = connection
        self.now_iso = now_iso
        self.workspace_id = workspace_id or default_workspace_id()
        self._bridge = DesignStoreBridge(self.workspace_id)

    def create(self, kind: str, request: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_ingestion.create_job(
                conn, workspace_id=self.workspace_id, kind=kind, request=request
            )
        )

    def update_request(self, job_id: str, request: JsonObject) -> JsonObject:
        """Replace the stored request_json for a job (e.g. to record the
        tmp-file path once it is known post-create). Job-terminal columns are
        untouched."""
        return self._bridge._run(
            lambda conn: design_ingestion.update_request(
                conn, workspace_id=self.workspace_id, job_id=job_id, request=request
            )
        )

    def get(self, job_id: str) -> Optional[JsonObject]:
        return self._bridge._run(
            lambda conn: design_ingestion.get_job(
                conn, workspace_id=self.workspace_id, job_id=job_id
            )
        )

    def require(self, job_id: str) -> JsonObject:
        """Fetch or raise. The bridge translates the DAL's fail-closed refusal into
        ``lumen_api.database.NotFoundError`` — a ``KeyError`` subclass, so the ported
        ``raise KeyError`` contract still holds for every caller."""
        return self._bridge._run(
            lambda conn: design_ingestion.require_job(
                conn, workspace_id=self.workspace_id, job_id=job_id
            )
        )

    def list_recent(self, limit: int = 50) -> list[JsonObject]:
        """Most-recent jobs first (by created_at, then job_id as a tiebreak)."""
        return self._bridge._run(
            lambda conn: design_ingestion.list_recent(
                conn, workspace_id=self.workspace_id, limit=limit
            )
        )

    def set_running(self, job_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_ingestion.set_running(
                conn, workspace_id=self.workspace_id, job_id=job_id
            )
        )

    def set_stage(self, job_id: str, stage: str, progress: float) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_ingestion.set_stage(
                conn,
                workspace_id=self.workspace_id,
                job_id=job_id,
                stage=stage,
                progress=progress,
            )
        )

    def complete(
        self,
        job_id: str,
        brand_kit_id: str,
        version: int,
        evidence_json: Optional[str],
    ) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_ingestion.complete(
                conn,
                workspace_id=self.workspace_id,
                job_id=job_id,
                brand_kit_id=brand_kit_id,
                version=version,
                evidence_json=evidence_json,
            )
        )

    def fail(self, job_id: str, error: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_ingestion.fail(
                conn, workspace_id=self.workspace_id, job_id=job_id, error=error
            )
        )


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

"""Ingestion-job store (Part II slice D2.3: now Postgres, behind the same public surface).

The SQL moved to ``clue_design.ingestion``; this class is the sync facade the API and the
BackgroundTasks workers keep calling. Every method routes through one
:class:`~lumen_api.design_store.DesignStoreBridge` call — one coroutine, one loop, one
transaction (the O5 rule) — and returns the same JSON shape as before.

D2.5B deleted the two vestigial constructor arguments — ``connection`` (the SQLite handle) and
``now_iso`` (timestamps have been the database's ``now()`` since the port) — along with the
SQLite substrate itself.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional, Protocol
from uuid import UUID

from clue_design import ingestion as design_ingestion
from clue_design.errors import DesignJobFencedError
from clue_design.ingestion import new_id as new_id  # re-exported: the ported public name
from lumen_api.design_store import DesignStoreBridge, default_workspace_id
from py_lumen_obs import get_logger

JsonObject = Dict[str, Any]

logger = get_logger("lumen_ingestion.jobs")


class IngestionJobStore:
    """Durable store for brand-kit ingestion jobs (Postgres, workspace-scoped).

    ``workspace_id`` defaults to the configured dev workspace, exactly like
    ``HybridRepository`` — request paths pass the resolved workspace explicitly.

    ``expected_generation`` (D5 Round C) is the lease generation the caller holds. Set it and
    EVERY write this store makes is fenced: once a takeover worker claims the job under a higher
    generation, this store's writes raise
    :class:`~clue_design.errors.DesignJobFencedError` rather than overwriting the live attempt's
    progress or result. Left ``None`` (the direct/CLI callers, and every pre-fleet path) the
    writes are unfenced exactly as before.
    """

    def __init__(
        self,
        *,
        workspace_id: Optional[str] = None,
        expected_generation: Optional[int] = None,
    ) -> None:
        self.workspace_id = workspace_id or default_workspace_id()
        self.expected_generation = expected_generation
        self._bridge = DesignStoreBridge(self.workspace_id)

    def create(self, kind: str, request: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_ingestion.create_job(
                conn, workspace_id=self.workspace_id, kind=kind, request=request
            )
        )

    def create_and_offer(
        self,
        kind: str,
        request: JsonObject,
        *,
        job_id: str,
        work_id: UUID,
        envelope: JsonObject,
        priority: int = 0,
    ) -> JsonObject:
        """Create the job AND offer its ``design_job`` task to the fleet — ONE transaction.

        The ingestion twin of ``HybridRepository.create_run_and_offer`` (R-D5-B5) and the same
        ``launch_entity_research_run`` precedent. Split across two commits there are two ways to
        be wrong and both are live failure modes: a job row with no task is an ingestion that
        never starts and never fails (exactly the ``BackgroundTasks`` failure this replaces), and
        a task with no job row is a worker that claims work it cannot find.

        Both ids are minted by the CALLER because the envelope names the job: a server-side id
        discovered only after the INSERT could not have ridden the task payload it was enqueued
        with. The job's staged inputs (``request``) are already durable platform-storage digests
        (D4), so a requeued worker recovers them with
        :func:`~clue_design.ingestion.read_staged_request` and re-reads the same bytes.
        """

        return self._bridge._run(lambda conn: create_and_offer(
            conn, workspace_id=self.workspace_id, kind=kind, request=request,
            job_id=job_id, work_id=work_id, envelope=envelope, priority=priority,
        ))

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

    def list_recent(
        self, limit: int = 50, *, kinds: Optional[tuple[str, ...]] = None
    ) -> list[JsonObject]:
        """Most-recent jobs first (by created_at, then job_id as a tiebreak); ``kinds`` narrows."""
        return self._bridge._run(
            lambda conn: design_ingestion.list_recent(
                conn, workspace_id=self.workspace_id, limit=limit, kinds=kinds
            )
        )

    def set_running(self, job_id: str) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_ingestion.set_running(
                conn,
                workspace_id=self.workspace_id,
                job_id=job_id,
                expected_generation=self.expected_generation,
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
                expected_generation=self.expected_generation,
            )
        )

    def complete(
        self,
        job_id: str,
        brand_kit_id: str | None,
        version: int | None,
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
                expected_generation=self.expected_generation,
            )
        )

    def fail(self, job_id: str, error: JsonObject) -> JsonObject:
        return self._bridge._run(
            lambda conn: design_ingestion.fail(
                conn,
                workspace_id=self.workspace_id,
                job_id=job_id,
                error=error,
                expected_generation=self.expected_generation,
            )
        )


class StageReporter(Protocol):
    """Progress callback handed to capture/normalize code (not the store)."""

    def __call__(self, stage: str, progress: float) -> None: ...


def run_ingestion_job(
    store: IngestionJobStore,
    job_id: str,
    work: Callable[[StageReporter], "tuple[Optional[str], Optional[int], Optional[str]]"],
    *,
    on_complete: Optional[Callable[[], Any]] = None,
) -> None:
    """Drive a job to a terminal state. Never raises.

    ``work`` receives a StageReporter and returns
    ``(brand_kit_id, version, evidence_json)``. Any exception is captured into
    a ``failed`` row via ``store.fail`` — the job is always left in a terminal
    state and this function does not propagate.

    **The one exception to "always terminal" is being FENCED** (D5 Round C). When ``store``
    carries an ``expected_generation`` and a takeover worker has claimed the job under a newer
    one, this attempt has already been replaced: its writes are refused with
    :class:`~clue_design.errors.DesignJobFencedError` and the correct behaviour is to drop them
    and stop, never to retry and never to stamp ``failed`` over the live attempt's work. So a
    fence is caught, logged loudly (a zombie is visible in the logs) and returned from — the job
    is terminalized by whoever actually owns it.

    ``on_complete`` runs once the job has been durably marked ``succeeded`` by THIS attempt, and
    never after a failure or a fence. It is follow-on work (the ad-assets card offer), so its own
    failure is logged and swallowed: the job it follows has already finished.
    """
    if not _fenced_guard(store.set_running, job_id, job_id=job_id, write="set_running"):
        return

    def report(stage: str, progress: float) -> None:
        # A fenced progress write is dropped, not raised: it must not become the ``work``
        # exception that would then be recorded as a job failure below.
        _fenced_guard(store.set_stage, job_id, stage, progress, job_id=job_id, write="set_stage")

    try:
        brand_kit_id, version, evidence_json = work(report)
    except Exception as error:  # noqa: BLE001 - failure must never escape
        _fenced_guard(
            store.fail,
            job_id,
            {
                "code": _failure_code(error),
                "message": f"{type(error).__name__}: {error}",
            },
            job_id=job_id,
            write="fail",
        )
        return
    completed = _fenced_guard(
        store.complete,
        job_id,
        brand_kit_id,
        version,
        evidence_json,
        job_id=job_id,
        write="complete",
    )
    if completed and on_complete is not None:
        try:
            on_complete()
        except Exception:  # noqa: BLE001 - follow-on work must never touch the finished job
            logger.exception("ingestion_job.on_complete_failed", job_id=job_id)


def _failure_code(error: BaseException) -> str:
    """The job's terminal failure code — ``LUMI0401`` unless a provider refused to SELL.

    Lane 3 slice 5: an OpenRouter ``402``/out-of-credit latches the provider and raises
    ``ProviderHalted`` out of the ingestion model clients (they swallow every other failure and
    fall back). That is not "this stage did not work", it is "this deployment cannot buy" — the
    only failure an operator fixes by topping up a key rather than by reading a traceback — so it
    gets its own code, named after the provider and the reason it gave.
    """
    from clue_spend import ProviderHalted

    if isinstance(error, ProviderHalted):
        return f"provider_refused:{error.provider}:{error.reason_code}"
    return "LUMI0401"


def _fenced_guard(
    write_fn: Callable[..., Any], *args: Any, job_id: str, write: str
) -> bool:
    """Call one store write; ``False`` when it was refused because this attempt was taken over."""
    try:
        write_fn(*args)
    except DesignJobFencedError as fenced:
        logger.warning(
            "ingestion_job.write_fenced",
            job_id=job_id,
            write=write,
            expected_generation=fenced.expected_generation,
            current_generation=fenced.current_generation,
            detail="a takeover worker owns this job; the abandoned attempt's write was dropped",
        )
        return False
    return True


async def create_and_offer(
    conn: Any, *, workspace_id: str, kind: str, request: JsonObject,
    job_id: str, work_id: UUID, envelope: JsonObject, priority: int = 0,
) -> JsonObject:
    """One shared transaction operation for ingestion offers and atomic asset uploads."""
    from clue_core import ProjectRunId
    from clue_fleet.enums import FleetTaskKind
    from clue_fleet.queue import enqueue_task

    job = await design_ingestion.create_job(
        conn, workspace_id=workspace_id, kind=kind, request=request,
        job_id=job_id, work_id=work_id,
    )
    await enqueue_task(
        conn, kind=FleetTaskKind.DESIGN_JOB, project_run_id=ProjectRunId(work_id),
        dedup_key=str(work_id), payload=envelope, priority=priority, reopen_terminal=False,
    )
    return job

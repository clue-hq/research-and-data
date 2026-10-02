"""B2 storage api-root wiring — build one backend, bind it per run, feed it to the erasure paths.

The B2 storage lane (PB-B2) ships every substrate piece behind an *injected*
:class:`~clue_storage.StorageBackend` (the ``Freshness`` pattern) and, per treaty §3.4, defers the
composition-root wiring to the integrator. This module is that wiring — the one place ``clue_api``
(the import-linter-exempt seam; nothing imports it) reads the ``CLUE_STORAGE_*`` settings and
threads the resulting backend into the four B2 seams:

* :func:`build_storage_backend` — the single :class:`~clue_storage.StorageBackend` for the process,
  built from settings alone (fs default, S3 when configured). Every consumer below takes it injected
  and never learns which impl it holds (the same split the gateway/db seams use).
* :class:`SnapshotBindingPhaseHandler` — wraps a phase handler so **each run** executes inside
  ``bind_snapshots(SnapshotSink(workspace_id=ctx.workspace_id), storage)``. The tier-2 scrape
  resolver captures into, and the waterfall flushes from, this one **ambient** sink (audit finding
  5: the registered resolver holds no sink — it reads the per-run binding), so concurrent runs never
  cross workspaces. ``deep/composition.py`` wraps the DEEP handler with this.
* :func:`build_data_subject_rights` — the DSAR construction site with ``storage=`` injected, so an
  ``erase`` / objection performs the refcounted blob deletion (B2.5). Feed its result into
  :func:`~clue_api.review_feedback_wiring.build_dsar_with_disposition_cascade` to add the M13.2
  disposition tombstone cascade.
* :func:`run_orphan_blob_sweep` — the scheduled op entry point for
  :func:`clue_storage.sweep_orphan_blobs` (an abandoned rolled-back upload leaves a blob with no
  ``artifact`` row; the grace window keeps the sweep from racing an open transaction). Analogous to
  the retention sweep, but a maintenance op rather than a phase handler — an operator/scheduler
  calls it periodically alongside the retention sweep.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncConnection

from clue_config import Secrets, Settings
from clue_core import EntityId, PhaseContext, PhaseHandler, PhaseResult, ProjectPhase
from clue_db import ConnFactory, transaction
from clue_obs import get_logger
from clue_obs.otel import MetricSink
from clue_research.compliance import DataSubjectRightsImpl
from clue_research.durable import stop_contact_research_operations
from clue_storage import (
    SnapshotSink,
    StorageBackend,
    bind_snapshots,
    purge_erased_artifacts,
    storage_from_settings,
    sweep_orphan_blobs,
)

__all__ = [
    "build_storage_backend",
    "SnapshotBindingPhaseHandler",
    "bind_snapshots_around_deep",
    "build_data_subject_rights",
    "DurableContactResearchPrivacyStopper",
    "run_orphan_blob_sweep",
    "DEFAULT_ORPHAN_SWEEP_GRACE",
]

# The default reconciliation grace for the orphan-blob sweep — far beyond any transaction lifetime,
# so the sweep never races an in-flight upload whose ``artifact`` row is inserted-but-not-committed.
DEFAULT_ORPHAN_SWEEP_GRACE: timedelta = timedelta(hours=24)
log = get_logger("clue_api.storage_wiring")


class DurableContactResearchPrivacyStopper:
    """Bind compliance's privacy-stop seam to the unified C4/C5 durable operation control."""

    async def stop(
        self,
        conn: AsyncConnection,
        *,
        workspace_id: str,
        contact_id: EntityId,
        reason_code: str,
        authority_ref: str,
        channel_field_keys: frozenset[str] | None = None,
        stop_external: bool = True,
    ) -> None:
        from clue_api.arv2.research_operations import stop_contact_jobs

        await conn.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": f"contact-research:{workspace_id}:{contact_id}"},
        )
        await stop_contact_jobs(
            conn,
            workspace_id=workspace_id,
            contact_id=contact_id,
            stop_external=stop_external,
            channel_fields=channel_field_keys,
        )
        await stop_contact_research_operations(
            conn,
            workspace_id=workspace_id,
            contact_id=contact_id,
            reason_code=reason_code,
            authority_ref=authority_ref,
            channel_field_keys=channel_field_keys,
            stop_external=stop_external,
        )


def build_storage_backend(
    settings: Settings | None = None, secrets: Secrets | None = None
) -> StorageBackend:
    """The single :class:`~clue_storage.StorageBackend` for the process, from settings alone.

    A thin api-root wrapper over :func:`clue_storage.storage_from_settings` (the only reader of the
    ``CLUE_STORAGE_*`` knobs) so every B2 consumer at this root shares one composed backend — the
    same "build one concrete, inject it everywhere" shape the gateway/redis/session seams follow.
    ``CLUE_STORAGE_BACKEND=fs`` (default) or ``s3`` (needs ``CLUE_STORAGE_S3_BUCKET``; fails loud).
    """
    resolved = settings if settings is not None else Settings()
    if resolved.storage_backend == "fs":
        # Resolve once at composition so every later read/write uses the exact root reported at
        # startup. A relative root interpreted under two different process working directories is
        # otherwise indistinguishable from data loss when API and worker share a database.
        fs_root = Path(resolved.storage_fs_root).expanduser().resolve()
        resolved = resolved.model_copy(update={"storage_fs_root": str(fs_root)})
        log.info(
            "storage.backend.configured",
            backend="fs",
            fs_root=str(fs_root),
        )
    else:
        log.info(
            "storage.backend.configured",
            backend="s3",
            bucket=resolved.storage_s3_bucket,
            region=resolved.storage_s3_region,
        )
    return storage_from_settings(resolved, secrets)


class SnapshotBindingPhaseHandler:
    """Wraps a phase handler so its ``run`` executes inside the run's ambient snapshot binding.

    Each ``run(ctx)`` binds a fresh per-run :class:`~clue_storage.SnapshotSink`, workspace-scoped to
    ``ctx.workspace_id``, plus the durable ``storage`` backend, for the duration of the inner run
    (audit finding 5). The tier-2 scrape resolver — registered globally and therefore **sink-less**
    — captures into this ambient sink, and the waterfall/pipeline flush from it; ContextVars are
    task-local, so two concurrent runs never share (or swap) workspace-bound sinks. Delegates
    ``phase`` to the inner handler so it registers under the same ``ProjectPhase``
    (last-write-wins), exactly as
    :class:`~clue_api.handoff_retention.RetentionSweepHandoffHandler` wraps the inner handoff
    handler."""

    def __init__(self, *, inner: PhaseHandler, storage: StorageBackend) -> None:
        self._inner = inner
        self._storage = storage
        # Register under the SAME phase as the inner handler (last-write-wins) — a plain attribute,
        # not a property, so it satisfies the mutable ``PhaseHandler.phase`` protocol member.
        self.phase: ProjectPhase = inner.phase

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        # Fail closed on a missing workspace scope: an empty ``workspace_id`` would key every
        # captured snapshot into the ``public/{sha}`` scope (the sink's public fallback), so a
        # tenant run's evidence blobs would land in the cross-tenant public namespace with a
        # scope-mismatched ``artifact`` row — against the workspace-local ruling (B3). A run must
        # carry a real workspace to capture snapshots; an unset one is a composition/state-machine
        # bug, not a silently-public capture.
        if not ctx.workspace_id:
            raise ValueError(
                "SnapshotBindingPhaseHandler.run requires a non-empty ctx.workspace_id "
                "(an empty workspace would key tenant snapshots into the public scope)"
            )
        sink = SnapshotSink(workspace_id=ctx.workspace_id)
        with bind_snapshots(sink, self._storage):
            return await self._inner.run(ctx)


def bind_snapshots_around_deep(
    inner: PhaseHandler, *, storage: StorageBackend
) -> SnapshotBindingPhaseHandler:
    """Wrap the DEEP phase handler so every deep run captures/flushes under one per-run sink.

    The DEEP run is where the tier-2 scrape resolver fetches evidence pages, so it is the run-drive
    path that must bind the sink. ``deep/composition.py`` calls this when a ``storage`` backend is
    supplied; without one, the handler is registered unwrapped (the pre-B2 no-snapshotting path)."""
    return SnapshotBindingPhaseHandler(inner=inner, storage=storage)


def build_data_subject_rights(
    workspace_id: str,
    *,
    storage: StorageBackend | None = None,
    conn_factory: ConnFactory = transaction,
    sink: MetricSink | None = None,
) -> DataSubjectRightsImpl:
    """Construct the controller-scoped M10.5 DSAR service **with the storage backend injected**.

    The api-root construction site for :class:`~clue_research.compliance.DataSubjectRightsImpl`: an
    ``erase`` / ``record_objection`` tombstones the claim rows and — with ``storage`` wired —
    performs the refcounted blob deletion for any snapshot the erased claims were the last live
    citers of (B2.5). Without a backend the intent (``erased_at``) is still stamped and a later
    storage-wired sweep converges, but production must inject one. Wrap the result with
    :func:`~clue_api.review_feedback_wiring.build_dsar_with_disposition_cascade` to also cascade the
    M13.2 disposition tombstone."""
    return DataSubjectRightsImpl(
        workspace_id,
        conn_factory=conn_factory,
        sink=sink,
        storage=storage,
        contact_research_stopper=DurableContactResearchPrivacyStopper(),
    )


async def run_orphan_blob_sweep(
    conn: AsyncConnection,
    *,
    storage: StorageBackend | None = None,
    grace: timedelta = DEFAULT_ORPHAN_SWEEP_GRACE,
    now: datetime | None = None,
) -> tuple[str, ...]:
    """Purge expired/erased artifacts, then abandoned orphan blobs older than ``grace``.

    Returns the deleted orphan keys; erased-artifact purging keeps its existing durable receipts.

    A writer records the ``artifact`` row *before* putting the blob, so a transaction that rolls
    back and is never retried can leave a blob with no row — invisible to the DB, unreachable by
    DSAR. :func:`clue_storage.sweep_orphan_blobs` collects those; the grace window (default 24h)
    keeps it from racing an open transaction. This is the orphan leg the retention sweep does not
    cover; schedule it alongside ``RetentionSweep`` at the ops layer (the fleet worker process runs
    it on ``CLUE_STORAGE_ORPHAN_SWEEP_INTERVAL_S``; see :mod:`clue_api.fleet_main`).

    **Compose-if-None asymmetry (deliberate).** Unlike the production *registration* surfaces
    (:func:`~clue_api.deep.composition.register_deep_phase_handler`,
    :func:`~clue_api.handoff_retention.register_retention_sweeping_handoff_handler`), where a
    missing ``storage`` is a ``TypeError`` (a forgotten backend must fail loud, not run
    un-snapshotted / un-deleting), this is an **ops convenience** entry point: ``storage=None``
    composes the process backend via :func:`build_storage_backend`. A maintenance op invoked ad hoc
    (a cron/ops shell) should not have to construct the backend itself, and there is no correctness
    hazard in the default — the sweep only ever *deletes* orphans, so the worst case of a wrong
    backend is a no-op, not a leak. Pass ``storage`` explicitly to sweep a specific backend."""
    backend = storage if storage is not None else build_storage_backend()
    await purge_erased_artifacts(conn, backend)
    return await sweep_orphan_blobs(conn, backend, grace=grace, now=now)


# Static-time conformance: the snapshot-binding wrapper is itself a ``core.PhaseHandler`` (drop-in
# for any registration), so wrapping the DEEP handler changes nothing the state machine observes.
_WRAPPER_IS_A_PHASE_HANDLER: type[PhaseHandler] = SnapshotBindingPhaseHandler

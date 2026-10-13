"""B2 storage api-root wiring (PB-B2 treaty §3.4) — driven by fakes, no DB.

Proves the four composition-root joins: one backend built from settings, injected into the DSAR /
retention constructions; the per-run ambient snapshot binding on the run-drive path (finding 5); and
the orphan-blob sweep runner reaching :func:`clue_storage.sweep_orphan_blobs` with the composed
storage. The scrape resolver's *production* shape (registered sink-less, reading the ambient
binding) is asserted implicitly by (b): the wrapper is the sole binder of the per-run sink.
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from clue_api import storage_wiring
from clue_api.handoff_retention import build_retention_sweeping_handoff_handler
from clue_api.storage_wiring import (
    DEFAULT_ORPHAN_SWEEP_GRACE,
    SnapshotBindingPhaseHandler,
    build_data_subject_rights,
    build_storage_backend,
    run_orphan_blob_sweep,
)
from clue_config import Secrets, Settings
from clue_core import (
    PhaseContext,
    PhaseResult,
    PhaseStatus,
    ProjectPhase,
    new_project_run_id,
)
from clue_research.compliance import DataSubjectRightsImpl, RetentionSweep
from clue_research.durable import AccountSpec
from clue_storage import (
    SnapshotSink,
    StorageBackend,
    current_snapshot_sink,
    current_storage,
)
from tests.db.conftest import run_async

_CLIENT = "client-acme"


class FakeStorage:
    """A no-op :class:`~clue_storage.StorageBackend` (structural — all methods present)."""

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        return None

    async def get(self, key: str) -> bytes:
        return b""

    async def delete(self, key: str) -> None:
        return None

    async def exists(self, key: str) -> bool:
        return False

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        return f"file://{key}"

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return
        yield  # unreachable — makes this an (empty) async generator


def _ctx(*, workspace_id: str = _CLIENT) -> PhaseContext:
    return PhaseContext(
        project_run_id=new_project_run_id(),
        project_id="prj-test",
        brand_id="brd-test",
        phase=ProjectPhase.DEEP,
        workspace_id=workspace_id,
        icp_key="icp-1",
        icp_version=1,
    )


# --- (a) one backend from settings, injected into the erasure paths -----------------------------


def test_build_storage_backend_from_settings(tmp_path: object) -> None:
    settings = Settings(_env_file=None, storage_backend="fs", storage_fs_root=str(tmp_path))
    backend = build_storage_backend(settings, Secrets(_env_file=None))
    assert isinstance(backend, StorageBackend)
    assert backend._root == Path(str(tmp_path)).resolve()  # type: ignore[attr-defined]  # noqa: SLF001


def test_dsar_construction_injects_storage() -> None:
    storage = FakeStorage()
    dsr = build_data_subject_rights(_CLIENT, storage=storage)
    assert isinstance(dsr, DataSubjectRightsImpl)
    assert dsr._storage is storage  # noqa: SLF001 — wiring test asserts the injected collaborator
    # Without a backend the site still builds (intent-only erasure; a later sweep converges).
    assert build_data_subject_rights(_CLIENT)._storage is None  # noqa: SLF001


def test_retention_sweep_construction_injects_storage() -> None:
    storage = FakeStorage()

    async def _no_accounts(_ctx: PhaseContext) -> Sequence[AccountSpec]:
        return ()

    handler = build_retention_sweeping_handoff_handler(
        inner=_FakeHandoff(),
        account_resolver=_no_accounts,
        govern_contacts=False,
        storage=storage,
    )
    sweep = handler._sweep  # noqa: SLF001 — the wired RetentionSweep the handler drives
    assert isinstance(sweep, RetentionSweep)
    assert sweep._storage is storage  # noqa: SLF001


class _FakeHandoff:
    phase = ProjectPhase.HANDOFF

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        return PhaseResult(status=PhaseStatus.COMPLETED, cost_cents=Decimal(0), payload={})


# --- (b) the run-drive path binds an ambient sink with the run's workspace_id -------------------


class _SinkObservingHandler:
    """Inner handler that records the ambient snapshot binding it runs under."""

    phase = ProjectPhase.DEEP

    def __init__(self) -> None:
        self.seen_sink: SnapshotSink | None = None
        self.seen_storage: StorageBackend | None = None

    async def run(self, ctx: PhaseContext) -> PhaseResult:
        self.seen_sink = current_snapshot_sink()
        self.seen_storage = current_storage()
        return PhaseResult(status=PhaseStatus.COMPLETED, cost_cents=Decimal(0), payload={})


def test_wrapper_binds_per_run_sink_scoped_to_workspace() -> None:
    storage = FakeStorage()
    inner = _SinkObservingHandler()
    wrapper = SnapshotBindingPhaseHandler(inner=inner, storage=storage)
    # It is a drop-in DEEP handler (delegates ``phase``), so registration is last-write-wins.
    assert wrapper.phase is ProjectPhase.DEEP

    assert current_snapshot_sink() is None  # nothing bound outside a run
    run_async(wrapper.run(_ctx(workspace_id="ws-42")))
    # The inner run saw a per-run sink scoped to the run's workspace, plus the durable backend …
    assert inner.seen_sink is not None
    assert inner.seen_sink.workspace_id == "ws-42"
    assert inner.seen_storage is storage
    # … and the binding is restored (not leaked) after the run.
    assert current_snapshot_sink() is None
    assert current_storage() is None


def test_empty_workspace_id_is_refused() -> None:
    """Fail closed (Fix, B2 review): an empty ``ctx.workspace_id`` would key the run's snapshots
    into the ``public/{sha}`` scope (the sink's public fallback) — a scope-mismatched,
    cross-tenant-public ``artifact`` row, against the workspace-local ruling. The wrapper raises."""
    inner = _SinkObservingHandler()
    wrapper = SnapshotBindingPhaseHandler(inner=inner, storage=FakeStorage())
    with pytest.raises(ValueError, match="workspace"):
        run_async(wrapper.run(_ctx(workspace_id="")))
    # the inner handler never ran, and no binding leaked
    assert inner.seen_sink is None
    assert current_snapshot_sink() is None


def test_each_run_gets_a_fresh_sink() -> None:
    inner = _SinkObservingHandler()
    wrapper = SnapshotBindingPhaseHandler(inner=inner, storage=FakeStorage())
    run_async(wrapper.run(_ctx(workspace_id="ws-a")))
    first = inner.seen_sink
    run_async(wrapper.run(_ctx(workspace_id="ws-b")))
    second = inner.seen_sink
    assert first is not None and second is not None
    assert first is not second
    assert (first.workspace_id, second.workspace_id) == ("ws-a", "ws-b")


# --- (c) the orphan-sweep runner reaches sweep_orphan_blobs with the composed storage -----------


def test_orphan_sweep_runner_uses_the_given_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: dict[str, object] = {}

    async def _purge(conn: object, storage: object, *, privacy_purged_since: object) -> None:
        calls.update(purge_conn=conn, purge_storage=storage, since=privacy_purged_since)

    async def _spy(conn: object, storage: object, *, grace: timedelta, now: object = None) -> tuple:
        assert calls["purge_conn"] is conn
        calls.update(conn=conn, storage=storage, grace=grace)
        return ("public/deadbeef",)

    monkeypatch.setattr(storage_wiring, "sweep_orphan_blobs", _spy)
    monkeypatch.setattr(storage_wiring, "purge_erased_artifacts", _purge)
    conn, storage = object(), FakeStorage()
    result = run_async(run_orphan_blob_sweep(conn, storage=storage))  # type: ignore[arg-type]
    assert result == ("public/deadbeef",)
    assert calls["conn"] is conn
    assert calls["storage"] is storage
    assert calls["purge_storage"] is storage
    assert calls["grace"] == DEFAULT_ORPHAN_SWEEP_GRACE
    assert calls["since"] is None  # the purge's own default look-back


def test_orphan_sweep_runner_defaults_to_the_composed_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sentinel = FakeStorage()
    seen: dict[str, object] = {}

    async def _purge(conn: object, storage: object, *, privacy_purged_since: object) -> None:
        seen["purge_storage"] = storage

    async def _spy(conn: object, storage: object, *, grace: timedelta, now: object = None) -> tuple:
        seen["storage"] = storage
        return ()

    monkeypatch.setattr(storage_wiring, "build_storage_backend", lambda *a, **k: sentinel)
    monkeypatch.setattr(storage_wiring, "sweep_orphan_blobs", _spy)
    monkeypatch.setattr(storage_wiring, "purge_erased_artifacts", _purge)
    run_async(run_orphan_blob_sweep(object()))  # type: ignore[arg-type]
    # storage=None → the runner composes the process backend via build_storage_backend.
    assert seen["storage"] is sentinel
    assert seen["purge_storage"] is sentinel

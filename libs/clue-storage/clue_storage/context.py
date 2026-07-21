"""Run-scoped snapshot binding — the sink/backend travel with the *call context*, never a global.

The audit's finding: a per-run, workspace-bound :class:`~clue_storage.snapshot.SnapshotSink`
must not be stored on anything registered globally (a resolver in the process-wide registry),
or concurrent runs capture into the wrong workspace's sink. The ``Resolver`` protocol is frozen
and synchronous, so the sink can't be threaded as a parameter either. A :class:`~contextvars
.ContextVar` is the mechanism that fits both constraints: the run owner binds the sink (and the
durable backend) around the run —

    async with bind_snapshots(sink, storage):
        ... the whole per-run graph ...

— and every layer below (the waterfall's ``resolve_field``, ``run_pipeline``, the tier-2 scrape
resolver's ``resolve``) reads :func:`current_snapshot_sink` / :func:`current_storage` when no
explicit argument was passed. ContextVars are task-local: two concurrent account runs in one
process each see their own binding (a task spawned inside the ``with`` inherits it), which is
exactly the "request/run-scoped, threaded through the call context" requirement. An explicit
``snapshots=``/``storage=`` argument always beats the ambient binding; with neither, behavior
is the pre-B2 no-snapshotting path.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from clue_storage.protocol import StorageBackend
from clue_storage.snapshot import SnapshotSink

_SNAPSHOT_SINK: ContextVar[SnapshotSink | None] = ContextVar("clue_snapshot_sink", default=None)
_STORAGE: ContextVar[StorageBackend | None] = ContextVar("clue_snapshot_storage", default=None)


def current_snapshot_sink() -> SnapshotSink | None:
    """The run's ambient snapshot sink, or ``None`` outside any :func:`bind_snapshots`."""
    return _SNAPSHOT_SINK.get()


def current_storage() -> StorageBackend | None:
    """The run's ambient durable backend, or ``None`` outside any :func:`bind_snapshots`."""
    return _STORAGE.get()


@contextmanager
def bind_snapshots(
    sink: SnapshotSink | None, storage: StorageBackend | None = None
) -> Iterator[None]:
    """Bind the per-run sink (+ backend) to the current context for the duration of the block.

    The run owner (the api composition root / the per-account graph driver) wraps the run body;
    nested binds shadow and restore. Binding ``None`` explicitly disables snapshotting for the
    block (useful to fence off a sub-scope from an outer binding)."""
    sink_token = _SNAPSHOT_SINK.set(sink)
    storage_token = _STORAGE.set(storage)
    try:
        yield
    finally:
        _STORAGE.reset(storage_token)
        _SNAPSHOT_SINK.reset(sink_token)

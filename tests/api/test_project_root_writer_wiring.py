"""The project mount's writer reads artifacts on the loop it writes on (ruling P3-14).

Offline, and deliberately so: the defect this pins is not about rows, it is about *which
connection factory* a reader was built from, and that is decidable without a database.

The live failure it comes from: the turn runner handed the writer the serving process's
``DurableAgentArtifactStore``, whose default factory is :func:`clue_db.transaction` — an engine
belonging to the worker's own loop. ``ProjectRootWriter.refresh()`` runs on the *bridge* loop and
compiles the library, and compiling reads the artifact index back through that reader. asyncpg
connections belong to the loop that made them, so the read died with ``Task … attached to a
different loop`` while the connection was being torn down — *after* the document row had landed.
The model was told its write succeeded but could not be re-read, and the turn stalled.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncConnection

from clue_api.agent_turn_wiring import DurableAgentArtifactStore
from clue_api.project_root_writer import bridge_bound_artifact_reader, bridge_transaction
from clue_db import transaction
from clue_storage.fs import FsStorage


@asynccontextmanager
async def _nowhere() -> AsyncIterator[AsyncConnection]:
    """A stand-in for "somebody else's factory" — it is only ever compared, never entered."""

    raise AssertionError("this factory exists to be identified, not opened")
    yield  # pragma: no cover - unreachable, and present only to make this a generator


def test_the_bridge_bound_reader_keeps_the_factory_it_was_given(tmp_path: Path) -> None:
    """Whatever factory the writer opens its transactions with, its reader opens the same ones."""

    storage = FsStorage(tmp_path / "blobs")

    reader = bridge_bound_artifact_reader(storage, _nowhere)

    assert isinstance(reader, DurableAgentArtifactStore)
    assert reader._conn_factory is _nowhere


def test_the_bridge_bound_reader_never_defaults_to_the_serving_process_engine(
    tmp_path: Path,
) -> None:
    """The default is the bridge's own factory, because the bridge is the only reason it exists.

    The contrast is the point: the plain reader's default *is* ``clue_db.transaction``, which is
    exactly right for everything that runs on the worker's loop and exactly wrong for anything the
    bridge calls. Building the writer's reader without a factory must not quietly reproduce the
    defect.
    """

    storage = FsStorage(tmp_path / "blobs")

    assert bridge_bound_artifact_reader(storage)._conn_factory is bridge_transaction
    assert bridge_bound_artifact_reader(storage)._conn_factory is not transaction
    # …and the reader the serving process builds is the one that must not reach the bridge.
    assert DurableAgentArtifactStore(storage=storage)._conn_factory is transaction

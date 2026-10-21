from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from pathlib import Path

import pytest

from clue_agents import WorkspaceConfigurationError
from clue_api.agent_workspace_wiring import (
    StorageAgentArtifactSink,
    build_agent_workspace_factory,
)
from clue_config import Settings


class _Storage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def put(self, key: str, data: bytes, *, media_type: str) -> None:
        self.objects[key] = (data, media_type)

    async def get(self, key: str) -> bytes:
        return self.objects[key][0]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)

    async def exists(self, key: str) -> bool:
        return key in self.objects

    async def presign(self, key: str, *, expires_in: int = 3600) -> str:
        return key

    async def list_blobs(self) -> AsyncIterator[tuple[str, datetime]]:
        return
        yield


def _isolated_roots(tmp_path: Path) -> tuple[Path, Path, Path]:
    source = tmp_path / "source"
    home = tmp_path / "home"
    source.mkdir(mode=0o700)
    home.mkdir(mode=0o700)
    return tmp_path / "agent-root", source, home


def test_factory_requires_and_validates_explicit_workspace_root(tmp_path: Path) -> None:
    storage = _Storage()
    with pytest.raises(WorkspaceConfigurationError):
        build_agent_workspace_factory(
            storage=storage,
            settings=Settings(_env_file=None, agent_workspace_root=None),
            source_root=tmp_path,
            home_root=tmp_path,
        )

    root, source, home = _isolated_roots(tmp_path)
    factory = build_agent_workspace_factory(
        storage=storage,
        settings=Settings(_env_file=None, agent_workspace_root=str(root)),
        source_root=source,
        home_root=home,
    )
    try:
        assert root.is_dir()
        assert root.stat().st_mode & 0o777 == 0o700
    finally:
        factory.close()


def test_storage_sink_is_workspace_scoped_content_addressed_and_idempotent() -> None:
    storage = _Storage()
    sink = StorageAgentArtifactSink(storage)

    import asyncio

    first = asyncio.run(
        sink.persist(
            workspace_id="ws-1",
            logical_path="outputs/report.md",
            data=b"final",
            media_type="text/markdown",
        )
    )
    second = asyncio.run(
        sink.persist(
            workspace_id="ws-1",
            logical_path="outputs/report.md",
            data=b"final",
            media_type="text/markdown",
        )
    )

    assert first == second
    assert first.artifact_key == f"ws-1/{first.sha256}"
    assert storage.objects[first.artifact_key] == (b"final", "text/markdown")


@pytest.mark.parametrize("path", ["work/note.md", "../outputs/report.md", "/outputs/report.md"])
def test_storage_sink_rejects_non_output_or_hostile_paths(path: str) -> None:
    import asyncio

    with pytest.raises((ValueError, WorkspaceConfigurationError)):
        asyncio.run(
            StorageAgentArtifactSink(_Storage()).persist(
                workspace_id="ws-1",
                logical_path=path,
                data=b"no",
                media_type="text/plain",
            )
        )


# --- F3 Phase 1, plan Task 9 (WS-15, WS-21; AW-19) --------------------------------------------


def test_the_factory_roots_in_this_process_area_when_snapshots_are_on(tmp_path: Path) -> None:
    root, source, home = _isolated_roots(tmp_path)
    factory = build_agent_workspace_factory(
        storage=_Storage(),
        settings=Settings(
            _env_file=None, agent_workspace_root=str(root), agent_workspace_snapshots_enabled=True
        ),
        source_root=source,
        home_root=home,
    )
    try:
        assert factory.area is not None
        assert factory.root_path == root / "workers" / factory.area.name
        assert factory.root_path.is_dir()
    finally:
        factory.close()
        if factory.area is not None:
            factory.area.close()


def test_the_factory_uses_a_local_root_when_snapshots_are_off(tmp_path: Path) -> None:
    root, source, home = _isolated_roots(tmp_path)
    factory = build_agent_workspace_factory(
        storage=_Storage(),
        settings=Settings(
            _env_file=None, agent_workspace_root=str(root), agent_workspace_snapshots_enabled=False
        ),
        source_root=source,
        home_root=home,
    )
    try:
        # An unlocked area over the shared local folder, so the cache sweep can still tell which
        # chats this process is using (snapshots off keeps folders a day, not 30 minutes).
        assert factory.area is not None
        assert factory.area.name == "local"
        assert factory.area.path == root / "local"
        assert factory.root_path == root / "local"
    finally:
        factory.close()


def test_every_acquire_site_restores_and_saves() -> None:
    """No caller in the platform takes a bare workspace lease: every one goes through the hook."""

    import re

    platform = Path(__file__).resolve().parents[2] / "platform" / "api" / "clue_api"
    offenders = []
    for path in platform.rglob("*.py"):
        text = path.read_text()
        for match in re.finditer(r"workspaces\.acquire\(|\.workspaces\.acquire\(", text):
            offenders.append(f"{path.name}:{text[: match.start()].count(chr(10)) + 1}")
    assert offenders == []

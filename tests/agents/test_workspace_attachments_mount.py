from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from clue_agents import (
    AgentWorkspaceFactory,
    AgentWorkspaceLease,
    AnchoredAgentWorkspaceBackend,
    MountRequest,
    WorkspaceConfigurationError,
    WorkspaceSecurityError,
)
from clue_agents.worker_area import ChatScope
from tests.agents.workspace_helpers import (
    DEFAULT_READABLE_PREFIXES,
    EXECUTION_ID,
    make_factory,
    policy,
)

_WORKSPACE_ID = "ws-1"
_PROJECT_ID = "project-1"
_THREAD_ID = "thread-1"


def _acquire(factory: AgentWorkspaceFactory, *, readable: tuple[str, ...]) -> AgentWorkspaceLease:
    return factory.acquire(
        workspace_id=_WORKSPACE_ID,
        project_id=_PROJECT_ID,
        thread_id=_THREAD_ID,
        execution_id=EXECUTION_ID,
        policy=policy(readable=readable),
        mounts=MountRequest(attachments=True),
    )


def _mount_names(backend: AnchoredAgentWorkspaceBackend) -> set[str]:
    """The mount roots the model sees at the workspace root, as ``ls`` reports them."""

    entries = backend.ls("/").entries or []
    return {entry["path"] for entry in entries if entry["is_dir"]}


def test_attachments_mount_is_read_only_optional_and_readable(tmp_path: Path) -> None:
    """The ``attachments`` mount is absent when nothing was uploaded, read-only when it is not.

    One acquire per case, because the live-lease table refuses a second lease over the same
    thread and the mount table is fixed at acquire time — which is the point: the directory the
    fleet's sync wrote before the turn is the directory this turn reads.
    """

    _root, factory, _sink = make_factory(tmp_path)
    try:
        # 1. No directory on disk → the request is honoured by mounting nothing, not by failing.
        lease = _acquire(factory, readable=DEFAULT_READABLE_PREFIXES)
        try:
            assert "attachments" not in _mount_names(lease.backend)
        finally:
            lease.release()

        # 2. The fleet's sync writes the bytes into the chat's own folder, beside its agent root.
        chat_dir = factory.chat_host_path(ChatScope(_WORKSPACE_ID, _PROJECT_ID, _THREAD_ID))
        attachments = chat_dir / "attachments"
        attachments.mkdir(mode=0o700, parents=True)
        (attachments / "brief.md").write_text("# brief\n")
        (attachments / "r.pdf").write_bytes(b"%PDF-1.4\xff\xfe")
        os.chmod(attachments / "brief.md", 0o400)
        os.chmod(attachments / "r.pdf", 0o400)

        lease = _acquire(factory, readable=(*DEFAULT_READABLE_PREFIXES, "attachments"))
        try:
            assert "attachments" in _mount_names(lease.backend)
            names = {entry.path for entry in asyncio.run(lease.backend.list_entries("attachments"))}
            assert {"attachments/brief.md", "attachments/r.pdf"} <= names
            assert asyncio.run(lease.backend.read_text("attachments/brief.md")) == "# brief\n"
            # A binary attachment is listed and byte-identical on disk, but it is not text: the
            # text read refuses it rather than returning mojibake.
            with pytest.raises(WorkspaceSecurityError):
                asyncio.run(lease.backend.read_text("attachments/r.pdf"))
            assert (attachments / "r.pdf").read_bytes() == b"%PDF-1.4\xff\xfe"
            # Read-only: the model may not add to, or overwrite, what the human uploaded.
            with pytest.raises(WorkspaceSecurityError):
                asyncio.run(lease.backend.write_text("attachments/x.md", "no"))
            # A read-only mount is readable but never charged: the human's uploads must not
            # spend the agent's own file/byte budget.
            assert lease.usage_snapshot().file_count == 0
            # The mount is never copied into the thread root.
            thread_dir = factory.thread_host_path(_WORKSPACE_ID, _PROJECT_ID, _THREAD_ID)
            assert thread_dir.is_dir()
            assert not (thread_dir / "attachments").exists()
        finally:
            lease.release()
    finally:
        factory.close()


def test_host_path_accessors_name_the_real_directories_and_validate_segments(
    tmp_path: Path,
) -> None:
    """The Docker runner bind-mounts these paths, so they must be the factory's own layout."""

    root, factory, _sink = make_factory(tmp_path)
    try:
        assert factory.root_path == root
        chat = ChatScope(_WORKSPACE_ID, _PROJECT_ID, _THREAD_ID)
        assert factory.chat_host_path(chat) == (
            root / "chats" / _WORKSPACE_ID / _PROJECT_ID / _THREAD_ID
        )
        assert factory.thread_host_path(_WORKSPACE_ID, _PROJECT_ID, _THREAD_ID) == (
            factory.chat_host_path(chat) / "agent"
        )
        lease = factory.acquire(
            workspace_id=_WORKSPACE_ID,
            project_id=_PROJECT_ID,
            thread_id=_THREAD_ID,
            execution_id=EXECUTION_ID,
            policy=policy(),
        )
        try:
            assert lease.workspace_segment == _WORKSPACE_ID
            assert lease.project_segment == _PROJECT_ID
            assert lease.thread_segment == _THREAD_ID
            assert factory.thread_host_path(
                lease.workspace_segment,
                lease.project_segment,
                lease.thread_segment,
            ).is_dir()
        finally:
            lease.release()

        # A host path is built from validated segments, so it can never leave the root.
        for bad in ("../escape", "ws/../..", "", ".."):
            with pytest.raises(WorkspaceConfigurationError):
                factory.chat_host_path(ChatScope(bad, _PROJECT_ID, _THREAD_ID))
    finally:
        factory.close()

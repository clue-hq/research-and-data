from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from clue_agents import (
    AgentWorkspaceFactory,
    AgentWorkspaceLease,
    MountRequest,
    WorkspaceConfigurationError,
    WorkspacePolicy,
)
from clue_api.sandbox.workspaces import (
    RunBudgetExhausted,
    SandboxMounts,
    SandboxWorkspaces,
    sandbox_mounts_for_lease,
)
from clue_core import ExecutionId
from tests.agents.workspace_helpers import DEFAULT_READABLE_PREFIXES, make_factory, policy

_EXECUTION = ExecutionId(UUID("00000000-0000-0000-0000-0000000007a1"))
_OTHER_EXECUTION = ExecutionId(UUID("00000000-0000-0000-0000-0000000007a2"))
_WORKSPACE_ID = "ws-1"
_PROJECT_ID = "project-1"
_THREAD_ID = "thread-1"


def _mounts(tmp_path: Path) -> SandboxMounts:
    workspace_policy = WorkspacePolicy(
        virtual_mode=True,
        max_total_bytes=20_971_520,
        max_file_bytes=1_048_576,
        max_file_count=400,
        allowed_extensions=(".md",),
        readable_prefixes=("scratch",),
        writable_prefixes=("scratch",),
        retention_class="agent-ephemeral-v1",
    )
    return SandboxMounts(
        thread_root=tmp_path,
        read_only={"inputs": tmp_path / "inputs"},
        read_write={"scratch": tmp_path / "scratch"},
        policy=workspace_policy,
    )


def test_register_take_release(tmp_path: Path) -> None:
    """One turn's registration, its run budget, and the release that ends both."""

    registry = SandboxWorkspaces(max_runs_per_turn=2)
    assert registry.mounts_for(_EXECUTION) is None
    # An unknown execution has no budget at all: the tool refuses rather than running unmetered.
    assert registry.runs_remaining(_EXECUTION) == 0
    with pytest.raises(RunBudgetExhausted):
        registry.take_run(_EXECUTION)

    registry.register(_EXECUTION, _mounts(tmp_path))
    with pytest.raises(ValueError):
        registry.register(_EXECUTION, _mounts(tmp_path))
    assert registry.mounts_for(_EXECUTION) is not None
    assert registry.runs_remaining(_EXECUTION) == 2
    assert registry.take_run(_EXECUTION) == 1
    assert registry.take_run(_EXECUTION) == 0
    with pytest.raises(RunBudgetExhausted):
        registry.take_run(_EXECUTION)

    # One execution's exhausted budget is not another's.
    registry.register(_OTHER_EXECUTION, _mounts(tmp_path))
    assert registry.runs_remaining(_OTHER_EXECUTION) == 2

    registry.release(_EXECUTION)
    registry.release(_EXECUTION)
    assert registry.mounts_for(_EXECUTION) is None
    assert registry.runs_remaining(_OTHER_EXECUTION) == 2
    # The registration is gone, so re-registering the same turn is allowed again (crash resume).
    registry.register(_EXECUTION, _mounts(tmp_path))
    assert registry.runs_remaining(_EXECUTION) == 2


def _acquire(factory: AgentWorkspaceFactory, active_policy: WorkspacePolicy) -> AgentWorkspaceLease:
    return factory.acquire(
        workspace_id=_WORKSPACE_ID,
        project_id=_PROJECT_ID,
        thread_id=_THREAD_ID,
        execution_id=_EXECUTION,
        policy=active_policy,
        mounts=MountRequest(attachments=True),
    )


def test_sandbox_mounts_for_lease_names_the_leases_own_host_directories(tmp_path: Path) -> None:
    """The container is bind-mounted from these paths, so they must be the factory's own layout.

    The mount set is derived, never guessed: the thread's layout folders always exist under a
    live lease, and ``attachments`` is present only when the project actually has uploads.
    """

    root, factory, _sink = make_factory(tmp_path)
    try:
        active_policy = policy(readable=(*DEFAULT_READABLE_PREFIXES, "attachments"))
        lease = _acquire(factory, active_policy)
        try:
            thread = root / _WORKSPACE_ID / "projects" / _PROJECT_ID / "threads" / _THREAD_ID
            project = root / _WORKSPACE_ID / "projects" / _PROJECT_ID

            mounts = sandbox_mounts_for_lease(
                lease,
                factory,
                brand=None,
                project_library=False,
                attachments=True,
            )
            assert mounts.thread_root == thread
            assert mounts.read_write == {
                "scratch": thread / "scratch",
                "work": thread / "work",
                "outputs": thread / "outputs",
            }
            # Nothing was uploaded, so the attachments directory does not exist and is not mounted.
            assert mounts.read_only == {
                "inputs": thread / "inputs",
                "context": thread / "context",
                "reads": thread / "reads",
            }
            assert all(path.is_dir() for path in mounts.read_write.values())
            assert all(path.is_dir() for path in mounts.read_only.values())
            assert mounts.policy == active_policy

            (project / "attachments").mkdir(mode=0o700)
            (project / "library").mkdir(mode=0o700)
            brand = root / _WORKSPACE_ID / "library" / "brand" / "brand-1" / "v1"
            brand.mkdir(mode=0o700, parents=True)

            mounts = sandbox_mounts_for_lease(
                lease,
                factory,
                brand=("brand-1", "v1"),
                project_library=True,
                attachments=True,
            )
            assert mounts.read_only["attachments"] == project / "attachments"
            assert mounts.read_only["project"] == project / "library"
            assert mounts.read_only["brand"] == brand

            # The mount map is read-only: a caller cannot widen one turn's container.
            with pytest.raises(TypeError):
                mounts.read_only["escape"] = root  # type: ignore[index]

            # A brand id is a validated segment, so a mount path can never leave the root.
            with pytest.raises(WorkspaceConfigurationError):
                sandbox_mounts_for_lease(
                    lease,
                    factory,
                    brand=("../escape", "v1"),
                    project_library=False,
                    attachments=False,
                )
        finally:
            lease.release()
    finally:
        factory.close()


def test_an_attachments_symlink_is_not_mounted(tmp_path: Path) -> None:
    """A link where the attachments directory should be is treated as no attachments at all.

    The factory opens every mount with ``O_NOFOLLOW``; a bind mount is a path, so the same
    refusal has to be made here, or a link would carry the container outside the root.
    """

    root, factory, _sink = make_factory(tmp_path)
    try:
        lease = _acquire(factory, policy())
        try:
            elsewhere = tmp_path / "elsewhere"
            elsewhere.mkdir(mode=0o700)
            project = root / _WORKSPACE_ID / "projects" / _PROJECT_ID
            (project / "attachments").symlink_to(elsewhere, target_is_directory=True)

            mounts = sandbox_mounts_for_lease(
                lease, factory, brand=None, project_library=False, attachments=True
            )
            assert "attachments" not in mounts.read_only
        finally:
            lease.release()
    finally:
        factory.close()


def test_a_pinned_project_tree_is_the_tree_the_sandbox_mounts(tmp_path: Path) -> None:
    """A replayed turn mounts its pinned generation, never the live library.

    The fleet materializes a superseded generation beside the library as ``pinned-<turn>`` and
    passes that name on ``MountRequest.project_library_name``; the script has to read the same
    tree the model's own file tools read, or the two would see different projects.
    """

    root, factory, _sink = make_factory(tmp_path)
    try:
        lease = _acquire(factory, policy())
        try:
            project = root / _WORKSPACE_ID / "projects" / _PROJECT_ID
            mounts = sandbox_mounts_for_lease(
                lease,
                factory,
                brand=None,
                project_library=True,
                project_library_name="pinned-0123456789ab",
                attachments=False,
            )
            assert mounts.read_only["project"] == project / "pinned-0123456789ab"
            # The default is the project's shared library, which is what an ordinary turn reads.
            assert (
                sandbox_mounts_for_lease(
                    lease, factory, brand=None, project_library=True, attachments=False
                ).read_only["project"]
                == project / "library"
            )
            # The tree name is one validated segment, so it can never become a path.
            with pytest.raises(WorkspaceConfigurationError):
                sandbox_mounts_for_lease(
                    lease,
                    factory,
                    brand=None,
                    project_library=True,
                    project_library_name="../escape",
                    attachments=False,
                )
        finally:
            lease.release()
    finally:
        factory.close()

"""Where a sandboxed run finds its workspace on the host, and how much budget it has left.

``ToolContext`` carries ids, never handles, so the ``run_python@1`` tool cannot be given the
turn's workspace lease. The conversation engine instead registers the host directories it
derived from that lease here, keyed by execution id, at the same point it binds the spill sink,
and releases them when the turn ends. The tool looks the turn up by its execution id: an id
nobody registered has no directories and no budget, which is exactly the refusal the spec asks
for (``workspace_unavailable`` / ``run_budget_exhausted``) rather than a run over a guessed path.

Nothing here opens, creates or reads a file. The paths are derived from already-validated
segments — the same segments the factory walked when it opened the lease's descriptors — so a
mount can name the thread's own tree and the project's read-only trees, and can name nothing
else.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Final

from clue_agents.contracts import WorkspacePolicy
from clue_agents.workspace import (
    ATTACHMENTS_DIR,
    AgentWorkspaceFactory,
    AgentWorkspaceLease,
)
from clue_agents.workspace_policy import validate_workspace_segment
from clue_core import ExecutionId

__all__ = [
    "READ_ONLY_THREAD_DIRS",
    "READ_WRITE_THREAD_DIRS",
    "RunBudgetExhausted",
    "SandboxMounts",
    "SandboxWorkspaces",
    "sandbox_mounts_for_lease",
]

#: The thread layout folders the container may write, and the ones it may only read. Both are
#: subsets of :data:`clue_agents.workspace._LAYOUT`, which the factory creates under every lease,
#: so a live lease always has all six on disk. ``.deepagent`` is deliberately absent: the pinned
#: profile, prompt and skills are the runtime's, not the script's.
READ_WRITE_THREAD_DIRS: Final = ("scratch", "work", "outputs")
READ_ONLY_THREAD_DIRS: Final = ("inputs", "context", "reads")
#: The workspace-wide library tree brand generations live under, mirroring the chain
#: ``AgentWorkspaceFactory._open_mounts`` walks for ``MountRequest.brand``.
_BRAND_DIR: Final = "brand"


class RunBudgetExhausted(RuntimeError):
    """This turn has no run left — including the turn that was never registered."""


@dataclass(frozen=True, slots=True)
class SandboxMounts:
    """One turn's host directories and the policy every sandbox-written file answers to."""

    #: ``<chat folder>/agent`` — the lease's own directory.
    thread_root: Path
    #: name → host directory, mounted read-only at ``/workspace/<name>``.
    read_only: Mapping[str, Path]
    #: name → host directory, mounted read-write at ``/workspace/<name>``.
    read_write: Mapping[str, Path]
    #: The profile's workspace contract: the quotas and extensions the post-run sweep enforces.
    policy: WorkspacePolicy
    #: Writes one output spill into ``reads/`` through the workspace, inside its quota (F3 §12);
    #: ``None`` only for mounts built by hand, which then spill nothing.
    spill: Callable[[str, bytes], str] | None = None
    #: The worker area whose label the container carries, so a restarted worker can kill what a
    #: dead run of its own left behind (AW-19).
    area: str | None = None

    def __post_init__(self) -> None:
        # The maps are the container's authority. Freezing them here means a caller that holds
        # a SandboxMounts cannot widen the run it is about to start.
        object.__setattr__(self, "read_only", MappingProxyType(dict(self.read_only)))
        object.__setattr__(self, "read_write", MappingProxyType(dict(self.read_write)))


@dataclass(slots=True)
class _Registration:
    mounts: SandboxMounts
    runs_remaining: int


class SandboxWorkspaces:
    """The live turns' sandbox workspaces, and what is left of each turn's run budget.

    Registration happens on the worker loop while the lease is held; ``take_run`` is called from
    the tool's own thread, so every read and write here takes the lock.
    """

    def __init__(self, *, max_runs_per_turn: int) -> None:
        if max_runs_per_turn < 0:
            raise ValueError("max_runs_per_turn cannot be negative")
        self.max_runs_per_turn = max_runs_per_turn
        self._lock = threading.Lock()
        self._live: dict[ExecutionId, _Registration] = {}

    def register(self, execution_id: ExecutionId, mounts: SandboxMounts) -> None:
        """Bind this execution's host directories for the life of the turn."""

        with self._lock:
            if execution_id in self._live:
                raise ValueError("this execution already has a registered sandbox workspace")
            self._live[execution_id] = _Registration(
                mounts=mounts, runs_remaining=self.max_runs_per_turn
            )

    def release(self, execution_id: ExecutionId) -> None:
        """End the binding. Idempotent: the turn's cleanup runs on more than one path."""

        with self._lock:
            self._live.pop(execution_id, None)

    # --- the workspace factory's turn binding (F3, WS-14) ---------------------------------------

    def bind(self, execution_id: ExecutionId, lease: AgentWorkspaceLease) -> None:
        """Register the lease's own mounts. A re-acquire of the same execution keeps its budget."""

        mounts = sandbox_mounts_for_lease(
            lease,
            lease.factory,
            brand=lease.mounts.brand,
            project_library=lease.mounts.project_library,
            attachments=lease.mounts.attachments,
        )
        with self._lock:
            existing = self._live.get(execution_id)
            if existing is not None:
                existing.mounts = mounts
                return
            self._live[execution_id] = _Registration(
                mounts=mounts, runs_remaining=self.max_runs_per_turn
            )

    def unbind(self, execution_id: ExecutionId) -> None:
        self.release(execution_id)

    def mounts_for(self, execution_id: ExecutionId) -> SandboxMounts | None:
        """This execution's directories, or ``None`` when no turn registered them."""

        with self._lock:
            registration = self._live.get(execution_id)
        return None if registration is None else registration.mounts

    def take_run(self, execution_id: ExecutionId) -> int:
        """Spend one run and return how many remain.

        An unregistered execution raises rather than returning a budget: a turn nobody bound
        cannot be metered, so it does not get to run.
        """

        with self._lock:
            registration = self._live.get(execution_id)
            if registration is None or registration.runs_remaining <= 0:
                raise RunBudgetExhausted("this turn has no sandbox run left")
            registration.runs_remaining -= 1
            return registration.runs_remaining

    def runs_remaining(self, execution_id: ExecutionId) -> int:
        """How many runs this turn may still take; zero when it is unregistered."""

        with self._lock:
            registration = self._live.get(execution_id)
        return 0 if registration is None else registration.runs_remaining


def sandbox_mounts_for_lease(
    lease: AgentWorkspaceLease,
    workspaces: AgentWorkspaceFactory,
    *,
    brand: tuple[str, str] | None,
    project_library: bool,
    attachments: bool,
) -> SandboxMounts:
    """Derive one turn's container mounts from the lease the turn already holds.

    The arguments mirror the :class:`~clue_agents.workspace.MountRequest` the lease was acquired
    with, so the script sees the same ``brand/``, ``project/`` and ``attachments/`` paths the
    model's own file tools see: the chat's own copies, in the chat's own folder (F3, WS-37).

    ``attachments`` is the one optional directory — a project nobody has uploaded to has none,
    which is the ordinary state of a new project — so it is mounted only when it exists, exactly
    as the mount table treats it.
    """

    chat_dir = workspaces.chat_host_path(lease.chat)
    thread_root = workspaces.thread_host_path(
        lease.workspace_segment, lease.project_segment, lease.thread_segment
    )
    read_only: dict[str, Path] = {name: thread_root / name for name in READ_ONLY_THREAD_DIRS}
    if brand is not None:
        brand_id, knowledge_version = brand
        validate_workspace_segment(brand_id, label="brand_id")
        validate_workspace_segment(knowledge_version, label="brand_version")
        read_only["brand"] = chat_dir / _BRAND_DIR
    if project_library:
        read_only["project"] = chat_dir / "project"
    attachments_dir = chat_dir / ATTACHMENTS_DIR
    # The factory opens every mount with O_NOFOLLOW; a bind mount must not follow a link out of
    # the root either, so a link where the directory should be is treated as no directory.
    if attachments and attachments_dir.is_dir() and not attachments_dir.is_symlink():
        read_only["attachments"] = attachments_dir
    return SandboxMounts(
        thread_root=thread_root,
        read_only=read_only,
        read_write={name: thread_root / name for name in READ_WRITE_THREAD_DIRS},
        policy=lease.backend.policy,
        spill=lease.backend.write_spill_file,
        area=None if workspaces.area is None else workspaces.area.name,
    )

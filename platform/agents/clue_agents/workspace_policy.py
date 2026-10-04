"""Trusted host-root and logical-identity policy for C6 agent workspaces."""

from __future__ import annotations

import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path

__all__ = [
    "PreparedWorkspaceRoot",
    "WorkspaceConfigurationError",
    "WorkspaceConflict",
    "WorkspaceError",
    "WorkspaceQuotaExceeded",
    "WorkspaceRootPolicy",
    "WorkspaceSecurityError",
    "validate_workspace_segment",
]

_SEGMENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_PRIVATE_DIR_MODE = 0o700


class WorkspaceError(RuntimeError):
    """Base error for the isolated agent-workspace subsystem."""


class WorkspaceConfigurationError(WorkspaceError):
    """The trusted deployment root or identity is unsafe."""


class WorkspaceSecurityError(WorkspaceError):
    """A logical path, filesystem object, or permission violates isolation."""


class WorkspaceQuotaExceeded(WorkspaceError):
    """A write would exceed the immutable workspace quota envelope."""


class WorkspaceConflict(WorkspaceError):
    """A one-shot workspace or file identity already exists."""


def validate_workspace_segment(value: str, *, label: str) -> str:
    """Return one safe directory segment derived from trusted typed identity."""

    if not isinstance(value, str) or not _SEGMENT.fullmatch(value):
        raise WorkspaceConfigurationError(
            f"{label} must be a non-empty ASCII identifier containing only letters, "
            "numbers, dot, underscore, or hyphen"
        )
    if value in {".", ".."}:
        raise WorkspaceConfigurationError(f"{label} must not be a dot path component")
    return value


def _paths_related(left: Path, right: Path) -> bool:
    return left == right or left.is_relative_to(right) or right.is_relative_to(left)


def _private_directory(stat_result: os.stat_result, *, label: str) -> None:
    if not stat.S_ISDIR(stat_result.st_mode):
        raise WorkspaceConfigurationError(f"{label} must be a real directory")
    if stat_result.st_mode & 0o077:
        raise WorkspaceConfigurationError(f"{label} must not grant group or other permissions")
    if hasattr(os, "getuid") and stat_result.st_uid != os.getuid():
        raise WorkspaceConfigurationError(f"{label} must be owned by the service user")


@dataclass(frozen=True, slots=True)
class PreparedWorkspaceRoot:
    """Trusted host-only root. It is never placed in model state or agent-facing errors."""

    path: Path


@dataclass(frozen=True, slots=True)
class WorkspaceRootPolicy:
    """Validate and prepare the dedicated external production root.

    Only the final root component may be created. Requiring an existing parent prevents an
    environment typo from recursively constructing an unexpected host path.
    """

    configured_root: Path
    source_root: Path
    home_root: Path

    def prepare(self) -> PreparedWorkspaceRoot:
        if not self.configured_root.is_absolute():
            raise WorkspaceConfigurationError("CLUE_AGENT_WORKSPACE_ROOT must be absolute")
        if self.configured_root == Path(self.configured_root.anchor):
            raise WorkspaceConfigurationError("the filesystem root cannot be an agent workspace")

        try:
            source = self.source_root.resolve(strict=True)
            home = self.home_root.resolve(strict=True)
            parent = self.configured_root.parent.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceConfigurationError(
                "workspace, source, and home parents must already exist"
            ) from exc

        candidate = parent / self.configured_root.name
        if candidate != self.configured_root:
            raise WorkspaceConfigurationError(
                "agent workspace root path must not traverse links or dot components"
            )
        if _paths_related(candidate, source):
            raise WorkspaceConfigurationError(
                "agent workspace root must be unrelated to the source worktree"
            )
        if _paths_related(candidate, home):
            raise WorkspaceConfigurationError(
                "agent workspace root must be unrelated to the service home"
            )

        try:
            root_lstat = candidate.lstat()
        except FileNotFoundError:
            try:
                os.mkdir(candidate, _PRIVATE_DIR_MODE)
                os.chmod(candidate, _PRIVATE_DIR_MODE)
            except OSError as exc:
                raise WorkspaceConfigurationError(
                    "agent workspace root could not be created"
                ) from exc
            root_lstat = candidate.lstat()
        except OSError as exc:
            raise WorkspaceConfigurationError(
                "agent workspace root could not be inspected"
            ) from exc

        if stat.S_ISLNK(root_lstat.st_mode):
            raise WorkspaceConfigurationError("agent workspace root must not be a symbolic link")
        _private_directory(root_lstat, label="agent workspace root")
        if stat.S_IMODE(root_lstat.st_mode) != _PRIVATE_DIR_MODE:
            raise WorkspaceConfigurationError("agent workspace root must have mode 0700")

        try:
            canonical = candidate.resolve(strict=True)
        except OSError as exc:
            raise WorkspaceConfigurationError("agent workspace root could not be resolved") from exc
        if canonical != candidate:
            raise WorkspaceConfigurationError("agent workspace root must not traverse a link")
        if _paths_related(canonical, source) or _paths_related(canonical, home):
            raise WorkspaceConfigurationError("agent workspace root violates host isolation")

        try:
            with os.scandir(canonical) as entries:
                for entry in entries:
                    entry_stat = entry.stat(follow_symlinks=False)
                    if entry.is_symlink():
                        raise WorkspaceConfigurationError(
                            "agent workspace root contains an unexpected link"
                        )
                    # Named, so a refusal points at the offending entry: production 2026-10-04,
                    # a 0755 design-agent directory crash-looped every fleet worker, and finding
                    # it took a shell on the VM.
                    label = f"workspace scope directory {entry.name!r}"
                    _private_directory(entry_stat, label=label)
                    if stat.S_IMODE(entry_stat.st_mode) != _PRIVATE_DIR_MODE:
                        raise WorkspaceConfigurationError(f"{label} must have mode 0700")
        except WorkspaceConfigurationError:
            raise
        except OSError as exc:
            raise WorkspaceConfigurationError("agent workspace root could not be audited") from exc

        return PreparedWorkspaceRoot(path=canonical)

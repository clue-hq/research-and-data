from __future__ import annotations

import os
from pathlib import Path

import pytest

from clue_agents import (
    WorkspaceConfigurationError,
    WorkspaceRootPolicy,
)
from clue_agents.workspace_policy import validate_workspace_segment


def _roots(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "source"
    home = tmp_path / "home"
    source.mkdir(mode=0o700)
    home.mkdir(mode=0o700)
    return source, home


def test_root_is_created_private_and_only_at_an_existing_parent(tmp_path: Path) -> None:
    source, home = _roots(tmp_path)
    root = tmp_path / "runtime"

    prepared = WorkspaceRootPolicy(root, source, home).prepare()

    assert prepared.path == root
    assert root.stat().st_mode & 0o777 == 0o700
    with pytest.raises(WorkspaceConfigurationError):
        WorkspaceRootPolicy(tmp_path / "missing" / "runtime", source, home).prepare()


@pytest.mark.parametrize("relation", ["equal", "inside", "ancestor"])
def test_root_must_be_unrelated_to_source_and_home(tmp_path: Path, relation: str) -> None:
    source, home = _roots(tmp_path)
    if relation == "equal":
        configured = source
    elif relation == "inside":
        configured = source / "runtime"
    else:
        configured = tmp_path

    with pytest.raises(WorkspaceConfigurationError):
        WorkspaceRootPolicy(configured, source, home).prepare()

    with pytest.raises(WorkspaceConfigurationError):
        WorkspaceRootPolicy(home / "runtime", source, home).prepare()


def test_root_rejects_relative_link_permissive_and_unexpected_entries(tmp_path: Path) -> None:
    source, home = _roots(tmp_path)
    with pytest.raises(WorkspaceConfigurationError):
        WorkspaceRootPolicy(Path("relative"), source, home).prepare()

    target = tmp_path / "target"
    target.mkdir(mode=0o700)
    link = tmp_path / "runtime-link"
    link.symlink_to(target, target_is_directory=True)
    with pytest.raises(WorkspaceConfigurationError):
        WorkspaceRootPolicy(link, source, home).prepare()

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir(mode=0o700)
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    with pytest.raises(WorkspaceConfigurationError):
        WorkspaceRootPolicy(linked_parent / "runtime", source, home).prepare()

    permissive = tmp_path / "permissive"
    permissive.mkdir(mode=0o755)
    with pytest.raises(WorkspaceConfigurationError):
        WorkspaceRootPolicy(permissive, source, home).prepare()

    unexpected = tmp_path / "unexpected"
    unexpected.mkdir(mode=0o700)
    (unexpected / "file").write_text("not a scope")
    with pytest.raises(WorkspaceConfigurationError):
        WorkspaceRootPolicy(unexpected, source, home).prepare()


@pytest.mark.parametrize(
    "value",
    ["", ".", "..", "../ws", "ws/project", "ws\\project", "ws space", "é", "a" * 129],
)
def test_workspace_identity_segments_fail_closed(value: str) -> None:
    with pytest.raises(WorkspaceConfigurationError):
        validate_workspace_segment(value, label="workspace_id")


def test_root_rejects_group_permissions_even_under_umask(tmp_path: Path) -> None:
    source, home = _roots(tmp_path)
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    os.chmod(root, 0o710)
    with pytest.raises(WorkspaceConfigurationError):
        WorkspaceRootPolicy(root, source, home).prepare()

    os.chmod(root, 0o500)
    with pytest.raises(WorkspaceConfigurationError):
        WorkspaceRootPolicy(root, source, home).prepare()


def test_a_permissive_scope_entry_is_named_in_the_refusal(tmp_path: Path) -> None:
    """Production 2026-10-04: a 0755 entry crash-looped every fleet worker, and the refusal did not
    say WHICH entry — finding it took a shell on the VM."""
    source, home = _roots(tmp_path)
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    (root / "lumen-agent").mkdir(mode=0o700)
    os.chmod(root / "lumen-agent", 0o755)
    with pytest.raises(WorkspaceConfigurationError, match="'lumen-agent'"):
        WorkspaceRootPolicy(root, source, home).prepare()

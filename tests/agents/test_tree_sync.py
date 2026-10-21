"""F3 Phase 1, plan Task 4: ``sync_directory`` writes only new or changed files.

Spec WS-36, WS-37.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from clue_agents.tree_sync import TreeSyncReport, sync_directory
from clue_agents.workspace_policy import WorkspaceSecurityError

FILES = {
    "manifest.json": b"{}",
    "project/budget.json": b'{"spent": 4.2}',
    "project/card.json": b'{"name": "x"}',
}


def _parent(tmp_path: Path) -> int:
    root = tmp_path / "chat"
    root.mkdir(mode=0o700)
    return os.open(root, os.O_RDONLY | os.O_DIRECTORY)


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_first_sync_writes_everything(tmp_path: Path) -> None:
    parent = _parent(tmp_path)
    try:
        report = sync_directory(parent, "context", FILES, frozen=False)
    finally:
        os.close(parent)
    assert report == TreeSyncReport(written=tuple(sorted(FILES)), removed=(), unchanged=0)
    assert (tmp_path / "chat/context/project/budget.json").read_bytes() == b'{"spent": 4.2}'


def test_second_sync_with_same_files_writes_nothing(tmp_path: Path) -> None:
    parent = _parent(tmp_path)
    try:
        sync_directory(parent, "context", FILES, frozen=False)
        before = (tmp_path / "chat/context/project/card.json").stat().st_ino
        report = sync_directory(parent, "context", FILES, frozen=False)
    finally:
        os.close(parent)
    assert report == TreeSyncReport(written=(), removed=(), unchanged=3)
    assert (tmp_path / "chat/context/project/card.json").stat().st_ino == before


def test_changed_file_is_replaced_only(tmp_path: Path) -> None:
    parent = _parent(tmp_path)
    try:
        sync_directory(parent, "context", FILES, frozen=False)
        changed = {**FILES, "project/budget.json": b'{"spent": 6.1}'}
        report = sync_directory(parent, "context", changed, frozen=False)
    finally:
        os.close(parent)
    assert report.written == ("project/budget.json",)
    assert report.unchanged == 2
    assert (tmp_path / "chat/context/project/budget.json").read_bytes() == b'{"spent": 6.1}'


def test_missing_file_is_removed_and_empty_dirs_pruned(tmp_path: Path) -> None:
    parent = _parent(tmp_path)
    try:
        sync_directory(parent, "context", FILES, frozen=False)
        report = sync_directory(parent, "context", {"manifest.json": b"{}"}, frozen=False)
    finally:
        os.close(parent)
    assert report.removed == ("project/budget.json", "project/card.json")
    assert not (tmp_path / "chat/context/project").exists()


def test_frozen_tree_ends_read_only_and_can_be_synced_again(tmp_path: Path) -> None:
    parent = _parent(tmp_path)
    try:
        sync_directory(parent, "context", FILES, frozen=True)
        assert _mode(tmp_path / "chat/context") == 0o500
        assert _mode(tmp_path / "chat/context/project") == 0o500
        assert _mode(tmp_path / "chat/context/project/card.json") == 0o400
        report = sync_directory(parent, "context", {**FILES, "project/new.json": b"1"}, frozen=True)
    finally:
        os.close(parent)
    assert report.written == ("project/new.json",)
    assert _mode(tmp_path / "chat/context/project/new.json") == 0o400


def test_unfrozen_tree_is_private_and_writable(tmp_path: Path) -> None:
    parent = _parent(tmp_path)
    try:
        sync_directory(parent, "attachments", {"a.pdf": b"%PDF"}, frozen=False)
    finally:
        os.close(parent)
    assert _mode(tmp_path / "chat/attachments") == 0o700
    assert _mode(tmp_path / "chat/attachments/a.pdf") == 0o600


def test_symlink_in_tree_is_refused(tmp_path: Path) -> None:
    parent = _parent(tmp_path)
    try:
        sync_directory(parent, "context", FILES, frozen=False)
        os.symlink("/etc/passwd", tmp_path / "chat/context/evil")
        with pytest.raises(WorkspaceSecurityError):
            sync_directory(parent, "context", FILES, frozen=False)
    finally:
        os.close(parent)


def test_symlinked_directory_itself_is_refused(tmp_path: Path) -> None:
    parent = _parent(tmp_path)
    (tmp_path / "elsewhere").mkdir()
    os.symlink(tmp_path / "elsewhere", tmp_path / "chat/context")
    try:
        with pytest.raises(WorkspaceSecurityError):
            sync_directory(parent, "context", FILES, frozen=False)
    finally:
        os.close(parent)


@pytest.mark.parametrize("bad", ["../x", "/abs", "a//b", "a/./b", ""])
def test_bad_relative_paths_are_refused(tmp_path: Path, bad: str) -> None:
    parent = _parent(tmp_path)
    try:
        with pytest.raises(WorkspaceSecurityError):
            sync_directory(parent, "context", {bad: b"x"}, frozen=False)
    finally:
        os.close(parent)


def test_binary_and_empty_files(tmp_path: Path) -> None:
    parent = _parent(tmp_path)
    try:
        sync_directory(parent, "attachments", {"e.txt": b"", "b.xlsx": b"\x00\xff"}, frozen=False)
        report = sync_directory(
            parent, "attachments", {"e.txt": b"", "b.xlsx": b"\x00\xff"}, frozen=False
        )
    finally:
        os.close(parent)
    assert report.unchanged == 2
    assert (tmp_path / "chat/attachments/e.txt").read_bytes() == b""
    assert (tmp_path / "chat/attachments/b.xlsx").read_bytes() == b"\x00\xff"


def test_a_file_becoming_a_directory_is_handled(tmp_path: Path) -> None:
    parent = _parent(tmp_path)
    try:
        sync_directory(parent, "project", {"docs": b"was a file"}, frozen=False)
        report = sync_directory(parent, "project", {"docs/a.md": b"now a dir"}, frozen=False)
    finally:
        os.close(parent)
    assert report.removed == ("docs",)
    assert report.written == ("docs/a.md",)
    assert (tmp_path / "chat/project/docs/a.md").read_bytes() == b"now a dir"

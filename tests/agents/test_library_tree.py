"""Atomic, read-only library trees under an anchored parent directory."""

from __future__ import annotations

import json
import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from clue_agents import (
    LibraryFile,
    LibraryTree,
    WorkspaceConflict,
    WorkspaceSecurityError,
)


def _index(digest: str) -> LibraryFile:
    return LibraryFile("index.json", json.dumps({"library_sha256": digest}).encode("utf-8"))


@contextmanager
def _parent(path: Path) -> Iterator[int]:
    parent_fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        yield parent_fd
    finally:
        os.close(parent_fd)


def _residue(root: Path, name: str = "library") -> list[str]:
    return [
        entry.name
        for entry in root.iterdir()
        if entry.name.startswith(f"{name}.next") or entry.name.startswith(f"{name}.old")
    ]


# --- the brief's three tests --------------------------------------------------------------


def test_replace_is_atomic_and_read_only(tmp_path: Path) -> None:
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        assert tree.current_digest() is None
        tree.replace(
            [
                LibraryFile("status.md", b"# s\n"),
                LibraryFile("index.json", b'{"library_sha256":"abc"}'),
            ],
            digest="abc",
        )
        assert tree.current_digest() == "abc"
        assert (tmp_path / "library" / "status.md").read_bytes() == b"# s\n"
        assert stat.S_IMODE((tmp_path / "library" / "status.md").stat().st_mode) == 0o400
        assert stat.S_IMODE((tmp_path / "library").stat().st_mode) == 0o500
        assert _residue(tmp_path) == []


def test_an_open_reader_keeps_the_old_tree_across_a_replace(tmp_path: Path) -> None:
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        tree.replace([LibraryFile("status.md", b"# s\n"), _index("abc")], digest="abc")
        reader_fd = tree.open_fd()
        try:
            tree.replace([LibraryFile("status.md", b"# s2\n"), _index("def")], digest="def")
            # The in-flight reader still resolves names through the superseded tree.
            old_fd = os.open("status.md", os.O_RDONLY, dir_fd=reader_fd)
            try:
                assert os.read(old_fd, 100) == b"# s\n"
            finally:
                os.close(old_fd)
        finally:
            os.close(reader_fd)
        assert (tmp_path / "library" / "status.md").read_bytes() == b"# s2\n"
        assert tree.current_digest() == "def"


def test_replace_refuses_a_digest_mismatch_and_a_hostile_path(tmp_path: Path) -> None:
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        with pytest.raises(WorkspaceSecurityError):
            tree.replace([LibraryFile("../x.md", b"")], digest="d")
        with pytest.raises(WorkspaceConflict):
            tree.replace([LibraryFile("index.json", b'{"library_sha256":"other"}')], digest="d")
        # Neither refusal left a tree or a partial build behind.
        assert not (tmp_path / "library").exists()
        assert _residue(tmp_path) == []


# --- refusals ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "path",
    [
        "/etc/passwd",
        "..",
        "a/../b.md",
        "a//b.md",
        "a\\b.md",
        "",
        ".hidden.md",
        "a/.hidden/b.md",
        "notes.sh",
        "notes",
        "notes.md.exe",
    ],
)
def test_replace_refuses_an_unsafe_or_unsupported_path(tmp_path: Path, path: str) -> None:
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        with pytest.raises(WorkspaceSecurityError):
            tree.replace([LibraryFile(path, b"x"), _index("abc")], digest="abc")
        assert not (tmp_path / "library").exists()
        assert _residue(tmp_path) == []


def test_replace_refuses_non_utf8_content(tmp_path: Path) -> None:
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        with pytest.raises(WorkspaceSecurityError):
            tree.replace([LibraryFile("note.md", b"\xff\xfe"), _index("abc")], digest="abc")


def test_replace_refuses_a_duplicate_path(tmp_path: Path) -> None:
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        with pytest.raises(WorkspaceConflict):
            tree.replace(
                [LibraryFile("a.md", b"one"), LibraryFile("a.md", b"two"), _index("abc")],
                digest="abc",
            )


@pytest.mark.parametrize(
    "files",
    [
        [LibraryFile("status.md", b"# s\n")],
        [LibraryFile("index.json", b"not json")],
        [LibraryFile("index.json", b'{"other":"abc"}')],
        [LibraryFile("index.json", b'["abc"]')],
        [LibraryFile("nested/index.json", b'{"library_sha256":"abc"}')],
    ],
)
def test_replace_requires_an_index_that_carries_the_digest(
    tmp_path: Path, files: list[LibraryFile]
) -> None:
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        with pytest.raises(WorkspaceConflict):
            tree.replace(files, digest="abc")
        assert not (tmp_path / "library").exists()


@pytest.mark.parametrize("name", ["..", ".hidden", "a/b", "", "with space", "x" * 200])
def test_a_hostile_tree_name_is_refused(tmp_path: Path, name: str) -> None:
    with _parent(tmp_path) as parent_fd, pytest.raises(WorkspaceSecurityError):
        LibraryTree(parent_fd=parent_fd, name=name)


# --- the served tree -----------------------------------------------------------------------


def test_nested_files_are_written_and_frozen(tmp_path: Path) -> None:
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="v3")
        tree.replace(
            [
                LibraryFile("accounts/acme/brief.md", b"# Acme\n"),
                LibraryFile("accounts/index.json", b"{}"),
                _index("abc"),
            ],
            digest="abc",
        )
        assert (tmp_path / "v3/accounts/acme/brief.md").read_bytes() == b"# Acme\n"
        for relative in ("v3", "v3/accounts", "v3/accounts/acme"):
            assert stat.S_IMODE((tmp_path / relative).stat().st_mode) == 0o500
        for relative in ("v3/accounts/acme/brief.md", "v3/accounts/index.json", "v3/index.json"):
            assert stat.S_IMODE((tmp_path / relative).stat().st_mode) == 0o400


def test_open_fd_serves_only_an_audited_read_only_tree(tmp_path: Path) -> None:
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        with pytest.raises(WorkspaceConflict):
            tree.open_fd()
        tree.replace([LibraryFile("status.md", b"# s\n"), _index("abc")], digest="abc")
        served = tree.open_fd()
        try:
            assert stat.S_IMODE(os.fstat(served).st_mode) == 0o500
            assert sorted(os.listdir(served)) == ["index.json", "status.md"]
        finally:
            os.close(served)

        os.chmod(tmp_path / "library", 0o700)
        os.symlink("/etc/passwd", tmp_path / "library" / "escape.md")
        os.chmod(tmp_path / "library", 0o500)
        with pytest.raises(WorkspaceSecurityError):
            tree.open_fd()

        os.chmod(tmp_path / "library", 0o755)
        with pytest.raises(WorkspaceSecurityError):
            tree.open_fd()


def test_a_writable_tree_is_never_served(tmp_path: Path) -> None:
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        tree.replace([_index("abc")], digest="abc")
        os.chmod(tmp_path / "library", 0o700)
        with pytest.raises(WorkspaceSecurityError):
            tree.open_fd()


def test_current_digest_refuses_a_linked_index(tmp_path: Path) -> None:
    other = tmp_path / "elsewhere.json"
    other.write_text('{"library_sha256":"stolen"}')
    (tmp_path / "library").mkdir(mode=0o700)
    os.symlink(other, tmp_path / "library" / "index.json")
    os.chmod(tmp_path / "library", 0o500)
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        with pytest.raises(WorkspaceSecurityError):
            tree.current_digest()


def test_current_digest_is_none_without_an_index(tmp_path: Path) -> None:
    (tmp_path / "library").mkdir(mode=0o500)
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        assert tree.current_digest() is None


# --- crash residue -------------------------------------------------------------------------


def test_a_crashed_build_is_cleaned_up_by_the_next_replace(tmp_path: Path) -> None:
    leftover_next = tmp_path / f"library.next-{os.getpid()}"
    leftover_next.mkdir(mode=0o700)
    (leftover_next / "stale.md").write_bytes(b"stale")
    os.chmod(leftover_next / "stale.md", 0o400)
    os.chmod(leftover_next, 0o500)
    leftover_old = tmp_path / "library.old-4242"
    leftover_old.mkdir(mode=0o500)
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        tree.replace([LibraryFile("status.md", b"# s\n"), _index("abc")], digest="abc")
        assert _residue(tmp_path) == []
        assert tree.current_digest() == "abc"


def test_a_second_replace_reclaims_the_superseded_tree(tmp_path: Path) -> None:
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        tree.replace([LibraryFile("a.md", b"1"), _index("one")], digest="one")
        tree.replace([LibraryFile("b.md", b"2"), _index("two")], digest="two")
        # One superseded generation is held for in-flight readers...
        assert _residue(tmp_path) == [f"library.old-{os.getpid()}"]
        tree.replace([LibraryFile("c.md", b"3"), _index("three")], digest="three")
        # ...and reclaimed by the replace after it, never accumulating.
        assert _residue(tmp_path) == [f"library.old-{os.getpid()}"]
        assert sorted(os.listdir(tmp_path / "library")) == ["c.md", "index.json"]
        assert tree.current_digest() == "three"


def test_replace_refuses_a_non_directory_at_the_tree_name(tmp_path: Path) -> None:
    (tmp_path / "library").write_text("not a tree")
    with _parent(tmp_path) as parent_fd:
        tree = LibraryTree(parent_fd=parent_fd, name="library")
        with pytest.raises(WorkspaceSecurityError):
            tree.replace([_index("abc")], digest="abc")

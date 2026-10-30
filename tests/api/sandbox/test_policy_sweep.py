"""The post-run sweep: what a script may leave behind, and what is deleted before anyone sees it.

Every test builds Task 7's ``_mounts`` workspace (one read-write ``scratch``, a profile that
allows ``.md`` and nothing else) and tunes exactly one quota so that exactly one rule fires.
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from clue_agents.sandbox.policy_sweep import SANDBOX_OUTPUT_EXTENSIONS, snapshot, sweep
from clue_agents.sandbox.workspaces import SandboxMounts
from tests.api.sandbox.test_workspaces import _mounts


def _workspace(tmp_path: Path, **policy_updates: object) -> SandboxMounts:
    """Task 7's mounts with the scratch tree on disk and one or more quotas re-tuned."""

    mounts = _mounts(tmp_path)
    for host in mounts.read_write.values():
        host.mkdir(parents=True, exist_ok=True)
    if not policy_updates:
        return mounts
    return replace(mounts, policy=mounts.policy.model_copy(update=policy_updates))


def _write(
    mounts: SandboxMounts, relative: str, body: bytes, *, mtime: float | None = None
) -> Path:
    mount, _, rest = relative.partition("/")
    path = mounts.read_write[mount] / rest
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(body)
    if mtime is not None:
        os.utime(path, (mtime, mtime))
    return path


def test_snapshot_lists_the_regular_files_under_the_read_write_dirs(tmp_path: Path) -> None:
    """The before-picture is the writable tree only, recursed, keyed workspace-relative."""

    mounts = _workspace(tmp_path)
    _write(mounts, "scratch/notes.md", b"12345")
    _write(mounts, "scratch/nested/deep.md", b"1")
    (mounts.thread_root / "inputs").mkdir(parents=True, exist_ok=True)
    (mounts.thread_root / "inputs" / "brief.md").write_bytes(b"read only")

    before = snapshot(mounts)

    assert sorted(before) == ["scratch/nested/deep.md", "scratch/notes.md"]
    assert before["scratch/notes.md"][0] == 5


def test_a_file_type_the_profile_does_not_allow_is_removed(tmp_path: Path) -> None:
    """``write_file`` could never have produced ``.py``; neither may the sandbox."""

    mounts = _workspace(tmp_path)
    before = snapshot(mounts)
    _write(mounts, "scratch/notes.md", b"kept")
    script = _write(mounts, "scratch/helper.py", b"print(1)")
    suffixless = _write(mounts, "scratch/Makefile", b"all:")

    result = sweep(mounts, before=before)

    assert result.kept == (("scratch/notes.md", 4),)
    assert result.removed == (
        ("scratch/Makefile", "extension_not_allowed"),
        ("scratch/helper.py", "extension_not_allowed"),
    )
    assert not script.exists()
    assert not suffixless.exists()


def test_a_sandbox_output_extension_survives_a_profile_that_does_not_list_it(
    tmp_path: Path,
) -> None:
    """The point of the sandbox: a script writes the CSV the file tools cannot."""

    mounts = _workspace(tmp_path)
    assert ".csv" not in mounts.policy.allowed_extensions
    assert ".csv" in SANDBOX_OUTPUT_EXTENSIONS
    before = snapshot(mounts)
    table = _write(mounts, "scratch/out.csv", b"a,b\n1,2\n")
    # Suffix matching is case-insensitive, both for the profile's list and for ours.
    chart = _write(mounts, "scratch/chart.PNG", b"\x89PNG")
    upper = _write(mounts, "scratch/README.MD", b"hi")

    result = sweep(mounts, before=before)

    assert result.removed == ()
    assert result.kept == (
        ("scratch/README.MD", 2),
        ("scratch/chart.PNG", 4),
        ("scratch/out.csv", 8),
    )
    assert table.exists() and chart.exists() and upper.exists()


def test_a_file_over_the_per_file_quota_is_removed(tmp_path: Path) -> None:
    mounts = _workspace(tmp_path, max_file_bytes=8)
    before = snapshot(mounts)
    small = _write(mounts, "scratch/small.md", b"12345678")
    large = _write(mounts, "scratch/large.md", b"123456789")

    result = sweep(mounts, before=before)

    assert result.kept == (("scratch/small.md", 8),)
    assert result.removed == (("scratch/large.md", "file_too_large"),)
    assert small.exists()
    assert not large.exists()


def test_over_the_total_quota_the_newest_written_go_first(tmp_path: Path) -> None:
    mounts = _workspace(tmp_path, max_total_bytes=20, max_file_bytes=20)
    before = snapshot(mounts)
    first = _write(mounts, "scratch/first.md", b"0123456789", mtime=1_000.0)
    second = _write(mounts, "scratch/second.md", b"0123456789", mtime=2_000.0)
    third = _write(mounts, "scratch/third.md", b"0123456789", mtime=3_000.0)

    result = sweep(mounts, before=before)

    # 30 bytes over a 20-byte ceiling: the newest one file goes, and the sweep stops there.
    assert result.removed == (("scratch/third.md", "quota_exceeded"),)
    assert result.kept == (("scratch/first.md", 10), ("scratch/second.md", 10))
    assert first.exists() and second.exists()
    assert not third.exists()


def test_over_the_file_count_quota_the_newest_written_go_first(tmp_path: Path) -> None:
    mounts = _workspace(tmp_path, max_file_count=2)
    before = snapshot(mounts)
    _write(mounts, "scratch/a.md", b"a", mtime=1_000.0)
    _write(mounts, "scratch/b.md", b"b", mtime=2_000.0)
    _write(mounts, "scratch/c.md", b"c", mtime=3_000.0)
    _write(mounts, "scratch/d.md", b"d", mtime=4_000.0)

    result = sweep(mounts, before=before)

    assert result.removed == (
        ("scratch/c.md", "quota_exceeded"),
        ("scratch/d.md", "quota_exceeded"),
    )
    assert result.kept == (("scratch/a.md", 1), ("scratch/b.md", 1))


def test_a_pre_existing_file_survives_a_quota_the_run_did_not_blow(tmp_path: Path) -> None:
    """The over-quota state predates the run: the sweep stops rather than deleting the past.

    The pre-existing file is both over quota on its own *and* the newest thing in the tree, so a
    sweep that ranked candidates by mtime alone would take it first. Only the run's own file is
    ever a candidate, and once it is gone the sweep stops and reports nothing about the rest.
    """

    mounts = _workspace(tmp_path, max_total_bytes=5, max_file_bytes=10)
    old = _write(mounts, "scratch/old.md", b"0123456789", mtime=3_000.0)
    before = snapshot(mounts)
    new = _write(mounts, "scratch/new.md", b"1", mtime=2_000.0)

    result = sweep(mounts, before=before)

    assert result.removed == (("scratch/new.md", "quota_exceeded"),)
    assert result.kept == ()
    assert old.read_bytes() == b"0123456789"
    assert not new.exists()


def test_symlinks_and_other_non_regular_entries_are_removed_without_being_followed(
    tmp_path: Path,
) -> None:
    mounts = _workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_bytes(b"not the sandbox's")
    before = snapshot(mounts)

    escape = mounts.read_write["scratch"] / "escape.md"
    escape.symlink_to(outside / "secret.md")
    ladder = mounts.read_write["scratch"] / "ladder"
    ladder.symlink_to(outside, target_is_directory=True)
    pipe = mounts.read_write["scratch"] / "pipe.md"
    os.mkfifo(pipe)
    kept = _write(mounts, "scratch/real.md", b"ok")

    result = sweep(mounts, before=before)

    assert result.removed == (
        ("scratch/escape.md", "not_a_regular_file"),
        ("scratch/ladder", "not_a_regular_file"),
        ("scratch/pipe.md", "not_a_regular_file"),
    )
    assert result.kept == (("scratch/real.md", 2),)
    assert kept.exists()
    assert not escape.is_symlink() and not ladder.is_symlink() and not pipe.exists()
    # The link was unlinked, never walked: what it pointed at is untouched.
    assert (outside / "secret.md").read_bytes() == b"not the sandbox's"


def test_an_atomic_write_residue_name_is_removed(tmp_path: Path) -> None:
    """A ``.clue-tmp-*`` leftover makes every later workspace listing raise; it cannot stay."""

    mounts = _workspace(tmp_path)
    before = snapshot(mounts)
    residue = _write(mounts, "scratch/.clue-tmp-abc.md", b"half a write")

    result = sweep(mounts, before=before)

    assert result.removed == (("scratch/.clue-tmp-abc.md", "atomic_write_residue"),)
    assert result.kept == ()
    assert not residue.exists()


def test_unchanged_files_are_not_listed_as_kept(tmp_path: Path) -> None:
    """``kept`` is what this run produced, not an inventory of the workspace."""

    mounts = _workspace(tmp_path)
    _write(mounts, "scratch/untouched.md", b"same", mtime=1_000.0)
    edited = _write(mounts, "scratch/edited.md", b"before", mtime=1_000.0)
    before = snapshot(mounts)

    edited.write_bytes(b"after the run")
    os.utime(edited, (2_000.0, 2_000.0))
    _write(mounts, "scratch/fresh.md", b"new", mtime=2_000.0)

    result = sweep(mounts, before=before)

    assert result.removed == ()
    assert result.kept == (("scratch/edited.md", 13), ("scratch/fresh.md", 3))


def test_a_missing_read_write_dir_is_not_an_error(tmp_path: Path) -> None:
    """A turn whose script never ran, or a layout folder nobody created, sweeps to nothing."""

    mounts = _mounts(tmp_path)

    assert snapshot(mounts) == {}
    assert sweep(mounts, before={}) == sweep(mounts, before={})
    assert sweep(mounts, before={}).kept == ()


def test_explicitly_changed_modes_are_repaired(tmp_path: Path) -> None:
    """A script may override its private defaults; the sweep remains a defensive fallback."""

    mounts = _workspace(tmp_path)
    before = snapshot(mounts)
    nested = _write(mounts, "scratch/out/table.csv", b"a,b\n1,2\n")
    os.chmod(nested, 0o644)
    os.chmod(nested.parent, 0o755)
    result = sweep(mounts, before=before)
    assert result.kept == (("scratch/out/table.csv", 8),)
    assert result.removed == ()
    assert os.stat(nested).st_mode & 0o777 == 0o600
    assert os.stat(nested.parent).st_mode & 0o777 == 0o700


def test_private_outputs_need_no_permission_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    mounts = _workspace(tmp_path)
    before = snapshot(mounts)
    nested = _write(mounts, "scratch/out/table.csv", b"a,b\n1,2\n")
    os.chmod(nested, 0o600)
    os.chmod(nested.parent, 0o700)

    def unexpected_chmod(*args: object, **kwargs: object) -> None:
        pytest.fail("Ordinary sandbox output should not need chmod")

    monkeypatch.setattr(os, "chmod", unexpected_chmod)
    result = sweep(mounts, before=before)
    assert result.kept == (("scratch/out/table.csv", 8),)
    assert result.removed == ()


def test_a_hard_linked_file_is_removed(tmp_path: Path) -> None:
    mounts = _workspace(tmp_path)
    before = snapshot(mounts)
    original = _write(mounts, "scratch/one.md", b"x")
    os.link(original, mounts.read_write["scratch"] / "two.md")
    result = sweep(mounts, before=before)
    # Whichever name the walk meets first is the hard link and goes; the other is then an
    # ordinary single-link file and stays.
    assert [reason for _, reason in result.removed] == ["hard_linked"]
    assert len(result.kept) == 1
    survivor = mounts.read_write["scratch"] / result.kept[0][0].split("/", 1)[1]
    assert os.stat(survivor).st_nlink == 1


def test_a_folder_with_an_atomic_write_residue_name_is_removed_with_everything_in_it(
    tmp_path: Path,
) -> None:
    """Review A2-I3: the sweep checked file names only, so ``outputs/.clue-tmp-a/r.md`` survived.
    The backend refuses any name with the prefix, folders included, and a saved snapshot carried
    it to every machine — so the folder goes, with each file in it reported."""

    mounts = _workspace(tmp_path)
    before = snapshot(mounts)
    kept = _write(mounts, "scratch/keep/real.md", b"ok")
    _write(mounts, "scratch/.clue-tmp-a/r.md", b"one")
    _write(mounts, "scratch/keep/.clue-tmp-b/deeper/s.md", b"two")
    (mounts.read_write["scratch"] / ".clue-tmp-empty").mkdir()

    result = sweep(mounts, before=before)

    assert result.removed == (
        ("scratch/.clue-tmp-a/r.md", "atomic_write_residue"),
        ("scratch/keep/.clue-tmp-b/deeper/s.md", "atomic_write_residue"),
    )
    assert result.kept == (("scratch/keep/real.md", 2),)
    assert kept.exists()
    root = mounts.read_write["scratch"]
    assert sorted(path.name for path in root.rglob("*")) == ["keep", "real.md"]


def test_a_link_inside_a_residue_folder_is_unlinked_never_followed(tmp_path: Path) -> None:
    mounts = _workspace(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret.md").write_bytes(b"not the sandbox's")
    residue = mounts.read_write["scratch"] / ".clue-tmp-a"
    residue.mkdir()
    (residue / "escape").symlink_to(outside)

    result = sweep(mounts, before=snapshot(mounts))

    assert result.removed == (("scratch/.clue-tmp-a/escape", "atomic_write_residue"),)
    assert not residue.exists()
    assert (outside / "secret.md").read_bytes() == b"not the sandbox's"

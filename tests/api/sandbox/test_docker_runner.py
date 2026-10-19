from __future__ import annotations

import asyncio
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

from clue_api.sandbox.docker_runner import (
    SandboxLimits,
    build_command,
    docker_available,
    run_script,
)
from clue_api.sandbox.workspaces import sandbox_mounts_for_lease
from tests.agents.workspace_helpers import make_workspace
from tests.api.sandbox.test_workspaces import _mounts

LIMITS = SandboxLimits(
    image="clue-agent-sandbox:latest",
    timeout_s=60,
    cpus=1.0,
    memory_mb=1024,
    max_output_bytes=4096,
)


def test_command_is_locked_down(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(os, "getuid", lambda: 1234)
    monkeypatch.setattr(os, "getgid", lambda: 5678)
    cmd = build_command(_mounts(tmp_path), LIMITS)
    for flag in (
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--pids-limit",
        "256",
        "--user",
        "1234:5678",
    ):
        assert flag in cmd
    assert cmd[-3:] == ["sh", "-c", "umask 077; exec python -I -"]
    assert f"{tmp_path / 'inputs'}:/workspace/inputs:ro" in cmd
    assert f"{tmp_path / 'scratch'}:/workspace/scratch:rw" in cmd
    assert not any(part.startswith("CLUE_") or part.startswith("OPENROUTER") for part in cmd)


def test_root_worker_is_refused_before_starting_docker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(os, "getuid", lambda: 0)
    available, reason = docker_available(LIMITS.image)
    assert not available and "non-root" in reason
    with pytest.raises(PermissionError, match="non-root"):
        build_command(_mounts(tmp_path), LIMITS)


def test_startup_creates_private_files_without_changing_the_workers_mask(tmp_path: Path) -> None:
    """Exercise the actual child startup even on hosts without Docker."""

    command = build_command(_mounts(tmp_path), LIMITS)
    # A before/after probe observes the parent mask without ever changing this process's umask.
    before = tmp_path / "before"
    before.write_text("before")
    result = subprocess.run(
        command[-3:],
        cwd=tmp_path,
        input=(
            "from pathlib import Path\n"
            "import subprocess, sys\n"
            "Path('nested').mkdir()\n"
            "Path('nested/report.csv').write_text('account,acv\\nExample,12\\n')\n"
            "subprocess.run([sys.executable, '-c', "
            "\"open('nested/child.csv', 'w').write('child')\"], check=True)\n"
            "print('literal $HOME `echo never`')\n"
        ),
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "literal $HOME `echo never`"
    assert stat.S_IMODE((tmp_path / "nested").stat().st_mode) == 0o700
    for name in ("report.csv", "child.csv"):
        assert stat.S_IMODE((tmp_path / "nested" / name).stat().st_mode) == 0o600
    after = tmp_path / "after"
    after.write_text("after")
    assert stat.S_IMODE(before.stat().st_mode) == stat.S_IMODE(after.stat().st_mode)


def test_output_truncation_flags(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    class Done:  # stands in for subprocess.CompletedProcess
        returncode = 0
        stdout = b"x" * 10_000
        stderr = b""

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: Done())
    run = run_script("print('hi')", mounts=_mounts(tmp_path), limits=LIMITS, timeout_s=5)
    assert run.exit_code == 0 and run.stdout_truncated and len(run.stdout) == 4096


def test_timeout_is_reported(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    def boom(*a: object, **k: object) -> None:
        raise subprocess.TimeoutExpired(cmd="docker", timeout=1)

    monkeypatch.setattr(subprocess, "run", boom)
    run = run_script("while True: pass", mounts=_mounts(tmp_path), limits=LIMITS, timeout_s=1)
    assert run.timed_out and run.exit_code is None


@pytest.mark.skipif(
    shutil.which("docker") is None or not docker_available("clue-agent-sandbox:latest")[0],
    reason="Docker or the clue-agent-sandbox image is not available on this host",
)
def test_real_container_runs_and_writes_scratch(tmp_path: Path) -> None:
    mounts = _mounts(tmp_path)
    run = run_script(
        "import pathlib; pathlib.Path('scratch/hello.md').write_text('hi'); print('ok')",
        mounts=mounts,
        limits=LIMITS,
        timeout_s=60,
    )
    assert run.exit_code == 0 and run.stdout.strip() == b"ok"
    assert (tmp_path / "scratch" / "hello.md").read_text() == "hi"


@pytest.mark.skipif(
    shutil.which("docker") is None or not docker_available(LIMITS.image)[0],
    reason="Docker or the clue-agent-sandbox image is not available on this host",
)
def test_real_output_can_be_snapshotted_without_permission_repair(tmp_path: Path) -> None:
    """Reproduce the failed CSV turn through the real workspace finalizer, without a sweep."""

    workspace = make_workspace(tmp_path)
    try:
        workspace.lease.backend.write_text_sync("scratch/source.md", "account,acv\nExample,12\n")
        mounts = sandbox_mounts_for_lease(
            workspace.lease,
            workspace.factory,
            brand=None,
            project_library=False,
            attachments=False,
        )
        run = run_script(
            "from pathlib import Path\n"
            "source = Path('scratch/source.md').read_text()\n"
            "Path('outputs/nested').mkdir()\n"
            "Path('outputs/nested/report.csv').write_text(source)\n"
            "try:\n"
            "    Path('inputs/forbidden.md').write_text('blocked')\n"
            "except OSError:\n"
            "    print('read-only mount enforced')\n"
            "else:\n"
            "    raise AssertionError('input mount was writable')\n",
            mounts=mounts,
            limits=LIMITS,
            timeout_s=60,
        )
        assert run.exit_code == 0, run.stderr.decode()
        assert run.stdout.strip() == b"read-only mount enforced"
        output = workspace.thread_path / "outputs/nested/report.csv"
        assert output.stat().st_uid == os.getuid()
        assert stat.S_IMODE(output.stat().st_mode) == 0o600
        assert stat.S_IMODE(output.parent.stat().st_mode) == 0o700
        refs = asyncio.run(workspace.lease.backend.snapshot_outputs(empty_after=True))
        assert len(refs) == 1
        assert workspace.sink.records == [
            (
                "ws-1",
                "outputs/nested/report.csv",
                b"account,acv\nExample,12\n",
                "application/octet-stream",
            )
        ]
        assert not output.exists()
    finally:
        workspace.close()


def test_run_resolves_docker_before_sanitizing_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    executable = "/Applications/Docker.app/Contents/Resources/bin/docker"
    monkeypatch.setattr(shutil, "which", lambda name: executable if name == "docker" else None)
    monkeypatch.setenv("CLUE_TEST_SECRET", "must-not-reach-docker")
    observed = {}

    def execute(command, **kwargs):
        observed["command"] = command
        observed["environment"] = kwargs["env"]
        return subprocess.CompletedProcess(command, 0, b"ok", b"")

    monkeypatch.setattr(subprocess, "run", execute)
    result = run_script("print('ok')", mounts=_mounts(tmp_path), limits=LIMITS, timeout_s=5)
    assert result.exit_code == 0
    assert observed["command"][0] == executable
    assert observed["environment"] == {"PATH": "/usr/bin:/bin:/usr/local/bin"}

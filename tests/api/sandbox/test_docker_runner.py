from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from clue_api.sandbox.docker_runner import (
    SandboxLimits,
    build_command,
    docker_available,
    run_script,
)
from tests.api.sandbox.test_workspaces import _mounts

LIMITS = SandboxLimits(
    image="clue-agent-sandbox:latest",
    timeout_s=60,
    cpus=1.0,
    memory_mb=1024,
    max_output_bytes=4096,
)


def test_command_is_locked_down(tmp_path: Path) -> None:
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
        "65534:65534",
    ):
        assert flag in cmd
    assert cmd[-3:] == ["python", "-I", "-"]
    assert f"{tmp_path / 'inputs'}:/workspace/inputs:ro" in cmd
    assert f"{tmp_path / 'scratch'}:/workspace/scratch:rw" in cmd
    assert not any(part.startswith("CLUE_") or part.startswith("OPENROUTER") for part in cmd)


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

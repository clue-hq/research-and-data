"""deploy/vm/ci_deploy.sh: the forced command behind CI's SSH key on the worker VM.

CI connects as `clue` with a key that `authorized_keys` pins to this script, so the key can deploy
one commit and do nothing else: the requested command (SSH_ORIGINAL_COMMAND) must be a full 40-char
commit sha, which is handed to deploy.sh; anything else is refused before deploy.sh runs.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

VM = Path(__file__).resolve().parents[2] / "deploy" / "vm"
SHA = "0f362f9f8c02093904c1a34f69a787a3eb2e4209"


@pytest.fixture
def vm_dir(tmp_path: Path) -> Path:
    shutil.copy(VM / "ci_deploy.sh", tmp_path / "ci_deploy.sh")
    fake = tmp_path / "deploy.sh"
    fake.write_text('#!/usr/bin/env bash\necho "deploy.sh $*" > "$CALLS"\n', encoding="utf-8")
    fake.chmod(0o755)
    return tmp_path


def _run(vm_dir: Path, requested: str | None) -> tuple[subprocess.CompletedProcess[str], str]:
    calls = vm_dir / "calls.log"
    env = {"PATH": os.environ["PATH"], "CALLS": str(calls)}
    if requested is not None:
        env["SSH_ORIGINAL_COMMAND"] = requested
    result = subprocess.run(
        ["bash", str(vm_dir / "ci_deploy.sh")], env=env, capture_output=True, text=True
    )
    return result, calls.read_text(encoding="utf-8") if calls.exists() else ""


def test_a_full_commit_sha_runs_deploy_for_exactly_that_commit(vm_dir: Path) -> None:
    result, calls = _run(vm_dir, SHA)
    assert result.returncode == 0, result.stderr
    assert calls.strip() == f"deploy.sh {SHA}"


@pytest.mark.parametrize(
    "requested",
    [
        None,
        "",
        SHA[:12],
        SHA.upper(),
        f"{SHA} --extra",
        f"{SHA}; id",
        "bash",
        "/bin/sh -c id",
        f" {SHA}",
        f"{SHA}\nid",
    ],
)
def test_anything_but_a_full_sha_is_refused_before_deploy_runs(
    vm_dir: Path, requested: str | None
) -> None:
    result, calls = _run(vm_dir, requested)
    assert result.returncode != 0
    assert "refused" in result.stderr
    assert calls == ""

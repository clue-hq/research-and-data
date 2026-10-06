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
    """The VM's layout: <app>/deploy/vm/{ci_deploy.sh,deploy.sh}, with stand-in git and deploy."""
    vm = tmp_path / "app" / "deploy" / "vm"
    vm.mkdir(parents=True)
    shutil.copy(VM / "ci_deploy.sh", vm / "ci_deploy.sh")
    fake = vm / "deploy.sh"
    fake.write_text('#!/usr/bin/env bash\necho "deploy.sh $*" >> "$CALLS"\n', encoding="utf-8")
    fake.chmod(0o755)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    git = bin_dir / "git"
    git.write_text(
        "#!/usr/bin/env bash\n"
        'echo "git $*" >> "$CALLS"\n'
        '[[ " $* " == *" $FAKE_GIT_FAIL "* ]] && exit 1\n'
        "exit 0\n",
        encoding="utf-8",
    )
    git.chmod(0o755)
    return vm


def _run(
    vm_dir: Path, requested: str | None, **extra: str
) -> tuple[subprocess.CompletedProcess[str], str]:
    calls = vm_dir / "calls.log"
    bin_dir = vm_dir.parents[2] / "bin"
    env = {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CALLS": str(calls),
        "FAKE_GIT_FAIL": "__never__",
        **extra,
    }
    if requested is not None:
        env["SSH_ORIGINAL_COMMAND"] = requested
    result = subprocess.run(
        ["bash", str(vm_dir / "ci_deploy.sh")], env=env, capture_output=True, text=True
    )
    return result, calls.read_text(encoding="utf-8") if calls.exists() else ""


def test_a_full_commit_sha_runs_deploy_for_exactly_that_commit(vm_dir: Path) -> None:
    result, calls = _run(vm_dir, SHA)
    assert result.returncode == 0, result.stderr
    assert calls.strip().splitlines()[-1] == f"deploy.sh {SHA}"


def test_the_requested_commit_is_checked_out_before_its_own_deploy_script_runs(
    vm_dir: Path,
) -> None:
    """Production 2026-10-04: CI ran the PREVIOUS release's deploy.sh (it checks out the new
    commit itself, too late), so #96's new preparation steps never ran while its new compose
    file did, and the design workspace came up root-owned. The checkout comes first now."""
    result, calls = _run(vm_dir, SHA)
    assert result.returncode == 0, result.stderr
    app = vm_dir.parents[1]
    assert calls.strip().splitlines() == [
        f"git -C {app} fetch origin main",
        f"git -C {app} checkout --detach {SHA}",
        f"deploy.sh {SHA}",
    ]


def test_a_failed_checkout_deploys_nothing(vm_dir: Path) -> None:
    result, calls = _run(vm_dir, SHA, FAKE_GIT_FAIL="checkout")
    assert result.returncode != 0
    assert "deploy.sh" not in calls


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

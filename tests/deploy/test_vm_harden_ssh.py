"""deploy/vm/harden_ssh.sh: turn off SSH password login, never before a key can log in.

Run for real with stand-in ``getent`` / ``sshd`` / ``systemctl`` on PATH and a temp sshd drop-in
directory, so no root, VM or SSH daemon is needed.
"""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "deploy" / "vm" / "harden_ssh.sh"
KEY = "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIExampleExampleExampleExampleExample aryan@cluehq.ai\n"
EXPECTED = "PasswordAuthentication no\nKbdInteractiveAuthentication no\nPermitRootLogin no\n"


def _stub(bin_dir: Path, name: str, body: str) -> None:
    path = bin_dir / name
    path.write_text(f"#!/usr/bin/env bash\n{body}\n", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)


@pytest.fixture
def box(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    home = tmp_path / "home" / "ubuntu"
    (home / ".ssh").mkdir(parents=True)
    log = tmp_path / "calls.log"
    _stub(bin_dir, "getent", f'echo "ubuntu:x:1000:1000::{home}:/bin/bash"')
    _stub(bin_dir, "sshd", f'echo "sshd $*" >> {log}; exit "${{FAKE_SSHD_EXIT:-0}}"')
    _stub(bin_dir, "systemctl", f'echo "systemctl $*" >> {log}')
    sshd_dir = tmp_path / "sshd_config.d"
    sshd_dir.mkdir()
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "SUDO_USER": "ubuntu",
        "CLUE_SSHD_CONFIG_DIR": str(sshd_dir),
        "HOME_KEYS": str(home / ".ssh" / "authorized_keys"),
        "LOG": str(log),
    }


def _run(box: dict[str, str], **extra: str) -> tuple[int, str, list[str], Path]:
    env = {k: v for k, v in box.items() if k not in {"HOME_KEYS", "LOG"}}
    result = subprocess.run(
        ["bash", str(SCRIPT)],
        env={**env, **extra},
        capture_output=True,
        text=True,
        check=False,
    )
    log = Path(box["LOG"])
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    dropin = Path(box["CLUE_SSHD_CONFIG_DIR"]) / "00-clue-hardening.conf"
    return result.returncode, result.stdout + result.stderr, calls, dropin


def test_with_a_key_installed_password_login_is_turned_off_and_ssh_reloaded(
    box: dict[str, str],
) -> None:
    Path(box["HOME_KEYS"]).write_text(KEY, encoding="utf-8")
    code, out, calls, dropin = _run(box)
    assert code == 0, out
    assert dropin.read_text(encoding="utf-8") == EXPECTED
    assert calls == ["sshd -t", "systemctl reload ssh"], "validate before reloading"


@pytest.mark.parametrize("keys", [None, "", "# no keys yet\n\n"])
def test_without_a_key_it_refuses_and_changes_nothing(
    box: dict[str, str], keys: str | None
) -> None:
    """Turning passwords off with no key installed would lock the operator out."""
    if keys is not None:
        Path(box["HOME_KEYS"]).write_text(keys, encoding="utf-8")
    code, out, calls, dropin = _run(box)
    assert code != 0
    assert "ssh-copy-id" in out
    assert not dropin.exists()
    assert calls == []


def test_a_config_sshd_rejects_is_removed_and_ssh_is_not_reloaded(box: dict[str, str]) -> None:
    Path(box["HOME_KEYS"]).write_text(KEY, encoding="utf-8")
    code, out, calls, dropin = _run(box, FAKE_SSHD_EXIT="1")
    assert code != 0
    assert not dropin.exists(), "a config sshd rejects must not stay behind"
    assert "systemctl reload ssh" not in calls


def test_running_it_twice_leaves_the_same_file(box: dict[str, str]) -> None:
    Path(box["HOME_KEYS"]).write_text(KEY, encoding="utf-8")
    assert _run(box)[0] == 0
    code, out, _, dropin = _run(box)
    assert code == 0, out
    assert dropin.read_text(encoding="utf-8") == EXPECTED


def test_the_operator_defaults_to_ubuntu_when_not_run_through_sudo(box: dict[str, str]) -> None:
    """OVHcloud's image logs in as ubuntu; a bare root shell still checks ubuntu's keys."""
    Path(box["HOME_KEYS"]).write_text(KEY, encoding="utf-8")
    env = {k: v for k, v in box.items() if k != "SUDO_USER"}
    code, out, _, dropin = _run(env)
    assert code == 0, out
    assert dropin.exists()


def test_bootstrap_hardens_ssh_before_anything_else() -> None:
    bootstrap = (SCRIPT.parent / "bootstrap.sh").read_text(encoding="utf-8")
    harden = bootstrap.index("harden_ssh.sh")
    assert harden < bootstrap.index("apt-get"), "close password login before the long setup"

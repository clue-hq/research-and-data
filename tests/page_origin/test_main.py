from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from clue_config import Secrets, Settings
from clue_page_origin.main import build_gate, build_reads


def test_build_gate_refuses_trust_with_a_secret() -> None:
    settings = Settings(_env_file=None, pages_trust_host_header=True)
    secrets = Secrets(_env_file=None, pages_edge_secret="s")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        build_gate(settings, secrets)


def test_build_gate_dev_and_prod_shapes() -> None:
    dev = build_gate(
        Settings(_env_file=None, pages_trust_host_header=True),
        Secrets(_env_file=None),  # type: ignore[call-arg]
    )
    assert dev is not None
    prod = build_gate(
        Settings(_env_file=None),
        Secrets(_env_file=None, pages_edge_secret="s"),  # type: ignore[call-arg]
    )
    assert prod is not None


def test_k3_6_the_origin_serves_system_addresses_on_the_system_and_every_legacy_suffix() -> None:
    """Review finding K3-6: during a domain move the origin answers `<label>.<s>` for the new
    suffix and the old one, so every step of the move leaves every link working."""
    settings = Settings(
        _env_file=None,
        pages_system_suffix="clue-pages.example",
        pages_legacy_system_suffixes="pages.cluehq.ai, ,clue-pages.example",
    )
    reads = build_reads(settings, Secrets(_env_file=None))  # type: ignore[call-arg]
    assert reads.system_suffixes == ("clue-pages.example", "pages.cluehq.ai")
    today = build_reads(
        Settings(
            _env_file=None,
            pages_system_suffix="pages.cluehq.ai",
            pages_legacy_system_suffixes="pages.cluehq.ai",
        ),
        Secrets(_env_file=None),  # type: ignore[call-arg]
    )
    assert today.system_suffixes == ("pages.cluehq.ai",)  # production today: one suffix


def test_the_origin_refuses_to_start_on_s3_without_the_s3_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Live 2026-10-19: the page origin's image had no aioboto3, every R2 read failed and was
    skipped, and every published image, font and script answered 404 with nothing logged. Built
    without the client, it now refuses to start instead."""
    from clue_storage import StorageError

    monkeypatch.setitem(sys.modules, "aioboto3", None)  # what an image without the extra looks like
    settings = Settings(_env_file=None, storage_backend="s3", storage_s3_bucket="clue-prod")
    with pytest.raises(StorageError, match=r"clue-storage\[s3\]"):
        build_reads(settings, Secrets(_env_file=None))  # type: ignore[call-arg]


def test_the_origins_own_install_carries_the_s3_client() -> None:
    """The origin's image installs only its own package (`uv sync --package clue-page-origin` in
    Dockerfile.railway), not the root's deploy group, so the S3 client must be its own
    dependency."""
    root = Path(__file__).resolve().parents[2]
    dockerfile = (root / "platform/page_origin/Dockerfile.railway").read_text(encoding="utf-8")
    assert "--package clue-page-origin" in dockerfile
    exported = subprocess.run(
        ["uv", "export", "--frozen", "--no-dev", "--no-hashes", "--package", "clue-page-origin"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    assert re.search(r"^aioboto3==", exported, re.MULTILINE), (
        "aioboto3 is not in the origin's install"
    )

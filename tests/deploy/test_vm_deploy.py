"""deploy/vm/deploy.sh (first deployment spec §9.3), run with stand-in git/docker commands."""

from __future__ import annotations

import os
import stat
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
DEPLOY = REPO / "deploy" / "vm" / "deploy.sh"
SHA = "abc1234def"

FAKE_DOCKER = r"""#!/usr/bin/env python3
import os, sys
args = sys.argv[1:]
with open(os.environ["CALLS_LOG"], "a") as fh:
    fh.write("docker " + " ".join(args) + "\n")
if args[:1] == ["run"] and "alembic current" in " ".join(args):
    sys.exit(0 if os.environ.get("FAKE_AT_HEAD", "1") == "1" else 1)
sys.exit(0)
"""
FAKE_GIT = """#!/usr/bin/env bash
echo "git $*" >> "$CALLS_LOG"
"""

GOOD_ENV = "\n".join(
    [
        "CLUE_DATABASE_URL=postgresql+asyncpg://u:p@proxy.rlwy.net:5432/railway",
        "LUMEN_INGESTION_CONTROLLER_DATABASE_URL=postgresql+asyncpg://u:p@proxy.rlwy.net:5432/railway",
        "CLUE_MIGRATE_DATABASE_URL=postgresql+asyncpg://owner:p@proxy.rlwy.net:5432/railway",
        "CLUE_REDIS_URL=rediss://default:p@proxy.rlwy.net:6379/0?ssl_cert_reqs=none",
        "CLUE_STORAGE_BACKEND=s3",
        "CLUE_STORAGE_S3_BUCKET=clue-prod",
        "CLUE_STORAGE_S3_ENDPOINT_URL=https://acct.r2.cloudflarestorage.com",
        "CLUE_STORAGE_S3_ACCESS_KEY_ID=k",
        "CLUE_STORAGE_S3_SECRET_ACCESS_KEY=s",
        "CLUE_PAGES_SYSTEM_SUFFIX=pages.cluehq.ai",
        "CLUE_PAGES_PUBLIC_SCHEME=https",
        "CLUE_PAGES_TRUST_HOST_HEADER=false",
        "CLUE_SCRAPE_BACKEND=scrapling",
        "CLUE_STAGE0_PAGE_FETCHER=scrapling",
        "CLUE_STORAGE_S3_REGION=auto",
        "CLUE_METRICS_EXPORTER=otlp",
        "CLUE_METRICS_OTLP_ENDPOINT=https://otlp-gateway.example/otlp/v1/metrics",
        "CLUE_AUTH_ENABLED=true",
        "CLUE_AUTH_ENVIRONMENT=production",
        "CLUE_AUTH_MODE=clerk",
        "CLUE_OPENROUTER_API_KEY=or-key",
        "LUMEN_API_ORIGIN=https://app.cluehq.ai/api/clue/design-public",
    ]
)


@pytest.fixture
def vm(tmp_path: Path) -> dict[str, str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name, body in {"docker": FAKE_DOCKER, "git": FAKE_GIT}.items():
        path = bin_dir / name
        path.write_text(body, encoding="utf-8")
        path.chmod(path.stat().st_mode | stat.S_IEXEC)
    (tmp_path / "env").write_text(GOOD_ENV + "\n", encoding="utf-8")
    (tmp_path / "compose.env").write_text("DOCKER_GID=999\nBACKEND_IMAGE=old\n", encoding="utf-8")
    return {
        "PATH": f"{bin_dir}:{os.environ['PATH']}",
        "CALLS_LOG": str(tmp_path / "calls.log"),
        "CLUE_APP_DIR": str(REPO),
        "CLUE_ENV_FILE": str(tmp_path / "env"),
        "CLUE_COMPOSE_ENV": str(tmp_path / "compose.env"),
    }


def _deploy(env: dict[str, str], **extra: str) -> tuple[int, str, list[str]]:
    result = subprocess.run(
        ["bash", str(DEPLOY), SHA],
        env={**env, **extra},
        capture_output=True,
        text=True,
        check=False,
    )
    log = Path(env["CALLS_LOG"])
    calls = log.read_text(encoding="utf-8").splitlines() if log.exists() else []
    return result.returncode, result.stdout + result.stderr, calls


def _compose_up(calls: list[str]) -> bool:
    return any(" compose " in f" {c} " and " up " in f" {c} " for c in calls)


def test_a_good_deploy_pulls_checks_head_and_restarts_the_pools(vm: dict[str, str]) -> None:
    code, out, calls = _deploy(vm)
    assert code == 0, out
    assert f"docker pull ghcr.io/clue-hq/clue-backend:{SHA}" in calls
    assert f"docker pull ghcr.io/clue-hq/clue-agent-sandbox:{SHA}" in calls
    assert any("alembic current" in c for c in calls)
    assert _compose_up(calls)
    compose_env = Path(vm["CLUE_COMPOSE_ENV"]).read_text(encoding="utf-8").splitlines()
    assert f"BACKEND_IMAGE=ghcr.io/clue-hq/clue-backend:{SHA}" in compose_env
    assert "BACKEND_IMAGE=old" not in compose_env
    assert "DOCKER_GID=999" in compose_env


def test_the_sandbox_image_line_is_added_when_missing_and_replaced_when_present(
    vm: dict[str, str],
) -> None:
    env_file = Path(vm["CLUE_ENV_FILE"])
    assert _deploy(vm)[0] == 0
    lines = env_file.read_text(encoding="utf-8").splitlines()
    assert lines.count(f"CLUE_SANDBOX_IMAGE=ghcr.io/clue-hq/clue-agent-sandbox:{SHA}") == 1
    env_file.write_text(env_file.read_text(encoding="utf-8").replace(SHA, "previous"), "utf-8")
    assert _deploy(vm)[0] == 0
    lines = env_file.read_text(encoding="utf-8").splitlines()
    sandbox_lines = [line for line in lines if line.startswith("CLUE_SANDBOX_IMAGE=")]
    assert sandbox_lines == [f"CLUE_SANDBOX_IMAGE=ghcr.io/clue-hq/clue-agent-sandbox:{SHA}"]


def test_a_database_behind_head_refuses_and_never_restarts(vm: dict[str, str]) -> None:
    code, out, calls = _deploy(vm, FAKE_AT_HEAD="0")
    assert code != 0
    assert "not at head" in out
    assert not _compose_up(calls)


def test_a_bad_env_file_stops_before_anything_is_pulled(vm: dict[str, str]) -> None:
    env_file = Path(vm["CLUE_ENV_FILE"])
    env_file.write_text(
        GOOD_ENV.replace("CLUE_STORAGE_BACKEND=s3", "CLUE_STORAGE_BACKEND=fs"), "utf-8"
    )
    code, out, calls = _deploy(vm)
    assert code != 0
    assert "CLUE_STORAGE_BACKEND" in out
    assert not any(c.startswith("docker pull") for c in calls)
    assert not _compose_up(calls)

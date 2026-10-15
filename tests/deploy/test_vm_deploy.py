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
joined = " ".join(args)
with open(os.environ["CALLS_LOG"], "a") as fh:
    fh.write("docker " + joined + "\n")
if args[:1] == ["run"] and "alembic current" in joined:
    sys.exit(0 if os.environ.get("FAKE_AT_HEAD", "1") == "1" else 1)
if args[:1] == ["run"] and "build_agent_workspace_factory" in joined:
    if os.environ.get("FAKE_WORKSPACE_OK", "1") != "1":
        print("WorkspaceConfigurationError: workspace scope directory 'x' "
              "must not grant group or other permissions", file=sys.stderr)
        sys.exit(1)
    sys.exit(0)
if args[:1] == ["run"] and ".deploy-write-check" in joined:
    sys.exit(0 if os.environ.get("FAKE_DESIGN_WRITABLE", "1") == "1" else 1)
if args[:1] == ["run"] and "test -d" in joined:
    sys.exit(0 if os.environ.get("FAKE_OLD_DESIGN_DIR", "0") == "1" else 1)
if args[:1] == ["compose"] and "ps" in args and "-q" in args:
    print("c1\nc2")
    sys.exit(0)
if args[:1] == ["inspect"]:
    # Restart counts: the first look at a container is the baseline; a later look reports
    # FAKE_RESTARTS_AFTER for c1 (a crash loop), 0 for everything else.
    state = os.environ["CALLS_LOG"] + ".inspected"
    container = args[-1]
    seen = open(state).read().split() if os.path.exists(state) else []
    later = container in seen
    with open(state, "a") as fh:
        fh.write(container + "\n")
    restarts = os.environ.get("FAKE_RESTARTS_AFTER", "0") if later and container == "c1" else "0"
    print(f"/vm-{container}-1 {restarts} true")
    sys.exit(0)
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
        "CLUE_LANGFUSE_ENVIRONMENT=production",
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
        "CLUE_DEPLOY_HEALTH_WAIT_S": "0",
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


def _index(calls: list[str], needle: str) -> int:
    return next(i for i, call in enumerate(calls) if needle in call)


def test_the_workers_boot_check_runs_with_the_new_image_before_anything_restarts(
    vm: dict[str, str],
) -> None:
    code, out, calls = _deploy(vm)
    assert code == 0, out
    check = _index(calls, "build_agent_workspace_factory")
    assert f"ghcr.io/clue-hq/clue-backend:{SHA}" in calls[check]
    assert "--user 1000:1000" in calls[check]
    assert check < _index(calls, " up ")


def test_a_failing_boot_check_refuses_the_deploy_and_restarts_nothing(vm: dict[str, str]) -> None:
    """Production 2026-10-04: a 0755 entry in the agent workspace root crash-looped every fleet
    worker after `up`. The same check, run first, stops the deploy with the old workers running."""
    code, out, calls = _deploy(vm, FAKE_WORKSPACE_OK="0")
    assert code != 0
    assert "must not grant group or other permissions" in out
    assert not _compose_up(calls)
    assert not any(" compose " in f" {c} " and " stop " in f" {c} " for c in calls)
    compose_env = Path(vm["CLUE_COMPOSE_ENV"]).read_text(encoding="utf-8")
    assert "BACKEND_IMAGE=old" in compose_env


def test_the_design_workspace_is_always_prepared_before_up(vm: dict[str, str]) -> None:
    code, out, calls = _deploy(vm)
    assert code == 0, out
    prepare = _index(calls, "install -d -m 700 -o 1000 -g 1000 /srv/clue/lumen-agent")
    assert prepare < _index(calls, " up ")
    # Nothing to move: the fleet is not stopped for it.
    assert not any(" compose " in f" {c} " and " stop " in f" {c} " for c in calls)


def test_the_old_nested_design_workspace_is_moved_with_the_fleet_stopped(
    vm: dict[str, str],
) -> None:
    code, out, calls = _deploy(vm, FAKE_OLD_DESIGN_DIR="1")
    assert code == 0, out
    stop = _index(calls, " stop ")
    for service in ("chat", "design", "batch1", "batch2", "batch3", "ingestion"):
        assert service in calls[stop].split()
    move = _index(calls, "/srv/clue/workspaces/lumen-agent/.")
    assert "--user 0:0" in calls[move]
    assert stop < move < _index(calls, " up ")


def test_a_worker_that_restarts_after_up_fails_the_deploy(vm: dict[str, str]) -> None:
    """`up` reports success while a worker that cannot boot restarts forever (177 restarts went
    unnoticed in production on 2026-10-04); the deploy must fail loudly instead."""
    code, out, _calls = _deploy(vm, FAKE_RESTARTS_AFTER="3")
    assert code != 0
    assert "vm-c1-1" in out
    assert f"deployed {SHA}" not in out.splitlines()


def test_the_design_workspace_is_proven_writable_by_the_workers_before_up(
    vm: dict[str, str],
) -> None:
    """Production 2026-10-05: /srv/clue/lumen-agent was root-owned and every design run failed
    with Permission denied — workers booted fine, so neither the boot check nor the health
    check could see it. The deploy now writes there as the workers' user first."""
    code, out, calls = _deploy(vm)
    assert code == 0, out
    check = _index(calls, ".deploy-write-check")
    assert "--user 1000:1000" in calls[check]
    assert _index(calls, "install -d -m 700 -o 1000 -g 1000 /srv/clue/lumen-agent") < check
    assert check < _index(calls, " up ")


def test_an_unwritable_design_workspace_refuses_the_deploy_and_restarts_nothing(
    vm: dict[str, str],
) -> None:
    code, out, calls = _deploy(vm, FAKE_DESIGN_WRITABLE="0", FAKE_OLD_DESIGN_DIR="1")
    assert code != 0
    assert "/srv/clue/lumen-agent" in out
    assert not _compose_up(calls)
    assert not any(" compose " in f" {c} " and " stop " in f" {c} " for c in calls)

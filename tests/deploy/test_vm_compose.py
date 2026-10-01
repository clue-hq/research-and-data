"""The worker VM compose file's invariants (first deployment spec §5.2, §7, §9.4)."""

from __future__ import annotations

from pathlib import Path

import yaml

from clue_fleet import FleetTaskKind

COMPOSE = Path(__file__).resolve().parents[2] / "deploy" / "vm" / "compose.yaml"
WORKSPACE_ROOT = "/srv/clue/workspaces"
#: One service per pool; batch2 and batch3 are identical replicas of batch1.
POOL_SERVICES = ("chat", "design", "batch1")
SLOTS = {"chat": "10", "design": "8", "batch1": "10", "batch2": "10", "batch3": "10"}


def _services() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def _env(service: dict) -> dict[str, str]:
    return {str(k): str(v) for k, v in (service.get("environment") or {}).items()}


def test_every_task_kind_is_claimed_by_exactly_one_pool() -> None:
    """A kind no pool claims would sit queued forever; a kind two pools claim breaks the caps."""
    services = _services()
    claims: dict[str, list[str]] = {}
    for name in POOL_SERVICES:
        for kind in _env(services[name])["CLUE_FLEET_WORKER_KINDS"].split(","):
            claims.setdefault(kind.strip(), []).append(name)
    assert set(claims) == {kind.value for kind in FleetTaskKind}
    assert all(len(owners) == 1 for owners in claims.values()), claims


def test_batch_replicas_are_identical() -> None:
    services = _services()
    assert _env(services["batch2"]) == _env(services["batch1"])
    assert _env(services["batch3"]) == _env(services["batch1"])


def test_pool_sizes_match_the_spec() -> None:
    services = _services()
    for name, slots in SLOTS.items():
        assert _env(services[name])["CLUE_FLEET_WORKER_CONCURRENCY"] == slots, name
    assert _env(services["chat"])["CLUE_FLEET_WORKER_KINDS"] == "agent_turn"
    assert _env(services["design"])["CLUE_FLEET_WORKER_KINDS"] == "design_job"


def test_workers_can_start_sandbox_containers() -> None:
    """docker run mount paths resolve on the HOST, so the workspace root is the same path on both
    sides; the sandbox refuses root, so workers run as a non-root user in the docker group."""
    services = _services()
    for name in (*SLOTS, "ingestion"):
        service = services[name]
        assert f"{WORKSPACE_ROOT}:{WORKSPACE_ROOT}" in service["volumes"], name
        assert _env(service)["CLUE_AGENT_WORKSPACE_ROOT"] == WORKSPACE_ROOT, name
        assert str(service["user"]) == "1000:1000", name
    for name in SLOTS:
        assert "/var/run/docker.sock:/var/run/docker.sock" in services[name]["volumes"], name
        assert "${DOCKER_GID}" in [str(g) for g in services[name]["group_add"]], name


def test_worker_pools_reach_postgres_through_pgbouncer() -> None:
    services = _services()
    for name in SLOTS:
        assert "@pgbouncer:6432/" in _env(services[name])["CLUE_DATABASE_URL"], name


def test_the_ingestion_pool_bypasses_pgbouncer() -> None:
    """Its controller holds a SESSION-level advisory lock (lumen_api/ingestion_pool.py), which
    transaction pooling would release mid-session; it uses the env file's direct database URL."""
    assert "CLUE_DATABASE_URL" not in _env(_services()["ingestion"])

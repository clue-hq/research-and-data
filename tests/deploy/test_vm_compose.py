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


def test_the_ingestion_children_reach_postgres_through_pgbouncer() -> None:
    """The coordinator and analysis children are ordinary fleet workers (transaction-scoped
    locks only), so the ingestion container's CLUE_DATABASE_URL is the PgBouncer one."""
    ingestion = _services()["ingestion"]
    assert "@pgbouncer:6432/" in _env(ingestion)["CLUE_DATABASE_URL"]
    assert "pgbouncer" in ingestion["depends_on"]


def test_only_the_ingestion_controller_gets_a_direct_database_url() -> None:
    """The controller's SESSION advisory lock (lumen_api/ingestion_pool.py) needs a direct
    connection; it reads LUMEN_INGESTION_CONTROLLER_DATABASE_URL from the env file. No service may
    override that name, and no service but ingestion runs the controller."""
    services = _services()
    for name, service in services.items():
        assert "LUMEN_INGESTION_CONTROLLER_DATABASE_URL" not in _env(service), name
    assert [n for n, s in services.items() if s.get("command") == ["ingestion-pool"]] == [
        "ingestion"
    ]


def test_the_ingestion_pool_gets_no_docker_socket() -> None:
    """It runs no sandboxes; fewer containers that can drive the host's Docker."""
    ingestion = _services()["ingestion"]
    assert not any("docker.sock" in str(v) for v in ingestion["volumes"])
    assert "group_add" not in ingestion


def test_the_controller_url_is_documented_with_an_empty_default() -> None:
    """Env parity rule: a LUMEN_* name goes in the root and the design subsystem's .env.example."""
    root = Path(__file__).resolve().parents[2]
    for example in (root / ".env.example", root / "subsystems/clue-design/.env.example"):
        lines = example.read_text(encoding="utf-8").splitlines()
        assert "LUMEN_INGESTION_CONTROLLER_DATABASE_URL=" in lines, example


def test_design_session_memory_has_its_own_mounted_root_outside_the_agent_workspace_root() -> None:
    """Unset, the design agent keeps session memory and compaction history under the image's own
    /app/subsystems/clue-design/.deepagent-workspace, which every redeploy replaces — so it needs
    a mounted host directory. It must NOT be inside CLUE_AGENT_WORKSPACE_ROOT: the fleet workers
    refuse to boot when any entry there is not a private 0700 directory, and the design agent
    creates its root with the default umask (production 2026-10-04: a 0755
    /srv/clue/workspaces/lumen-agent crash-looped every fleet worker after a deploy)."""
    services = _services()
    for name in (*SLOTS, "ingestion"):
        env = _env(services[name])
        root = env.get("LUMEN_AGENT_WORKSPACE_ROOT", "")
        agent_root = env.get("CLUE_AGENT_WORKSPACE_ROOT", WORKSPACE_ROOT)
        assert root.startswith("/"), name
        design, platform = Path(root), Path(agent_root)
        assert not design.is_relative_to(platform), name
        assert not platform.is_relative_to(design), name
        assert f"{root}:{root}" in services[name].get("volumes", []), name

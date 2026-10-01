# First Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the complete Clue app on hosted infrastructure — web tier, Postgres and Redis on Railway, a stateless OVHcloud worker VM, files in Cloudflare R2 — shipped from `main` (with `research-streaming` as staging).

**Architecture:** Every image is booted in CI before it can be deployed: both APIs must answer `/healthz`, a worker must register its handlers and start, and the sandbox must run a trivial script. One backend container image runs every Python service (platform API, design API, fleet worker pools, ingestion pool, migrations) with different commands. Railway runs the web services plus Postgres 16 + pgvector and Redis 7; the VM runs three worker pools (chat 1×10, design 1×8, batch 3×10), the ingestion pool, PgBouncer and the Docker code sandbox from one docker compose file, reaching Postgres/Redis through Railway's TLS TCP proxy. GitHub Actions builds and pushes images on every push to `main`.

**Tech Stack:** Docker (multi-stage), uv (Python 3.12), Rust/cargo (`lumen-api-helper`), Node 24 (design editor Tailwind toolchain), Playwright Chromium, docker compose, PgBouncer, GitHub Actions + GHCR, Railway, OVHcloud VPS, Cloudflare R2.

**Spec:** `docs/superpowers/specs/2026-10-01-first-deployment-design.md` (approved 2026-10-01). Read it before any task.

## Global Constraints

- Region: US East for every tier.
- Worker VM: OVHcloud VPS-4 — 8 vCores / 24 GB / 200 GB NVMe, Ubuntu 24.04, x86_64. It holds **no customer data**.
- Worker pools: chat `agent_turn` 1×10; design `design_job` 1×8; batch = every other kind, 3×10.
- Postgres 16 + pgvector and Redis 7 on Railway; the VM reaches them only through Railway's TCP proxy with TLS.
- Files: `CLUE_STORAGE_BACKEND=s3` against Cloudflare R2.
- Design API on Railway: `LUMEN_EMBEDDED_FLEET_WORKER=0`.
- Pages: `CLUE_PAGES_SYSTEM_SUFFIX=pages.cluehq.ai`, `CLUE_PAGES_PUBLIC_SCHEME=https`, `CLUE_PAGES_TRUST_HOST_HEADER=false`, `CLUE_PAGES_EDGE_SECRET` set.
- Hostnames: `app.cluehq.ai` (frontend), `api.cluehq.ai` (platform API), `design-api.cluehq.ai` (design API).
- Branches: `research-streaming` is staging; `main` is the deployment branch. Releasing = merging a PR from `research-streaming` into `main`; never commit to `main` directly.
- Deploy order: build image → `alembic upgrade head` → Railway services + VM restart.
- Env parity rule (repo CLAUDE.md): every setting the code reads appears in `.env.example` with its default when introduced.
- Worker containers run as a **non-root** user (the sandbox refuses root — `platform/api/clue_api/sandbox/docker_runner.py:90`).
- Repo rules: commit locally at checkpoints; **never push** or touch Railway/OVHcloud/Cloudflare/GitHub settings without the founder's explicit go-ahead for that step; no AI attribution in commits.
- Never run `make check` or broad pytest with real keys; focused test files only, `--ignore-glob='*_live.py'`.

## Review Focus

1. **A task kind no pool claims** — a kind added later, or missed in the compose file, would sit `queued` forever with no error. Pinned by Task 3's coverage test (every `FleetTaskKind` claimed by exactly one pool).
2. **A typo in `CLUE_FLEET_WORKER_KINDS`** — a pool that silently claims nothing. Pinned by Task 1: unknown kind names and an empty selection fail at startup.
3. **Sandbox mount paths inside the worker container** — `docker run -v` paths are resolved by the host daemon, so a workspace root that differs inside/outside the container breaks every `run_python`. Pinned by Task 3's compose test (identical host/container path equal to `CLUE_AGENT_WORKSPACE_ROOT`, non-root user, docker group).
4. **A production env left on a lane default** — embedded design worker on, fs storage, `raw` reasoning trace, trusted Host header. Pinned by Task 5's `check_prod_env.py` tests, run before every deploy.
5. **A backup job that silently produces nothing** — pinned by Task 6: the backup script fails on an empty dump or a dump `pg_restore --list` can't read, and the watchdog alerts when the newest backup is older than 26 hours.

---

## File map

| Path | Responsibility | Task |
|---|---|---|
| `libs/clue-config/clue_config/settings.py` | `fleet_worker_kinds` setting | 1 |
| `platform/api/clue_api/fleet_wiring.py` | parse + apply the kind selection in `build_multi_work_worker` | 1 |
| `tests/api/test_fleet_wiring.py` | kind-selection tests | 1 |
| `.env.example` | `CLUE_FLEET_WORKER_KINDS`, `CLUE_STORAGE_S3_*` | 1, 2 |
| `tests/test_storage_settings_documented.py` | S3 settings documented | 2 |
| `.dockerignore`, `docker/backend/Dockerfile`, `docker/backend/entrypoint.sh`, `docker/backend/smoke.sh` | backend image | 4 |
| `deploy/vm/compose.yaml` | worker VM services (PgBouncer configured by env) | 3 |
| `tests/deploy/test_vm_compose.py` | pool coverage + sandbox mount invariants | 3 |
| `deploy/check_prod_env.py`, `tests/deploy/test_check_prod_env.py` | production env validator | 5 |
| `deploy/vm/backup_db.sh`, `deploy/vm/restore_check.sh`, `deploy/vm/watchdog.sh`, `deploy/vm/systemd/*` | backups, restore rehearsal, VM alerts | 6 |
| `deploy/vm/bootstrap.sh`, `deploy/vm/deploy.sh` | VM provisioning and deploys | 7 |
| `platform/api/clue_api/projections_app.py`, `subsystems/clue-design/apps/api/lumen_api/main.py` | `/healthz` on both APIs | 4A |
| `subsystems/clue-design/scripts/preflight_editor_wasm.mjs`, `…/verify_handshake.mjs`, `apps/frontend/Dockerfile.railway`, `.github/workflows/ci.yml` | engine handshake gate | 4B |
| `docker/backend/boot_smoke.sh`, `.github/workflows/deploy-images.yml` | boot every service in CI; publish `production` tags only after it passes | 8 |
| `docs/deploy/runbook.md` | the whole founder-facing runbook (Railway, Cloudflare, OVHcloud, first ship, rollback, AWS move) | 9 |
| `_memory/2026-10-01-first-deployment.md` | session record | 10 |

---

### Task 1: Worker task-kind selection (`CLUE_FLEET_WORKER_KINDS`)

**Files:**
- Modify: `libs/clue-config/clue_config/settings.py` (next to `fleet_worker_concurrency`, ~line 211)
- Modify: `platform/api/clue_api/fleet_wiring.py` (`build_multi_work_worker`, ~lines 365–500)
- Modify: `.env.example` (the "Fleet worker concurrency" block, ~line 315)
- Test: `tests/api/test_fleet_wiring.py`

**Interfaces:**
- Produces: `Settings.fleet_worker_kinds: str` (default `""`); `clue_api.fleet_wiring.selected_worker_kinds(raw: str) -> frozenset[FleetTaskKind] | None` (`None` = all kinds); `build_multi_work_worker` registers only selected kinds and raises `ValueError` when the selection names an unknown kind or leaves the worker with no handler.

- [ ] **Step 1: Write the failing tests** — append to `tests/api/test_fleet_wiring.py`:

```python
from clue_api.fleet_wiring import selected_worker_kinds


def test_blank_worker_kinds_means_every_kind() -> None:
    assert selected_worker_kinds("") is None
    assert selected_worker_kinds("  ") is None
    assert Settings.model_fields["fleet_worker_kinds"].default == ""


def test_worker_kinds_parse_comma_separated_names() -> None:
    assert selected_worker_kinds("agent_turn, design_job") == frozenset(
        {FleetTaskKind.AGENT_TURN, FleetTaskKind.DESIGN_JOB}
    )


def test_an_unknown_worker_kind_fails_at_startup() -> None:
    with pytest.raises(ValueError, match="agent_turns"):
        selected_worker_kinds("agent_turns")


def test_a_worker_limited_to_one_kind_registers_only_that_kind() -> None:
    worker = build_multi_work_worker(
        _settings(fleet_worker_kinds="agent_turn", fleet_worker_concurrency=10),
        driver=build_fleet_run_driver(),
        graph_handler=_CompositionHandler(FleetTaskKind.EXECUTE_GRAPH),
        agent_turn_handler=_CompositionHandler(FleetTaskKind.AGENT_TURN),
        onboarding_handler=_CompositionHandler(FleetTaskKind.ONBOARDING_RUN),
    )
    assert set(worker._handlers) == {FleetTaskKind.AGENT_TURN}
    assert worker.concurrency == 10


def test_a_selection_that_leaves_no_handler_fails_at_startup() -> None:
    # design_job is selected but this deployment composed no design handler.
    with pytest.raises(ValueError, match="no handler"):
        build_multi_work_worker(
            _settings(fleet_worker_kinds="design_job"),
            driver=build_fleet_run_driver(),
            graph_handler=_CompositionHandler(FleetTaskKind.EXECUTE_GRAPH),
        )


def test_every_kind_is_registered_when_the_selection_is_blank() -> None:
    worker = build_multi_work_worker(
        _settings(),
        driver=build_fleet_run_driver(),
        graph_handler=_CompositionHandler(FleetTaskKind.EXECUTE_GRAPH),
        agent_turn_handler=_CompositionHandler(FleetTaskKind.AGENT_TURN),
    )
    assert {FleetTaskKind.DRIVE_RUN, FleetTaskKind.EXECUTE_GRAPH, FleetTaskKind.AGENT_TURN} <= set(
        worker._handlers
    )


def test_worker_kinds_env_name_is_documented_blank() -> None:
    text = (Path(__file__).resolve().parents[2] / ".env.example").read_text(encoding="utf-8")
    assert re.search(r"^CLUE_FLEET_WORKER_KINDS=$", text, re.MULTILINE)
```

Add `import re` to the file's imports if absent. `FleetTaskKind`, `_CompositionHandler`, `_settings`, `build_fleet_run_driver`, `Path` and `pytest` are already imported/defined in this file.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/api/test_fleet_wiring.py -k "worker_kind or one_kind or no_handler or selection_is_blank" -v`
Expected: FAIL — `ImportError: cannot import name 'selected_worker_kinds'`.

- [ ] **Step 3: Add the setting** — in `settings.py`, directly after `fleet_worker_concurrency`:

```python
    # Which task kinds THIS worker process claims (first deployment, 2026-10-01): a comma-separated
    # list of ``FleetTaskKind`` values, blank = every kind (the behaviour before this setting). It
    # is how one VM runs separate pools — chat (``agent_turn``), design (``design_job``) and batch
    # — so a long research job can never hold the slot a chat turn needs.
    # Env: ``CLUE_FLEET_WORKER_KINDS``.
    fleet_worker_kinds: str = ""
```

- [ ] **Step 4: Implement the selection** — in `fleet_wiring.py`, add near the top-level helpers:

```python
def selected_worker_kinds(raw: str) -> frozenset[FleetTaskKind] | None:
    """Parse ``CLUE_FLEET_WORKER_KINDS``: ``None`` (blank) means every kind.

    An unknown name fails loudly — a typo must not start a worker that silently claims nothing.
    """
    names = [part.strip() for part in raw.split(",") if part.strip()]
    if not names:
        return None
    valid = {kind.value: kind for kind in FleetTaskKind}
    unknown = [name for name in names if name not in valid]
    if unknown:
        raise ValueError(
            f"CLUE_FLEET_WORKER_KINDS names unknown task kinds {unknown}; "
            f"valid kinds are {sorted(valid)}"
        )
    return frozenset(valid[name] for name in names)
```

and in `build_multi_work_worker`, immediately before `return LeasedWorkWorker(`:

```python
    selected = selected_worker_kinds(settings.fleet_worker_kinds)
    if selected is not None:
        handlers = [handler for handler in handlers if handler.kind in selected]
        if not handlers:
            raise ValueError(
                f"CLUE_FLEET_WORKER_KINDS={settings.fleet_worker_kinds!r} leaves this worker with "
                "no handler: none of the selected kinds is composed in this deployment"
            )
```

Add one paragraph to the function's docstring: "``CLUE_FLEET_WORKER_KINDS`` (first deployment) narrows the registered handlers to the named kinds; blank keeps every kind."

- [ ] **Step 5: Document the env name** — in `.env.example`, after `CLUE_FLEET_WORKER_CONCURRENCY=3`:

```bash
# Which task kinds this worker process claims: comma-separated FleetTaskKind values, blank = all
# kinds. The hosted VM runs three pools with it — agent_turn (chat), design_job (design), and every
# other kind (batch). An unknown name refuses to start. (first deployment, 2026-10-01)
CLUE_FLEET_WORKER_KINDS=
```

Also add `CLUE_FLEET_WORKER_KINDS=` to the local `.env` (parity rule; `.env` is untracked).

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/api/test_fleet_wiring.py -v`
Expected: all PASS, including the pre-existing concurrency and serialisation tests.

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check libs/clue-config/clue_config/settings.py platform/api/clue_api/fleet_wiring.py tests/api/test_fleet_wiring.py
git add libs/clue-config/clue_config/settings.py platform/api/clue_api/fleet_wiring.py tests/api/test_fleet_wiring.py .env.example
git commit -m "Let a fleet worker claim only chosen task kinds (CLUE_FLEET_WORKER_KINDS)"
```

---

### Task 2: Document the S3/R2 storage settings in `.env.example`

**Files:**
- Modify: `.env.example` (the storage block, next to `CLUE_STORAGE_BACKEND=fs`, ~line 30)
- Create: `tests/test_storage_settings_documented.py`

**Interfaces:** none (documentation + guard). Names come from `libs/clue-config/clue_config/settings.py:309-317` (settings) and the secrets it names.

- [ ] **Step 1: Write the failing test** — `tests/test_storage_settings_documented.py`:

```python
"""First deployment: the S3/R2 storage settings the code reads are documented in .env.example
(the repo's env parity rule), with their shipped defaults."""

from __future__ import annotations

import re
from pathlib import Path

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"

#: Every storage env name the code reads, and the value .env.example must ship.
DOCUMENTED = {
    "CLUE_STORAGE_BACKEND": "fs",
    "CLUE_STORAGE_S3_BUCKET": "",
    "CLUE_STORAGE_S3_ENDPOINT_URL": "",
    "CLUE_STORAGE_S3_REGION": "",
    "CLUE_STORAGE_S3_ACCESS_KEY_ID": "",
    "CLUE_STORAGE_S3_SECRET_ACCESS_KEY": "",
}


def test_every_storage_env_name_is_documented_with_its_default() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for name, default in DOCUMENTED.items():
        match = re.search(rf"^{name}=(.*)$", text, re.MULTILINE)
        assert match is not None, f"absent from .env.example: {name}"
        assert match.group(1).strip() == default, name
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_storage_settings_documented.py -v`
Expected: FAIL — `absent from .env.example: CLUE_STORAGE_S3_BUCKET`.

- [ ] **Step 3: Add the lines** to `.env.example`, directly under `CLUE_STORAGE_FS_ROOT=…`:

```bash
# S3-compatible storage (AWS S3 / Cloudflare R2 / MinIO) — used when CLUE_STORAGE_BACKEND=s3.
# Production uses Cloudflare R2: endpoint https://<account-id>.r2.cloudflarestorage.com, region auto.
# The bucket is required for the s3 backend (the factory fails loud without it).
CLUE_STORAGE_S3_BUCKET=
CLUE_STORAGE_S3_ENDPOINT_URL=
CLUE_STORAGE_S3_REGION=
# Secrets (R2 API token's access key pair) — never commit real values.
CLUE_STORAGE_S3_ACCESS_KEY_ID=
CLUE_STORAGE_S3_SECRET_ACCESS_KEY=
```

Add the same five blank keys to the local `.env`.

- [ ] **Step 4: Run to verify it passes**

Run: `uv run pytest tests/test_storage_settings_documented.py -v`
Expected: PASS.

- [ ] **Step 5: Confirm the secret names really are the ones the code reads**

Run: `grep -rn "STORAGE_S3_ACCESS_KEY_ID\|storage_s3_access_key_id" libs/clue-config libs/clue-storage`
Expected: the `Secrets` field in `libs/clue-config` whose env name matches. If the actual env name differs, use the actual name in both `.env.example` and the test.

- [ ] **Step 6: Commit**

```bash
git add .env.example tests/test_storage_settings_documented.py
git commit -m "Document the S3/R2 storage settings in .env.example"
```

---

### Task 3: Worker VM compose file, with its invariants tested

**Files:**
- Create: `deploy/vm/compose.yaml`
- Create: `tests/deploy/__init__.py` (empty), `tests/deploy/test_vm_compose.py`

**Interfaces:**
- Consumes: `CLUE_FLEET_WORKER_KINDS` (Task 1); the backend image commands `fleet-worker` and `ingestion-pool` (Task 4).
- Produces: compose services `pgbouncer`, `chat`, `design`, `batch1`, `batch2`, `batch3`, `ingestion`; VM paths `/srv/clue/env` (application env, 0600), `/srv/clue/pgbouncer.env` (0600), `/srv/clue/compose.env` (compose variables: `BACKEND_IMAGE`, `DOCKER_GID`, `PGBOUNCER_CLIENT_PASSWORD`), `/srv/clue/workspaces`, `/srv/clue/engine-cache`. The worker database URL is `postgresql+asyncpg://clue_worker:${PGBOUNCER_CLIENT_PASSWORD}@pgbouncer:6432/railway`.

- [ ] **Step 1: Write the failing test** — `tests/deploy/test_vm_compose.py`:

```python
"""The worker VM compose file's invariants (first deployment spec §5.2, §9.4)."""

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


def test_workers_reach_postgres_only_through_pgbouncer() -> None:
    services = _services()
    for name in (*SLOTS, "ingestion"):
        assert "@pgbouncer:6432/" in _env(services[name])["CLUE_DATABASE_URL"], name
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/deploy/test_vm_compose.py -v`
Expected: FAIL — `FileNotFoundError: …/deploy/vm/compose.yaml`. (If `import yaml` fails, run with `uv run --with pyyaml pytest …`.)

- [ ] **Step 3: PgBouncer in transaction mode; the one session lock connects directly**

Transaction pooling breaks session-level advisory locks (and named prepared statements — PgBouncer
≥1.21 handles those with `MAX_PREPARED_STATEMENTS`). Find the session locks:

```bash
grep -rn "pg_advisory_lock\b\|pg_try_advisory_lock\b" platform libs subsystems --include='*.py' | grep -v /tests/
```

Found (2026-10-01): exactly one — the ingestion pool's controller
(`subsystems/clue-design/apps/api/lumen_api/ingestion_pool.py`), which holds it across commits as
its leadership claim. Everything else (59 sites) is `pg_advisory_xact_lock`. Ruling (founder,
2026-10-01): **PgBouncer stays `POOL_MODE=transaction`, `DEFAULT_POOL_SIZE=20` for every fleet
worker and for the ingestion children; only the controller reaches Postgres directly** through
Railway's TCP proxy — one connection, needs no pooling, and its session lock behaves correctly.
Never session mode for the whole VM. (The rejected alternative: a second, session-mode PgBouncer
pool used by the controller alone — more moving parts for one connection.)

Mechanism: a new setting `LUMEN_INGESTION_CONTROLLER_DATABASE_URL` (default empty = use
`CLUE_DATABASE_URL`), read only by `ingestion_pool.controller_engine()`. The ingestion container's
`CLUE_DATABASE_URL` is the PgBouncer one (from `x-worker-env`), which the children inherit; the
env file carries the direct URL under the controller's name. `check_prod_env.py worker` requires it
and refuses one pointing at PgBouncer or localhost. Tests:
`subsystems/clue-design/apps/api/tests/test_ingestion_pool_database_url.py` (controller uses the
override; falls back when unset; children get no rewritten env; the env name loads) and
`tests/deploy/test_vm_compose.py` / `test_check_prod_env.py`. Document the name with an empty default
in both `.env.example` files.

- [ ] **Step 4: Write `deploy/vm/compose.yaml`:**

```yaml
# Worker VM (OVHcloud VPS-4) — first deployment spec §5.2, §9.4. Holds no customer data.
# Compose variables come from /srv/clue/compose.env (BACKEND_IMAGE, DOCKER_GID,
# PGBOUNCER_CLIENT_PASSWORD); the application env from /srv/clue/env (mode 0600).
# Run: docker compose --env-file /srv/clue/compose.env -f compose.yaml up -d

x-worker: &worker
  image: ${BACKEND_IMAGE}
  command: ["fleet-worker"]
  env_file: [/srv/clue/env]
  user: "1000:1000"
  group_add: ["${DOCKER_GID}"]
  restart: unless-stopped
  stop_grace_period: 60s
  depends_on: [pgbouncer]
  volumes:
    - /var/run/docker.sock:/var/run/docker.sock
    - /srv/clue/workspaces:/srv/clue/workspaces
    - /srv/clue/engine-cache:/srv/clue/engine-cache

x-worker-env: &worker-env
  CLUE_DATABASE_URL: postgresql+asyncpg://clue_worker:${PGBOUNCER_CLIENT_PASSWORD}@pgbouncer:6432/railway
  CLUE_AGENT_WORKSPACE_ROOT: /srv/clue/workspaces
  LUMEN_ASSET_STORE_ROOT: /srv/clue/engine-cache

x-batch: &batch
  <<: *worker
  environment:
    <<: *worker-env
    CLUE_FLEET_WORKER_KINDS: drive_run,account_job,execute_graph,entity_research_job,stage0_recon,official_site_crawl,onboarding_run,arv2_account_research,arv2_discovery,arv2_display_page
    CLUE_FLEET_WORKER_CONCURRENCY: "10"

services:
  pgbouncer:
    image: edoburu/pgbouncer:v1.23.1-p3
    restart: unless-stopped
    env_file: [/srv/clue/pgbouncer.env]

  chat:
    <<: *worker
    environment:
      <<: *worker-env
      CLUE_FLEET_WORKER_KINDS: agent_turn
      CLUE_FLEET_WORKER_CONCURRENCY: "10"

  design:
    <<: *worker
    environment:
      <<: *worker-env
      CLUE_FLEET_WORKER_KINDS: design_job
      CLUE_FLEET_WORKER_CONCURRENCY: "8"

  batch1: *batch
  batch2: *batch
  batch3: *batch

  ingestion:
    <<: *worker
    command: ["ingestion-pool"]
    group_add: []
    volumes:
      - /srv/clue/workspaces:/srv/clue/workspaces
      - /srv/clue/engine-cache:/srv/clue/engine-cache
    environment:
      <<: *worker-env
```

PgBouncer is configured entirely from `/srv/clue/pgbouncer.env` (the `edoburu/pgbouncer` image turns these variables into its config — check the variable names against the image README for the pinned tag before first use): `DATABASE_URL=postgres://clue_worker:<password>@<railway-proxy-host>:<port>/railway`, `POOL_MODE` and `DEFAULT_POOL_SIZE` (Step 3), `AUTH_TYPE=scram-sha-256`, `SERVER_TLS_SSLMODE=require`, `MAX_CLIENT_CONN=200`, `LISTEN_PORT=6432`.

- [ ] **Step 5: Run to verify the tests pass**

Run: `uv run pytest tests/deploy/test_vm_compose.py -v`
Expected: all PASS.

- [ ] **Step 6: Validate compose syntax**

Run: `BACKEND_IMAGE=x DOCKER_GID=999 PGBOUNCER_CLIENT_PASSWORD=x docker compose -f deploy/vm/compose.yaml config --quiet`
Expected: exit 0. If it fails only because `/srv/clue/*.env` files are absent on this machine, add `--no-interpolate` or create empty temporary files at those paths inside a throwaway container; the pytest invariants are the gate.

- [ ] **Step 7: Commit**

```bash
git add deploy/vm/compose.yaml tests/deploy/__init__.py tests/deploy/test_vm_compose.py
git commit -m "Worker VM compose: chat, design and batch pools, ingestion, PgBouncer (<pool mode> pooling: <count> session advisory lock sites)"
```

---

### Task 4: The backend image

**Files:**
- Create: `.dockerignore`
- Create: `docker/backend/Dockerfile`
- Create: `docker/backend/entrypoint.sh`
- Create: `docker/backend/smoke.sh`

**Interfaces:**
- Produces: image entrypoint `clue <command>` with commands `platform-api`, `design-api`, `fleet-worker`, `ingestion-pool`, `migrate`, `shell`; baked defaults `LUMEN_CORE_HELPER=/app/subsystems/clue-design/target/release/lumen-api-helper`, `LUMEN_FONT_LIBRARY_MANIFEST_PATH=/app/subsystems/clue-design/apps/api/font-library/manifest.json`; the image runs as uid 1000 by default.

- [ ] **Step 1: Write the smoke test first** — `docker/backend/smoke.sh`:

```bash
#!/usr/bin/env bash
# Smoke-test a built backend image: every service imports, the helper runs, Chromium and the
# Tailwind toolchain are present. Usage: docker/backend/smoke.sh <image>
set -Eeuo pipefail
IMAGE="${1:?usage: smoke.sh <image>}"
run() { docker run --rm --entrypoint "" "$IMAGE" "$@"; }

run python -c "import clue_api.projections_main, clue_api.fleet_main, clue_page_origin.main" \
  && echo "ok: platform imports"
run bash -c 'cd /app/subsystems/clue-design && PYTHONPATH=.:apps/api:apps/agent_runtime python -c "import lumen_api.main, lumen_api.ingestion_pool"' \
  && echo "ok: design imports"
run test -x /app/subsystems/clue-design/target/release/lumen-api-helper && echo "ok: helper present"
run test -f /app/subsystems/clue-design/apps/api/font-library/manifest.json && echo "ok: font manifest"
run test -d /app/subsystems/clue-design/apps/editor/node_modules/@tailwindcss/node && echo "ok: tailwind toolchain"
run node --version
run docker --version
run python -c "from playwright.sync_api import sync_playwright; p=sync_playwright().start(); b=p.chromium.launch(); b.close(); p.stop(); print('ok: chromium launches')"
run id -u | grep -qx 1000 && echo "ok: non-root"
run alembic --help >/dev/null && echo "ok: alembic"
echo "SMOKE PASSED"
```

`chmod +x docker/backend/smoke.sh`.

- [ ] **Step 2: Write `.dockerignore`:**

```
.git
**/.venv
**/node_modules
**/__pycache__
**/.pytest_cache
**/target
.artifacts
.context
_memory
docs
apps/frontend
subsystems/clue-design/.engine-cache
subsystems/clue-design/.design-runs
subsystems/clue-design/apps/editor/.next
.env
**/.env
```

- [ ] **Step 3: Write `docker/backend/entrypoint.sh`:**

```bash
#!/usr/bin/env bash
# One image, every Python service (first deployment spec §9.1). Railway sets PORT.
set -Eeuo pipefail
DESIGN_DIR=/app/subsystems/clue-design
DESIGN_PATH=".:apps/api:apps/agent_runtime"

case "${1:-}" in
  platform-api)
    cd /app && exec uvicorn clue_api.projections_main:app --host 0.0.0.0 --port "${PORT:-8020}" ;;
  design-api)
    cd "$DESIGN_DIR" && PYTHONPATH="$DESIGN_PATH" exec uvicorn lumen_api.main:app --host 0.0.0.0 --port "${PORT:-8010}" ;;
  fleet-worker)
    cd /app && exec python -m clue_api.fleet_main ;;
  ingestion-pool)
    cd "$DESIGN_DIR" && PYTHONPATH="$DESIGN_PATH" exec python -m lumen_api.ingestion_pool ;;
  migrate)
    cd /app && exec alembic upgrade head ;;
  shell)
    shift; exec bash "$@" ;;
  *)
    echo "usage: clue {platform-api|design-api|fleet-worker|ingestion-pool|migrate|shell}" >&2
    exit 2 ;;
esac
```

`chmod +x docker/backend/entrypoint.sh`.

- [ ] **Step 4: Write `docker/backend/Dockerfile`:**

```dockerfile
# syntax=docker/dockerfile:1
# The backend image (first deployment spec §9.1): platform API, design API, fleet workers,
# ingestion pool and migrations, started by `clue <command>` (docker/backend/entrypoint.sh).

# --- Rust design-engine helper -------------------------------------------------------------
FROM rust:1-bookworm AS helper
WORKDIR /src
COPY subsystems/clue-design/Cargo.toml subsystems/clue-design/Cargo.lock ./
COPY subsystems/clue-design/crates ./crates
RUN cargo build --release -p lumen-api-helper

# --- Design editor's Tailwind toolchain (used at web export) ------------------------------------
FROM node:24-bookworm-slim AS editor
WORKDIR /src/subsystems/clue-design
COPY subsystems/clue-design/apps/editor/package.json subsystems/clue-design/apps/editor/package-lock.json ./apps/editor/
RUN cd apps/editor && npm ci --ignore-scripts
COPY subsystems/clue-design/scripts/vendor_tailwind_runtime.sh ./scripts/
RUN bash scripts/vendor_tailwind_runtime.sh

# --- Runtime ------------------------------------------------------------------------------
FROM python:3.12-slim-bookworm AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.10 /uv /usr/local/bin/uv
COPY --from=node:24-bookworm-slim /usr/local/bin/node /usr/local/bin/node
COPY --from=docker:27-cli /usr/local/bin/docker /usr/local/bin/docker
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1 PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv PATH=/app/.venv/bin:$PATH \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN apt-get update && apt-get install -y --no-install-recommends fontconfig libfontconfig1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY . /app
RUN uv sync --frozen --no-dev --all-packages
RUN python -m playwright install --with-deps chromium && chmod -R a+rX /ms-playwright
COPY --from=helper /src/target/release/lumen-api-helper /app/subsystems/clue-design/target/release/lumen-api-helper
COPY --from=editor /src/subsystems/clue-design/apps/editor/node_modules /app/subsystems/clue-design/apps/editor/node_modules
COPY --from=editor /src/subsystems/clue-design/apps/editor/public/vendor /app/subsystems/clue-design/apps/editor/public/vendor
ENV LUMEN_CORE_HELPER=/app/subsystems/clue-design/target/release/lumen-api-helper \
    LUMEN_FONT_LIBRARY_MANIFEST_PATH=/app/subsystems/clue-design/apps/api/font-library/manifest.json
COPY docker/backend/entrypoint.sh /usr/local/bin/clue
RUN useradd --uid 1000 --create-home clue && chown -R clue:clue /app/subsystems/clue-design
USER 1000:1000
ENTRYPOINT ["clue"]
```

- [ ] **Step 5: Build the image locally (disk-careful)**

The Docker Desktop VM disk on the founder's Mac is small and hosts the lane Postgres (incident 2026-09-07). Before building: `docker system df`. After the smoke test: remove the image and prune the builder cache.

Run: `docker build --platform linux/amd64 -f docker/backend/Dockerfile -t clue-backend:local .`
Expected: build succeeds. If `cargo build` fails on a missing system library, add it to the `helper` stage's `apt-get` (none were needed on GitHub's `ubuntu-latest` — `subsystems/clue-design/.github/workflows/conformance.yml:101`). If `uv sync --all-packages` is not accepted by uv 0.10, use `uv sync --frozen --no-dev --all-packages --no-editable` or list packages with repeated `--package`.

- [ ] **Step 6: Run the smoke test**

Run: `docker/backend/smoke.sh clue-backend:local`
Expected: every `ok:` line and `SMOKE PASSED`.

- [ ] **Step 7: Clean up the local image and cache**

```bash
docker rmi clue-backend:local
docker builder prune -af
docker system df
```

- [ ] **Step 8: Commit**

```bash
git add .dockerignore docker/backend/Dockerfile docker/backend/entrypoint.sh docker/backend/smoke.sh
git commit -m "One backend image for every Python service, with a smoke test"
```

---

### Task 4A: `/healthz` on the platform API and the design API

Neither API has a health route today (only the page origin does — `platform/page_origin/clue_page_origin/routes.py:78`). The boot smoke test (Task 8), Railway's health check and the uptime monitors (Task 9) all need one.

**Files:**
- Modify: `platform/api/clue_api/projections_app.py` (`create_projections_app`, after `app = FastAPI(` ~line 898)
- Modify: `subsystems/clue-design/apps/api/lumen_api/main.py` (`create_app`, after `app = FastAPI(` ~line 776)
- Test: `tests/api/test_projections_app.py`, `subsystems/clue-design/apps/api/tests/test_healthz.py`

**Interfaces:**
- Produces: `GET /healthz` → `200 {"status": "ok"}` on both APIs, with **no** auth header and **no** `X-Workspace-Id`, and no database or Redis call (a health check must not fail because a dependency is slow — dependency failures surface in the boot smoke and the logs).

- [ ] **Step 1: Write the failing platform test** — append to `tests/api/test_projections_app.py`:

```python
def test_healthz_answers_without_auth_or_workspace() -> None:
    async def _run() -> None:
        async with rollback_conn(seed_pack=False) as conn:
            async with _client(_app(conn)) as client:
                response = await client.get("/healthz")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

    run_async(_run())
```

- [ ] **Step 2: Write the failing design test** — `subsystems/clue-design/apps/api/tests/test_healthz.py`:

```python
from __future__ import annotations

from fastapi.testclient import TestClient


def test_healthz_answers_without_a_workspace_header(tmp_path, design_storage) -> None:
    from lumen_api.main import create_app

    app = create_app(tmp_path / "engine-cache", storage=design_storage)
    with TestClient(app) as client:  # deliberately NOT make_client: no X-Workspace-Id header
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
```

- [ ] **Step 3: Run both to verify they fail**

Run: `uv run pytest tests/api/test_projections_app.py -k healthz -v` and
`(set -a; source .env; set +a; cd subsystems/clue-design && LUMEN_INGESTION_DESCRIBE=0 LUMEN_INGESTION_VISION=0 uv run pytest apps/api/tests/test_healthz.py -v)`
Expected: both FAIL with 404 (the design one may be 401 if a workspace guard runs first — still a failure).

- [ ] **Step 4: Add the route to both apps** — immediately after each `app = FastAPI(...)` line:

```python
    @app.get("/healthz", include_in_schema=False)
    async def healthz() -> dict[str, str]:
        """Liveness for Railway's health check, the uptime monitors and the boot smoke test.
        Touches no database or Redis, and needs no auth or workspace header."""
        return {"status": "ok"}
```

- [ ] **Step 5: Run both to verify they pass**

Same commands as Step 3. Expected: PASS. If either still returns 401/403, an app-wide auth or workspace middleware runs before routing: find it (`grep -n "add_middleware\|@app.middleware" <file>`) and add `/healthz` to that middleware's existing exemption list (the page origin's edge gate exempts `/healthz` the same way — `platform/page_origin/clue_page_origin/routes.py:3`). Do not weaken the middleware for any other path.

- [ ] **Step 6: Commit**

```bash
git add platform/api/clue_api/projections_app.py subsystems/clue-design/apps/api/lumen_api/main.py tests/api/test_projections_app.py subsystems/clue-design/apps/api/tests/test_healthz.py
git commit -m "Add /healthz to the platform API and the design API"
```

---

### Task 4B: Engine handshake gate (browser wasm ⇄ server helper)

The browser wasm is a **committed** file (`subsystems/clue-design/apps/editor/public/wasm/lumen_wasm_bg.wasm` + `lumen_wasm.js`); the server's `lumen-api-helper` is compiled from source. Both bake `schema_version` and `engine_commit` (a content hash of `crates/lumen-core` sources — `crates/build_support/engine_stamp.rs`); the editor locks canvas editing when they differ. Today the frontend build's preflight only **warns** on a stale wasm and exits 0 (`subsystems/clue-design/scripts/preflight_editor_wasm.mjs:125`), so a forgotten rebuild ships silently. Spec §9.5.

**Files:**
- Modify: `subsystems/clue-design/scripts/preflight_editor_wasm.mjs` (strict mode)
- Modify: `subsystems/clue-design/scripts/verify_handshake.mjs` (helper command override)
- Modify: `apps/frontend/Dockerfile.railway` (strict preflight in the Railway build, before line 47's `RUN npm run design-system:build && npm run build`)
- Modify: `apps/frontend/scripts/copy-design-vendor.mjs` (re-throw a failing preflight in strict mode)
- Modify: `.github/workflows/ci.yml` (fast handshake job on PRs and pushes to `research-streaming` / `main`)

**Interfaces:**
- Produces: env `WASM_PREFLIGHT_STRICT=1` → the preflight exits **1** on a stale or unreadable committed wasm (and when sources can't be hashed) instead of rebuilding; env `HANDSHAKE_HELPER_CMD` → `verify_handshake.mjs` runs that shell command (stdin = the `build_info` request) instead of `cargo run`. Task 8 consumes both.

- [ ] **Step 1: Confirm today's committed wasm is in sync (baseline)**

Run: `node subsystems/clue-design/scripts/preflight_editor_wasm.mjs`
Expected: `[wasm-preflight] editor engine up to date (<12-hex>)`. If it says it is stale and starts rebuilding, stop: the committed wasm is already out of date on `research-streaming` — rebuild it (`bash subsystems/clue-design/scripts/build_wasm_core.sh && node subsystems/clue-design/scripts/verify_handshake.mjs`), commit the rebuilt files as their own commit, and tell the founder before continuing.

- [ ] **Step 2: Add strict mode to the preflight** — in `preflight_editor_wasm.mjs`, add after the imports:

```js
// Deploy/CI mode (first deployment spec §9.5): never rebuild, never warn-and-continue — a stale
// committed wasm FAILS, because shipping it means an uneditable canvas for every user.
const STRICT = process.env.WASM_PREFLIGHT_STRICT === "1";
```

In the `sourceStamp()` failure branch, replace `process.exit(0);` with `process.exit(STRICT ? 1 : 0);`.

Immediately after the `if (built === expected) { … process.exit(0); }` block, add:

```js
if (STRICT) {
  console.error(
    `[wasm-preflight] STRICT: committed editor engine ${built ?? "missing"} != engine sources ${expected}.\n` +
      "  The browser wasm was not rebuilt after an engine change. Fix, then commit the result:\n" +
      "    bash subsystems/clue-design/scripts/build_wasm_core.sh\n" +
      "    node subsystems/clue-design/scripts/verify_handshake.mjs"
  );
  process.exit(1);
}
```

Update the file's header comment: "Non-fatal by design" → "Non-fatal by design in local dev; `WASM_PREFLIGHT_STRICT=1` (Railway build, CI) makes a stale wasm fatal."

- [ ] **Step 3: Prove strict mode fails on drift and passes when clean**

```bash
F=subsystems/clue-design/crates/lumen-core/src/lib.rs
echo "// handshake-gate drift probe" >> "$F"
WASM_PREFLIGHT_STRICT=1 node subsystems/clue-design/scripts/preflight_editor_wasm.mjs; echo "exit=$?"
git checkout -- "$F"
WASM_PREFLIGHT_STRICT=1 node subsystems/clue-design/scripts/preflight_editor_wasm.mjs; echo "exit=$?"
```

Expected: first run prints `STRICT: committed editor engine … != engine sources …` and `exit=1`; after the revert, `editor engine up to date` and `exit=0`. Confirm `git status` shows `lib.rs` unmodified. (If `lumen-core` has no `src/lib.rs`, use any `.rs` file under `crates/lumen-core/src/`.)

- [ ] **Step 4: Let `verify_handshake.mjs` ask a helper inside an image** — replace its `const helperOutput = execFileSync("cargo", …);` statement with:

```js
// HANDSHAKE_HELPER_CMD (deploy workflow, spec §9.5): ask the helper INSIDE the built image, so the
// check compares exactly the two artifacts that will be deployed. Unset = build and run it locally.
const request = JSON.stringify({ action: "build_info" });
const helperCmd = process.env.HANDSHAKE_HELPER_CMD;
const helperOutput = helperCmd
  ? execFileSync("bash", ["-c", helperCmd], { input: request, encoding: "utf8" })
  : execFileSync(
      "cargo",
      ["run", "--quiet", "--manifest-path", path.join(root, "Cargo.toml"), "-p", "lumen-api-helper"],
      { input: request, encoding: "utf8" }
    );
```

Verify the local path still works: `node subsystems/clue-design/scripts/verify_handshake.mjs` → prints both versions and exits 0. (It compiles the helper; allow a few minutes on first run.)

- [ ] **Step 5: Make the frontend's Railway build strict** — in `apps/frontend/Dockerfile.railway`, directly above `RUN npm run design-system:build && npm run build`:

```dockerfile
# A stale committed editor wasm must fail this build, not ship an uneditable canvas
# (first deployment spec §9.5). copy-design-vendor.mjs runs the preflight during prebuild.
ENV WASM_PREFLIGHT_STRICT=1
```

The prebuild wrapper swallows a failing preflight: `apps/frontend/scripts/copy-design-vendor.mjs` (~line 78) runs it inside `try { … } catch (error) { console.warn(…) }` so a crash "must not take the app down". In strict mode that would hide exactly the failure we want. Add, as the first line inside that `catch (error) {` block:

```js
  // Strict (Railway build, spec §9.5): a stale editor wasm must fail the build, not warn.
  if (process.env.WASM_PREFLIGHT_STRICT === "1") throw error;
```

(The preflight inherits the environment — the `execFileSync` call passes no `env` option — so the variable reaches it.)

Verify, still without a full image build:

```bash
cd apps/frontend
WASM_PREFLIGHT_STRICT=1 node scripts/copy-design-vendor.mjs; echo "clean exit=$?"
echo "// handshake-gate drift probe" >> ../../subsystems/clue-design/crates/lumen-core/src/lib.rs
WASM_PREFLIGHT_STRICT=1 node scripts/copy-design-vendor.mjs; echo "drift exit=$?"
git checkout -- ../../subsystems/clue-design/crates/lumen-core/src/lib.rs
cd ../..
```

Expected: `clean exit=0`; `drift exit=1` with the STRICT message; `lib.rs` restored.

- [ ] **Step 6: Add the fast CI job** — in `.github/workflows/ci.yml`, change the trigger to:

```yaml
on:
  push:
    branches: [main, research-streaming]
  pull_request:
```

and add a second job beside `check`:

```yaml
  engine-handshake:
    # Seconds, not minutes: hashes the lumen-core sources and reads the committed wasm's stamp.
    # Catches an engine change merged without a rebuilt browser wasm (first deployment spec §9.5).
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "24"
      - name: Committed editor wasm matches the engine sources
        env:
          WASM_PREFLIGHT_STRICT: "1"
        run: node subsystems/clue-design/scripts/preflight_editor_wasm.mjs
```

Run: `actionlint .github/workflows/ci.yml` → no errors.

Note for the founder: adding `research-streaming` to `push` also runs the existing `check` job (`make check` + `make db-smoke`) on every push there. If that job is too slow for staging pushes, move it to `pull_request` only and keep `engine-handshake` on both.

- [ ] **Step 7: Commit**

```bash
git add subsystems/clue-design/scripts/preflight_editor_wasm.mjs subsystems/clue-design/scripts/verify_handshake.mjs apps/frontend/Dockerfile.railway apps/frontend/scripts/copy-design-vendor.mjs .github/workflows/ci.yml
git commit -m "Gate deploys on the editor engine handshake: strict wasm preflight, helper-in-image check"
```

---

### Task 5: Production env validator (`deploy/check_prod_env.py`)

**Files:**
- Create: `deploy/check_prod_env.py`
- Create: `tests/deploy/test_check_prod_env.py`

**Interfaces:**
- Produces: `deploy.check_prod_env.problems(env: dict[str, str], role: str) -> list[str]` where `role` is one of `platform-api`, `design-api`, `worker`; CLI `uv run python deploy/check_prod_env.py <role> <env-file>` exits 1 and prints each problem when any is found.

- [ ] **Step 1: Write the failing tests** — `tests/deploy/test_check_prod_env.py`:

```python
from __future__ import annotations

import importlib.util
from pathlib import Path

_PATH = Path(__file__).resolve().parents[2] / "deploy" / "check_prod_env.py"
_spec = importlib.util.spec_from_file_location("check_prod_env", _PATH)
check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check)  # type: ignore[union-attr]

GOOD_COMMON = {
    "CLUE_DATABASE_URL": "postgresql+asyncpg://u:p@db.internal:5432/clue",
    "CLUE_REDIS_URL": "redis://default:p@redis.internal:6379/0",
    "CLUE_STORAGE_BACKEND": "s3",
    "CLUE_STORAGE_S3_BUCKET": "clue-prod",
    "CLUE_STORAGE_S3_ENDPOINT_URL": "https://acct.r2.cloudflarestorage.com",
    "CLUE_STORAGE_S3_ACCESS_KEY_ID": "k",
    "CLUE_STORAGE_S3_SECRET_ACCESS_KEY": "s",
    "CLUE_PAGES_SYSTEM_SUFFIX": "pages.cluehq.ai",
    "CLUE_PAGES_PUBLIC_SCHEME": "https",
    "CLUE_PAGES_TRUST_HOST_HEADER": "false",
    "CLUE_PAGES_EDGE_SECRET": "edge",
    "CLUE_SCRAPE_BACKEND": "scrapling",
    "CLUE_STAGE0_PAGE_FETCHER": "scrapling",
    "CLUE_CHAT_REASONING_TRACE_MODE": "",
}


def test_a_correct_design_api_env_has_no_problems() -> None:
    env = {**GOOD_COMMON, "LUMEN_EMBEDDED_FLEET_WORKER": "0"}
    assert check.problems(env, "design-api") == []


def test_the_embedded_design_worker_must_be_off_on_railway() -> None:
    env = {**GOOD_COMMON, "LUMEN_EMBEDDED_FLEET_WORKER": "1"}
    assert any("LUMEN_EMBEDDED_FLEET_WORKER" in p for p in check.problems(env, "design-api"))


def test_lane_defaults_are_caught() -> None:
    env = {
        **GOOD_COMMON,
        "CLUE_STORAGE_BACKEND": "fs",
        "CLUE_CHAT_REASONING_TRACE_MODE": "raw",
        "CLUE_PAGES_TRUST_HOST_HEADER": "true",
        "CLUE_DATABASE_URL": "postgresql+asyncpg://clue:clue@localhost:55040/clue_lane",
    }
    found = " ".join(check.problems(env, "platform-api"))
    for name in ("CLUE_STORAGE_BACKEND", "CLUE_CHAT_REASONING_TRACE_MODE",
                 "CLUE_PAGES_TRUST_HOST_HEADER", "localhost"):
        assert name in found


def test_workers_must_not_pick_their_own_kinds_in_the_shared_env_file() -> None:
    """Pool kinds live in compose.yaml; a kinds line in the shared env file would override them."""
    env = {**GOOD_COMMON, "CLUE_FLEET_WORKER_KINDS": "agent_turn"}
    assert any("CLUE_FLEET_WORKER_KINDS" in p for p in check.problems(env, "worker"))


def test_an_unknown_role_is_refused() -> None:
    import pytest

    with pytest.raises(ValueError):
        check.problems(GOOD_COMMON, "frontend")
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/deploy/test_check_prod_env.py -v`
Expected: FAIL — `FileNotFoundError` for `deploy/check_prod_env.py`.

- [ ] **Step 3: Implement `deploy/check_prod_env.py`:**

```python
"""Refuse a production env that still carries a lane default (first deployment spec §10).

Usage: uv run python deploy/check_prod_env.py {platform-api|design-api|worker} <env-file>
"""

from __future__ import annotations

import sys
from pathlib import Path

ROLES = ("platform-api", "design-api", "worker")

#: name -> the only acceptable production value.
EXACT = {
    "CLUE_STORAGE_BACKEND": "s3",
    "CLUE_PAGES_SYSTEM_SUFFIX": "pages.cluehq.ai",
    "CLUE_PAGES_PUBLIC_SCHEME": "https",
    "CLUE_PAGES_TRUST_HOST_HEADER": "false",
    "CLUE_SCRAPE_BACKEND": "scrapling",
    "CLUE_STAGE0_PAGE_FETCHER": "scrapling",
}
#: names that must be set to something non-empty.
REQUIRED = (
    "CLUE_DATABASE_URL",
    "CLUE_REDIS_URL",
    "CLUE_STORAGE_S3_BUCKET",
    "CLUE_STORAGE_S3_ENDPOINT_URL",
    "CLUE_STORAGE_S3_ACCESS_KEY_ID",
    "CLUE_STORAGE_S3_SECRET_ACCESS_KEY",
    "CLUE_PAGES_EDGE_SECRET",
)


def parse(text: str) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def problems(env: dict[str, str], role: str) -> list[str]:
    if role not in ROLES:
        raise ValueError(f"unknown role {role!r}; expected one of {ROLES}")
    found: list[str] = []
    for name, wanted in EXACT.items():
        if env.get(name, "") != wanted:
            found.append(f"{name} must be {wanted!r} in production (is {env.get(name)!r})")
    for name in REQUIRED:
        if not env.get(name):
            found.append(f"{name} must be set")
    if env.get("CLUE_CHAT_REASONING_TRACE_MODE", "") == "raw":
        found.append("CLUE_CHAT_REASONING_TRACE_MODE=raw is dev-only")
    for name in ("CLUE_DATABASE_URL", "CLUE_REDIS_URL"):
        value = env.get(name, "")
        if "localhost" in value or "127.0.0.1" in value:
            found.append(f"{name} points at localhost")
    if role == "design-api" and env.get("LUMEN_EMBEDDED_FLEET_WORKER") != "0":
        found.append("LUMEN_EMBEDDED_FLEET_WORKER must be 0 on Railway (design jobs belong to the VM)")
    if role == "worker" and env.get("CLUE_FLEET_WORKER_KINDS"):
        found.append("CLUE_FLEET_WORKER_KINDS must not be set in the shared env file (compose.yaml sets it per pool)")
    return found


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(__doc__, file=sys.stderr)
        return 2
    role, path = argv[1], Path(argv[2])
    found = problems(parse(path.read_text(encoding="utf-8")), role)
    for problem in found:
        print(f"PROBLEM: {problem}")
    print("OK" if not found else f"{len(found)} problem(s)")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
```

- [ ] **Step 4: Run to verify they pass**

Run: `uv run pytest tests/deploy/test_check_prod_env.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add deploy/check_prod_env.py tests/deploy/test_check_prod_env.py
git commit -m "Validate a production env file against the lane defaults it must not carry"
```

---

### Task 6: Backups, restore rehearsal and the VM watchdog

**Files:**
- Create: `deploy/vm/backup_db.sh`, `deploy/vm/restore_check.sh`, `deploy/vm/watchdog.sh`
- Create: `deploy/vm/systemd/clue-db-backup.service`, `deploy/vm/systemd/clue-db-backup.timer`, `deploy/vm/systemd/clue-watchdog.service`, `deploy/vm/systemd/clue-watchdog.timer`

**Interfaces:**
- Consumes: `/srv/clue/backup.env` on the VM with `PGURL` (direct Railway TCP-proxy URL, `sslmode=require`), `R2_ENDPOINT`, `R2_BUCKET`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `SENTRY_CRON_URL_BACKUP`, `SENTRY_CRON_URL_WATCHDOG`.
- Ruling (2026-10-01, Problem A): `R2_BUCKET` is a **separate bucket** (`clue-backups`) with its **own token** — the app's orphan sweep (`clue_storage.sweep_orphan_blobs`, every fleet worker, 6-hourly) deletes every object in the app bucket without an `artifact` row, so a dump there would be gone within a day. `backup_db.sh` reads the app env (`CLUE_ENV_FILE`, default `/srv/clue/env`) first and refuses, before any dump and without a Sentry check-in, if the bucket or key matches the app's or the app env is unreadable. Tests: `tests/deploy/test_vm_scripts.py::test_backups_refuse_*`.
- Produces: nightly objects `s3://$R2_BUCKET/db-backups/clue-YYYYMMDDTHHMMSSZ.dump` (custom format), 14-day retention.

- [ ] **Step 1: Write `deploy/vm/backup_db.sh`:**

```bash
#!/usr/bin/env bash
# Nightly Postgres dump to R2 (first deployment spec §8). Fails loud on an empty or unreadable dump.
set -Eeuo pipefail
source /srv/clue/backup.env
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"' EXIT
FILE="$WORK/clue-$STAMP.dump"
aws_r2() {
  docker run --rm -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -v "$WORK:/work" \
    amazon/aws-cli:2.17.0 --endpoint-url "$R2_ENDPOINT" --region auto "$@"
}

docker run --rm -v "$WORK:/work" postgres:16 pg_dump --format=custom --no-owner --dbname="$PGURL" --file="/work/$(basename "$FILE")"
[ -s "$FILE" ] || { echo "backup FAILED: empty dump" >&2; exit 1; }
docker run --rm -v "$WORK:/work" postgres:16 pg_restore --list "/work/$(basename "$FILE")" > /dev/null
aws_r2 s3 cp "/work/$(basename "$FILE")" "s3://$R2_BUCKET/db-backups/$(basename "$FILE")"

# Retention: delete dumps older than 14 days.
CUTOFF="$(date -u -d '14 days ago' +%Y%m%d)"
aws_r2 s3 ls "s3://$R2_BUCKET/db-backups/" | awk '{print $4}' | while read -r name; do
  day="$(echo "$name" | sed -E 's/^clue-([0-9]{8})T.*/\1/')"
  [[ "$day" =~ ^[0-9]{8}$ ]] && [ "$day" -lt "$CUTOFF" ] && aws_r2 s3 rm "s3://$R2_BUCKET/db-backups/$name"
done
curl -fsS -m 10 "$SENTRY_CRON_URL_BACKUP" > /dev/null || true
echo "backup OK: $(basename "$FILE") ($(stat -c %s "$FILE") bytes)"
```

- [ ] **Step 2: Write `deploy/vm/restore_check.sh`** (the rehearsal, spec §8 step 3):

```bash
#!/usr/bin/env bash
# Restore the newest R2 dump into a throwaway local Postgres and check it. Usage: restore_check.sh
set -Eeuo pipefail
source /srv/clue/backup.env
WORK="$(mktemp -d)"; trap 'rm -rf "$WORK"; docker rm -f clue-restore-check >/dev/null 2>&1 || true' EXIT
aws_r2() {
  docker run --rm -e AWS_ACCESS_KEY_ID -e AWS_SECRET_ACCESS_KEY -v "$WORK:/work" \
    amazon/aws-cli:2.17.0 --endpoint-url "$R2_ENDPOINT" --region auto "$@"
}
LATEST="$(aws_r2 s3 ls "s3://$R2_BUCKET/db-backups/" | awk '{print $4}' | sort | tail -1)"
[ -n "$LATEST" ] || { echo "no backups found" >&2; exit 1; }
aws_r2 s3 cp "s3://$R2_BUCKET/db-backups/$LATEST" "/work/$LATEST"

docker run -d --name clue-restore-check -e POSTGRES_PASSWORD=check -v "$WORK:/work" pgvector/pgvector:pg16 >/dev/null
until docker exec clue-restore-check pg_isready -U postgres >/dev/null 2>&1; do sleep 1; done
docker exec clue-restore-check psql -U postgres -c "CREATE DATABASE clue"
docker exec clue-restore-check pg_restore --no-owner -U postgres -d clue "/work/$LATEST"
docker exec clue-restore-check psql -U postgres -d clue -At -c "SELECT version_num FROM alembic_version"
for t in workspace account_entity arv2_research_job design_document design_web_publish; do
  echo "$t: $(docker exec clue-restore-check psql -U postgres -d clue -At -c "SELECT count(*) FROM $t")"
done
echo "RESTORE CHECK PASSED for $LATEST"
```

- [ ] **Step 3: Write `deploy/vm/watchdog.sh`:**

```bash
#!/usr/bin/env bash
# Every 5 minutes: memory, disk, worker pools, backup age (spec §11). Checks in to Sentry cron
# monitoring on success; a missed check-in is the alert.
set -Eeuo pipefail
source /srv/clue/backup.env
fail() { echo "WATCHDOG: $*" >&2; exit 1; }

mem_used=$(free | awk '/Mem:/ {printf "%d", ($3/$2)*100}')
[ "$mem_used" -lt 85 ] || fail "memory at ${mem_used}%"
disk_used=$(df --output=pcent / | tail -1 | tr -dc '0-9')
[ "$disk_used" -lt 80 ] || fail "disk at ${disk_used}%"
for svc in chat design batch1 batch2 batch3 ingestion pgbouncer; do
  docker compose --env-file /srv/clue/compose.env -f /srv/clue/app/deploy/vm/compose.yaml ps --status running --services | grep -qx "$svc" || fail "$svc not running"
done
curl -fsS -m 10 "$SENTRY_CRON_URL_WATCHDOG" > /dev/null
```

Backup age is covered by the backup job's own Sentry cron monitor (configured with a 26-hour margin in Task 9), not here.

- [ ] **Step 4: Write the systemd units:**

`deploy/vm/systemd/clue-db-backup.service`:
```ini
[Unit]
Description=Clue nightly Postgres dump to R2
[Service]
Type=oneshot
ExecStart=/srv/clue/app/deploy/vm/backup_db.sh
```

`deploy/vm/systemd/clue-db-backup.timer`:
```ini
[Unit]
Description=Nightly Clue DB backup
[Timer]
OnCalendar=*-*-* 07:00:00 UTC
Persistent=true
[Install]
WantedBy=timers.target
```

`deploy/vm/systemd/clue-watchdog.service`:
```ini
[Unit]
Description=Clue VM watchdog
[Service]
Type=oneshot
ExecStart=/srv/clue/app/deploy/vm/watchdog.sh
```

`deploy/vm/systemd/clue-watchdog.timer`:
```ini
[Unit]
Description=Clue VM watchdog every 5 minutes
[Timer]
OnCalendar=*:0/5
Persistent=true
[Install]
WantedBy=timers.target
```

- [ ] **Step 5: Lint the scripts**

Run: `chmod +x deploy/vm/*.sh && shellcheck deploy/vm/*.sh` (install with `brew install shellcheck` if absent)
Expected: no errors (warnings about `source` of a runtime file — SC1091 — are acceptable; silence with `# shellcheck source=/dev/null` above each `source`).

- [ ] **Step 6: Rehearse the dump/restore locally against the lane DB (no R2)**

```bash
set -a; source .env; set +a
docker run --rm -v /tmp:/work postgres:16 pg_dump --format=custom --no-owner \
  --dbname="postgresql://clue:clue@host.docker.internal:55040/clue_addis-ababa" --file=/work/lane.dump
docker run --rm -v /tmp:/work postgres:16 pg_restore --list /work/lane.dump | head -5
rm -f /tmp/lane.dump
```

Expected: a non-empty table of contents. This proves the dump format and client version against Postgres 16 before the real VM exists.

- [ ] **Step 7: Commit**

```bash
git add deploy/vm/backup_db.sh deploy/vm/restore_check.sh deploy/vm/watchdog.sh deploy/vm/systemd/
git commit -m "Nightly DB dump to R2, restore rehearsal script and VM watchdog"
```

---

### Task 7: VM bootstrap and deploy scripts

**Files:**
- Create: `deploy/vm/bootstrap.sh`, `deploy/vm/deploy.sh`

**Interfaces:**
- Consumes: `deploy/vm/compose.yaml` (Task 3), `deploy/check_prod_env.py` (Task 5), backend image tags `ghcr.io/clue-hq/clue-backend:<sha>` and sandbox image `ghcr.io/clue-hq/clue-agent-sandbox:<sha>` (Task 8).
- Produces: `/srv/clue/compose.env` containing `BACKEND_IMAGE=`, `DOCKER_GID=`, `PGBOUNCER_CLIENT_PASSWORD=`; `deploy.sh <sha>` as the one VM deploy command.

- [ ] **Step 1: Write `deploy/vm/bootstrap.sh`** (run once, as root, on a fresh Ubuntu 24.04 VM):

```bash
#!/usr/bin/env bash
# One-time VM setup (first deployment spec §6, §9.4). Idempotent. Run as root.
set -Eeuo pipefail
apt-get update
apt-get install -y ca-certificates curl git ufw python3
curl -fsSL https://get.docker.com | sh
ufw default deny incoming && ufw allow OpenSSH && ufw --force enable

id clue >/dev/null 2>&1 || useradd --uid 1000 --create-home --shell /bin/bash clue
usermod -aG docker clue
mkdir -p /srv/clue/workspaces /srv/clue/engine-cache
chown -R 1000:1000 /srv/clue/workspaces /srv/clue/engine-cache
chmod 700 /srv/clue/workspaces

[ -d /srv/clue/app/.git ] || git clone --branch main https://github.com/clue-hq/research-and-data.git /srv/clue/app
for f in env pgbouncer.env backup.env; do touch "/srv/clue/$f"; chmod 600 "/srv/clue/$f"; done
DOCKER_GID="$(stat -c %g /var/run/docker.sock)"
touch /srv/clue/compose.env && chmod 600 /srv/clue/compose.env
grep -q '^DOCKER_GID=' /srv/clue/compose.env || echo "DOCKER_GID=$DOCKER_GID" >> /srv/clue/compose.env
grep -q '^PGBOUNCER_CLIENT_PASSWORD=' /srv/clue/compose.env || echo "PGBOUNCER_CLIENT_PASSWORD=" >> /srv/clue/compose.env

cp /srv/clue/app/deploy/vm/systemd/*.service /srv/clue/app/deploy/vm/systemd/*.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now clue-db-backup.timer clue-watchdog.timer
echo "bootstrap done — fill /srv/clue/{env,pgbouncer.env,backup.env} and PGBOUNCER_CLIENT_PASSWORD in compose.env, then run deploy.sh <sha>"
```

(Cloning a private repo needs a read-only deploy key or a fine-grained token — founder action in the runbook, Task 9.)

- [ ] **Step 2: Write `deploy/vm/deploy.sh`:**

```bash
#!/usr/bin/env bash
# Deploy one commit to the VM (spec §9.3). Run AFTER Railway's deploy of the same commit is green:
# Railway's platform-api pre-deploy command owns `alembic upgrade head`; this script only checks
# the database is at head, so two migration runs can never race.
# Usage: deploy.sh <git-sha>   (run as the clue user)
set -Eeuo pipefail
SHA="${1:?usage: deploy.sh <git-sha>}"
APP=/srv/clue/app
BACKEND="ghcr.io/clue-hq/clue-backend:$SHA"
SANDBOX="ghcr.io/clue-hq/clue-agent-sandbox:$SHA"
COMPOSE=(docker compose --env-file /srv/clue/compose.env -f "$APP/deploy/vm/compose.yaml")

set_line() {  # set_line FILE KEY VALUE — replace or append KEY=VALUE
  if grep -q "^$2=" "$1"; then sed -i "s#^$2=.*#$2=$3#" "$1"; else echo "$2=$3" >> "$1"; fi
}

git -C "$APP" fetch origin main && git -C "$APP" checkout --detach "$SHA"
python3 "$APP/deploy/check_prod_env.py" worker /srv/clue/env
docker pull "$BACKEND"
docker pull "$SANDBOX"
set_line /srv/clue/env CLUE_SANDBOX_IMAGE "$SANDBOX"

MIGRATE_URL="$(grep '^CLUE_MIGRATE_DATABASE_URL=' /srv/clue/env | cut -d= -f2-)"
docker run --rm --env-file /srv/clue/env -e CLUE_DATABASE_URL="$MIGRATE_URL" "$BACKEND" \
  shell -c "cd /app && alembic current 2>/dev/null | grep -q '(head)'" \
  || { echo "database is not at head for $SHA — wait for Railway's deploy (it runs the migration)" >&2; exit 1; }

set_line /srv/clue/compose.env BACKEND_IMAGE "$BACKEND"
"${COMPOSE[@]}" up -d --remove-orphans
"${COMPOSE[@]}" ps
echo "deployed $SHA"
```

`CLUE_MIGRATE_DATABASE_URL` is the **direct** Railway proxy URL for the database owner role (not PgBouncer, not `clue_worker`): Alembic takes session-level locks and runs DDL, which must not go through a transaction pooler and which the worker role may not do. `check_prod_env.py` uses only the standard library, so the VM's system `python3` runs it.

- [ ] **Step 3: Lint**

Run: `chmod +x deploy/vm/*.sh && shellcheck deploy/vm/bootstrap.sh deploy/vm/deploy.sh`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add deploy/vm/bootstrap.sh deploy/vm/deploy.sh
git commit -m "VM bootstrap and one-command deploy (env check, migrate, restart pools)"
```

---

### Task 8: GitHub Actions — build, boot-smoke, then publish images on `main`

The images are pushed under their commit SHA first; the `production` tag moves only after **both** smoke tests pass, so a broken build never becomes the tag anything deploys from. No test suite runs here — this is a boot check, minutes long.

**Files:**
- Create: `docker/backend/boot_smoke.sh`
- Create: `.github/workflows/deploy-images.yml`

**Interfaces:**
- Consumes: the image entrypoint commands (Task 4), `/healthz` (Task 4A), `WASM_PREFLIGHT_STRICT` and `HANDSHAKE_HELPER_CMD` (Task 4B), the worker's boot log events `"event": "fleet.boot.handlers_registered"` and `"event": "worker.start"` (emitted by `clue_api.fleet_main` today), `clue_api.sandbox.docker_runner.docker_available(image) -> tuple[bool, str]`.
- Produces: `ghcr.io/clue-hq/clue-backend:<sha>` and `ghcr.io/clue-hq/clue-agent-sandbox:<sha>` on every push; `:production` on both only after the smoke tests pass.

- [ ] **Step 1: Write `docker/backend/boot_smoke.sh`:**

```bash
#!/usr/bin/env bash
# Boot every service from the built image against throwaway Postgres (pgvector) + Redis and check
# it comes up: both APIs answer /healthz, the worker registers its handlers and starts, and the
# sandbox runs a trivial script through the image's Docker CLI. Catches a broken build before it
# reaches a server. Usage: boot_smoke.sh <backend-image> <sandbox-image>
# Expects Postgres on 127.0.0.1:5432 (clue/clue/clue, vector extension created) and Redis on :6379.
set -Eeuo pipefail
IMAGE="${1:?usage: boot_smoke.sh <backend-image> <sandbox-image>}"
SANDBOX="${2:?usage: boot_smoke.sh <backend-image> <sandbox-image>}"
DOCKER_GID="$(stat -c %g /var/run/docker.sock)"
ENVF="$(mktemp)"
cat > "$ENVF" <<ENV
CLUE_DATABASE_URL=postgresql+asyncpg://clue:clue@127.0.0.1:5432/clue
CLUE_REDIS_URL=redis://127.0.0.1:6379/0
CLUE_STORAGE_BACKEND=fs
CLUE_STORAGE_FS_ROOT=/tmp/artifacts
CLUE_AGENT_WORKSPACE_ROOT=/tmp/clue-workspaces
CLUE_DESIGN_RUNTIME_ENABLED=1
CLUE_SANDBOX_ENABLED=true
CLUE_SANDBOX_IMAGE=$SANDBOX
LUMEN_EMBEDDED_FLEET_WORKER=0
ENV
cleanup() { docker rm -f smoke-platform smoke-design smoke-worker >/dev/null 2>&1 || true; rm -f "$ENVF"; }
trap cleanup EXIT
start() { docker run -d --name "$1" --network host --env-file "$ENVF" "${@:2}"; }
wait_http() {  # wait_http URL CONTAINER
  for _ in $(seq 1 90); do curl -fsS "$1" >/dev/null 2>&1 && { echo "ok: $1"; return 0; }; sleep 2; done
  echo "FAILED: $1 never answered"; docker logs --tail 100 "$2"; return 1
}
wait_log() {  # wait_log CONTAINER EVENT
  for _ in $(seq 1 90); do docker logs "$1" 2>&1 | grep -q "\"event\": \"$2\"" && { echo "ok: $1 $2"; return 0; }; sleep 2; done
  echo "FAILED: $1 never logged $2"; docker logs --tail 100 "$1"; return 1
}

docker run --rm --network host --env-file "$ENVF" "$IMAGE" migrate
start smoke-platform -e PORT=18020 "$IMAGE" platform-api
start smoke-design -e PORT=18010 "$IMAGE" design-api
wait_http http://127.0.0.1:18020/healthz smoke-platform
wait_http http://127.0.0.1:18010/healthz smoke-design

start smoke-worker --group-add "$DOCKER_GID" -v /var/run/docker.sock:/var/run/docker.sock "$IMAGE" fleet-worker
wait_log smoke-worker fleet.boot.handlers_registered
wait_log smoke-worker worker.start

docker run --rm --network host --group-add "$DOCKER_GID" -v /var/run/docker.sock:/var/run/docker.sock \
  -e SANDBOX="$SANDBOX" "$IMAGE" shell -c '
    set -e
    python -c "from clue_api.sandbox.docker_runner import docker_available; ok, why = docker_available(\"$SANDBOX\"); assert ok, why; print(\"ok: docker_available\")"
    out=$(docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
          --user 1000:1000 "$SANDBOX" python -c "print(2 + 2)")
    [ "$out" = "4" ] && echo "ok: sandbox ran python"'
echo "BOOT SMOKE PASSED"
```

`chmod +x docker/backend/boot_smoke.sh`.

**If a service refuses to boot because a setting or key is missing**, that is the finding this test exists for. For each one decide, and record in the commit message: either boot genuinely requires it (add it to the smoke env with a dummy value and to the runbook's required list), or boot should not require it (fix the code to start without it and fail only when the feature is used).

- [ ] **Step 2: Write `.github/workflows/deploy-images.yml`:**

```yaml
name: deploy-images
on:
  push:
    branches: [main]
  workflow_dispatch:

permissions:
  contents: read
  packages: write

env:
  BACKEND: ghcr.io/clue-hq/clue-backend
  SANDBOX: ghcr.io/clue-hq/clue-agent-sandbox

jobs:
  images:
    runs-on: ubuntu-latest
    timeout-minutes: 90
    services:
      postgres:
        image: pgvector/pgvector:pg16
        env: { POSTGRES_USER: clue, POSTGRES_PASSWORD: clue, POSTGRES_DB: clue }
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U clue" --health-interval 5s --health-retries 20
      redis:
        image: redis:7
        ports: ["6379:6379"]
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}
      - name: Sandbox image
        uses: docker/build-push-action@v6
        with:
          context: docker/agent-sandbox
          platforms: linux/amd64
          push: true
          tags: ${{ env.SANDBOX }}:${{ github.sha }}
      - name: Backend image
        uses: docker/build-push-action@v6
        with:
          context: .
          file: docker/backend/Dockerfile
          platforms: linux/amd64
          push: true
          tags: ${{ env.BACKEND }}:${{ github.sha }}
          cache-from: type=gha,scope=backend
          cache-to: type=gha,mode=max,scope=backend
      - name: Pull the images just built
        run: |
          docker pull "$BACKEND:${{ github.sha }}"
          docker pull "$SANDBOX:${{ github.sha }}"
      - uses: actions/setup-node@v4
        with:
          node-version: "24"
      - name: Engine handshake — committed browser wasm vs the helper inside the built image
        env:
          HANDSHAKE_HELPER_CMD: >-
            docker run --rm -i --entrypoint /app/subsystems/clue-design/target/release/lumen-api-helper
            ${{ env.BACKEND }}:${{ github.sha }}
        run: |
          WASM_PREFLIGHT_STRICT=1 node subsystems/clue-design/scripts/preflight_editor_wasm.mjs
          node subsystems/clue-design/scripts/verify_handshake.mjs
      - name: Static smoke (contents)
        run: docker/backend/smoke.sh "$BACKEND:${{ github.sha }}"
      - name: Boot smoke (services start)
        run: |
          PGPASSWORD=clue psql -h 127.0.0.1 -U clue -d clue -c "CREATE EXTENSION IF NOT EXISTS vector"
          docker/backend/boot_smoke.sh "$BACKEND:${{ github.sha }}" "$SANDBOX:${{ github.sha }}"
      - name: Move the production tags (only after both smoke tests passed)
        run: |
          docker buildx imagetools create -t "$BACKEND:production" "$BACKEND:${{ github.sha }}"
          docker buildx imagetools create -t "$SANDBOX:production" "$SANDBOX:${{ github.sha }}"
```

- [ ] **Step 3: Lint**

Run: `shellcheck docker/backend/boot_smoke.sh && actionlint .github/workflows/deploy-images.yml`
Expected: no errors.

- [ ] **Step 4: Run the boot smoke locally once (Linux semantics differ on a Mac)**

On the Mac, `--network host` does not expose the host's ports the same way, so run the local check inside a Linux VM or skip it and rely on the first `workflow_dispatch` run: push the branch to a throwaway branch name **only with the founder's go-ahead**, trigger `deploy-images` by hand (`gh workflow run deploy-images --ref <branch>`), and read the job log. Expected: `SMOKE PASSED`, `BOOT SMOKE PASSED`, and the production tags moved. (The `production` tag moves on a `workflow_dispatch` run too — on a throwaway branch, comment out the last step for that run or accept that `:production` then points at that commit until the real first ship.)

- [ ] **Step 5: Confirm the sandbox build context**

Run: `ls docker/agent-sandbox/ && grep -n "sandbox-image" -A3 Makefile`
Expected: a `Dockerfile` in `docker/agent-sandbox/`; if the Makefile passes build args, add them under the sandbox step's `build-args`.

- [ ] **Step 6: Commit**

```bash
git add docker/backend/boot_smoke.sh .github/workflows/deploy-images.yml
git commit -m "CI: build images, boot-smoke every service, then move the production tags"
```

---

### Task 9: The deployment runbook

**Files:**
- Create: `docs/deploy/runbook.md`

This is the founder-facing checklist for every step that happens in a dashboard or on a server. Each section lists exact settings; every **[FOUNDER]** step needs the founder's own account and explicit go-ahead.

- [ ] **Step 1: Write `docs/deploy/runbook.md` with these sections, in this order, with the exact content below:**

````markdown
# First deployment runbook

Spec: `docs/superpowers/specs/2026-10-01-first-deployment-design.md`. Order matters.

## 1. Cloudflare [FOUNDER]
1. R2 → create bucket `clue-prod` (location hint: Eastern North America). *(Superseded 2026-10-01: also `clue-backups` with its own token — see Task 6's ruling and `docs/deploy/runbook.md` §1.)*
2. R2 → Manage API tokens → create a token with Object Read & Write on `clue-prod`. Record the
   access key id, secret, and the S3 endpoint `https://<account-id>.r2.cloudflarestorage.com`.
3. Pages delivery: follow `docs/specs/pages-hosting-runbook.md` (Worker, edge secret, Cloudflare
   for SaaS on `pages.cluehq.ai`). Record `CLUE_PAGES_EDGE_SECRET`.

## 2. Railway [FOUNDER]
1. Project region: US East.
2. Add **Postgres** from the pgvector template (Postgres 16). In its shell:
   `CREATE EXTENSION IF NOT EXISTS vector;`
   `ALTER SYSTEM SET max_connections = 200;` then restart the service.
   Create the worker role:
   `CREATE ROLE clue_worker LOGIN PASSWORD '<long random>';`
   `GRANT CONNECT ON DATABASE railway TO clue_worker; GRANT USAGE ON SCHEMA public TO clue_worker;`
   `GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO clue_worker;`
   `GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO clue_worker;`
   `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO clue_worker;`
   `ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO clue_worker;`
   Enable **TCP proxy** on Postgres; record host and port. Enable scheduled **volume backups**.
3. Add **Redis** (Redis 7). Enable TCP proxy; record host, port, password.
4. Add services from this repo, branch `main`, built by Railway from
   `RAILWAY_DOCKERFILE_PATH=/docker/backend/Dockerfile` (the same Dockerfile CI builds for the VM,
   so both run identical code for a given commit):
   - `platform-api`: start command `clue platform-api`, **pre-deploy command `clue migrate`**
     (Railway runs it once, before the new deployment goes live — the only place migrations run),
     memory 1 GB, domain `api.cluehq.ai`.
   - `design-api`: start command `clue design-api`, memory 1.5 GB, domain `design-api.cluehq.ai`,
     `LUMEN_EMBEDDED_FLEET_WORKER=0`.
   - `page-origin`: `platform/page_origin/Dockerfile.railway`, memory 256 MB.
5. Frontend service: change its branch from `integration/frontend-design-part-iv-v4` to
   `main`; set `CLUE_API_BASE_URL=https://api.cluehq.ai`,
   `LUMEN_API_BASE_URL=https://design-api.cluehq.ai`, `CLUE_APP_ORIGIN=https://app.cluehq.ai`,
   `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES=https://app.cluehq.ai`.
6. Variables for `platform-api` and `design-api`: every key in `.env.example` with its production
   value (spec §10). `CLUE_DATABASE_URL` and `CLUE_REDIS_URL` use Railway's private hostnames.
   Before saving, paste each service's variables into a local file and run
   `uv run python deploy/check_prod_env.py platform-api <file>` (and `design-api`) — it must print OK.

## 3. OVHcloud VPS-4 [FOUNDER]
1. Order VPS-4 (8 vCores / 24 GB / 200 GB NVMe), US East, Ubuntu 24.04, your SSH key.
2. GitHub → repo → Settings → Deploy keys: add the VM's read-only key (for `git clone`).
3. GHCR: create a read-only token for `docker login ghcr.io` on the VM (packages:read).

## 4. VM setup
1. `scp deploy/vm/bootstrap.sh root@<vm>:` then `ssh root@<vm> bash bootstrap.sh`.
2. As `clue`: `docker login ghcr.io` with the read-only token.
3. Fill `/srv/clue/env`: every `.env.example` key with production values, plus
   `CLUE_MIGRATE_DATABASE_URL` (direct Railway proxy URL for the owner role, with `?ssl=require`), `CLUE_REDIS_URL` (Railway proxy, `rediss://` if TLS), `CLUE_SANDBOX_ENABLED=true`.
   **Do not** set `CLUE_FLEET_WORKER_KINDS` here (compose sets it per pool).
4. Fill `/srv/clue/pgbouncer.env`: `DATABASE_URL=postgres://clue_worker:<password>@<proxy-host>:<port>/railway`,
   `POOL_MODE` and `DEFAULT_POOL_SIZE` (as decided in plan Task 3 Step 3), `AUTH_TYPE=scram-sha-256`,
   `SERVER_TLS_SSLMODE=require`, `MAX_CLIENT_CONN=200`, `LISTEN_PORT=6432`. Put the same
   `clue_worker` password in `/srv/clue/compose.env` as `PGBOUNCER_CLIENT_PASSWORD`.
5. Fill `/srv/clue/backup.env`: `PGURL`, `R2_ENDPOINT`, `R2_BUCKET=clue-prod`,
   `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `SENTRY_CRON_URL_BACKUP`,
   `SENTRY_CRON_URL_WATCHDOG`.
6. Sentry → Crons: monitor `clue-db-backup` (daily, 26-hour margin) and `clue-watchdog`
   (every 5 minutes, 10-minute margin), alerting the founder.

## 5. Vendors [FOUNDER]
Set monthly spend caps and alerts on OpenRouter, Exa, AI Ark and Adyntel.

## 6. First ship
1. Open a pull request from `research-streaming` into `main` and merge it [FOUNDER]. (The first one
   merges cleanly — checked 2026-10-01.)
2. Wait for the `deploy-images` workflow to go green (smoke test included).
3. Railway rebuilds and redeploys from `main`; `platform-api`'s pre-deploy `clue migrate`
   runs `alembic upgrade head` once.
4. **Only after Railway's deploy is green**, on the VM: `/srv/clue/app/deploy/vm/deploy.sh <sha>`
   (it refuses if the database is not at head).
5. Uptime checks (Better Stack or UptimeRobot free tier) on `https://app.cluehq.ai`,
   `https://api.cluehq.ai/healthz`, `https://design-api.cluehq.ai/healthz` and a published page.

## 7. Every later ship
Merge a pull request from `research-streaming` into `main` once staging is tested; wait for the `deploy-images` workflow and Railway to go green; then `deploy.sh <sha>` on the VM.

## 7a. Known gap — accepted for now, to be closed later
Railway rebuilds the frontend and the design API separately, so for a minute or two during a deploy
they can run different engine versions; an editor opened in that window shows the "Canvas editing
is disabled" banner until reloaded. (Founder, 2026-10-01: acceptable only for now.)

## 8. Rollback
Railway: redeploy the previous deployment. VM: `deploy.sh <previous-sha>`. If a migration must be
undone: `docker run --rm --env-file /srv/clue/env <image> shell -c "cd /app && alembic downgrade -1"`
against `CLUE_MIGRATE_DATABASE_URL` — migrations are reversible by repo rule.

## 9. Restore rehearsal
On the VM: `/srv/clue/app/deploy/vm/restore_check.sh` — must end with `RESTORE CHECK PASSED`.

## 10. Moving to AWS later (spec §13)
Build RDS (Postgres 16 + pgvector) and an EC2 VM with the same compose file; stop the Railway
services and the VM pools; `pg_dump` from Railway, `pg_restore` into RDS; compare row counts on the
tables in `restore_check.sh`; repoint `CLUE_DATABASE_URL` everywhere; start. Keep Railway Postgres
read-only for two weeks. R2 does not move.
````

- [ ] **Step 2: Verify every file and command the runbook names exists**

Run: `for f in deploy/vm/bootstrap.sh deploy/vm/deploy.sh deploy/vm/restore_check.sh deploy/check_prod_env.py docker/backend/Dockerfile platform/page_origin/Dockerfile.railway docs/specs/pages-hosting-runbook.md; do test -e "$f" && echo "ok $f" || echo "MISSING $f"; done`
Expected: every line `ok`.

- [ ] **Step 3: Check the health endpoints named in the runbook exist**

Run: `grep -rn '"/healthz"\|/healthz' platform/api/clue_api/projections_app.py subsystems/clue-design/apps/api/lumen_api/main.py | head`
Expected: a route on each API. If an API has no health route, replace its uptime URL in the runbook with a route that exists and returns 200 unauthenticated (for example `/docs` or `/openapi.json`), and note it.

- [ ] **Step 4: Commit**

```bash
git add docs/deploy/runbook.md
git commit -m "First deployment runbook: Cloudflare, Railway, OVHcloud VM, first ship, rollback"
```

---

### Task 10: Ship, accept, record

This task is executed **with the founder**, following `docs/deploy/runbook.md`. Every [FOUNDER] step and every push needs their go-ahead in chat.

- [ ] **Step 1:** Founder completes runbook §1–§5. Record each resource name (not secrets) in `_memory/2026-10-01-first-deployment.md`.
- [ ] **Step 2:** Run the focused test files: `uv run pytest tests/api/test_fleet_wiring.py tests/test_storage_settings_documented.py tests/deploy -v` — all PASS.
- [ ] **Step 3:** The founder opens and merges the `research-streaming` → `main` pull request (runbook §6.1). Watch `deploy-images` go green.
- [ ] **Step 4:** Run `deploy.sh <sha>` on the VM; `docker compose ps` shows all seven services running.
- [ ] **Step 5: Acceptance walk (spec §16)**, with memory/CPU sampled on the VM every 15 s (`docker stats --no-stream` in a loop, written to a file):
  1. Sign up; the workspace and its `<label>.pages.cluehq.ai` address exist.
  2. Onboard a real company end to end.
  3. Discover 3 accounts; research one with its committee.
  4. Chat with the Head of ABM while research runs — replies are not delayed by research.
  5. Build and publish a landing page; load it on the pages hostname; republish under a new slug; the old slug returns 404.
  6. Connect a custom domain (custom-domain spec §10 live walk).
  7. Run `restore_check.sh` → `RESTORE CHECK PASSED`.
  8. Roll back one deploy to the previous sha and forward again.
- [ ] **Step 6:** Write `_memory/2026-10-01-first-deployment.md`: what was stood up, resource names, measured VM memory/CPU peaks during the walk, costs of the walk, anything that failed and how it was fixed, what is still owed. Commit it.

---

## Self-review

- **Spec coverage:** §3/§5 hosting and sizing → Tasks 3, 9; §5.1 embedded worker off → Tasks 5, 9; §5.2 pools → Tasks 1, 3; §6 stateless VM → Tasks 3, 7; §7 connections/PgBouncer/least-privilege role → Tasks 3, 9; §8 backups/rehearsal → Task 6; §9.1 one image → Task 4; §9.2 production branch → Tasks 8, 9, 10; §9.3 deploy order → Tasks 7, 9; §9.4 sandbox socket/paths/non-root → Tasks 3, 4, 7; §10 config → Tasks 2, 5, 9; §11 domains/monitoring → Tasks 6, 9; §12 spend caps → Task 9 §5; §13 AWS path → Task 9 §10; §15 app changes → Tasks 1, 2, 4 (the localhost/local-disk audit is covered by `check_prod_env.py` for URLs and by the image's baked `LUMEN_*` paths; anything else surfaces in the Task 4 smoke test and the Task 10 walk); §16 acceptance → Task 10; boot-before-deploy (founder ask 2026-10-01) → Tasks 4A, 8; §9.5 engine handshake gate → Tasks 4B, 8; `main` as deployment branch, `research-streaming` as staging (founder ruling 2026-10-01) → Tasks 7, 8, 9, 10.
- **Known risk carried into execution:** PgBouncer transaction pooling vs session advisory locks — Task 3 Step 3 decides `transaction` vs `session` from a grep before anything ships.
````

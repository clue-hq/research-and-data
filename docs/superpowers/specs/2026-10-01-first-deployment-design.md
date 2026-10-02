# First deployment — design

**Status:** draft for founder review (2026-10-01)
**Branch:** `deploy/first-deployment` (off `research-streaming` at `e2e629684`)
**Decisions taken in conversation, 2026-09-29 → 2026-10-01** — this document records them; nothing
here is built yet.

## 1. Goal

Put the complete Clue app on hosted infrastructure for the first time, so that the team and the
first pilot customers use it with real data and real spend, and no laptop has to be running.

Success means: a pilot can sign up, onboard their company, discover and research target accounts,
chat with the Head of ABM, build a landing page, publish it on their Clue pages address, and connect
their own domain — on the hosted stack, with backups in place and a written way back if a deploy
goes wrong.

**Audience:** internal team plus the first pilots (founder ruling). Reliable and secure, not built
for scale: one region, modest capacity, deliberate manual shipping.

**Budget:** pre-funding. Infrastructure should stay around **$60–70/month**; model and data spend is
separate and larger (§12).

## 2. Out of scope (deliberately deferred)

- **Per-workspace fairness, quotas and rate limits** (fair claim ordering, per-workspace slot caps,
  per-tenant vendor rate limits and budgets). Founder ruling 2026-10-01: after the credit system.
  The one exception kept here is the separate chat pool (§5.2), which is configuration, not a
  scheduler change.
- Autoscaling, Kubernetes, Temporal, multi-region, a staging environment.
- A hosted code-sandbox service (E2B/Modal/Daytona). The sandbox stays Docker on the worker VM.

## 3. Decisions and why

| Decision | Choice | Why |
|---|---|---|
| Region | US East for everything | Pilots and most vendors (OpenRouter, Exa, Clerk, AI Ark) are US-based; every tier must sit together because the workers and APIs talk to Postgres constantly |
| Web tier | Railway (frontend already there) | Already in use; no Docker daemon needed by these services |
| Workers | One VM with Docker | `run_python` shells out to `docker run` on the worker's own host (`platform/api/clue_api/sandbox/docker_runner.py`); Railway gives no Docker daemon |
| Worker VM provider | **OVHcloud VPS-4** — 8 vCores / 24 GB / 200 GB NVMe, month-to-month (no commitment), **Virginia (US-EAST-VA)**, ordered 2026-10-02 through the US Control Panel | Cheapest dependable option found on 2026-10-01 (Hetzner US is now $165.99 for 8/32 after its June 2026 price rise; Contabo is cheaper per GB but known for oversold CPU). Holds no customer data, so its reliability risk is bounded (§6) |
| Postgres | **Railway Postgres 16 + pgvector** | One platform, cheapest; the VM stays stateless. Accepted trade-off: no point-in-time recovery — worst case a day of data (§8) |
| Redis | **Railway Redis 7** | The platform API uses Redis too (`clue_api/locks.py`), so it must be reachable from Railway; it holds only short-lived locks and counters |
| Files | **Cloudflare R2** via the existing S3 backend (`libs/clue-storage/clue_storage/s3.py`) | Provider-independent; stays put through any future provider move; no egress fees |
| Shipping | **`main` is the deployment branch**; `research-streaming` is staging | Releasing = merging a pull request from `research-streaming` into `main` (founder ruling 2026-10-01); `research-streaming` stays the internal testing branch |
| Later move to AWS | Planned, not now | When startup credits arrive: dump/restore Postgres into RDS, rebuild the VM on EC2 from the same compose file (§13) |

Rejected, with reasons recorded in the conversation: AWS for everything now (~$255+/month);
Postgres on the VM (puts customer data on the least reliable machine); Neon (point-in-time recovery,
but a third provider — revisit if a day of data loss becomes unacceptable); Convex (not Postgres —
the app has 290 Alembic migrations, 383 tables, 272 triggers, 401 files of hand-written SQL, advisory
locks and a `SKIP LOCKED` queue; adopting it would mean rewriting the data layer).

## 4. Architecture

```
                  Cloudflare
   pages Worker + Cloudflare for SaaS ──► page origin (Railway)
   R2 bucket  ◄──────────── all services read/write files (S3 API)

   Railway, US East (private network)
   ┌──────────┐ ┌──────────────┐ ┌────────────┐ ┌─────────────┐
   │ frontend │ │ platform API │ │ design API │ │ page origin │
   └──────────┘ └──────┬───────┘ └─────┬──────┘ └──────┬──────┘
                       └──────┬────────┴───────────────┘
                     ┌────────┴────────┐  ┌─────────┐
                     │ Postgres 16 +   │  │ Redis 7 │
                     │ pgvector        │  │         │
                     └────────┬────────┘  └────┬────┘
                   Railway TCP proxy (TLS)     │ TCP proxy
                              │                │
   OVHcloud VPS-4, US East (Virginia) — stateless (docker compose)
   ┌──────────────────────────┴────────────────┴───────────────┐
   │ PgBouncer │ chat pool │ design pool │ batch pool ×3 │      │
   │ ingestion pool │ code sandbox containers (docker run)     │
   └────────────────────────────────────────────────────────────┘
```

## 5. Components and sizing

Sizes come from measurements on the lane stack on 2026-09-30 (Appendix A), not guesses.

### 5.1 Railway services

| Service | Start command (from `scripts/dev_stack.sh`) | Memory limit | Replicas |
|---|---|---|---|
| Frontend | existing `apps/frontend/Dockerfile.railway` | 512 MB | 1 |
| Platform API | `uvicorn clue_api.projections_main:app` | 1 GB | 1 |
| Design API | `uvicorn lumen_api.main:app` (from `subsystems/clue-design`, `PYTHONPATH=.:apps/api:apps/agent_runtime`) | 1.5 GB | 1 |
| Page origin | existing `platform/page_origin/Dockerfile.railway` | 256 MB | 1 |
| Postgres 16 + pgvector | Railway pgvector image | 2 GB | 1 |
| Redis 7 | Railway Redis | 256 MB | 1 |

The **design API's embedded fleet worker must be off on Railway** (`LUMEN_EMBEDDED_FLEET_WORKER=0`).
It takes design jobs by default; left on, website design runs and their Chromium would run on
Railway instead of the VM's design pool. The design API still needs Chromium in its image: it
renders previews itself (measured: a 378 MB Chromium + 144 MB Node driver during a preview).

### 5.2 Worker VM — three pools, 48 slots

| Pool | Processes × slots | Task kinds | Why |
|---|---|---|---|
| Chat | 1 × 10 | `agent_turn` | Chat never waits behind a 10-minute research job |
| Design | 1 × 8 | `design_job` | Caps simultaneous website builds at 8 (~1 GB each at peak) |
| Batch | 3 × 10 | all others: `arv2_account_research`, `arv2_discovery`, `onboarding_run`, `arv2_display_page`, … | I/O-bound; ~25–90 MB and ~0.05 core per slot |

Plus, on the same VM: the ingestion pool (`python -m lumen_api.ingestion_pool`), the code sandbox
containers, and PgBouncer.

**Memory budget at a busy moment (24 GB VM):** worker processes ~2 GB · research slots ~3 GB · 8
design runs ~8 GB · sandbox runs ~4 GB · ingestion ~3 GB · PgBouncer/OS/Docker ~1.5 GB → **~21.5 GB**.

## 6. Why the VM is stateless

Nothing on the VM is customer data: Postgres and Redis are on Railway, every file is in R2, agent
workspaces are per-turn scratch (6.6 MB on the lane), and the design engine cache (111 MB) rebuilds.
If the VM dies or the provider disappoints, a new VM is provisioned from the compose file, the env
file is restored, and work resumes — leases and retries already survive a worker disappearing.

## 7. Data and connections

- **Railway services** reach Postgres and Redis over Railway's private network.
- **The VM** reaches them through Railway's **TCP proxy**: TLS required, long random passwords, a
  least-privilege database role for the workers. PgBouncer (transaction pooling) on the VM gives the
  ~50 worker slots and the ingestion workers a small, fixed set of real connections. The one
  process that holds a session-level lock — the ingestion pool's controller, a single connection —
  bypasses it and connects directly (`LUMEN_INGESTION_CONTROLLER_DATABASE_URL`; founder ruling
  2026-10-01: never session mode for the whole VM).
- The public proxy endpoint is the accepted exposure. If it needs closing later, a private tunnel
  (Tailscale or WireGuard) replaces it without app changes.
- `max_connections` on Postgres is set to cover the platform API, design API, page origin and
  PgBouncer's pool with headroom (the lane idles at 27 and hit the default 100 once under test load).

## 8. Backups and restore

1. Railway's scheduled volume backups on the Postgres service.
2. A **nightly `pg_dump`** from the VM, uploaded to a **separate R2 bucket** (`clue-backups`) with
   **its own token**, 14-day retention. Not a prefix of the app's bucket: the app's orphan sweep
   deletes every object there without an `artifact` row, and a shared token would let the app
   delete its own backups. `backup_db.sh` refuses to run if bucket or key match the app's.
3. **A restore rehearsal before the first pilot:** restore last night's dump into a scratch database,
   run `alembic current`, check row counts on the main tables, sign in against it.
4. Accepted risk: up to ~24 hours of data. Revisit (Neon or RDS point-in-time recovery, or WAL
   archiving) once pilots depend on it daily.

## 9. Building and shipping

### 9.1 Images

- **One backend image** built from the repo root for every Python service — platform API, design
  API, fleet worker pools, ingestion pool — started with different commands. It contains the uv
  environment, the design subsystem, the Rust `lumen-api-helper`, Node, Playwright Chromium and the
  font manifest. One image means one build, one version, and no drift between the API and workers.
- **Frontend and page origin** keep their existing Railway Dockerfiles.
- **Sandbox image** (`docker/agent-sandbox/`) is built on the VM (`make sandbox-image`), as today.
- GitHub Actions builds the backend image on every push to `main`, boots it (§9.5), and pushes it to
  GHCR tagged with the commit SHA; the `production` image tag moves only after the boot checks pass.

### 9.2 Branches: `research-streaming` is staging, `main` is production

- Railway services and the VM deploy from `main`.
- `research-streaming` is the staging branch: feature branches merge into it and it is tested
  internally there.
- Releasing = a pull request from `research-streaming` into `main`, merged by the founder. Never
  commit to `main` directly. (Branch protection is not available on this GitHub plan for a private
  repository, so this is team discipline, backed by the CI checks on every push to `main`.)
- The first `research-streaming` → `main` merge is clean (checked 2026-10-01: `main`'s one extra
  commit, the merge of PR #44, has both parents already in `research-streaming`).
- The frontend's Railway service is repointed from `integration/frontend-design-part-iv-v4` to
  `main` (founder action in the Railway dashboard).

### 9.3 Deploy order

1. The image for the new commit is built and pushed.
2. **`alembic upgrade head`** runs once, as a release step, against the Railway Postgres.
3. Railway services redeploy; the VM pulls the new tag and restarts its compose services (draining:
   running tasks finish or are reclaimed by lease expiry).
4. Smoke check: each public hostname answers; a chat turn completes.

### 9.4 Worker containers and the sandbox

The worker containers start sandbox containers through the **host's Docker daemon** (the Docker
socket is mounted into them). Two consequences the compose file must honour:
- The agent workspace root is bind-mounted at the **same absolute path** inside and outside the
  worker container, because `docker run` mount paths are resolved by the host daemon.
- A container holding the Docker socket effectively has root on the host. Acceptable on a
  single-purpose VM with no customer data; recorded as a risk (§14).

### 9.5 Checks before an image can be deployed

Founder ask 2026-10-01: catch a broken build before it reaches a server, not after.
- **Boot smoke** (CI, every push to `main`): against throwaway Postgres (pgvector) + Redis, run the
  migrations; start the platform API and the design API and require `/healthz` to answer (both APIs
  gain `/healthz` — neither had one); start a worker and require its
  `fleet.boot.handlers_registered` and `worker.start` log lines; through the image's own Docker CLI,
  run `docker_available` and have the sandbox image print `2 + 2` under the runner's lockdown flags.
  No test suite runs here — minutes, not hours.
- **Engine handshake gate.** The browser wasm is a committed file
  (`subsystems/clue-design/apps/editor/public/wasm/`) while the server's Rust helper is compiled from
  source, and the two must carry the same `schema_version` and `engine_commit` (a content hash of the
  `lumen-core` sources) or the editor locks canvas editing. Today the frontend build's preflight only
  warns on a stale wasm (`preflight_editor_wasm.mjs` exits 0). The gate: a strict preflight mode that
  fails on a mismatch, used by the frontend's Railway build and by CI on every PR/push to
  `research-streaming`; and, in the deploy workflow, the committed wasm checked against the helper
  inside the built image.
- Only when every check passes does the `production` image tag move.
- **Accepted for now (founder, 2026-10-01), to be closed later:** Railway rebuilds the frontend and the
  design API separately, so for a minute or two during a deploy they can run different engines; an
  editor opened in that window shows the mismatch banner until reloaded.

## 10. Configuration and secrets

- **`.env.example` is the checklist.** Every key gets a deliberate production value.
- Railway variables hold the web tier's settings; the VM holds one env file (mode 0600) for its
  compose services. Secrets never go in images or the repo.
- Production values that differ from the lane:
  - `CLUE_STORAGE_BACKEND=s3` plus the R2 bucket, endpoint, region and credentials
  - `LUMEN_EMBEDDED_FLEET_WORKER=0` on the design API
  - `CLUE_PAGES_SYSTEM_SUFFIX=pages.cluehq.ai`, `CLUE_PAGES_PUBLIC_SCHEME=https`,
    `CLUE_PAGES_TRUST_HOST_HEADER=false`, `CLUE_PAGES_EDGE_SECRET` set (S0 runbook)
  - `CLUE_SCRAPE_BACKEND=scrapling`, `CLUE_STAGE0_PAGE_FETCHER=scrapling`
  - dev-only switches off, e.g. `CLUE_CHAT_REASONING_TRACE_MODE` not `raw`
  - Sentry and Langfuse environment = `production`
  - `CLUE_ARV2_DISCOVERY_MAX_TOPUPS=3` (as on the lane)
  - **Paths the image sets are left out** of every production env: `LUMEN_CORE_HELPER`,
    `LUMEN_FONT_LIBRARY_MANIFEST_PATH`, `CLUE_ARV2_RAW_ROOT` (`/var/lib/clue/arv2-raw`, owned by
    uid 1000; podcast audio there is deleted once transcribed). Their `.env.example` values are
    lane values — a blank helper means `cargo run`, the font path is a checkout placeholder, the
    raw root is relative under the root-owned `/app` — and any env line, even empty, overrides
    the image. `check_prod_env.py` refuses all three.
- Model settings stay env-only, per the repo's agent model configuration block.

## 11. Domains and monitoring

- `app.cluehq.ai` → frontend; `api.cluehq.ai` → platform API. **The design API has no public
  domain** (2026-10-02): it trusts an `X-Workspace-Id` header with no login, so the frontend's
  server and `platform-api` reach it over Railway's private network
  (`design-api.railway.internal:8010`), and the VM's preview renders fetch images through the
  frontend's narrow public proxy (`/api/clue/design-public/asset-store/<digest>`). Auth is a
  **production** Clerk instance (Frontend API `clerk.cluehq.ai`). Pages: the S0 runbook's Cloudflare Worker + edge secret + Cloudflare for SaaS,
  with `<label>.pages.cluehq.ai` served by the page origin.
- Sentry and Langfuse on every service under `production`.
- Uptime checks on each public hostname; alerts on VM memory above 85%, disk above 80%, and any worker
  pool with zero live processes.

## 12. Cost

| Item | $/month |
|---|---|
| OVHcloud VPS-4 (Virginia, no commitment) | ~23–28 |
| Railway: 4 web services + Postgres + Redis (usage-billed, Pro plan) | ~30–40 |
| Cloudflare: Workers paid plan, R2 (~$1.50 per 100 GB), custom hostnames (first 100 included) | ~5 |
| **Infrastructure** | **~$60–70** |

Measured usage costs, on top (2026-09-29/30): onboarding a workspace ~$7.40; discovery of 3 accounts
~$0.40; account research ~$4.00; each buying-committee person ~$2.60–3.80; one website design ~$2.00;
a Head-of-ABM turn ~$0.30–0.60. **Spend caps on OpenRouter, Exa and AI Ark are part of this
deployment**, set in each vendor's dashboard.

## 13. Portability and the move to AWS

Rules that keep every provider replaceable:
1. Everything runs from container images and one compose file — no hand-configured servers.
2. Standard Postgres 16 + pgvector only; no provider-specific database features.
3. All customer files in R2.
4. Redis holds nothing that can't be lost.
5. Backups go to R2, whoever hosts the database.
6. A restore rehearsal before pilots, and before any provider move.

Move to AWS (when credits arrive): build RDS (Postgres 16 + pgvector) and an EC2 VM from the same
compose file; stop the writers; `pg_dump` → `pg_restore`; verify row counts; repoint; start. At pilot
size this is about a day of work and a 15–60 minute maintenance window. Keep the old database
read-only for two weeks.

## 14. Risks

| Risk | Mitigation |
|---|---|
| 24 GB is tight if design runs and sandbox runs peak together | Design pool capped at 8; VM memory alert at 85%; resize is minutes |
| OVHcloud VPS cores are shared | Measure CPU during the acceptance walk and the first pilot week with the same samplers used on 2026-09-30 |
| Public TCP proxy endpoint for Postgres/Redis | TLS, strong credentials, least-privilege role; tunnel later if needed |
| Up to a day of data loss | Nightly dumps + Railway backups + rehearsed restore; revisit when pilots rely on it daily |
| Docker socket in worker containers | Single-purpose VM, no customer data on it |
| Sizing rests on one run of each kind on a Mac, and a 5-person research target | Re-measure on the hosted VM during acceptance |
| One tenant can fill the batch pool (no fairness yet) | Deferred by ruling; the chat pool keeps chat responsive meanwhile |

## 15. App changes this deployment needs

1. **Worker task-kind selection.** A setting (proposed `CLUE_FLEET_WORKER_KINDS`, comma-separated,
   blank = all kinds, today's behaviour) that limits which handlers a fleet process registers. No
   such setting exists today (checked 2026-10-01). Needed for the three pools.
2. **S3 settings in `.env.example`.** `storage_s3_bucket`, `_endpoint_url`, `_region` and the
   credentials exist in `libs/clue-config/clue_config/settings.py` but are missing from
   `.env.example` — a violation of the repo's env parity rule.
3. **The backend Dockerfile, the VM compose file, the GitHub Actions workflow.**
4. **An audit for local-disk and `localhost` assumptions** (absolute paths such as the helper
   binary and font manifest, `127.0.0.1` defaults, anything writing under the checkout). Found items
   are fixed as settings, not special cases.

## 16. Acceptance

On the hosted stack, with the VM sampled for memory and CPU throughout:
1. Sign up; a workspace and its `<label>.pages.cluehq.ai` address are created.
2. Onboard a real company end to end (brand kit, knowledge documents).
3. Discover 3 accounts; research one with its buying committee.
4. Chat with the Head of ABM while research runs — replies arrive without waiting on research.
5. Build a landing page; publish it; load it on the pages hostname; republish under a new slug and
   confirm the old one returns 404.
6. Connect a custom domain through Cloudflare for SaaS (the S2 live walk, spec §10 of the
   custom-domain design).
7. Run the restore rehearsal (§8).
8. Roll back one deploy to the previous image tag and forward again.

## Appendix A — measurements behind the sizing (lane stack, 2026-09-30)

| Measure | Value |
|---|---|
| Fleet worker process, idle footprint | 363–390 MB |
| Research slot, added memory | ~25–90 MB (3 concurrent person slots peaked a worker at 473 MB) |
| Research slot, CPU | ~0.05 core average, spikes to ~0.8 core |
| Account research job | 12m48s, 56 model / 146 tool calls, $4.00 |
| Person research jobs (3 concurrent) | 9–11 min each, $2.64–3.76 |
| Website design run | 6m44s; Python peak 687 MB resident; Chromium 524 MB across 7 processes, alive ~72 s; Playwright Node 184 MB; Python peak 1 core, Chromium 0.8 core |
| Design API preview render | Chromium 378 MB + Node 144 MB |
| Platform API idle | ~342 MB; page origin ~92 MB |
| Lane database after one onboarding + research + design | 380 MB |
| Lane files for that workspace | 183 MB |
| Sandbox image | 612 MB |

# First deployment runbook

Spec: `docs/superpowers/specs/2026-10-01-first-deployment-design.md` · Plan:
`docs/superpowers/plans/2026-10-01-first-deployment.md`. Work through the sections **in order**.
Every **[FOUNDER]** step needs the founder's own account. Secrets never go in the repo, a chat, or
`_memory/` — only into Railway variables and the VM's `/srv/clue/*.env` files (mode 0600).

Branches: `research-streaming` is staging (internal testing); **`main` is what production runs**.
Releasing = merging a pull request from `research-streaming` into `main`.

## 1. Cloudflare [FOUNDER]
1. R2 → create two buckets (location hint: Eastern North America): `clue-prod` for the app's files
   and `clue-backups` for the nightly database dumps.
2. R2 → Manage API tokens → **two** tokens, each **Object Read & Write** on **one** bucket:
   - the app token on `clue-prod` only (Railway services and the VM's `/srv/clue/env`);
   - the backup token on `clue-backups` only (the VM's `/srv/clue/backup.env`).
   Record each access key id and secret, and the S3 endpoint
   `https://<account-id>.r2.cloudflarestorage.com`.
   **Why two:** the app's fleet workers delete every object in `clue-prod` that has no `artifact`
   row (the orphan sweep, every 6 hours), which would remove each dump within a day; and a token
   shared with the app would let an app bug or a leaked app key delete the backups.
   `backup_db.sh` refuses to run if its bucket or key matches the app's.
3. Pages delivery: follow `docs/specs/pages-hosting-runbook.md` (Worker, edge secret, Cloudflare for
   SaaS on `pages.cluehq.ai`; the move to the published pages' own domain is that runbook's §8).
   Record `CLUE_PAGES_EDGE_SECRET`.

## 2. Railway [FOUNDER]
The variable files are generated from `.env.example` into `~/clue-deploy/` (outside the repo):
`railway/1-shared-secrets.env` (secrets only, `<FILL: …>` placeholders), `2-platform-api.env`,
`3-design-api.env`, `4-page-origin.env` (no secrets: they reference `${{shared.NAME}}`), and
`vm/srv-clue-env.env` for §4. Every service file passes `check_prod_env.py` as generated.

**The design API is never public.** It decides the workspace from an `X-Workspace-Id` header with
no login check, so it has **no public domain**: the frontend's server and `platform-api` reach it on
Railway's private network (`http://design-api.railway.internal:8010`), and the VM's preview renders
fetch images through the frontend's narrow public proxy
(`https://app.cluehq.ai/api/clue/design-public/asset-store/<digest>`).

1. Project (Pro plan); every service's region **US East (Virginia)**. Leave **"Wait for CI" off**.
2. **Postgres 16 + pgvector, with encryption enforced.** Not a marketplace template: the pgvector
   ones run Postgres 18 (our backup/restore tools are 16) or omit the `PG*` variables, and the plain
   image runs with SSL **off** while the VM connects over the public TCP proxy with `ssl=require`.
   - **+ Create → Docker Image** → `pgvector/pgvector:pg16`. Rename the service (click its name in the
     panel header) to exactly **`Postgres`**; region US East.
   - **Volume** mounted at `/var/lib/postgresql/data`; set its size with room to grow (long-used
     lane databases reached ~2.5 GB, almost all agent checkpoints).
   - **Variables:**
     ```
     POSTGRES_USER=postgres
     POSTGRES_PASSWORD=<openssl rand -hex 24>
     POSTGRES_DB=railway
     PGDATA=/var/lib/postgresql/data/pgdata
     PGUSER=${{POSTGRES_USER}}
     PGPASSWORD=${{POSTGRES_PASSWORD}}
     PGDATABASE=${{POSTGRES_DB}}
     ```
     (`PGDATA` is a subfolder: a fresh volume holds `lost+found`, and `initdb` refuses a non-empty dir.)
   - **Settings → Deploy → Custom Start Command:** the one line in
     `deploy/railway-postgres-start-command.txt`. On first start it creates a self-signed certificate
     on the volume (kept across restarts), turns SSL on, refuses every non-SSL connection from another
     host (`hostssl` only), and sets `max_connections=200`, `shared_buffers=1GB`,
     `effective_cache_size=3GB`, `work_mem=8MB`, `maintenance_work_mem=256MB`, `random_page_cost=1.1`,
     a 10-minute idle-in-transaction timeout and a 2-second slow-query log. Memory limit **4 GB**.
     (Tested 2026-10-02 on this image: SSL in use, plaintext and wrong password refused, same after a
     restart.)
   - Deploy, then **Settings → Networking → TCP Proxy** on port **5432** (record host and port; the
     VM uses it) and scheduled **backups** on the volume.
   - From your Mac (`psql "<TCP-proxy URL>?sslmode=require"`), as `postgres`:
     ```sql
     CREATE EXTENSION IF NOT EXISTS vector;
     CREATE ROLE clue_worker LOGIN PASSWORD '<long random>';
     GRANT CONNECT ON DATABASE railway TO clue_worker;
     GRANT USAGE ON SCHEMA public TO clue_worker;
     GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO clue_worker;
     GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO clue_worker;
     ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO clue_worker;
     ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO clue_worker;
     ```
     Migrations run as `postgres`; `design-api`, `page-origin` and the VM workers run as `clue_worker`.
   `clue_worker` has no CREATE on schema public. LangGraph's checkpoint tables therefore come from a
   migration (`4a94970221e9`), and the runtime runs LangGraph's `setup()` only when they are behind.
   (2026-10-03: before that migration existed, a temporary `GRANT CREATE ON SCHEMA public TO
   clue_worker` unblocked production; once a release containing `4a94970221e9` is deployed, run
   `REVOKE CREATE ON SCHEMA public FROM clue_worker;` as the owner.)
     Every Railway database URL in the variable files carries `?ssl=require`.
3. **Redis 7, TLS for the VM.** Railway's Redis serves no TLS, and the VM reaches Redis over the
   public TCP proxy, so the password and lock traffic would cross the internet in clear text.
   - **+ Create → Docker Image** → `redis:7`, named exactly **`Redis`**, region US East. No volume
     needed (locks and rate-limit buckets are short-lived).
   - On your Mac, make its certificate once (the image has no `openssl`):
     ```bash
     openssl req -new -x509 -days 3650 -nodes -subj "/CN=redis" -keyout redis.key -out redis.crt
     base64 < redis.crt | tr -d '\n' | pbcopy   # → REDIS_TLS_CERT_B64
     base64 < redis.key | tr -d '\n' | pbcopy   # → REDIS_TLS_KEY_B64 (then delete both files)
     ```
   - **Variables:**
     ```
     REDIS_PASSWORD=<openssl rand -hex 24>
     REDIS_TLS_CERT_B64=<one line>
     REDIS_TLS_KEY_B64=<one line>
     REDIS_URL=redis://default:${{REDIS_PASSWORD}}@${{RAILWAY_PRIVATE_DOMAIN}}:6380/0
     ```
   - **Custom Start Command:** the one line in `deploy/railway-redis-start-command.txt`. Redis serves
     **TLS on 6379** and plain **6380** for the private network only (Railway's WireGuard mesh; the
     services use `${{Redis.REDIS_URL}}`), with `requirepass` and `noeviction`. TLS sits on the
     standard port because Railway's **Add Public Access** detects Redis and proxies 6379 without
     asking.
   - **Public Access** (the TCP proxy) on **6379** — the TLS port. The VM's
     `CLUE_REDIS_URL=rediss://default:<REDIS_PASSWORD>@<proxy-host>:<proxy-port>/0?ssl_cert_reqs=none`
     (`check_prod_env.py worker` refuses anything else). Tested 2026-10-02 with redis-py: private
     plain and public TLS connect; plain on the TLS port and a wrong password are refused.
4. **Clerk production instance** (Clerk dashboard → Create production instance, domain
   `cluehq.ai`). Add every DNS record its **Domains** page lists to Cloudflare as **DNS only (grey
   cloud)**; wait until Clerk shows them verified and deploys its certificates. Its Frontend API is
   then `https://clerk.cluehq.ai` — the variable files assume that issuer and JWKS URL; if Clerk
   shows a different one, change both lines in `2-platform-api.env`. In production, social sign-in
   needs your own OAuth credentials; email-code sign-up needs bot protection off and email
   verification by code on (as on the development instance).
5. **Shared Variables** (Project Settings): fill every `<FILL>` in `1-shared-secrets.env`, paste it.
   Production also needs, as shared variables referenced by `platform-api` and `design-api` (and in
   the VM's `/srv/clue/env`) — settings refuse the in-memory metrics sink in production:
   `CLUE_METRICS_EXPORTER=otlp`, `CLUE_METRICS_OTLP_ENDPOINT=<Grafana Cloud OTLP endpoint>/v1/metrics`
   (the full path: the exporter uses it as written) and
   `OTEL_EXPORTER_OTLP_METRICS_HEADERS=Authorization=Basic%20<base64 of instanceID:token>` (the
   metrics-only header, so traces keep going to Langfuse). Grafana Cloud stack `curiousferret2524`,
   us-east-3 (chosen 2026-10-03). **Sumble is off in production:**
   `CLUE_SUMBLE_ACCOUNT_GAP_ENRICHMENT_ENABLED=false` and
   `CLUE_SUMBLE_DISCOVERY_GAP_ENRICHMENT_ENABLED=false` (each switch on without `CLUE_SUMBLE_API_KEY`
   makes the service refuse to start).
6. Three services; paste each one's file into Variables → Raw Editor. **`platform-api` and `design-api`
   run the image CI built and tested** — they never build it themselves (2026-10-03): Settings → Source →
   Docker image `ghcr.io/clue-hq/clue-backend:production`, and under **Registry Credentials** a GitHub
   personal access token (classic) with only `read:packages`. Their `RAILWAY_DOCKERFILE_PATH` line is
   then unused. `deploy-images` redeploys them after moving the `production` tags
   (`deploy/railway_redeploy.sh`, `platform-api` first), using the repository secret
   **`RAILWAY_TOKEN`**: a Railway project token for this project's production environment.
   `page-origin` builds from this repo, branch **`main`**. Then:
   - `platform-api` — start command `clue platform-api`, **pre-deploy command `clue migrate`** (the
     only place migrations run), memory 1 GB, health check `/healthz`, domain `api.cluehq.ai`
     (Cloudflare CNAME, **DNS only**). Add the zone id and Cloudflare token references once Part C
     exists (they are already in the file).
   - `design-api` — start command `clue design-api`, memory 1.5 GB, health check `/healthz`,
     **no domain**. Its file sets `PORT=8010`; it listens on IPv4 (`0.0.0.0`), which this project's
     private network supports (Railway shows "IPv4 & IPv6" under Private Networking). Only in an
     IPv6-only environment would it need `CLUE_BIND_HOST=::` (uvicorn on `::` is IPv6-only).
   - `page-origin` — no start command (its Dockerfile has one), memory 256 MB, health check
     `/healthz`, domain `page-origin.cluehq.ai` (**DNS only**).
7. **Frontend** service (already exists): branch **`main`**, and set
   **`RAILWAY_DOCKERFILE_PATH=/apps/frontend/Dockerfile.railway`** (without it Railway's auto-builder
   detects the repository root as Python and fails — 2026-10-03, when replacing the variables dropped
   it), `CLUE_AUTH_ENABLED=true`, `CLUE_API_BASE_URL=http://platform-api.railway.internal:8020` (the
   frontend's server reaches the API privately; the public `https://api.cluehq.ai` also works),
   `LUMEN_API_BASE_URL=http://design-api.railway.internal:8010` (private — never a public URL),
   `CLUE_APP_ORIGIN=https://app.cluehq.ai`, `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES=https://app.cluehq.ai`,
   `CLUE_PROJECTS_API_BASE_URL=/api/clue`, and the production Clerk pair
   `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY=pk_live_…` / `CLERK_SECRET_KEY=sk_live_…` (the publishable key
   is baked in at build, so redeploy after changing it). Domain `app.cluehq.ai`, **DNS only**. Its
   build runs the editor wasm check in strict mode (`WASM_PREFLIGHT_STRICT=1`).
8. Check the service files (they pass as generated; re-run after any edit), and before deploying
   boot each backend locally with its **real** Railway variables — only the database and Redis are
   swapped for throwaway ones; no value is printed — so every startup refusal shows at once instead
   of one failed deploy at a time (from a directory `railway link`ed to the project):
   `deploy/railway_boot_check.sh platform-api platform-api ghcr.io/clue-hq/clue-backend:production`
   (and `design-api design-api …`).
   ```bash
   python3 deploy/check_prod_env.py platform-api ~/clue-deploy/railway/2-platform-api.env
   python3 deploy/check_prod_env.py design-api ~/clue-deploy/railway/3-design-api.env
   python3 deploy/check_prod_env.py page-origin ~/clue-deploy/railway/4-page-origin.env
   ```
   The image sets `LUMEN_CORE_HELPER`, `LUMEN_FONT_LIBRARY_MANIFEST_PATH`, `CLUE_ARV2_RAW_ROOT` and
   `LUMEN_SITE_RENDER_CHROMIUM_SANDBOX` (0: containers cannot give the site renderer's Chromium its
   own sandbox — `docs/specs/2026-10-14-site-render-chromium-sandbox-decision.md`); the check refuses any line for them. Until the release PR merges `main`, every backend build
   fails (the code is not on `main` yet) — expected; Railway rebuilds on the merge.

## 3. OVHcloud VPS-4 [FOUNDER]
1. Order a **VPS-4** (8 vCores / 24 GB / 200 GB NVMe) from the **US** Control Panel
   (`manager.us.ovhcloud.com`) so it lands in **Virginia (US-EAST-VA)**, next to Railway's US East.
   Never a US *West* VM: it would add ~70 ms to every database round trip. Image **Ubuntu 24.04**
   (pick it in the version list; 26.04 is the default), local storage, no commitment. The order
   asks for no SSH key: the delivery email gives the `ubuntu` user a one-time password link; use it
   once for `ssh-copy-id ubuntu@<vm>`, then log in with the key. Note the VM's public IPv4.
   (Ordered 2026-10-02: `vps-2df8067d.vps.ovh.us`, US-EAST-VA, month-to-month.)
2. GHCR: create a GitHub token with **read:packages** only, for `docker login ghcr.io` on the VM.

## 4. Worker VM setup
OVHcloud's Ubuntu image logs in as **`ubuntu`** (with sudo); root SSH login is disabled.
1. `scp deploy/vm/bootstrap.sh deploy/vm/harden_ssh.sh ubuntu@<vm>:` then
   `ssh ubuntu@<vm> sudo bash bootstrap.sh`. Its first step, `harden_ssh.sh`, turns SSH password
   login off (and root login) — and refuses, changing nothing, until your key is installed
   (`ssh-copy-id`, §3), so it cannot lock you out. It stops at the `git clone` step until step 2
   is done; re-run it afterwards (it is idempotent).
2. On the VM (`ssh ubuntu@<vm>`): `sudo -u clue ssh-keygen -t ed25519 -N "" -f /home/clue/.ssh/id_ed25519`; add
   `/home/clue/.ssh/id_ed25519.pub` to GitHub → repo → Settings → **Deploy keys** (read-only)
   [FOUNDER]; then `sudo -u clue ssh -o StrictHostKeyChecking=accept-new git@github.com` once, and
   re-run `sudo bash bootstrap.sh`.
3. As `clue` (`sudo -iu clue`): `docker login ghcr.io` with the read-only token.
4. Fill `/srv/clue/env`: every `.env.example` key with production values, plus:
   - `CLUE_DATABASE_URL` = the **direct** Railway TCP-proxy URL for `clue_worker`
     (`postgresql+asyncpg://clue_worker:<pw>@<proxy-host>:<port>/railway?ssl=require`). Every
     container in `compose.yaml` overrides it with the PgBouncer URL; it is only what a one-off
     `docker run --env-file /srv/clue/env …` shell sees.
   - `LUMEN_INGESTION_CONTROLLER_DATABASE_URL` = the **same direct URL**. Only the ingestion pool's
     controller reads it — one connection, holding a session-level advisory lock that PgBouncer's
     transaction pooling would break. Its coordinator and analysis children, like every pool, go
     through PgBouncer. `check_prod_env.py` refuses the file without it, or with it pointing at
     PgBouncer.
   - `CLUE_MIGRATE_DATABASE_URL` = the direct proxy URL for the **owner** role (used only to check
     the schema is at head before a deploy).
   - `CLUE_REDIS_URL` = the Railway Redis proxy URL.
   - `CLUE_SANDBOX_ENABLED=true` (`deploy.sh` sets `CLUE_SANDBOX_IMAGE` on every deploy).
   - **Do not** set `CLUE_FLEET_WORKER_KINDS` here — `compose.yaml` sets it per pool.
   - **Do not** copy `LUMEN_CORE_HELPER`, `LUMEN_FONT_LIBRARY_MANIFEST_PATH`, `CLUE_ARV2_RAW_ROOT`
     or `LUMEN_SITE_RENDER_CHROMIUM_SANDBOX` from the example — the image sets all four (the last
     is 0 on purpose: `docs/specs/2026-10-14-site-render-chromium-sandbox-decision.md`).
   Check it: `python3 /srv/clue/app/deploy/check_prod_env.py worker /srv/clue/env` → `OK`.
5. Fill `/srv/clue/pgbouncer.env` (the `edoburu/pgbouncer` image turns these into its config — confirm
   the names against the image README for tag `v1.23.1-p3`):
   ```
   DATABASE_URL=postgres://clue_worker:<pw>@<proxy-host>:<port>/railway
   POOL_MODE=transaction
   MAX_PREPARED_STATEMENTS=200
   DEFAULT_POOL_SIZE=20
   MAX_CLIENT_CONN=200
   STATS_USERS=clue_worker
   AUTH_TYPE=scram-sha-256
   SERVER_TLS_SSLMODE=require
   LISTEN_PORT=6432
   ```
   Put the same `clue_worker` password in `/srv/clue/compose.env` as `PGBOUNCER_CLIENT_PASSWORD`.
   (Transaction pooling is safe for everything behind it: all 59 of the workers' advisory locks
   are transaction-scoped; the one session-level lock, the ingestion controller's, bypasses
   PgBouncer. If something else turns out to need session state, give that process its own
   direct URL the same way, or a second session-mode PgBouncer pool for it alone — never
   `POOL_MODE=session` for the whole VM.)

   **Research capacity and connection checks (2026-10-03).** `STATS_USERS` gives the app user
   read-only `SHOW POOLS` / `SHOW STATS` on PgBouncer's admin database (confirm the variable name
   against the image README for this tag, as above).
   - Research jobs run at once, fleet-wide = batch workers × `CLUE_ARV2_ACCOUNT_MAX_PARALLEL_JOBS`
     (today 3 × 4 = 12). A worker never claims more research tasks than it can run.
   - Are transactions waiting for a PgBouncer server connection? From a worker container, connect
     to the `pgbouncer` database on port 6432 as `clue_worker` and run `SHOW POOLS;` — `cl_waiting`
     staying above 0 means the pool is too small.
   - `DEFAULT_POOL_SIZE` goes from 20 to 40 **only after** the research slowness fixes
     (`docs/superpowers/specs/2026-10-03-research-slowness-fixes-design.md`) are deployed and
     measured: raising it before them only lets more transactions wait on the same locks. Postgres
     allows 200 connections and the Railway services use about 10. Edit `/srv/clue/pgbouncer.env`,
     then run `docker compose up -d pgbouncer` from `/srv/clue/app/deploy/vm` as `clue`.
   - Lock waits: sample `pg_stat_activity` for `wait_event_type='Lock'` while research runs, and
     look for `db.critical_section` lines in the batch workers' logs (`docker logs vm-batch1-1`).
6. Fill `/srv/clue/backup.env`:
   ```
   PGURL=postgresql://<owner>:<pw>@<proxy-host>:<port>/railway?sslmode=require
   R2_ENDPOINT=https://<account-id>.r2.cloudflarestorage.com
   R2_BUCKET=clue-backups
   AWS_ACCESS_KEY_ID=<backup token key id — NOT the app token>
   AWS_SECRET_ACCESS_KEY=<backup token secret>
   SENTRY_CRON_URL_BACKUP=<sentry cron check-in url>
   SENTRY_CRON_URL_WATCHDOG=<sentry cron check-in url>
   ```
7. Sentry → Crons [FOUNDER]: monitor `clue-db-backup` (daily, 26-hour margin) and `clue-watchdog`
   (every 5 minutes, 10-minute margin), alerting the founder. A missed check-in is the alert.
8. **CI deploys the VM** (one time). On your Mac:
   `ssh-keygen -t ed25519 -N "" -C clue-ci-deploy -f ci_deploy_key`. On the VM, append to
   `/home/clue/.ssh/authorized_keys` (owned by clue, mode 600):
   `command="/srv/clue/app/deploy/vm/ci_deploy.sh",restrict <contents of ci_deploy_key.pub>` —
   the key can then only ask `deploy/vm/ci_deploy.sh` to deploy one full commit sha. In GitHub
   (repo Settings → Secrets and variables → Actions): secret **`VM_SSH_KEY`** = `ci_deploy_key`
   (the private key), secret **`VM_SSH_KNOWN_HOSTS`** = `ssh-keyscan -t ed25519 <vm-ip>` (pins the
   host key), variable **`VM_HOST`** = the VM's IP. Delete the local key files afterwards. Until
   all three exist, `deploy-images` warns and skips the VM step.

## 5. Vendors [FOUNDER]
Set monthly spend caps and alerts on OpenRouter, Exa, AI Ark and Adyntel.

## 6. First ship
0. **Before pushing any change to the images** (`docker/`, `pyproject.toml`/`uv.lock`, the
   `deploy-images` workflow): run `docker/backend/local_gate.sh` from the repository root. It refuses
   to build with under 15 GB of Docker disk free, builds both images, and runs `smoke.sh` and
   `boot_smoke.sh` — the checks CI runs — in about 8 minutes cached. CI then confirms on amd64.
1. Open a pull request from `research-streaming` into `main` [FOUNDER]. Its `deploy-images` run builds
   both images, checks the engine handshake, and runs the static and boot smoke tests (migrations, both
   APIs' health, the S3 storage round trip, worker start, the sandbox). **Merge only once that check
   is green** — merging while it runs is how 2026-10-02's release shipped an image that never built.
2. The merge's own `deploy-images` run repeats every check and only then moves the `production` tags.
   It must be green.
3. That run then redeploys `platform-api` from the new image and waits until it is live — its
   pre-deploy `clue migrate` runs `alembic upgrade head` once — and then `design-api`, then
   `page-origin` (which also builds from `main` on its own and can fail before the migration lands;
   this redeploy puts it on the migrated schema). The frontend rebuilds from `main` as before.
4. **Only after Railway is green**, on the VM as `clue`:
   `/srv/clue/app/deploy/vm/deploy.sh <sha>` — it refuses if the database is not at head, and
   if the agent workspace root (`/srv/clue/workspaces`) fails the workers' own boot check (every
   entry must be a private 0700 directory owned by UID 1000; the refusal names the entry, and
   nothing is restarted). It keeps the design agent's root `/srv/clue/lumen-agent` (UID 1000,
   0700) separate from that root, and after `up` it fails the deploy if any worker restarts
   (2026-10-04: a 0755 `/srv/clue/workspaces/lumen-agent` crash-looped every fleet worker while
   the deploy reported success).
5. Uptime checks (Better Stack or UptimeRobot free tier) on `https://app.cluehq.ai`,
   `https://api.cluehq.ai/healthz`, and one published page. (The design API has no public domain; Railway's
   health check covers it.)

## 7. Every later ship
Merge a pull request from `research-streaming` into `main` once staging is tested and the pull
request's `deploy-images` check is green (image changes: `local_gate.sh` first). The merge's
`deploy-images` run moves the tags, redeploys Railway (`platform-api` first) and then the worker VM
(§4 step 8). Without that step configured, or if it fails: `deploy.sh <sha>` on the VM as `clue`.
A release that adds a variable the workers need: add it to `/srv/clue/env` first.

## 7a. Known gap — accepted for now, to be closed later
Railway rebuilds the frontend and the design API separately, so for a minute or two during a deploy
they can run different editor-engine versions; an editor opened in that window shows the "Canvas
editing is disabled" banner until reloaded. (Founder, 2026-10-01: acceptable only for now.)

## 8. Rollback
Railway: redeploy the previous deployment of each service. VM: `deploy.sh <previous-sha>`. To undo a
migration (migrations are reversible by repo rule), on the VM:
```bash
docker run --rm --env-file /srv/clue/env \
  -e CLUE_DATABASE_URL="$(grep '^CLUE_MIGRATE_DATABASE_URL=' /srv/clue/env | cut -d= -f2-)" \
  ghcr.io/clue-hq/clue-backend:<sha> shell -c "cd /app && alembic downgrade -1"
```

## 9. Restore rehearsal
On the VM: `/srv/clue/app/deploy/vm/restore_check.sh` — must end with `RESTORE CHECK PASSED`. Do it
once before the first pilot and before any provider move. (Rehearsed 2026-10-01 against the lane
database: alembic head and the row counts of five tables matched the source exactly.)

## 10. Moving to AWS later (spec §13)
Build RDS (Postgres 16 + pgvector) and an EC2 VM from the same compose file; stop the Railway
services and the VM pools; `pg_dump` from Railway and `pg_restore` into RDS; compare the row counts
`restore_check.sh` prints; repoint `CLUE_DATABASE_URL`, `CLUE_MIGRATE_DATABASE_URL` and PgBouncer's
`DATABASE_URL`; start everything. Keep Railway Postgres read-only for two weeks. R2 does not move.

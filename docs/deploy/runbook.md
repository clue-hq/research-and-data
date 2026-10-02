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
   SaaS on `pages.cluehq.ai`). Record `CLUE_PAGES_EDGE_SECRET`.

## 2. Railway [FOUNDER]
1. Project region: **US East**.
2. Add **Postgres** from the pgvector template (Postgres 16). In its query shell, as the owner role:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ALTER SYSTEM SET max_connections = 200;   -- then restart the Postgres service
   CREATE ROLE clue_worker LOGIN PASSWORD '<long random>';
   GRANT CONNECT ON DATABASE railway TO clue_worker;
   GRANT USAGE ON SCHEMA public TO clue_worker;
   GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO clue_worker;
   GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO clue_worker;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO clue_worker;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO clue_worker;
   ```
   Enable the **TCP proxy** (record host and port) and scheduled **volume backups**. Migrations run
   as the owner role; the workers run as `clue_worker`.
3. Add **Redis** (Redis 7). Enable its TCP proxy; record host, port and password.
4. Add three services from this repo, branch **`main`**, each built by Railway with
   `RAILWAY_DOCKERFILE_PATH=/docker/backend/Dockerfile` (the same Dockerfile CI builds for the VM):
   - `platform-api` — start command `clue platform-api`, **pre-deploy command `clue migrate`** (the
     only place migrations run), memory limit 1 GB, health check path `/healthz`, domain
     `api.cluehq.ai`.
   - `design-api` — start command `clue design-api`, memory limit 1.5 GB, health check `/healthz`,
     domain `design-api.cluehq.ai`, **`LUMEN_EMBEDDED_FLEET_WORKER=0`** (design jobs run on the VM).
   - `page-origin` — `RAILWAY_DOCKERFILE_PATH=/platform/page_origin/Dockerfile.railway`, memory
     256 MB, health check `/healthz`.
5. **Frontend** service (already exists): change its branch from
   `integration/frontend-design-part-iv-v4` to **`main`**; set
   `CLUE_API_BASE_URL=https://api.cluehq.ai`, `LUMEN_API_BASE_URL=https://design-api.cluehq.ai`,
   `CLUE_APP_ORIGIN=https://app.cluehq.ai`,
   `CLUE_AUTH_CLERK_AUTHORIZED_PARTIES=https://app.cluehq.ai`. Its build now runs the editor wasm
   check in strict mode (`WASM_PREFLIGHT_STRICT=1`): a stale browser engine fails the build.
6. Variables for `platform-api` and `design-api`: every key in `.env.example` with its production
   value (spec §10). **Leave out the three paths the image sets** (here and on the VM):
   `LUMEN_CORE_HELPER`, `LUMEN_FONT_LIBRARY_MANIFEST_PATH`, `CLUE_ARV2_RAW_ROOT`. Any line for them —
   even an empty one — overrides the image: a blank helper falls back to `cargo run` (not in the
   image, so every design render fails), the font path is a checkout placeholder, and the raw root
   is relative (podcast downloads fail). `check_prod_env.py` refuses them. `CLUE_DATABASE_URL` and `CLUE_REDIS_URL` use Railway's **private** hostnames.
   Before saving, paste each service's variables into a local file and check it:
   ```bash
   python3 deploy/check_prod_env.py platform-api /path/to/platform-api.env
   python3 deploy/check_prod_env.py design-api /path/to/design-api.env
   ```
   Both must print `OK`.

## 3. OVHcloud VPS-4 [FOUNDER]
1. Order a **VPS-4** (8 vCores / 24 GB / 200 GB NVMe) at **North America (Canada - East -
   Beauharnois)**, about 15–20 ms from Railway's US East (the US data centers were out of stock on
   2026-10-02; a US *West* VM would add ~70 ms to every database round trip — don't). Image
   **Ubuntu 24.04** (pick it in the version list; 26.04 is the default), local storage, no
   commitment, with your SSH key. Note the VM's public IPv4.
2. GHCR: create a GitHub token with **read:packages** only, for `docker login ghcr.io` on the VM.

## 4. Worker VM setup
OVHcloud's Ubuntu image logs in as **`ubuntu`** (with sudo); root SSH login is disabled.
1. `scp deploy/vm/bootstrap.sh ubuntu@<vm>:` then `ssh ubuntu@<vm> sudo bash bootstrap.sh`. It stops
   at the `git clone` step until step 2 is done; re-run it afterwards (it is idempotent).
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
   - **Do not** copy `LUMEN_CORE_HELPER`, `LUMEN_FONT_LIBRARY_MANIFEST_PATH` or `CLUE_ARV2_RAW_ROOT`
     from the example — the image sets all three.
   Check it: `python3 /srv/clue/app/deploy/check_prod_env.py worker /srv/clue/env` → `OK`.
5. Fill `/srv/clue/pgbouncer.env` (the `edoburu/pgbouncer` image turns these into its config — confirm
   the names against the image README for tag `v1.23.1-p3`):
   ```
   DATABASE_URL=postgres://clue_worker:<pw>@<proxy-host>:<port>/railway
   POOL_MODE=transaction
   MAX_PREPARED_STATEMENTS=200
   DEFAULT_POOL_SIZE=20
   MAX_CLIENT_CONN=200
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

## 5. Vendors [FOUNDER]
Set monthly spend caps and alerts on OpenRouter, Exa, AI Ark and Adyntel.

## 6. First ship
1. Open a pull request from `research-streaming` into `main` and merge it [FOUNDER]. (The first one
   merges cleanly — checked 2026-10-01.)
2. Watch the `deploy-images` workflow: it builds both images, checks the engine handshake, runs the
   static and boot smoke tests, and only then moves the `production` tags. It must be green.
3. Railway rebuilds and redeploys from `main`; `platform-api`'s pre-deploy `clue migrate` runs
   `alembic upgrade head` once.
4. **Only after Railway is green**, on the VM as `clue`:
   `/srv/clue/app/deploy/vm/deploy.sh <sha>` — it refuses if the database is not at head.
5. Uptime checks (Better Stack or UptimeRobot free tier) on `https://app.cluehq.ai`,
   `https://api.cluehq.ai/healthz`, `https://design-api.cluehq.ai/healthz`, and one published page.

## 7. Every later ship
Merge a pull request from `research-streaming` into `main` once staging is tested; wait for
`deploy-images` and Railway to go green; then `deploy.sh <sha>` on the VM.

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

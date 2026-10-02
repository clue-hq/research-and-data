# 2026-10-01 — First deployment: spec, plan, implementation (Tasks 1–9)

Branch `deploy/first-deployment` (off `research-streaming` at `e2e629684`). Spec
`docs/superpowers/specs/2026-10-01-first-deployment-design.md`, plan
`docs/superpowers/plans/2026-10-01-first-deployment.md`, runbook `docs/deploy/runbook.md`.
Ledger with every ruling: `.superpowers/sdd/2026-10-01-first-deployment/progress.md` (git-ignored).

## Founder decisions (2026-09-30 → 10-01)
- Audience internal + first pilots; US East; pre-funding budget (~$60–70/month infra).
- Web tier + Postgres 16/pgvector + Redis 7 on **Railway**; one stateless **OVHcloud VPS-4**
  (8 vCores/24 GB, $23.37) for workers; files in **Cloudflare R2**; nightly pg_dump to R2.
- Pools: chat `agent_turn` 1×10, design `design_job` 1×8, batch 3×10. Workspace fairness/rate limits
  deferred until after the credit system.
- **`main` is the deployment branch; `research-streaming` is staging.** Releasing = PR rs → main.
- CI boots every service before the `production` image tag moves; engine handshake gate (Task 4B).
- Deploy-window frontend/design-API engine mismatch accepted **only for now**.
- Measured sizing (lane, 2026-09-30): research slot +25–90 MB, ~0.05 core; website design slot
  ~1 GB peak (Chromium 524 MB, alive ~18% of the run); worker process 363–390 MB idle.
- Rejected with reasons: AWS-now, Postgres on the VM, Neon (third provider), Convex (not Postgres),
  Hetzner US (now $165.99 for 8/32 after its June 2026 price rise).

## Built (commits e431f36..f9ef87d)
1 `CLUE_FLEET_WORKER_KINDS` · 2 S3 env guard (they already existed — my grep missed the digit in
S3) · 3 VM compose (ingestion pool bypasses PgBouncer: its controller holds the one session-level
advisory lock) · 4 backend image (**unbuilt**) · 4A `/healthz` on both APIs (live-verified on the
lane) · 4B strict wasm preflight + helper-in-image handshake (copy-design-vendor swallowed failures
too) · 5 `deploy/check_prod_env.py` · 6 backup/watchdog/restore (restore rehearsed for real: lane DB
137 MB, counts matched) · 7 bootstrap/deploy.sh · 8 deploy-images workflow + boot_smoke.sh · 9 runbook.

## Owed
- **Task 4 build + `docker/backend/smoke.sh`**, and a first run of `boot_smoke.sh` — Docker Desktop
  20.10.22 here cannot pull any image (registries answer the host in <1s; daemon pulls hang).
  Needs a Docker Desktop restart (interrupts other lanes' containers) or a CI run (needs a push).
- Task 10 with the founder: runbook §1–§5 dashboards, PR rs → main, acceptance walk, restore check.
- The final review was a self-review (founder rule: no reviewer subagents).

## Found along the way (task chips raised)
- The fleet orphan sweep deleted 37 committed files under `.artifacts/` (storage root) at 06:53 UTC;
  restored from git; they return to deletion on the next sweep. Chip: "Move committed reports out of
  the storage root".
- The clue-design Python suite takes hours. Chip: "Speed up the clue-design Python test suite".

## 2026-10-01 — PgBouncer split (founder ruling)
- PgBouncer stays `POOL_MODE=transaction` for every fleet pool AND the ingestion children; only the
  ingestion **controller** (one connection, session advisory lock `CONTROLLER_LOCK`) connects
  directly, via new `LUMEN_INGESTION_CONTROLLER_DATABASE_URL` (empty default = CLUE_DATABASE_URL),
  read only by `lumen_api/ingestion_pool.py::controller_engine()`. Never session mode for the VM.
- compose: ingestion now uses `x-worker-env` (PgBouncer CLUE_DATABASE_URL) + `depends_on: pgbouncer`,
  still no Docker socket. `check_prod_env.py worker` requires the controller URL, refuses PgBouncer/localhost.
- Tests: design `apps/api/tests/test_ingestion_pool_database_url.py` (4), deploy suites 78 pass.
- Lane DB on 55040 was DOWN this session (design healthz test fails on connect — environmental).
- Pre-existing ruff I001/SIM105 in ingestion_pool.py left alone (not this change).
- Still open from the `.artifacts` discussion: backups share `clue-prod` with the orphan sweep
  (would be deleted within ~24h) → proposed separate `clue-backups` bucket; `CLUE_ARV2_RAW_ROOT`
  relative default is unwritable in the image (uid 1000, /app root-owned). Awaiting founder go-ahead.

## 2026-10-01 — Problem B fixed: ARV2 raw root in production
- Only production writer of `CLUE_ARV2_RAW_ROOT`: the podcast hop (`account_research_tools._podcast_hop`
  → `download_enclosure`, mkdir + mp3 per episode). Raw records/ledger go to the DB in production.
- Fix: (1) the hop deletes the audio (and the job's empty folder) in a `finally` once transcribed or
  failed — it never accumulated-safely before; (2) image sets `CLUE_ARV2_RAW_ROOT=/var/lib/clue/arv2-raw`,
  created + chowned to uid 1000 before `USER`; (3) `smoke.sh` writes there as the image user;
  (4) `check_prod_env.py` (every role) refuses a relative value — the `.env.example` default copied
  into an env file would override the image; runbook + spec §10: leave the key out.
- Tests: 2 hop tests (RED→GREEN), 3 image-source tests, 4 env-check tests; arv2+deploy 1202 pass.
- Pre-existing, NOT this change (recorded only): `tests/arv2/test_person_{continuation_preview,
  discovery_trial,trial_source_review}.py` fail to import `duration_of` from media_acquisition;
  `test_account_research_port` pins recipe_version 22 (resource is 24); `test_import_guard` flags
  person_research_brief/quality_reconciliation imports.
- Same class, not fixed: root `.env.example` LUMEN_FONT_LIBRARY_MANIFEST_PATH placeholder
  (`/absolute/path/to/your/checkout/...`) would override the image's correct value if copied.
- Smoke/Docker build still unrun locally (Docker can't pull) — first proof is the CI image run.

## 2026-10-01 — Problem A fixed: backups in their own bucket; image-owned paths; stale tests
- Problem A: audited every storage writer (core app, research, design `clue_design.storage`,
  pages) — all record an `artifact` row before `put`; the only object put in the bucket from
  outside the app was the nightly dump, which `sweep_orphan_blobs` (every fleet worker, 6-hourly,
  24h grace) would delete. Fix: bucket `clue-backups` + its own token; `backup_db.sh` reads the app
  env (`CLUE_ENV_FILE`, default /srv/clue/env) and refuses (before pg_dump, no Sentry check-in) if
  the bucket or key matches the app's or the app env is unreadable. Runbook §1/§4.6, spec §8, plan
  Task 6 ruling updated. (Unused `StorageAgentArtifactSink` writes without a row — not wired.)
- Image-owned paths: check_prod_env refuses ANY line (even empty) for LUMEN_CORE_HELPER,
  LUMEN_FONT_LIBRARY_MANIFEST_PATH, CLUE_ARV2_RAW_ROOT on every role (blank helper = `cargo run`,
  absent in the image → every design render fails). Both .env.example files mark the lines.
- Stale tests reconciled (0215602d6): trial script keeps its own ffprobe `duration_of` and its own
  file-layout `source_navigation`; recipe pin → "default = newest recipe file"; import guard
  allowlists `clue_api.quality_research_artifacts` + `clue_api.execution_wiring`. arv2+deploy:
  1222 pass, 0 fail (406 DB skips — lane DB on 55040 down).

## 2026-10-02 — Railway variables prepared; design API made private; Clerk production
- **Design API gets NO public domain** (security): it trusts X-Workspace-Id with no login. Frontend
  BFF + platform-api use http://design-api.railway.internal:8010 (PORT=8010, CLUE_BIND_HOST=::);
  the VM's previews use LUMEN_API_ORIGIN=https://app.cluehq.ai/api/clue/design-public (the
  unauthenticated, 64-hex-locked /asset-store proxy). uvicorn on :: is IPv6-only (measured on macOS).
- check_prod_env: page-origin role (edge secret only there), region required, production auth for
  app roles (also what arms the dev-lens startup refusal — VM workers need it), production Clerk on
  platform-api, both dev lenses off, bare ${...} refused (.env.example's OPENROUTER/IMAGE key lines
  would have reached Railway/docker as literal text), worker LUMEN_API_ORIGIN public https.
- compose: LUMEN_AGENT_WORKSPACE_ROOT=/srv/clue/workspaces/lumen-agent (else design session memory
  lived inside the image and every redeploy wiped it).
- Variable files generated to ~/clue-deploy/{railway,vm}/ (outside repo, 0600): shared secrets as
  <FILL>, service files reference ${{shared.X}}; all three service files pass check_prod_env as
  generated; the VM file passes with dummy secrets. Generator: session scratchpad gen_railway_env.py.
- Founder chose Clerk PRODUCTION; JWKS/issuer assumed https://clerk.cluehq.ai (verify in Clerk).
- Lane .env differs from example: ARV2 discovery ON and Langfuse US host — carried into production.

### 2026-10-03 — backend image never built (skia from source)
- Release PR #84 merged 2026-10-02 before CI finished; both deploy-images runs (37033670590 PR,
  37033905636 push main) failed in `Backend image`: rust-skia 0.97.2 has no prebuilt Skia for our
  feature set (textlayout+svg+webp, no vulkan) on Linux x86_64 or aarch64 → 404 → full source
  build → `ninja` missing. First CI build of the image ever; deterministic, a rerun cannot help.
  Railway platform-api/design-api build the same Dockerfile → same failure. No tag moved.
- Fix (branch deploy/skia-build-deps): helper stage COPYs subsystems/clue-design/fonts (lumen-skia
  include_bytes! the Inter faces — the second failure, found by the local build) and installs clang, libclang-dev, ninja-build,
  libfontconfig1-dev. Cold build +15–25 min; CI caches the layer (gha), Railway builds it per service.
  Rejected: adding `vulkan` to match a prebuilt (changes the engine's pinned features for packaging).
  Follow-up idea: Railway pulls the CI-built GHCR image instead of building (one Skia compile).

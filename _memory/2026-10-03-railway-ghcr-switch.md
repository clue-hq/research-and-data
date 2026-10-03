# 2026-10-03 — Railway backends switched to the CI-built GHCR image

- `railway service source connect --image ghcr.io/clue-hq/clue-backend:production` for platform-api
  and design-api (production env of remarkable-vibrancy; founder-approved). Before: both repo
  `clue-hq/research-and-data` (branch main). Revert: `railway service source connect --repo
  clue-hq/research-and-data --branch main --service <s>`.
- The switch triggered one deploy each (fe05c56c…, 6830d859…) → FAILED: the `production` tag does not
  exist yet and Registry Credentials are not set. Expected; nothing had ever run.
- Settings verified from the deployment manifest (`railway deployment list --json` → meta.serviceManifest
  .deploy — `railway status --json` does NOT show these fields, which made them look unset):
  platform-api start `clue platform-api`, preDeploy `clue migrate`, health `/healthz`; design-api start
  `clue design-api`, health `/healthz`; page-origin health `/healthz`. All ON_FAILURE, 1 replica.
- DONE 2026-10-03 (founder): GitHub classic PAT (read:packages) in each service's Settings → Source →
  Registry Credentials; Railway project token (production) as GitHub secret RAILWAY_TOKEN. Then the
  release PR to main; its deploy-images run moves the tags and runs deploy/railway_redeploy.sh.
- Frontend: 11 staged changes in the Railway UI — do not apply until the backends are healthy.

## 2026-10-03 ~08:25 UTC — first production deploy LIVE (Railway web tier)
- Release #86 merge run: all checks green, `production` tags moved; its Railway redeploy step then hit
  two production startup refusals, fixed as Railway variables (no rebuild):
  1. Settings: production requires `CLUE_METRICS_EXPORTER=otlp` + endpoint (rule from 2026-08-15,
     predates the 2026-09-14 telemetry spec that deferred the Grafana stack). Founder chose Grafana
     Cloud (stack curiousferret2524, instance 1853757, us-east-3): shared vars
     CLUE_METRICS_EXPORTER=otlp, CLUE_METRICS_OTLP_ENDPOINT=…/otlp/v1/metrics,
     OTEL_EXPORTER_OTLP_METRICS_HEADERS=Authorization=Basic%20<b64> (metrics-only header). The first
     token was pasted in chat → founder told to revoke/regenerate.
  2. Startup: Sumble account-gap enrichment on without CLUE_SUMBLE_API_KEY. Founder: Sumble OFF in
     production — CLUE_SUMBLE_{ACCOUNT,DISCOVERY}_GAP_ENRICHMENT_ENABLED=false on platform-api + design-api
     (VM env needs the same).
- Method that ended the one-refusal-per-deploy loop: scratchpad prod_boot_check.sh — `railway run`
  injects a service's real variables into a local `docker run` of the image, overriding only DB/Redis
  (throwaway) and Sentry/Langfuse off; values never printed. Both services booted clean before redeploy.
- Redeployed in order with deploy/railway_redeploy.sh: platform-api 891f8b41 (migrated), design-api
  2a193823, page-origin 50c1752e — all SUCCESS. api.cluehq.ai/healthz 200 (edge needed ~1 min after
  deploy), page-origin.cluehq.ai/healthz 200.
- Frontend: staged settings applied by founder; build failed (Railpack, "no start command") because
  RAILWAY_DOCKERFILE_PATH=/apps/frontend/Dockerfile.railway had been dropped — restored; deployment
  0e6a0ed2 live. app.cluehq.ai → /onboarding/sign-in, Clerk from clerk.cluehq.ai (production).
  Its CLUE_API_BASE_URL is the private http://platform-api.railway.internal:8020 (works; differs from
  the runbook's public URL).
- Owed: runbook §2 step 7 must list RAILWAY_DOCKERFILE_PATH; check_prod_env must know the metrics and
  Sumble rules; push branch deploy/page-origin-after-migrate; VM (§4) not started; founder sign-in walk.

## 2026-10-03 ~09:30 UTC — VM live; onboarding findings
- VM (OVH, 40.160.37.148): bootstrap needed a fix (UID 1000 is `ubuntu` on OVH's image → clue is
  1001; PR #87). Env files filled from Railway by a script (no values printed), boot-checked locally
  per pool, installed 0600; `deploy.sh 0f362f9f8…` → pgbouncer, chat, design, batch1-3, ingestion up.
- Onboarding jobs queued at 08:30 were picked up at 09:04 (no workers before). Website brand kit:
  ~17 min of work, ~7.5 of it the brand brief (x-ai/grok-4.7, medium reasoning, screenshots,
  ToolStrategy re-asks) — knobs LUMEN_INGESTION_BRIEF_MODEL / _REASONING.
- ad_assets job FAILED: Adyntel HTTP 402 "Insufficient tokens" → founder to top up, then Try again.
  The setup screen keeps spinning "Creating brand kit" on a failed ad_assets job (UI gap: should show
  "hit a problem" like the research steps).
- Sentry 7770166418: agent turns (onboarding ICP step; also chat turns and design jobs) failed —
  LangGraph saver.setup() runs CREATE TABLE IF NOT EXISTS in public as clue_worker → permission
  denied. FIX A (applied 09:3x, founder-approved): `GRANT CREATE ON SCHEMA public TO clue_worker`;
  setup() run once as clue_worker (async + sync savers) → checkpoint tables exist, migration v9.
- TODO B (follow-up PR): create the LangGraph checkpoint tables in an Alembic migration (owner), make
  agent_execution_wiring / entity_research_runtime_wiring / lumen_api.fleet_handler skip setup() when
  checkpoint_migrations is current, then `REVOKE CREATE ON SCHEMA public FROM clue_worker`.
- TODO: ingestion pool installs no Sentry/OTel/Langfuse (lumen_api.ingestion_pool main() only calls
  setup()); its spend IS on provider_call_ledger. Add the production installers (service
  clue-ingestion-pool).
- Langfuse MCP in this workspace is attached to the DEV project (lane environments), not production.

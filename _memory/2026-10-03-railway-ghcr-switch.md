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

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

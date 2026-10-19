# 2026-10-19 — cluehq.page launch readiness (runbook §9), read-only checks

- Railway prod (project 60353f67…): services design-api, frontend, page-origin, platform-api, Postgres,
  Redis — **no `site-editor` service**. Step-5 settings present on all four; branch
  `deploy/check_prod_env.py` passes platform-api / page-origin / frontend, now and with the release-day
  suffix. **design-api FAILS: `CLUE_SITE_SECTION_LINK_SECRET` not set** — the new design API refuses to
  start without it (S7-4), so it must be added before PR #128 merges.
- VM `/srv/clue/env`: legacy suffix, CNAME target, `LUMEN_SITE_LIVE_WORKSPACES=*` in; checker (role
  worker, piped over SSH) OK now and with `CLUE_PAGES_SYSTEM_SUFFIX=cluehq.page`. VM runs main bb70d80
  (CI VM deploy works).
- DNS: `cluehq.page` apex + wildcard proxied through Cloudflare; Railway answers "Application not
  found" (no Worker yet — expected). `deeppresence.ai` has no records. Registrations: cluehq.page to
  2028-10-15, deeppresence.ai to 2028-01-09, both on Cloudflare NS.
- Cloudflare for SaaS (read with the token stored on platform-api): fallback origin `cluehq.page`
  active, 0 custom hostnames, token active, zone id in Railway is cluehq.page's.
- Merging into main IS the deploy (deploy-images.yml: build → boot smoke → `production` tags → Railway
  redeploys platform-api, design-api, page-origin → VM). The 5 pre-existing mypy errors fail `check`
  but do not gate it. Site editor Dockerfile is not on main yet.

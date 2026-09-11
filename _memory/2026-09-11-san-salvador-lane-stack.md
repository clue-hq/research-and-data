# 2026-09-11 — the san-salvador lane's dev stack (for the founder's manual ARV2 testing)

Branch `track-r4` (O6 + R1–R4 + the D4-b relift), worktree `san-salvador`, DB `clue_san-salvador`
on :55040 at alembic head `2cd622be2da0`. The founder asked for the frontend, the platform API, the
design API and four to five fleet workers with per-worker concurrency, to test every ARV2 feature by
hand, and said the other workspaces' instances could be paused.

## What runs, and how it is started

`./scripts/dev_stack_san_salvador.sh up|down|status` — a wrapper that sets the new `DEV_STACK_*`
knobs and execs the runbook script. **Same ports and login as `DEV_STACK.md`**: frontend
`http://localhost:3020`, design API 8010, platform API 8020 (+ the 8030 twin), four
`clue_api.fleet_main` processes at `CLUE_FLEET_WORKER_CONCURRENCY=3` (the O6 exit-gate ruling:
four processes × three slots). Logs: `/tmp/san-salvador_{design_api,platform_api_8020,platform_api,
fleet_worker,fleet_worker_2..4,frontend}.log`. Agent workspace root
`/private/tmp/clue-agent-workspaces-san-salvador`.

`scripts/dev_stack.sh` gained five env knobs with defaults equal to its previous hard-coded values
(`DEV_STACK_DB_URL`, `DEV_STACK_WORKERS`, `DEV_STACK_WORKER_CONCURRENCY`,
`DEV_STACK_AGENT_WORKSPACE_ROOT`, `DEV_STACK_LOG_PREFIX`), a 6-second stagger between worker
launches, and a macOS-safe worker count in `status` (`pgrep -c` does not exist here). The istanbul
checkout's behaviour is unchanged. `DEV_STACK.md` carries the new section.

Machine-local settings changed for this (all git-ignored): `.env` →
`LUMEN_API_ORIGIN` and `CLUE_DESIGN_API_BASE_URL` to `127.0.0.1:8010`, `LUMEN_API_CORS_ORIGINS`
gains 3020; `apps/frontend/.env.local` → `CLUE_API_BASE_URL=8020`, `LUMEN_API_BASE_URL=8010`,
`CLUE_APP_ORIGIN=http://localhost:3020` (it had been a copy of colombo's 8052/8060/3033).
`CLUE_AUTH_CLERK_AUTHORIZED_PARTIES` already contained 3020. `.env.example` untouched (ports and
origins are deployment-specific; the `CLUE_FLEET_WORKER_CONCURRENCY` default stays 1 — the 3 is a
per-process env set by the script, like its DB override).

Prerequisites built in this worktree for the first time: `apps/frontend` `npm install` +
`design-system:build`; `cargo build -p lumen-api-helper --release` (the other worktrees' binaries
were NOT reusable — `lumen-web` differs from both colombo and istanbul); the vendored
`apps/frontend/public/vendor/tailwind-browser.js` copied from istanbul (git-ignored). Playwright
1.61 with chromium 1228/1234 already present in the shared cache.

## Other stacks stopped (founder: "you may pause the other workspace's instances")

Checked in-flight work first: semarang and colombo had nothing running; istanbul's `clue` DB shows
`design_agent_run running 4 / queued 44` but its worker was driving `clue_istanbul_dev` (the
script's override), which had one queued task only — stale rows, nothing was being driven. Killed by
pid: istanbul (3020/8010/8020/8030 + worker), colombo (3033/8052/8060 + worker), semarang
(3040/8070 + four workers). **Left running:** the port-of-spain dummy frontend on :3000 (the
presentation-truth reference). To bring istanbul back, `down` this lane first — same ports.

## Verification

`status` → all four ports UP, `fleet-worker: UP (4 process(es), 3 slot(s) each)`; each worker log
shows three `worker.slot_start` and zero tracebacks; `fs_root` = this checkout's `.artifacts`;
`GET :8020/auth/v1/session` → 401 (auth surface alive); `GET :8010/openapi.json` → 200;
`GET :3020/` and `/sign-in` → 307 (Clerk redirect, expected before sign-in); no "address already
in use" in any log. The browser walk (sign in → workspace → project → "ping") is the founder's.

## Finding worth a follow-up (not fixed — live run first)

**Fleet worker boot seeds the field registry with plain INSERTs and is not concurrency-safe.** Four
workers started together: three died at boot on
`asyncpg.exceptions.UniqueViolationError: duplicate key value violates unique constraint
"field_definition_pkey"` (the `core.account_name` seed row), the fourth won and ran. Reproducible
on any fresh multi-worker start; the semarang stack never hit it because its workers were started
by hand, one after another. The stagger in the script is the mitigation; the seed should become
`INSERT … ON CONFLICT DO NOTHING` (or take an advisory lock) — owner: whoever next touches the
field-registry seeding in `clue_api` worker wiring.

## Not confirmed here

The worker log does not list its registered kinds, so "the `arv2_discovery` handler is composed in
these four processes" rests on `CLUE_ARV2_DISCOVERY_ENABLED=true` in `.env` and the offline fleet
wiring tests, not on a live line. The first discovery launch (`scripts/launch_arv2_discovery.py`)
proves it.

## Addendum — .env parity and the provisioning flag (founder, 2026-09-11)

First browser walk hit `Provisioning failed with status 404` on the Welcome screen: the Clerk dev
user has no membership in `clue_san-salvador`, the frontend posts to `/auth/v1/provision`, and that
route is mounted only under `CLUE_SELF_SERVE_PROVISIONING_ENABLED`, which was **absent** from the
lane `.env` (default false). Founder ruling: bring `.env` to full parity with `.env.example` and
set `CLUE_SELF_SERVE_PROVISIONING_ENABLED=true` for this lane.

- 33 keys were missing from the lane `.env` (it had only ever served CLI-driven live runs), among
  them `CLUE_FRONTEND_READ_ENABLED` (default false → every `/frontend/v1` accounts read 404'd),
  `CLUE_MEMORY_ENABLED`, `CLUE_ONBOARDING_V2_ENABLED`, the `CLUE_ARV2_FIT_*` thresholds and the
  `CLUE_ARV2_DISPLAY_*` block. All appended at the example's values in a dated block at the end of
  `.env`; the provisioning flag alone set `true`. Parity now 207 = 207 keys, no extras, no
  duplicates. `.env.example` untouched — its posture line stays `false` (standing checklist item 7
  / master plan §11); the lane's `true` is a local testing choice, not a default change.
- **Pitfall in the parity check:** `grep -oE '^[A-Z_]+='` silently drops every key with a digit
  (`…_V2_…`, `…_C7_…`, `…_ARV2_…`) — use `[A-Z0-9_]+`. The first pass reported 0 missing while ten
  keys were still absent.
- With the flag on, the API process composes the old Stage-0 scrape binder and recon (sync LLM
  calls on the web loop — the CLAUDE.md backlog bullet), and the worker composes the recon handler
  and the official-site crawl enqueuer. That is the old lane's onboarding, on only so a browser
  user can mint a workspace; the new onboarding lane stays behind `CLUE_ONBOARDING_V2_ENABLED=false`.
- Every process reads `.env`, so the whole stack was restarted through the wrapper.

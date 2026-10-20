# CRM integration — Phase 1 (reads) progress, 2026-10-20

Branch `feat/crm-integration` (cut from origin/main f05373d59; upstream unset — never push).
Docs module: `docs/superpowers/specs/crm-integration/` — `README.md` (index), `rulings.md`
(every founder decision, R-x.y), `status.md` (build status), the first-release design, and
`composio-api-notes.md` (verified Composio REST v3.1 shapes). Plan:
`docs/superpowers/plans/2026-10-20-crm-integration-phase-1-reads.md`.

## Done (committed)
- Task 0: Composio spike — notes file; HubSpot developer test account + Salesforce Developer
  Edition org connected via a Composio **dev** project (managed auth configs), seeded with the same
  story (20 companies `*.test`, 66 contacts `@*.example.com`, 36 deals: 14 won / 14 lost / 8 open,
  118 SF contact roles). Spike/seed scripts live only in the session scratchpad.
- Task 1 `be7883485` config; Task 2 `896280273` + fix `f17a3f254` migration `3b800d603402`
  (project/thread ids are TEXT); Task 3 `7d8e0863b` gateway (`clue_api.crm.composio_gateway`,
  REST over httpx, composio SDK forbidden by import-linter); Task 4 `072bc6806` connection store;
  Task 5 `61d95df2f` routes `/frontend/v1/crm/{connect-link,complete,connection}` + wake.

## Facts / decisions worth knowing
- Connect card is drawn from the `connect_crm` tool result (no agent gate) + `crm_connect_request`
  table (R-3.10). Callback page is a frontend route `/integrations/crm/callback?request=<id>`
  built from `CLUE_APP_ORIGIN`.
- Composio managed apps fix their scopes (dashboard trims don't stick); Salesforce subdomain
  `login` works; expired connection = HTTP 410 slug `ActionExecute_ConnectedAccountExpired`.
- Test DB: `clue_nashville_crm_test` (localhost:55040) — swap the db name in the .env DSN.
- Pre-existing on main, not ours: import contract "agents import only the toolbelt facade +
  projections" broken by `clue_agents.compaction_config -> clue_gateway.model_windows`.
- Dev `.env`: `CLUE_SANDBOX_MAX_RUNS_PER_TURN=75` (R-3.13; example/code default stay 10).
- The founder's Composio dev API key was printed once in a tool output (failed masking);
  founder advised to rotate it.

## Next
Task 6 (frontend connect card + callback page; show founder a preview, non-blocking), Tasks 7–11,
then Task 12 founder test on the local stack (gate before Phase 2), then deploy reads (R-2.4).

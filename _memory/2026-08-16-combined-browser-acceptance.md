# Combined browser acceptance

Date: 2026-08-16
Branch: `platform/integration-onboarding-pilot`
Status: in progress; browser handoff required before the first UI action

## Isolated runtime

- Fresh PostgreSQL database: `clue_combined_browser_20260816_c1`.
- Fresh durable artifact root: `/private/tmp/clue-combined-browser-20260816-c1`.
- Separate agent-workspace root:
  `/private/tmp/clue-combined-browser-agent-20260816-c1`.
- Database is at sole Alembic head `f85ca69b93ba` and remains zero-state: zero platform users,
  workspaces, and projects.
- The merged API is running on `127.0.0.1:8000` with real Clerk authentication, self-serve
  provisioning, frontend reads, chat, C7 reads/snapshots/evidence/handoff, filesystem storage, and
  pilot budget controls off. It authorizes the existing localhost Clerk origin and the isolated
  `3077` origin.
- The merged frontend is running on `127.0.0.1:3077` with its authenticated same-origin BFF.
- The fleet is intentionally not started yet. The browser must first provision the random fresh
  workspace and enqueue setup; the worker can then be started with that exact workspace in both
  the official-site crawl and agent-runtime allowlists.

## Browser blocker

- The in-app Browser connected successfully and its first request reached the frontend/API, but
  the first frontend process had an incorrectly overridden cross-origin project-chat URL. The
  process was restarted with the repository's required `/api/clue` same-origin value.
- On the corrected stack, the in-app Browser refused both reload and DOM inspection of the
  localhost tab under its URL safety policy. Per the Browser skill, no other browser surface,
  raw protocol, indirect navigation, or automation workaround was used.
- Resume condition: the user opens `http://localhost:3077` in the in-app Browser, then the agent
  claims that exact tab and continues the requested browser -> API -> PostgreSQL matrix.

## Local rendering diagnosis

- The user-opened in-app tab first exposed a complete `/onboarding/profile` accessibility tree,
  while the isolated database remained zero-state. The initial root request took 5.4 seconds:
  3.9 seconds in Next development compilation and about 1.5 seconds in proxy/application work.
- The same Turbopack dev process then became genuinely unresponsive: direct probes to both `/` and
  `/onboarding/profile` timed out after 15 seconds with zero response bytes even though the Node
  listener remained open. The user's screenshot correctly showed a blank navigation, not merely a
  slow rendered page.
- Restarted only the disposable frontend with Next 16 webpack. Direct route probes then passed:
  root returned its expected redirect in 2.6-2.9 seconds, and the onboarding profile returned 200
  in 1.7-2.4 seconds. API, database, and fleet state were not the cause of the blank page.
- Computer Use could not attach to the running Google Chrome application after three attempts.
  The dedicated Chrome browser-control path did reach the webpack server—the server completed root
  and profile responses—but the control operation itself remained pending for 45 seconds. This is
  evidence of a browser-control/extension-side hang after a healthy server response; it is not a
  completed visual Chrome acceptance.
- The first real profile submission was correctly rejected by the frontend CSRF boundary with
  `origin_forbidden`: the disposable frontend listened on `localhost:3077` while `clueAppOrigin()`
  retained its development default `http://localhost:3000`. The backend and provisioning route were
  never reached. Restarted the webpack frontend with exact `CLUE_APP_ORIGIN=http://localhost:3077`
  and matching Clerk authorized parties; source files were not changed.

## Acceptance still outstanding

All requested scenarios remain unclaimed until browser control resumes: Clerk provisioning,
automatic fast release, same-frontier completion, Client-KB and product context, ICP revision and
approval, FI-2 selected-account launch, budget controls in both modes, per-project product
selection, replay/DSAR/historical receipts, and design-integration exclusion.

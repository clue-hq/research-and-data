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

## Acceptance still outstanding

All requested scenarios remain unclaimed until browser control resumes: Clerk provisioning,
automatic fast release, same-frontier completion, Client-KB and product context, ICP revision and
approval, FI-2 selected-account launch, budget controls in both modes, per-project product
selection, replay/DSAR/historical receipts, and design-integration exclusion.

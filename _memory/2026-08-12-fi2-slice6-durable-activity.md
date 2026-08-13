# 2026-08-12 — FI-2 Slice 6 durable Account activity

Branch: `platform/fi2-accounts-cutover` in the Monterrey worktree.

## Contract and implementation

- Added `GET /frontend/v1/accounts/{accountId}/activity` under the existing authenticated
  frontend-read router. It reads the append-only `research_subject_activity` ledger and inner-joins
  the exact `research_view_event`, `project`, `project_run`, and `account_run`. The join requires
  workspace, Account, run, event-kind, owner-reference, and timestamp agreement.
- The response contains safe machine values only: durable id/kind/time, non-human actor category,
  governed Account/Contact subject, project name/id, project/account run ids, and a subject-specific
  drill-down containing event/snapshot/optional-report plus section/item ids. Internal `fetch_ref`
  and event bodies never cross.
- Human activity is omitted because the durable activity row currently has only the category and no
  resolvable principal id. System/agent/worker are explicit non-human attributions. Unknown kinds,
  broken references and Contacts outside the governed Account committee/project selection are
  omitted rather than synthesized.
- `state.committeeCount` is `len(read_account_detail(...).committee)` and `state.summary` is the same
  typed `ProseRead` returned by Account detail. The frontend links those states to Contacts and
  Account Overview. Account activity links to Insights, Contact activity links to the governed
  Contact profile, and project context links to the project route.
- Removed Activity from the empty legacy Account-workspace model. The dedicated Zod model and HTTP
  repository always use the authenticated live read seam. Display mappings stay frontend-side and
  timestamps render as absolute UTC `<time>` values.
- Updated `apps/frontend/docs/api-contracts/accounts.md` and closed LF-ACTIVITY-001 in the local
  `.context/defect-log.md`.

## Verification

- Isolated DB `fi2_activity_monterrey` on local port 5432 was created and migrated to head.
- `tests/api/test_frontend_read_account_activity.py`: 2/2 passed against real Postgres. It verifies
  exact source rows, newest-first/reload-stable timestamps, shared Account-detail state,
  project/run refs, cross-workspace 404, unresolved-reference omission, human-without-principal and
  ungoverned-Contact omission, governed Contact events, and honest empty events.
- Adjacent frontend-read API group: 57 passed (`test_frontend_read_app`, Account detail, Activity).
- Frontend: 167 tests passed; ESLint passed; design-system token build passed; webpack production
  build compiled, type-checked and generated all routes. The default Turbopack build reproduced the
  existing LF-BUILD-001 compile stall and was stopped cleanly.
- Repository `make check`: ruff format/check, mypy (634 files), and all 25 import contracts passed.
  Pytest completed with 2,392 passed / 2,026 skipped / 5 unrelated known failures: the existing
  Stage-0 resource-version assertion, three stale shared-DB pilot tests (`research_scope` absent),
  and the design-subsystem logging scan. No failing file overlaps Slice 6.

## Authenticated browser acceptance

- Reused dedicated DB `clue_monterrey_fi2_slice5_20260812` and added three idempotent append-only
  acceptance events through `.context/lane-f-e2e/fi2-slice6-browser-events.sql`. API ran from this
  worktree on port 8000; frontend ran on 3077 with the existing authenticated Clerk session.
- Eventful Account `fda8f410-015b-45e6-a5cc-4d9b6a9dc027` rendered Account/Contact/Account events at
  10:45/10:15/09:15 UTC, preserved that ordering across reload, had no relative “1 hour ago” copy,
  and matched database ids, timestamps, subjects, project, event, snapshot, project-run and
  account-run rows. The Contact event identified Dana Buyer and its link opened her live profile.
- Activity's three contacts matched the three Contacts grid rows. “Summary not composed” linked to
  Overview, which rendered “No written account summary has been composed yet.” The event link
  resolved to Insights and the project link resolved to the real Contacts project A workspace.
- Empty Account `a4a82a82-fbda-470d-9ad6-50ebbe754d51` had zero activity rows and rendered “No
  durable activity exists for this account yet” identically across reloads.
- Browser diagnostics after the clean server restart had no application errors; only normal dev/HMR
  and Clerk development-key warnings remained. API logs showed authenticated session/principal plus
  `200` Account and Activity reads.

No remote push was performed.

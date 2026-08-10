# 2026-08-10 — R4 Home and project-route integration

## Scope

- Implemented repair Slice R4 only on `platform/lane-d-chat-launch`.
- Preserved `.artifacts/` and did not begin R5.
- Reused the R2 backend `GET /api/v1/home` and atomic `POST /api/v1/projects`
  surfaces. No backend source change was needed because those routes already own
  tenant scoping, typed refusals, request validation, atomic creation, and
  idempotent replay.

## Decisions and changes

- Added a strict frontend bootstrap-request schema for brand, exact message
  bytes, ordered context references, durable attachment receipts, and optional
  agent profile. The repository validates this shape before translating it to
  the snake-case HTTP wire contract.
- Added a transport-independent Home submission coordinator. One exact draft
  may have only one request in flight; an unchanged failed draft reuses its
  idempotency key; a message or brand edit rotates the retry identity; and only
  the latest accepted act may navigate after concurrent completions.
- Home now validates locally, clears only the successfully submitted current
  draft, and navigates solely with the backend-returned `href`. It never builds
  project/thread ids or prompt/model/phase query parameters.
- Kept the composer editable while a different draft is in flight and disabled
  only submission of the exact in-flight draft. Both click and Enter paths
  enforce that duplicate guard.
- Resolved a requested thread exclusively against the project-scoped thread
  page. A foreign or stale thread id is never fetched: the controller selects an
  allowed thread and canonicalizes the URL, or renders a controlled unavailable
  state if no allowed thread exists. Thread creation/selection also updates the
  canonical route.
- Recorded R4 as implemented in
  `apps/frontend/docs/api-contracts/projects.md`.

## Verification

- `npm run lint` — pass.
- `npx tsc --noEmit` — pass.
- `npm run design-system:build` — pass.
- `npm test` — 123 passed, 0 failed/skipped. New coverage includes local request
  validation, retry-key lifecycle, exact-draft concurrency, latest-navigation
  ownership, typed HTTP refusal without fixture fallback, and cross-project
  thread-route resolution.
- Focused database-backed backend regression suite — 35 passed:
  thread shell, Home bootstrap, project/sidebar reads, chat-thread surface,
  turn submission, and auth policy.
- In-app browser:
  - Navigating project `prj_dc6c73c46703531791bcd5188473ad42` with foreign
    thread `thr_4afa9d5342395e579ee873d356cfdc60` canonicalized to the allowed
    `thr_dae5bcbcf50b564d90a3b94d27ddda6b`; no raw backend error or foreign
    transcript rendered.
  - Rapidly double-clicking Home Send for
    `R4 duplicate browser verification 0810-1742` navigated to
    `prj_c7e947de0e8455659e0423e6f36f119d?thread=thr_d41b6a0ec5d459b491c60f77fefc504b`
    with no prompt/model/phase parameters. The project title was `Untitled
    project`, the first-thread title matched the message, and Gallery was empty.
  - A read-only Postgres join found exactly one matching project/thread after
    the double click. Browser logs contained no application error (only the
    expected Clerk development-key warning and HMR messages).

## Runtime note

- The browser-created first turn remained `Queued` because this verification
  session was running the HTTP backend and frontend, not a fleet worker. R4
  proves the real atomic Home acceptance/navigation/read path; it does not
  expand into worker/runtime repair or R5.

## Closing state

- R4 implementation, verification, and this session note are included in the
  focused local commit `feat(chat): complete Home route integration`.
- No remote push was performed.
